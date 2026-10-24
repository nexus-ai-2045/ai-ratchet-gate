from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ai_ratchet_gate.model import RatchetError
from ai_ratchet_gate.operation_contracts import (
    MAX_OBSERVED_PATHS,
    MAX_RESIDUAL_ITEMS,
    ResidualItem,
    build_operation_receipt,
    classify_residuals,
    verify_operation_receipt,
    verify_residual_report,
    verify_scope_binding,
    verify_scope_binding_receipt,
)


SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()
SHA_C = hashlib.sha256(b"c").hexdigest()


def _rehash_payload(payload: dict[str, object]) -> None:
    body = dict(payload)
    body.pop("receipt_sha256")
    payload["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def test_operation_requires_terminal_success_and_independent_readback() -> None:
    receipt = build_operation_receipt(
        subject="repo:example",
        operation_id="push:main",
        target_id="github:owner/example@main",
        terminal_status="succeeded",
        exit_code=0,
        terminal_evidence_sha256=SHA_A,
        expected_state_sha256=SHA_B,
        readback_state_sha256=SHA_B,
        readback_evidence_sha256=SHA_C,
    )

    assert receipt.status == "evidence_consistent"
    assert receipt.evidence_consistent is True
    assert receipt.to_dict()["receipt_sha256"] == receipt.receipt_sha256
    assert verify_operation_receipt(receipt.to_dict()) == receipt


@pytest.mark.parametrize(
    ("terminal_status", "exit_code", "readback_state", "readback_evidence"),
    [
        ("succeeded", 0, SHA_A, SHA_C),
        ("succeeded", 0, None, None),
        ("failed", 1, SHA_B, SHA_C),
        ("timeout", None, SHA_B, SHA_C),
        ("unknown", None, SHA_B, SHA_C),
    ],
)
def test_operation_never_trusts_exit_or_mutation_without_matching_readback(
    terminal_status: str,
    exit_code: int | None,
    readback_state: str | None,
    readback_evidence: str | None,
) -> None:
    receipt = build_operation_receipt(
        subject="repo:example",
        operation_id="push:main",
        target_id="github:owner/example@main",
        terminal_status=terminal_status,
        exit_code=exit_code,
        terminal_evidence_sha256=SHA_A,
        expected_state_sha256=SHA_B,
        readback_state_sha256=readback_state,
        readback_evidence_sha256=readback_evidence,
    )

    assert receipt.status == "denied"
    assert receipt.evidence_consistent is False


def test_operation_preserves_negative_signal_returncode_as_denied() -> None:
    receipt = build_operation_receipt(
        subject="repo:example", operation_id="push:main",
        target_id="github:example@main", terminal_status="failed", exit_code=-9,
        terminal_evidence_sha256=SHA_A, expected_state_sha256=SHA_B,
        readback_state_sha256=None, readback_evidence_sha256=None,
    )

    assert receipt.exit_code == -9
    assert receipt.status == "denied"
    assert receipt.evidence_consistent is False


def test_operation_rejects_same_terminal_and_readback_evidence() -> None:
    receipt = build_operation_receipt(
        subject="repo:example", operation_id="push:main",
        target_id="github:example@main", terminal_status="succeeded", exit_code=0,
        terminal_evidence_sha256=SHA_A, expected_state_sha256=SHA_B,
        readback_state_sha256=SHA_B, readback_evidence_sha256=SHA_A,
    )

    assert receipt.status == "denied"


def test_operation_consume_path_rejects_tampered_receipt() -> None:
    receipt = build_operation_receipt(
        subject="repo:example", operation_id="push:main",
        target_id="github:example@main", terminal_status="succeeded", exit_code=0,
        terminal_evidence_sha256=SHA_A, expected_state_sha256=SHA_B,
        readback_state_sha256=SHA_B, readback_evidence_sha256=SHA_C,
    )
    payload = receipt.to_dict()
    payload["status"] = "denied"

    with pytest.raises(RatchetError, match="verification_failed"):
        verify_operation_receipt(payload)


def test_operation_consume_path_rejects_bool_as_int() -> None:
    receipt = build_operation_receipt(
        subject="repo:example", operation_id="push:main",
        target_id="github:example@main", terminal_status="succeeded", exit_code=0,
        terminal_evidence_sha256=SHA_A, expected_state_sha256=SHA_B,
        readback_state_sha256=SHA_B, readback_evidence_sha256=SHA_C,
    )
    payload = receipt.to_dict()
    payload["evidence_consistent"] = 1
    _rehash_payload(payload)

    with pytest.raises(RatchetError, match="verification_failed"):
        verify_operation_receipt(payload)


def test_scope_binding_uses_explicit_target_not_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    child = parent / ".repos" / "child"
    child_file = child / "src" / "app.py"
    child_file.parent.mkdir(parents=True)
    child_file.write_text("pass\n", encoding="utf-8")
    monkeypatch.chdir(parent)

    receipt = verify_scope_binding(
        subject="repo:child",
        target_root=child,
        observed_paths=[child_file],
        expected_path_count=1,
        enumerator_evidence_sha256=SHA_A,
    )

    assert receipt.evidence_consistent is True
    assert receipt.all_supplied_paths_in_scope is True
    assert receipt.out_of_scope_paths == ()
    assert verify_scope_binding_receipt(receipt.to_dict()) == receipt


def test_scope_binding_fails_closed_on_parent_repo_mixing(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    child = parent / ".repos" / "child"
    child.mkdir(parents=True)
    parent_file = parent / "parent-only.py"
    parent_file.write_text("pass\n", encoding="utf-8")

    receipt = verify_scope_binding(
        subject="repo:child",
        target_root=child,
        observed_paths=[parent_file],
        expected_path_count=1,
        enumerator_evidence_sha256=SHA_A,
    )

    assert receipt.evidence_consistent is False
    assert receipt.all_supplied_paths_in_scope is False
    assert receipt.out_of_scope_paths == (str(parent_file.resolve()),)


def test_scope_binding_rejects_empty_completion_claim(tmp_path: Path) -> None:
    with pytest.raises(RatchetError, match="invalid_expected_path_count"):
        verify_scope_binding(
            subject="repo:empty", target_root=tmp_path, observed_paths=[],
            expected_path_count=0, enumerator_evidence_sha256=SHA_A,
        )


def test_scope_binding_caps_observed_paths(tmp_path: Path) -> None:
    paths = (Path(f"item-{index}") for index in range(MAX_OBSERVED_PATHS + 1))
    with pytest.raises(RatchetError, match="too_many_observed_paths"):
        verify_scope_binding(
            subject="repo:many", target_root=tmp_path, observed_paths=paths,
            expected_path_count=MAX_OBSERVED_PATHS + 1,
            enumerator_evidence_sha256=SHA_A,
        )


def test_scope_consume_path_rejects_tampered_completion(tmp_path: Path) -> None:
    item = tmp_path / "item"
    item.write_text("x", encoding="utf-8")
    receipt = verify_scope_binding(
        subject="repo:scope", target_root=tmp_path, observed_paths=[item],
        expected_path_count=1, enumerator_evidence_sha256=SHA_A,
    )
    payload = receipt.to_dict()
    payload["evidence_consistent"] = False
    _rehash_payload(payload)

    with pytest.raises(RatchetError, match="verification_failed"):
        verify_scope_binding_receipt(payload)


def test_residual_report_separates_unrelated_existing_wip() -> None:
    report = classify_residuals(
        subject="task:example",
        classifier_evidence_sha256=SHA_C,
        items=[
            ResidualItem.create(
                category="unrelated_existing_wip",
                key="other-owner-dirty-tree",
                owner="other-owner",
                status="open",
                evidence_sha256=SHA_A,
            )
        ],
    )

    assert report.residual_zero is True
    assert report.blocking_keys == ()
    assert report.counts["unrelated_existing_wip"] == 1
    assert verify_residual_report(report.to_dict()) == report


@pytest.mark.parametrize("category", ["task_residual", "repo_residual", "ui_archive_residual"])
def test_residual_report_blocks_owned_or_required_residuals(category: str) -> None:
    report = classify_residuals(
        subject="task:example",
        classifier_evidence_sha256=SHA_C,
        items=[
            ResidualItem.create(
                category=category,
                key="remaining",
                owner="task-owner",
                status="open",
                evidence_sha256=SHA_A,
            )
        ],
    )

    assert report.residual_zero is False
    assert report.blocking_keys == (f"{category}/remaining",)


def test_contracts_reject_unknown_values() -> None:
    with pytest.raises(RatchetError, match="invalid_terminal_status"):
        build_operation_receipt(
            subject="repo:example",
            operation_id="push:main",
            target_id="github:owner/example@main",
            terminal_status="maybe",
            exit_code=0,
            terminal_evidence_sha256=SHA_A,
            expected_state_sha256=SHA_B,
            readback_state_sha256=SHA_B,
            readback_evidence_sha256=SHA_C,
        )

    with pytest.raises(RatchetError, match="invalid_residual_category"):
        ResidualItem.create(
            category="mystery",
            key="remaining",
            owner="task-owner",
            status="open",
            evidence_sha256=SHA_A,
        )


def test_residual_report_caps_items() -> None:
    item = ResidualItem.create(
        category="task_residual", key="remaining", owner="owner",
        status="open", evidence_sha256=SHA_A,
    )
    with pytest.raises(RatchetError, match="too_many_residual_items"):
        classify_residuals(
            subject="task:many",
            items=(item for _ in range(MAX_RESIDUAL_ITEMS + 1)),
            classifier_evidence_sha256=SHA_C,
        )


def test_residual_consume_path_rejects_tampered_zero() -> None:
    report = classify_residuals(
        subject="task:example",
        items=[ResidualItem.create(
            category="task_residual", key="remaining", owner="owner",
            status="open", evidence_sha256=SHA_A,
        )],
        classifier_evidence_sha256=SHA_C,
    )
    payload = report.to_dict()
    payload["residual_zero"] = True
    _rehash_payload(payload)

    with pytest.raises(RatchetError, match="verification_failed"):
        verify_residual_report(payload)
