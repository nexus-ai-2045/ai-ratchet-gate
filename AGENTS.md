# Agent Rules

## Scope

この repository は、git の状態矛盾 (tracked∧ignored) の増分検査を扱う。

## Safety boundaries

- 既定動作は read-only、fail-closed とする。書き込みは `--update-baseline` の baseline 1 ファイルのみ
- 対象 repo のファイルを自動修復しない (`git rm --cached` 等は人間へ案内するだけ)
- baseline の更新は必ず diff としてレビュー可能な形で行う。skip 系の迂回を既定にしない
- remote 作成、push、公開、外部送信は別承認とする。既定 visibility は private

## Verification

- 判定は純関数として単体テストする (baseline 差分・整形・解析)
- git 統合テストは一時 repo で行い、親プロセスの `GIT_*` 環境変数を持ち込まない
- 完了報告では local test と実 repo での実測を分ける
