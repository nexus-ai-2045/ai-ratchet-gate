"""CI設定のつまずき3型を read-only 観測する adapter（ADR-0009）。

- `ci.pin_tagged`: 固定先の40桁SHAが、保護されたタグから辿れるSHAか
- `ci.release_asset_live`: GitHub Release の配布先URLが生きているか
- `ci.secret_declared`: workflow が使う secret の名前が登録済みか（名前だけ。値は扱わない）

adapter 自身はネットワークへ出ない。外の事実（タグのSHA一覧・生きている配布先・
登録済み secret の名前）は `scripts/collect_ci_facts.py` が集めた
`ai-ratchet-gate.ci-facts/v1` で受け取る。必要な事実が無ければ fail-closed（RatchetError）。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..model import Finding, Observation, RatchetError
from .protocol import ScanContext

PIN_TAGGED_ADAPTER_ID = "ci.pin_tagged"
RELEASE_ASSET_LIVE_ADAPTER_ID = "ci.release_asset_live"
SECRET_DECLARED_ADAPTER_ID = "ci.secret_declared"
ADAPTER_VERSION = "1"
CI_FACTS_SCHEMA = "ai-ratchet-gate.ci-facts/v1"

# 固定先として数える owner。これ以外の `uses: owner/x@SHA`（外部action）は数えない
DEFAULT_PIN_OWNERS = ("nexus-ai-2045",)
CI_DIR = ".github"
ASSET_EXTRA_FILES = ("pyproject.toml",)
ASSET_EXTRA_GLOBS = ("requirements*.txt",)
MAX_FILE_BYTES = 1024 * 1024
MAX_FACT_ITEMS = 100_000

_SHA40 = re.compile(r"(?<![0-9A-Fa-f])[0-9a-f]{40}(?![0-9A-Fa-f])")
_USES = re.compile(
    r"""uses:\s*["']?(?P<target>[^@\s"']+)@(?P<ref>[0-9a-f]{40})(?![0-9A-Fa-f])"""
)
_ASSET_URL = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/download/"
    r"[^\s\"'`()<>#\\]+"
)
_SECRET_REF = re.compile(
    r"""secrets\s*(?:\.\s*(?P<dot>[A-Za-z_][A-Za-z0-9_]*)"""
    r"""|\[\s*["'](?P<idx>[A-Za-z_][A-Za-z0-9_]*)["']\s*\])"""
)
_SECRET_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")
_BUILTIN_SECRETS = frozenset({"GITHUB_TOKEN"})
_ZERO_SHA = "0" * 40


