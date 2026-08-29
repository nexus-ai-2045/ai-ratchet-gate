#!/usr/bin/env python3
"""同じ observe→evaluate 判定を local / CI / pre-commit から呼ぶ運用接続。

既存の公開 CLI（`observe` / `evaluate`）だけを消費する。新subcommandは追加しない。
レビュー済み baseline seed（finding_ids）へ、enforcement 側が固定した subject を
実行時に束縛してから判定する。baseline 拡大・waiver 承認・merge は行わない。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from ai_ratchet_gate.cli import _read_json
from ai_ratchet_gate.model import RatchetError


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_BASELINE_KEYS = {
    "schema",
    "adapter_id",
    "adapter_version",
    "subject",
    "policy",
    "finding_ids",
}


def _sanitized_git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _resolve_subject(repo: Path, subject: str | None) -> str:
    if subject:
        return subject
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        env=_sanitized_git_env(),
    )
    if completed.returncode != 0:
        print(
            "ERROR [enforce]: HEAD SHA を解決できません "
            f"(exit {completed.returncode})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    sha = completed.stdout.strip()
    if not sha:
        print("ERROR [enforce]: HEAD SHA が空です", file=sys.stderr)
        raise SystemExit(2)
    return f"repo:nexus-ai-2045/ai-ratchet-gate@{sha}"


def _load_baseline_seed(path: Path) -> dict[str, object]:
    """evaluate と同じ duplicate-key 拒否（cli._read_json）で seed を読む。"""
    try:
        raw = _read_json(path)
    except RatchetError as error:
        print(f"ERROR [enforce]: baseline seed を読めません: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except OSError as error:
        print(f"ERROR [enforce]: baseline seed を読めません: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    if not isinstance(raw, dict) or set(raw) != REQUIRED_BASELINE_KEYS:
        print(
            "ERROR [enforce]: baseline seed のキー集合が不正です "
            f"(expected {sorted(REQUIRED_BASELINE_KEYS)})",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if raw["schema"] != "ai-ratchet-gate.baseline/v1":
        print("ERROR [enforce]: 未知の baseline schema です", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(raw["finding_ids"], list):
        print("ERROR [enforce]: finding_ids は配列である必要があります", file=sys.stderr)
        raise SystemExit(2)
    return raw


def _run_cli(args: list[str]) -> int:
    completed = subprocess.run(
        [sys.executable, "-m", "ai_ratchet_gate", *args],
        check=False,
    )
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="observe→evaluate を同一 subject で実行する運用接続"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=ROOT,
        help="検査対象repo（既定: このrepositoryのroot）",
    )
    parser.add_argument(
        "--adapter",
        choices=["git.tracked_ignored", "skills.provenance", "test.disable"],
        default="git.tracked_ignored",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="レビュー済み baseline seed（finding_ids）。subject は実行時に上書きする",
    )
    parser.add_argument(
        "--waiver",
        type=Path,
        default=None,
        help="レビュー済み waiver JSON（opt-in）。evaluate へフォワードするだけ。"
        "追加・延長・承認はしない",
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="省略時は repo:nexus-ai-2045/ai-ratchet-gate@<HEAD>",
    )
    parser.add_argument(
        "--mode",
        choices=["ratchet", "strict"],
        default="ratchet",
        help="enforcement 用。observe mode は受け付けない",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="receipt 出力先。省略時は一時directoryへ書く",
    )
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    subject = _resolve_subject(repo, args.subject)
    seed = _load_baseline_seed(args.baseline.resolve())
    if seed["adapter_id"] != args.adapter:
        print(
            "ERROR [enforce]: --adapter と baseline seed の adapter_id が不一致です",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory(prefix="ai-ratchet-gate-enforce-") as raw_tmpdir:
        tmpdir = Path(raw_tmpdir)
        observation = tmpdir / "observation.json"
        baseline = tmpdir / "baseline.json"
        receipt = args.receipt if args.receipt is not None else tmpdir / "receipt.json"
        if args.receipt is not None:
            try:
                receipt.parent.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                print(
                    f"ERROR [enforce]: receipt 親directoryを作成できません: {error}",
                    file=sys.stderr,
                )
                return 2

        # 検査対象repo外へ observation を書く（read-only契約）
        observe_code = _run_cli(
            [
                "observe",
                "--repo",
                str(repo),
                "--adapter",
                args.adapter,
                "--subject",
                subject,
                "--out",
                str(observation),
            ]
        )
        if observe_code != 0:
            return observe_code

        bound = dict(seed)
        bound["subject"] = subject
        baseline.write_text(
            json.dumps(bound, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        evaluate_args = [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--expected-subject",
            subject,
            "--receipt",
            str(receipt),
            "--mode",
            args.mode,
        ]
        if args.waiver is not None:
            evaluate_args.extend(["--waiver", str(args.waiver.resolve())])
        return _run_cli(evaluate_args)


if __name__ == "__main__":
    raise SystemExit(main())
