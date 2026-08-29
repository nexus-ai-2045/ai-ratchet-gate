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
_JS_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_PY_SKIP_IMPORT_NAMES = frozenset({"skip", "SkipTest"})


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _evidence(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _encode_identity_component(value: str) -> str:
    """subject_key 全体を `/` 分割しても path traversal と誤認されないよう符号化。"""
    return value.replace("%", "%25").replace("/", "%2F")


def _subject_key(rel_path: str, qualified_name: str) -> str:
    path = _nfc(rel_path)
    name = _encode_identity_component(_nfc(qualified_name))
    if not path or not name or "::" in path:
        raise RatchetError("invalid_test_subject_key")
    if path.startswith("/") or any(
        part in {"", ".", ".."} for part in path.split("/")
    ):
        raise RatchetError("invalid_test_subject_key")
    key = f"{path}::{name}"
    if any(part in {"", ".", ".."} for part in key.split("/")):
        raise RatchetError("invalid_test_subject_key")
    return key


def _qualify(*parts: str) -> str:
    cleaned = [_nfc(part) for part in parts if part]
    if not cleaned or any("::" in part for part in cleaned):
        raise RatchetError("invalid_test_subject_key")
    return "::".join(cleaned)


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


def _py_collect_skip_aliases(tree: ast.AST) -> frozenset[str]:
    """from pytest/unittest import skip 等の裸名だけを許可する。"""
    aliases: set[str] = set()
    for node in getattr(tree, "body", ()):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module not in {"pytest", "unittest", "unittest.case"}:
                continue
            for alias in node.names:
                if alias.name in _PY_SKIP_IMPORT_NAMES:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            # import pytest は Attribute 呼び出し側で見る
            continue
    return frozenset(aliases)


def _py_name_is(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _py_call_is_unconditional_skip(
    call: ast.Call, *, skip_aliases: frozenset[str]
) -> bool:
    """本体先頭の pytest.skip / 許可された裸 skip / unittest.skipTest。"""
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr == "skip" and _py_name_is(func.value, "pytest"):
            return True
        if func.attr == "skipTest" and _py_name_is(func.value, "unittest"):
            return True
        if func.attr == "skipTest" and isinstance(func.value, ast.Name):
            # self.skipTest(...) on TestCase
            return func.value.id == "self"
        return False
    if isinstance(func, ast.Name) and func.id in skip_aliases:
        return True
    return False


def _py_raise_is_skip_test(node: ast.Raise, *, skip_aliases: frozenset[str]) -> bool:
    if node.exc is None:
        return False
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Attribute) and exc.attr == "SkipTest":
        return True
    if isinstance(exc, ast.Name) and (
        exc.id == "SkipTest" or exc.id in skip_aliases
    ):
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


def _py_body_has_unconditional_skip_call(
    body: list[ast.stmt], *, skip_aliases: frozenset[str]
) -> bool:
    effective = _py_effective_body(body)
    if not effective:
        return False
    first = effective[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Call):
        return _py_call_is_unconditional_skip(
            first.value, skip_aliases=skip_aliases
        )
    if isinstance(first, ast.Raise):
        return _py_raise_is_skip_test(first, skip_aliases=skip_aliases)
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


def _py_bases_include_testcase(bases: list[ast.expr]) -> bool:
    for base in bases:
        if isinstance(base, ast.Name) and base.id == "TestCase":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "TestCase":
            return True
    return False


def _py_is_test_class(node: ast.ClassDef) -> bool:
    name = node.name
    if name.startswith("Test") or name.endswith("Test") or name.endswith("Tests"):
        return True
    return _py_bases_include_testcase(node.bases)


def _scan_python(rel_path: str, source: str) -> list[tuple[str, str, str]]:
    """(rule_id, qualified_name, message) のリスト。"""
    del rel_path
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise RatchetError("test_python_parse_failed") from error
    skip_aliases = _py_collect_skip_aliases(tree)
    findings: list[tuple[str, str, str]] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []
            # 祖先クラスが無条件skip / skipif ならメソッドの hollow を出さない
            self.skip_depth = 0
            self.skipif_depth = 0

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            is_test = _py_is_test_class(node)
            has_skipif = is_test and _py_has_skipif_decorator(node.decorator_list)
            has_skip = is_test and _py_has_unconditional_skip_decorator(
                node.decorator_list
            )
            if is_test and has_skip and not has_skipif:
                findings.append(
                    (
                        "unconditional_skip",
                        _qualify(*self.class_stack, node.name),
                        "unconditional skip decorator on test class",
                    )
                )
            entered = is_test
            if entered:
                self.class_stack.append(node.name)
                if has_skipif:
                    self.skipif_depth += 1
                if has_skip and not has_skipif:
                    self.skip_depth += 1
            self.generic_visit(node)
            if entered:
                if has_skip and not has_skipif:
                    self.skip_depth -= 1
                if has_skipif:
                    self.skipif_depth -= 1
                self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)
            self.generic_visit(node)

        def _visit_function(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef
        ) -> None:
            if not _py_is_test_function(node.name):
                return
            qualified = _qualify(*self.class_stack, node.name)
            if _py_has_skipif_decorator(node.decorator_list) or self.skipif_depth:
                return
            if _py_has_unconditional_skip_decorator(node.decorator_list):
                findings.append(
                    (
                        "unconditional_skip",
                        qualified,
                        "unconditional skip decorator observed",
                    )
                )
                return
            if self.skip_depth:
                # 無条件skip済みクラス配下は実行されない → hollow にしない
                return
            if _py_body_has_unconditional_skip_call(
                node.body, skip_aliases=skip_aliases
            ):
                findings.append(
                    (
                        "unconditional_skip",
                        qualified,
                        "unconditional pytest.skip/SkipTest observed",
                    )
                )
                return
            if _py_body_is_hollow(node.body):
                findings.append(
                    (
                        "hollow_test",
                        qualified,
                        "hollow or assert-True-only test body",
                    )
                )

    _Visitor().visit(tree)
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


