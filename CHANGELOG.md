# 変更履歴

このプロジェクトの重要な変更を記録します。

## [Unreleased]

### 追加

- 運用接続: `scripts/enforce_observe_evaluate.py`（既存`observe`→`evaluate`だけを消費。
  公開CLIは増やさない）。`.ai-ratchet-gate/baselines/*.v1.json` seed、
  CIのEnforce observe→evaluateステップ、`.pre-commit-hooks.yaml`（legacy入口）
- sdist allowlistへ運用接続ファイルを追加（Windows CIはバックスラッシュ継続を避けた）
- OPERATIONSを運用向け正本へ拡充（同一判定の三入口、PDCA境界、人間停止線、
  hook迂回範囲とCI強制境界、誤検知手順、baseline追加/縮小/migration）
- 脅威モデルに誤検知・観測失敗・入力改ざんの回帰対応表を追加
- 回帰: finding件数上限、rule軸非相殺、observe modeの誤検知収集、enforceスクリプト
- enforce: baseline seedのduplicate-key拒否（CLI `_read_json`再利用）、任意`--waiver`フォワード、
  receipt親directory失敗をexit 2、unitは一時repoのみ

- 第三built-in adapter `test.disable`（[ADR-0005](docs/adr/ADR-0005-test-disable-adapter.md) /
  [Issue #11](https://github.com/nexus-ai-2045/ai-ratchet-gate/issues/11)）。
  Python + JS/TSのテスト無効化をread-only観測し、
  `unconditional_skip` / `focused_only` / `hollow_test`を独立軸のFindingとして出す。
  `skipif`はC1に含めず、`test.todo`はhollowではない。自由記述reasonは許可条件にせず
  既存`waivers/v1`を消費。C2は既存`strict`（新契約ではない）。C4・逆さまテストはスコープ外。
  `observe --adapter test.disable`でopt-in。既定の`git.tracked_ignored`とlegacy CLIは維持
- 脅威モデル回帰: symlink、非UTF-8、曖昧構文、skipif非検知、todo非hollow、
  waiver例外、他adapter baselineによるidentity偽装拒否
- OPERATIONSへ`test.disable`の導入・日常・ロールバック手順を追記
- ADR indexにADR-0005を掲載

- 第二built-in adapter `skills.provenance`（[ADR-0004](docs/adr/ADR-0004-skill-provenance-adapter.md)）。
  Agent Skillsの`SKILL.md` YAML frontmatterとsibling `scripts/`を、`.agents/skills/`と
  `skills/`（存在するrootだけ）からread-only観測し、
  `new_skill` / `allowed_tools_token` / `unrestricted_tools` / `executable_asset`を
  独立軸のFindingとして出す。`scripts/` payload digestはdeny軸。
  `SKILL.md`本文のみの編集ではdenyしない。
  `observe --adapter skills.provenance`でopt-in。既定の`git.tracked_ignored`とlegacy CLIは維持
- 脅威モデル回帰: label入替、path spoof、symlink、waiverが他軸を相殺しないこと、
  他adapter baselineによるidentity偽装拒否
- 運用経路回帰: 両root欠落、scripts新規/内容変更deny、grandfather digest allow、
  軸非相殺、本文のみ非deny、observe→baseline→evaluate→receipt
- OPERATIONSへ`skills.provenance`の導入・日常・ロールバック手順を追記
- ADR indexにADR-0001〜0004を掲載

- 期限付きwaiver schema（`ai-ratchet-gate.waivers/v1`）と`evaluate --waiver`。baseline（grandfather）と
  分離し、finding ID・observation digest・review binding・有効期限へ束縛する。追加・延長・scope変更の
  自動承認入口は持たない
- 脅威モデル上の安価なゲーム（非決定ID、path/理由の偽装、baseline拡大と解消の混同）に対する回帰テスト

- legacy CLIにratchet可視化バナー。denyは「🔒 RATCHET DENY: 新規悪化 N 件を阻止 (grandfather 済み M 件は通過中)」、
  allowも「🔓 RATCHET OK: 新規 0 / baseline M 件を監視中」で、ratchetが効いている状態を毎回明示する
  (exit code・receiptは不変。機械連携は壊さない)

- agent非依存のFinding、Observation、Decisionによる汎用ラチェットcore
- `new_only` / `exact_baseline` policyと`observe` / `ratchet` / `strict` mode
- 厳格なv1 observation・baseline入力と、入力digestへ束縛した決定論的receipt
- read-only adapter契約と`git.tracked_ignored`組み込みadapter
- 汎用engineの責務、人間停止線、先行概念を固定するADRと脅威モデル

- `observe` subcommand。組み込みadapterで対象を観測し、`evaluate`が受理するobservation JSONを出力
- `Observation.to_dict()`と、`ScanContext` / `TrackedIgnoredAdapter`の公開API export

### 変更

- `observe`は検査対象repo内への`--out`を拒否し (read-only契約)、`--out`指定時はstdoutへ
  findingsを流さず、`evaluate`の入力上限を超えるobservationをfail-closedで拒否する
- adapterはmerge未解決indexの複数stageで重複する同一パスを1 findingへ潰す
- legacy CLIは非UTF-8パスをU+FFFDへ置換せず、fail-closedで停止する
- legacy CLIのexit codeを`evaluate`と揃え、git列挙失敗とbaseline欠落は違反（`1`）と区別して`2`を返す
- receiptのdecisionへ`waived`を追加（waiver未使用時は空配列）

### 互換性

- v0.1の引数なしCLI、テキストbaseline、allow/denyの出力とexit code（`0` / `1`）を維持。
  legacy入口の観測面（`--exclude-standard`互換）も維持
- 観測不能時のexit codeは`1`から`2`へ変更。hookで`!= 0`判定している利用者には影響しない
- 新しい汎用判定は`observe` / `evaluate` subcommandとしてopt-in提供
- waiver契約は`--waiver`指定時のみ有効。未指定時の既存evaluate挙動は維持
- `skills.provenance`は`--adapter skills.provenance`指定時のみ有効。未指定時は`git.tracked_ignored`
- `test.disable`は`--adapter test.disable`指定時のみ有効。未指定時は`git.tracked_ignored`

### 安全性

- legacy CLIのGit観測を組み込み`TrackedIgnoredAdapter`へ委譲しつつ、互換用`exclude_standard` profileで従来の観測面を維持
- baselineとreceiptを同一directoryの一時fileからatomic replaceし、途中書込みを公開しない。既存modeを保持し、新規fileは`0644`
- symlink作成能力がないWindowsでは、symlink専用回帰テストを環境能力skipとして分類
- 期限切れ・scope外・review binding不一致・未知schemaのwaiverはfail-closed。一軸のwaiverで他軸の新規悪化を相殺しない
- skills rootのsymlink、曖昧frontmatter、path spoofはfail-closed。skill安定キーはrepo相対path
- `scripts/` payload digestは`executable_asset`のdeny軸。`SKILL.md`本文のみはevidence（ID不変）
- テスト走査のsymlink・非UTF-8・曖昧構文はfail-closed。`subject_key`は`file::test-name`（NFC）
- 自由記述skip reasonは許可条件にしない。`focused_only`は既存`strict`で常時deny

## [0.1.1] - 2026-08-19

### 修正

- 公開済み配布物に残っていたPRIVATE／公開未承認の旧文書を、現在のPUBLIC状態へ訂正
- GitHub Release限定配布とPyPI非公開の案内を維持

## [0.1.0] - 2026-08-17

### 追加

- `tracked ∧ ignored` の新規増加を止めるラチェット型ゲート
- 現在の矛盾を記録するbaselineと、意図的な更新経路
- Pythonパッケージとソースcheckoutの両方から使えるCLI
- Ubuntu・Windows、Python 3.11・3.13のCI
- 日本語の利用者向け文書とRepo Preflight

### 安全性

- gitによる列挙に失敗した場合はfail-closedで停止
- baseline変更とskip利用を人間レビューの対象として明示
- 公開前はPRIVATE運用を維持し、公開・release・配布を別承認とした

### 公開準備

- 公開時のライセンスとしてMIT Licenseを採用
- 配布先はGitHub Releaseだけとし、PyPIへは送信しない方針を採用
- visibility変更、tag、release作成は個別承認のまま維持
