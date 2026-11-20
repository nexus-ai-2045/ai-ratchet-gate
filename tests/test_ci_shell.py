"""CI の複数行 run が、途中のコマンドの失敗で止まることのテスト。

Windows の runner は既定のシェルが pwsh で、複数行の run は最後のコマンドの終了コードしか
step の結果にしない。2026-11-21 の検証用 PR（#13）では、Windows の job で
git.tracked_ignored が deny（exit 1）を返したのに、後ろの adapter が allow で終わったため
step が成功になった。ラチェットが Windows だけ素通りしないよう、bash（-e 付き）で走らせる。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_test_job_runs_every_step_with_bash() -> None:
    text = CI.read_text(encoding="utf-8")

    # job 全体の既定を bash にする（GitHub の bash は -e で途中の失敗で止まる）
    assert re.search(r"^    defaults:\n      run:\n        shell: bash\n", text, re.M)
    # step ごとに pwsh / cmd へ戻していない
    assert not re.search(r"shell:\s*(pwsh|powershell|cmd)", text)


def test_multi_command_enforce_steps_exist_under_bash() -> None:
    """守る対象（複数行で adapter を続けて呼ぶ step）が今もあることを確かめる。"""
    text = CI.read_text(encoding="utf-8")

    blocks = re.findall(r"run: \|\n((?:          .*\n)+)", text)
    multi = [b for b in blocks if b.count("enforce_observe_evaluate.py") >= 2]
    assert multi, "adapter を続けて呼ぶ step が見つからない"