def _js_is_suite_callee(callee: str) -> bool:
    normalized = re.sub(r"\s+", "", callee)
    base = normalized.split(".", 1)[0]
    return base in {"describe", "xdescribe", "fdescribe"}


def _js_prepare_source(source: str) -> tuple[str, list[bool]]:
    """コメント・文字列内部を空白化した走査用文字列と、呼び出し開始可能マスクを返す。

    文字列の引用符自体は残し、`test.skip('name'` 形式の正規表現がタイトル位置を
    保持できるようにする。テンプレート式 `${}` は曖昧なので fail-closed。
    """
    length = len(source)
    chars = list(source)
    mask = [True] * length
    index = 0
    while index < length:
        char = source[index]
        nxt = source[index + 1] if index + 1 < length else ""
        if char == "/" and nxt == "/":
            while index < length and source[index] not in "\r\n":
                chars[index] = " "
                mask[index] = False
                index += 1
            continue
        if char == "/" and nxt == "*":
            chars[index] = " "
            chars[index + 1] = " "
            mask[index] = False
            mask[index + 1] = False
            index += 2
            while index < length - 1 and not (
                source[index] == "*" and source[index + 1] == "/"
            ):
                chars[index] = " "
                mask[index] = False
                index += 1
            if index >= length - 1:
                raise RatchetError("test_js_parse_ambiguous")
            chars[index] = " "
            chars[index + 1] = " "
            mask[index] = False
            mask[index + 1] = False
            index += 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            # 引用符は残す（regex が (?P<q>) で捕捉するため）
            mask[index] = False
            index += 1
            while index < length:
                cur = source[index]
                if cur == "\\" and quote != "`":
                    chars[index] = " "
                    mask[index] = False
                    if index + 1 < length:
                        chars[index + 1] = " "
                        mask[index + 1] = False
                    index += 2
                    continue
                if quote == "`" and cur == "\\":
                    chars[index] = " "
                    mask[index] = False
                    if index + 1 < length:
                        chars[index + 1] = " "
                        mask[index + 1] = False
                    index += 2
                    continue
                if (
                    quote == "`"
                    and cur == "$"
                    and index + 1 < length
                    and source[index + 1] == "{"
                ):
                    raise RatchetError("test_js_parse_ambiguous")
                if cur == quote:
                    mask[index] = False
                    index += 1
                    break
                chars[index] = " "
                mask[index] = False
                index += 1
            else:
                raise RatchetError("test_js_parse_ambiguous")
            continue
        index += 1
    return "".join(chars), mask


