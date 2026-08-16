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
import os
import subprocess
import sys
from pathlib import Path

SKIP_ENV = "AI_RATCHET_GATE_SKIP"
DEFAULT_BASELINE = ".ai-ratchet-gate/baseline.txt"

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


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
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
