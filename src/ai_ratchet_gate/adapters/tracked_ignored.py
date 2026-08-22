"""Gitのtrackedかつignored矛盾をFindingへ正規化するadapter。"""

from __future__ import annotations

import hashlib
import os
import subprocess

from ..model import Finding, Observation, RatchetError
from .protocol import ScanContext


class TrackedIgnoredAdapter:
    adapter_id = "git.tracked_ignored"
    adapter_version = "1"

    def observe(self, context: ScanContext) -> Observation:
        git_env = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        git_env["GIT_CONFIG_GLOBAL"] = os.devnull
        git_env["GIT_CONFIG_SYSTEM"] = os.devnull
        try:
            # repo-local core.fsmonitor hook を無効化し、外部 excludesFile も固定空に隔離する
            completed = subprocess.run(
                [
                    "git", "-C", str(context.root),
                    "-c", "core.fsmonitor=false",
                    "-c", f"core.excludesFile={os.devnull}",
                    "ls-files", "-i", "-c",
                    "--exclude-standard", "-z",
                ],
                capture_output=True,
                check=True,
                env=git_env,
            )
            raw = completed.stdout.decode("utf-8", errors="strict")
        except (subprocess.CalledProcessError, OSError, UnicodeDecodeError) as error:
            raise RatchetError("adapter_observation_failed") from error
        paths = sorted(item for item in raw.split("\0") if item)
        findings = [
            Finding.create(
                adapter_id=self.adapter_id,
                adapter_version=self.adapter_version,
                rule_id="tracked_ignored",
                subject_kind="repo_path",
                subject_key=path,
                message="tracked file matches an ignore rule",
                evidence_sha256=hashlib.sha256(path.encode("utf-8")).hexdigest(),
            )
            for path in paths
        ]
        return Observation.create(
            self.adapter_id, self.adapter_version, context.subject, findings
        )
