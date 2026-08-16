from __future__ import annotations

import email.message
import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release_artifacts.py"
SPEC = importlib.util.spec_from_file_location("check_release_artifacts", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def metadata_bytes(
    *,
    private_classifier: bool = True,
    version: str = "0.1.0",
    requires_python: str = ">=3.11",
) -> bytes:
    metadata = email.message.Message()
    metadata["Name"] = "ai-ratchet-gate"
    metadata["Version"] = version
    metadata["License-Expression"] = "MIT"
    metadata["License-File"] = "LICENSE"
    metadata["Requires-Python"] = requires_python
    if private_classifier:
        metadata["Classifier"] = CHECK.PRIVATE_CLASSIFIER
    return metadata.as_bytes()


def write_wheel(
    path: Path,
    *,
    private_classifier: bool = True,
    include_controls: bool = True,
    dist_info: str = "ai_ratchet_gate-0.1.0.dist-info/",
    wheel_version: str = "1.0",
    module_prefix: str = "",
    include_entry_point: bool = True,
    include_license: bool = True,
    requires_python: str = ">=3.11",
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name in CHECK.REQUIRED_WHEEL_SUFFIXES:
            archive.writestr(f"{module_prefix}{name}", "")
        metadata_file = f"{dist_info}METADATA"
        archive.writestr(
            metadata_file,
            metadata_bytes(
                private_classifier=private_classifier,
                requires_python=requires_python,
            ),
        )
        if include_controls:
            wheel_file = f"{dist_info}WHEEL"
            record_file = f"{dist_info}RECORD"
            archive.writestr(
                wheel_file,
                f"Wheel-Version: {wheel_version}\nTag: py3-none-any\n",
            )
            archive.writestr(
                record_file,
                f"{metadata_file},,\n{wheel_file},,\n{record_file},,\n",
            )
        if include_entry_point:
            archive.writestr(
                f"{dist_info}entry_points.txt",
                "[console_scripts]\nai-ratchet-gate = ai_ratchet_gate.cli:main\n",
            )
        if include_license:
            archive.writestr(f"{dist_info}licenses/LICENSE", "MIT")


def write_sdist(
    path: Path, *, version: str = "0.1.0", omit: str | None = None
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        files = {
            **{suffix: b"test" for suffix in CHECK.REQUIRED_SDIST_SUFFIXES},
            "PKG-INFO": metadata_bytes(version=version),
        }
        if omit is not None:
            files.pop(omit)
        for suffix, data in files.items():
            info = tarfile.TarInfo(f"ai_ratchet_gate-0.1.0/{suffix}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_release_artifacts_accept_expected_archives(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel)
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 0


def test_release_artifacts_require_pypi_rejection_classifier(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, private_classifier=False)
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_require_wheel_control_files(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, include_controls=False)
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_validate_sdist_metadata(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel)
    write_sdist(sdist, version="9.9.9")

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_require_sdist_build_metadata(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel)
    write_sdist(sdist, omit="pyproject.toml")

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_reject_unsupported_wheel_version(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, wheel_version="99.0")
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_require_matching_dist_info(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, dist_info="unrelated-0.1.0.dist-info/")
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_require_top_level_modules(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, module_prefix="decoy/")
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_require_sdist_files_at_root(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel)
    write_sdist(sdist)

    with tarfile.open(sdist, "r:gz") as source, tarfile.open(
        tmp_path / "nested.tar.gz", "w:gz"
    ) as target:
        for member in source.getmembers():
            data = source.extractfile(member)
            if member.name.endswith("/pyproject.toml"):
                member.name = member.name.replace(
                    "/pyproject.toml", "/decoy/pyproject.toml"
                )
            target.addfile(member, data)
    (tmp_path / "nested.tar.gz").replace(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_require_console_entry_point(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, include_entry_point=False)
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_reject_invalid_wheel_filename(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-invalid.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel)
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_require_wheel_license(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, include_license=False)
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1


def test_release_artifacts_validate_requires_python(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_ratchet_gate-0.1.0-py3-none-any.whl"
    sdist = tmp_path / "ai_ratchet_gate-0.1.0.tar.gz"
    write_wheel(wheel, requires_python=">=99")
    write_sdist(sdist)

    assert CHECK.main(["--dist-dir", str(tmp_path)]) == 1
