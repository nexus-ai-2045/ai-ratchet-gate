"""運用接続スクリプト scripts/enforce_observe_evaluate.py の回帰。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_ratchet_gate.adapters import ScanContext, TestDisableAdapter
from ai_ratchet_gate.waiver import (
    observation_digest,
    review_binding_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
ENFORCE = ROOT / "scripts" / "enforce_observe_evaluate.py"
GIT_BASELINE = ROOT / ".ai-ratchet-gate" / "baselines" / "git.tracked_ignored.v1.json"
NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


def _git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, env=_git_env(), check=True)
    subprocess.run(
        ["git", "config", "user.email", "enforce@example.com"],
        cwd=path,
        env=_git_env(),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "enforce"],
        cwd=path,
        env=_git_env(),
        check=True,
    )
    (path / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=path, env=_git_env(), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"],
        cwd=path,
        env=_git_env(),
        check=True,
    )


def _empty_seed(path: Path, adapter_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": adapter_id,
                "adapter_version": "1",
                "subject": "placeholder",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )


def test_enforce_allows_clean_repo_with_empty_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    seed = tmp_path / "baseline.json"
    _empty_seed(seed, "git.tracked_ignored")
    receipt = tmp_path / "out" / "receipt.json"
    code = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--adapter",
            "git.tracked_ignored",
            "--baseline",
            str(seed),
            "--subject",
            "repo:example@deadbeef",
            "--receipt",
            str(receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
    ).returncode
    assert code == 0
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "allow"
    assert payload["decision"]["new"] == []


def test_enforce_denies_new_tracked_ignored(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (repo / "generated.txt").write_text("leak\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".gitignore", "generated.txt"],
        cwd=repo,
        env=_git_env(),
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", "bad"],
        cwd=repo,
        env=_git_env(),
        check=True,
    )
    seed = tmp_path / "baseline.json"
    _empty_seed(seed, "git.tracked_ignored")
    code = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--baseline",
            str(seed),
            "--subject",
            "repo:example@1",
        ],
        check=False,
        capture_output=True,
        text=True,
    ).returncode
    assert code == 1


def test_enforce_rejects_observe_mode(tmp_path: Path) -> None:
    """enforcement 入口は observe mode を受け取らない（誤検知観測と強制を混同しない）。"""
    result = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--baseline",
            str(GIT_BASELINE),
            "--mode",
            "observe",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_enforce_adapter_baseline_mismatch_fails_closed(tmp_path: Path) -> None:
    seed = tmp_path / "baseline.json"
    _empty_seed(seed, "skills.provenance")
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    result = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--adapter",
            "git.tracked_ignored",
            "--baseline",
            str(seed),
            "--subject",
            "repo:example@1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "adapter_id" in result.stderr


def test_enforce_rejects_duplicate_baseline_seed_keys(tmp_path: Path) -> None:
    """空 finding_ids のあとに別 finding_ids を足す曖昧 seed は fail-closed (exit 2)。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    seed = tmp_path / "dup-seed.json"
    # json.dumps では重複キーを表現できないため、手書き JSON を使う
    finding_id = "a" * 64
    seed.write_text(
        "{\n"
        '  "schema": "ai-ratchet-gate.baseline/v1",\n'
        '  "adapter_id": "git.tracked_ignored",\n'
        '  "adapter_version": "1",\n'
        '  "subject": "placeholder",\n'
        '  "policy": "new_only",\n'
        '  "finding_ids": [],\n'
        f'  "finding_ids": ["{finding_id}"]\n'
        "}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--baseline",
            str(seed),
            "--subject",
            "repo:example@dup",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "duplicate_json_object_key" in result.stderr


def test_enforce_receipt_parent_oserror_is_tool_error(tmp_path: Path) -> None:
    """receipt 親directory作成失敗は deny(1) ではなく tool_error(2)。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    seed = tmp_path / "baseline.json"
    _empty_seed(seed, "git.tracked_ignored")
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    receipt = blocker / "nested" / "receipt.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--baseline",
            str(seed),
            "--subject",
            "repo:example@receipt",
            "--receipt",
            str(receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "receipt" in result.stderr.lower() or "directory" in result.stderr.lower()


def test_enforce_forwards_reviewed_waiver(tmp_path: Path) -> None:
    """レビュー済み waiver を evaluate へフォワードし、承認はしない。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_flaky.py").write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_flaky():\n"
        "    assert 1 == 1\n",
        encoding="utf-8",
    )
    subject = "repo:example@waiver"
    observation = TestDisableAdapter().observe(ScanContext(repo, subject))
    finding = next(
        item for item in observation.findings if item.rule_id == "unconditional_skip"
    )
    digest = observation_digest(observation)
    expires_at = "2099-01-01T00:00:00Z"
    waiver_path = tmp_path / "waiver.json"
    waiver_path.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.waivers/v1",
                "adapter_id": "test.disable",
                "adapter_version": "1",
                "subject": subject,
                "waivers": [
                    {
                        "waiver_id": "w-enforce-1",
                        "finding_id": finding.finding_id,
                        "expires_at": expires_at,
                        "observation_sha256": digest,
                        "review_binding_sha256": review_binding_sha256(
                            adapter_id="test.disable",
                            adapter_version="1",
                            subject=subject,
                            waiver_id="w-enforce-1",
                            finding_id=finding.finding_id,
                            expires_at=expires_at,
                            observation_sha256=digest,
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    seed = tmp_path / "baseline.json"
    _empty_seed(seed, "test.disable")
    receipt = tmp_path / "receipt.json"

    denied = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--adapter",
            "test.disable",
            "--baseline",
            str(seed),
            "--subject",
            subject,
        ],
        check=False,
        capture_output=True,
        text=True,
    ).returncode
    assert denied == 1

    allowed = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--adapter",
            "test.disable",
            "--baseline",
            str(seed),
            "--subject",
            subject,
            "--waiver",
            str(waiver_path),
            "--receipt",
            str(receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
    ).returncode
    assert allowed == 0
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "allow"
    assert finding.finding_id in payload["decision"]["waived"]


def test_repo_baseline_seeds_match_built_in_adapters() -> None:
    """本repoの seed ファイル（読取のみ）は3 adapter 分あり契約どおり。走査はしない。"""
    base = ROOT / ".ai-ratchet-gate" / "baselines"
    expected = {
        "git.tracked_ignored": "git.tracked_ignored.v1.json",
        "skills.provenance": "skills.provenance.v1.json",
        "test.disable": "test.disable.v1.json",
    }
    for adapter_id, name in expected.items():
        payload = json.loads((base / name).read_text(encoding="utf-8"))
        assert payload["schema"] == "ai-ratchet-gate.baseline/v1"
        assert payload["adapter_id"] == adapter_id
        assert payload["policy"] == "new_only"
        assert payload["finding_ids"] == []
        assert set(payload) == {
            "schema",
            "adapter_id",
            "adapter_version",
            "subject",
            "policy",
            "finding_ids",
        }


@pytest.mark.parametrize(
    "adapter",
    ["git.tracked_ignored", "skills.provenance", "test.disable"],
)
def test_enforce_empty_seed_allows_on_temp_fixture(
    adapter: str, tmp_path: Path
) -> None:
    """unit は一時 repo fixture のみ。実 checkout 走査は CI/local enforce コマンド側。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    seed = tmp_path / "baseline.json"
    _empty_seed(seed, adapter)
    receipt = tmp_path / f"{adapter}.receipt.json"
    code = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(repo),
            "--adapter",
            adapter,
            "--baseline",
            str(seed),
            "--subject",
            f"repo:fixture@{adapter}",
            "--receipt",
            str(receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
    ).returncode
    assert code == 0, (
        adapter,
        code,
        receipt.read_text(encoding="utf-8") if receipt.exists() else "",
    )
    assert json.loads(receipt.read_text(encoding="utf-8"))["decision"]["status"] == (
        "allow"
    )
