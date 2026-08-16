# 運用手順

## 導入

導入先リポジトリの状態を先に確認し、現在の`tracked ∧ ignored`をbaselineとして記録します。
baselineの初回差分を人間が確認してから、commit前の検査またはCIへ接続します。

## 日常運用

- 通常検査はread-onlyで実行する
- 新規矛盾が出たら、生成物は追跡解除し、実装ファイルはignore対象から除外する
- 意図的な例外だけbaseline更新とし、その差分をレビューする
- skipは緊急回避に限定し、実行理由と出力をレビュー記録へ残す

## 監視と再検証

- CLI、baseline形式、hook、CI、対応Pythonを変更したときは全テストを再実行する
- gitの列挙結果とbaseline件数が想定外に変化した場合は導入先を調査する
- release前にはUbuntu・Windows、対応するPython版で検証する

## ロールバック

導入を外す場合は、最初にcommit hookまたはCIの呼び出しだけを無効化します。
baselineと導入commitは、原因調査と再導入に使えるため即時削除しません。通常のGit差分として
取り消し、導入先のテストと`git status`を再確認します。
