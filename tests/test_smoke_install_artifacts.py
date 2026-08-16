from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_install_artifacts.py"
SPEC = importlib.util.spec_from_file_location("smoke_install_artifacts", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def test_smoke_install_isolated_from_checkout(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "package.whl"
    artifact.touch()
    calls: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setenv("PYTHONPATH", "src")
    monkeypatch.setenv("PYTHONHOME", "fake-home")
    monkeypatch.setenv("PIP_TARGET", str(tmp_path / "outside"))
    monkeypatch.setattr(SMOKE.venv.EnvBuilder, "create", lambda self, path: None)
    monkeypatch.setattr(
        SMOKE.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs)) or SimpleNamespace(stdout="tracked∧ignored")
        ),
    )

    SMOKE.smoke_install(artifact)

    assert len(calls) == 3
    for command, kwargs in calls:
        assert kwargs["cwd"] != ROOT
        assert "PYTHONPATH" not in kwargs["env"]
        assert "PYTHONHOME" not in kwargs["env"]
        assert not any(name.startswith("PIP_") for name in kwargs["env"])
    assert "-I" in calls[0][0]
    assert "--isolated" in calls[0][0]
    assert "-I" in calls[1][0]
    assert calls[2][0][-1] == "--help"
