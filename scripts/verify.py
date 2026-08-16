#!/usr/bin/env python3
"""選択したPythonとテスト実行環境の食い違いを早期検出する。"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile


def main() -> int:
    if sys.version_info < (3, 11):
        print(f"ERROR: Python 3.11以上が必要です: {sys.executable}")
        return 2

    if importlib.util.find_spec("pytest") is None:
        print(
            "ERROR: このPython環境にtest依存がありません。\n"
            f'  初期化: "{sys.executable}" -m pip install -e ".[test]"'
        )
        return 2

    print(f"==> 検証Python: {sys.executable}")
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


if __name__ == "__main__":
    raise SystemExit(main())
