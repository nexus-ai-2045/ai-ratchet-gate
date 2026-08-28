# 運用手順

## 導入

導入先リポジトリの状態を先に確認し、現在の`tracked ∧ ignored`をbaselineとして記録します。
baselineの初回差分を人間が確認してから、commit前の検査またはCIへ接続します。

第二adapter `skill.provenance`を使う場合は、対象repoにskills root（既定`skills/`）を用意し、
`observe --adapter skill.provenance`でobservationを取り、そのfinding ID集合を
`ai-ratchet-gate.baseline/v1`としてレビューしてから`evaluate`へ接続します。
skills rootが無い／列挙できない場合はfail-closed（exit 2）です。空のskills rootは
finding 0件のobservationになり、空baselineと組み合わせるとallowになります。

## 日常運用

- 通常検査はread-onlyで実行する
- 新規矛盾が出たら、生成物は追跡解除し、実装ファイルはignore対象から除外する
- skill側で新規SKILL.md、`allowed-tools`拡大、`scripts/`改変が出たら、意図しない拡大か
  レビューする。意図的な例外だけbaseline更新または期限付きwaiverとし、その差分をレビューする
- skipは緊急回避に限定し、実行理由と出力をレビュー記録へ残す
- baseline拡大、waiver追加・延長・scope変更、adapterのenforce昇格は自動承認しない

## 監視と再検証

- CLI、baseline形式、hook、CI、対応Pythonを変更したときは全テストを再実行する
- gitの列挙結果とbaseline件数が想定外に変化した場合は導入先を調査する
- `skill.provenance`のfinding件数やrule_id分布が想定外に変化した場合も導入先を調査する
- release前にはUbuntu・Windows、対応するPython版で検証する

## ロールバック

導入を外す場合は、最初にcommit hookまたはCIの呼び出しだけを無効化します。
baselineと導入commitは、原因調査と再導入に使えるため即時削除しません。通常のGit差分として
取り消し、導入先のテストと`git status`を再確認します。
`skill.provenance`だけ外す場合は、`--adapter skill.provenance`の呼び出しを止めればよく、
legacyの`git.tracked_ignored`検査はそのまま残せます。
