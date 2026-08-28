"""Agent Skills の SKILL.md / scripts を read-only 観測する adapter。

v1入力は SKILL.md の YAML frontmatter と sibling の scripts/ だけ。
独立軸: skill_present / skill_allowed_tool / skill_scripts_digest。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

from ..model import Finding, Observation, RatchetError
from .protocol import ScanContext

DEFAULT_SKILLS_ROOT = "skills"
SKILL_FILENAME = "SKILL.md"
SCRIPTS_DIRNAME = "scripts"

_FRONTMATTER_BOUNDARY = re.compile(r"\A---\r?\n(.*?\r?\n)---(?:\r?\n|\Z)", re.DOTALL)
_TOOL_TOKEN = re.compile(r"[^\s,]+")


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _repo_relative(root: Path, path: Path) -> str:
    """repo root からの相対 POSIX path。脱出と絶対pathを拒否する。"""
    try:
        relative = path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise RatchetError("skill_path_escapes_root") from error
    text = relative.as_posix()
    if text.startswith("/") or any(part in {"", ".", ".."} for part in text.split("/")):
        raise RatchetError("invalid_skill_path")
    return _nfc(text)


def _parse_allowed_tools(frontmatter: str) -> tuple[str, ...]:
    """allowed-tools の空間/カンマ区切り文字列、または単純 YAML list だけを受理する。"""
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("allowed-tools:"):
            index += 1
            continue
        remainder = line[len("allowed-tools:") :].strip()
        if remainder == "" or remainder == "|" or remainder == ">":
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
    return ()


def _extract_frontmatter(text: str) -> str:
    match = _FRONTMATTER_BOUNDARY.match(text)
    if match is None:
        raise RatchetError("skill_frontmatter_missing")
    return match.group(1)


def _scripts_digest(scripts_dir: Path) -> str:
    """scripts/ 配下の通常ファイル内容を path 順で束ねた sha256。symlink は拒否。"""
    if not scripts_dir.exists():
        payload = b""
    else:
        if scripts_dir.is_symlink():
            raise RatchetError("skill_scripts_symlink_rejected")
        if not scripts_dir.is_dir():
            raise RatchetError("skill_scripts_not_directory")
        entries: list[tuple[str, bytes]] = []
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
                entries.append((_nfc(rel), path.read_bytes()))
        except OSError as error:
            raise RatchetError("skill_scripts_enumeration_failed") from error
        chunks = [
            f"{name}\0".encode("utf-8") + hashlib.sha256(content).digest()
            for name, content in entries
        ]
        payload = b"\n".join(chunks)
    return hashlib.sha256(payload).hexdigest()


def _evidence(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


class SkillProvenanceAdapter:
    adapter_id = "skill.provenance"
    adapter_version = "1"

    def __init__(self, *, skills_root: str = DEFAULT_SKILLS_ROOT) -> None:
        root = _nfc(skills_root.strip())
        if (
            not root
            or root.startswith("/")
            or any(part in {"", ".", ".."} for part in root.split("/"))
        ):
            raise RatchetError("invalid_skills_root")
        self.skills_root = root

    def _skills_root_path(self, context: ScanContext) -> Path:
        root = context.root
        try:
            if not root.exists() or not root.is_dir():
                raise RatchetError("adapter_observation_failed")
            candidate = (root / self.skills_root).resolve(strict=False)
            repo = root.resolve(strict=True)
            candidate.relative_to(repo)
        except (OSError, ValueError) as error:
            raise RatchetError("adapter_observation_failed") from error
        if candidate.is_symlink():
            raise RatchetError("skills_root_symlink_rejected")
        if not candidate.exists():
            raise RatchetError("skills_root_missing")
        if not candidate.is_dir():
            raise RatchetError("skills_root_not_directory")
        return candidate

    def list_skill_dirs(self, context: ScanContext) -> tuple[Path, ...]:
        skills_root = self._skills_root_path(context)
        try:
            children = sorted(skills_root.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise RatchetError("adapter_observation_failed") from error
        skill_dirs: list[Path] = []
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
        return tuple(skill_dirs)

    def observe(self, context: ScanContext) -> Observation:
        findings: list[Finding] = []
        for skill_dir in self.list_skill_dirs(context):
            skill_key = _repo_relative(context.root, skill_dir)
            skill_md = skill_dir / SKILL_FILENAME
            try:
                text = skill_md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise RatchetError("adapter_observation_failed") from error
            frontmatter = _extract_frontmatter(text)
            tools = _parse_allowed_tools(frontmatter)
            scripts_digest = _scripts_digest(skill_dir / SCRIPTS_DIRNAME)

            findings.append(
                Finding.create(
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    rule_id="skill_present",
                    subject_kind="skill",
                    subject_key=skill_key,
                    message="skill directory with SKILL.md observed",
                    evidence_sha256=_evidence("skill_present", skill_key),
                )
            )
            for tool in tools:
                tool_key = f"{skill_key}::{tool}"
                findings.append(
                    Finding.create(
                        adapter_id=self.adapter_id,
                        adapter_version=self.adapter_version,
                        rule_id="skill_allowed_tool",
                        subject_kind="skill",
                        subject_key=tool_key,
                        message="declared allowed-tools token observed",
                        evidence_sha256=_evidence("skill_allowed_tool", tool_key),
                    )
                )
            digest_key = f"{skill_key}@{scripts_digest}"
            findings.append(
                Finding.create(
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    rule_id="skill_scripts_digest",
                    subject_kind="skill",
                    subject_key=digest_key,
                    message="companion scripts tree digest observed",
                    evidence_sha256=_evidence("skill_scripts_digest", digest_key),
                )
            )
        return Observation.create(
            self.adapter_id, self.adapter_version, context.subject, findings
        )
