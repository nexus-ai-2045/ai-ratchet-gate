"""外部操作、対象scope、残務closeoutのopt-in汎用契約。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from .model import RatchetError

OPERATION_RECEIPT_SCHEMA = "ai-ratchet-gate.operation-receipt/v1"
SCOPE_BINDING_SCHEMA = "ai-ratchet-gate.scope-binding/v1"
RESIDUAL_REPORT_SCHEMA = "ai-ratchet-gate.residual-report/v1"

_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "timeout", "unknown"})
_RESIDUAL_CATEGORIES = (
    "task_residual",
    "repo_residual",
    "unrelated_existing_wip",
    "ui_archive_residual",
)
_BLOCKING_CATEGORIES = frozenset(
    {"task_residual", "repo_residual", "ui_archive_residual"}
)
_RESIDUAL_STATUSES = frozenset({"open", "resolved", "unknown"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_OBSERVED_PATHS = 4096
MAX_RESIDUAL_ITEMS = 4096


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except UnicodeEncodeError:
        # 非UTF-8のpathは、値を含まないエラーで拒否する。
        raise RatchetError("non_utf8_canonical_input") from None


def _filesystem_text(path: Path) -> str:
    text = str(path)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise RatchetError("non_utf8_canonical_input") from None
    return text


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _string(value: object, name: str) -> str:
    if type(value) is not str or not value or not value.strip() or "\x00" in value:
        raise RatchetError(f"invalid_{name}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RatchetError(f"invalid_{name}") from error
    if len(encoded) > 4096:
        raise RatchetError(f"invalid_{name}")
    return unicodedata.normalize("NFC", value)


def _sha256(value: object, name: str) -> str:
    text = _string(value, name)
    if _SHA256_RE.fullmatch(text) is None:
        raise RatchetError(f"invalid_{name}")
    return text


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    subject: str
    operation_id: str
    target_id: str
    terminal_status: str
    exit_code: int | None
    terminal_evidence_sha256: str
    expected_state_sha256: str
    readback_state_sha256: str | None
    readback_evidence_sha256: str | None
    status: str
    evidence_consistent: bool
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": OPERATION_RECEIPT_SCHEMA,
            "subject": self.subject,
            "operation_id": self.operation_id,
            "target_id": self.target_id,
            "terminal_status": self.terminal_status,
            "exit_code": self.exit_code,
            "terminal_evidence_sha256": self.terminal_evidence_sha256,
            "expected_state_sha256": self.expected_state_sha256,
            "readback_state_sha256": self.readback_state_sha256,
            "readback_evidence_sha256": self.readback_evidence_sha256,
            "status": self.status,
            "evidence_consistent": self.evidence_consistent,
            "receipt_sha256": self.receipt_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "OperationReceipt":
        """Serialized receiptを再計算し、自己hashと意味条件が一致した時だけ受理する。"""
        required = {
            "schema", "subject", "operation_id", "target_id", "terminal_status",
            "exit_code", "terminal_evidence_sha256", "expected_state_sha256",
            "readback_state_sha256", "readback_evidence_sha256", "status",
            "evidence_consistent", "receipt_sha256",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise RatchetError("invalid_operation_receipt_schema")
        if value["schema"] != OPERATION_RECEIPT_SCHEMA:
            raise RatchetError("invalid_operation_receipt_schema")
        supplied_hash = _sha256(value["receipt_sha256"], "receipt_sha256")
        supplied_body = dict(value)
        del supplied_body["receipt_sha256"]
        if not hmac.compare_digest(_digest(supplied_body), supplied_hash):
            raise RatchetError("operation_receipt_verification_failed")
        rebuilt = build_operation_receipt(
            subject=value["subject"],
            operation_id=value["operation_id"],
            target_id=value["target_id"],
            terminal_status=value["terminal_status"],
            exit_code=value["exit_code"],
            terminal_evidence_sha256=value["terminal_evidence_sha256"],
            expected_state_sha256=value["expected_state_sha256"],
            readback_state_sha256=value["readback_state_sha256"],
            readback_evidence_sha256=value["readback_evidence_sha256"],
        )
        if _canonical(rebuilt.to_dict()) != _canonical(value):
            raise RatchetError("operation_receipt_verification_failed")
        return rebuilt


def build_operation_receipt(
    *,
    subject: str,
    operation_id: str,
    target_id: str,
    terminal_status: str,
    exit_code: int | None,
    terminal_evidence_sha256: str,
    expected_state_sha256: str,
    readback_state_sha256: str | None,
    readback_evidence_sha256: str | None,
) -> OperationReceipt:
    """Command終了と別証拠のreadbackが一致した時だけ整合済みにする。"""
    terminal = _string(terminal_status, "terminal_status")
    if terminal not in _TERMINAL_STATUSES:
        raise RatchetError("invalid_terminal_status")
    if exit_code is not None and type(exit_code) is not int:
        raise RatchetError("invalid_exit_code")
    if (readback_state_sha256 is None) != (readback_evidence_sha256 is None):
        raise RatchetError("incomplete_readback_evidence")

    expected = _sha256(expected_state_sha256, "expected_state_sha256")
    readback_state = (
        _sha256(readback_state_sha256, "readback_state_sha256")
        if readback_state_sha256 is not None
        else None
    )
    readback_evidence = (
        _sha256(readback_evidence_sha256, "readback_evidence_sha256")
        if readback_evidence_sha256 is not None
        else None
    )
    terminal_evidence = _sha256(
        terminal_evidence_sha256, "terminal_evidence_sha256"
    )
    evidence_consistent = (
        terminal == "succeeded"
        and exit_code == 0
        and readback_state == expected
        and readback_evidence is not None
        and readback_evidence != terminal_evidence
    )
    body = {
        "schema": OPERATION_RECEIPT_SCHEMA,
        "subject": _string(subject, "subject"),
        "operation_id": _string(operation_id, "operation_id"),
        "target_id": _string(target_id, "target_id"),
        "terminal_status": terminal,
        "exit_code": exit_code,
        "terminal_evidence_sha256": terminal_evidence,
        "expected_state_sha256": expected,
        "readback_state_sha256": readback_state,
        "readback_evidence_sha256": readback_evidence,
        "status": "evidence_consistent" if evidence_consistent else "denied",
        "evidence_consistent": evidence_consistent,
    }
    return OperationReceipt(
        subject=body["subject"],
        operation_id=body["operation_id"],
        target_id=body["target_id"],
        terminal_status=terminal,
        exit_code=exit_code,
        terminal_evidence_sha256=terminal_evidence,
        expected_state_sha256=expected,
        readback_state_sha256=readback_state,
        readback_evidence_sha256=readback_evidence,
        status=body["status"],
        evidence_consistent=evidence_consistent,
        receipt_sha256=_digest(body),
    )


def verify_operation_receipt(value: object) -> OperationReceipt:
    """未信頼JSONを唯一のconsume経路で再計算検証する。真正性は外部署名の責務。"""
    return OperationReceipt.from_dict(value)


@dataclass(frozen=True, slots=True)
class ScopeBindingReceipt:
    subject: str
    target_root: str
    observed_paths: tuple[str, ...]
    out_of_scope_paths: tuple[str, ...]
    observed_path_count: int
    expected_path_count: int
    enumerator_evidence_sha256: str
    all_supplied_paths_in_scope: bool
    evidence_consistent: bool
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": SCOPE_BINDING_SCHEMA,
            "subject": self.subject,
            "target_root": self.target_root,
            "observed_paths": list(self.observed_paths),
            "out_of_scope_paths": list(self.out_of_scope_paths),
            "observed_path_count": self.observed_path_count,
            "expected_path_count": self.expected_path_count,
            "enumerator_evidence_sha256": self.enumerator_evidence_sha256,
            "all_supplied_paths_in_scope": self.all_supplied_paths_in_scope,
            "evidence_consistent": self.evidence_consistent,
            "receipt_sha256": self.receipt_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ScopeBindingReceipt":
        required = {
            "schema", "subject", "target_root", "observed_paths",
            "out_of_scope_paths", "observed_path_count", "expected_path_count",
            "enumerator_evidence_sha256", "all_supplied_paths_in_scope",
            "evidence_consistent", "receipt_sha256",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise RatchetError("invalid_scope_binding_schema")
        if value["schema"] != SCOPE_BINDING_SCHEMA:
            raise RatchetError("invalid_scope_binding_schema")
        if type(value["target_root"]) is not str:
            raise RatchetError("invalid_target_root")
        if (
            not isinstance(value["observed_paths"], list)
            or len(value["observed_paths"]) > MAX_OBSERVED_PATHS
            or any(type(item) is not str for item in value["observed_paths"])
        ):
            raise RatchetError("invalid_observed_paths")
        supplied_hash = _sha256(value["receipt_sha256"], "receipt_sha256")
        supplied_body = dict(value)
        del supplied_body["receipt_sha256"]
        if not hmac.compare_digest(_digest(supplied_body), supplied_hash):
            raise RatchetError("scope_binding_verification_failed")
        rebuilt = verify_scope_binding(
            subject=value["subject"],
            target_root=Path(value["target_root"]),
            observed_paths=[Path(item) for item in value["observed_paths"]],
            expected_path_count=value["expected_path_count"],
            enumerator_evidence_sha256=value["enumerator_evidence_sha256"],
        )
        if _canonical(rebuilt.to_dict()) != _canonical(value):
            raise RatchetError("scope_binding_verification_failed")
        return rebuilt


def verify_scope_binding(
    *,
    subject: str,
    target_root: Path,
    observed_paths: Iterable[Path],
    expected_path_count: int,
    enumerator_evidence_sha256: str,
) -> ScopeBindingReceipt:
    """明示targetへ観測pathを束縛し、列挙証拠と期待件数へ整合させる。"""
    if not isinstance(target_root, Path):
        raise RatchetError("invalid_target_root")
    _filesystem_text(target_root)
    root = target_root.resolve()
    root_text = _filesystem_text(root)
    if not root.is_dir():
        raise RatchetError("invalid_target_root")

    if type(expected_path_count) is not int or expected_path_count <= 0:
        raise RatchetError("invalid_expected_path_count")
    enumerator_evidence = _sha256(
        enumerator_evidence_sha256, "enumerator_evidence_sha256"
    )
    normalized: list[str] = []
    outside: list[str] = []
    try:
        iterator = iter(observed_paths)
    except TypeError as error:
        raise RatchetError("invalid_observed_paths") from error
    for index, raw_path in enumerate(iterator):
        if index >= MAX_OBSERVED_PATHS:
            raise RatchetError("too_many_observed_paths")
        if not isinstance(raw_path, Path):
            raise RatchetError("invalid_observed_path")
        _filesystem_text(raw_path)
        path = (root / raw_path).resolve() if not raw_path.is_absolute() else raw_path.resolve()
        text = _filesystem_text(path)
        normalized.append(text)
        try:
            path.relative_to(root)
        except ValueError:
            outside.append(text)

    observed = tuple(sorted(set(normalized)))
    out_of_scope = tuple(sorted(set(outside)))
    all_in_scope = not out_of_scope
    evidence_consistent = all_in_scope and len(observed) == expected_path_count
    body = {
        "schema": SCOPE_BINDING_SCHEMA,
        "subject": _string(subject, "subject"),
        "target_root": root_text,
        "observed_paths": list(observed),
        "out_of_scope_paths": list(out_of_scope),
        "observed_path_count": len(observed),
        "expected_path_count": expected_path_count,
        "enumerator_evidence_sha256": enumerator_evidence,
        "all_supplied_paths_in_scope": all_in_scope,
        "evidence_consistent": evidence_consistent,
    }
    return ScopeBindingReceipt(
        subject=body["subject"],
        target_root=body["target_root"],
        observed_paths=observed,
        out_of_scope_paths=out_of_scope,
        observed_path_count=len(observed),
        expected_path_count=expected_path_count,
        enumerator_evidence_sha256=enumerator_evidence,
        all_supplied_paths_in_scope=all_in_scope,
        evidence_consistent=evidence_consistent,
        receipt_sha256=_digest(body),
    )


def verify_scope_binding_receipt(value: object) -> ScopeBindingReceipt:
    """保存済みscope receiptをexact schema・自己hash・意味条件で再検証する。"""
    return ScopeBindingReceipt.from_dict(value)


@dataclass(frozen=True, slots=True)
class ResidualItem:
    category: str
    key: str
    owner: str
    status: str
    evidence_sha256: str

    @classmethod
    def create(
        cls,
        *,
        category: str,
        key: str,
        owner: str,
        status: str,
        evidence_sha256: str,
    ) -> "ResidualItem":
        category_value = _string(category, "residual_category")
        if category_value not in _RESIDUAL_CATEGORIES:
            raise RatchetError("invalid_residual_category")
        status_value = _string(status, "residual_status")
        if status_value not in _RESIDUAL_STATUSES:
            raise RatchetError("invalid_residual_status")
        return cls(
            category=category_value,
            key=_string(key, "residual_key"),
            owner=_string(owner, "residual_owner"),
            status=status_value,
            evidence_sha256=_sha256(evidence_sha256, "evidence_sha256"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "category": self.category,
            "key": self.key,
            "owner": self.owner,
            "status": self.status,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResidualItem":
        required = {"category", "key", "owner", "status", "evidence_sha256"}
        if not isinstance(value, dict) or set(value) != required:
            raise RatchetError("invalid_residual_item")
        return cls.create(
            category=value["category"], key=value["key"], owner=value["owner"],
            status=value["status"], evidence_sha256=value["evidence_sha256"],
        )


@dataclass(frozen=True, slots=True)
class ResidualReport:
    subject: str
    items: tuple[ResidualItem, ...]
    counts: Mapping[str, int]
    blocking_keys: tuple[str, ...]
    residual_zero: bool
    classifier_evidence_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": RESIDUAL_REPORT_SCHEMA,
            "subject": self.subject,
            "items": [item.to_dict() for item in self.items],
            "counts": dict(self.counts),
            "blocking_keys": list(self.blocking_keys),
            "residual_zero": self.residual_zero,
            "classifier_evidence_sha256": self.classifier_evidence_sha256,
            "receipt_sha256": self.receipt_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ResidualReport":
        required = {
            "schema", "subject", "items", "counts", "blocking_keys",
            "residual_zero", "classifier_evidence_sha256", "receipt_sha256",
        }
        if not isinstance(value, dict) or set(value) != required:
            raise RatchetError("invalid_residual_report_schema")
        if value["schema"] != RESIDUAL_REPORT_SCHEMA:
            raise RatchetError("invalid_residual_report_schema")
        if (
            not isinstance(value["items"], list)
            or len(value["items"]) > MAX_RESIDUAL_ITEMS
        ):
            raise RatchetError("invalid_residual_items")
        supplied_hash = _sha256(value["receipt_sha256"], "receipt_sha256")
        supplied_body = dict(value)
        del supplied_body["receipt_sha256"]
        if not hmac.compare_digest(_digest(supplied_body), supplied_hash):
            raise RatchetError("residual_report_verification_failed")
        rebuilt = classify_residuals(
            subject=value["subject"],
            items=[ResidualItem.from_dict(item) for item in value["items"]],
            classifier_evidence_sha256=value["classifier_evidence_sha256"],
        )
        if _canonical(rebuilt.to_dict()) != _canonical(value):
            raise RatchetError("residual_report_verification_failed")
        return rebuilt


def classify_residuals(
    *, subject: str, items: Iterable[ResidualItem], classifier_evidence_sha256: str
) -> ResidualReport:
    """task固有残務と証拠付きの無関係WIPを混同せずcloseout判定する。"""
    try:
        bounded: list[ResidualItem] = []
        for index, item in enumerate(items):
            if index >= MAX_RESIDUAL_ITEMS:
                raise RatchetError("too_many_residual_items")
            bounded.append(item)
        normalized = tuple(
            sorted(bounded, key=lambda item: (item.category, item.key, item.owner))
        )
    except (AttributeError, TypeError) as error:
        raise RatchetError("invalid_residual_items") from error
    identities = [(item.category, item.key) for item in normalized]
    if len(identities) != len(set(identities)):
        raise RatchetError("duplicate_residual_item")
    for item in normalized:
        if ResidualItem.create(**item.to_dict()) != item:
            raise RatchetError("invalid_residual_item")

    counts = {category: 0 for category in _RESIDUAL_CATEGORIES}
    blocking: list[str] = []
    for item in normalized:
        if item.status != "resolved":
            counts[item.category] += 1
            if item.category in _BLOCKING_CATEGORIES:
                blocking.append(f"{item.category}/{item.key}")
    blocking_keys = tuple(sorted(blocking))
    classifier_evidence = _sha256(
        classifier_evidence_sha256, "classifier_evidence_sha256"
    )
    body = {
        "schema": RESIDUAL_REPORT_SCHEMA,
        "subject": _string(subject, "subject"),
        "items": [item.to_dict() for item in normalized],
        "counts": counts,
        "blocking_keys": list(blocking_keys),
        "residual_zero": not blocking_keys,
        "classifier_evidence_sha256": classifier_evidence,
    }
    return ResidualReport(
        subject=body["subject"],
        items=normalized,
        counts=MappingProxyType(counts),
        blocking_keys=blocking_keys,
        residual_zero=body["residual_zero"],
        classifier_evidence_sha256=classifier_evidence,
        receipt_sha256=_digest(body),
    )


def verify_residual_report(value: object) -> ResidualReport:
    """保存済み残務reportをexact schema・自己hash・意味条件で再検証する。"""
    return ResidualReport.from_dict(value)
