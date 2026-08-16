#!/usr/bin/env python3
"""ソースcheckoutからの従来実行を維持する互換ラッパー。"""

from src.ai_ratchet_gate.cli import *  # noqa: F403
from src.ai_ratchet_gate.cli import main

__version__ = "0.1.0"


if __name__ == "__main__":
    raise SystemExit(main())
