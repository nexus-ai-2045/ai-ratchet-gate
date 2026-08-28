"""テスト無効化（skip / only / hollow）を read-only 観測する adapter。

Issue #11 / ADR-0005。v1対象は Python + JS/TS。
C1 unconditional_skip / C2 focused_only / C3 hollow_test。
C4・逆さまテストは対象外。skipif（条件付き）は C1 に含めない。
自由記述の skip reason は許可条件にしない（例外は既存 waivers/v1）。
"""

from __future__ import annotations

import ast
import hashlib
import re
import unicodedata
from pathlib import Path

from ..model import Finding, Observation, RatchetError
from .protocol import ScanContext

ADAPTER_ID = "test.disable"
ADAPTER_VERSION = "1"

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".eggs",
    }
)
_PY_TEST_FILE = re.compile(r"(^test_.*\.py$)|(.*_test\.py$)")
_JS_TEST_FILE = re.compile(
    r".*\.(test|spec)\.(js|jsx|ts|tsx)$", re.IGNORECASE
)

# JS/TS: 呼び出し先頭の識別子列（保守的。完全な TS parser は持ち込まない）
_JS_CALL = re.compile(
    r"(?P<callee>\b(?:describe|xdescribe|fdescribe|test|xtest|it|xit|fit)"
    r"(?:\s*\.\s*(?:skip|only|todo))?)\s*\(\s*(?P<q>['\"`])(?P<name>.*?)(?P=q)",
    re.MULTILINE,
)
_JS_HOLLOW_TRUE = re.compile(
    r"expect\s*\(\s*true\s*\)\s*\.\s*toBe\s*\(\s*true\s*\)"
    r"|expect\s*\(\s*true\s*\)\s*\.\s*toBeTruthy\s*\(\s*\)"
    r"|assert\s*\(\s*true\s*\)",
    re.IGNORECASE,
)


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _evidence(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _subject_key(rel_path: str, test_name: str) -> str:
    path = _nfc(rel_path)
    name = _nfc(test_name)
    if not path or not name or "::" in path or "::" in name:
        raise RatchetError("invalid_test_subject_key")
    if path.startswith("/") or any(
        part in {"", ".", ".."} for part in path.split("/")
    ):
        raise RatchetError("invalid_test_subject_key")
    return f"{path}::{name}"


def _repo_relative(root: Path, path: Path) -> str:
    try:
        relative = path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise RatchetError("test_path_escapes_root") from error
    text = relative.as_posix()
    if text.startswith("/") or any(part in {"", ".", ".."} for part in text.split("/")):
        raise RatchetError("invalid_test_path")
    return _nfc(text)


def _is_test_file(name: str) -> bool:
    return bool(_PY_TEST_FILE.match(name) or _JS_TEST_FILE.match(name))


def _iter_test_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError as error:
            raise RatchetError("adapter_observation_failed") from error
        for child in sorted(children, key=lambda item: item.name):
            try:
                if child.is_symlink():
                    raise RatchetError("test_symlink_rejected")
                is_dir = child.is_dir()
                is_file = child.is_file()
            except OSError as error:
                raise RatchetError("adapter_observation_failed") from error
            if is_dir:
                if child.name in _SKIP_DIR_NAMES:
                    continue
                stack.append(child)
                continue
            if is_file and _is_test_file(child.name):
                files.append(child)
    return tuple(sorted(files, key=lambda item: item.as_posix()))


def _decorator_attr_or_name(node: ast.AST) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def _decorator_is_unconditional_skip(node: ast.AST) -> bool:
    """pytest.mark.skip / unittest.skip。skipif は除外。"""
    return _decorator_attr_or_name(node) == "skip"


def _decorator_is_skipif(node: ast.AST) -> bool:
    """pytest.mark.skipif / unittest.skipIf。条件付きなので C1 でも C3 でもない。"""
    name = _decorator_attr_or_name(node)
    return name in {"skipif", "skipIf"}


def _py_has_unconditional_skip_decorator(decorators: list[ast.expr]) -> bool:
    return any(_decorator_is_unconditional_skip(dec) for dec in decorators)


def _py_has_skipif_decorator(decorators: list[ast.expr]) -> bool:
    return any(_decorator_is_skipif(dec) for dec in decorators)


def _py_call_is_unconditional_skip(call: ast.Call) -> bool:
    """本体先頭の pytest.skip(...) / skip(...)（条件なし）。"""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "skip":
        return True
    if isinstance(func, ast.Name) and func.id == "skip":
        return True
    return False


def _py_raise_is_skip_test(node: ast.Raise) -> bool:
    if node.exc is None:
        return False
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Attribute) and exc.attr == "SkipTest":
        return True
    if isinstance(exc, ast.Name) and exc.id == "SkipTest":
        return True
    return False


