"""組み込み観測adapter。"""

from .protocol import Adapter, ScanContext
from .skill_provenance import (
    ADAPTER_ID as SKILLS_PROVENANCE_ADAPTER_ID,
    DEFAULT_SKILL_ROOTS,
    SkillProvenanceAdapter,
)
from .test_disable import ADAPTER_ID as TEST_DISABLE_ADAPTER_ID, TestDisableAdapter
from .tracked_ignored import TrackedIgnoredAdapter

__all__ = [
    "Adapter",
    "DEFAULT_SKILL_ROOTS",
    "SKILLS_PROVENANCE_ADAPTER_ID",
    "TEST_DISABLE_ADAPTER_ID",
    "ScanContext",
    "SkillProvenanceAdapter",
    "TestDisableAdapter",
    "TrackedIgnoredAdapter",
]
