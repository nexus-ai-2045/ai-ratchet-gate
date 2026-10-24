# Agent Rules

## Scope

このrepositoryは、agent非依存の汎用非回帰engine、built-in adapter、解決知識の選択・再検証Harness契約を扱う。
Gitの状態矛盾（tracked∧ignored）は最初のadapterであり、既存CLI互換を維持する。

## Safety boundaries

- 既定動作はread-only、fail-closedとする。書き込みはlegacy `--update-baseline`と明示したreceiptだけ
- 対象 repo のファイルを直接修復するbuilt-in resolverを持たない。Harnessは呼び出し側が明示登録したresolver callbackだけを実行する
- resolver適用は隔離worktree等の上位運用層で行い、post-verify成功を確認するまでcommit/push/PR更新へ進めない
- baseline の更新は必ず diff としてレビュー可能な形で行う。skip 系の迂回を既定にしない
- baseline拡大、waiver承認、rule/knowledgeのcentral昇格は人間レビューなしに自動化しない
- remote 作成、push、公開、外部送信は別承認とする。既定 visibility は private

## Verification

- 判定・knowledge merge・Harness状態遷移は純粋または注入callbackで単体テストする
- git 統合テストは一時 repo で行い、親プロセスの `GIT_*` 環境変数を持ち込まない
- Harnessはpre-verifyとpost-verifyを分け、resolver callbackの正常終了だけを成功根拠にしない
- 完了報告では local test と実 repo での実測を分ける
