# アーキテクチャ

汎用化の設計判断は[ADR-0001](adr/ADR-0001-generic-ratchet-engine.md)、用語の境界は
[先行概念との関係](prior-art.md)を正本とする。解決知識の再利用はADR-0003、適用・再検証Harness境界はADR-0007を正本とする。

## Repository責務

| 層 | 所有する責務 | 所有しない責務 |
|---|---|---|
| `ai-ratchet-gate` | 決定論的core、schema、built-in adapter、baseline、receipt、resolver identityとHarness状態遷移 | GitHub mutation、対象固有resolver、承認、公開 |
| `repo-preflight` | PR、CI、review、tag、Release等のread-only外部状態照合 | 対象固有の修復、公開実行 |
| 上位Harness / 非公開運用層 | 隔離worktree、対象固有resolver、commit/push/PR更新、人間承認、外部送信 | 汎用判定・knowledge merge・receipt契約の複製 |

この分離により、通常のengine実行をread-onlyに保ち、Harnessも対象固有のmutation primitiveをpackageへ埋め込まない。

## 構成

- `src/ai_ratchet_gate/cli.py`: 検査、baseline比較、CLIの正本
- `src/ai_ratchet_gate/harness.py`: 解決知識をpre-verify、resolver適用、post-verify、receiptへ接続する薄い契約
- `ai_ratchet_gate.py`: ソースcheckoutからの従来利用を維持する互換ラッパー
- `.ai-ratchet-gate/baseline.txt`: 導入時点で許容した既存矛盾のパス集合
- `scripts/verify.py`: 選択したPythonでテストとCLI smoke testを実行する検証入口
- `scripts/enforce_observe_evaluate.py`: local/CI向けのobserve→evaluate運用接続（既存CLI消費）
- `.ai-ratchet-gate/baselines/*.v1.json`: レビュー済みfinding_ids seed（subjectはenforcementが束縛）
- `tests/`: 列挙、baseline差分、互換ラッパー、CLI、knowledge、Harness状態遷移の回帰テスト

汎用engineでは、上記の既存入口を維持しながら内部を次へ分離する。

- `model`: Finding、Observation、Decisionのversioned schema
- `adapters`: 対象をread-only観測し、安定IDへ正規化するbuilt-in adapter
  （`git.tracked_ignored`、`skills.provenance`、`test.disable`）
- `engine`: adapterに依存しない集合比較、軸別判定、central/local解決知識の合成
- `harness`: resolver registry、pre/post verification、before/after digest、resolution receipt
- `waiver`: 期限付き例外のschema検証と適用判定（承認はしない）
- JSON baseline: 既存負債のreviewed snapshot（grandfatherされたfinding ID集合）
- JSON waiver: baselineと分離した期限付き例外。`evaluate --waiver`でopt-in消費するだけであり、
  追加・延長・scope変更の自動承認はしない
- `receipt`: subject SHAと全入力digestを結び付けた機械可読証跡

legacy CLIも`TrackedIgnoredAdapter`へ内部委譲し、Git観測の実装を二重化しない。legacy入口は
互換用`exclude_standard` profile、汎用入口は再現可能な`repo_only` profileを使う。baselineとreceiptの
書込みは同一directoryの一時fileを`fsync`した後にatomic replaceし、並走agentが途中状態を
観測しないようにする。

## データの流れ

1. CLIが組み込みadapter（既定`git.tracked_ignored`、opt-inで`skills.provenance` /
   `test.disable`）経由で対象をread-only観測する。
   legacy入口は互換用`exclude_standard` profile、汎用入口（`observe`）のgit adapterは
   `.gitignore`だけを見る再現可能な`repo_only` profileを使う。
   `skills.provenance`は`.agents/skills/`と`skills/`（存在するrootだけ）配下の
   `SKILL.md`とsibling `scripts/`を列挙する。
   `test.disable`は`test_*.py` / `*_test.py` / `*.{test,spec}.{js,jsx,ts,tsx}`を列挙し、
   Pythonは`ast`、JS/TSは保守的構文走査でC1/C2/C3をFinding化する。
