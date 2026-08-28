# ADR-0002: PRレビュー知見の昇格とリポジトリ横断伝播

- Status: Proposed
- Date: 2026-08-29

## Context

AI Ratchet Gateの汎用engineは、決定論的adapterが返すFindingを安定IDへ正規化し、reviewed baselineと比較して新規悪化をdenyできる。
しかし、実運用では別の断絶が残る。

1. PRレビューで発見された問題が、そのPRだけの修正で終わる。
2. 同種の問題が別repoで再発しても、中央側へ学習済みの不変条件として残らない。
3. 中央で追加した不変条件を各repoへどう適用するかの契約がない。
4. repo固有のルールと中央共通ルールを、どちらかで上書きせず合成する契約がない。
5. レビューコメントは未信頼入力なので、そのままruleへ変換するとprompt injection・誤診・設計判断の自動昇格を招く。

このADRは、既存engineを変更せず、その前段と配布側の制御面を定義する。

## Decision

### 1. ルールの正本を二層に分ける

- **central rule set**: 複数repoへ再利用できる、対象非依存または対象クラス単位の不変条件。
- **local rule set**: 1 repoだけの契約・設計・互換性・例外に依存する不変条件。

各repoでの有効rule setは和集合とする。

```text
active_rules(repo) = central_rules ∪ local_rules(repo)
```

local ruleがcentral ruleを暗黙に無効化してはならない。中央ruleを適用不能にする場合は、期限・理由・対象rule IDを持つ明示的waiverとしてレビュー可能にする。

### 2. レビューコメントをruleの正本にしない

PRレビューコメント、bot出力、LLM出力、Issue本文などはすべて**candidate evidence**であり、未信頼入力として扱う。

candidateは次の条件をすべて満たすまでcentral/local ruleへ昇格しない。

1. 対象PRのexact HEADが固定されている。
2. コメント本文そのものではなく、コード・既存契約・決定論的テストのいずれかで独立再確認できる。
3. findingを再現するfixtureまたは機械検査条件が定義できる。
4. ruleのfalse-positive境界と対象scopeを説明できる。
5. repo固有か横断可能かを分類できる。
6. rule ID・adapter ID・version・証拠digestがレビュー可能なdiffになる。
7. 人間レビューを経てenforceへ昇格する。

未再現、設計判断、権限・secret・settings変更を要求するものは自動昇格しない。

### 3. Rule lifecycleを明示する

ruleは次の状態を持つ。

```text
candidate -> verified -> observe -> enforce
    |            |          |
    +----------> rejected <-+
```

- `candidate`: 未信頼レビュー等から抽出した仮説。再現不能・誤検知・非決定的なら直接`rejected`へ遷移できる。
- `verified`: 独立再現または既存契約で高確度確認済み。
- `observe`: 各repoで検出するがdenyしない。false-positiveと適用範囲を収集する。
- `enforce`: 新規悪化をdenyする。
- `rejected`: 誤検知・非決定的・scope不適合などの理由でその昇格経路を採用しない。

repo固有であること自体は`rejected`理由ではない。横断central昇格の対象外とし、検証済みならlocal lifecycleへ送る。
`candidate -> verified`までは自動補助できるが、`observe -> enforce`は人間停止線とする。

`observe -> enforce`へ移る前に、各consumer repoで最後のobserve結果から既存違反のreviewed baseline diffを作る。
central revision更新とそのbaseline handoffを同じレビュー単位で確認し、既存負債を新規findingとして誤認しない状態でenforceを開始する。

### 4. Rule manifestをGitで管理する

別DBを正本にしない。ruleはversioned text manifestとしてGit diffに残す。

概念schema:

```yaml
schema: ai-ratchet-gate.rule/v1
rule_id: repository.no-personal-absolute-path
adapter_id: repository.path-policy
adapter_version: "1"
scope:
  kind: repository
  selectors: ["*"]
state: observe
origin:
  repository: owner/source-repo
  pull_request: 123
  head_sha: <exact sha>
verification:
  method: fixture
  evidence_sha256: <sha256>
message: 個人環境の絶対pathを新規導入しない
remediation: repo相対pathまたは設定値へ置換する
```

manifestは実行ロジックではない。adapterがruleを決定論的に評価し、既存Finding schemaへ変換する。

### 5. 中央から各repoへの伝播はpull方式を基本とする

中央repoが他repoへ直接pushすることを標準動作にしない。

各repoのCIまたは導入更新PRが、固定されたcentral revisionを参照する。

```text
central_source:
  repository: nexus-ai-2045/ai-ratchet-gate
  revision: <commit sha or signed release digest>
```

更新はdependency updateと同様にレビュー可能なPRとして行い、中央更新が無審査で全repoを一斉破壊しないようにする。

緊急の組織ポリシー強制などpush型配布が必要な場合も、配布オーケストレータは本package外の運用層に置く。

### 6. PRレビュー待ちループとRatchetを接続する

外部オーケストレータはPRごとに次を反復できる。

1. exact HEADを固定する。
2. CI/review thread/commentをread-only取得し、**各結果が固定したHEAD SHAに属することを検証する**。
3. 未信頼入力としてprompt injectionを検査する。
4. actionable findingをコード・契約・テストで再検証する。
5. repo固有ならlocal candidate、横断可能ならcentral candidateとして記録する。
6. 修正後のHEADで再観測する。
7. receipt生成直前にPR HEADを再取得し、最初に固定したSHAから動いていたらfail-closedで最初から再評価する。
8. blocking findingが0件、CI green、未解決重要threadが0件ならmerge-ready receiptを生成する。

merge-ready receiptには少なくともrepository、PR番号、exact HEAD、変更目的、検証済みfinding、残存risk、central/local candidate IDに加え、**評価に使用したcentral source revisionと全local rule-set inputのdigest/identity**を含める。

このreceiptはmerge承認そのものではない。

## Consequences

### Positive

- 同じレビュー指摘のrepo間再発を、会話記憶ではなくGit管理された機械契約へ変換できる。
- 中央とrepo固有の知識を混ぜずに併用できる。
- レビューbotの誤診やprompt injectionをruleへ直結させない。
- central更新のrevisionを固定でき、どのrule setで判定したか再現できる。
- 既存のFinding / Observation / Decision / receipt契約を再利用できる。

### Negative

- ruleを追加しただけでは効かず、対応adapterまたは既存adapterのrule解釈実装が必要。
- `observe`期間を設けるため、発見から全repo enforceまで即時ではない。
- central revision更新PRを管理する外部オーケストレーションが必要。

## Non-goals

- LLMレビューコメントを自動で正しいと判定すること。
- すべてのrepoへ中央repoから直接pushすること。
- merge、release、settings、secret、権限変更を自動承認すること。
- repo固有の設計判断を無理に中央ruleへ一般化すること。

## Follow-up

1. `ai-ratchet-gate.rule/v1`の最小schemaを実装する。
2. central + local manifestの決定論的mergeと重複rule ID拒否を実装する。
3. 最初の横断rule adapterを1つ選び、fixtureでcharacterizationする。
4. 外部PRオーケストレータ向けのcandidate / merge-ready receipt契約を別ADRで定義する。
5. 2つ以上のconsumer repoでcentral revision固定とlocal rules併用をsmoke testする。
