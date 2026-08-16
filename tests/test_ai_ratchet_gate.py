"""ai_ratchet_gate.py のテスト。

「tracked なのに gitignore にマッチする」矛盾の増分を commit 時に止めるゲート。
既存分は baseline として grandfather し、新規だけ deny する。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_ratchet_gate import (  # noqa: E402
    diff_against_baseline,
    format_baseline,
    list_tracked_ignored,
    main,
    parse_baseline,
)


def test_package_exposes_version() -> None:
    import ai_ratchet_gate

    assert ai_ratchet_gate.__version__ == "0.1.0"


def test_legacy_script_ignores_unrelated_src_package(tmp_path: Path) -> None:
    unrelated_src = tmp_path / "src"
    unrelated_src.mkdir()
    (unrelated_src / "__init__.py").write_text("", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)
    env["PYTHONUTF8"] = "1"

    completed = subprocess.run(
        [sys.executable, str(ROOT / "ai_ratchet_gate.py"), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "tracked∧ignored" in completed.stdout


def _git_env() -> dict[str, str]:
    """親プロセスの GIT_* を持ち込まない (GIT_DIR 継承で実 repo を壊す事故の自衛)。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _init_repo(root: Path) -> None:
    env = _git_env()
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.invalid"],
        cwd=root, env=env, check=True,
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, env=env, check=True)


def _commit_all(root: Path, message: str = "c") -> None:
    env = _git_env()
    subprocess.run(["git", "add", "-A", "-f"], cwd=root, env=env, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message, "--no-verify"],
        cwd=root, env=env, check=True,
    )


# --- 純関数 ---------------------------------------------------------------


def test_parse_baseline_skips_comments_and_blanks(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("# header\n\na.log\nb/c.log\n", encoding="utf-8")

    assert parse_baseline(baseline) == {"a.log", "b/c.log"}


def test_diff_reports_only_new_entries() -> None:
    new, resolved = diff_against_baseline(
        current={"a.log", "new.log"}, baseline={"a.log", "gone.log"}
    )

    assert new == ["new.log"]
    assert resolved == ["gone.log"]


def test_format_baseline_is_sorted_and_stable() -> None:
    text = format_baseline({"b.log", "a.log"})

    lines = [l for l in text.splitlines() if l and not l.startswith("#")]
    assert lines == ["a.log", "b.log"]
    assert text == format_baseline({"a.log", "b.log"})  # 順序非依存で同一出力


# --- git 統合 (tmp repo) ---------------------------------------------------


def test_list_tracked_ignored_detects_late_ignore_pattern(tmp_path: Path) -> None:
    """先に commit → 後から ignore、の順で矛盾が生まれる (本ゲートの起源事故の型)。"""
    _init_repo(tmp_path)
    (tmp_path / "out.log").write_text("v1", encoding="utf-8")
    _commit_all(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _commit_all(tmp_path)

    assert list_tracked_ignored(tmp_path) == {"out.log"}


def test_list_tracked_ignored_handles_non_ascii_paths(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "計測ログ.log").write_text("v1", encoding="utf-8")
    _commit_all(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _commit_all(tmp_path)

    assert list_tracked_ignored(tmp_path) == {"計測ログ.log"}


def test_main_allows_when_no_new_inconsistency(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(format_baseline(set()), encoding="utf-8")

    assert main(["--repo", str(tmp_path), "--baseline", str(baseline)]) == 0


def test_main_blocks_new_inconsistency(tmp_path: Path, capsys) -> None:
    _init_repo(tmp_path)
    (tmp_path / "out.log").write_text("v1", encoding="utf-8")
    _commit_all(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _commit_all(tmp_path)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(format_baseline(set()), encoding="utf-8")

    code = main(["--repo", str(tmp_path), "--baseline", str(baseline)])

    out = capsys.readouterr().out
    assert code == 1
    assert "out.log" in out
    assert "rm --cached" in out  # 修復手順を案内する


def test_main_allows_grandfathered_entries(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "out.log").write_text("v1", encoding="utf-8")
    _commit_all(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _commit_all(tmp_path)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(format_baseline({"out.log"}), encoding="utf-8")

    assert main(["--repo", str(tmp_path), "--baseline", str(baseline)]) == 0


def test_main_fails_closed_without_baseline(tmp_path: Path, capsys) -> None:
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path)

    code = main(
        ["--repo", str(tmp_path), "--baseline", str(tmp_path / "missing.txt")]
    )

    assert code == 1
    assert "baseline" in capsys.readouterr().out


def test_main_update_baseline_writes_current_state(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "out.log").write_text("v1", encoding="utf-8")
    _commit_all(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _commit_all(tmp_path)
    baseline = tmp_path / "baseline.txt"

    code = main(
        ["--repo", str(tmp_path), "--baseline", str(baseline), "--update-baseline"]
    )

    assert code == 0
    assert parse_baseline(baseline) == {"out.log"}
    # 直後の通常実行は通る
    assert main(["--repo", str(tmp_path), "--baseline", str(baseline)]) == 0


def test_main_default_baseline_lives_inside_repo(tmp_path: Path) -> None:
    """--baseline 省略時は <repo>/.ai-ratchet-gate/baseline.txt を使う。"""
    _init_repo(tmp_path)
    (tmp_path / "src.py").write_text("x = 1\n", encoding="utf-8")
    _commit_all(tmp_path)

    code = main(["--repo", str(tmp_path), "--update-baseline"])

    assert code == 0
    assert (tmp_path / ".ai-ratchet-gate" / "baseline.txt").is_file()
    assert main(["--repo", str(tmp_path)]) == 0


def test_main_skip_env_bypasses_with_notice(tmp_path: Path, capsys, monkeypatch) -> None:
    _init_repo(tmp_path)
    (tmp_path / "out.log").write_text("v1", encoding="utf-8")
    _commit_all(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _commit_all(tmp_path)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(format_baseline(set()), encoding="utf-8")
    monkeypatch.setenv("AI_RATCHET_GATE_SKIP", "1")

    code = main(["--repo", str(tmp_path), "--baseline", str(baseline)])

    assert code == 0
    assert "SKIP" in capsys.readouterr().out
