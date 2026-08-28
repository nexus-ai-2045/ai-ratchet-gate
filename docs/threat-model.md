# 脅威モデル

## 守る対象

- `tracked ∧ ignored` の矛盾を増やさないという不変条件
- skill provenance（新規SKILL.md、`allowed-tools`拡大、companion `scripts/` digest変更）を
  増やさないという不変条件
- baseline変更を差分としてレビューできること
- 検査不能を成功として扱わないこと
- findingの安定した同一性と、軸ごとの新規悪化を相殺しないこと
- receiptが対象候補と入力へ結び付いていること

## 想定する入力と失敗

- `git add -f`によるignore対象ファイルの強制追加
- 追跡済みファイルへ後から追加されたignoreルール
- 日本語など非ASCII文字を含むパス
- git実行不能、対象パス不正、baseline欠落
- skills root欠落、列挙不能、symlink／path traversalによるrepo外参照
- `SKILL.md` frontmatter欠落や曖昧な`allowed-tools`解釈
- rule_idやsubject_keyの入替によるfinding偽装
- baselineの意図しない拡大やskipの常用
- schema downgrade、未知schema、baseline改ざん
- 期限切れ、scope不一致、再利用されたwaiver
- 不安定または重複したfinding IDによる違反隠蔽
- path traversal、absolute path、symlink / junction経由のrepo外参照
- 巨大出力、finding件数爆発、observer timeout
- Unicode正規化衝突、証拠やIDへのsecret・個人情報混入
- 古いreceiptを異なるHEADや設定へ再利用するreplay

## 対応

- gitのNUL区切り出力を使い、パスの曖昧な分割を避ける
- baselineにない新規パス／findingをdenyする
- git実行失敗とbaseline欠落ではfail-closedにする
- skills root欠落、symlink、曖昧frontmatterではfail-closedにする
- skillの安定キーはrepo相対pathとし、declared nameへの静かな合流を避ける
- 一軸のwaiverや改善で他軸（例: tool拡大とscripts改変）を相殺しない
- baseline更新とskipを人間レビュー対象として運用文書に残す
- 未知schema、identity不一致、重複IDをfail-closedにする。期限付きwaiverはbaselineと分離し、
  レビュー済みファイルだけを消費する。追加・延長・scope変更の自動承認はしない
- repo-relative pathと正規化規則を固定し、repo外参照を拒否する
- JSON入力にbyte上限、finding件数と各文字列に上限を設ける。外部adapterのtimeoutは次段階で追加する
- receiptへbaselineとobservationのdigestを記録し、CLIで期待subjectとの一致を検証する
- evidence本文を既定で埋めず、安全な要約とdigestを使う
- baselineとreceiptは同一directoryの一時fileへ排他的に書き、`fsync`後のatomic replaceで
  途中状態を公開しない。置換失敗時は既存fileを維持し、一時fileを回収する。既存fileのmodeは
  保持し、新規fileは`0644`とする
- waiverはfinding IDとobservation digest、review bindingへ束縛する。wildcardおよび無期限waiverを
  許可しない。期限切れ・scope不一致・binding改ざんはfail-closed（適用拒否または判定不能）

## 対象外

- secret、malware、依存関係脆弱性、コード品質全般の検出
- hookを通らないcommit経路の強制阻止
- 悪意ある利用者によるコード、baseline、CI設定そのものの改変
- 任意の第三者adapterを安全に隔離するsandbox
- LLM出力の意味的正しさや、形式化されていない未知障害の検出
- hookを迂回する管理者を、このパッケージ単体で阻止すること
- receipt自己hashによる作成者の真正性証明（必要なら外層の署名・CI attestationを使う）

## 人間レビュー境界

baseline拡大、waiver追加・延長、adapterのenforce昇格、schemaの判定意味変更は人間レビュー対象とする。
自動化は差分とreceiptを準備できるが、承認そのものは行わない。merge、release、公開、外部送信も
この脅威モデルの外側にある明示承認境界である。
