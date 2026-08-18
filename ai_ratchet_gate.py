#!/usr/bin/env python3
"""ソースcheckoutからの従来実行とimportを維持する互換ラッパー。"""

import importlib
from pathlib import Path

# checkout直下の同名ファイルとしてimportされた場合もpackage submoduleを解決する。
# 外部cwdの無関係な ``src`` は参照せず、このファイルに隣接する正本へ固定する。
_PACKAGE_PATH = Path(__file__).resolve().parent / "src" / "ai_ratchet_gate"
__path__ = [str(_PACKAGE_PATH)]
_CLI = importlib.import_module("ai_ratchet_gate.cli")

__all__ = [
    "BASELINE_HEADER",
    "DEFAULT_BASELINE",
    "SKIP_ENV",
    "diff_against_baseline",
    "format_baseline",
    "list_tracked_ignored",
    "main",
    "parse_baseline",
]
globals().update({name: getattr(_CLI, name) for name in __all__})

__version__ = "0.1.1"


if __name__ == "__main__":
    raise SystemExit(main())
