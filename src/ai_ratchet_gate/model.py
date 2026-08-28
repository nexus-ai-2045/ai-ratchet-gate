"""汎用ラチェット判定の値オブジェクト。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


class RatchetError(ValueError):
    """入力を安全に判定できない場合のfail-closedエラー。"""


MAX_STRING_BYTES = 4096
MAX_FINDINGS = 10_000


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _nonempty(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise RatchetError(f"invalid_{name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        # json.loads は lone surrogate を許容するが、UTF-8 へは落とせない
        raise RatchetError(f"invalid_{name}") from error
    if len(encoded) > MAX_STRING_BYTES:
        raise RatchetError(f"invalid_{name}")
    return unicodedata.normalize("NFC", value)


def _subject_key(value: object) -> str:
    key = _nonempty(value, "subject_key")
    if key.startswith("/") or any(
        part in {"", ".", ".."} for part in key.split("/")
    ):
        raise RatchetError("invalid_subject_key")
    return key


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    adapter_id: str
    adapter_version: str
    rule_id: str
    subject_kind: str
    subject_key: str
    message: str
    evidence_sha256: str

    @classmethod
    def create(
        cls,
        *,
        adapter_id: str,
        adapter_version: str,
        rule_id: str,
        subject_kind: str,
        subject_key: str,
        message: str,
        evidence_sha256: str,
    ) -> "Finding":
        identity = {
            "adapter_id": _nonempty(adapter_id, "adapter_id"),
            "rule_id": _nonempty(rule_id, "rule_id"),
            "subject_kind": _nonempty(subject_kind, "subject_kind"),
            "subject_key": _subject_key(subject_key),
        }
        evidence = _nonempty(evidence_sha256, "evidence_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", evidence) is None:
            raise RatchetError("invalid_evidence_sha256")
        return cls(
            finding_id=hashlib.sha256(_canonical(identity)).hexdigest(),
            adapter_id=identity["adapter_id"],
            adapter_version=_nonempty(adapter_version, "adapter_version"),
            rule_id=identity["rule_id"],
            subject_kind=identity["subject_kind"],
            subject_key=identity["subject_key"],
            message=_nonempty(message, "message"),
            evidence_sha256=evidence,
        )

    @classmethod
    def from_dict(cls, value: object) -> "Finding":
        keys = {
            "finding_id", "adapter_id", "adapter_version", "rule_id",
            "subject_kind", "subject_key", "message", "evidence_sha256",
        }
        if not isinstance(value, dict) or set(value) != keys:
            raise RatchetError("invalid_finding")
        result = cls.create(**{key: value[key] for key in keys - {"finding_id"}})
        if value["finding_id"] != result.finding_id:
            raise RatchetError("finding_id_mismatch")
        return result

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class Observation:
    adapter_id: str
    adapter_version: str
    subject: str
    findings: tuple[Finding, ...]

    @classmethod
    def create(
        cls, adapter_id: str, adapter_version: str, subject: str,
        findings: Iterable[Finding],
    ) -> "Observation":
        normalized = tuple(sorted(findings, key=lambda item: item.finding_id))
        if len(normalized) > MAX_FINDINGS:
            raise RatchetError("too_many_findings")
        ids = [item.finding_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise RatchetError("duplicate_finding_id")
        aid = _nonempty(adapter_id, "adapter_id")
        version = _nonempty(adapter_version, "adapter_version")
        if any(
            item.adapter_id != aid or item.adapter_version != version
            for item in normalized
        ):
            raise RatchetError("adapter_identity_mismatch")
        return cls(aid, version, _nonempty(subject, "subject"), normalized)

    def to_dict(self) -> dict[str, object]:
        """`ai-ratchet-gate.observation/v1` 形式。`evaluate` がそのまま受理する。"""
        return {
            "schema": "ai-ratchet-gate.observation/v1",
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "subject": self.subject,
            "findings": [item.to_dict() for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class Decision:
    observation: Observation
    mode: str
    policy: str
    status: str
    accepted: tuple[str, ...]
    new: tuple[str, ...]
    resolved: tuple[str, ...]
    baseline_ids: tuple[str, ...]
    waived: tuple[str, ...] = ()
