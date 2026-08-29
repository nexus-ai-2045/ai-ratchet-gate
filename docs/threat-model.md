# 脅威モデル

## 守る対象

- `tracked ∧ ignored` の矛盾を増やさないという不変条件
- skill provenance（新規SKILL.md、`allowed-tools`拡大、無制限tools、scripts payload digest変更）を
  増やさないという不変条件。`SKILL.md`本文のみの変更はevidenceでありfinding IDが変わらないが、
  companion `scripts/`の内容変更は新しい`executable_asset` findingとしてdenyする
- テスト無効化（無条件skip、`.only`/`fit`/`fdescribe`、空洞assert）を増やさないという不変条件。
  `skipif`はC1に含めず、`test.todo`はhollowではない。自由記述reasonは許可条件にしない。
  C4（削除・rename）と逆さまテストはスコープ外
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
- テストファイル列挙不能、symlink、非UTF-8、曖昧なJS/TS構文、Python構文エラー
- 無条件skipを自由記述reasonで正当化する試み（機械許可条件にしない）
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
- skills rootのsymlink、曖昧frontmatterではfail-closedにする
  （両方の既定rootが無い場合はfinding 0件として観測する）
- skillの安定キーはrepo相対pathとし、declared nameへの静かな合流を避ける
- `scripts/` payload digestを`executable_asset`のsubject_keyへ含め、内容改変をdenyする
- `SKILL.md`本文digestはevidenceのみ（本文のみ編集ではfinding ID不変）
- テスト走査のsymlink・非UTF-8・曖昧構文はfail-closed。安定キーは`file::qualified-name`（NFC。`/`符号化）
- `focused_only`は既存`strict` modeで1件でもdeny（新契約を増やさない）
- 自由記述skip reasonは許可条件にせず、例外は既存`waivers/v1`だけを消費する
- 一軸のwaiverや改善で他軸（例: tool拡大とscripts digest変更）を相殺しない
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
- 逆さまテスト（仕様をバグに固定する健全に見えるassert）の検出
- テスト削除・rename・収集対象外化（C4）の検出
- hookを迂回する管理者を、このパッケージ単体で阻止すること
- receipt自己hashによる作成者の真正性証明（必要なら外層の署名・CI attestationを使う）

## 人間レビュー境界

baseline拡大、waiver追加・延長、adapterのenforce昇格、schemaの判定意味変更は人間レビュー対象とする。
自動化は差分とreceiptを準備できるが、承認そのものは行わない。merge、release、公開、外部送信も
この脅威モデルの外側にある明示承認境界である。運用接続・停止線・hook迂回の正本は
[OPERATIONS.md](../OPERATIONS.md)とする。

## 回帰テスト対応（v1.0基準: 誤検知・観測失敗・入力改ざん）

網羅の正本はこの表。新規の脅威主張は、ここに行を足し、対応テストを先に追加する。

| 分類 | 脅威 / 主張 | 主な回帰 |
|---|---|---|
| 誤検知 | `mode=observe`は新規findingでもallow（収集用）。enforcementは`ratchet`/`strict` | `tests/test_engine.py::test_threat_observe_mode_collects_misdetection_without_deny`、`scripts/enforce_observe_evaluate.py`が`--mode observe`を拒否 |
| 誤検知 | message変更だけではIDが変わらない（理由の言い換えで監視から消えない） | `tests/test_waiver.py::test_threat_path_rename_or_reason_disguise_creates_new_id` |
| 観測失敗 | git列挙不能・repo外・timeoutは成功にしない | `tests/test_engine.py`（timeout）、`tests/test_generic_cli.py::test_observe_cli_fails_closed_outside_git_repo`、legacy exit 2 |
| 観測失敗 | skills/testのsymlink・非UTF-8・曖昧構文はfail-closed | `tests/test_skill_provenance.py`、`tests/test_test_disable.py` |
| 入力改ざん | 未知schema、subject replay、他subject baseline、duplicate ID | `tests/test_generic_cli.py`、`tests/test_engine.py::test_duplicate_finding_id_is_rejected` |
| 入力改ざん | finding件数爆発・過大JSON | `tests/test_engine.py::test_too_many_findings_fail_closed`、`test_observe_cli_rejects_observation_exceeding_evaluate_limit` |
| 入力改ざん | 一軸改善で他軸悪化を相殺しない | `tests/test_engine.py::test_threat_rule_axis_improvement_does_not_offset_new_worsening`、skills/waiverの軸非相殺テスト |
| 入力改ざん | baseline拡大をresolvedと混同しない | `tests/test_waiver.py::test_threat_baseline_enlargement_is_not_a_resolved_finding` |
| 運用 | observe→evaluateの運用接続がdeny/allowを既存CLIと同じexitで返す | `tests/test_enforce_observe_evaluate.py` |
