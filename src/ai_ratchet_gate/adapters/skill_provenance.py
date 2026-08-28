"""Tracked skill bundleの provenance / digest / permission expansion を観測するadapter。

Agent Skills形式の SKILL.md frontmatter（name, description, allowed-tools）を決定論的に
読み、レビュー済みbaselineと比較可能なFindingへ正規化する。runtime仲介・署名検証・
ネットワークは行わない。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from ..model import Finding, Observation, RatchetError
from .protocol import ScanContext

GIT_LS_FILES_TIMEOUT_SECONDS = 30
SKILL_FILENAME = "SKILL.md"
ADAPTER_ID = "skill.provenance"
ADAPTER_VERSION = "1"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CAPABILITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:()*+?\[\]{}/\\|<>=@, -]{0,255}$")


def _sanitized_git_env() -> dict[str, str]:
    git_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    git_env["GIT_CONFIG_GLOBAL"] = os.devnull
    git_env["GIT_CONFIG_SYSTEM"] = os.devnull
    return git_env


def _validate_skills_root(skills_root: str) -> str:
    if type(skills_root) is not str or not skills_root or "\x00" in skills_root:
        raise RatchetError("invalid_skills_root")
    normalized = skills_root.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("/") or any(
        part in {"", ".", ".."} for part in normalized.split("/")
    ):
        raise RatchetError("invalid_skills_root")
    return normalized


def _parse_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip()


def _tokenize_capabilities(raw: str) -> frozenset[str]:
    text = raw.strip()
    if not text:
        return frozenset()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return frozenset()
        parts = [item.strip() for item in inner.split(",")]
    else:
        parts = text.split()
    capabilities: set[str] = set()
    for part in parts:
        item = _parse_scalar(part)
        if not item:
            continue
        if _CAPABILITY_RE.fullmatch(item) is None:
            raise RatchetError("invalid_skill_capability")
        capabilities.add(item)
    return frozenset(capabilities)


def parse_skill_frontmatter(text: str) -> tuple[str, str, frozenset[str]]:
    """SKILL.mdの最小frontmatterを決定論的に解析する。PyYAMLは使わない。"""
    if type(text) is not str or not text.startswith("---\n"):
        raise RatchetError("invalid_skill_frontmatter")
    end = text.find("\n---\n", 3)
    if end < 0:
        if text.endswith("\n---"):
            end = len(text) - 4
            body_start = len(text)
        else:
            raise RatchetError("invalid_skill_frontmatter")
    else:
        body_start = end + len("\n---\n")
    block = text[4:end]
    if "\x00" in block:
        raise RatchetError("invalid_skill_frontmatter")

    fields: dict[str, object] = {}
    lines = block.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[:1].isspace():
            raise RatchetError("invalid_skill_frontmatter")
        if ":" not in line:
            raise RatchetError("invalid_skill_frontmatter")
        key, _, remainder = line.partition(":")
        key = key.strip()
        if not key or key in fields:
            raise RatchetError("invalid_skill_frontmatter")
        remainder = remainder.strip()
        if remainder in {"|", ">"}:
            collected: list[str] = []
            index += 1
            while index < len(lines):
                next_line = lines[index]
                if next_line and not next_line[:1].isspace():
                    break
                collected.append(next_line[1:] if next_line.startswith(" ") else next_line)
                index += 1
            fields[key] = "\n".join(collected).strip("\n")
            continue
        if remainder == "":
            collected_items: list[str] = []
            index += 1
            while index < len(lines):
                next_line = lines[index]
                if not next_line.strip():
                    index += 1
                    continue
                if not next_line[:1].isspace():
                    break
                stripped = next_line.strip()
                if stripped.startswith("- "):
                    item = _parse_scalar(stripped[2:])
                    if not item:
                        raise RatchetError("invalid_skill_frontmatter")
                    collected_items.append(item)
                    index += 1
                    continue
                raise RatchetError("invalid_skill_frontmatter")
            fields[key] = collected_items
            continue
        fields[key] = _parse_scalar(remainder)
        index += 1

    name = fields.get("name")
    description = fields.get("description")
    if type(name) is not str or not name or _NAME_RE.fullmatch(name) is None:
        raise RatchetError("invalid_skill_name")
    if type(description) is not str or not description.strip():
        raise RatchetError("invalid_skill_description")

    raw_tools = fields.get("allowed-tools", fields.get("allowed_tools", ""))
    if isinstance(raw_tools, list):
        capabilities: set[str] = set()
        for item in raw_tools:
            if type(item) is not str or not item:
                raise RatchetError("invalid_skill_capability")
            if _CAPABILITY_RE.fullmatch(item) is None:
                raise RatchetError("invalid_skill_capability")
            capabilities.add(item)
        tools = frozenset(capabilities)
    elif type(raw_tools) is str:
        tools = _tokenize_capabilities(raw_tools)
    else:
        raise RatchetError("invalid_skill_capability")

    # frontmatter以降の本文はdigest対象だが、parser契約としては存在確認のみ
    _ = body_start
    return name, description.strip(), tools


def _encode_capability(capability: str) -> str:
    """subject_key内の'/'衝突を避けるためcapabilityを百分率エンコードする。"""
    return "".join(
        ch if ch.isalnum() or ch in "._-~:@()+*=,|" else f"%{ord(ch):02X}"
        for ch in capability
    )


def _bundle_digest(root: Path, rel_paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(rel_paths):
        path = root / rel
        if path.is_symlink():
            raise RatchetError("skill_bundle_symlink_rejected")
        if not path.is_file():
            raise RatchetError("skill_bundle_file_missing")
        try:
            data = path.read_bytes()
        except OSError as error:
            raise RatchetError("skill_bundle_read_failed") from error
        file_digest = hashlib.sha256(data).hexdigest()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


class SkillProvenanceAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def __init__(self, *, skills_root: str) -> None:
        self.skills_root = _validate_skills_root(skills_root)

    def list_tracked_paths(self, context: ScanContext) -> tuple[str, ...]:
        """skills root配下のtracked pathをUnicode正規化せず列挙する。"""
        root = context.root
        skills_path = root / self.skills_root
        if skills_path.exists() and skills_path.is_symlink():
            raise RatchetError("skills_root_symlink_rejected")
        if not skills_path.exists():
            raise RatchetError("skills_root_missing")
        if not skills_path.is_dir():
            raise RatchetError("skills_root_not_directory")
        try:
            if not skills_path.resolve().is_relative_to(root.resolve()):
                raise RatchetError("skills_root_escapes_repo")
        except OSError as error:
            raise RatchetError("skills_root_unresolvable") from error

        git_env = _sanitized_git_env()
        command = [
            "git", "-C", str(root),
            "-c", "core.fsmonitor=false",
            "-c", f"core.excludesFile={os.devnull}",
            "ls-files", "-z", "--", self.skills_root,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=True,
                env=git_env,
                timeout=GIT_LS_FILES_TIMEOUT_SECONDS,
            )
            raw = completed.stdout.decode("utf-8", errors="strict")
        except subprocess.TimeoutExpired as error:
            raise RatchetError("adapter_observation_timeout") from error
        except (subprocess.CalledProcessError, OSError, UnicodeDecodeError) as error:
            raise RatchetError("adapter_observation_failed") from error
        return tuple(sorted({item for item in raw.split("\0") if item}))

    def observe(self, context: ScanContext) -> Observation:
        tracked = self.list_tracked_paths(context)
        prefix = f"{self.skills_root}/"
        skill_files: dict[str, list[str]] = {}
        for rel in tracked:
            if not rel.startswith(prefix):
                if rel == self.skills_root:
                    continue
                raise RatchetError("skill_path_outside_root")
            rest = rel[len(prefix):]
            parts = rest.split("/")
            if len(parts) < 2:
                # skills_root直下のファイルはbundleではない
                continue
            skill_id = parts[0]
            if skill_id in {"", ".", ".."}:
                raise RatchetError("invalid_skill_bundle_path")
            skill_files.setdefault(skill_id, []).append(rel)

        findings: list[Finding] = []
        for skill_id in sorted(skill_files):
            rel_paths = tuple(sorted(skill_files[skill_id]))
            skill_md = f"{self.skills_root}/{skill_id}/{SKILL_FILENAME}"
            if skill_md not in rel_paths:
                continue
            skill_rel = f"{self.skills_root}/{skill_id}"
            try:
                text = (context.root / skill_md).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise RatchetError("invalid_skill_frontmatter") from error
            name, _description, capabilities = parse_skill_frontmatter(text)
            digest = _bundle_digest(context.root, rel_paths)
            present_evidence = hashlib.sha256(
                f"{skill_rel}\0{name}".encode("utf-8")
            ).hexdigest()
            findings.append(
                Finding.create(
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    rule_id="skill_present",
                    subject_kind="skill",
                    subject_key=skill_rel,
                    message="tracked skill bundle is present",
                    evidence_sha256=present_evidence,
                )
            )
            findings.append(
                Finding.create(
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    rule_id="skill_digest",
                    subject_kind="skill_digest",
                    subject_key=f"{skill_rel}/{digest}",
                    message="skill bundle digest observed",
                    evidence_sha256=digest,
                )
            )
            for capability in sorted(capabilities):
                encoded = _encode_capability(capability)
                cap_key = f"{skill_rel}/{encoded}"
                cap_evidence = hashlib.sha256(
                    f"{skill_rel}\0{capability}".encode("utf-8")
                ).hexdigest()
                findings.append(
                    Finding.create(
                        adapter_id=self.adapter_id,
                        adapter_version=self.adapter_version,
                        rule_id="skill_capability",
                        subject_kind="skill_capability",
                        subject_key=cap_key,
                        message="skill declares a tool or permission",
                        evidence_sha256=cap_evidence,
                    )
                )
        return Observation.create(
            self.adapter_id, self.adapter_version, context.subject, findings
        )
