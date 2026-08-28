import hashlib

import pytest

from ai_ratchet_gate.knowledge import (
    KNOWLEDGE_SCHEMA,
    SolutionKnowledge,
    compose_knowledge,
    load_knowledge_document,
    resolve_problem,
)
from ai_ratchet_gate.model import RatchetError


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make(scope: str, problem_key: str, resolver_id: str) -> SolutionKnowledge:
    return SolutionKnowledge.create(
        problem_key=problem_key,
        resolver_id=resolver_id,
        resolver_version="1",
        scope=scope,
        evidence_sha256=digest(f"fixture:{problem_key}:{resolver_id}"),
        source="repo:example/source#review-1",
    )


def test_central_solution_is_reused_in_another_repository():
    learned_in_repo_a = make(
        "central",
        "python.pytest.disabled-test-marker",
        "python.pytest.restore-test",
    )

    knowledge = compose_knowledge([learned_in_repo_a], [])
    resolution = resolve_problem("python.pytest.disabled-test-marker", knowledge)

    assert resolution.status == "known"
    assert resolution.knowledge is not None
    assert resolution.knowledge.resolver_id == "python.pytest.restore-test"
    # repo B固有のpathやcommit SHAをidentityに含めず、同種問題として再利用できる。
    assert resolution.reason == "verified_solution_available"


def test_local_solution_overrides_central_for_same_problem_key():
    central = make("central", "generated-artifact-tracked", "git.untrack-generated")
    local = make("local", "generated-artifact-tracked", "repo.keep-generated-source")

    knowledge = compose_knowledge([central], [local])

    assert knowledge["generated-artifact-tracked"].resolver_id == "repo.keep-generated-source"
    assert knowledge["generated-artifact-tracked"].scope == "local"


def test_unknown_problem_is_returned_for_human_resolution_not_false_success():
    resolution = resolve_problem("novel.problem", compose_knowledge([], []))

    assert resolution.status == "unknown"
    assert resolution.knowledge is None
    assert resolution.reason == "no_verified_solution"


def test_ambiguous_same_scope_resolution_fails_closed():
    first = make("central", "same-problem", "resolver.one")
    second = make("central", "same-problem", "resolver.two")

    with pytest.raises(RatchetError, match="ambiguous_problem_resolution"):
        compose_knowledge([first, second], [])


def test_document_round_trip_validates_scope_and_identity():
    entry = make("central", "same-problem", "resolver.one")
    document = {
        "schema": KNOWLEDGE_SCHEMA,
        "scope": "central",
        "entries": [entry.to_dict()],
    }

    assert load_knowledge_document(document, expected_scope="central") == (entry,)

    document["entries"][0]["resolver_id"] = "tampered"
    with pytest.raises(RatchetError, match="knowledge_id_mismatch"):
        load_knowledge_document(document, expected_scope="central")
