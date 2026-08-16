# 変更履歴

このプロジェクトの重要な変更を記録します。

## 0.1.1（2026-08-17）

### 修正

- 公開済み配布物に残っていたPRIVATE／公開未承認の旧文書を、現在のPUBLIC状態へ訂正
- GitHub Release限定配布とPyPI非公開の案内を維持

## 0.1.0（2026-08-17）

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
