"""人間確認済みfailureを実行可能な非回帰guardへ変える汎用gate。"""

from .adapters import (
    DEFAULT_SKILL_ROOTS,
    SKILLS_PROVENANCE_ADAPTER_ID,
    TEST_DISABLE_ADAPTER_ID,
    ScanContext,
    SkillProvenanceAdapter,
    TestDisableAdapter,
    TrackedIgnoredAdapter,
)
from .engine import evaluate
from .model import Decision, Finding, Observation, RatchetError
from .receipt import build_receipt
from .waiver import (
    WaiverDocument,
    WaiverRecord,
    observation_digest,
    review_binding_sha256,
    select_waived_finding_ids,
)

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
    "DEFAULT_SKILL_ROOTS",
    "SKIP_ENV",
    "SKILLS_PROVENANCE_ADAPTER_ID",
    "TEST_DISABLE_ADAPTER_ID",
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
    "SkillProvenanceAdapter",
    "TestDisableAdapter",
    "TrackedIgnoredAdapter",
    "WaiverDocument",
    "WaiverRecord",
    "build_receipt",
    "evaluate",
    "observation_digest",
    "review_binding_sha256",
    "select_waived_finding_ids",
]

__version__ = "0.1.1"
