"""skills.provenance adapter の決定論的観測と脅威モデル回帰。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_ratchet_gate.adapters import (
    DEFAULT_SKILL_ROOTS,
    ScanContext,
    SkillProvenanceAdapter,
)
from ai_ratchet_gate.cli import main
from ai_ratchet_gate.engine import evaluate
from ai_ratchet_gate.model import Finding, Observation, RatchetError
from ai_ratchet_gate.waiver import (
    WaiverDocument,
    observation_digest,
    review_binding_sha256,
    select_waived_finding_ids,
)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _write_skill(
    root: Path,
    name: str,
    *,
    skills_root: str = "skills",
    allowed_tools: str | list[str] | None | object = ...,
    scripts: dict[str, str] | None = None,
    body: str | None = None,
) -> Path:
    skill_dir = root / skills_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    if allowed_tools is ...:
        tools_block = ""
    elif allowed_tools is None:
        tools_block = ""
    elif isinstance(allowed_tools, list):
        tools_block = "allowed-tools:\n" + "".join(
            f"  - {item}\n" for item in allowed_tools
        )
    elif isinstance(allowed_tools, str):
        tools_block = f"allowed-tools: {allowed_tools}\n"
    else:
        raise AssertionError("unsupported allowed_tools fixture")
    body_text = body if body is not None else f"# {name}\n"
    text = (
        "---\n"
        f"name: {name}\n"
        f"description: fixture skill {name}\n"
        f"{tools_block}"
        "---\n"
        f"{body_text}"
    )
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    if scripts is not None:
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.exists():
            for child in scripts_dir.rglob("*"):
                if child.is_file():
                    child.unlink()
        else:
            scripts_dir.mkdir()
        for relative, content in scripts.items():
            path = scripts_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return skill_dir


def _by_rule(observation: Observation, rule_id: str) -> list[Finding]:
    return [item for item in observation.findings if item.rule_id == rule_id]


def test_default_roots_include_agents_and_skills() -> None:
    assert DEFAULT_SKILL_ROOTS == (".agents/skills", "skills")


def test_grandfathered_skill_allows_under_baseline(tmp_path: Path) -> None:
    _write_skill(
        tmp_path, "known", allowed_tools="Read", scripts={"run.sh": "echo ok"}
    )
    adapter = SkillProvenanceAdapter()
    observation = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in observation.findings]
    decision = evaluate(observation, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "allow"
    assert {item.rule_id for item in observation.findings} == {
        "new_skill",
        "allowed_tools_token",
        "executable_asset",
    }


def test_new_skill_denies(tmp_path: Path) -> None:
    _write_skill(tmp_path, "known", allowed_tools="Read")
    adapter = SkillProvenanceAdapter()
    baseline_ids = [
        item.finding_id
        for item in adapter.observe(ScanContext(tmp_path, "repo:skills@1")).findings
    ]
    _write_skill(tmp_path, "brand-new", allowed_tools="Read")
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert any(
        item.rule_id == "new_skill"
        and item.subject_key == "skills/brand-new"
        and item.finding_id in decision.new
        for item in current.findings
    )


def test_allowed_tools_expansion_denies(tmp_path: Path) -> None:
    _write_skill(tmp_path, "expand", allowed_tools="Read", scripts={"a.sh": "echo 1"})
    adapter = SkillProvenanceAdapter()
    baseline_ids = [
        item.finding_id
        for item in adapter.observe(ScanContext(tmp_path, "repo:skills@1")).findings
    ]
    _write_skill(
        tmp_path, "expand", allowed_tools="Read Write", scripts={"a.sh": "echo 1"}
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    new_findings = [
        item for item in current.findings if item.finding_id in decision.new
    ]
    assert all(item.rule_id == "allowed_tools_token" for item in new_findings)
    assert any(item.subject_key.endswith("::Write") for item in new_findings)


def test_unrestricted_tools_finding_when_allowed_tools_absent(
    tmp_path: Path,
) -> None:
    _write_skill(tmp_path, "open", allowed_tools=None)
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    unrestricted = _by_rule(observation, "unrestricted_tools")
    assert len(unrestricted) == 1
    assert unrestricted[0].subject_key == "skills/open"
    assert _by_rule(observation, "allowed_tools_token") == []


def test_grandfathered_script_digest_allows(tmp_path: Path) -> None:
    _write_skill(
        tmp_path, "payload", allowed_tools="Read", scripts={"run.sh": "echo fixed"}
    )
    adapter = SkillProvenanceAdapter()
    observation = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in observation.findings]
    assets = _by_rule(observation, "executable_asset")
    assert len(assets) == 1
    assert "@" in assets[0].subject_key
    decision = evaluate(observation, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "allow"
    assert decision.new == ()


def test_new_or_changed_script_payload_denies(tmp_path: Path) -> None:
    _write_skill(
        tmp_path, "payload", allowed_tools="Read", scripts={"run.sh": "echo old"}
    )
    adapter = SkillProvenanceAdapter()
    baseline_obs = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in baseline_obs.findings]

    _write_skill(
        tmp_path, "payload", allowed_tools="Read", scripts={"run.sh": "echo new"}
    )
    changed = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    changed_decision = evaluate(
        changed, baseline_ids, mode="ratchet", policy="new_only"
    )
    assert changed_decision.status == "deny"
    new_changed = [
        item for item in changed.findings if item.finding_id in changed_decision.new
    ]
    assert len(new_changed) == 1
    assert new_changed[0].rule_id == "executable_asset"
    assert new_changed[0].subject_key.startswith("skills/payload/scripts/run.sh@")
    assert changed_decision.resolved  # 旧 digest finding が resolved

    _write_skill(
        tmp_path,
        "payload",
        allowed_tools="Read",
        scripts={"run.sh": "echo old", "extra.sh": "echo x"},
    )
    added = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    added_decision = evaluate(added, baseline_ids, mode="ratchet", policy="new_only")
    assert added_decision.status == "deny"
    assert any(
        item.rule_id == "executable_asset"
        and "/scripts/extra.sh@" in item.subject_key
        and item.finding_id in added_decision.new
        for item in added.findings
    )


def test_script_and_tool_axes_do_not_cancel(tmp_path: Path) -> None:
    """tool縮小（改善）と script digest変更（悪化）は相殺しない。"""
    _write_skill(
        tmp_path,
        "mix",
        allowed_tools="Read Write",
        scripts={"run.sh": "echo old"},
    )
    adapter = SkillProvenanceAdapter()
    baseline_obs = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in baseline_obs.findings]
    old_write = next(
        item
        for item in _by_rule(baseline_obs, "allowed_tools_token")
        if item.subject_key.endswith("::Write")
    )
    old_script = _by_rule(baseline_obs, "executable_asset")[0]

    _write_skill(
        tmp_path,
        "mix",
        allowed_tools="Read",
        scripts={"run.sh": "echo new"},
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert old_write.finding_id in decision.resolved
    assert old_script.finding_id in decision.resolved
    assert any(
        item.rule_id == "executable_asset" and item.finding_id in decision.new
        for item in current.findings
    )
    assert not any(
        item.rule_id == "allowed_tools_token" and item.finding_id in decision.new
        for item in current.findings
    )


def test_body_only_edit_does_not_deny(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "docs",
        allowed_tools="Read",
        scripts={"run.sh": "echo 1"},
        body="# old body\n",
    )
    adapter = SkillProvenanceAdapter()
    baseline_ids = [
        item.finding_id
        for item in adapter.observe(ScanContext(tmp_path, "repo:skills@1")).findings
    ]
    _write_skill(
        tmp_path,
        "docs",
        allowed_tools="Read",
        scripts={"run.sh": "echo 1"},
        body="# rewritten body that must not deny\n",
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "allow"
    assert decision.new == ()


def test_scans_agents_skills_and_skills_roots(tmp_path: Path) -> None:
    _write_skill(
        tmp_path, "a", skills_root=".agents/skills", allowed_tools="Read"
    )
    _write_skill(tmp_path, "b", skills_root="skills", allowed_tools="Read")
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    keys = {item.subject_key for item in _by_rule(observation, "new_skill")}
    assert keys == {".agents/skills/a", "skills/b"}


def test_missing_both_roots_observes_zero_findings(tmp_path: Path) -> None:
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@empty")
    )
    assert observation.findings == ()
    assert evaluate(observation, [], mode="ratchet", policy="new_only").status == "allow"


def test_axes_do_not_net_out(tmp_path: Path) -> None:
    _write_skill(tmp_path, "left", allowed_tools="Read Write")
    _write_skill(tmp_path, "right", allowed_tools="Read", scripts={"x.sh": "old"})
    adapter = SkillProvenanceAdapter()
    baseline_ids = [
        item.finding_id
        for item in adapter.observe(ScanContext(tmp_path, "repo:skills@1")).findings
    ]
    _write_skill(tmp_path, "left", allowed_tools="Read")
    _write_skill(
        tmp_path,
        "right",
        allowed_tools="Read",
        scripts={"x.sh": "old", "y.sh": "new"},
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert any(
        item.rule_id == "executable_asset" and item.finding_id in decision.new
        for item in current.findings
    )


def test_invalid_frontmatter_fails_closed(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
    with pytest.raises(RatchetError, match="skill_frontmatter_missing"):
        SkillProvenanceAdapter().observe(ScanContext(tmp_path, "repo:skills@1"))


def test_path_spoof_skills_root_rejected() -> None:
    with pytest.raises(RatchetError, match="invalid_skills_root"):
        SkillProvenanceAdapter(skill_roots=("../outside",))


def test_symlink_skill_rejected(tmp_path: Path) -> None:
    real = tmp_path / "outside"
    real.mkdir()
    (real / "SKILL.md").write_text(
        "---\nname: outside\ndescription: x\n---\n", encoding="utf-8"
    )
    skills = tmp_path / "skills"
    skills.mkdir()
    try:
        (skills / "linked").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(RatchetError, match="skill_symlink_rejected"):
        SkillProvenanceAdapter().observe(ScanContext(tmp_path, "repo:skills@1"))


def test_subject_key_uses_path_not_declared_name(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "path-key"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: declared-other\ndescription: x\nallowed-tools: Read\n---\n",
        encoding="utf-8",
    )
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    present = _by_rule(observation, "new_skill")
    assert present[0].subject_key == "skills/path-key"
    assert "declared-other" not in present[0].subject_key


def test_label_swap_does_not_reuse_finding_identity(tmp_path: Path) -> None:
    _write_skill(tmp_path, "swap", allowed_tools="Read")
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    present = _by_rule(observation, "new_skill")[0]
    spoofed = Finding.create(
        adapter_id=present.adapter_id,
        adapter_version=present.adapter_version,
        rule_id="allowed_tools_token",
        subject_kind=present.subject_kind,
        subject_key=present.subject_key,
        message=present.message,
        evidence_sha256=present.evidence_sha256,
    )
    assert spoofed.finding_id != present.finding_id
    decision = evaluate(
        Observation.create(
            observation.adapter_id,
            observation.adapter_version,
            observation.subject,
            [spoofed],
        ),
        [present.finding_id],
        mode="ratchet",
        policy="new_only",
    )
    assert decision.status == "deny"
    assert decision.new == (spoofed.finding_id,)


def test_waiver_on_token_does_not_cover_executable_addition(
    tmp_path: Path,
) -> None:
    _write_skill(
        tmp_path, "bound", allowed_tools="Read", scripts={"a.sh": "old"}
    )
    adapter = SkillProvenanceAdapter()
    baseline_obs = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    _write_skill(
        tmp_path,
        "bound",
        allowed_tools="Read Write",
        scripts={"a.sh": "old", "b.sh": "new"},
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    expanded_tool = next(
        item
        for item in _by_rule(current, "allowed_tools_token")
        if item.subject_key.endswith("::Write")
    )
    digest = observation_digest(current)
    record = {
        "waiver_id": "w1",
        "finding_id": expanded_tool.finding_id,
        "observation_sha256": digest,
        "expires_at": "2099-01-01T00:00:00Z",
        "review_binding_sha256": review_binding_sha256(
            adapter_id=current.adapter_id,
            adapter_version=current.adapter_version,
            subject=current.subject,
            waiver_id="w1",
            finding_id=expanded_tool.finding_id,
            expires_at="2099-01-01T00:00:00Z",
            observation_sha256=digest,
        ),
    }
    document = WaiverDocument.from_dict(
        {
            "schema": "ai-ratchet-gate.waivers/v1",
            "adapter_id": current.adapter_id,
            "adapter_version": current.adapter_version,
            "subject": current.subject,
            "waivers": [record],
        }
    )
    waived = select_waived_finding_ids(document, current, now=NOW)
    baseline_ids = [item.finding_id for item in baseline_obs.findings]
    decision = evaluate(
        current,
        baseline_ids,
        mode="ratchet",
        policy="new_only",
        waived_finding_ids=waived,
    )
    assert decision.status == "deny"
    assert expanded_tool.finding_id in decision.waived
    assert any(
        item.rule_id == "executable_asset" and item.finding_id in decision.new
        for item in current.findings
    )


def test_observe_cli_skills_adapter_feeds_evaluate(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill(repo, "cli-skill", allowed_tools="Read")
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "skills.provenance",
            "--subject",
            "repo:cli@head",
            "--out",
            str(observation),
        ]
    ) == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    assert payload["adapter_id"] == "skills.provenance"
    assert payload["findings"]
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "skills.provenance",
                "adapter_version": "1",
                "subject": "repo:cli@head",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--expected-subject",
            "repo:cli@head",
        ]
    ) == 1


def test_observe_cli_default_adapter_remains_git(tmp_path: Path) -> None:
    import os
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    (repo / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (repo / "generated.txt").write_text("x", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".gitignore", "generated.txt"],
        cwd=repo,
        env=env,
        check=True,
    )
    observation = tmp_path / "observation.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--subject",
            "repo:x@head",
            "--out",
            str(observation),
        ]
    ) == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    assert payload["adapter_id"] == "git.tracked_ignored"


def test_operational_observe_evaluate_receipt_allow(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill(repo, "ops", allowed_tools="Read", scripts={"run.sh": "echo ops"})
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    receipt = tmp_path / "receipt.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "skills.provenance",
            "--subject",
            "repo:ops@head",
            "--out",
            str(observation),
        ]
    ) == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "skills.provenance",
                "adapter_version": "1",
                "subject": "repo:ops@head",
                "policy": "new_only",
                "finding_ids": [item["finding_id"] for item in payload["findings"]],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--expected-subject",
            "repo:ops@head",
            "--receipt",
            str(receipt),
        ]
    ) == 0
    decision = json.loads(receipt.read_text(encoding="utf-8"))
    assert decision["decision"]["status"] == "allow"
    assert decision["decision"]["new"] == []


def test_baseline_from_git_adapter_cannot_mask_skill_findings(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill(repo, "cross", allowed_tools="Read")
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "skills.provenance",
            "--subject",
            "repo:cross@head",
            "--out",
            str(observation),
        ]
    ) == 0
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "git.tracked_ignored",
                "adapter_version": "1",
                "subject": "repo:cross@head",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    code = main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--expected-subject",
            "repo:cross@head",
        ]
    )
    assert code == 2
    assert "baseline_identity_mismatch" in capsys.readouterr().out


def test_stable_ids_across_tool_list_syntax(tmp_path: Path) -> None:
    _write_skill(tmp_path, "syntax", allowed_tools="Read Write")
    string_form = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    _write_skill(tmp_path, "syntax", allowed_tools=["Write", "Read"])
    list_form = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    assert {item.finding_id for item in string_form.findings} == {
        item.finding_id for item in list_form.findings
    }
