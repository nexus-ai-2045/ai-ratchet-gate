# Agent Rules

## Scope

このrepositoryは、agent非依存の汎用非回帰engineとbuilt-in adapterを扱う。
Gitの状態矛盾（tracked∧ignored）は最初のadapterであり、既存CLI互換を維持する。

## Safety boundaries

- 既定動作はread-only、fail-closedとする。書き込みはlegacy `--update-baseline`と明示したreceiptだけ
- 対象 repo のファイルを自動修復しない (`git rm --cached` 等は人間へ案内するだけ)
- baseline の更新は必ず diff としてレビュー可能な形で行う。skip 系の迂回を既定にしない
- baseline拡大、waiver承認、rule昇格は人間レビューなしに自動化しない
- remote 作成、push、公開、外部送信は別承認とする。既定 visibility は private

## Verification

- 判定は純関数として単体テストする (baseline 差分・整形・解析)
- git 統合テストは一時 repo で行い、親プロセスの `GIT_*` 環境変数を持ち込まない
- 完了報告では local test と実 repo での実測を分ける
