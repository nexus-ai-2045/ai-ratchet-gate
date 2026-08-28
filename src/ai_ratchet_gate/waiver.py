"""期限付きwaiverの検証。

coreはwaiverの追加・延長・scope変更を承認しない。レビュー済みファイルを
fail-closedで消費し、適用可能なfinding IDだけを返す。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .model import MAX_STRING_BYTES, Observation, RatchetError

WAIVER_SCHEMA = "ai-ratchet-gate.waivers/v1"
_FINDING_ID = re.compile(r"[0-9a-f]{64}")
_EXPIRES_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _nonempty(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise RatchetError(f"invalid_{name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RatchetError(f"invalid_{name}") from error
    if len(encoded) > MAX_STRING_BYTES:
        raise RatchetError(f"invalid_{name}")
    return unicodedata.normalize("NFC", value)


def _sha256_hex(value: object, name: str) -> str:
    digest = _nonempty(value, name)
    if _FINDING_ID.fullmatch(digest) is None:
        raise RatchetError(f"invalid_{name}")
    return digest


def _parse_expires_at(value: object) -> tuple[str, datetime]:
    if type(value) is not str or _EXPIRES_AT.fullmatch(value) is None:
        raise RatchetError("invalid_expires_at")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RatchetError("invalid_expires_at") from error
    if instant.tzinfo is None:
        raise RatchetError("invalid_expires_at")
    return value, instant.astimezone(timezone.utc)


def observation_digest(observation: Observation) -> str:
    """receiptと同じcanonical observation bytesのSHA-256。"""
    return hashlib.sha256(
        _canonical(observation.to_dict()).encode("utf-8")
    ).hexdigest()


def review_binding_sha256(
    *,
    adapter_id: str,
    adapter_version: str,
    subject: str,
    waiver_id: str,
    finding_id: str,
    expires_at: str,
    observation_sha256: str,
) -> str:
    """人間レビュー時点の内容へ束縛するdigest。承認そのものではない。"""
    payload = {
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
        "expires_at": expires_at,
        "finding_id": finding_id,
        "observation_sha256": observation_sha256,
        "subject": subject,
        "waiver_id": waiver_id,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WaiverRecord:
    waiver_id: str
    finding_id: str
    expires_at: str
    observation_sha256: str
    review_binding_sha256: str
    expires_at_utc: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "waiver_id": self.waiver_id,
            "finding_id": self.finding_id,
            "expires_at": self.expires_at,
            "observation_sha256": self.observation_sha256,
            "review_binding_sha256": self.review_binding_sha256,
        }


@dataclass(frozen=True, slots=True)
class WaiverDocument:
    adapter_id: str
    adapter_version: str
    subject: str
    waivers: tuple[WaiverRecord, ...]

    @classmethod
    def from_dict(cls, value: object) -> "WaiverDocument":
        keys = {"schema", "adapter_id", "adapter_version", "subject", "waivers"}
        if not isinstance(value, dict) or set(value) != keys:
            raise RatchetError("invalid_waiver_schema")
        if value["schema"] != WAIVER_SCHEMA:
            raise RatchetError("invalid_waiver_schema")
        if not isinstance(value["waivers"], list):
            raise RatchetError("invalid_waiver_document")
        adapter_id = _nonempty(value["adapter_id"], "adapter_id")
        adapter_version = _nonempty(value["adapter_version"], "adapter_version")
        subject = _nonempty(value["subject"], "subject")
        records: list[WaiverRecord] = []
        seen_ids: set[str] = set()
        seen_findings: set[str] = set()
        for item in value["waivers"]:
            record_keys = {
                "waiver_id",
                "finding_id",
                "expires_at",
                "observation_sha256",
                "review_binding_sha256",
            }
            if not isinstance(item, dict) or set(item) != record_keys:
                raise RatchetError("invalid_waiver_record")
            waiver_id = _nonempty(item["waiver_id"], "waiver_id")
            if waiver_id in seen_ids:
                raise RatchetError("duplicate_waiver_id")
            seen_ids.add(waiver_id)
            finding_id = _sha256_hex(item["finding_id"], "finding_id")
            if finding_id in seen_findings:
                raise RatchetError("duplicate_waiver_finding_id")
            seen_findings.add(finding_id)
            expires_at, expires_at_utc = _parse_expires_at(item["expires_at"])
            observation_sha256 = _sha256_hex(
                item["observation_sha256"], "observation_sha256"
            )
            expected_binding = review_binding_sha256(
                adapter_id=adapter_id,
                adapter_version=adapter_version,
                subject=subject,
                waiver_id=waiver_id,
                finding_id=finding_id,
                expires_at=expires_at,
                observation_sha256=observation_sha256,
            )
            provided_binding = _sha256_hex(
                item["review_binding_sha256"], "review_binding_sha256"
            )
            if provided_binding != expected_binding:
                raise RatchetError("waiver_review_binding_mismatch")
            records.append(
                WaiverRecord(
                    waiver_id=waiver_id,
                    finding_id=finding_id,
                    expires_at=expires_at,
                    observation_sha256=observation_sha256,
                    review_binding_sha256=provided_binding,
                    expires_at_utc=expires_at_utc,
                )
            )
        ordered = tuple(sorted(records, key=lambda item: item.waiver_id))
        return cls(adapter_id, adapter_version, subject, ordered)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": WAIVER_SCHEMA,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "subject": self.subject,
            "waivers": [item.to_dict() for item in self.waivers],
        }


def select_waived_finding_ids(
    document: WaiverDocument,
    observation: Observation,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """レビュー済みwaiverのうち、現在観測に適用できるfinding IDを返す。

    期限切れ・observation不一致のrecordは適用しない（そのfindingはdeny側に残る）。
    documentのadapter/subject不一致は判定不能としてfail-closedする。
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        raise RatchetError("invalid_evaluation_time")
    else:
        now = now.astimezone(timezone.utc)

    subject = unicodedata.normalize("NFC", document.subject)
    if (
        document.adapter_id != observation.adapter_id
        or document.adapter_version != observation.adapter_version
        or subject != observation.subject
    ):
        raise RatchetError("waiver_scope_mismatch")

    current_digest = observation_digest(observation)
    current_ids = {item.finding_id for item in observation.findings}
    selected: list[str] = []
    for record in document.waivers:
        if record.finding_id not in current_ids:
            continue
        if record.observation_sha256 != current_digest:
            continue
        if now >= record.expires_at_utc:
            continue
        selected.append(record.finding_id)
    return tuple(sorted(set(selected)))


def validate_waived_finding_ids(ids: Iterable[str]) -> tuple[str, ...]:
    raw = tuple(ids)
    if any(type(item) is not str or _FINDING_ID.fullmatch(item) is None for item in raw):
        raise RatchetError("invalid_waived_finding_ids")
    ordered = tuple(sorted(raw))
    if len(ordered) != len(set(ordered)):
        raise RatchetError("invalid_waived_finding_ids")
    return ordered
