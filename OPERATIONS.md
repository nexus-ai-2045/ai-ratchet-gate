# 運用手順

この文書は、pre-commit / CI / ローカルrunner、人間停止線、hook迂回範囲の
**運用向け正本**です。設計判断の詳細は[architecture.md](docs/architecture.md)、
脅威と回帰の対応は[threat-model.md](docs/threat-model.md)、
core契約は[ADR-0001](docs/adr/ADR-0001-generic-ratchet-engine.md)を参照します。

## 同じ判定を三箇所から使う

判定の正本は公開CLIの `observe` → `evaluate` です（LLM・特定agent・ホストサービス不要）。

| 入口 | 呼び方 | 備考 |
|---|---|---|
| ローカルrunner | `python scripts/enforce_observe_evaluate.py --adapter … --baseline …`（任意 `--waiver`） | 本repo同梱の運用接続。既存CLIだけをsubprocessで呼ぶ |
| CI | `.github/workflows/ci.yml` の Enforce observe→evaluate ステップ | 上記スクリプトを3 built-in adapterへ適用 |
| pre-commit | `.pre-commit-hooks.yaml` の legacy `ai-ratchet-gate`、または下記レシピ | 汎用判定は公開APIを増やさず observe/evaluate を直接呼ぶ |

`scripts/enforce_observe_evaluate.py` はレビュー済み baseline seed（`finding_ids`）へ、
enforcement側が固定した subject（既定: `repo:nexus-ai-2045/ai-ratchet-gate@<HEAD>`）を
実行時に束縛してから `evaluate` する。`--mode observe` は受け付けない。

### 導入先での同等レシピ（コピー用）

```bash
SUBJECT="repo:OWNER/NAME@$(git rev-parse HEAD)"
OUT="$(mktemp -d)"
SEED=".ai-ratchet-gate/baselines/git.tracked_ignored.v1.json"  # レビュー済み seed
ai-ratchet-gate observe --repo . --adapter git.tracked_ignored \
  --subject "$SUBJECT" --out "$OUT/observation.json"
# レビュー済み finding_ids を持つ baseline に subject を束縛してから evaluate
python - <<'PY' "$SEED" "$SUBJECT" "$OUT/baseline.json"
import json, sys
seed_path, subject, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
seed = json.load(open(seed_path, encoding="utf-8"))
seed["subject"] = subject
open(out_path, "w", encoding="utf-8").write(
    json.dumps(seed, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
)
PY
ai-ratchet-gate evaluate \
  --observation "$OUT/observation.json" \
  --baseline "$OUT/baseline.json" \
  --expected-subject "$SUBJECT" \
  --receipt "$OUT/receipt.json"
```

運用接続スクリプトを使う場合は subject 束縛と一時 baseline 作成を代行する。

```bash
python scripts/enforce_observe_evaluate.py \
  --adapter git.tracked_ignored \
  --baseline .ai-ratchet-gate/baselines/git.tracked_ignored.v1.json
# 任意: レビュー済み waiver を evaluate へフォワード（承認はしない）
# python scripts/enforce_observe_evaluate.py ... --waiver waivers.json
```

exit codeは allow=`0`、deny=`1`、観測不能/schema不正=`2`。hookやCIは `!= 0` で止められる。

本repoの seed は `.ai-ratchet-gate/baselines/*.v1.json`（現状 finding_ids は空）。
`subject` 欄の placeholder は enforcement が上書きする。seed の拡大は人間レビュー対象。

## 導入

導入先リポジトリの状態を先に確認し、現在の`tracked ∧ ignored`をbaselineとして記録します。
baselineの初回差分を人間が確認してから、commit前の検査またはCIへ接続します。

第二adapter `skills.provenance`を使う場合は、対象repoの`.agents/skills/`および/または
`skills/`（存在するrootだけが走査対象）を用意し、
`observe --adapter skills.provenance`でobservationを取り、そのfinding ID集合を
`ai-ratchet-gate.baseline/v1`としてレビューしてから`evaluate`へ接続します。
両方のrootが無い場合はfinding 0件です。存在するrootを列挙できない場合はfail-closed（exit 2）です。

第三adapter `test.disable`を使う場合は、
`observe --adapter test.disable`でPython / JS/TSテストファイルをread-only観測し、
finding ID集合をbaselineとしてレビューしてから`evaluate`へ接続します。
`focused_only`（`.only` / `fit` / `fdescribe`）は既存`strict` modeで常時denyする運用を推奨します。
例外は既存の`ai-ratchet-gate.waivers/v1`だけを消費し、自由記述のskip reasonは許可条件にしません。
symlink・非UTF-8・曖昧構文はfail-closed（exit 2）です。

## 日常運用

