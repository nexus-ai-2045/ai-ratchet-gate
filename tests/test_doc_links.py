"""文書のリンク先が別物を指さないことのテスト。

このリポジトリは再構築先なので、移行前リポの Issue 番号をそのまま
`nexus-ai-2045/ai-ratchet-gate/issues/<番号>` へリンクすると、新しいリポの
別の PR（例: #11）へ飛ぶ。移行前の Issue は番号だけを書き、リンクしない。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "ROADMAP.md", "CHANGELOG.md", "docs/adr/ADR-0005-test-disable-adapter.md")
# 移行前リポで振られた番号。新しいリポでは別の PR に使われている
PRE_MIGRATION_ISSUES = (11,)


def test_pre_migration_issue_numbers_are_not_linked_to_this_repo() -> None:
    for name in DOCS:
        text = (ROOT / name).read_text(encoding="utf-8")
        for number in PRE_MIGRATION_ISSUES:
            assert f"nexus-ai-2045/ai-ratchet-gate/issues/{number})" not in text, name
