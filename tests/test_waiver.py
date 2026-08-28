"""waiver検証と脅威モデルの安価なゲームに対する回帰テスト。"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_ratchet_gate.cli import main
from ai_ratchet_gate.engine import evaluate
from ai_ratchet_gate.model import Finding, Observation, RatchetError
from ai_ratchet_gate.waiver import (
    WaiverDocument,
    observation_digest,
    review_binding_sha256,
    select_waived_finding_ids,
)


NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _finding(
    subject_key: str,
    *,
    adapter_id: str = "example.guard",
    adapter_version: str = "1",
    rule_id: str = "no-regression",
    message: str = "説明",
    evidence: str | None = None,
) -> Finding:
    return Finding.create(
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        rule_id=rule_id,
        subject_kind="artifact",
        subject_key=subject_key,
        message=message,
        evidence_sha256=evidence or ("a" * 64),
    )


def _observation(
    findings: list[Finding],
    *,
    adapter_id: str = "example.guard",
    subject: str = "repo:abc",
) -> Observation:
    version = findings[0].adapter_version if findings else "1"
    if findings:
        adapter_id = findings[0].adapter_id
        version = findings[0].adapter_version
    return Observation.create(adapter_id, version, subject, findings)


def _waiver_record(
    observation: Observation,
    finding: Finding,
    *,
    waiver_id: str = "w-1",
    expires_at: str = "2026-12-31T00:00:00Z",
    observation_sha256: str | None = None,
    mutate_binding: bool = False,
) -> dict[str, str]:
    digest = observation_sha256 or observation_digest(observation)
    binding = review_binding_sha256(
        adapter_id=observation.adapter_id,
        adapter_version=observation.adapter_version,
        subject=observation.subject,
        waiver_id=waiver_id,
        finding_id=finding.finding_id,
        expires_at=expires_at,
        observation_sha256=digest,
    )
    if mutate_binding:
        binding = "0" * 64
    return {
        "waiver_id": waiver_id,
        "finding_id": finding.finding_id,
        "expires_at": expires_at,
        "observation_sha256": digest,
        "review_binding_sha256": binding,
    }


def _waiver_doc(
    observation: Observation,
    records: list[dict[str, str]],
    *,
    adapter_id: str | None = None,
    subject: str | None = None,
) -> dict[str, object]:
    return {
        "schema": "ai-ratchet-gate.waivers/v1",
        "adapter_id": adapter_id or observation.adapter_id,
        "adapter_version": observation.adapter_version,
        "subject": subject or observation.subject,
        "waivers": records,
    }


def test_reviewed_in_scope_unexpired_waiver_allows_only_that_finding() -> None:
    waived = _finding("allowed.txt")
    other = _finding("other.txt")
    observation = _observation([waived])
    document = WaiverDocument.from_dict(
        _waiver_doc(observation, [_waiver_record(observation, waived)])
    )
    selected = select_waived_finding_ids(document, observation, now=NOW)
    decision = evaluate(observation, [], waived_finding_ids=selected)
    assert decision.status == "allow"
    assert decision.waived == (waived.finding_id,)
    assert decision.new == ()

    both = _observation([waived, other])
    # observation digestが変わったwaiverは適用されず、両方とも新規として残る
    stale = WaiverDocument.from_dict(
        _waiver_doc(observation, [_waiver_record(observation, waived)])
    )
    selected_stale = select_waived_finding_ids(stale, both, now=NOW)
    denied = evaluate(both, [], waived_finding_ids=selected_stale)
    assert denied.status == "deny"
    assert waived.finding_id in denied.new
    assert other.finding_id in denied.new

    fresh = WaiverDocument.from_dict(
        _waiver_doc(both, [_waiver_record(both, waived)])
    )
    selected_fresh = select_waived_finding_ids(fresh, both, now=NOW)
    partial = evaluate(both, [], waived_finding_ids=selected_fresh)
    assert partial.status == "deny"
    assert partial.waived == (waived.finding_id,)
    assert partial.new == (other.finding_id,)


def test_expired_waiver_does_not_cover_finding() -> None:
    item = _finding("expired.txt")
    observation = _observation([item])
    document = WaiverDocument.from_dict(
        _waiver_doc(
            observation,
            [
                _waiver_record(
                    observation,
                    item,
                    expires_at="2026-01-01T00:00:00Z",
                )
            ],
        )
    )
    selected = select_waived_finding_ids(document, observation, now=NOW)
    decision = evaluate(observation, [], waived_finding_ids=selected)
    assert selected == ()
    assert decision.status == "deny"
    assert decision.new == (item.finding_id,)
    assert decision.waived == ()


def test_out_of_scope_waiver_document_fails_closed() -> None:
    item = _finding("scoped.txt", adapter_id="example.guard")
    other_item = _finding("scoped.txt", adapter_id="other.guard")
    observation = _observation([item], adapter_id="example.guard")
    foreign_obs = _observation([other_item], adapter_id="other.guard")
    # 別adapter向けに署名されたwaiverを、現在のobservationへ流用できない
    record = _waiver_record(foreign_obs, other_item)
    # finding_idだけ現在のfindingへ差し替えても、bindingとscopeが守る
    record["finding_id"] = item.finding_id
    with pytest.raises(RatchetError, match="waiver_review_binding_mismatch"):
        WaiverDocument.from_dict(_waiver_doc(foreign_obs, [record]))
    valid_foreign = WaiverDocument.from_dict(
        _waiver_doc(foreign_obs, [_waiver_record(foreign_obs, other_item)])
    )
    with pytest.raises(RatchetError, match="waiver_scope_mismatch"):
        select_waived_finding_ids(valid_foreign, observation, now=NOW)


def test_unbound_or_edited_waiver_fails_closed() -> None:
    item = _finding("edited.txt")
    observation = _observation([item])
    with pytest.raises(RatchetError, match="waiver_review_binding_mismatch"):
        WaiverDocument.from_dict(
            _waiver_doc(
                observation,
                [_waiver_record(observation, item, mutate_binding=True)],
            )
        )
    raw = _waiver_doc(observation, [_waiver_record(observation, item)])
    raw["waivers"][0]["expires_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(RatchetError, match="waiver_review_binding_mismatch"):
        WaiverDocument.from_dict(raw)


def test_unknown_schema_and_missing_digest_fail_closed() -> None:
    item = _finding("schema.txt")
    observation = _observation([item])
    with pytest.raises(RatchetError, match="invalid_waiver_schema"):
        WaiverDocument.from_dict({"schema": "unknown", "waivers": []})
    broken = _waiver_doc(observation, [_waiver_record(observation, item)])
    del broken["waivers"][0]["observation_sha256"]
    with pytest.raises(RatchetError, match="invalid_waiver_record"):
        WaiverDocument.from_dict(broken)
    broken_id = _waiver_doc(observation, [_waiver_record(observation, item)])
    del broken_id["waivers"][0]["waiver_id"]
    with pytest.raises(RatchetError, match="invalid_waiver_record"):
        WaiverDocument.from_dict(broken_id)


def test_waiver_subject_uses_unicode_nfc() -> None:
    item = _finding("unicode.txt")
    # cafe + combining acute (NFD)。既存engine/CLIと同じNFC束縛。
    nfd = "cafe\u0301"
    nfc = unicodedata.normalize("NFC", nfd)
    assert nfc != nfd
    observation = _observation([item], subject=nfd)
    assert observation.subject == nfc
    record = _waiver_record(observation, item)
    document = WaiverDocument.from_dict(
        _waiver_doc(observation, [record], subject=nfd)
    )
    assert document.subject == nfc
    selected = select_waived_finding_ids(document, observation, now=NOW)
    assert selected == (item.finding_id,)


def test_waiver_on_one_adapter_does_not_offset_other_axis() -> None:
    left = _finding("a.txt", adapter_id="axis.left")
    right = _finding("b.txt", adapter_id="axis.right")
    left_obs = _observation([left], adapter_id="axis.left", subject="repo:multi")
    right_obs = _observation([right], adapter_id="axis.right", subject="repo:multi")
    left_waiver = WaiverDocument.from_dict(
        _waiver_doc(left_obs, [_waiver_record(left_obs, left)])
    )
    left_decision = evaluate(
        left_obs,
        [],
        waived_finding_ids=select_waived_finding_ids(left_waiver, left_obs, now=NOW),
    )
    right_decision = evaluate(right_obs, [])
    assert left_decision.status == "allow"
    assert right_decision.status == "deny"
    assert right_decision.new == (right.finding_id,)
    # 総合点は導入しない。軸ごとのstatusを独立に読む。
    assert {left_decision.status, right_decision.status} == {"allow", "deny"}


def test_core_has_no_waiver_auto_approve_entrypoint() -> None:
    import ai_ratchet_gate
    import ai_ratchet_gate.cli as cli_module

    forbidden = [
        "approve_waiver",
        "update_waiver",
        "extend_waiver",
        "add_waiver",
        "--update-waiver",
        "--approve-waiver",
    ]
    for name in forbidden:
        assert not hasattr(ai_ratchet_gate, name)
        assert not hasattr(cli_module, name)


def test_evaluate_cli_consumes_reviewed_waiver(tmp_path: Path) -> None:
    item = _finding("cli.txt")
    observation = _observation([item])
    observation_path = tmp_path / "observation.json"
    baseline_path = tmp_path / "baseline.json"
    waiver_path = tmp_path / "waiver.json"
    receipt_path = tmp_path / "receipt.json"
    observation_path.write_text(
        json.dumps(observation.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "example.guard",
                "adapter_version": "1",
                "subject": "repo:abc",
                "policy": "new_only",
                "finding_ids": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    waiver_path.write_text(
        json.dumps(
            _waiver_doc(observation, [_waiver_record(observation, item)]),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert main(
        [
            "evaluate",
            "--observation",
            str(observation_path),
            "--baseline",
            str(baseline_path),
            "--waiver",
            str(waiver_path),
            "--receipt",
            str(receipt_path),
            "--expected-subject",
            "repo:abc",
        ]
    ) == 0
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload["decision"]["status"] == "allow"
    assert payload["decision"]["waived"] == [item.finding_id]


def test_evaluate_cli_expired_waiver_still_denies(tmp_path: Path) -> None:
    item = _finding("cli-expired.txt")
    observation = _observation([item])
    observation_path = tmp_path / "observation.json"
    baseline_path = tmp_path / "baseline.json"
    waiver_path = tmp_path / "waiver.json"
    observation_path.write_text(json.dumps(observation.to_dict()), encoding="utf-8")
    baseline_path.write_text(
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
    waiver_path.write_text(
        json.dumps(
            _waiver_doc(
                observation,
                [
                    _waiver_record(
                        observation,
                        item,
                        expires_at=(NOW - timedelta(days=1)).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                    )
                ],
            )
        ),
        encoding="utf-8",
    )
    assert main(
        [
            "evaluate",
            "--observation",
            str(observation_path),
            "--baseline",
            str(baseline_path),
            "--waiver",
            str(waiver_path),
            "--expected-subject",
            "repo:abc",
        ]
    ) == 1


def test_unreadable_observation_with_waiver_fails_closed(
    tmp_path: Path, capsys
) -> None:
    baseline_path = tmp_path / "baseline.json"
    waiver_path = tmp_path / "waiver.json"
    missing = tmp_path / "missing-observation.json"
    baseline_path.write_text(
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
    waiver_path.write_text("{}", encoding="utf-8")
    assert main(
        [
            "evaluate",
            "--observation",
            str(missing),
            "--baseline",
            str(baseline_path),
            "--waiver",
            str(waiver_path),
            "--expected-subject",
            "repo:abc",
        ]
    ) == 2
    assert "tool_error" in capsys.readouterr().out


# --- 脅威モデル: AAR由来の安価なゲーム（subsystemではなく回帰テストだけ） ---


def test_threat_nondeterministic_id_cannot_make_new_finding_disappear() -> None:
    """再実行でIDが揺らぐと、新規findingを監視から消したように見せられる。

    Finding IDはidentityへ決定論的に束縛され、同じ違反は同じIDになる。
    IDを差し替えた観測は別findingとしてnewに残りdenyされる。
    """
    stable = _finding("report.json", message="run-1")
    again = _finding("report.json", message="run-2")
    assert stable.finding_id == again.finding_id
    forged = _finding("report.json", evidence="b" * 64)
    # evidenceはIDに入らないが、subject_keyを変えると別IDになる
    renamed = _finding("report-renamed.json")
    assert stable.finding_id != renamed.finding_id
    decision = evaluate(_observation([renamed]), [stable.finding_id])
    assert decision.status == "deny"
    assert decision.new == (renamed.finding_id,)
    assert decision.resolved == (stable.finding_id,)


def test_threat_path_rename_or_reason_disguise_creates_new_id() -> None:
    """path renameや理由文の言い換えで同一違反を別IDへ偽装するゲーム。

    message変更ではIDは変わらず、subject_key変更は新規悪化としてdenyされる。
    旧IDのresolvedは新IDのallowを意味しない。
    """
    original = _finding("build/out.bin", message="skip: flaky")
    disguised_reason = _finding("build/out.bin", message="skip: known issue #9")
    renamed = _finding("build/out-v2.bin", message="skip: flaky")
    assert original.finding_id == disguised_reason.finding_id
    assert original.finding_id != renamed.finding_id
    decision = evaluate(
        _observation([renamed]),
        [original.finding_id],
    )
    assert decision.status == "deny"
    assert decision.accepted == ()
    assert decision.new == (renamed.finding_id,)
    assert decision.resolved == (original.finding_id,)


def test_threat_baseline_enlargement_is_not_a_resolved_finding() -> None:
    """baseline拡大を「解消した」かのように見せるゲーム。

    grandfather（accepted）と解消（resolved）はpartitionが異なり、
    baselineへIDを足すことはfindingの消失ではない。
    """
    old = _finding("legacy.txt")
    added = _finding("new-debt.txt")
    before = evaluate(_observation([old]), [old.finding_id])
    assert before.status == "allow"
    assert before.accepted == (old.finding_id,)
    assert before.resolved == ()

    enlarged = evaluate(
        _observation([old, added]),
        [old.finding_id, added.finding_id],
    )
    assert enlarged.status == "allow"
    assert set(enlarged.accepted) == {old.finding_id, added.finding_id}
    assert enlarged.resolved == ()
    assert enlarged.new == ()

    actually_resolved = evaluate(_observation([]), [old.finding_id, added.finding_id])
    assert actually_resolved.accepted == ()
    assert set(actually_resolved.resolved) == {old.finding_id, added.finding_id}
    # enlargementとresolutionを混同しない
    assert enlarged.resolved != actually_resolved.resolved
