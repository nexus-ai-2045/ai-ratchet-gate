"""副作用を持たない集合差分ラチェット。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .model import Decision, Observation, RatchetError


def evaluate(
    observation: Observation,
    baseline_ids: Iterable[str],
    *,
    mode: str = "ratchet",
    policy: str = "new_only",
) -> Decision:
    if type(mode) is not str or mode not in {"observe", "ratchet", "strict"}:
        raise RatchetError("invalid_mode")
    if type(policy) is not str or policy not in {"new_only", "exact_baseline"}:
        raise RatchetError("invalid_policy")
    raw_baseline = tuple(baseline_ids)
    if any(
        type(item) is not str or re.fullmatch(r"[0-9a-f]{64}", item) is None
        for item in raw_baseline
    ):
        raise RatchetError("invalid_baseline_ids")
    baseline = tuple(sorted(raw_baseline))
    if len(baseline) != len(set(baseline)):
        raise RatchetError("invalid_baseline_ids")
    current = {item.finding_id for item in observation.findings}
    known = set(baseline)
    accepted = tuple(sorted(current & known))
    new = tuple(sorted(current - known))
    resolved = tuple(sorted(known - current))
    denied = mode == "strict" and bool(current)
    if mode == "ratchet":
        denied = bool(new) or (policy == "exact_baseline" and bool(resolved))
    return Decision(
        observation=observation,
        mode=mode,
        policy=policy,
        status="deny" if denied else "allow",
        accepted=accepted,
        new=new,
        resolved=resolved,
        baseline_ids=baseline,
    )
