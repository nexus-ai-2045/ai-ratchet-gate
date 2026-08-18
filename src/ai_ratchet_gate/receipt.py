"""入力へ束縛された再現可能な判定receipt。"""

from __future__ import annotations

import hashlib
import json

from .model import Decision


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_receipt(decision: Decision) -> str:
    observation = {
        "adapter_id": decision.observation.adapter_id,
        "adapter_version": decision.observation.adapter_version,
        "subject": decision.observation.subject,
        # messageやsubject_keyを再掲せず、CI logへのsecret/PII漏洩面を縮小する。
        "findings": [
            {
                "finding_id": item.finding_id,
                "evidence_sha256": item.evidence_sha256,
            }
            for item in decision.observation.findings
        ],
    }
    baseline_document = {
        "schema": "ai-ratchet-gate.baseline/v1",
        "adapter_id": decision.observation.adapter_id,
        "adapter_version": decision.observation.adapter_version,
        "policy": decision.policy,
        "finding_ids": list(decision.baseline_ids),
    }
    body: dict[str, object] = {
        "schema": "ai-ratchet-gate.receipt/v1",
        "observation_sha256": hashlib.sha256(_canonical(observation).encode()).hexdigest(),
        "baseline_sha256": hashlib.sha256(
            _canonical(baseline_document).encode()
        ).hexdigest(),
        "subject": decision.observation.subject,
        "adapter": {
            "id": decision.observation.adapter_id,
            "version": decision.observation.adapter_version,
        },
        "decision": {
            "mode": decision.mode,
            "policy": decision.policy,
            "status": decision.status,
            "accepted": list(decision.accepted),
            "new": list(decision.new),
            "resolved": list(decision.resolved),
        },
    }
    body["receipt_sha256"] = hashlib.sha256(_canonical(body).encode()).hexdigest()
    return _canonical(body) + "\n"
