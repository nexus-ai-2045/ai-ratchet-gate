from __future__ import annotations

import json
from pathlib import Path

from ai_ratchet_gate.cli import main
from ai_ratchet_gate.model import Finding


def test_evaluate_cli_writes_receipt_and_denies_new_finding(tmp_path: Path) -> None:
    item = Finding.create(
        adapter_id="example.guard",
        adapter_version="1",
        rule_id="rule",
        subject_kind="artifact",
        subject_key="result.json",
        message="bad",
        evidence_sha256="b" * 64,
    )
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    receipt = tmp_path / "receipt.json"
    observation.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.observation/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": "repo:abc",
                "findings": [item.to_dict()],
            }
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": "repo:abc",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )

    assert main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--receipt",
            str(receipt),
            "--expected-subject",
            "repo:abc",
        ]
    ) == 1
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "deny"
    assert payload["receipt_sha256"]


def test_evaluate_cli_rejects_unknown_schema(tmp_path: Path, capsys) -> None:
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text('{"schema":"unknown"}', encoding="utf-8")
    baseline.write_text('{"schema":"unknown"}', encoding="utf-8")
    assert main(
        [
            "evaluate", "--observation", str(observation), "--baseline", str(baseline),
            "--expected-subject", "repo:abc",
        ]
    ) == 2
    assert "tool_error" in capsys.readouterr().out


def test_receipt_does_not_echo_untrusted_message(tmp_path: Path, capsys) -> None:
    secret = "github_pat_" + "S" * 30
    item = Finding.create(
        adapter_id="example.guard", adapter_version="1", rule_id="rule",
        subject_kind="artifact", subject_key="result.json", message=secret,
        evidence_sha256="c" * 64,
    )
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(json.dumps({
        "schema": "ai-ratchet-gate.observation/v1", "adapter_id": "example.guard",
        "adapter_version": "1", "subject": "repo:abc", "findings": [item.to_dict()],
    }), encoding="utf-8")
    baseline.write_text(json.dumps({
        "schema": "ai-ratchet-gate.baseline/v1", "adapter_id": "example.guard",
        "adapter_version": "1", "policy": "new_only", "finding_ids": [],
        "subject": "repo:abc",
    }), encoding="utf-8")
    assert main(["evaluate", "--observation", str(observation), "--baseline", str(baseline),
                 "--expected-subject", "repo:abc"]) == 1
    assert secret not in capsys.readouterr().out


def test_evaluate_cli_rejects_subject_replay(tmp_path: Path) -> None:
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(json.dumps({
        "schema": "ai-ratchet-gate.observation/v1", "adapter_id": "example.guard",
        "adapter_version": "1", "subject": "repo:old", "findings": [],
    }), encoding="utf-8")
    baseline.write_text(json.dumps({
        "schema": "ai-ratchet-gate.baseline/v1", "adapter_id": "example.guard",
        "adapter_version": "1", "policy": "new_only", "finding_ids": [],
        "subject": "repo:old",
    }), encoding="utf-8")
    assert main(["evaluate", "--observation", str(observation), "--baseline", str(baseline),
                 "--expected-subject", "repo:new"]) == 2


def test_evaluate_cli_rejects_baseline_from_another_subject(tmp_path: Path) -> None:
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(json.dumps({
        "schema": "ai-ratchet-gate.observation/v1", "adapter_id": "example.guard",
        "adapter_version": "1", "subject": "repo:new", "findings": [],
    }), encoding="utf-8")
    baseline.write_text(json.dumps({
        "schema": "ai-ratchet-gate.baseline/v1", "adapter_id": "example.guard",
        "adapter_version": "1", "subject": "repo:old", "policy": "new_only",
        "finding_ids": [],
    }), encoding="utf-8")
    assert main(["evaluate", "--observation", str(observation), "--baseline", str(baseline),
                 "--expected-subject", "repo:new"]) == 2


def test_checkout_shim_exports_generic_api() -> None:
    import ai_ratchet_gate

    assert ai_ratchet_gate.Finding is Finding
    assert callable(ai_ratchet_gate.evaluate)
