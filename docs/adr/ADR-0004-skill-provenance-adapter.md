---
title: skill provenance / permission expansion adapter
type: adr
status: accepted
created: 2026-08-28
updated: 2026-08-28
owner: nexus-ai-2045
related:
  - ../../ROADMAP.md
  - ../architecture.md
  - ../threat-model.md
  - ../prior-art.md
  - ADR-0001-generic-ratchet-engine.md
---

# ADR-0004 skill provenance と permission expansion adapter

## Context

ADR-0001 Next Action 5は、第二built-in adapterの第一候補として決定論的な
skill provenance / permission expansionを挙げる。Phase 2のskills候補
（出所、digest、許可されたtool／権限宣言の新規拡大）を、既存の
observe → 安定Finding ID → baseline比較 → new-only deny 契約の上へ載せる。

v1の入力はAgent Skillsの`SKILL.md`（YAML frontmatter）と、そのsiblingである
`scripts/`配下の通常ファイルだけとする。製品固有APIや、複数skill形式の動物園は
導入しない。OPA/Rego、SLSA/in-toto runtime、LLM判定は持ち込まない。digestと
capability expansionは語彙として使い、artifactの内容固定と宣言権限の単調拡大検知に
留める。

## Decision

- built-in adapter IDは`skill.provenance`とする。
- 観測対象は明示されたskills root（既定: 対象repo相対の`skills/`）配下の各skill
  directory。各skillは`SKILL.md`を必須とし、任意で`scripts/`を持つ。
- skills rootが存在しない、列挙できない、repo外へ脱出する、symlinkを辿ると曖昧になる、
  frontmatterが解釈不能な場合はfail-closed（`RatchetError` / CLI exit 2）。
- Findingは次の独立軸だけを出す。総合点やnet-zero scoreは作らない。

| rule_id | 意味 | subject_key |
|---|---|---|
| `skill_present` | 観測されたskill（新規SKILL.md） | skill directoryのrepo相対path |
| `skill_allowed_tool` | 宣言された個別tool／権限 | `{skill_path}::{tool_token}` |
| `skill_scripts_digest` | companion `scripts/` treeの内容digest | `{skill_path}@{scripts_digest}` |

- `subject_kind`は常に`skill`。
- 安定キーは**declared `name`ではなくrepo相対path**とする。renameは新しいidentityになり、
  別名へ静かに合流しない（rename耐性より同一性の誤結合を避ける）。
- `allowed-tools`はfrontmatterの空間／カンマ区切り文字列、または単純なYAML listだけを
  受理する。tokenはNFC正規化し、集合として扱う（順序はfinding IDに影響しない）。
- `scripts/`が無い、または空の場合も空treeのdigestを出し、後からscriptが追加された拡大を
  検知できるようにする。
- `observe --adapter skill.provenance`でopt-inする。既定の`git.tracked_ignored`とlegacy
  CLIは変更しない。`evaluate` / baseline / waiver / receiptは既存coreを再利用する。

## Allowed

- read-only観測とFinding正規化
- grandfather済みskill／tool／scripts digestのbaseline比較
- 期限付きwaiverのopt-in消費（承認はしない）

## Prohibited

- skillの生成・改善・実行
- 第三者plugin adapterの実行
- LLMをdeny判定の主根拠にすること
- 軸を単一スコアへ潰すこと
- baseline拡大やwaiver承認の自動化
- GitHub mutation、merge、release、公開、秘密のreceipt埋め込み

## Human Review Gate

baseline拡大、waiver追加・延長・scope変更、本adapterの`ratchet` / `strict`昇格、
schemaの判定意味変更、merge / release / 公開は人間レビュー必須。

## Consequences

### 肯定的

- 第二の独立adapterを、既存git adapterと同じcore契約で検証できる。
- 新規skill、権限拡大、scripts改変を別findingとして止め、一軸の改善で他軸を相殺できない。
- Agent Skillsの具体入力に閉じるため、再現可能なfixtureと脅威モデル回帰が書ける。

### 否定的

- path基準のため、skill directoryのrenameは新規悪化として見える。
- `SKILL.md`本文だけを変え、tool宣言も`scripts/`も変えない改変は本v1の対象外。
- YAMLの完全実装は持たない。曖昧なfrontmatterはfail-closedする。

### 検討した代替案

- **declared name + digestを主キーにする**: 同名skillのpath差替えを静かに同一視し得る。
- **SKILL.md全体digestだけを見る**: permission expansionと新規skillを区別できない。
- **OPAで権限policyを書く**: 新runtimeを持ち込み、ADR-0001の小さなPython配布物方針に反する。

## Next Actions

1. `SkillProvenanceAdapter`とCLI opt-inを実装する。
2. grandfather / 新規skill / tool拡大 / scripts改変 / 観測失敗 / 軸非相殺のテストを追加する。
3. 脅威モデルの安価なゲーム（label入替、path spoof、baselineとwaiverの混同）を回帰する。
