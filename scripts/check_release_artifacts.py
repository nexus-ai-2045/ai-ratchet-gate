#!/usr/bin/env python3
"""GitHub Releaseへ添付する配布物を、外部送信せず検査する。"""

from __future__ import annotations

import argparse
import base64
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

from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_CLASSIFIER = "Private :: Do Not Upload"
REQUIRED_WHEEL_SUFFIXES = (
    "ai_ratchet_gate/__init__.py",
    "ai_ratchet_gate/__main__.py",
    "ai_ratchet_gate/cli.py",
)
REQUIRED_SDIST_MATCH_SUFFIXES = (
    "CHANGELOG.md",
    "ROADMAP.md",
    "scripts/check_release_changelog.py",
)
ALLOWED_SDIST_SUFFIXES = (
    ".ai-ratchet-gate/baseline.txt",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "MANIFEST.in",
    "OPERATIONS.md",
    "PREFLIGHT.md",
    "pyproject.toml",
    "README.md",
    "ROADMAP.md",
    "LICENSE",
    "SECURITY.md",
    "docs/architecture.md",
    "docs/release.md",
    "docs/threat-model.md",
    "scripts/verify.py",
    "scripts/check_release_artifacts.py",
    "scripts/check_release_changelog.py",
    "scripts/smoke_install_artifacts.py",
    "src/ai_ratchet_gate/__init__.py",
    "src/ai_ratchet_gate/__main__.py",
    "src/ai_ratchet_gate/cli.py",
    "src/ai_ratchet_gate.egg-info/PKG-INFO",
    "src/ai_ratchet_gate.egg-info/SOURCES.txt",
    "src/ai_ratchet_gate.egg-info/dependency_links.txt",
    "src/ai_ratchet_gate.egg-info/entry_points.txt",
    "src/ai_ratchet_gate.egg-info/requires.txt",
    "src/ai_ratchet_gate.egg-info/top_level.txt",
    "tests/test_ai_ratchet_gate.py",
    "tests/test_package_metadata.py",
    "tests/test_release_artifacts.py",
    "tests/test_release_changelog.py",
    "tests/test_smoke_install_artifacts.py",
    "ai_ratchet_gate.py",
    "setup.cfg",
)


def dependency_signature(
    requirement: str, extra: str = ""
) -> tuple[str, tuple[str, ...], tuple[str, ...], str, str]:
    parsed = Requirement(requirement)
    marker = parsed.marker
    if extra:
        extra_marker = Marker(f'extra == "{extra}"')
        marker = Marker(f"({marker}) and ({extra_marker})") if marker else extra_marker
    return (
        canonicalize_name(parsed.name),
        tuple(sorted(str(item) for item in parsed.specifier)),
        tuple(sorted(canonicalize_name(item) for item in parsed.extras)),
        parsed.url or "",
        str(marker) if marker is not None else "",
    )


def project_metadata() -> tuple[
    str,
    str,
    str,
    str,
    str,
    tuple[tuple[str, tuple[str, ...], tuple[str, ...], str, str], ...],
    tuple[str, ...],
]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    command, target = next(iter(project["scripts"].items()))
    dependencies = [
        dependency_signature(item) for item in project.get("dependencies", [])
    ]
    optional_dependencies = project.get("optional-dependencies", {})
    for extra, requirements in optional_dependencies.items():
        dependencies.extend(dependency_signature(item, extra) for item in requirements)
    return (
        project["name"],
        project["version"],
        project["requires-python"],
        command,
        target,
        tuple(sorted(dependencies)),
        tuple(sorted(canonicalize_name(item) for item in optional_dependencies)),
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    expected_dependencies: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...], str, str], ...
    ],
    expected_extras: tuple[str, ...],
) -> None:
    metadata = email.message_from_bytes(raw_metadata)
    if metadata["Name"] != expected_name:
        raise ValueError(f"package名が不一致です: {metadata['Name']}")
    if metadata["Version"] != expected_version:
        raise ValueError(f"versionが不一致です: {metadata['Version']}")
    if metadata["License-Expression"] != "MIT":
        raise ValueError(
            f"licenseがMITではありません: {metadata['License-Expression']}"
        )
    if metadata["Requires-Python"] != expected_requires_python:
        raise ValueError(f"Requires-Pythonが不一致です: {metadata['Requires-Python']}")
    if "LICENSE" not in metadata.get_all("License-File", []):
        raise ValueError("metadataにLicense-File: LICENSEがありません")
    actual_dependencies = tuple(
        sorted(
            dependency_signature(item) for item in metadata.get_all("Requires-Dist", [])
        )
    )
    if actual_dependencies != expected_dependencies:
        raise ValueError("Requires-Distがpyproject.tomlと一致しません")
    actual_extras = tuple(
        sorted(
            canonicalize_name(item) for item in metadata.get_all("Provides-Extra", [])
        )
    )
    if actual_extras != expected_extras:
        raise ValueError("Provides-Extraがpyproject.tomlと一致しません")
    if PRIVATE_CLASSIFIER not in metadata.get_all("Classifier", []):
        raise ValueError("PyPIへの誤送信を拒否するclassifierがありません")


