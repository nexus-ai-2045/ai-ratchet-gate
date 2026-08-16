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


def write_wheel(path: Path, *, private_classifier: bool = True) -> None:
    metadata = email.message.Message()
    metadata["Name"] = "ai-ratchet-gate"
    metadata["Version"] = "0.1.0"
    metadata["License-Expression"] = "MIT"
    if private_classifier:
        metadata["Classifier"] = CHECK.PRIVATE_CLASSIFIER

    with zipfile.ZipFile(path, "w") as archive:
        for name in CHECK.REQUIRED_WHEEL_SUFFIXES:
            archive.writestr(name, "")
        archive.writestr(
            "ai_ratchet_gate-0.1.0.dist-info/METADATA", metadata.as_bytes()
        )


def write_sdist(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for suffix in CHECK.REQUIRED_SDIST_SUFFIXES:
            data = b"test"
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
