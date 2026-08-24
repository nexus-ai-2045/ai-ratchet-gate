# アーキテクチャ

汎用化の設計判断は[ADR-0001](adr/ADR-0001-generic-ratchet-engine.md)、用語の境界は
[先行概念との関係](prior-art.md)を正本とする。

## Repository責務

| 層 | 所有する責務 | 所有しない責務 |
|---|---|---|
| `ai-ratchet-gate` | 決定論的core、schema、built-in adapter、baseline、receipt | GitHub mutation、承認、公開 |
| `repo-preflight` | PR、CI、review、tag、Release等のread-only外部状態照合 | 対象固有の修復、公開実行 |
| 非公開運用層 | 人間承認、公開実行、外部送信、台帳 | 汎用判定ロジックの複製 |

この分離により、通常のengine実行をread-onlyに保ち、外部権限を持たせない。

## 構成

- `src/ai_ratchet_gate/cli.py`: 検査、baseline比較、CLIの正本
- `ai_ratchet_gate.py`: ソースcheckoutからの従来利用を維持する互換ラッパー
- `.ai-ratchet-gate/baseline.txt`: 導入時点で許容した既存矛盾のパス集合
- `scripts/verify.py`: 選択したPythonでテストとCLI smoke testを実行する検証入口
- `tests/`: 列挙、baseline差分、互換ラッパー、CLI動作の回帰テスト

汎用engineでは、上記の既存入口を維持しながら内部を次へ分離する。

- `model`: Finding、Observation、Decisionのversioned schema
- `adapters`: 対象をread-only観測し、安定IDへ正規化するbuilt-in adapter
- `engine`: adapterに依存しない集合比較と軸別判定
- JSON baseline: 既存負債のreviewed snapshot。期限付きwaiverは次段階で別schemaとして追加する
- `receipt`: subject SHAと全入力digestを結び付けた機械可読証跡

## データの流れ

1. CLIが組み込みadapter（`git.tracked_ignored`）経由でgitの標準コマンドを実行する。
   `.gitignore`だけを見て、global excludesFileや`.git/info/exclude`は判定へ混ぜない。
2. Gitで追跡済みかつignore対象のパスを、NUL区切りのUTF-8として受け取る。
   UTF-8として読めないパスはfail-closedで停止する。
3. baselineのパス集合と比較する。
4. 新規パスがなければ成功し、あれば修復案を表示して失敗する。
5. 明示されたbaseline更新時だけ、baselineファイルを書き換える。

汎用契約では次のPDCAを各enforcement pointで繰り返す。

1. **Plan**: config、schema、adapter、baselineを検証し、評価対象の次状態を固定する。
2. **Do**: adapterが対象をread-only観測する。
3. **Check**: findingを正規化・重複排除し、baselineに対して軸別判定する。
4. **Act**: allowまたはdenyをreceiptへ残す。観測不能はCLIの`tool_error`（exit 2）で停止する。

一軸の改善で別軸の新規悪化を相殺しない。将来の複数adapter統合では`indeterminate`を
schemaへ追加するが、MVPでは観測不能を`tool_error`としてfail-closedにする。

## 自動化と人間停止線

scan、decision、receipt、修復案、baseline縮小候補までは自動化できる。baseline拡大、waiver承認、
enforce昇格、merge、release、公開、外部送信は人間レビューで停止する。receiptの成功はこれらの
承認を意味しない。

## 信頼境界

- 対象リポジトリのgit metadataとignoreルールは検査入力であり、信頼済みとはみなさない。
- 通常検査はread-onlyで、baseline更新だけがファイル書き込みを行う。
- commit hookやCIへの接続は利用側の責務であり、このパッケージ単体では強制できない。
- MVPはbuilt-in adapterだけを実行する。第三者pluginのsandboxを提供したとはみなさない。
- receiptはbaselineとobservationのdigestを持つ。CLIはenforcement側が指定した
  `--expected-subject`との一致を必須にし、別候補への単純な再利用を拒否する。
- receiptの自己hashは真正性の証明ではない。改ざん耐性が必要な環境では外層のCI attestationを使う。
