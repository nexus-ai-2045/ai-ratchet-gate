#!/usr/bin/env python3
"""生成済みwheel／sdistを隔離venvへ実際にインストールして確認する。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def select_one(dist_dir: Path, pattern: str) -> Path:
    matches = sorted(dist_dir.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"{pattern} は1件必要です: {len(matches)}件")
    return matches[0].resolve()


def smoke_install(artifact: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ai-ratchet-gate-install-") as temp:
        environment = Path(temp)
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONHOME", None)
        clean_env.pop("PYTHONPATH", None)
        subprocess.run(
            [str(python), "-I", "-m", "pip", "install", "--no-deps", str(artifact)],
            check=True,
            cwd=environment,
            env=clean_env,
        )
        subprocess.run(
            [str(python), "-I", "-m", "ai_ratchet_gate", "--help"],
            check=True,
            cwd=environment,
            env=clean_env,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)

    try:
        wheel = select_one(args.dist_dir, "*.whl")
        sdist = select_one(args.dist_dir, "*.tar.gz")
        for artifact in (wheel, sdist):
            smoke_install(artifact)
            print(f"OK install: {artifact.name}")
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"ERROR [smoke-install]: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
