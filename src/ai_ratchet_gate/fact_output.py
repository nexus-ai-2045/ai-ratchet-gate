"""Structured fact-output envelope validator.

This module intentionally does not encode any product-specific label vocabulary.
A caller supplies a reviewed policy, then the adapter converts semantic violations
into the common Finding/Observation contract. Malformed or ambiguous input fails
closed with RatchetError.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

from .model import Finding, Observation, RatchetError

ADAPTER_ID = "agent.fact_output"
ADAPTER_VERSION = "1"
FACT_OUTPUT_SCHEMA = "ai-ratchet-gate.fact-output/v1"
FACT_OUTPUT_POLICY_SCHEMA = "ai-ratchet-gate.fact-output-policy/v1"
MAX_CLAIMS = 1_000
MAX_LABELS = 64
MAX_STRING_BYTES = 16 * 1024
_SOURCE_REQUIREMENTS = frozenset({"required", "optional", "forbidden"})
_CLAIM_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _string(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise RatchetError(f"invalid_{name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RatchetError(f"invalid_{name}") from error
    if len(encoded) > MAX_STRING_BYTES:
        raise RatchetError(f"invalid_{name}")
    return unicodedata.normalize("NFC", value)


def _exact_keys(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


@dataclass(frozen=True, slots=True)
class LabelPolicy:
    source: str


@dataclass(frozen=True, slots=True)
class FactOutputPolicy:
    labels: dict[str, LabelPolicy]
    require_claims: bool

    @classmethod
    def from_dict(cls, value: object) -> "FactOutputPolicy":
        if not _exact_keys(value, {"schema", "labels", "require_claims"}):
            raise RatchetError("invalid_fact_output_policy")
        if value["schema"] != FACT_OUTPUT_POLICY_SCHEMA:
            raise RatchetError("invalid_fact_output_policy_schema")
        if type(value["require_claims"]) is not bool:
            raise RatchetError("invalid_require_claims")
        raw_labels = value["labels"]
        if not isinstance(raw_labels, dict) or not raw_labels or len(raw_labels) > MAX_LABELS:
            raise RatchetError("invalid_fact_output_labels")

        labels: dict[str, LabelPolicy] = {}
        for raw_name, raw_policy in raw_labels.items():
            name = _string(raw_name, "label")
            if not _exact_keys(raw_policy, {"source"}):
                raise RatchetError("invalid_label_policy")
            source = _string(raw_policy["source"], "source_requirement")
            if source not in _SOURCE_REQUIREMENTS:
                raise RatchetError("invalid_source_requirement")
            if name in labels:
                raise RatchetError("duplicate_normalized_label")
            labels[name] = LabelPolicy(source=source)
        return cls(labels=labels, require_claims=value["require_claims"])


@dataclass(frozen=True, slots=True)
class FactClaim:
    key: str
    label: str
    text: str
    source: str | None

    @classmethod
    def from_dict(cls, value: object) -> "FactClaim":
        if not _exact_keys(value, {"key", "label", "text", "source"}):
            raise RatchetError("invalid_fact_claim")
        key = _string(value["key"], "claim_key")
        if _CLAIM_KEY_RE.fullmatch(key) is None:
            raise RatchetError("invalid_claim_key")
        label = _string(value["label"], "claim_label")
        text = _string(value["text"], "claim_text")
        raw_source = value["source"]
        source = None if raw_source is None else _string(raw_source, "claim_source")
        return cls(key=key, label=label, text=text, source=source)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "text": self.text,
            "source": self.source,
        }


def _evidence_digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finding(*, rule_id: str, subject_key: str, message: str, evidence: object) -> Finding:
    return Finding.create(
        adapter_id=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        rule_id=rule_id,
        subject_kind="fact_output",
        subject_key=subject_key,
        message=message,
        evidence_sha256=_evidence_digest(evidence),
    )


def observe_fact_output(
    document: object,
    policy: object,
    *,
    subject: str,
) -> Observation:
    """Validate one structured response and emit deterministic findings.

    The outer runtime must render only the validated claims. Free-form text outside
    this envelope is deliberately outside the trust boundary and must not bypass the
    gate.
    """
    normalized_subject = _string(subject, "subject")
    parsed_policy = FactOutputPolicy.from_dict(policy)
    if not _exact_keys(document, {"schema", "claims"}):
        raise RatchetError("invalid_fact_output_document")
    if document["schema"] != FACT_OUTPUT_SCHEMA:
        raise RatchetError("invalid_fact_output_schema")
    raw_claims = document["claims"]
    if not isinstance(raw_claims, list) or len(raw_claims) > MAX_CLAIMS:
        raise RatchetError("invalid_fact_output_claims")

    claims = tuple(FactClaim.from_dict(item) for item in raw_claims)
    keys = [claim.key for claim in claims]
    if len(keys) != len(set(keys)):
        raise RatchetError("duplicate_claim_key")

    findings: list[Finding] = []
    if parsed_policy.require_claims and not claims:
        findings.append(
            _finding(
                rule_id="fact-output.claim-required",
                subject_key="document",
                message="fact-output envelope must contain at least one claim",
                evidence=document,
            )
        )

    for claim in claims:
        claim_policy = parsed_policy.labels.get(claim.label)
        if claim_policy is None:
            findings.append(
                _finding(
                    rule_id="fact-output.unsupported-label",
                    subject_key=f"claims/{claim.key}",
                    message=f"claim label is not allowed by policy: {claim.label}",
                    evidence=claim.to_dict(),
                )
            )
            continue
        if claim_policy.source == "required" and claim.source is None:
            findings.append(
                _finding(
                    rule_id="fact-output.source-required",
                    subject_key=f"claims/{claim.key}",
                    message=f"source is required for label: {claim.label}",
                    evidence=claim.to_dict(),
                )
            )
        elif claim_policy.source == "forbidden" and claim.source is not None:
            findings.append(
                _finding(
                    rule_id="fact-output.source-forbidden",
                    subject_key=f"claims/{claim.key}",
                    message=f"source must be omitted for label: {claim.label}",
                    evidence=claim.to_dict(),
                )
            )

    return Observation.create(
        ADAPTER_ID,
        ADAPTER_VERSION,
        normalized_subject,
        findings,
    )
