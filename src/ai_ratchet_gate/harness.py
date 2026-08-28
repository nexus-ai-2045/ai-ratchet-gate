"""検証済み解決知識を安全に適用する薄いagent harness契約。"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .engine import Resolution
from .model import RatchetError

RECEIPT_SCHEMA = "ai-ratchet-gate.resolution-receipt/v1"


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
    knowledge_id: str | None
    resolver_id: str | None
    resolver_version: str | None
    before_sha256: str
    after_sha256: str
    verification: Verification | None
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RECEIPT_SCHEMA,
            "subject": self.subject,
            "problem_key": self.problem_key,
            "status": self.status,
            "applied": self.applied,
            "knowledge_id": self.knowledge_id,
            "resolver_id": self.resolver_id,
            "resolver_version": self.resolver_version,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "verification": (
                {
                    "resolved": self.verification.resolved,
                    "verifier_id": self.verification.verifier_id,
                    "verifier_version": self.verification.verifier_version,
                    "evidence_sha256": self.verification.evidence_sha256,
                }
                if self.verification
                else None
            ),
            "receipt_sha256": self.receipt_sha256,
        }


def _receipt(
    *,
    subject: str,
    problem_key: str,
    status: str,
    applied: bool,
    knowledge_id: str | None,
    resolver_id: str | None,
    resolver_version: str | None,
    before_sha256: str,
    after_sha256: str,
    verification: Verification | None,
) -> ResolutionReceipt:
    body = {
        "schema": RECEIPT_SCHEMA,
        "subject": _nonempty(subject, "subject"),
        "problem_key": _nonempty(problem_key, "problem_key"),
        "status": _nonempty(status, "status"),
        "applied": applied,
        "knowledge_id": knowledge_id,
        "resolver_id": resolver_id,
        "resolver_version": resolver_version,
        "before_sha256": _sha256(before_sha256, "before_sha256"),
        "after_sha256": _sha256(after_sha256, "after_sha256"),
        "verification": (
            {
                "resolved": verification.resolved,
                "verifier_id": verification.verifier_id,
                "verifier_version": verification.verifier_version,
                "evidence_sha256": verification.evidence_sha256,
            }
            if verification
            else None
        ),
    }
    digest = hashlib.sha256(_canonical(body)).hexdigest()
    return ResolutionReceipt(
        subject=body["subject"],
        problem_key=body["problem_key"],
        status=body["status"],
        applied=applied,
        knowledge_id=knowledge_id,
        resolver_id=resolver_id,
        resolver_version=resolver_version,
        before_sha256=body["before_sha256"],
        after_sha256=body["after_sha256"],
        verification=verification,
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


def _verify_without_mutation(
    target: Any,
    problem_key: str,
    *,
    snapshot: Callable[[Any], str],
    verify: Callable[[Any, str], Verification],
    expected_sha256: str,
) -> Verification:
    verification = verify(target, problem_key)
    if not isinstance(verification, Verification):
        raise RatchetError("invalid_verification_result")
    observed = _sha256(snapshot(target), "verification_state_sha256")
    if observed != expected_sha256:
        raise RatchetError("verifier_mutated_target")
    return verification


def run_resolution_loop(
    resolution: Resolution,
    *,
    subject: str,
    target: Any,
    resolvers: dict[tuple[str, str], ResolverBinding],
    snapshot: Callable[[Any], str],
    verify: Callable[[Any, str], Verification],
) -> ResolutionReceipt:
    """pre-verify -> exact resolver apply -> post-verify。対象固有mutation primitiveは内蔵しない。"""
    if not callable(snapshot) or not callable(verify):
        raise RatchetError("invalid_harness_callback")
    subject_value = _nonempty(subject, "subject")
    before = _sha256(snapshot(target), "before_sha256")

    if resolution.status == "unknown":
        if resolution.knowledge is not None:
            raise RatchetError("unknown_resolution_has_knowledge")
        return _receipt(
            subject=subject_value,
            problem_key=resolution.problem_key,
            status="human_resolution_required",
            applied=False,
            knowledge_id=None,
            resolver_id=None,
            resolver_version=None,
            before_sha256=before,
            after_sha256=before,
            verification=None,
        )

    if resolution.status != "known" or resolution.knowledge is None:
        raise RatchetError("invalid_resolution")
    knowledge = resolution.knowledge
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
            knowledge_id=knowledge.knowledge_id,
            resolver_id=knowledge.resolver_id,
            resolver_version=knowledge.resolver_version,
            before_sha256=before,
            after_sha256=before,
            verification=pre,
        )

    key = (knowledge.resolver_id, knowledge.resolver_version)
    binding = resolvers.get(key)
    if binding is None:
        raise RatchetError("resolver_not_registered")

    try:
        binding.apply(target)
    except Exception as error:
        raise RatchetError("resolver_apply_failed") from error

    after = _sha256(snapshot(target), "after_sha256")
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
        knowledge_id=knowledge.knowledge_id,
        resolver_id=knowledge.resolver_id,
        resolver_version=knowledge.resolver_version,
        before_sha256=before,
        after_sha256=after,
        verification=post,
    )
