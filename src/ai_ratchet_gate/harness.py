"""検証済み解決知識を安全に適用する薄いagent harness契約。"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .engine import Resolution, SolutionKnowledge
from .model import RatchetError

RECEIPT_SCHEMA = "ai-ratchet-gate.resolution-receipt/v2"


def _nonempty(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise RatchetError(f"invalid_{name}")
    return unicodedata.normalize("NFC", value)


def _sha256(value: object, name: str) -> str:
    text = _nonempty(value, name)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise RatchetError(f"invalid_{name}")
    return text


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class Verification:
    resolved: bool
    verifier_id: str
    verifier_version: str
    evidence_sha256: str

    @classmethod
    def create(
        cls,
        *,
        resolved: bool,
        verifier_id: str,
        verifier_version: str,
        evidence_sha256: str,
    ) -> "Verification":
        if type(resolved) is not bool:
            raise RatchetError("invalid_resolved")
        return cls(
            resolved,
            _nonempty(verifier_id, "verifier_id"),
            _nonempty(verifier_version, "verifier_version"),
            _sha256(evidence_sha256, "evidence_sha256"),
        )


@dataclass(frozen=True, slots=True)
class ResolverBinding:
    resolver_id: str
    resolver_version: str
    apply: Callable[[Any], None]

    @classmethod
    def create(
        cls,
        *,
        resolver_id: str,
        resolver_version: str,
        apply: Callable[[Any], None],
    ) -> "ResolverBinding":
        if not callable(apply):
            raise RatchetError("invalid_resolver_apply")
        return cls(
            _nonempty(resolver_id, "resolver_id"),
            _nonempty(resolver_version, "resolver_version"),
            apply,
        )


@dataclass(frozen=True, slots=True)
class ResolutionReceipt:
    subject: str
    problem_key: str
    status: str
    applied: bool
    knowledge_context_sha256: str
    knowledge_id: str | None
    knowledge_evidence_sha256: str | None
    resolver_id: str | None
    resolver_version: str | None
    before_sha256: str
    after_sha256: str
    pre_verification: Verification | None
    post_verification: Verification | None
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "subject": self.subject,
            "problem_key": self.problem_key,
            "status": self.status,
            "applied": self.applied,
            "knowledge_context_sha256": self.knowledge_context_sha256,
            "knowledge_id": self.knowledge_id,
            "knowledge_evidence_sha256": self.knowledge_evidence_sha256,
            "resolver_id": self.resolver_id,
            "resolver_version": self.resolver_version,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "pre_verification": _verification_dict(self.pre_verification),
            "post_verification": _verification_dict(self.post_verification),
            "receipt_sha256": self.receipt_sha256,
        }


def _verification_dict(verification: Verification | None) -> dict[str, object] | None:
    return (
                {
                    "resolved": verification.resolved,
                    "verifier_id": verification.verifier_id,
                    "verifier_version": verification.verifier_version,
                    "evidence_sha256": verification.evidence_sha256,
                }
                if verification
                else None
    )


def _receipt(
    *,
    subject: str,
    problem_key: str,
    status: str,
    applied: bool,
    knowledge_context_sha256: str,
    knowledge_id: str | None,
    knowledge_evidence_sha256: str | None,
    resolver_id: str | None,
    resolver_version: str | None,
    before_sha256: str,
    after_sha256: str,
    pre_verification: Verification | None,
    post_verification: Verification | None,
) -> ResolutionReceipt:
    context = _sha256(knowledge_context_sha256, "knowledge_context_sha256")
    evidence = (
        _sha256(knowledge_evidence_sha256, "knowledge_evidence_sha256")
        if knowledge_evidence_sha256 is not None
        else None
    )
    body = {
        "schema": RECEIPT_SCHEMA,
        "subject": _nonempty(subject, "subject"),
        "problem_key": _nonempty(problem_key, "problem_key"),
        "status": _nonempty(status, "status"),
        "applied": applied,
        "knowledge_context_sha256": context,
        "knowledge_id": knowledge_id,
        "knowledge_evidence_sha256": evidence,
        "resolver_id": resolver_id,
        "resolver_version": resolver_version,
        "before_sha256": _sha256(before_sha256, "before_sha256"),
        "after_sha256": _sha256(after_sha256, "after_sha256"),
        "pre_verification": _verification_dict(pre_verification),
        "post_verification": _verification_dict(post_verification),
    }
    digest = hashlib.sha256(_canonical(body)).hexdigest()
    return ResolutionReceipt(
        subject=body["subject"],
        problem_key=body["problem_key"],
        status=body["status"],
        applied=applied,
        knowledge_context_sha256=context,
        knowledge_id=knowledge_id,
        knowledge_evidence_sha256=evidence,
        resolver_id=resolver_id,
        resolver_version=resolver_version,
        before_sha256=body["before_sha256"],
        after_sha256=body["after_sha256"],
        pre_verification=pre_verification,
        post_verification=post_verification,
        receipt_sha256=digest,
    )


def build_resolver_registry(
    bindings: Iterable[ResolverBinding],
) -> dict[tuple[str, str], ResolverBinding]:
    registry: dict[tuple[str, str], ResolverBinding] = {}
    for binding in bindings:
        key = (binding.resolver_id, binding.resolver_version)
        if key in registry:
            raise RatchetError("duplicate_resolver_binding")
        registry[key] = binding
    return registry


def _snapshot(target: Any, callback: Callable[[Any], str], name: str) -> str:
    try:
        return _sha256(callback(target), name)
    except RatchetError:
        raise
    except Exception as error:
        raise RatchetError("snapshot_failed") from error


def _verify_without_mutation(
    target: Any,
    problem_key: str,
    *,
    snapshot: Callable[[Any], str],
    verify: Callable[[Any, str], Verification],
    expected_sha256: str,
) -> Verification:
    try:
        verification = verify(target, problem_key)
    except Exception as error:
        observed = _snapshot(target, snapshot, "verification_state_sha256")
        if observed != expected_sha256:
            raise RatchetError("verifier_mutated_target") from error
        raise RatchetError("verifier_failed") from error
    observed = _snapshot(target, snapshot, "verification_state_sha256")
    if observed != expected_sha256:
        raise RatchetError("verifier_mutated_target")
    if not isinstance(verification, Verification):
        raise RatchetError("invalid_verification_result")
    validated = Verification.create(
        resolved=verification.resolved,
        verifier_id=verification.verifier_id,
        verifier_version=verification.verifier_version,
        evidence_sha256=verification.evidence_sha256,
    )
    if validated != verification:
        raise RatchetError("invalid_verification_result")
    return validated


def run_resolution_loop(
    resolution: Resolution,
    *,
    subject: str,
    knowledge_context_sha256: str,
    target: Any,
    resolvers: dict[tuple[str, str], ResolverBinding],
    snapshot: Callable[[Any], str],
    verify: Callable[[Any, str], Verification],
) -> ResolutionReceipt:
    """pre-verify -> exact resolver apply -> post-verify。対象固有mutation primitiveは内蔵しない。"""
    if not callable(snapshot) or not callable(verify):
        raise RatchetError("invalid_harness_callback")
    subject_value = _nonempty(subject, "subject")
    context = _sha256(knowledge_context_sha256, "knowledge_context_sha256")
    before = _snapshot(target, snapshot, "before_sha256")

    if resolution.status == "unknown":
        if resolution.knowledge is not None:
            raise RatchetError("unknown_resolution_has_knowledge")
        return _receipt(
            subject=subject_value,
            problem_key=resolution.problem_key,
            status="human_resolution_required",
            applied=False,
            knowledge_context_sha256=context,
            knowledge_id=None,
            knowledge_evidence_sha256=None,
            resolver_id=None,
            resolver_version=None,
            before_sha256=before,
            after_sha256=before,
            pre_verification=None,
            post_verification=None,
        )

    if resolution.status != "known" or resolution.knowledge is None:
        raise RatchetError("invalid_resolution")
    knowledge = resolution.knowledge
    try:
        knowledge = SolutionKnowledge.from_dict(knowledge.to_dict())
    except (AttributeError, TypeError, RatchetError) as error:
        raise RatchetError("invalid_solution_knowledge") from error
    if knowledge.problem_key != resolution.problem_key:
        raise RatchetError("problem_key_mismatch")

    pre = _verify_without_mutation(
        target,
        resolution.problem_key,
        snapshot=snapshot,
        verify=verify,
        expected_sha256=before,
    )
    if pre.resolved:
        return _receipt(
            subject=subject_value,
            problem_key=resolution.problem_key,
            status="already_resolved",
            applied=False,
            knowledge_context_sha256=context,
            knowledge_id=knowledge.knowledge_id,
            knowledge_evidence_sha256=knowledge.evidence_sha256,
            resolver_id=knowledge.resolver_id,
            resolver_version=knowledge.resolver_version,
            before_sha256=before,
            after_sha256=before,
            pre_verification=pre,
            post_verification=None,
        )

    key = (knowledge.resolver_id, knowledge.resolver_version)
    binding = resolvers.get(key)
    if binding is None:
        raise RatchetError("resolver_not_registered")
    try:
        validated_binding = ResolverBinding.create(
            resolver_id=binding.resolver_id,
            resolver_version=binding.resolver_version,
            apply=binding.apply,
        )
    except (AttributeError, TypeError, RatchetError) as error:
        raise RatchetError("invalid_resolver_binding") from error
    if validated_binding != binding or (
        validated_binding.resolver_id,
        validated_binding.resolver_version,
    ) != key:
        raise RatchetError("resolver_binding_identity_mismatch")

    try:
        validated_binding.apply(target)
    except Exception as error:
        raise RatchetError("resolver_apply_failed") from error

    after = _snapshot(target, snapshot, "after_sha256")
    post = _verify_without_mutation(
        target,
        resolution.problem_key,
        snapshot=snapshot,
        verify=verify,
        expected_sha256=after,
    )
    return _receipt(
        subject=subject_value,
        problem_key=resolution.problem_key,
        status="resolved" if post.resolved else "verification_failed",
        applied=True,
        knowledge_context_sha256=context,
        knowledge_id=knowledge.knowledge_id,
        knowledge_evidence_sha256=knowledge.evidence_sha256,
        resolver_id=knowledge.resolver_id,
        resolver_version=knowledge.resolver_version,
        before_sha256=before,
        after_sha256=after,
        pre_verification=pre,
        post_verification=post,
    )
