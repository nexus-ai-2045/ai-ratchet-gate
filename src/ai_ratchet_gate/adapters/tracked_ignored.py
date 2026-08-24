"""Gitのtrackedかつignored矛盾をFindingへ正規化するadapter。"""

from __future__ import annotations

import hashlib
import os
import subprocess

from ..model import Finding, Observation, RatchetError
from .protocol import ScanContext

# FIFO ignore 等で git がブロックしても CI worker を無限待ちさせない
GIT_LS_FILES_TIMEOUT_SECONDS = 30


class TrackedIgnoredAdapter:
    adapter_id = "git.tracked_ignored"
    adapter_version = "1"

    def __init__(self, *, ignore_profile: str = "repo_only") -> None:
        if ignore_profile not in {"repo_only", "exclude_standard"}:
            raise ValueError("unsupported_ignore_profile")
        self.ignore_profile = ignore_profile

    def list_paths(self, context: ScanContext) -> tuple[str, ...]:
        """Gitが返したpathをUnicode正規化せず列挙する。"""
        try:
            if self.ignore_profile == "exclude_standard":
                # legacy CLI互換: Git環境・global/system configも従来どおり継承する。
                command = [
                    "git", "-C", str(context.root), "ls-files", "-i", "-c",
                    "--exclude-standard", "-z",
                ]
                git_env = None
            else:
                # 汎用profileは外部設定を隔離し、レビュー対象の.gitignoreだけを使う。
                git_env = {
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith("GIT_")
                }
                git_env["GIT_CONFIG_GLOBAL"] = os.devnull
                git_env["GIT_CONFIG_SYSTEM"] = os.devnull
                command = [
                    "git", "-C", str(context.root),
                    "-c", "core.fsmonitor=false",
                    "-c", f"core.excludesFile={os.devnull}",
                    "ls-files", "-i", "-c",
                    "--exclude-per-directory=.gitignore", "-z",
                ]
            completed = subprocess.run(
                command,
                capture_output=True,
                check=True,
                env=git_env,
                timeout=GIT_LS_FILES_TIMEOUT_SECONDS,
            )
            raw = completed.stdout.decode("utf-8", errors="strict")
        except subprocess.TimeoutExpired as error:
            raise RatchetError("adapter_observation_timeout") from error
        except (subprocess.CalledProcessError, OSError, UnicodeDecodeError) as error:
            raise RatchetError("adapter_observation_failed") from error
        return tuple(sorted(item for item in raw.split("\0") if item))

    def observe(self, context: ScanContext) -> Observation:
        paths = self.list_paths(context)
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
