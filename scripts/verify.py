#!/usr/bin/env python3
"""選択したPythonとテスト実行環境の食い違いを早期検出する。

既定（引数なし）はCIと同じ全部の検証。途中の作業では `--changed [BASE]` で、
変えたファイルに関係するテストだけを回し、画面には要約だけを出して全文をログへ落とす。
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
# 変えたら全部のテストに戻すファイル（テストの土台・依存・設定）
FULL_TRIGGERS = ("pyproject.toml", "tests/conftest.py", "ai_ratchet_gate.py")
FULL_TRIGGER_PREFIXES = (".github/", ".ai-ratchet-gate/", "src/ai_ratchet_gate/__")


def _git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def changed_files(base: str, root: Path = ROOT) -> list[str]:
    merge_base = _git("merge-base", base, "HEAD", root=root).strip()
    names = set(_git("diff", "--name-only", "-z", merge_base, root=root).split("\0"))
    names |= set(_git("ls-files", "-z", "--others", "--exclude-standard", root=root).split("\0"))
    names.discard("")
    return sorted(names)


def _consumers_pattern(module: str, root: Path) -> re.Pattern[str]:
    """変えたモジュールと、それを（間接に）使うモジュールの名前すべてに当たる正規表現。"""
    sources = {
        p.stem: p.read_text(encoding="utf-8")
        for base in ("src", "scripts")
        for p in (root / base).rglob("*.py")
    }
    names = {module}
    while True:
        pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(names))) + r")\b")
        grown = names | {stem for stem, text in sources.items() if pattern.search(text)}
        if grown == names:
            return pattern
        names = grown


def related_tests(files: list[str], root: Path = ROOT) -> list[str] | None:
    """変えたファイルに関係するテスト。Noneは「全部のテストに戻す」。"""
    all_tests = sorted(
        p.relative_to(root).as_posix() for p in (root / "tests").glob("test_*.py")
    )
    tests: set[str] = set()
    for name in files:
        if name in FULL_TRIGGERS or name.startswith(FULL_TRIGGER_PREFIXES):
            return None
        if name.startswith("tests/") and name.endswith(".py"):
            if not Path(name).name.startswith("test_"):
                return None
            if (root / name).exists():
                tests.add(name)
        elif name.endswith(".py") and name.startswith(("src/", "scripts/")):
            pattern = _consumers_pattern(Path(name).stem, root)
            hits = [
                t
                for t in all_tests
                if pattern.search((root / t).read_text(encoding="utf-8"))
            ]
            if not hits:
                return None  # 関係するテストが見つからない変更は安全側で全部に戻す
            tests.update(hits)
        elif name == "CHANGELOG.md":
            tests.add("tests/test_release_changelog.py")
    return sorted(tests)


def redact(text: str, root: Path) -> str:
    """ログに実ホームパス・アカウント名・Pythonの場所・作業場所の絶対パスを残さない。"""
    pairs = [
        (sys.executable, "<python>"),
        (sys.prefix, "<python-prefix>"),
        (sys.base_prefix, "<python-base>"),
        (str(root), "<repo>"),
        (tempfile.gettempdir(), "<tmp>"),
        (str(Path.home()), "~"),
    ]
    for old, new in pairs:
        if old and old not in ("/", "."):
            text = text.replace(old, new)
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - 取れない環境では置き換えない
        user = ""
    if len(user) >= 3:
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(user)}(?![A-Za-z0-9_])", "<user>", text
        )
    return text


def display_path(path: Path, root: Path) -> str:
    """linked worktreeではgit-dirがROOTの外にあるため、相対パスで示す（実ホームパスを出さない）。"""
    return Path(os.path.relpath(path, root)).as_posix()


def _preflight() -> int:
    if sys.version_info < (3, 11):
        print(f"ERROR: Python 3.11以上が必要です: {sys.executable}")
        return 2
    if importlib.util.find_spec("pytest") is None:
        print(
            "ERROR: このPython環境にtest依存がありません。\n"
            f'  初期化: "{sys.executable}" -m pip install -e ".[test]"'
        )
        return 2
    return 0


def run_full() -> int:
    print(f"==> 検証Python: {sys.executable}")
    changelog = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_release_changelog.py")],
        check=False,
    )
    if changelog.returncode != 0:
        return changelog.returncode

    with tempfile.TemporaryDirectory(prefix="ai-ratchet-gate-pytest-") as basetemp:
        tests = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--basetemp", basetemp],
            check=False,
        )
    if tests.returncode != 0:
        return tests.returncode

    cli = subprocess.run(
        [sys.executable, "-m", "ai_ratchet_gate", "--help"], check=False
    )
    return cli.returncode


def run_changed(base: str) -> int:
    try:
        files = changed_files(base)
    except subprocess.CalledProcessError:
        print(f"失敗: 比較元 {base} が読めないので止めます（git fetch してください）")
        return 2
    tests = related_tests(files)
    py = sys.executable
    with tempfile.TemporaryDirectory(prefix="ai-ratchet-gate-pytest-") as basetemp:
        pytest_cmd = [py, "-m", "pytest", "-q", "--basetemp", basetemp]
        steps: list[tuple[str, list[str]]] = [
            ("changelog", [py, str(ROOT / "scripts" / "check_release_changelog.py")])
        ]
        if tests is None:
            steps.append(("pytest（全部・安全側）", pytest_cmd))
        elif tests:
            steps.append((f"pytest（関係 {len(tests)} ファイル）", pytest_cmd + tests))
        steps.append(("cli --help", [py, "-m", "ai_ratchet_gate", "--help"]))
        log_dir = ROOT / _git("rev-parse", "--git-dir").strip() / "verify"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-changed.log"
        failed: list[str] = []
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log:
            for name, cmd in steps:
                t0 = time.monotonic()
                done = subprocess.run(
                    cmd,
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="backslashreplace",
                    check=False,
                )
                rc = done.returncode
                log.write(f"===== {name}\n")
                log.write(redact(done.stdout, ROOT))
                print(f"{'緑' if rc == 0 else '赤'} {name} {time.monotonic() - t0:.1f}秒")
                if rc != 0:
                    failed.append(name)
    print(
        f"{'合格' if not failed else '不合格'}（changed）: "
        f"{len(steps) - len(failed)}/{len(steps)} 項目 {time.monotonic() - started:.1f}秒"
    )
    if failed:
        print("失敗した項目: " + "、".join(failed))
    print(f"全文のログ: {display_path(log_path, ROOT)}")
    print("PRを出す前とマージ前は、引数なしの全部の検証を回してください。")
    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="検証入口（既定はCIと同じ全部）")
    parser.add_argument(
        "--changed",
        nargs="?",
        const="origin/main",
        metavar="BASE",
        help="途中の作業用。BASE（既定 origin/main）からの差分に関係するテストだけを回す",
    )
    ns = parser.parse_args(argv)
    rc = _preflight()
    if rc:
        return rc
    if ns.changed:
        return run_changed(ns.changed)
    return run_full()


if __name__ == "__main__":
    raise SystemExit(main())
