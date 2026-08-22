# 変更履歴

このプロジェクトの重要な変更を記録します。

## [Unreleased]

### 追加

- agent非依存のFinding、Observation、Decisionによる汎用ラチェットcore
- `new_only` / `exact_baseline` policyと`observe` / `ratchet` / `strict` mode
- 厳格なv1 observation・baseline入力と、入力digestへ束縛した決定論的receipt
- read-only adapter契約と`git.tracked_ignored`組み込みadapter
- 汎用engineの責務、人間停止線、先行概念を固定するADRと脅威モデル

### 互換性

- v0.1の引数なしCLI、テキストbaseline、出力、exit codeを維持
- 新しい汎用判定は`evaluate` subcommandとしてopt-in提供

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
