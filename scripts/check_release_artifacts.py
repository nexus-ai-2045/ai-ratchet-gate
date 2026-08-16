#!/usr/bin/env python3
"""GitHub Releaseへ添付する配布物を、外部送信せず検査する。"""

from __future__ import annotations

import argparse
import configparser
import csv
import email
import hashlib
import io
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_CLASSIFIER = "Private :: Do Not Upload"
REQUIRED_WHEEL_SUFFIXES = (
    "ai_ratchet_gate/__init__.py",
    "ai_ratchet_gate/__main__.py",
    "ai_ratchet_gate/cli.py",
)
REQUIRED_SDIST_SUFFIXES = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "PUBLIC_READY.md",
    "docs/architecture.md",
    "docs/release.md",
    "docs/threat-model.md",
    "scripts/verify.py",
    "src/ai_ratchet_gate/cli.py",
)


def project_metadata() -> tuple[str, str, str, str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    command, target = next(iter(project["scripts"].items()))
    return (
        project["name"],
        project["version"],
        project["requires-python"],
        command,
        target,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_exact_names(names: set[str], required_names: tuple[str, ...]) -> None:
    missing = [name for name in required_names if name not in names]
    if missing:
        raise ValueError(f"配布物に必須ファイルがありません: {', '.join(missing)}")


def wheel_dist_info(expected_name: str, expected_version: str) -> str:
    normalized_name = re.sub(r"[-_.]+", "_", expected_name)
    normalized_version = expected_version.replace("-", "_")
    return f"{normalized_name}-{normalized_version}.dist-info/"


def validate_metadata(
    raw_metadata: bytes,
    expected_name: str,
    expected_version: str,
    expected_requires_python: str,
) -> None:
    metadata = email.message_from_bytes(raw_metadata)
    if metadata["Name"] != expected_name:
        raise ValueError(f"package名が不一致です: {metadata['Name']}")
    if metadata["Version"] != expected_version:
        raise ValueError(f"versionが不一致です: {metadata['Version']}")
    if metadata["License-Expression"] != "MIT":
        raise ValueError(f"licenseがMITではありません: {metadata['License-Expression']}")
    if metadata["Requires-Python"] != expected_requires_python:
        raise ValueError(
            f"Requires-Pythonが不一致です: {metadata['Requires-Python']}"
        )
    if "LICENSE" not in metadata.get_all("License-File", []):
        raise ValueError("metadataにLicense-File: LICENSEがありません")
    if PRIVATE_CLASSIFIER not in metadata.get_all("Classifier", []):
        raise ValueError("PyPIへの誤送信を拒否するclassifierがありません")


def validate_wheel(
    path: Path,
    expected_name: str,
    expected_version: str,
    expected_requires_python: str,
    expected_command: str,
    expected_target: str,
) -> None:
    expected_filename = (
        f"{re.sub(r'[-_.]+', '_', expected_name)}-{expected_version}-py3-none-any.whl"
    )
    if path.name != expected_filename:
        raise ValueError(f"wheelファイル名が不正です: {path.name}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError("wheelのMETADATAが一意ではありません")
        dist_info = metadata_files[0].removesuffix("METADATA")
        expected_dist_info = wheel_dist_info(expected_name, expected_version)
        if dist_info != expected_dist_info:
            raise ValueError(
                f"wheelのdist-info名が不一致です: {dist_info.removesuffix('/')}"
            )
        wheel_file = f"{dist_info}WHEEL"
        record_file = f"{dist_info}RECORD"
        entry_points_file = f"{dist_info}entry_points.txt"
        license_file = f"{dist_info}licenses/LICENSE"
        if not {wheel_file, record_file, entry_points_file, license_file}.issubset(names):
            raise ValueError("wheelの制御ファイル、entry point、またはLICENSEがありません")

        validate_metadata(
            archive.read(metadata_files[0]),
            expected_name,
            expected_version,
            expected_requires_python,
        )
        entry_points = configparser.ConfigParser(interpolation=None)
        entry_points.read_string(archive.read(entry_points_file).decode("utf-8"))
        if entry_points.get("console_scripts", expected_command, fallback=None) != expected_target:
            raise ValueError(f"console entry pointが不一致です: {expected_command}")
        wheel_metadata = email.message_from_bytes(archive.read(wheel_file))
        wheel_version = wheel_metadata["Wheel-Version"]
        if not wheel_version:
            raise ValueError("WHEELにWheel-Versionがありません")
        try:
            wheel_major = int(wheel_version.split(".", 1)[0])
        except ValueError as error:
            raise ValueError(f"Wheel-Versionが不正です: {wheel_version}") from error
        if wheel_major != 1:
            raise ValueError(f"未対応のWheel-Versionです: {wheel_version}")
        records = list(
            csv.reader(io.StringIO(archive.read(record_file).decode("utf-8")))
        )
        recorded_names = {row[0] for row in records if row}
        if not {metadata_files[0], wheel_file, record_file}.issubset(recorded_names):
            raise ValueError("RECORDにwheel制御ファイルが記録されていません")
    require_exact_names(names, REQUIRED_WHEEL_SUFFIXES)


def validate_sdist(
    path: Path,
    expected_name: str,
    expected_version: str,
    expected_requires_python: str,
) -> None:
    with tarfile.open(path, "r:gz") as archive:
        files = {member.name: member for member in archive.getmembers() if member.isfile()}
        names = set(files)
        metadata_files = [
            name
            for name in names
            if name.endswith("/PKG-INFO") and name.count("/") == 1
        ]
        if len(metadata_files) != 1:
            raise ValueError("sdistのPKG-INFOが一意ではありません")
        stream = archive.extractfile(files[metadata_files[0]])
        if stream is None:
            raise ValueError("sdistのPKG-INFOを読み込めません")
        validate_metadata(
            stream.read(), expected_name, expected_version, expected_requires_python
        )
    root = f"{re.sub(r'[-_.]+', '_', expected_name)}-{expected_version}"
    require_exact_names(names, tuple(f"{root}/{name}" for name in REQUIRED_SDIST_SUFFIXES))


def select_one(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"{pattern} は1件必要です: {len(matches)}件")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)

    try:
        name, version, requires_python, command, target = project_metadata()
        wheel = select_one(args.dist_dir, f"{name.replace('-', '_')}-{version}-*.whl")
        sdist = select_one(args.dist_dir, f"{name.replace('-', '_')}-{version}.tar.gz")
        validate_wheel(wheel, name, version, requires_python, command, target)
        validate_sdist(sdist, name, version, requires_python)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"ERROR [release-artifacts]: {error}")
        return 1

    for path in (wheel, sdist):
        print(f"OK {path.name} sha256={sha256(path)}")
    print("==> release artifacts OK (外部送信なし)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
