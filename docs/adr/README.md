# Architecture Decision Records

このディレクトリは、AI Ratchet Gateの公開された設計判断の正本です。ADRの識別子は
`nexus-ai-2045/ai-ratchet-gate + ADR番号`で一意に扱います。

| ADR | 状態 | 概要 |
|---|---|---|
| [ADR-0001](ADR-0001-generic-ratchet-engine.md) | accepted | 汎用ラチェットengineとadapter境界 |
| [ADR-0002](ADR-0002-review-knowledge-propagation.md) | proposed | PRレビュー知見の昇格と横断伝播 |
| [ADR-0003](ADR-0003-solution-knowledge-propagation.md) | proposed | 解決知識の中央/ローカル伝播 |
| [ADR-0004](ADR-0004-skill-provenance-adapter.md) | accepted | skills provenance / permission expansion adapter |
| [ADR-0005](ADR-0005-test-disable-adapter.md) | accepted | テスト無効化（skip / only / hollow）adapter |
| [ADR-0006](ADR-0006-fact-output-enforcement.md) | proposed | structured fact-output enforcement（read-only CLI。runtime は not_enforced） |
| [ADR-0007](ADR-0007-solution-harness-loop.md) | proposed | 解決知識の適用・再検証Harness境界 |