def _evidence(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _relative(root: Path, path: Path) -> str:
    text = path.relative_to(root).as_posix()
    text = unicodedata.normalize("NFC", text)
    if text.startswith("/") or any(part in {"", ".", ".."} for part in text.split("/")):
        raise RatchetError("invalid_ci_path")
    return text


def _read_text(path: Path) -> str:
    try:
        if path.is_symlink():
            # 外部pathを辿って観測面を広げない（fail-closed）
            raise RatchetError("ci_path_is_symlink")
        raw = path.read_bytes()
    except OSError as error:
        raise RatchetError("adapter_observation_failed") from error
    if len(raw) > MAX_FILE_BYTES:
        raise RatchetError("ci_file_too_large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RatchetError("ci_file_not_utf8") from error


def _iter_ci_files(root: Path) -> tuple[Path, ...]:
    """`.github/` 配下の通常fileを決定的な順で列挙する。無ければ空。"""
    base = root / CI_DIR
    try:
        if base.is_symlink():
            raise RatchetError("ci_path_is_symlink")
        if not base.exists():
            return ()
        if not base.is_dir():
            raise RatchetError("adapter_observation_failed")
    except OSError as error:
        raise RatchetError("adapter_observation_failed") from error
    files: list[Path] = []
    stack = [base]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError as error:
            raise RatchetError("adapter_observation_failed") from error
        for child in children:
            try:
                if child.is_symlink():
                    raise RatchetError("ci_path_is_symlink")
                if child.is_dir():
                    stack.append(child)
                elif child.is_file() and child.suffix in {".yml", ".yaml"}:
                    files.append(child)
            except OSError as error:
                raise RatchetError("adapter_observation_failed") from error
    return tuple(sorted(files, key=lambda item: item.as_posix()))


def _iter_asset_files(root: Path) -> tuple[Path, ...]:
    files = list(_iter_ci_files(root))
    for name in ASSET_EXTRA_FILES:
        candidate = root / name
        if candidate.is_symlink():
            raise RatchetError("ci_path_is_symlink")
        if candidate.is_file():
            files.append(candidate)
    for pattern in ASSET_EXTRA_GLOBS:
        for candidate in sorted(root.glob(pattern)):
            if candidate.is_symlink():
                raise RatchetError("ci_path_is_symlink")
            if candidate.is_file():
                files.append(candidate)
    return tuple(files)


def extract_pins(
    text: str, *, pin_owners: tuple[str, ...] = DEFAULT_PIN_OWNERS
) -> tuple[str, ...]:
    """固定先として数える40桁SHAを返す（重複なし・順序は出現順）。

    外部action（`uses: <owner以外>/x@SHA`）の行は丸ごと数えない。
    それ以外の行の40桁SHA（例: `preflight-ref:`）は固定先として数える。
    64桁のsha256の一部や、push の空SHA（0が40桁）は数えない。
    """
    owners = {owner.lower() for owner in pin_owners}
    found: list[str] = []
    for line in text.splitlines():
        uses = _USES.search(line)
        if uses is not None:
            owner = uses.group("target").split("/", 1)[0].lower()
            if owner not in owners:
                continue
        for match in _SHA40.finditer(line):
            sha = match.group(0)
            if sha != _ZERO_SHA and sha not in found:
                found.append(sha)
    return tuple(found)


def extract_asset_urls(text: str) -> tuple[str, ...]:
    """GitHub Release の配布先URLを返す（`#sha256=` などの断片は外す）。

    変数（`$`）を含むURLは、実行時まで中身が決まらないので数えない。
    """
    found: list[str] = []
    for match in _ASSET_URL.finditer(text):
        url = match.group(0).rstrip(".,;:")
        if "$" in url:
            # `${VERSION}` などの変数入りURLは静的に確かめられないので数えない
            continue
        if url not in found:
            found.append(url)
    return tuple(found)


_BLOCK_SCALAR = re.compile(r"(?:^|[\s:-])[|>][1-9+-]{0,2}$")
_BLOCK_KEY = re.compile(r"""^(?:-\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_-]*|"[^"]*"|'[^']*')\s*:(?:\s+(?P<rest>.*))?$""")


def _strip_comment(line: str) -> str:
    """YAML の注釈（引用の外で、行頭か空白の直後の `#` から後ろ）を外す。"""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'" and (index == 0 or line[index - 1] in " \t:[{,"):
            quote = char
            continue
        if char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip()
        continue
    return line.rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _active_lines(text: str) -> list[str]:
    """注釈を外した行。ブロック文字列（`run: |` など）の中身はそのまま残す。

    GitHub はブロック文字列の中の `${{ }}` も展開するので、シェルの `#` の後ろでも参照として数える。
    """
    result: list[str] = []
    block_indent: int | None = None
    for line in text.splitlines():
        if block_indent is not None:
            if not line.strip() or _indent(line) > block_indent:
                result.append(line)
                continue
            block_indent = None
        active = _strip_comment(line)
        result.append(active)
        if active.strip() and _BLOCK_SCALAR.search(active):
            block_indent = _indent(line)
    return result


def _unquote(key: str) -> str:
    key = key.strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
        return key[1:-1]
    return key


def _flow_mapping(text: str) -> dict[str, str] | None:
    """`{a: 1, b: {c: 2}}` の一番外側の key と値（文字列のまま）。読めなければ None。"""
    text = text.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    body = text[1:-1]
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    current: list[str] = []
    for char in body:
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth < 0:
                return None
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    if depth != 0 or quote is not None:
        return None
    parts.append("".join(current))
    mapping: dict[str, str] = {}
    for part in parts:
        if not part.strip():
            continue
        key, sep, value = part.partition(":")
        if not sep:
            mapping[_unquote(key)] = ""
            continue
        mapping[_unquote(key)] = value.strip()
    return mapping


def _flow_secret_names(workflow_call_value: str) -> set[str]:
    call = _flow_mapping(workflow_call_value)
    if call is None or "secrets" not in call:
        return set()
    secrets = _flow_mapping(call["secrets"])
    return set() if secrets is None else {name.upper() for name in secrets}


def _caller_provided_secrets(lines: list[str]) -> set[str]:
    """`on.workflow_call.secrets` で呼び出し側から受け取る名前（登録先は呼び出し側）。

    ブロック形式・フロー形式（`{required: true}` や `secrets: {A: ...}`）・注釈つきの行を読む。
    読めない形は「受け取らない」とみなす（数える側に倒す＝赤になる側で、緩めない）。
    """
    names: set[str] = set()
    for index, line in enumerate(lines):
        match = _BLOCK_KEY.match(line.strip())
        if match is None:
            continue
        key = _unquote(match.group("key"))
        rest = (match.group("rest") or "").strip()
        if key == "on" and rest.startswith("{"):
            on = _flow_mapping(rest)
            if on is not None and "workflow_call" in on:
                names |= _flow_secret_names(on["workflow_call"])
            continue
        if key != "workflow_call":
            continue
        if rest.startswith("{"):
            names |= _flow_secret_names(rest)
            continue
        if rest:
            continue
        base = _indent(line)
        cursor = index + 1
        while cursor < len(lines):
            current = lines[cursor]
            if current.strip() and _indent(current) <= base:
                break
            child = _BLOCK_KEY.match(current.strip())
            if child is None or _unquote(child.group("key")) != "secrets":
                cursor += 1
                continue
            child_rest = (child.group("rest") or "").strip()
            if child_rest.startswith("{"):
                mapping = _flow_mapping(child_rest)
                if mapping is not None:
                    names |= {name.upper() for name in mapping}
                cursor += 1
                continue
            secrets_indent = _indent(current)
            key_indent: int | None = None
            cursor += 1
            while cursor < len(lines):
                inner = lines[cursor]
                if not inner.strip():
                    cursor += 1
                    continue
                if _indent(inner) <= secrets_indent:
                    break
                if key_indent is None:
                    key_indent = _indent(inner)
                if _indent(inner) == key_indent:
                    entry = _BLOCK_KEY.match(inner.strip())
                    if entry is not None:
                        names.add(_unquote(entry.group("key")).upper())
                cursor += 1
    return names


def extract_secret_names(text: str) -> tuple[str, ...]:
    """workflow が参照する secret の名前（大文字化）。値は読まない。

    YAML の注釈の中の参照は数えない（ブロック文字列の中身は GitHub が展開するので数える）。
    `GITHUB_TOKEN` と、`workflow_call` で呼び出し側から受け取る名前は除く。
    """
    lines = _active_lines(text)
    caller = _caller_provided_secrets(lines)
    found: list[str] = []
    for match in _SECRET_REF.finditer("\n".join(lines)):
        name = (match.group("dot") or match.group("idx")).upper()
        if name in _BUILTIN_SECRETS or name in caller:
            continue
        if name not in found:
            found.append(name)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class CiFacts:
    """CI外の事実。各adapterは自分が要る欄が無ければ fail-closed にする。"""

    tagged_shas: frozenset[str] | None = None
    live_release_assets: frozenset[str] | None = None
    registered_secret_names: frozenset[str] | None = None

    @classmethod
    def from_dict(cls, value: object) -> "CiFacts":
        allowed = {
            "schema", "tagged_shas", "live_release_assets", "registered_secret_names",
        }
        if not isinstance(value, dict) or not set(value) <= allowed:
            raise RatchetError("invalid_ci_facts")
        if value.get("schema") != CI_FACTS_SCHEMA:
            raise RatchetError("invalid_ci_facts_schema")

        def items(key: str, pattern: re.Pattern[str]) -> frozenset[str] | None:
            if key not in value:
                return None
            raw = value[key]
            if not isinstance(raw, list) or len(raw) > MAX_FACT_ITEMS:
                raise RatchetError(f"invalid_ci_facts_{key}")
            for item in raw:
                if type(item) is not str or pattern.fullmatch(item) is None:
                    raise RatchetError(f"invalid_ci_facts_{key}")
            return frozenset(raw)

        return cls(
            tagged_shas=items("tagged_shas", re.compile(r"[0-9a-f]{40}")),
            live_release_assets=items(
                "live_release_assets", re.compile(_ASSET_URL.pattern)
            ),
            registered_secret_names=items("registered_secret_names", _SECRET_NAME),
        )


class _CiAdapterBase:
    adapter_id = ""
    adapter_version = ADAPTER_VERSION

    def __init__(self, facts: CiFacts | None) -> None:
        if facts is None:
            raise RatchetError("ci_facts_required")
        self.facts = facts

    def _observation(self, context: ScanContext, findings: list[Finding]) -> Observation:
        return Observation.create(
            self.adapter_id, self.adapter_version, context.subject, findings
        )


class PinTaggedAdapter(_CiAdapterBase):
    """タグから辿れない固定先SHAをFindingにする。"""

    adapter_id = PIN_TAGGED_ADAPTER_ID

    def __init__(
        self, facts: CiFacts | None, *, pin_owners: tuple[str, ...] = DEFAULT_PIN_OWNERS
    ) -> None:
        super().__init__(facts)
        if self.facts.tagged_shas is None:
            raise RatchetError("ci_facts_missing_tagged_shas")
        self.pin_owners = pin_owners

    def observe(self, context: ScanContext) -> Observation:
        root = context.root
        tagged = self.facts.tagged_shas or frozenset()
        findings: list[Finding] = []
        for path in _iter_ci_files(root):
            rel = _relative(root, path)
            for sha in extract_pins(_read_text(path), pin_owners=self.pin_owners):
                if sha in tagged:
                    continue
                findings.append(
                    Finding.create(
                        adapter_id=self.adapter_id,
                        adapter_version=self.adapter_version,
                        rule_id="pin_not_tagged",
                        subject_kind="ci_pin",
                        subject_key=f"{rel}@{sha}",
                        message="固定先のSHAがタグから辿れない",
                        evidence_sha256=_evidence(rel, sha),
                    )
                )
        return self._observation(context, findings)


class ReleaseAssetLiveAdapter(_CiAdapterBase):
    """生きていない GitHub Release 配布先URLをFindingにする。"""

    adapter_id = RELEASE_ASSET_LIVE_ADAPTER_ID

    def __init__(self, facts: CiFacts | None) -> None:
        super().__init__(facts)
        if self.facts.live_release_assets is None:
            raise RatchetError("ci_facts_missing_live_release_assets")

    def observe(self, context: ScanContext) -> Observation:
        root = context.root
        live = self.facts.live_release_assets or frozenset()
        findings: list[Finding] = []
        for path in _iter_asset_files(root):
            rel = _relative(root, path)
            for url in extract_asset_urls(_read_text(path)):
                if url in live:
                    continue
                digest = _evidence(url)
                findings.append(
                    Finding.create(
                        adapter_id=self.adapter_id,
                        adapter_version=self.adapter_version,
                        rule_id="release_asset_not_live",
                        subject_kind="ci_release_asset",
                        subject_key=f"{rel}#asset-{digest[:16]}",
                        message="配布先URLが生きていない（200で取れない）",
                        evidence_sha256=_evidence(rel, url),
                    )
                )
        return self._observation(context, findings)


class SecretDeclaredAdapter(_CiAdapterBase):
    """登録されていない secret 名の参照をFindingにする（名前だけを見る）。"""

    adapter_id = SECRET_DECLARED_ADAPTER_ID

    def __init__(self, facts: CiFacts | None) -> None:
        super().__init__(facts)
        if self.facts.registered_secret_names is None:
            raise RatchetError("ci_facts_missing_registered_secret_names")

    def observe(self, context: ScanContext) -> Observation:
        root = context.root
        registered = {name.upper() for name in self.facts.registered_secret_names or ()}
        missing: set[str] = set()
        for path in _iter_ci_files(root):
            for name in extract_secret_names(_read_text(path)):
                if name not in registered:
                    missing.add(name)
        findings = [
            Finding.create(
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                rule_id="secret_not_registered",
                subject_kind="ci_secret_name",
                subject_key=f"secret:{name}",
                message="workflow が使う secret の名前が登録されていない",
                evidence_sha256=_evidence(name),
            )
            for name in sorted(missing)
        ]
        return self._observation(context, findings)


def required_secret_names(root: Path) -> tuple[str, ...]:
    """collector 用: repo が要る secret 名の一覧（値は扱わない）。"""
    names: set[str] = set()
    for path in _iter_ci_files(root):
        names.update(extract_secret_names(_read_text(path)))
    return tuple(sorted(names))


def referenced_asset_urls(root: Path) -> tuple[str, ...]:
    """collector 用: repo が参照する配布先URLの一覧。"""
    urls: list[str] = []
    for path in _iter_asset_files(root):
        for url in extract_asset_urls(_read_text(path)):
            if url not in urls:
                urls.append(url)
    return tuple(urls)
