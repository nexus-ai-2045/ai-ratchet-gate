"""中央から呼ぶ ratchet（ADR-0011）のテスト。

対象リポには呼び出しのジョブだけを書き、設定ファイルやフックを置かせない。
- 既定の baseline が無いときは「見逃し0件」として一番厳しく判定する（ファイルを作らない）
- 中央の reusable workflow は、対象リポとこのリポを別の場所へ取り出し、対象を書き換えない
- 必須チェック（all-green）が ratchet の結果を待つ
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_ratchet_gate import main  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "ratchet-gate.yml"
PREFLIGHT = ROOT / ".github" / "workflows" / "preflight.yml"


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, env=_git_env(), check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout


def _repo(root: Path, files: dict[str, str]) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")
    _git(root, "add", "-A", "-f")
    _git(root, "commit", "-q", "-m", "c", "--no-verify")


# --- 既定 baseline が無いとき ------------------------------------------------


def test_missing_default_baseline_passes_clean_repo_without_writing(
    tmp_path: Path, capsys
) -> None:
    _repo(tmp_path, {"a.py": "x = 1\n"})

    code = main(["--repo", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "baseline なし" in out
    # 対象リポへ何も作らない（ドットファイルを増やさない）
    assert not (tmp_path / ".ai-ratchet-gate").exists()
    assert _git(tmp_path, "status", "--porcelain", "--ignored") == ""


def test_missing_default_baseline_denies_every_inconsistency(
    tmp_path: Path, capsys
) -> None:
    """baseline が無い＝見逃し0件。既存の矛盾も新規として止める（弱めない）。"""
    _repo(tmp_path, {"out.log": "v1\n"})
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "commit", "-q", "-m", "ignore", "--no-verify")

    code = main(["--repo", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 1
    assert "out.log" in out
    assert not (tmp_path / ".ai-ratchet-gate").exists()


def test_explicit_missing_baseline_still_fails_closed(tmp_path: Path) -> None:
    """--baseline で名指ししたファイルが無いのは打ち間違いの恐れがあるので止める。"""
    _repo(tmp_path, {"a.py": "x = 1\n"})

    assert main(["--repo", str(tmp_path), "--baseline", str(tmp_path / "nai.txt")]) == 2


# --- 中央の reusable workflow ----------------------------------------------


def _text(path: Path) -> str:
    assert path.is_file(), f"{path} がありません"
    return path.read_text(encoding="utf-8")


def test_central_workflow_is_reusable_and_pinned_by_sha() -> None:
    text = _text(WORKFLOW)

    assert re.search(r"^on:\n  workflow_call:", text, re.M)
    assert "ratchet-ref:" in text
    # 枝名・タグ名は受けない。40桁 SHA だけ
    assert "^[0-9a-f]{40}$" in text
    assert 'test "$(git -C tool rev-parse HEAD)" = "$RATCHET_REF"' in text
    # 外部 action も含め uses は全部 40桁 SHA で固定する
    uses = re.findall(r"uses:\s*(\S+)", text)
    assert uses
    for target in uses:
        assert re.search(r"@[0-9a-f]{40}$", target), target


def test_central_workflow_does_not_touch_target_repo() -> None:
    text = _text(WORKFLOW)

    assert "path: target" in text
    assert "path: tool" in text
    assert text.count("persist-credentials: false") == 2
    assert "--repo target" in text
    # baseline の書き換えや、対象リポへのファイル配置をしない
    assert "--update-baseline" not in text
    assert "cp " not in text and "install -m" not in text
    # 呼び出し側の環境変数で素通りさせない
    assert 'AI_RATCHET_GATE_SKIP: ""' in text
    assert "permissions:\n  contents: read" in text


def test_required_aggregate_waits_for_ratchet() -> None:
    """必須チェック all-green が ratchet の結果を待つ（待たないと赤でもマージできる）。"""
    text = _text(PREFLIGHT)

    assert re.search(r"^  ratchet:\n    uses: \./\.github/workflows/ratchet-gate\.yml", text, re.M)
    assert re.search(r"needs: \[gate, ratchet\]", text)
    assert 'test "${{ needs.ratchet.result }}" = success' in text
