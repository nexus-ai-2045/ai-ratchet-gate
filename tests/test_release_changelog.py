from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release_changelog.py"
SPEC = importlib.util.spec_from_file_location("check_release_changelog", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def changelog(unreleased: str = "", release_date: str = "2026-08-19") -> str:
    return (
        "# 変更履歴\n\n"
        "## [Unreleased]\n\n"
        f"{unreleased}"
        f"## [0.1.1] - {release_date}\n\n"
        "### 修正\n\n- 文書を訂正\n"
    )


def test_accepts_release_candidate() -> None:
    CHECK.validate_changelog(
        changelog(),
        expected_version="0.1.1",
        require_clean_unreleased=True,
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# 変更履歴\n\n## [0.1.1] - 2026-08-19\n", "Unreleased"),
        (changelog(unreleased="- 未確定\n\n"), "空"),
        (changelog(release_date="2026-99-99"), "不正"),
    ],
)
def test_rejects_invalid_release_state(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CHECK.validate_changelog(
            text,
            expected_version="0.1.1",
            require_clean_unreleased=True,
        )


def test_rejects_version_mismatch() -> None:
    with pytest.raises(ValueError, match="versionが不一致"):
        CHECK.validate_changelog(changelog(), expected_version="0.1.2")


def test_rejects_requested_version_that_differs_from_package() -> None:
    with pytest.raises(ValueError, match="pyproject.tomlと不一致"):
        CHECK.validate_requested_version("0.1.2", "0.1.1")
