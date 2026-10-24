#!/usr/bin/env python3
"""ソースcheckoutからの従来実行とimportを維持する互換ラッパー。"""

import importlib.util
from pathlib import Path

_CLI_PATH = Path(__file__).resolve().parent / "src" / "ai_ratchet_gate" / "cli.py"
_SPEC = importlib.util.spec_from_file_location("_ai_ratchet_gate_cli", _CLI_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import機構の異常
    raise ImportError(f"実装を読み込めません: {_CLI_PATH}")
_CLI = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CLI)

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

__version__ = "0.1.0"


if __name__ == "__main__":
    raise SystemExit(main())