def _py_effective_body(body: list[ast.stmt]) -> list[ast.stmt]:
    effective: list[ast.stmt] = []
    for index, stmt in enumerate(body):
        if (
            index == 0
            and isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            continue
        effective.append(stmt)
    return effective


def _py_body_has_unconditional_skip_call(body: list[ast.stmt]) -> bool:
    """実行される本体の先頭が無条件 skip 呼び出しなら C1。"""
    effective = _py_effective_body(body)
    if not effective:
        return False
    first = effective[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
        return _py_call_is_unconditional_skip(first.value)
    if isinstance(first, ast.Raise):
        return _py_raise_is_skip_test(first)
    return False


def _py_body_is_hollow(body: list[ast.stmt]) -> bool:
    """実行されるテストの空本体 / assert True のみ。skip 済みは呼ばないこと。"""
    effective = _py_effective_body(body)
    if not effective or all(isinstance(stmt, ast.Pass) for stmt in effective):
        return True
    if len(effective) == 1 and isinstance(effective[0], ast.Assert):
        test = effective[0].test
        if isinstance(test, ast.Constant) and test.value is True:
            return True
    return False


def _py_is_test_function(name: str) -> bool:
    return name.startswith("test")


def _py_is_test_class(name: str) -> bool:
    return name.startswith("Test") or name.endswith("Test") or name.endswith("Tests")


def _scan_python(rel_path: str, source: str) -> list[tuple[str, str, str]]:
    """(rule_id, test_name, message) のリスト。"""
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as error:
        raise RatchetError("test_python_parse_failed") from error
    findings: list[tuple[str, str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if not _py_is_test_function(name):
                continue
            # skipif は C1 でも C3 でもない（条件付き。実行されない場合がある）
            if _py_has_skipif_decorator(node.decorator_list):
                continue
            if _py_has_unconditional_skip_decorator(node.decorator_list):
                findings.append(
                    (
                        "unconditional_skip",
                        name,
                        "unconditional skip decorator observed",
                    )
                )
                continue
            if _py_body_has_unconditional_skip_call(node.body):
                findings.append(
                    (
                        "unconditional_skip",
                        name,
                        "unconditional pytest.skip/SkipTest observed",
                    )
                )
                continue
            # hollow は「実行される」テストだけ
            if _py_body_is_hollow(node.body):
                findings.append(
                    ("hollow_test", name, "hollow or assert-True-only test body")
                )
        elif isinstance(node, ast.ClassDef):
            if not _py_is_test_class(node.name):
                continue
            if _py_has_skipif_decorator(node.decorator_list):
                continue
            if _py_has_unconditional_skip_decorator(node.decorator_list):
                findings.append(
                    (
                        "unconditional_skip",
                        node.name,
                        "unconditional skip decorator on test class",
                    )
                )
    return findings


def _js_callee_kind(callee: str) -> str | None:
    normalized = re.sub(r"\s+", "", callee)
    if normalized.endswith(".todo"):
        return "todo"
    if normalized.endswith(".only") or normalized in {"fit", "fdescribe"}:
        return "only"
    if (
        normalized.endswith(".skip")
        or normalized in {"xit", "xtest", "xdescribe"}
    ):
        return "skip"
    if normalized in {"test", "it", "describe"}:
        return "plain"
    return None


def _js_body_after_call(source: str, match_end: int) -> str:
    """マッチ末尾から関数本体らしき {...} を粗い括弧対応で取る。"""
    index = match_end
    length = len(source)
    while index < length and source[index] in " \t\r\n,":
        index += 1
    brace = source.find("{", index)
    if brace < 0 or brace - index > 120:
        return ""
    depth = 0
    for pos in range(brace, length):
        char = source[pos]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : pos]
    raise RatchetError("test_js_parse_ambiguous")


def _js_body_is_hollow(body: str) -> bool:
    stripped = body.strip()
    if stripped == "":
        return True
    without_comments = re.sub(r"//.*?$", "", stripped, flags=re.MULTILINE)
    without_comments = re.sub(
        r"/\*.*?\*/", "", without_comments, flags=re.DOTALL
    ).strip()
    if without_comments == "":
        return True
    remainder = _JS_HOLLOW_TRUE.sub("", without_comments)
    remainder = re.sub(r"[;\s]+", "", remainder)
    return remainder == ""


def _scan_javascript(rel_path: str, source: str) -> list[tuple[str, str, str]]:
    del rel_path  # 走査キーは呼び出し側で subject に束縛する
    findings: list[tuple[str, str, str]] = []
    for match in _JS_CALL.finditer(source):
        callee = match.group("callee")
        name = match.group("name")
        kind = _js_callee_kind(callee)
        if kind is None:
            continue
        if kind == "todo":
            continue
        if kind == "only":
            findings.append(
                ("focused_only", name, "focused .only/fit/fdescribe observed")
            )
            continue
        if kind == "skip":
            findings.append(
                ("unconditional_skip", name, "unconditional skip observed")
            )
            continue
        if kind == "plain":
            try:
                body = _js_body_after_call(source, match.end())
            except RatchetError:
                raise
            if body == "":
                continue
            if _js_body_is_hollow(body):
                findings.append(
                    ("hollow_test", name, "hollow or expect(true)-only test body")
                )
    return findings


class TestDisableAdapter:
    adapter_id = ADAPTER_ID
    adapter_version = ADAPTER_VERSION

    def observe(self, context: ScanContext) -> Observation:
        try:
            if not context.root.exists() or not context.root.is_dir():
                raise RatchetError("adapter_observation_failed")
            if context.root.is_symlink():
                raise RatchetError("test_symlink_rejected")
        except OSError as error:
            raise RatchetError("adapter_observation_failed") from error

        findings: list[Finding] = []
        for path in _iter_test_files(context.root):
            rel = _repo_relative(context.root, path)
            try:
                raw = path.read_bytes()
            except OSError as error:
                raise RatchetError("adapter_observation_failed") from error
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise RatchetError("test_non_utf8") from error

            if path.suffix == ".py":
                items = _scan_python(rel, text)
            else:
                items = _scan_javascript(rel, text)

            for rule_id, test_name, message in items:
                key = _subject_key(rel, test_name)
                findings.append(
                    Finding.create(
                        adapter_id=self.adapter_id,
                        adapter_version=self.adapter_version,
                        rule_id=rule_id,
                        subject_kind="test_case",
                        subject_key=key,
                        message=message,
                        evidence_sha256=_evidence(rule_id, key, rel),
                    )
                )
        return Observation.create(
            self.adapter_id, self.adapter_version, context.subject, findings
        )
