"""ci.* adapter（ADR-0009）と scripts/collect_ci_facts.py の回帰。"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ratchet_gate.adapters import (
    CI_FACTS_SCHEMA,
    CiFacts,
    PinTaggedAdapter,
    ReleaseAssetLiveAdapter,
    ScanContext,
    SecretDeclaredAdapter,
)
from ai_ratchet_gate.adapters.ci_facts import (
    extract_asset_urls,
    extract_pins,
    extract_secret_names,
    referenced_asset_urls,
    required_secret_names,
)
from ai_ratchet_gate.cli import main as cli_main
from ai_ratchet_gate.engine import evaluate
from ai_ratchet_gate.model import RatchetError

ROOT = Path(__file__).resolve().parents[1]
ENFORCE = ROOT / "scripts" / "enforce_observe_evaluate.py"
COLLECT = ROOT / "scripts" / "collect_ci_facts.py"
TAGGED = "5b7c774deb8e9abcf0fce0c5f39ec1c1f3a894f3"
UNTAGGED = "44fdece1634d4afb355639ad465375dca5e5c868"
EXTERNAL = "3d3c42e5aac5ba805825da76410c181273ba90b1"
LIVE_URL = (
    "https://github.com/nexus-ai-2045/ai-ratchet-gate/releases/download/"
    "v0.2.0/ai_ratchet_gate-0.2.0-py3-none-any.whl"
)
DEAD_URL = (
    "https://github.com/nexus-ai-2045/ai-ratchet-gate/releases/download/"
    "v0.1.1/ai_ratchet_gate-0.1.1-py3-none-any.whl"
)


def _facts(**overrides: object) -> CiFacts:
    raw: dict[str, object] = {
        "schema": CI_FACTS_SCHEMA,
        "tagged_shas": [TAGGED],
        "live_release_assets": [LIVE_URL],
        "registered_secret_names": ["PRESENT_NAME"],
    }
    raw.update(overrides)
    return CiFacts.from_dict({key: value for key, value in raw.items() if value is not None})


def _workflow(root: Path, name: str, text: str) -> Path:
    path = root / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ids(adapter: object, root: Path) -> list[str]:
    observation = adapter.observe(ScanContext(root, "repo:test@x"))  # type: ignore[attr-defined]
    return [item.subject_key for item in observation.findings]


# --- 抽出 ---------------------------------------------------------------------


def test_extract_pins_counts_own_pins_and_skips_external_actions() -> None:
    text = (
        f"    uses: nexus-ai-2045/repo-preflight/.github/workflows/g.yml@{TAGGED} # v\n"
        f"      preflight-ref: {UNTAGGED}\n"
        f"      - uses: actions/checkout@{EXTERNAL} # v7\n"
        f"      before: {'0' * 40}\n"
        f"      sha256: {'a' * 64}\n"
    )
    assert extract_pins(text) == (TAGGED, UNTAGGED)


def test_extract_pins_owner_match_is_case_insensitive() -> None:
    text = f"uses: Nexus-AI-2045/repo-preflight@{UNTAGGED}\n"
    assert extract_pins(text) == (UNTAGGED,)


def test_extract_asset_urls_drops_fragment_and_variables() -> None:
    text = (
        f"pip install '{DEAD_URL}#sha256={'b' * 64}'\n"
        "curl -L https://github.com/o/r/releases/download/v${V}/x.tgz\n"
        f"see ({LIVE_URL}).\n"
    )
    assert extract_asset_urls(text) == (DEAD_URL, LIVE_URL)


def test_extract_secret_names_uppercases_and_skips_builtin_and_caller_provided() -> None:
    text = (
        "on:\n"
        "  workflow_call:\n"
        "    inputs:\n"
        "      x:\n"
        "        type: string\n"
        "    secrets:\n"
        "      passed_in:\n"
        "        required: false\n"
        "jobs:\n"
        "  a:\n"
        "    steps:\n"
        "      - env:\n"
        "          A: ${{ secrets.GITHUB_TOKEN }}\n"
        "          B: ${{ secrets.passed_in }}\n"
        "          C: ${{ secrets.needed_one }}\n"
        "          D: ${{ secrets['OTHER_NAME'] }}\n"
    )
    assert extract_secret_names(text) == ("NEEDED_ONE", "OTHER_NAME")


# --- adapter ------------------------------------------------------------------


def test_pin_tagged_finds_untagged_pin_only(tmp_path: Path) -> None:
    _workflow(
        tmp_path,
        "preflight.yml",
        f"uses: nexus-ai-2045/repo-preflight/x.yml@{TAGGED}\npreflight-ref: {UNTAGGED}\n"
        f"uses: actions/checkout@{EXTERNAL}\n",
    )
    assert _ids(PinTaggedAdapter(_facts()), tmp_path) == [
        f".github/workflows/preflight.yml@{UNTAGGED}"
    ]


def test_release_asset_live_finds_dead_url_in_ci_and_pyproject(tmp_path: Path) -> None:
    _workflow(tmp_path, "ci.yml", f"run: pip install {DEAD_URL}\nrun: pip install {LIVE_URL}\n")
    (tmp_path / "pyproject.toml").write_text(f'x = "{DEAD_URL}"\n', encoding="utf-8")
    keys = _ids(ReleaseAssetLiveAdapter(_facts()), tmp_path)
    assert len(keys) == 2
    assert {key.split("#", 1)[0] for key in keys} == {".github/workflows/ci.yml", "pyproject.toml"}


def test_secret_declared_finds_unregistered_name_only(tmp_path: Path) -> None:
    _workflow(
        tmp_path,
        "a.yml",
        "x: ${{ secrets.PRESENT_NAME }}\ny: ${{ secrets.MISSING_NAME }}\n",
    )
    _workflow(tmp_path, "b.yml", "z: ${{ secrets.missing_name }}\n")
    assert _ids(SecretDeclaredAdapter(_facts()), tmp_path) == ["secret:MISSING_NAME"]


def test_no_github_dir_means_zero_findings(tmp_path: Path) -> None:
    for adapter in (
        PinTaggedAdapter(_facts()),
        ReleaseAssetLiveAdapter(_facts()),
        SecretDeclaredAdapter(_facts()),
    ):
        assert _ids(adapter, tmp_path) == []


def test_finding_identity_is_stable_when_lines_move(tmp_path: Path) -> None:
    path = _workflow(tmp_path, "p.yml", f"ref: {UNTAGGED}\n")
    first = PinTaggedAdapter(_facts()).observe(ScanContext(tmp_path, "s")).findings
    path.write_text(f"# 上に行を足す\n\nref: {UNTAGGED}\n", encoding="utf-8")
    second = PinTaggedAdapter(_facts()).observe(ScanContext(tmp_path, "s")).findings
    assert [f.finding_id for f in first] == [f.finding_id for f in second]


def test_ratchet_denies_new_untagged_pin_against_zero_baseline(tmp_path: Path) -> None:
    _workflow(tmp_path, "p.yml", f"ref: {UNTAGGED}\n")
    observation = PinTaggedAdapter(_facts()).observe(ScanContext(tmp_path, "s"))
    decision = evaluate(observation, [], mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert len(decision.new) == 1


# --- fail-closed ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "missing"),
    [
        (PinTaggedAdapter, "tagged_shas"),
        (ReleaseAssetLiveAdapter, "live_release_assets"),
        (SecretDeclaredAdapter, "registered_secret_names"),
    ],
)
def test_missing_fact_is_fail_closed(factory: type, missing: str) -> None:
    with pytest.raises(RatchetError, match=f"ci_facts_missing_{missing}"):
        factory(_facts(**{missing: None}))
    with pytest.raises(RatchetError, match="ci_facts_required"):
        factory(None)


@pytest.mark.parametrize(
    "raw",
    [
        {"schema": "other"},
        {"schema": CI_FACTS_SCHEMA, "unknown": []},
        {"schema": CI_FACTS_SCHEMA, "tagged_shas": ["ABC"]},
        {"schema": CI_FACTS_SCHEMA, "tagged_shas": "not-a-list"},
        {"schema": CI_FACTS_SCHEMA, "live_release_assets": ["http://example.com/x"]},
        {"schema": CI_FACTS_SCHEMA, "registered_secret_names": ["lower"]},
        [],
    ],
)
def test_invalid_facts_rejected(raw: object) -> None:
    with pytest.raises(RatchetError):
        CiFacts.from_dict(raw)


def test_symlink_in_ci_dir_is_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "outside.yml"
    target.write_text(f"ref: {UNTAGGED}\n", encoding="utf-8")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    try:
        (workflows / "link.yml").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("この環境ではsymlinkを作れない")
    with pytest.raises(RatchetError, match="ci_path_is_symlink"):
        PinTaggedAdapter(_facts()).observe(ScanContext(tmp_path, "s"))


def test_non_utf8_ci_file_is_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / ".github" / "workflows" / "bad.yml"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe x")
    with pytest.raises(RatchetError, match="ci_file_not_utf8"):
        SecretDeclaredAdapter(_facts()).observe(ScanContext(tmp_path, "s"))


# --- CI / enforce 接続 ----------------------------------------------------------


def _write_facts(path: Path, **overrides: object) -> Path:
    raw: dict[str, object] = {
        "schema": CI_FACTS_SCHEMA,
        "tagged_shas": [TAGGED],
        "live_release_assets": [],
        "registered_secret_names": [],
    }
    raw.update(overrides)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_cli_observe_requires_facts_for_ci_adapter(tmp_path: Path, capsys) -> None:
    code = cli_main(
        ["observe", "--repo", str(tmp_path), "--adapter", "ci.pin_tagged", "--subject", "s"]
    )
    assert code == 2
    assert "ci_facts_required" in capsys.readouterr().out


def test_cli_observe_rejects_facts_for_existing_adapter(tmp_path: Path, capsys) -> None:
    facts = _write_facts(tmp_path / "facts.json")
    repo = tmp_path / "repo"
    repo.mkdir()
    code = cli_main(
        [
            "observe", "--repo", str(repo), "--adapter", "test.disable",
            "--subject", "s", "--facts", str(facts),
        ]
    )
    assert code == 2
    assert "facts_not_applicable" in capsys.readouterr().out


def _seed(path: Path, adapter_id: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": adapter_id,
                "adapter_version": "1",
                "subject": "repo:nexus-ai-2045/ai-ratchet-gate@ENFORCEMENT_BINDS_SUBJECT",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _enforce(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ENFORCE), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_enforce_denies_new_untagged_pin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _workflow(repo, "p.yml", f"ref: {UNTAGGED}\n")
    seed = _seed(tmp_path / "seed.json", "ci.pin_tagged")
    facts = _write_facts(tmp_path / "facts.json")
    result = _enforce(
        "--repo", str(repo), "--adapter", "ci.pin_tagged", "--baseline", str(seed),
        "--facts", str(facts), "--subject", "repo:test@x",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["decision"]["status"] == "deny"


def test_enforce_allows_tagged_pin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _workflow(repo, "p.yml", f"ref: {TAGGED}\n")
    seed = _seed(tmp_path / "seed.json", "ci.pin_tagged")
    facts = _write_facts(tmp_path / "facts.json")
    result = _enforce(
        "--repo", str(repo), "--adapter", "ci.pin_tagged", "--baseline", str(seed),
        "--facts", str(facts), "--subject", "repo:test@x",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_enforce_requires_facts_for_ci_adapter(tmp_path: Path) -> None:
    seed = _seed(tmp_path / "seed.json", "ci.secret_declared")
    result = _enforce(
        "--repo", str(tmp_path), "--adapter", "ci.secret_declared",
        "--baseline", str(seed), "--subject", "repo:test@x",
    )
    assert result.returncode == 2
    assert "--facts" in result.stderr


@pytest.mark.parametrize(
    "adapter_id", ["ci.pin_tagged", "ci.release_asset_live", "ci.secret_declared"]
)
def test_repo_seed_is_zero_baseline(adapter_id: str) -> None:
    seed = json.loads(
        (ROOT / ".ai-ratchet-gate" / "baselines" / f"{adapter_id}.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert seed["adapter_id"] == adapter_id
    assert seed["policy"] == "new_only"
    assert seed["finding_ids"] == []


def test_ci_workflow_enforces_all_six_adapters() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for adapter_id in (
        "git.tracked_ignored", "skills.provenance", "test.disable",
        "ci.pin_tagged", "ci.release_asset_live", "ci.secret_declared",
    ):
        assert f"--adapter {adapter_id} " in text
    assert "scripts/collect_ci_facts.py" in text


# --- collector（ネットワークを使わない部分） ----------------------------------


def _load_collector():
    spec = importlib.util.spec_from_file_location("collect_ci_facts", COLLECT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_ls_remote_tags_prefers_peeled_commit() -> None:
    collector = _load_collector()
    text = (
        f"{'1' * 40}\trefs/tags/v1\n"
        f"{TAGGED}\trefs/tags/v1^{{}}\n"
        f"{'2' * 40}\trefs/tags/light\n"
        f"{'3' * 40}\trefs/heads/main\n"
    )
    assert collector.parse_ls_remote_tags(text) == {TAGGED, "2" * 40}


def test_collect_omits_secret_names_when_needed_but_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = _load_collector()
    monkeypatch.setattr(collector, "tagged_shas", lambda repos: [TAGGED])
    _workflow(tmp_path, "a.yml", "x: ${{ secrets.NEEDED }}\n")
    facts = collector.collect(tmp_path, tag_repos=("o/r",), secrets_repo=None)
    assert "registered_secret_names" not in facts
    with pytest.raises(RatchetError, match="ci_facts_missing_registered_secret_names"):
        SecretDeclaredAdapter(CiFacts.from_dict(facts))


def test_collect_writes_empty_secret_names_when_none_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = _load_collector()
    monkeypatch.setattr(collector, "tagged_shas", lambda repos: [TAGGED])
    _workflow(tmp_path, "a.yml", "x: ${{ secrets.GITHUB_TOKEN }}\n")
    facts = collector.collect(tmp_path, tag_repos=("o/r",), secrets_repo=None)
    assert facts["registered_secret_names"] == []


def test_collect_records_only_live_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collector = _load_collector()
    monkeypatch.setattr(collector, "tagged_shas", lambda repos: [])
    monkeypatch.setattr(collector, "asset_is_live", lambda url: url == LIVE_URL)
    _workflow(tmp_path, "a.yml", f"a: {LIVE_URL}\nb: {DEAD_URL}\n")
    facts = collector.collect(tmp_path, tag_repos=(), secrets_repo=None)
    assert facts["live_release_assets"] == [LIVE_URL]
    assert referenced_asset_urls(tmp_path) == (LIVE_URL, DEAD_URL)
    assert required_secret_names(tmp_path) == ()


def test_collect_rejects_output_inside_repo(tmp_path: Path) -> None:
    collector = _load_collector()
    assert collector.main(["--repo", str(tmp_path), "--out", str(tmp_path / "f.json")]) == 2
