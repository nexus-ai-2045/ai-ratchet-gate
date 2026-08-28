from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_ratchet_gate.fact_output import (
    FACT_EVIDENCE_SCHEMA,
    FACT_OUTPUT_POLICY_SCHEMA,
    FACT_OUTPUT_SCHEMA,
    canonical_sha256,
    observe_fact_output,
)
from ai_ratchet_gate.fact_output_cli import main as fact_output_main
from ai_ratchet_gate.model import RatchetError


KNOWN_SOURCE = "github:pull/16@abc123"
KNOWN_SOURCE_DIGEST = "a" * 64


def _policy() -> dict[str, object]:
    return {
        "schema": FACT_OUTPUT_POLICY_SCHEMA,
        "labels": {
            "fact": {"source": "required"},
            "user_signal": {"source": "optional"},
            "inference": {"source": "forbidden"},
            "unknown": {"source": "forbidden"},
        },
        "require_claims": True,
    }


def _evidence(*source_ids: str) -> dict[str, object]:
    return {
        "schema": FACT_EVIDENCE_SCHEMA,
        "sources": [
            {"id": source_id, "evidence_sha256": KNOWN_SOURCE_DIGEST}
            for source_id in source_ids
        ],
    }


def _document(*claims: dict[str, object]) -> dict[str, object]:
    return {"schema": FACT_OUTPUT_SCHEMA, "claims": list(claims)}


def _claim(
    key: str,
    label: str,
    text: str,
    source: str | None,
) -> dict[str, object]:
    return {"key": key, "label": label, "text": text, "source": source}


def test_valid_fact_output_has_no_findings() -> None:
    observation = observe_fact_output(
        _document(
            _claim("c1", "fact", "HEAD is abc123", KNOWN_SOURCE),
            _claim("c2", "user_signal", "avoid reinvention", None),
            _claim("c3", "inference", "a wrapper is the likely enforcement point", None),
        ),
        _policy(),
        _evidence(KNOWN_SOURCE),
        subject="turn:example",
    )

    assert observation.findings == ()
    assert observation.adapter_id == "agent.fact_output"


def test_missing_source_for_fact_is_deterministic_finding() -> None:
    first = observe_fact_output(
        _document(_claim("c1", "fact", "unverified claim", None)),
        _policy(),
        _evidence(),
        subject="turn:example",
    )
    second = observe_fact_output(
        _document(_claim("c1", "fact", "unverified claim", None)),
        _policy(),
        _evidence(),
        subject="turn:example",
    )

    assert len(first.findings) == 1
    assert first.findings[0].rule_id == "fact-output.source-required"
    assert first.findings[0].finding_id == second.findings[0].finding_id


def test_invented_source_is_denied_even_when_source_is_required() -> None:
    observation = observe_fact_output(
        _document(_claim("c1", "fact", "made-up evidence pointer", "github:fake@deadbeef")),
        _policy(),
        _evidence(KNOWN_SOURCE),
        subject="turn:example",
    )

    assert [finding.rule_id for finding in observation.findings] == [
        "fact-output.unknown-source"
    ]


def test_optional_source_must_also_exist_in_registry() -> None:
    observation = observe_fact_output(
        _document(_claim("c1", "user_signal", "user said this", "user:invented")),
        _policy(),
        _evidence(),
        subject="turn:example",
    )

    assert [finding.rule_id for finding in observation.findings] == [
        "fact-output.unknown-source"
    ]


def test_unsupported_label_is_denied() -> None:
    observation = observe_fact_output(
        _document(_claim("c1", "remembered", "I think this was decided", None)),
        _policy(),
        _evidence(),
        subject="turn:example",
    )

    assert [finding.rule_id for finding in observation.findings] == [
        "fact-output.unsupported-label"
    ]


def test_required_claims_reject_empty_envelope() -> None:
    observation = observe_fact_output(
        _document(),
        _policy(),
        _evidence(),
        subject="turn:example",
    )

    assert [finding.rule_id for finding in observation.findings] == [
        "fact-output.claim-required"
    ]


