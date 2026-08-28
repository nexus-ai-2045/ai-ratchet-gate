---
title: skills provenance / permission expansion adapter
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

# ADR-0004 skills provenance と permission expansion adapter

## Context

ADR-0001 Next Action 5は、第二built-in adapterの第一候補として決定論的な
skill provenance / permission expansionを挙げる。Phase 2のskills候補を、既存の
observe → 安定Finding ID → baseline比較 → new-only deny 契約の上へ載せる。

v1の入力はAgent Skillsの`SKILL.md`（YAML frontmatter）と、sibling `scripts/`配下の
通常ファイルだけとする。既定の走査先は`.agents/skills/`と`skills/`（存在するrootだけ）。
製品固有API、複数skill形式の動物園、OPA/Rego、SLSA/in-toto runtime、LLM判定は持ち込まない。

## Decision

- built-in adapter IDは`skills.provenance`とする。
- 各skill directoryは`SKILL.md`を必須とし、任意で`scripts/`を持つ。
- どちらのskills rootも無い場合はfinding 0件のobservationとする。存在するrootの列挙不能、
  symlink、repo外脱出、曖昧frontmatterはfail-closed。
- Findingは次の独立軸だけを出す。総合点やnet-zero scoreは作らない。
- **内容digestはevidenceでありdeny軸ではない。** `SKILL.md`本文だけ、または既存
  `scripts/`ファイル内容だけの変更ではfinding IDが変わらず、new-onlyではdenyしない。

| rule_id | 意味 | subject_key |
|---|---|---|
| `new_skill` | 観測されたskill | skill directoryのrepo相対path |
| `allowed_tools_token` | 宣言された個別tool | `{skill_path}::{tool_token}` |
| `unrestricted_tools` | `allowed-tools`欠落または空 | skill directoryのrepo相対path |
| `executable_asset` | companion `scripts/`配下の通常ファイル | `{skill_path}/scripts/{rel}` |

- `subject_kind`は常に`skill`。
- 安定キーは**declared `name`ではなくrepo相対path**とする。renameは新しいidentityになる。
- `allowed-tools`は空間／カンマ区切り文字列、または単純YAML listを受理する。
- `observe --adapter skills.provenance`でopt-inする。既定の`git.tracked_ignored`とlegacy
  CLIは変更しない。`evaluate` / baseline / waiver / receiptは既存coreを再利用する。

## Allowed

- read-only観測とFinding正規化
- grandfather済みfindingのbaseline比較
- 期限付きwaiverのopt-in消費（承認はしない）

## Prohibited

- skillの生成・改善・実行
- 第三者plugin adapterの実行
- LLMをdeny判定の主根拠にすること
- digest不一致そのものをdeny軸にすること
- 軸を単一スコアへ潰すこと
- baseline拡大やwaiver承認の自動化
- GitHub mutation、merge、release、公開、秘密のreceipt埋め込み

## Human Review Gate

baseline拡大、waiver追加・延長・scope変更、本adapterの`ratchet` / `strict`昇格、
schemaの判定意味変更、merge / release / 公開は人間レビュー必須。

## Consequences

### 肯定的

- 第二の独立adapterを、既存git adapterと同じcore契約で検証できる。
- 新規skill、権限拡大、無制限tools、executable asset追加を別findingとして止める。
- 本文のみの編集やscript内容改変で誤denyしない。

### 否定的

- path基準のため、skill directoryのrenameは新規悪化として見える。
- `scripts/`への新規ファイル追加はdenyするが、既存ファイルの内容改変は検知しない
  （evidence digestは変わるがfinding IDは不変）。

### 検討した代替案

- **scripts tree digestをdeny軸にする**: 内容改変を止められるが、本文／script編集の
  運用ノイズが大きく、本v1の「digestはevidence」方針に反する。
- **declared nameを主キーにする**: 同名skillのpath差替えを静かに同一視し得る。
- **OPAで権限policyを書く**: 新runtimeを持ち込み、ADR-0001に反する。

## Next Actions

1. ~~`SkillProvenanceAdapter`とCLI opt-inを実装する。~~（実装済み）
2. ~~grandfather / 新規skill / tool拡大 / unrestricted / executable追加 / 本文のみ非deny /
   観測失敗 / 軸非相殺のテストを追加する。~~（実装済み）
3. ~~脅威モデルの安価なゲーム（label入替、path spoof、baselineとwaiverの混同）を回帰する。~~
   （実装済み）
