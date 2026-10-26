# ADR-0009: CI の pin・配布先・secret を外部事実で検査する adapter

- Status: Accepted
- Date: 2026-10-26
- Depends on: ADR-0001
- Note: ADR-0008 は別PRで使用中のため 0009 とする。

## Context

repository 移行や再構築のあとで、次の3種類のつまずきが繰り返し起きた。

1. CI が参照する共有 workflow の commit pin が、どのタグも指していない（移行前の SHA が残る）。
2. CI や依存定義が参照する GitHub Release の配布URLが、移行後に存在しない。
3. workflow が参照する secret が、移行先 repository に登録されていない。

どれも「repository の中身」だけでは決まらず、外部の事実（タグ一覧・URLの生死・登録済み secret 名）
との突き合わせが要る。一方、ADR-0001 の adapter は read-only・決定論的・副作用なしであり、
adapter の中でネットワークに出ると結果が再現できなくなる。

## Decision

- 外部事実は `ai-ratchet-gate.ci-facts/v1` JSON として **adapter の外** で集める。
  収集は `scripts/collect_ci_facts.py`（`git ls-remote --tags`、HTTP HEAD、任意で
  `gh api .../actions/secrets` の **名前だけ**）が担う。secret の値は読まず、書かない。
- adapter は repository の `.github/**/*.yml|yaml`（配布URLは `pyproject.toml` と
  `requirements*.txt` も）と facts だけを読む純関数とする。
  - `ci.pin_tagged`（rule `pin_not_tagged`）: 自組織の commit pin（`uses: <他owner>/...@SHA` は対象外）が
    facts のタグ SHA に無い。subject は `path@sha`。
  - `ci.release_asset_live`（rule `release_asset_not_live`）: Release 配布URLが facts の live 一覧に無い。
    `${...}` を含むURLは実行時まで決まらないため数えない。subject は `path#asset-<url digest>`。
  - `ci.secret_declared`（rule `secret_not_registered`）: 参照 secret 名が facts の登録名に無い。
    `GITHUB_TOKEN` と `on.workflow_call.secrets` で呼び出し側から渡される名前は対象外。subject は `secret:NAME`。
    数えるのは `${{ ... }}` の式の中の `secrets.NAME` と `secrets['NAME']` だけで、式の中の文字列は数えない。
    名前が決まらない読み方（`secrets[matrix.x]`・`toJSON(secrets)` など）は観測エラーで止める（fail-closed）。YAML の注釈の中の参照は数えない（ブロック文字列と行をまたぐ引用の中身は
    GitHub が展開するので数える）。除外は一番上の `on.workflow_call.secrets` だけから取り、ブロック形式・フロー形式・
    注釈つきの行を読む。ブロック文字列や引用の中の文字は除外に使わず、読めない形は数える側に倒す。
- secret 名の一覧は repository・environment（全 environment の和）・organization（repo に許可された分）を合わせる。
  どれか一つでも読めなければ「不明」として収集を止める（exit 2）。environment ごとの job 対応までは見ない
  （和を使うので、別 environment の secret を誤って登録済みとみなす取りこぼしはあり得る）。
- facts が無い・schema が違う・必要な key が無い場合は fail-closed（exit 2）。
  特に secret 名の取得元が無いのに secret 参照がある場合、collector は key を省き、adapter が止まる。
- baseline は既存と同じ `new_only` seed（空 `finding_ids`）で始め、増えたら赤にする。
- 既存 adapter と engine の判定は変えない。`--facts` は ci.* だけが受け付け、既存 adapter に渡すと exit 2。

## Consequences

- タグを打たずに新しい SHA へ pin を進めると赤になる。先にタグを作るか、レビュー済み baseline 更新が要る。
- secret 名の一覧取得には repository 管理権限が要る。CI の既定 token では読めないため、
  secret を参照する repository では権限のある場所で集めた facts を渡す。参照が無い repository は `[]` で通る。
- 配布URLの生死はネットワーク結果に依存する。収集時の通信失敗は facts 不成立（exit 2）とし、
  「死んでいる」とは扱わない。
