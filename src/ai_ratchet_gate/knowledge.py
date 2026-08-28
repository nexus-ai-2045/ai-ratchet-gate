"""検証済みの解決知識を中央・repo固有で合成し、既知問題へ再利用する。

このmoduleは対象repositoryを変更しない。解法の選択までを決定論的に行い、実際の適用は
外側のagent harnessが担う。これによりai-ratchet-gate本体のread-only境界を維持する。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from .model import RatchetError

KNOWLEDGE_SCHEMA = "ai-ratchet-gate.solution-knowledge/v1"
MAX_KNOWLEDGE_ENTRIES = 10_000


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _nonempty(value: object, name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise RatchetError(f"invalid_{name}")
    return value


@dataclass(frozen=True, slots=True)
class SolutionKnowledge:
    """1件の検証済み解決知識。

    `problem_key` はrepository pathやcommit SHAを含めない、同種問題を横断同定する安定キー。
    `resolver_id` は外側harnessが実装する決定論的resolverの識別子。
    `evidence_sha256` は昇格判断に使った再現fixture / test evidenceのdigest。
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
        if normalized_scope not in {"central", "local"}:
            raise RatchetError("invalid_scope")
        evidence = _nonempty(evidence_sha256, "evidence_sha256")
        if len(evidence) != 64 or any(char not in "0123456789abcdef" for char in evidence):
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


def load_knowledge_document(value: object, *, expected_scope: str) -> tuple[SolutionKnowledge, ...]:
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
    """中央とlocalを問題キー単位で合成する。

    localはrepository固有事情を表せるため同一problem_keyではlocalを優先する。ただし同一scope内で
    同じproblem_keyに複数resolverがある曖昧状態はfail-closedにする。
    """

    def index(entries: Iterable[SolutionKnowledge], scope: str) -> dict[str, SolutionKnowledge]:
        result: dict[str, SolutionKnowledge] = {}
        for entry in entries:
            if entry.scope != scope:
                raise RatchetError("knowledge_scope_mismatch")
            previous = result.get(entry.problem_key)
            if previous is not None and previous.knowledge_id != entry.knowledge_id:
                raise RatchetError("ambiguous_problem_resolution")
            result[entry.problem_key] = entry
        return result

    merged = index(central, "central")
    merged.update(index(local, "local"))
    return merged


def resolve_problem(
    problem_key: str,
    knowledge: dict[str, SolutionKnowledge],
) -> Resolution:
    """既知問題ならresolverを返し、未知問題だけ人間判断へ返す。"""
    key = _nonempty(problem_key, "problem_key")
    selected = knowledge.get(key)
    if selected is None:
        return Resolution(key, "unknown", None, "no_verified_solution")
    return Resolution(key, "known", selected, "verified_solution_available")
