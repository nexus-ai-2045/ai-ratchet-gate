"""人間確認済みfailureを実行可能な非回帰guardへ変える汎用gate。"""

from .adapters import ScanContext, TrackedIgnoredAdapter
from .engine import evaluate
from .model import Decision, Finding, Observation, RatchetError
from .receipt import build_receipt

from .cli import (
    BASELINE_HEADER,
    DEFAULT_BASELINE,
    SKIP_ENV,
    diff_against_baseline,
    format_baseline,
    list_tracked_ignored,
    main,
    parse_baseline,
)

__all__ = [
    "BASELINE_HEADER",
    "DEFAULT_BASELINE",
    "SKIP_ENV",
    "diff_against_baseline",
    "format_baseline",
    "list_tracked_ignored",
    "main",
    "parse_baseline",
    "Decision",
    "Finding",
    "Observation",
    "RatchetError",
    "ScanContext",
    "TrackedIgnoredAdapter",
    "build_receipt",
    "evaluate",
]

__version__ = "0.1.1"
