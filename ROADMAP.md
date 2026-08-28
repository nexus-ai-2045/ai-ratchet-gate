# AI Ratchet Gate ロードマップ

## ビジョン

AI Ratchet Gateは、AIエージェントが変更するリポジトリ、memory、skills、権限、評価結果などに
対して、「既存負債を導入時に全修復させないが、新しい悪化は増やさない」という増分安全性を
適用する、エージェント非依存のゲートを目指します。

共通の処理モデルは次のとおりです。

1. 対象の現在状態をread-onlyで観測する
2. 違反を比較可能な安定IDへ正規化する
3. レビュー済みbaselineと比較する
4. baselineにない新規悪化だけを拒否する
5. 改善は自由に通し、例外追加はレビュー可能なdiffとして残す
6. 観測不能時は成功を返さない

## 現在地: v0.1

実装済みは、Gitの`tracked ∧ ignored`矛盾を対象にした最初のアダプターと、
Agent Skillsの`SKILL.md` / `scripts/`を対象にした第二アダプター`skill.provenance`です。
Memory管理、skill生成、エージェント実行、品質全般の評価はまだ提供していません。
v1.0には3種類以上の独立アダプターが必要なため、本時点ではv1.0完了を主張しません。

## Phase 1: 共通ラチェット契約

- findingの安定ID、説明、修復案、証拠を表す共通schemaを定義する
- 観測、正規化、baseline比較、判定を分離する
- baseline形式をversion管理し、未知の形式はfail-closedにする
- アダプターごとの結果を機械可読なreceiptとして出力する
- 現在のGit検査を共通契約上の参照アダプターへ移行する
- legacy CLIと`baseline.txt`をcharacterization testで固定し、新契約をopt-in導入する
- baselineと期限付きwaiverを分離する
- 複数adapterを総合点へ潰さず、軸ごとにallow / deny / indeterminateを返す
- 期限付きwaiver（`ai-ratchet-gate.waivers/v1`）の検証と、脅威モデル上の安価なゲームに対する回帰テスト

完了条件は、既存CLIとの互換性を保ち、同じ入力から同じ判定を再現できることです。

実装順は[ADR-0001](docs/adr/ADR-0001-generic-ratchet-engine.md)に従う。schema・純関数、Git検査の
adapter化、receipt、waiver検証（Next Action 1–4）に加え、第二adapter
`skill.provenance`（Next Action 5 / [ADR-0004](docs/adr/ADR-0004-skill-provenance-adapter.md)）
も実装済み。v1.0完了にはさらに独立adapterが必要。

## Phase 2: AI運用向け参照アダプター

候補を一度にenforceせず、検出精度と安定IDを検証してから個別に導入します。

- memory: secret・個人情報・未承認ファイル参照など、決定論的に検査できる項目
- skills: 出所、digest、許可されたtool／権限宣言の新規拡大（実装済み: `skill.provenance`。
  Agent Skillsの`SKILL.md` + sibling `scripts/` をread-only観測し、新規skill・
  `allowed-tools`拡大・scripts digest変更を独立軸でdenyする）
- agent設定: model、tool、外部送信先、書込権限の新規追加
- eval: 固定fixtureに対する既知成功ケースの退行
- repository: secret候補、生成物混入、個人pathなどの増分違反

各アダプターは、対象形式、信頼境界、誤検知時の扱い、baseline更新手順を明示します。
非決定的な評価値は、再現性と許容幅を定義できるまでdeny判定へ使いません。
第二adapter（skill provenance）は実装済み。secretやPIIを含み得るmemory検査は、
証拠漏洩と誤検知の設計後に扱います。

## Phase 3: エージェント横断の接続

- pre-commit、CI、ローカルrunnerから同じ判定を利用できるようにする
- Codex、Hermes Agentなど特定製品に依存しないファイル／CLI契約を維持する
- 外部ツールが生成したmemoryやskillsも、明示された対象だけread-onlyで検査する
- 複数アダプターのreceiptを統合し、どの不変条件が停止理由か追跡可能にする
- commit、PR、merge、release等の境界で再観測するreceding-horizon型PDCAを運用する

自動化はscan、decision、receipt、修復案、baseline縮小候補までとします。baseline拡大、waiver承認、
enforce昇格、merge、release、公開、外部送信は人間停止線です。

## v1.0の判断基準

- 3種類以上の独立アダプターが共通契約で動作する
- baselineの追加・縮小・schema migrationがレビュー可能である
- 誤検知、観測失敗、入力改ざんを含む脅威モデルと回帰テストがある
- 特定のLLM、エージェント、ホストサービスなしで検査を再現できる
- hookを迂回できる範囲と、CIなど運用側が担う強制境界を文書化している

## 非目標

- Memoryやskillを自動生成・改善すること
- Hermes Agentなどのエージェントruntimeを置き換えること
- LLMの主観評価だけでcommitを拒否すること
- baseline更新を人間レビューなしで自動承認すること
- 公開、外部送信、tag、Release、人間承認をこのパッケージが代行すること