- 通常検査はread-onlyで実行する
- 新規矛盾が出たら、生成物は追跡解除し、実装ファイルはignore対象から除外する
- skill側で新規SKILL.md、`allowed-tools`拡大、無制限tools、`scripts/`の追加・内容変更が出たら、
  意図しない拡大かレビューする。`SKILL.md`本文のみの変更はfinding IDが変わらない
  （scripts payload digestはdeny軸）
- test側で無条件skip・`.only`・空洞assertの新規が出たら、意図しない偽完了かレビューする。
  `skipif`と`test.todo`は観測対象外。例外はwaiver差分として残す
- 意図的な例外だけbaseline更新または期限付きwaiverとし、その差分をレビューする
- skipは緊急回避に限定し、実行理由と出力をレビュー記録へ残す
- baseline拡大、waiver追加・延長・scope変更、adapterのenforce昇格は自動承認しない

## 監視と再検証

- CLI、baseline形式、hook、CI、対応Pythonを変更したときは全テストを再実行する
- gitの列挙結果とbaseline件数が想定外に変化した場合は導入先を調査する
- `skills.provenance`のfinding件数やrule_id分布が想定外に変化した場合も導入先を調査する
- `test.disable`のfinding件数やrule_id分布が想定外に変化した場合も導入先を調査する
- release前にはUbuntu・Windows、対応するPython版で検証する

## ロールバック

導入を外す場合は、最初にcommit hookまたはCIの呼び出しだけを無効化します。
baselineと導入commitは、原因調査と再導入に使えるため即時削除しません。通常のGit差分として
取り消し、導入先のテストと`git status`を再確認します。
`skills.provenance`だけ外す場合は、`--adapter skills.provenance`の呼び出しを止めればよく、
legacyの`git.tracked_ignored`検査はそのまま残せます。
`test.disable`だけ外す場合も同様に、`--adapter test.disable`の呼び出しを止めれば足ります。

## Receding-horizon PDCA（境界ごとの再観測）

形式的な予測制御保証は主張しない。commit / PR / merge / release の各境界で、
同じ observe→evaluate を再実行する運用接続だけを提供する。

1. **Plan**: adapter・baseline seed・subject の固定方法を決める（本repoでは CI が HEAD を束縛）
2. **Do**: adapter が対象を read-only 観測する
3. **Check**: baseline と比較し receipt を残す
4. **Act**: allow/deny/tool_error を enforcement が解釈する。修復・baseline縮小候補は提案まで

このパッケージは PR の自動merge、tag、Release、公開、外部送信を行わない。

## 自動化してよい範囲 / 人間停止線

| 自動化してよい | 人間が所有する |
|---|---|
| scan（observe） | baseline 拡大 |
| decision（evaluate） | waiver 追加・延長・scope変更 |
| receipt 出力 | adapter / rule の enforce 昇格 |
| 修復案の提示 | merge / release / 公開 / 外部送信 |
| baseline 縮小候補の提示 | schema migration で判定意味が変わる変更 |
| CI・hook への接続設定の提案 | branch protection で当該 CI を必須化する操作 |

receipt の成功は上記承認の代替ではない。`AI_RATCHET_GATE_SKIP=1` は緊急回避であり、
恒久対応にしない。

## hook を迂回できる範囲と強制境界

このパッケージ単体では次を止められない。

- `git commit --no-verify`
- hook 未導入の作業環境からの commit / push
- 管理者による baseline・CI workflow・branch protection 自体の改変
- 本パッケージを呼び出さない別経路の merge

運用側（導入先）が担う強制境界の例:

- CI で `observe`→`evaluate`（または `scripts/enforce_observe_evaluate.py`）を必須ジョブにする
- branch protection でそのジョブの成功を要求する（GitHub設定。本パッケージ外）
- release 前に同じ判定を再実行する
- skip 利用と baseline 拡大の差分を人間が読む

policy decision（engine）と enforcement point（hook/CI/branch protection）は分離している。
engine は判定と receipt まで、強制の網羅は運用側の責務である。

## 誤検知時の扱い

1. まず `evaluate --mode observe` または観測専用フローで false-positive を収集する（enforcementでは使わない）
2. 真の新規悪化なら修復する
3. 意図的例外だけ、レビュー可能な baseline 拡大または期限付き waiver にする
4. rule / adapter の意味変更や enforce 昇格は人間レビュー

## baseline の追加・縮小・schema migration

- **追加（拡大）**: `--update-baseline`（legacy）または JSON baseline の `finding_ids` 追加。必ず diff レビュー
- **縮小**: 解消済み ID を seed から外す。改善方向は自由。自動化は候補提示まで
- **schema migration**: 未知 schema は fail-closed。判定意味が変わる migration は人間レビュー必須
