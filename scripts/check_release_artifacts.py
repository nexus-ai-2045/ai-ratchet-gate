#!/usr/bin/env python3
"""GitHub Releaseへ添付する配布物を、外部送信せず検査する。"""

from __future__ import annotations

import argparse
import csv
import email
import hashlib
import io
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


def project_metadata() -> tuple[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    return project["name"], project["version"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_suffixes(names: set[str], suffixes: tuple[str, ...]) -> None:
    missing = [suffix for suffix in suffixes if not any(n.endswith(suffix) for n in names)]
    if missing:
        raise ValueError(f"配布物に必須ファイルがありません: {', '.join(missing)}")


def validate_metadata(
    raw_metadata: bytes, expected_name: str, expected_version: str
) -> None:
    metadata = email.message_from_bytes(raw_metadata)
    if metadata["Name"] != expected_name:
        raise ValueError(f"package名が不一致です: {metadata['Name']}")
    if metadata["Version"] != expected_version:
        raise ValueError(f"versionが不一致です: {metadata['Version']}")
    if metadata["License-Expression"] != "MIT":
        raise ValueError(f"licenseがMITではありません: {metadata['License-Expression']}")
    if PRIVATE_CLASSIFIER not in metadata.get_all("Classifier", []):
        raise ValueError("PyPIへの誤送信を拒否するclassifierがありません")


def validate_wheel(path: Path, expected_name: str, expected_version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError("wheelのMETADATAが一意ではありません")
        dist_info = metadata_files[0].removesuffix("METADATA")
        wheel_file = f"{dist_info}WHEEL"
        record_file = f"{dist_info}RECORD"
        if wheel_file not in names or record_file not in names:
            raise ValueError("wheelのWHEELまたはRECORDがありません")

        validate_metadata(archive.read(metadata_files[0]), expected_name, expected_version)
        wheel_metadata = email.message_from_bytes(archive.read(wheel_file))
        if not wheel_metadata["Wheel-Version"]:
            raise ValueError("WHEELにWheel-Versionがありません")
        records = list(
            csv.reader(io.StringIO(archive.read(record_file).decode("utf-8")))
        )
        recorded_names = {row[0] for row in records if row}
        if not {metadata_files[0], wheel_file, record_file}.issubset(recorded_names):
            raise ValueError("RECORDにwheel制御ファイルが記録されていません")
    require_suffixes(names, REQUIRED_WHEEL_SUFFIXES)


def validate_sdist(path: Path, expected_name: str, expected_version: str) -> None:
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
        validate_metadata(stream.read(), expected_name, expected_version)
    require_suffixes(names, REQUIRED_SDIST_SUFFIXES)


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
        name, version = project_metadata()
        wheel = select_one(args.dist_dir, f"{name.replace('-', '_')}-{version}-*.whl")
        sdist = select_one(args.dist_dir, f"{name.replace('-', '_')}-{version}.tar.gz")
        validate_wheel(wheel, name, version)
        validate_sdist(sdist, name, version)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"ERROR [release-artifacts]: {error}")
        return 1

    for path in (wheel, sdist):
        print(f"OK {path.name} sha256={sha256(path)}")
    print("==> release artifacts OK (外部送信なし)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
