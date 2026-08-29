---
title: 汎用ラチェットengineとadapter境界
type: adr
status: accepted
created: 2026-08-19
updated: 2026-08-29
owner: nexus-ai-2045
related:
  - ../../ROADMAP.md
  - ../architecture.md
  - ../threat-model.md
---

# ADR-0001 汎用ラチェットengineとadapter境界

## Context

v0.1はGitの`tracked ∧ ignored`矛盾だけを検査する。将来はmemory、skills、tool権限、
agent設定、evalなどにも「既存負債は直ちに全修復させず、新しい悪化だけを止める」契約を
適用したい。一方、対象ごとの観測、共通判定、GitHub上の外部状態、公開承認を一つの
パッケージへ集約すると、権限と責務が肥大化する。

## Decision

- このrepositoryは、決定論的なcore engine、versioned schema、built-in adapter、baseline、
  期限付きwaiver、機械可読receiptを所有する。
- adapterはread-only観測とfindingの正規化だけを行い、coreがbaseline比較とdecisionを行う。
- MVPはbuilt-in adapterだけを許可する。任意Python importやsubprocess pluginは導入しない。
- 複数軸を単一スコアに集約しない。adapterごとに独立判定し、一軸の改善で別軸の悪化を
  相殺できないようにする。
- 既存CLI、`baseline.txt`、exit codeはcharacterization testで後方互換を固定し、新しい契約は
  opt-in subcommandとして段階導入する。
- receiptは観測と判定の証拠であり、承認書ではない。
- policy decisionとenforcement pointを分離する。hookやCIがengineのdecisionを強制する。
- 人間の反例をrule、fixture、adapterへ変換する循環を`CEGIS-inspired`、候補状態を境界で
  拒否する考えを`shielding-inspired`、各段階で再観測する方式を`MPC-inspired`または
  `receding-horizon`と呼ぶ。形式合成、runtime自動補正、予測制御の保証は主張しない。

## Allowed

- 通常のscan、decision、receipt生成
- baseline縮小patchと修復案の提案
- pre-commit、CI、ローカルrunnerから同じCLI契約を利用すること
- 再現性が定義された決定論的adapterを、個別レビュー後に追加すること

## Prohibited

- LLMの主観評価だけをdeny判定へ使用すること
- finding件数のnet-zero swapや総合点で新規悪化を隠すこと
- baseline拡大、waiver承認、公開操作をcoreが自動承認すること
- 外部送信、tag、Release、repository visibilityをこのパッケージが変更すること
- sandbox保証なしに第三者adapterを実行すること

## Human Review Gate

次は人間レビューを必須とする。

- baselineの拡大
- waiverの追加、延長、scope変更
- adapterまたはruleの`ratchet` / `strict`昇格
- schema migrationで判定意味が変わる変更
- merge、release、公開、外部送信

scan、receipt、baseline縮小候補、修復候補の生成までは自動化できる。自動化が作ったreceiptは
上記承認の代替にならない。

## Consequences

### 肯定的

- 現在の狭く検証済みなGitゲートを壊さず、同じ比較契約を別領域へ拡張できる。
- agent runtimeと独立しているため、モデルや製品が変わっても既知の悪化を検出できる。
- 責務と権限を分離し、公開操作を含まない小さな信頼境界を維持できる。

### 否定的

- adapterごとに安定ID、誤検知、証拠漏洩、再現性を個別設計する必要がある。
- built-in限定のMVPでは、第三者拡張性より安全性を優先する。
- hook単体は迂回可能であり、強制にはCIやbranch protectionなど外側の運用が必要である。

### 検討した代替案

- **OPA/Regoを直接採用**: 強力だが、v0.1の小さなPython配布物へ新runtimeを持ち込む。
- **全責務をrepo-preflightへ統合**: GitHub外部状態と対象内部の不変条件が密結合になる。
- **新repositoryへ分離**: 契約が未成熟な段階では配布、互換、利用者導線を不要に増やす。
- **総合fitness score**: 次元を圧縮できるが、別軸の改善で安全上の悪化を相殺し得る。

## Next Actions

1. characterization testで既存CLI契約を固定する。
2. Finding、Observation、Decision、Receiptのversioned schemaを導入する。
3. `tracked ∧ ignored`を参照adapterへ移す。
4. ~~waiver検証と脅威モデルの回帰テストを追加する。~~（実装済み: `ai-ratchet-gate.waivers/v1`、
   `evaluate --waiver`、期限・scope・review bindingのfail-closed、安価なゲームの回帰テスト）
5. ~~第二adapterは決定論的なskill provenance / permission expansionを第一候補として個別設計する。~~
   （実装済み: ADR-0004、`skills.provenance`、`observe --adapter skills.provenance`、
   `new_skill` / `allowed_tools_token` / `unrestricted_tools` / `executable_asset`、
   scripts digestはdeny軸・SKILL.md本文はevidence、回帰テスト）
6. ~~第三adapterはテスト無効化（skip / only / hollow）を個別設計する。~~
   （実装済み: ADR-0005、`test.disable`、`observe --adapter test.disable`、
   `unconditional_skip` / `focused_only` / `hollow_test`。C2は既存`strict`。
   C4・逆さまテストはスコープ外）
7. ~~脅威モデル回帰の明示対応、observe→evaluate運用接続、人間停止線の運用正本化。~~
   （実装済み: `docs/threat-model.md`の回帰表、`scripts/enforce_observe_evaluate.py`、
   CI Enforceステップ、`.pre-commit-hooks.yaml`、`OPERATIONS.md`を運用向け正本に拡充。
   公開CLIは増やさない。branch protection必須化・v1.0宣言は人間停止線）