def _js_skip_ws(source: str, index: int) -> int:
    length = len(source)
    while index < length and source[index] in " \t\r\n":
        index += 1
    return index


def _js_consume_balanced(
    source: str, start: int, open_char: str, close_char: str
) -> int:
    if start >= len(source) or source[start] != open_char:
        raise RatchetError("test_js_parse_ambiguous")
    depth = 0
    index = start
    length = len(source)
    in_str: str | None = None
    while index < length:
        char = source[index]
        if in_str is not None:
            if char == "\\" and in_str != "`":
                index += 2
                continue
            if in_str == "`" and char == "\\":
                index += 2
                continue
            if in_str == "`" and char == "$" and index + 1 < length and source[index + 1] == "{":
                raise RatchetError("test_js_parse_ambiguous")
            if char == in_str:
                in_str = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            in_str = char
            index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            index += 2
            while index < length and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            index += 2
            while index < length - 1 and not (
                source[index] == "*" and source[index + 1] == "/"
            ):
                index += 1
            index = index + 2 if index < length - 1 else length
            continue
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise RatchetError("test_js_parse_ambiguous")


def _js_parse_callback_body(source: str, after_title: int) -> tuple[str, int]:
    """タイトル直後から callback 本体を取り、(body, end_index) を返す。

    end_index は callback 終端の次。expression-bodied も明示的に扱う。
    境界が取れない場合は fail-closed。
    """
    index = _js_skip_ws(source, after_title)
    if index >= len(source) or source[index] != ",":
        # test.todo('x') のように callback なし
        return "", after_title
    index = _js_skip_ws(source, index + 1)
    if index >= len(source):
        raise RatchetError("test_js_parse_ambiguous")

    if source.startswith("async", index) and (
        index + 5 >= len(source) or not (source[index + 5].isalnum() or source[index + 5] in "_$")
    ):
        index = _js_skip_ws(source, index + 5)

    if source.startswith("function", index) and (
        index + 8 >= len(source) or not (source[index + 8].isalnum() or source[index + 8] in "_$")
    ):
        index = _js_skip_ws(source, index + 8)
        if index < len(source) and (source[index].isalpha() or source[index] in "_$"):
            match = _JS_IDENT.match(source, index)
            if match is None:
                raise RatchetError("test_js_parse_ambiguous")
            index = _js_skip_ws(source, match.end())
        if index >= len(source) or source[index] != "(":
            raise RatchetError("test_js_parse_ambiguous")
        index = _js_skip_ws(source, _js_consume_balanced(source, index, "(", ")"))
        if index >= len(source) or source[index] != "{":
            raise RatchetError("test_js_parse_ambiguous")
        body_start = index + 1
        body_end = _js_consume_balanced(source, index, "{", "}") - 1
        return source[body_start:body_end], body_end + 1

    # arrow params: ( ... ) or single ident
    if source[index] == "(":
        index = _js_skip_ws(source, _js_consume_balanced(source, index, "(", ")"))
    else:
        match = _JS_IDENT.match(source, index)
        if match is None:
            raise RatchetError("test_js_parse_ambiguous")
        index = _js_skip_ws(source, match.end())

    if not source.startswith("=>", index):
        raise RatchetError("test_js_parse_ambiguous")
    index = _js_skip_ws(source, index + 2)
    if index >= len(source):
        raise RatchetError("test_js_parse_ambiguous")

    if source[index] == "{":
        body_start = index + 1
        body_end = _js_consume_balanced(source, index, "{", "}") - 1
        return source[body_start:body_end], body_end + 1

    # expression-bodied: test('x', () => expect(true).toBe(true))
    expr_start = index
    depth_paren = 0
    depth_brace = 0
    depth_bracket = 0
    in_str: str | None = None
    length = len(source)
    while index < length:
        char = source[index]
        if in_str is not None:
            if char == "\\" and in_str != "`":
                index += 2
                continue
            if in_str == "`" and char == "\\":
                index += 2
                continue
            if in_str == "`" and char == "$" and index + 1 < length and source[index + 1] == "{":
                raise RatchetError("test_js_parse_ambiguous")
            if char == in_str:
                in_str = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            in_str = char
            index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            index += 2
            while index < length and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            index += 2
            while index < length - 1 and not (
                source[index] == "*" and source[index + 1] == "/"
            ):
                index += 1
            index = index + 2 if index < length - 1 else length
            continue
        if char == "(":
            depth_paren += 1
        elif char == ")":
            if depth_paren == 0 and depth_brace == 0 and depth_bracket == 0:
                return source[expr_start:index], index
            depth_paren -= 1
            if depth_paren < 0:
                raise RatchetError("test_js_parse_ambiguous")
        elif char == "{":
            depth_brace += 1
        elif char == "}":
            depth_brace -= 1
            if depth_brace < 0:
                raise RatchetError("test_js_parse_ambiguous")
        elif char == "[":
            depth_bracket += 1
        elif char == "]":
            depth_bracket -= 1
            if depth_bracket < 0:
                raise RatchetError("test_js_parse_ambiguous")
        elif (
            char == ","
            and depth_paren == 0
            and depth_brace == 0
            and depth_bracket == 0
        ):
            return source[expr_start:index], index
        index += 1
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
    del rel_path
    sanitized, mask = _js_prepare_source(source)
    findings: list[tuple[str, str, str]] = []
    # (suite_name, body_end_exclusive)
    suite_stack: list[tuple[str, int]] = []

    matches = list(_JS_CALL.finditer(sanitized))
    for match in matches:
        # コメント・文字列内の見かけの呼び出しは捨てる
        if not mask[match.start()]:
            continue
        callee = match.group("callee")
        # タイトルは original から取る（sanitized の内部は空白）
        name = source[match.start("name") : match.end("name")]
        kind = _js_callee_kind(callee)
        if kind is None:
            continue

        while suite_stack and match.start() >= suite_stack[-1][1]:
            suite_stack.pop()
        suite_names = tuple(item[0] for item in suite_stack)
        qualified = _qualify(*suite_names, name)

        try:
            body, body_end = _js_parse_callback_body(source, match.end())
        except RatchetError:
            raise

        if _js_is_suite_callee(callee) and body_end > match.end():
            # describe 系は本体範囲を suite 境界として積む
            suite_stack.append((name, body_end))

        if kind == "todo":
            continue
        if kind == "only":
            findings.append(
                ("focused_only", qualified, "focused .only/fit/fdescribe observed")
            )
            continue
        if kind == "skip":
            findings.append(
                ("unconditional_skip", qualified, "unconditional skip observed")
            )
            continue
        if kind == "plain":
            if body == "" and not _js_is_suite_callee(callee):
                # callback なしの plain test は観測しない（todo 以外の省略形）
                continue
            if _js_body_is_hollow(body):
                findings.append(
                    (
                        "hollow_test",
                        qualified,
                        "hollow or expect(true)-only test body",
                    )
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