def validate_wheel(
    path: Path,
    expected_name: str,
    expected_version: str,
    expected_requires_python: str,
    expected_command: str,
    expected_target: str,
    expected_dependencies: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...], str, str], ...
    ],
    expected_extras: tuple[str, ...],
    artifact_data: bytes | None = None,
) -> None:
    expected_filename = (
        f"{re.sub(r'[-_.]+', '_', expected_name)}-{expected_version}-py3-none-any.whl"
    )
    if path.name != expected_filename:
        raise ValueError(f"wheelファイル名が不正です: {path.name}")
    source: Path | io.BytesIO = (
        path if artifact_data is None else io.BytesIO(artifact_data)
    )
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        metadata_files = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
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
        top_level_file = f"{dist_info}top_level.txt"
        if not {wheel_file, record_file, entry_points_file, license_file}.issubset(
            names
        ):
            raise ValueError(
                "wheelの制御ファイル、entry point、またはLICENSEがありません"
            )
        allowed_names = set(REQUIRED_WHEEL_SUFFIXES) | {
            metadata_files[0],
            wheel_file,
            record_file,
            entry_points_file,
            license_file,
            top_level_file,
        }
        unexpected = sorted(names - allowed_names)
        if unexpected:
            raise ValueError(
                f"wheelに未許可ファイルがあります: {', '.join(unexpected)}"
            )
        for module_name in REQUIRED_WHEEL_SUFFIXES:
            source = ROOT / "src" / module_name
            if archive.read(module_name) != source.read_bytes():
                raise ValueError(
                    f"wheelの実行コードがレビュー済みsourceと不一致です: {module_name}"
                )

        validate_metadata(
            archive.read(metadata_files[0]),
            expected_name,
            expected_version,
            expected_requires_python,
            expected_dependencies,
            expected_extras,
        )
        if archive.read(license_file) != (ROOT / "LICENSE").read_bytes():
            raise ValueError("wheelのLICENSE本文がrepo正本と一致しません")
        entry_points = configparser.ConfigParser(interpolation=None)
        entry_points.read_string(archive.read(entry_points_file).decode("utf-8"))
        if entry_points.sections() != ["console_scripts"] or dict(
            entry_points.items("console_scripts")
        ) != {expected_command: expected_target}:
            raise ValueError("console entry pointがpyproject.tomlと一致しません")
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
        record_by_name = {row[0]: row for row in records if row}
        if set(record_by_name) != names:
            raise ValueError("RECORDのファイル一覧がwheel内容と一致しません")
        for name in names - {record_file}:
            row = record_by_name[name]
            if len(row) != 3 or not row[1].startswith("sha256=") or not row[2]:
                raise ValueError(f"RECORDのhashまたはsizeがありません: {name}")
            data = archive.read(name)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(
                b"="
            )
            if row[1] != f"sha256={digest.decode('ascii')}" or row[2] != str(len(data)):
                raise ValueError(f"RECORDのhashまたはsizeが不一致です: {name}")
    require_exact_names(names, REQUIRED_WHEEL_SUFFIXES)


