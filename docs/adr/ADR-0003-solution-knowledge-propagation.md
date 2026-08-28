# ADR-0003: 解決知識の昇格・伝播・再利用

- Status: Proposed
- Date: 2026-08-29

## Context

AI Ratchet Gateの既存coreは、決定論的なFindingをbaselineと比較して新規悪化を検出する。
一方、運用上の本当の損失は「一度解決した問題が別repositoryで再発し、人間またはagentが同じ
調査・修正を繰り返すこと」にある。

単純なdeny ruleだけを中央配布すると、既知問題を早く止められても、既知の解法があるのに毎回
人へ戻す構造が残る。MVPではRatchetを「禁止事項の集合」だけでなく、検証済みの解決知識を
再利用するcontrol planeへ拡張する。

## Decision

### 1. 解決知識を第一級データとして持つ

`ai-ratchet-gate.solution-knowledge/v1`を導入し、各entryは少なくとも次を持つ。

- `problem_key`: repository path / commit SHAに依存しない同種問題の安定キー
- `resolver_id` / `resolver_version`: agent harness側の決定論的resolver契約
- `scope`: `central` または `local`
- `evidence_sha256`: 再現fixtureや回帰testなど、昇格根拠のdigest
- `source`: 元になったreview / repository / incidentを追跡する参照
- `knowledge_id`: problem + resolver identityから導出する安定digest

### 2. 中央とrepo固有を二層で合成する

中央knowledgeは複数repositoryへ再利用する。各repositoryは必要に応じてlocal knowledgeを持つ。
同じ`problem_key`が中央とlocalの両方に存在する場合はlocalを優先する。

同一scope内で同じ`problem_key`に異なるresolverが複数存在する場合は、どちらかを恣意的に選ばず
fail-closedとする。

### 3. 既知問題は「block」ではなく「resolution available」として扱う

問題検出後、合成済みknowledgeを参照する。

- 既知: `known / verified_solution_available` を返し、harnessがresolverを適用して再検証する
- 未知: `unknown / no_verified_solution` として人または上位agentへ返す

未知問題を解決し、独立再現と回帰testが取れた後、人間レビューを経てcentralへ昇格できる。

### 4. ai-ratchet-gate本体は対象repoを直接変更しない

既存のread-only安全境界を維持する。ai-ratchet-gateは解法の選択、schema検証、曖昧性検出、
receipt生成を担い、実際の変更適用は外側のagent harness / orchestratorが担う。

resolverは`resolver_id + resolver_version`で固定し、harnessは適用後に必ず同じdetector / testsを
再実行する。検証に失敗したresolverは成功としてknowledgeへ蓄積しない。

## Promotion gate

localまたはincident由来の解法をcentralへ昇格できるのは次を全て満たす場合だけとする。

1. 問題がコード・既存契約・fixtureのいずれかで独立再現できる
2. resolver適用後に当該問題が消える
3. 既存回帰testが通る
4. `problem_key`が特定repository固有のpath / secret / account identityへ依存しない
5. evidence digestとsourceが残る
6. 人間レビューでcentral scopeへの昇格を承認する

LLMの主観的な「直ったと思う」だけでは昇格しない。

## End-to-end loop

1. **Detect**: detectorが問題を`problem_key`へ正規化する
2. **Lookup**: central + local knowledgeを決定論的に合成する
3. **Resolve**: 既知ならharnessがresolverを適用する
4. **Verify**: detector + testsで解決を再検証する
5. **Receipt**: 使用したknowledge ID、resolver version、input/output SHA、検証結果を残す
6. **Learn**: 未知問題だけ人へ返し、解決後にlocalへ記録する
7. **Promote**: 汎用性と証拠が揃ったものだけcentralへレビュー昇格する
8. **Propagate**: 他repoは次回lookupから同じcentral knowledgeを利用する

このループの成功状態は「既知問題を止め続けること」ではなく、**既知問題を人へ戻さず解決し、
検証して通過させること**である。

## MVP completion criteria

- central knowledgeとlocal knowledgeを同じschemaで読み込める
- local overrideを含めて決定論的に合成できる
- repo A由来のcentral knowledgeがrepo B相当の同一`problem_key`で選択されるtestがある
- unknown problemは偽成功せずhuman-resolutionへ返る
- 曖昧なresolver定義はfail-closedになる
- 対象repo mutationはai-ratchet-gate本体へ入れず、harness境界を維持する

## Consequences

### Positive

- 同じreview findingへの再調査を知識として償却できる
- repository固有例外と横断知識を混ぜずに運用できる
- 特定LLMのmemoryに依存せず、Git上でレビュー可能な形にできる
- resolverの適用と検証をharnessへ分離でき、coreへ外部書込権限を持たせずに済む

### Trade-offs

- 問題検出を`problem_key`へ正規化するdetector契約が別途必要
- resolver実装はharness側に必要
- central昇格は自動化しきらず、人間停止線を残す
- 誤った汎用化はblast radiusが大きいため、evidenceと回帰testの品質が重要になる
