from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest

from ai_ratchet_gate.engine import (
    KNOWLEDGE_SCHEMA,
    SolutionKnowledge,
    compose_knowledge,
    load_knowledge_document,
    resolve_problem,
)
from ai_ratchet_gate.model import RatchetError


ROOT = Path(__file__).resolve().parents[1]


def test_publication_metadata_matches_the_approved_identity() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == "ai-ratchet-gate"
    assert project["version"] == "0.1.1"
    assert project["license"] == "MIT"
    assert "Private :: Do Not Upload" in project["classifiers"]
    assert project["authors"] == [{"name": "nexus-ai-2045"}]
    assert project["urls"]["Source"] == (
        "https://github.com/nexus-ai-2045/ai-ratchet-gate"
    )
    assert project["optional-dependencies"]["release"] == [
        "build>=1.2,<2",
        "packaging>=24,<27",
        "wheel>=0.45,<1",
    ]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _knowledge(scope: str, problem_key: str, resolver_id: str) -> SolutionKnowledge:
    return SolutionKnowledge.create(
        problem_key=problem_key,
        resolver_id=resolver_id,
        resolver_version="1",
        scope=scope,
        evidence_sha256=_digest(f"fixture:{problem_key}:{resolver_id}"),
        source="repo:example/source#review-1",
    )


def test_central_solution_is_reused_for_same_problem_in_another_repo() -> None:
    learned_in_repo_a = _knowledge(
        "central",
        "python.pytest.disabled-test-marker",
        "python.pytest.restore-test",
    )
    resolution = resolve_problem(
        "python.pytest.disabled-test-marker",
        compose_knowledge([learned_in_repo_a], []),
    )

    assert resolution.status == "known"
    assert resolution.knowledge is not None
    assert resolution.knowledge.resolver_id == "python.pytest.restore-test"
    assert resolution.reason == "verified_solution_available"


def test_local_solution_overrides_central_for_same_problem_key() -> None:
    central = _knowledge("central", "generated-artifact-tracked", "git.untrack-generated")
    local = _knowledge("local", "generated-artifact-tracked", "repo.keep-generated-source")

    knowledge = compose_knowledge([central], [local])

    assert knowledge["generated-artifact-tracked"].resolver_id == "repo.keep-generated-source"
    assert knowledge["generated-artifact-tracked"].scope == "local"


def test_unknown_problem_returns_to_human_resolution() -> None:
    resolution = resolve_problem("novel.problem", compose_knowledge([], []))

    assert resolution.status == "unknown"
    assert resolution.knowledge is None
    assert resolution.reason == "no_verified_solution"


def test_ambiguous_same_scope_resolution_fails_closed() -> None:
    first = _knowledge("central", "same-problem", "resolver.one")
    second = _knowledge("central", "same-problem", "resolver.two")

    with pytest.raises(RatchetError, match="ambiguous_problem_resolution"):
        compose_knowledge([first, second], [])


def test_knowledge_document_validates_scope_and_identity() -> None:
    entry = _knowledge("central", "same-problem", "resolver.one")
    document = {
        "schema": KNOWLEDGE_SCHEMA,
        "scope": "central",
        "entries": [entry.to_dict()],
    }

    assert load_knowledge_document(document, expected_scope="central") == (entry,)

    document["entries"][0]["resolver_id"] = "tampered"
    with pytest.raises(RatchetError, match="knowledge_id_mismatch"):
        load_knowledge_document(document, expected_scope="central")