def validate_sdist(
    path: Path,
    expected_name: str,
    expected_version: str,
    expected_requires_python: str,
    expected_dependencies: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...], str, str], ...
    ],
    expected_extras: tuple[str, ...],
    artifact_data: bytes | None = None,
) -> None:
    root = f"{re.sub(r'[-_.]+', '_', expected_name)}-{expected_version}"
    source = None if artifact_data is None else io.BytesIO(artifact_data)
    with tarfile.open(
        path if source is None else None, "r:gz", fileobj=source
    ) as archive:
        members = archive.getmembers()
        outside_root = [
            member.name
            for member in members
            if member.name != root and not member.name.startswith(f"{root}/")
        ]
        if outside_root:
            raise ValueError(
                f"sdistに期待するroot外のmemberがあります: {', '.join(outside_root)}"
            )
        invalid_members = [
            member.name
            for member in members
            if not member.isfile() and not member.isdir()
        ]
        if invalid_members:
            raise ValueError(
                f"sdistに通常ファイル以外があります: {', '.join(invalid_members)}"
            )
        files = {member.name: member for member in members if member.isfile()}
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
            stream.read(),
            expected_name,
            expected_version,
            expected_requires_python,
            expected_dependencies,
            expected_extras,
        )
        license_member = files.get(f"{root}/LICENSE")
        if license_member is None:
            raise ValueError("sdistにLICENSEがありません")
        license_stream = archive.extractfile(license_member)
        if license_stream is None:
            raise ValueError("sdistのLICENSEを読み込めません")
        license_data = license_stream.read()
        source_data: dict[str, bytes] = {}
        for wheel_name in REQUIRED_WHEEL_SUFFIXES:
            source_name = f"src/{wheel_name}"
            source_member = files.get(f"{root}/{source_name}")
            if source_member is None:
                raise ValueError(f"sdistに実行コードがありません: {source_name}")
            source_stream = archive.extractfile(source_member)
            if source_stream is None:
                raise ValueError(f"sdistの実行コードを読み込めません: {source_name}")
            source_data[source_name] = source_stream.read()
        for source_name in REQUIRED_SDIST_MATCH_SUFFIXES:
            source_member = files.get(f"{root}/{source_name}")
            if source_member is None:
                raise ValueError(f"sdistに検査対象文書がありません: {source_name}")
            source_stream = archive.extractfile(source_member)
            if source_stream is None:
                raise ValueError(f"sdistの検査対象文書を読めません: {source_name}")
            source_data[source_name] = source_stream.read()
    allowed_names = {f"{root}/{name}" for name in ALLOWED_SDIST_SUFFIXES} | {
        metadata_files[0]
    }
    unexpected = sorted(names - allowed_names)
    missing = sorted(allowed_names - names)
    if unexpected or missing:
        raise ValueError(
            "sdist内容がallowlistと一致しません: "
            f"unexpected={','.join(unexpected)} missing={','.join(missing)}"
        )
    if license_data != (ROOT / "LICENSE").read_bytes():
        raise ValueError("sdistのLICENSE本文がrepo正本と一致しません")
    for source_name, data in source_data.items():
        if data != (ROOT / source_name).read_bytes():
            raise ValueError(f"sdist内容がrepo正本と一致しません: {source_name}")


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
        (
            name,
            version,
            requires_python,
            command,
            target,
            dependencies,
            extras,
        ) = project_metadata()
        wheel = select_one(args.dist_dir, f"{name.replace('-', '_')}-{version}-*.whl")
        sdist = select_one(args.dist_dir, f"{name.replace('-', '_')}-{version}.tar.gz")
        wheel_data = wheel.read_bytes()
        sdist_data = sdist.read_bytes()
        validate_wheel(
            wheel,
            name,
            version,
            requires_python,
            command,
            target,
            dependencies,
            extras,
            artifact_data=wheel_data,
        )
        validate_sdist(
            sdist,
            name,
            version,
            requires_python,
            dependencies,
            extras,
            artifact_data=sdist_data,
        )
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"ERROR [release-artifacts]: {error}")
        return 1

    for path, data in ((wheel, wheel_data), (sdist, sdist_data)):
        print(f"OK {path.name} sha256={sha256(data)}")
    print("==> release artifacts OK (外部送信なし)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
