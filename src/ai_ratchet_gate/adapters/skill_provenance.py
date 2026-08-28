"""Agent Skills の SKILL.md を read-only 観測する adapter。

v1入力は SKILL.md の YAML frontmatter と sibling scripts/ 配下の通常ファイル。
既定で `.agents/skills/` と `skills/` を「存在する場合だけ」走査する。

Finding軸（digestは evidence であり deny 軸ではない）:
- new_skill
- allowed_tools_token
- unrestricted_tools
- executable_asset
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from pathlib import Path

from ..model import Finding, Observation, RatchetError
from .protocol import ScanContext

ADAPTER_ID = "skills.provenance"
ADAPTER_VERSION = "1"
DEFAULT_SKILL_ROOTS = (".agents/skills", "skills")
SKILL_FILENAME = "SKILL.md"
SCRIPTS_DIRNAME = "scripts"

_FRONTMATTER_BOUNDARY = re.compile(r"\A---\r?\n(.*?\r?\n)---(?:\r?\n|\Z)", re.DOTALL)
_TOOL_TOKEN = re.compile(r"[^\s,]+")


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _validate_relative_root(root: str) -> str:
    text = _nfc(root.strip())
    if (
        not text
        or text.startswith("/")
        or any(part in {"", ".", ".."} for part in text.split("/"))
    ):
        raise RatchetError("invalid_skills_root")
    return text


def _repo_relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise RatchetError("skill_path_escapes_root") from error
    text = relative.as_posix()
    if text.startswith("/") or any(part in {"", ".", ".."} for part in text.split("/")):
        raise RatchetError("invalid_skill_path")
    return _nfc(text)


def _parse_allowed_tools(frontmatter: str) -> tuple[str, ...] | None:
    """allowed-tools を返す。キー欠落は None（unrestricted）、空宣言は ()。"""
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("allowed-tools:"):
            index += 1
            continue
        remainder = line[len("allowed-tools:") :].strip()
        if remainder == "" or remainder in {"|", ">"}:
            items: list[str] = []
            index += 1
            while index < len(lines):
                child = lines[index]
                if child.strip() == "":
                    index += 1
                    continue
                if not child.startswith((" ", "\t")):
                    break
                stripped = child.strip()
                if not stripped.startswith("- "):
                    raise RatchetError("skill_frontmatter_invalid")
                token = _nfc(stripped[2:].strip().strip("\"'"))
                if not token or any(ch.isspace() for ch in token):
                    raise RatchetError("skill_frontmatter_invalid")
                items.append(token)
                index += 1
            return tuple(sorted(set(items)))
        if remainder.startswith("[") and remainder.endswith("]"):
            inner = remainder[1:-1].strip()
            if not inner:
                return ()
            items = []
            for part in inner.split(","):
                token = _nfc(part.strip().strip("\"'"))
                if not token:
                    raise RatchetError("skill_frontmatter_invalid")
                items.append(token)
            return tuple(sorted(set(items)))
        tokens = [_nfc(match.group(0)) for match in _TOOL_TOKEN.finditer(remainder)]
        if not tokens:
            raise RatchetError("skill_frontmatter_invalid")
        return tuple(sorted(set(tokens)))
    return None


def _extract_frontmatter(text: str) -> str:
    match = _FRONTMATTER_BOUNDARY.match(text)
    if match is None:
        raise RatchetError("skill_frontmatter_missing")
    return match.group(1)


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise RatchetError("adapter_observation_failed") from error


def _evidence(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _list_executable_assets(scripts_dir: Path) -> tuple[tuple[str, str], ...]:
    """scripts/ 配下の通常ファイルを (repo相対ではない scripts相対path, content digest) で返す。

    finding ID は path だけに束縛し、digest は evidence に載せる。
    """
    if not scripts_dir.exists():
        return ()
    if scripts_dir.is_symlink():
        raise RatchetError("skill_scripts_symlink_rejected")
    if not scripts_dir.is_dir():
        raise RatchetError("skill_scripts_not_directory")
    entries: list[tuple[str, str]] = []
    try:
        for path in sorted(scripts_dir.rglob("*")):
            if path.is_symlink():
                raise RatchetError("skill_scripts_symlink_rejected")
            if path.is_dir():
                continue
            if not path.is_file():
                raise RatchetError("skill_scripts_enumeration_failed")
            rel = path.relative_to(scripts_dir).as_posix()
            if any(part in {"", ".", ".."} for part in rel.split("/")):
                raise RatchetError("invalid_skill_path")
            entries.append((_nfc(rel), _file_digest(path)))
    except OSError as error:
        raise RatchetError("skill_scripts_enumeration_failed") from error
    return tuple(entries)


class SkillProvenanceAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, *, skill_roots: tuple[str, ...] = DEFAULT_SKILL_ROOTS) -> None:
        if not skill_roots:
            raise RatchetError("invalid_skills_root")
        normalized = tuple(_validate_relative_root(item) for item in skill_roots)
        if len(normalized) != len(set(normalized)):
            raise RatchetError("duplicate_skills_root")
        self.skill_roots = normalized

    def _existing_roots(self, context: ScanContext) -> tuple[Path, ...]:
        try:
            if not context.root.exists() or not context.root.is_dir():
                raise RatchetError("adapter_observation_failed")
            repo = context.root.resolve(strict=True)
        except OSError as error:
            raise RatchetError("adapter_observation_failed") from error
        found: list[Path] = []
        for relative in self.skill_roots:
            candidate = (context.root / relative).resolve(strict=False)
            try:
                candidate.relative_to(repo)
            except ValueError as error:
                raise RatchetError("skill_path_escapes_root") from error
            if not candidate.exists():
                continue
            if candidate.is_symlink():
                raise RatchetError("skills_root_symlink_rejected")
            if not candidate.is_dir():
                raise RatchetError("skills_root_not_directory")
            # 列挙不能を成功扱いにしない
            if not os.access(candidate, os.R_OK | os.X_OK):
                raise RatchetError("adapter_observation_failed")
            found.append(candidate)
        return tuple(found)

    def list_skill_dirs(self, context: ScanContext) -> tuple[Path, ...]:
        skill_dirs: list[Path] = []
        for skills_root in self._existing_roots(context):
            try:
                children = sorted(skills_root.iterdir(), key=lambda item: item.name)
            except OSError as error:
                raise RatchetError("adapter_observation_failed") from error
            for child in children:
                if child.is_symlink():
                    raise RatchetError("skill_symlink_rejected")
                if not child.is_dir():
                    continue
                skill_md = child / SKILL_FILENAME
                if skill_md.is_symlink():
                    raise RatchetError("skill_symlink_rejected")
                if skill_md.is_file():
                    skill_dirs.append(child)
        # 同一相対pathの二重計上を避け、path順で安定化
        unique = { _repo_relative(context.root, path): path for path in skill_dirs }
        return tuple(unique[key] for key in sorted(unique))

    def observe(self, context: ScanContext) -> Observation:
        findings: list[Finding] = []
        for skill_dir in self.list_skill_dirs(context):
            skill_key = _repo_relative(context.root, skill_dir)
            skill_md = skill_dir / SKILL_FILENAME
            try:
                text = skill_md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise RatchetError("adapter_observation_failed") from error
            skill_digest = _evidence("skill_md", skill_key, _file_digest(skill_md))
            frontmatter = _extract_frontmatter(text)
            tools = _parse_allowed_tools(frontmatter)

            findings.append(
                Finding.create(
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    rule_id="new_skill",
                    subject_kind="skill",
                    subject_key=skill_key,
                    message="skill directory with SKILL.md observed",
                    evidence_sha256=skill_digest,
                )
            )
            if tools is None or tools == ():
                findings.append(
                    Finding.create(
                        adapter_id=self.adapter_id,
                        adapter_version=self.adapter_version,
                        rule_id="unrestricted_tools",
                        subject_kind="skill",
                        subject_key=skill_key,
                        message="allowed-tools absent or empty",
                        evidence_sha256=_evidence(
                            "unrestricted_tools", skill_key, skill_digest
                        ),
                    )
                )
            else:
                for tool in tools:
                    tool_key = f"{skill_key}::{tool}"
                    findings.append(
                        Finding.create(
                            adapter_id=self.adapter_id,
                            adapter_version=self.adapter_version,
                            rule_id="allowed_tools_token",
                            subject_kind="skill",
                            subject_key=tool_key,
                            message="declared allowed-tools token observed",
                            evidence_sha256=_evidence(
                                "allowed_tools_token", tool_key, skill_digest
                            ),
                        )
                    )
            for rel, content_digest in _list_executable_assets(
                skill_dir / SCRIPTS_DIRNAME
            ):
                asset_key = f"{skill_key}/scripts/{rel}"
                findings.append(
                    Finding.create(
                        adapter_id=self.adapter_id,
                        adapter_version=self.adapter_version,
                        rule_id="executable_asset",
                        subject_kind="skill",
                        subject_key=asset_key,
                        message="companion scripts asset observed",
                        evidence_sha256=_evidence(
                            "executable_asset", asset_key, content_digest
                        ),
                    )
                )
        return Observation.create(
            self.adapter_id, self.adapter_version, context.subject, findings
        )