2. adapterがFindingを安定IDへ正規化する。Gitでは追跡済みかつignore対象のパスを、
   NUL区切りのUTF-8として受け取る。UTF-8として読めないパスはfail-closedで停止する。
   skillでは`new_skill` / `allowed_tools_token` / `unrestricted_tools` /
   `executable_asset`を独立軸とする。`scripts/`のpayload digestはdeny軸。
   `SKILL.md`本文だけの変更はevidenceのみ（finding ID不変）。
   testでは`unconditional_skip` / `focused_only` / `hollow_test`を独立軸とし、
   `subject_kind=test_case` / `subject_key=file::qualified-name`（NFC。class/suite連結。
   タイトルの`/`は符号化）。
   `focused_only`は既存`strict` modeで常時deny（新契約ではない）。
3. baselineのfinding ID集合と比較する。
4. 新規findingがなければ成功し、あれば修復案を表示して失敗する。
5. 明示されたbaseline更新時だけ、baselineファイルを書き換える。

汎用契約では次のPDCAを各enforcement pointで繰り返す。

1. **Plan**: config、schema、adapter、baseline、active knowledge revisionを検証し、評価対象の次状態を固定する。
2. **Do**: adapterが対象をread-only観測する。既知問題ではHarnessがpre-verify後にexact resolverを呼び出す。
3. **Check**: findingを正規化・重複排除し、baselineに対して軸別判定する。resolver適用後は同じ問題をpost-verifyする。
4. **Act**: allow/denyまたはresolution statusをreceiptへ残す。観測不能・resolver不一致はfail-closedで停止する。

一軸の改善で別軸の新規悪化を相殺しない。将来の複数adapter統合では`indeterminate`を
schemaへ追加するが、MVPでは観測不能を`tool_error`としてfail-closedにする。

## 解決知識Harnessの流れ

1. `engine.resolve_problem`でcentral + local knowledgeから解法を決定する。
2. unknownなら対象を変更せず`human_resolution_required`を返す。
3. knownなら対象state digestを固定し、pre-verifierを実行する。
4. すでに解消済みならresolverを再実行しない。
5. `resolver_id + resolver_version`完全一致の登録resolverだけを呼び出す。
6. 適用後state digestを取り、post-verifierを実行する。
7. post-verifierが解決を証明した場合だけ`resolved`、それ以外は`verification_failed`とする。
8. subject、knowledge/resolver identity、before/after digest、verifier evidenceをresolution receiptへ固定する。

## 自動化と人間停止線

scan、decision、receipt、修復案、baseline縮小候補、既知resolverの隔離環境での適用・再検証までは自動化できる。baseline拡大、waiver承認、central knowledge昇格、merge、release、公開、外部送信は人間レビューで停止する。receiptの成功はこれらの承認を意味しない。

運用向けの手順・PDCA境界・hook迂回範囲・強制境界の正本は[OPERATIONS.md](../OPERATIONS.md)。
本repositoryのCIは`scripts/enforce_observe_evaluate.py`経由で既存の`observe`→`evaluate`を
消費する（公開CLIを増やさない）。branch protectionでそのジョブを必須化するかは導入先の
人間所有である。

## 信頼境界

- 対象リポジトリのgit metadataとignoreルールは検査入力であり、信頼済みとはみなさない。
- 通常検査はread-onlyで、baseline更新だけがファイル書き込みを行う。
- Harnessのresolver callback、snapshot、verifierは上位運用層が明示登録する信頼済み入力であり、本packageは第三者resolverのsandboxを提供しない。
- 本packageはfilesystem/GitHub/settings/secret等の対象固有mutation resolverを内蔵しない。
- commit hookやCIへの接続レシピは本パッケージが提供するが、hook迂回の強制阻止はこの
  パッケージ単体ではできない（OPERATIONSの「hookを迂回できる範囲」を正本とする）。
- MVPはbuilt-in adapterだけを実行する。第三者pluginのsandboxを提供したとはみなさない。
- receiptはbaselineとobservationのdigestを持つ。CLIはenforcement側が指定した
  `--expected-subject`との一致を必須にし、別候補への単純な再利用を拒否する。
- resolution receiptはbefore/after digestとverifier evidenceを持つが、自己hashは真正性の証明ではない。改ざん耐性が必要な環境では外層のCI attestationを使う。
