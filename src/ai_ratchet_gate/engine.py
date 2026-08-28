"""副作用を持たない集合差分ラチェットと解決知識の合成。"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from .model import Decision, Observation, RatchetError

KNOWLEDGE_SCHEMA = "ai-ratchet-gate.solution-knowledge/v1"
MAX_KNOWLEDGE_ENTRIES = 10_000
ALLOWED_KNOWLEDGE_SCOPES = frozenset({"central", "local"})


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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _nonempty(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise RatchetError(f"invalid_{name}")
    # model.Finding と同じく Unicode NFC へ揃えてから identity / lookup する
    return unicodedata.normalize("NFC", value)


@dataclass(frozen=True, slots=True)
class SolutionKnowledge:
    """検証済み解法のagent非依存identity。

    problem_keyはrepository pathやcommit SHAを含めない横断キーとし、resolver_id/versionは
    外側のagent harnessが実装する決定論的resolverを指す。本engineは対象repoを変更しない。
    """

    knowledge_id: str
    problem_key: str
    resolver_id: str
    resolver_version: str
    scope: str
    evidence_sha256: str
    source: str

    @classmethod
    def create(
        cls,
        *,
        problem_key: str,
        resolver_id: str,
        resolver_version: str,
        scope: str,
        evidence_sha256: str,
        source: str,
    ) -> "SolutionKnowledge":
        problem = _nonempty(problem_key, "problem_key")
        resolver = _nonempty(resolver_id, "resolver_id")
        version = _nonempty(resolver_version, "resolver_version")
        normalized_scope = _nonempty(scope, "scope")
        if normalized_scope not in ALLOWED_KNOWLEDGE_SCOPES:
            raise RatchetError("invalid_scope")
        evidence = _nonempty(evidence_sha256, "evidence_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", evidence) is None:
            raise RatchetError("invalid_evidence_sha256")
        origin = _nonempty(source, "source")
        identity = {
            "problem_key": problem,
            "resolver_id": resolver,
            "resolver_version": version,
        }
        return cls(
            knowledge_id=hashlib.sha256(_canonical(identity)).hexdigest(),
            problem_key=problem,
            resolver_id=resolver,
            resolver_version=version,
            scope=normalized_scope,
            evidence_sha256=evidence,
            source=origin,
        )

    @classmethod
    def from_dict(cls, value: object) -> "SolutionKnowledge":
        keys = {
            "knowledge_id",
            "problem_key",
            "resolver_id",
            "resolver_version",
            "scope",
            "evidence_sha256",
            "source",
        }
        if not isinstance(value, dict) or set(value) != keys:
            raise RatchetError("invalid_solution_knowledge")
        created = cls.create(**{key: value[key] for key in keys - {"knowledge_id"}})
        if value["knowledge_id"] != created.knowledge_id:
            raise RatchetError("knowledge_id_mismatch")
        return created

    def to_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class Resolution:
    problem_key: str
    status: str
    knowledge: SolutionKnowledge | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "problem_key": self.problem_key,
            "status": self.status,
            "knowledge": self.knowledge.to_dict() if self.knowledge else None,
            "reason": self.reason,
        }


def load_knowledge_document(
    value: object, *, expected_scope: str
) -> tuple[SolutionKnowledge, ...]:
    # empty manifestでも typo scope (例: global) を偽成功させない
    if type(expected_scope) is not str or expected_scope not in ALLOWED_KNOWLEDGE_SCOPES:
        raise RatchetError("invalid_scope")
    if not isinstance(value, dict) or set(value) != {"schema", "scope", "entries"}:
        raise RatchetError("invalid_knowledge_document")
    if value["schema"] != KNOWLEDGE_SCHEMA or value["scope"] != expected_scope:
        raise RatchetError("knowledge_document_identity_mismatch")
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_KNOWLEDGE_ENTRIES:
        raise RatchetError("invalid_knowledge_entries")
    parsed = tuple(SolutionKnowledge.from_dict(item) for item in entries)
    if any(item.scope != expected_scope for item in parsed):
        raise RatchetError("knowledge_scope_mismatch")
    ids = [item.knowledge_id for item in parsed]
    if len(ids) != len(set(ids)):
        raise RatchetError("duplicate_knowledge_id")
    return tuple(sorted(parsed, key=lambda item: item.knowledge_id))


def compose_knowledge(
    central: Iterable[SolutionKnowledge],
    local: Iterable[SolutionKnowledge],
) -> dict[str, SolutionKnowledge]:
    """central + localを決定論的に合成し、repo固有localを同一problem_keyで優先する。"""

    def index(
        entries: Iterable[SolutionKnowledge], scope: str
    ) -> dict[str, SolutionKnowledge]:
        result: dict[str, SolutionKnowledge] = {}
        for entry in entries:
            if entry.scope != scope:
                raise RatchetError("knowledge_scope_mismatch")
            previous = result.get(entry.problem_key)
            if previous is not None and previous != entry:
                if previous.knowledge_id != entry.knowledge_id:
                    raise RatchetError("ambiguous_problem_resolution")
                # 同一 knowledge_id でも evidence/source 等が食い違う場合は last-wins しない
                raise RatchetError("conflicting_knowledge_metadata")
            result[entry.problem_key] = entry
        return result

    merged = index(central, "central")
    merged.update(index(local, "local"))
    return merged


def resolve_problem(
    problem_key: str,
    knowledge: dict[str, SolutionKnowledge],
) -> Resolution:
    """既知問題は検証済みremediationを返し、未知問題だけhuman-resolutionへ送る。

    対象repoへのresolver適用は本関数の責務外。明示的な人間/harnessアクションの後に行う。
    """
    key = _nonempty(problem_key, "problem_key")
    selected = knowledge.get(key)
    if selected is None:
        return Resolution(key, "unknown", None, "no_verified_solution")
    if selected.problem_key != key:
        raise RatchetError("problem_key_mismatch")
    return Resolution(key, "known", selected, "verified_solution_available")
