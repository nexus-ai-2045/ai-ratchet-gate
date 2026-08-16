from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publication_metadata_matches_the_approved_identity() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == "ai-ratchet-gate"
    assert project["version"] == "0.1.0"
    assert project["license"] == "MIT"
    assert "Private :: Do Not Upload" not in project["classifiers"]
    assert project["authors"] == [{"name": "nexus-ai-2045"}]
    assert project["urls"]["Source"] == (
        "https://github.com/nexus-ai-2045/ai-ratchet-gate"
    )
    assert project["optional-dependencies"]["release"] == [
        "build>=1.2,<2",
        "twine>=6,<8",
    ]
