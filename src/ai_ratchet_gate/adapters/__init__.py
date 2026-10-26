"""組み込み観測adapter。"""

from .ci_facts import (
    CI_FACTS_SCHEMA,
    PIN_TAGGED_ADAPTER_ID,
    RELEASE_ASSET_LIVE_ADAPTER_ID,
    SECRET_DECLARED_ADAPTER_ID,
    CiFacts,
    PinTaggedAdapter,
    ReleaseAssetLiveAdapter,
    SecretDeclaredAdapter,
)
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
    "CI_FACTS_SCHEMA",
    "CiFacts",
    "PIN_TAGGED_ADAPTER_ID",
    "PinTaggedAdapter",
    "RELEASE_ASSET_LIVE_ADAPTER_ID",
    "ReleaseAssetLiveAdapter",
    "SECRET_DECLARED_ADAPTER_ID",
    "SecretDeclaredAdapter",
    "DEFAULT_SKILL_ROOTS",
    "SKILLS_PROVENANCE_ADAPTER_ID",
    "TEST_DISABLE_ADAPTER_ID",
    "ScanContext",
    "SkillProvenanceAdapter",
    "TestDisableAdapter",
    "TrackedIgnoredAdapter",
]
