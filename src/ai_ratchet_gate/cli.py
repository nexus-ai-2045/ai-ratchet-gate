#!/usr/bin/env python3
"""ai-ratchet-gate: git の「tracked なのに ignored」矛盾の増分を止める ratchet ゲート。

AI エージェントが並走する repo では、「先に commit されたファイルへ後から ignore
ルールが足される」事故が繰り返し起きる。gitignore は追跡済みファイルに効かないため、
この矛盾は放置すると生成物が書き換わるたび dirty 化し、push や自動化を静かに阻害する。

この矛盾は git 組み込みの `git ls-files -i -c --exclude-standard` で機械列挙できる。
本ゲートは ratchet (爪付きで逆回転しない歯車機構) 方式を取る:

- 既存の矛盾は baseline に記名して grandfather する (今日から全部直せとは言わない)
- baseline に無い新規の矛盾だけを deny する (増える方向にはロックが掛かる)
- baseline の増減は `--update-baseline` 経由でファイル diff になり、レビューで見える

矛盾が新しく生まれる経路は 2 つで、両方止まる:
  1. `git add -f` で ignored ファイルを強制追加した
  2. 既に tracked のファイルへ後から ignore ルールを追記した

修復は「生成物なら `git rm --cached`、実装なら `!` で allowlist へ」。
列挙に失敗した場合は成功を報告しない (fail-closed)。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .engine import evaluate
from .model import Finding, Observation, RatchetError
from .receipt import build_receipt

SKIP_ENV = "AI_RATCHET_GATE_SKIP"
DEFAULT_BASELINE = ".ai-ratchet-gate/baseline.txt"
MAX_JSON_BYTES = 2 * 1024 * 1024

BASELINE_HEADER = """\
# ai-ratchet-gate の baseline (ratchet)。
# ここに列挙されたファイルは「tracked なのに gitignore にマッチする」既存の矛盾で、
# 導入時点の現存分を grandfather したもの。新規の矛盾は commit 時に deny される。
# 棚卸しで解消したらこのリストからも消すこと (縮む方向の更新も --update-baseline)。
"""


def list_tracked_ignored(repo: Path) -> set[str]:
    """tracked かつ ignore ルールにマッチするファイルを列挙する。

    -z 区切りで取り、非 ASCII パスの quote (octal escape) を回避する。
    """
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-i", "-c", "--exclude-standard", "-z"],
        capture_output=True,
        check=True,
    )
    raw = completed.stdout.decode("utf-8", errors="replace")
    return {entry for entry in raw.split("\0") if entry}


def parse_baseline(path: Path) -> set[str]:
    entries: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line)
    return entries


def format_baseline(entries: set[str]) -> str:
    body = "\n".join(sorted(entries))
    return BASELINE_HEADER + body + ("\n" if body else "")


def diff_against_baseline(
    current: set[str], baseline: set[str]
) -> tuple[list[str], list[str]]:
    """(新規の矛盾, 解消済みで baseline から消せるもの) を返す。"""
    return sorted(current - baseline), sorted(baseline - current)


def _exact_keys(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _read_json(path: Path) -> object:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise RatchetError("json_input_too_large")
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RatchetError("invalid_json_input") from error


def _evaluate_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="汎用findingをbaselineと比較する")
    parser.add_argument("--observation", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--expected-subject",
        required=True,
        help="enforcement側が固定した候補identity。observationとの一致を必須化する",
    )
    parser.add_argument("--mode", choices=["observe", "ratchet", "strict"])
    args = parser.parse_args(argv)
    try:
        raw_observation = _read_json(args.observation)
        raw_baseline = _read_json(args.baseline)
        if not _exact_keys(
            raw_observation,
            {"schema", "adapter_id", "adapter_version", "subject", "findings"},
        ) or raw_observation["schema"] != "ai-ratchet-gate.observation/v1":
            raise RatchetError("invalid_observation_schema")
        if not isinstance(raw_observation["findings"], list):
            raise RatchetError("invalid_observation")
        observation = Observation.create(
            raw_observation["adapter_id"],
            raw_observation["adapter_version"],
            raw_observation["subject"],
            [Finding.from_dict(item) for item in raw_observation["findings"]],
        )
        if observation.subject != args.expected_subject:
            raise RatchetError("subject_identity_mismatch")
        if not _exact_keys(
            raw_baseline,
            {"schema", "adapter_id", "adapter_version", "policy", "finding_ids"},
        ) or raw_baseline["schema"] != "ai-ratchet-gate.baseline/v1":
            raise RatchetError("invalid_baseline_schema")
        if (
            raw_baseline["adapter_id"] != observation.adapter_id
            or raw_baseline["adapter_version"] != observation.adapter_version
            or not isinstance(raw_baseline["finding_ids"], list)
        ):
            raise RatchetError("baseline_identity_mismatch")
        decision = evaluate(
            observation,
            raw_baseline["finding_ids"],
            mode=args.mode or "ratchet",
            policy=raw_baseline["policy"],
        )
        receipt = build_receipt(decision)
        if args.receipt:
            args.receipt.parent.mkdir(parents=True, exist_ok=True)
            args.receipt.write_text(receipt, encoding="utf-8")
        print(receipt, end="")
        return 0 if decision.status == "allow" else 1
    except (RatchetError, OSError) as error:
        print(json.dumps({"status": "tool_error", "error": str(error)}))
        return 2


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(argv) if argv is not None else sys.argv[1:]
    if effective_argv[:1] == ["evaluate"]:
        return _evaluate_main(effective_argv[1:])
    parser = argparse.ArgumentParser(
        description="tracked∧ignored の矛盾の増分を deny する ratchet ゲート"
    )
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=f"baseline ファイル。既定は <repo>/{DEFAULT_BASELINE}",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="baseline を現状へ更新する (grandfather の意図的な増減。diff はレビュー対象)",
    )
    args = parser.parse_args(effective_argv)
    baseline_path = args.baseline or (args.repo / DEFAULT_BASELINE)

    if os.environ.get(SKIP_ENV) == "1":
        print(f"==> ai-ratchet-gate SKIP ({SKIP_ENV}=1)")
        return 0

    try:
        current = list_tracked_ignored(args.repo)
    except (subprocess.CalledProcessError, OSError) as error:
        # 列挙できないのに OK を返さない (fail-closed)
        print(f"ERROR [ai_ratchet_gate]: git 列挙に失敗しました: {error}")
        return 1

    if args.update_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(format_baseline(current), encoding="utf-8")
        print(
            f"==> ai-ratchet-gate baseline を更新しました ({len(current)} 件) -> "
            f"{baseline_path}"
        )
        return 0

    if not baseline_path.is_file():
        print(
            f"ERROR [ai_ratchet_gate]: baseline がありません: {baseline_path}\n"
            f"  初期化: python ai_ratchet_gate.py --update-baseline"
        )
        return 1

    new, resolved = diff_against_baseline(current, parse_baseline(baseline_path))

    if resolved:
        print(
            f"==> ai-ratchet-gate: baseline のうち {len(resolved)} 件は解消済み "
            f"(棚卸しの成果。--update-baseline で縮められます)"
        )
    if not new:
        print(f"==> ai-ratchet-gate OK (現存 {len(current)} 件 / 新規 0)")
        return 0

    print("ERROR [ai_ratchet_gate]: tracked なのに gitignore にマッチするファイルが増えました:")
    for entry in new:
        print(f"  {entry}")
    print(
        "  gitignore は追跡済みファイルに効かず、この状態は放置すると実行のたび dirty 化\n"
        "  して push や自動化を阻害します。修復:\n"
        "    生成物なら:   git rm --cached <file>   (ignore が効き始める)\n"
        "    実装なら:     .gitignore に `!<path>` を足して allowlist へ\n"
        "    意図的なら:   python ai_ratchet_gate.py --update-baseline\n"
        f"  緊急回避: {SKIP_ENV}=1 git commit ..."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
