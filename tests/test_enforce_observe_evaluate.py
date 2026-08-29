"""運用接続スクリプト scripts/enforce_observe_evaluate.py の回帰。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCE = ROOT / "scripts" / "enforce_observe_evaluate.py"
GIT_BASELINE = ROOT / ".ai-ratchet-gate" / "baselines" / "git.tracked_ignored.v1.json"


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


def test_enforce_allows_clean_repo_with_empty_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    seed = tmp_path / "baseline.json"
    seed.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "git.tracked_ignored",
                "adapter_version": "1",
                "subject": "placeholder",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
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
    seed.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "git.tracked_ignored",
                "adapter_version": "1",
                "subject": "placeholder",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
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
    assert "observe" in result.stderr.lower() or "invalid" in result.stderr.lower() or result.returncode == 2


def test_enforce_adapter_baseline_mismatch_fails_closed(tmp_path: Path) -> None:
    seed = tmp_path / "baseline.json"
    seed.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "skills.provenance",
                "adapter_version": "1",
                "subject": "placeholder",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
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


def test_repo_baseline_seeds_match_built_in_adapters() -> None:
    """本repoの seed は3 adapter 分あり、キー集合と schema が契約どおり。"""
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
    "adapter,seed_name",
    [
        ("git.tracked_ignored", "git.tracked_ignored.v1.json"),
        ("skills.provenance", "skills.provenance.v1.json"),
        ("test.disable", "test.disable.v1.json"),
    ],
)
def test_enforce_self_repo_seeds_allow_on_current_tree(
    adapter: str, seed_name: str, tmp_path: Path
) -> None:
    """本repoの現状（finding 0）では3 adapterとも empty seed で allow。"""
    receipt = tmp_path / f"{adapter}.receipt.json"
    code = subprocess.run(
        [
            sys.executable,
            str(ENFORCE),
            "--repo",
            str(ROOT),
            "--adapter",
            adapter,
            "--baseline",
            str(ROOT / ".ai-ratchet-gate" / "baselines" / seed_name),
            "--subject",
            f"repo:self-test@{adapter}",
            "--receipt",
            str(receipt),
        ],
        check=False,
        capture_output=True,
        text=True,
    ).returncode
    assert code == 0, (adapter, code, receipt.read_text(encoding="utf-8") if receipt.exists() else "")
    assert json.loads(receipt.read_text(encoding="utf-8"))["decision"]["status"] == "allow"
