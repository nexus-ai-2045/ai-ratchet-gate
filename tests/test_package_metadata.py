from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publication_stays_blocked_until_human_approval() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == "ai-ratchet-gate"
    assert project["version"] == "0.1.0"
    assert project["license"] == "LicenseRef-Proprietary"
    assert "Private :: Do Not Upload" in project["classifiers"]
    assert project["authors"] == [{"name": "nexus-ai-2045"}]
    assert project["urls"]["Source"] == (
        "https://github.com/nexus-ai-2045/ai-ratchet-gate"
    )
