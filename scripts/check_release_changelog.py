#!/usr/bin/env python3
"""CHANGELOGのrelease version・日付・Unreleased節をfail-closedで検査する。"""

from __future__ import annotations

import argparse
import re
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9), name="Asia/Tokyo")
HEADING = re.compile(r"^## (?P<label>.+)$", re.MULTILINE)
RELEASE_HEADING = re.compile(
    r"^\[(?P<version>\d+\.\d+\.\d+)\] - (?P<release_date>\d{4}-\d{2}-\d{2})$"
)


def project_version() -> str:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    return str(project["version"])


def validate_requested_version(requested: str, actual: str) -> None:
    if requested != actual:
        raise ValueError(
            f"指定versionがpyproject.tomlと不一致です: {requested} != {actual}"
        )


def current_release_date() -> str:
    """IANA timezone databaseに依存せず、JSTの現在日を返す。"""
    return datetime.now(JST).date().isoformat()


def validate_changelog(
    text: str,
    *,
    expected_version: str,
    expected_date: str | None = None,
    require_clean_unreleased: bool = False,
) -> None:
    headings = list(HEADING.finditer(text))
    if len(headings) < 2:
        raise ValueError("CHANGELOGにUnreleased節とrelease節が必要です")
    if headings[0].group("label") != "[Unreleased]":
        raise ValueError("最初のlevel-2見出しは## [Unreleased]である必要があります")

    unreleased_body = text[headings[0].end() : headings[1].start()].strip()
    if require_clean_unreleased and unreleased_body:
        raise ValueError("release候補ではUnreleased節を空にしてください")

    match = RELEASE_HEADING.fullmatch(headings[1].group("label"))
    if match is None:
        raise ValueError("Unreleased直後は## [X.Y.Z] - YYYY-MM-DD形式が必要です")
    actual_version = match.group("version")
    actual_date = match.group("release_date")
    if actual_version != expected_version:
        raise ValueError(
            f"CHANGELOG versionが不一致です: {actual_version} != {expected_version}"
        )
    try:
        date.fromisoformat(actual_date)
    except ValueError as error:
        raise ValueError(f"release日が不正です: {actual_date}") from error
    if expected_date is not None and actual_date != expected_date:
        raise ValueError(
            f"CHANGELOG release日が不一致です: {actual_date} != {expected_date}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actual_version = project_version()
    parser.add_argument("--version", default=actual_version)
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--release-date")
    date_group.add_argument("--require-current-date", action="store_true")
    parser.add_argument("--require-clean-unreleased", action="store_true")
    args = parser.parse_args(argv)
    try:
        validate_requested_version(args.version, actual_version)
        expected_date = (
            current_release_date()
            if args.require_current_date
            else args.release_date
        )
        validate_changelog(
            (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"),
            expected_version=args.version,
            expected_date=expected_date,
            require_clean_unreleased=args.require_clean_unreleased,
        )
    except (OSError, ValueError) as error:
        print(f"ERROR [release-changelog]: {error}")
        return 1
    print(f"OK release changelog: {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
