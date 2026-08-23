from __future__ import annotations

import json
import sys
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


def test_evaluate_cli_maps_deep_json_nesting_to_tool_error(
    tmp_path: Path, capsys
) -> None:
    deep = "[" * 10_000 + "]" * 10_000
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(deep, encoding="utf-8")
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
            "--expected-subject",
            "repo:abc",
        ]
    ) == 2
    assert "tool_error" in capsys.readouterr().out


def test_evaluate_cli_rejects_malformed_policy_type(tmp_path: Path, capsys) -> None:
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.observation/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": "repo:abc",
                "findings": [],
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
                "policy": ["new_only"],
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
            "--expected-subject",
            "repo:abc",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "tool_error", "error": "invalid_policy"}


def test_evaluate_cli_rejects_lone_surrogate_as_tool_error(
    tmp_path: Path, capsys
) -> None:
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    # json.loads は lone surrogate を受理するが、検証経路で fail-closed にする
    observation.write_text(
        '{"schema":"ai-ratchet-gate.observation/v1","adapter_id":"example.guard",'
        '"adapter_version":"1","subject":"repo:abc","findings":[]}'.replace(
            '"subject":"repo:abc"', '"subject":"\\ud800"'
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": "\ud800",
                "policy": "new_only",
                "finding_ids": [],
            },
            ensure_ascii=True,
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
            "--expected-subject",
            "\ud800",
        ]
    ) == 2
    assert "tool_error" in capsys.readouterr().out


def _write_allow_pair(tmp_path: Path) -> tuple[Path, Path]:
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.observation/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": "repo:abc",
                "findings": [],
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
    return observation, baseline


def test_evaluate_cli_rejects_receipt_path_aliasing_observation(
    tmp_path: Path, capsys
) -> None:
    observation, baseline = _write_allow_pair(tmp_path)
    before = observation.read_text(encoding="utf-8")
    assert main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--receipt",
            str(observation),
            "--expected-subject",
            "repo:abc",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "tool_error", "error": "receipt_path_aliases_input"}
    assert observation.read_text(encoding="utf-8") == before


def test_evaluate_cli_rejects_receipt_symlink_to_baseline(
    tmp_path: Path, capsys
) -> None:
    observation, baseline = _write_allow_pair(tmp_path)
    receipt = tmp_path / "receipt-link.json"
    receipt.symlink_to(baseline)
    before = baseline.read_text(encoding="utf-8")
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
    ) == 2
    assert "receipt_path_aliases_input" in capsys.readouterr().out
    assert baseline.read_text(encoding="utf-8") == before


def test_evaluate_cli_rejects_receipt_hardlink_to_observation(
    tmp_path: Path, capsys
) -> None:
    observation, baseline = _write_allow_pair(tmp_path)
    receipt = tmp_path / "receipt-hardlink.json"
    try:
        receipt.hardlink_to(observation)
    except OSError:
        # 一部FSでは hardlink 不可。symlink ケースは別テストで担保する。
        return
    before = observation.read_text(encoding="utf-8")
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
    ) == 2
    assert "receipt_path_aliases_input" in capsys.readouterr().out
    assert observation.read_text(encoding="utf-8") == before


def test_evaluate_cli_accepts_nfd_subject_identities(tmp_path: Path, capsys) -> None:
    # cafe + combining acute (NFD)。Observation側はNFC化されるため比較側も揃える。
    nfd_subject = "cafe\u0301"
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.observation/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": nfd_subject,
                "findings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": nfd_subject,
                "policy": "new_only",
                "finding_ids": [],
            },
            ensure_ascii=False,
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
            "--expected-subject",
            nfd_subject,
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"]["status"] == "allow"


def test_evaluate_cli_rejects_duplicate_json_object_keys(
    tmp_path: Path, capsys
) -> None:
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    # 先に不正schema、後に正当schema。last-winsだと通過してしまう。
    observation.write_text(
        '{"schema":"unknown","schema":"ai-ratchet-gate.observation/v1",'
        '"adapter_id":"example.guard","adapter_version":"1",'
        '"subject":"repo:abc","findings":[]}',
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
            "--expected-subject",
            "repo:abc",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "tool_error", "error": "duplicate_json_object_key"}


def test_evaluate_cli_maps_oversized_json_integer_to_tool_error(
    tmp_path: Path, capsys
) -> None:
    import sys

    digits = sys.get_int_max_str_digits() + 10
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text("1" + ("0" * digits), encoding="utf-8")
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
            "--expected-subject",
            "repo:abc",
        ]
    ) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "tool_error", "error": "invalid_json_input"}


def test_evaluate_cli_emits_utf8_receipt_under_ascii_stdout(
    tmp_path: Path, monkeypatch
) -> None:
    class _BytesCollector:
        def __init__(self) -> None:
            self.chunks: list[bytes] = []

        def write(self, data: bytes) -> int:
            self.chunks.append(data)
            return len(data)

        def flush(self) -> None:
            return None

        def getvalue(self) -> bytes:
            return b"".join(self.chunks)

    class AsciiStdout:
        encoding = "ascii"

        def __init__(self) -> None:
            self.buffer = _BytesCollector()

        def write(self, text: str) -> int:
            text.encode(self.encoding)
            raise AssertionError("text write should not be used for non-ascii")

        def flush(self) -> None:
            return None

    subject = "repo:日本語"
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    observation.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.observation/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": subject,
                "findings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": subject,
                "policy": "new_only",
                "finding_ids": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fake = AsciiStdout()
    monkeypatch.setattr(sys, "stdout", fake)
    assert main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--expected-subject",
            subject,
        ]
    ) == 0
    payload = json.loads(fake.buffer.getvalue().decode("utf-8"))
    assert payload["decision"]["status"] == "allow"
    assert subject in fake.buffer.getvalue().decode("utf-8")