def test_forbidden_source_is_denied() -> None:
    observation = observe_fact_output(
        _document(_claim("c1", "inference", "likely", KNOWN_SOURCE)),
        _policy(),
        _evidence(KNOWN_SOURCE),
        subject="turn:example",
    )

    assert [finding.rule_id for finding in observation.findings] == [
        "fact-output.source-forbidden"
    ]


def test_duplicate_claim_key_fails_closed() -> None:
    with pytest.raises(RatchetError, match="duplicate_claim_key"):
        observe_fact_output(
            _document(
                _claim("same", "unknown", "first", None),
                _claim("same", "unknown", "second", None),
            ),
            _policy(),
            _evidence(),
            subject="turn:example",
        )


def test_duplicate_evidence_source_fails_closed() -> None:
    evidence = {
        "schema": FACT_EVIDENCE_SCHEMA,
        "sources": [
            {"id": KNOWN_SOURCE, "evidence_sha256": KNOWN_SOURCE_DIGEST},
            {"id": KNOWN_SOURCE, "evidence_sha256": "b" * 64},
        ],
    }
    with pytest.raises(RatchetError, match="duplicate_source_id"):
        observe_fact_output(
            _document(_claim("c1", "fact", "ok", KNOWN_SOURCE)),
            _policy(),
            evidence,
            subject="turn:example",
        )


def test_policy_can_change_label_vocabulary_without_code_change() -> None:
    policy = {
        "schema": FACT_OUTPUT_POLICY_SCHEMA,
        "labels": {"verified": {"source": "required"}},
        "require_claims": True,
    }
    observation = observe_fact_output(
        _document(_claim("c1", "verified", "ok", "test:fixture")),
        policy,
        _evidence("test:fixture"),
        subject="turn:example",
    )

    assert observation.findings == ()


def test_canonical_digest_is_order_independent_for_object_keys() -> None:
    left = {"schema": FACT_EVIDENCE_SCHEMA, "sources": []}
    right = {"sources": [], "schema": FACT_EVIDENCE_SCHEMA}
    assert canonical_sha256(left) == canonical_sha256(right)


def test_cli_returns_one_and_writes_observation_for_policy_violation(
    tmp_path: Path,
) -> None:
    document = tmp_path / "document.json"
    policy = tmp_path / "policy.json"
    evidence = tmp_path / "evidence.json"
    output = tmp_path / "observation.json"
    document.write_text(
        json.dumps(_document(_claim("c1", "fact", "missing source", None))),
        encoding="utf-8",
    )
    policy.write_text(json.dumps(_policy()), encoding="utf-8")
    evidence.write_text(json.dumps(_evidence()), encoding="utf-8")

    assert fact_output_main(
        [
            "--document", str(document),
            "--policy", str(policy),
            "--evidence", str(evidence),
            "--subject", "turn:example",
            "--out", str(output),
        ]
    ) == 1
    emitted = json.loads(output.read_text(encoding="utf-8"))
    assert emitted["adapter_id"] == "agent.fact_output"
    assert len(emitted["findings"]) == 1


def test_cli_returns_two_for_duplicate_json_key(tmp_path: Path) -> None:
    document = tmp_path / "document.json"
    policy = tmp_path / "policy.json"
    evidence = tmp_path / "evidence.json"
    document.write_text(
        '{"schema":"ai-ratchet-gate.fact-output/v1","claims":[],"claims":[]}',
        encoding="utf-8",
    )
    policy.write_text(json.dumps(_policy()), encoding="utf-8")
    evidence.write_text(json.dumps(_evidence()), encoding="utf-8")

    assert fact_output_main(
        [
            "--document", str(document),
            "--policy", str(policy),
            "--evidence", str(evidence),
            "--subject", "turn:example",
        ]
    ) == 2
