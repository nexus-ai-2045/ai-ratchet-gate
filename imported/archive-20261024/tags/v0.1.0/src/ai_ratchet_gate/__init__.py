"""trackedかつignoredなGit矛盾の増分を止めるラチェット型ゲート。"""

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
]

__version__ = "0.1.0"
