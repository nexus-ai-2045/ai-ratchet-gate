# 運用手順

## 導入

導入先リポジトリの状態を先に確認し、現在の`tracked ∧ ignored`をbaselineとして記録します。
baselineの初回差分を人間が確認してから、commit前の検査またはCIへ接続します。

第二adapter `skills.provenance`を使う場合は、対象repoの`.agents/skills/`および/または
`skills/`（存在するrootだけが走査対象）を用意し、
`observe --adapter skills.provenance`でobservationを取り、そのfinding ID集合を
`ai-ratchet-gate.baseline/v1`としてレビューしてから`evaluate`へ接続します。
両方のrootが無い場合はfinding 0件です。存在するrootを列挙できない場合はfail-closed（exit 2）です。

## 日常運用

- 通常検査はread-onlyで実行する
- 新規矛盾が出たら、生成物は追跡解除し、実装ファイルはignore対象から除外する
- skill側で新規SKILL.md、`allowed-tools`拡大、無制限tools、`scripts/`の追加・内容変更が出たら、
  意図しない拡大かレビューする。`SKILL.md`本文のみの変更はfinding IDが変わらない
  （scripts payload digestはdeny軸）
- 意図的な例外だけbaseline更新または期限付きwaiverとし、その差分をレビューする
- skipは緊急回避に限定し、実行理由と出力をレビュー記録へ残す
- baseline拡大、waiver追加・延長・scope変更、adapterのenforce昇格は自動承認しない

## 監視と再検証

- CLI、baseline形式、hook、CI、対応Pythonを変更したときは全テストを再実行する
- gitの列挙結果とbaseline件数が想定外に変化した場合は導入先を調査する
- `skills.provenance`のfinding件数やrule_id分布が想定外に変化した場合も導入先を調査する
- release前にはUbuntu・Windows、対応するPython版で検証する

## ロールバック

導入を外す場合は、最初にcommit hookまたはCIの呼び出しだけを無効化します。
baselineと導入commitは、原因調査と再導入に使えるため即時削除しません。通常のGit差分として
取り消し、導入先のテストと`git status`を再確認します。
`skills.provenance`だけ外す場合は、`--adapter skills.provenance`の呼び出しを止めればよく、
legacyの`git.tracked_ignored`検査はそのまま残せます。
