import hashlib
import json

import pytest

from ai_ratchet_gate.engine import SolutionKnowledge, compose_knowledge, resolve_problem
from ai_ratchet_gate.harness import (
    ResolverBinding,
    Verification,
    build_resolver_registry,
    run_resolution_loop,
)
from ai_ratchet_gate.model import RatchetError


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def context() -> str:
    return sha({"central_revision": "b11e044a", "local_inputs": []})


def knowledge():
    entry = SolutionKnowledge.create(
        problem_key="demo.bad-flag",
        resolver_id="demo.clear-flag",
        resolver_version="1",
        scope="central",
        evidence_sha256=sha("fixture"),
        source="repo:a#1",
    )
    return resolve_problem("demo.bad-flag", compose_knowledge([entry], []))


def verify(target, _problem):
    return Verification.create(
        resolved=not target["bad"],
        verifier_id="demo.verify",
        verifier_version="1",
        evidence_sha256=sha(target),
    )


def run(resolution, target, *, resolvers, verifier=verify, snapshot=sha):
    return run_resolution_loop(
        resolution,
        subject="repo:b@abc",
        knowledge_context_sha256=context(),
        target=target,
        resolvers=resolvers,
        snapshot=snapshot,
        verify=verifier,
    )


def test_known_problem_is_applied_reverified_and_context_bound():
    target = {"bad": True}
    calls = []

    def apply(state):
        calls.append("apply")
        state["bad"] = False

    binding = ResolverBinding.create(
        resolver_id="demo.clear-flag", resolver_version="1", apply=apply
    )
    resolution = knowledge()
    receipt = run(
        resolution,
        target,
        resolvers=build_resolver_registry([binding]),
    )

    assert receipt.status == "resolved"
    assert receipt.applied is True
    assert calls == ["apply"]
    assert receipt.verification and receipt.verification.resolved
    assert receipt.before_sha256 != receipt.after_sha256
    assert receipt.knowledge_context_sha256 == context()
    assert receipt.knowledge_id == resolution.knowledge.knowledge_id
    assert receipt.knowledge_evidence_sha256 == resolution.knowledge.evidence_sha256
    assert len(receipt.receipt_sha256) == 64


def test_preverify_skips_unnecessary_reapplication():
    target = {"bad": False}
    calls = []
    binding = ResolverBinding.create(
        resolver_id="demo.clear-flag",
        resolver_version="1",
        apply=lambda _state: calls.append("apply"),
    )
    receipt = run(
        knowledge(), target, resolvers=build_resolver_registry([binding])
    )

    assert receipt.status == "already_resolved"
    assert receipt.applied is False
    assert calls == []


def test_unknown_problem_never_mutates_target_but_binds_context():
    target = {"bad": True}
    resolution = resolve_problem("novel.problem", compose_knowledge([], []))
    receipt = run(resolution, target, resolvers={})

    assert receipt.status == "human_resolution_required"
    assert receipt.applied is False
    assert receipt.knowledge_context_sha256 == context()
    assert receipt.knowledge_id is None
    assert target == {"bad": True}


def test_postverify_failure_is_not_reported_as_success():
    target = {"bad": True}
    binding = ResolverBinding.create(
        resolver_id="demo.clear-flag", resolver_version="1", apply=lambda _state: None
    )
    receipt = run(
        knowledge(), target, resolvers=build_resolver_registry([binding])
    )

    assert receipt.status == "verification_failed"
    assert receipt.applied is True
    assert receipt.verification and not receipt.verification.resolved


def test_missing_or_duplicate_resolver_fails_closed():
    target = {"bad": True}
    with pytest.raises(RatchetError, match="resolver_not_registered"):
        run(knowledge(), target, resolvers={})

    binding = ResolverBinding.create(
        resolver_id="demo.clear-flag", resolver_version="1", apply=lambda _state: None
    )
    with pytest.raises(RatchetError, match="duplicate_resolver_binding"):
        build_resolver_registry([binding, binding])


def test_resolver_exception_fails_closed():
    target = {"bad": True}

    def explode(_state):
        raise RuntimeError("boom")

    binding = ResolverBinding.create(
        resolver_id="demo.clear-flag", resolver_version="1", apply=explode
    )
    with pytest.raises(RatchetError, match="resolver_apply_failed"):
        run(knowledge(), target, resolvers=build_resolver_registry([binding]))


def test_pre_verifier_cannot_mutate_target():
    target = {"bad": True}

    def mutating_verify(state, _problem):
        state["touched"] = True
        return Verification.create(
            resolved=False,
            verifier_id="demo.mutating-verify",
            verifier_version="1",
            evidence_sha256=sha(state),
        )

    with pytest.raises(RatchetError, match="verifier_mutated_target"):
        run(knowledge(), target, resolvers={}, verifier=mutating_verify)


def test_post_verifier_cannot_mutate_target():
    target = {"bad": True}
    calls = 0

    def phase_verify(state, _problem):
        nonlocal calls
        calls += 1
        if calls == 2:
            state["touched"] = True
        return Verification.create(
            resolved=not state["bad"],
            verifier_id="demo.phase-verify",
            verifier_version="1",
            evidence_sha256=sha(state),
        )

    binding = ResolverBinding.create(
        resolver_id="demo.clear-flag",
        resolver_version="1",
        apply=lambda state: state.__setitem__("bad", False),
    )
    with pytest.raises(RatchetError, match="verifier_mutated_target"):
        run(
            knowledge(),
            target,
            resolvers=build_resolver_registry([binding]),
            verifier=phase_verify,
        )


def test_verifier_must_return_verification_contract():
    target = {"bad": True}
    with pytest.raises(RatchetError, match="invalid_verification_result"):
        run(
            knowledge(),
            target,
            resolvers={},
            verifier=lambda _target, _problem: True,
        )


def test_verifier_exception_is_normalized_fail_closed():
    def explode(_target, _problem):
        raise RuntimeError("boom")

    with pytest.raises(RatchetError, match="verifier_failed"):
        run(knowledge(), {"bad": True}, resolvers={}, verifier=explode)


def test_verifier_mutation_before_exception_is_detected():
    target = {"bad": True}

    def mutate_then_explode(state, _problem):
        state["touched"] = True
        raise RuntimeError("boom")

    with pytest.raises(RatchetError, match="verifier_mutated_target"):
        run(knowledge(), target, resolvers={}, verifier=mutate_then_explode)


def test_snapshot_exception_is_normalized_fail_closed():
    def explode(_target):
        raise RuntimeError("boom")

    with pytest.raises(RatchetError, match="snapshot_failed"):
        run(knowledge(), {"bad": True}, resolvers={}, snapshot=explode)


def test_snapshot_exception_during_verifier_state_check_is_normalized():
    calls = 0

    def flaky_snapshot(target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("boom")
        return sha(target)

    with pytest.raises(RatchetError, match="snapshot_failed"):
        run(knowledge(), {"bad": True}, resolvers={}, snapshot=flaky_snapshot)


def test_invalid_knowledge_context_is_rejected_before_mutation():
    target = {"bad": True}
    with pytest.raises(RatchetError, match="invalid_knowledge_context_sha256"):
        run_resolution_loop(
            knowledge(),
            subject="repo:b@abc",
            knowledge_context_sha256="not-a-digest",
            target=target,
            resolvers={},
            snapshot=sha,
            verify=verify,
        )
    assert target == {"bad": True}
