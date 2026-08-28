---
title: skill provenance / permission expansion adapter
type: adr
status: accepted
created: 2026-08-28
updated: 2026-08-28
owner: nexus-ai-2045
related:
  - ../../ROADMAP.md
  - ../architecture.md
  - ../prior-art.md
  - ADR-0001-generic-ratchet-engine.md
---

# ADR-0005 skill provenance と permission expansion の第二adapter

## Context

[ADR-0001](ADR-0001-generic-ratchet-engine.md) Next Action 5は、第二built-in adapterの第一候補を
決定論的な skill provenance / permission expansion とした。agentがSKILL.md bundleを追加・改変し、
宣言された tool / 権限を広げると、レビュー済みallowlistを静かに超える。

一方でSLSA供給網保証、Sigstore署名、SkillLedger台帳、OPA/Rego、runtime proxyは本repoのMVP境界外である。
必要なのは、既存の`Adapter.observe(ScanContext) -> Observation`契約上で、tracked skill bundleの
現状を安定Findingへ正規化し、baseline比較で新規悪化だけを止めることである。

## Decision

- built-in adapter `skill.provenance`（version `1`）を追加する。
- 対象は、subject repo内の**明示されたskills root**配下にある tracked skill bundle
  （各bundle直下の`SKILL.md`）に限定する。repo外filesystemは走査しない。
- `SKILL.md`はAgent Skills frontmatterとして扱い、最小決定論parserで`name` / `description` /
  `allowed-tools`（または`allowed_tools`）を読む。PyYAMLや外部schema runtimeは導入しない。
- Finding規則:
  - `skill_present`: bundleの存在（新規skill検出）
  - `skill_digest`: bundle内tracked file集合のSHA-256 digest（内容変化検出）
  - `skill_capability`: 宣言された各tool / permission（permission expansion検出）
- digestは path → file SHA-256 のソート済み連結ハッシュとする。symlinkは拒否する。
- Git列挙は`tracked_ignored`と同型に隔離する（`GIT_*`除去、`core.fsmonitor=false`、timeout、
  fail-closed）。repo制御hookを実行しない。
- CLIは`observe --adapter skill.provenance --skills-root <rel>`としてopt-in。既定の
  `git.tracked_ignored`とlegacy CLIはcharacterization固定のまま維持する。
- 判定は既存engineの集合差分に委譲する。adapterはbaseline比較・承認・修復を行わない。

## Allowed

- tracked skill bundleのread-only観測とFinding正規化
- `observe` / `evaluate`によるopt-in判定とreceipt生成
- malformed frontmatter・観測不能時のfail-closed

## Prohibited

- runtime mediation、skill install、ネットワーク取得
- 署名検証、transparency log、Sigstore、SkillLedger
- OPA/Rego、第三者plugin subprocess
- baseline自動拡大、自動修復、GitHub mutation、merge
- LLMの意味判断をdeny根拠にすること
- subject repo外のfilesystem走査

## Consequences

### 肯定的

- ADR-0001の共通契約を壊さず、Phase 2第一候補を検証可能なfitness functionとして導入できる。
- permissionの拡大だけを`skill_capability`の新規Findingとして止め、縮小は`new_only`で許容できる。

### 否定的

- frontmatter方言の完全互換は狙わない。未対応構文はfail-closedする。
- digestはtracked file集合のみ。untracked追加はgit-aware境界の外である。

### 検討した代替案

- **OPA/Rego**: 強力だが小さなPython配布へ新runtimeを持ち込む。
- **SkillLedger / Sigstore**: 台帳・署名は別信頼境界であり本MVPの範囲外。
- **repo-preflightへ統合**: GitHub外部状態と対象内部観測が密結合になる。

## Next Actions

1. characterizationと回帰（新規skill / digest変化 / 権限拡大 / grandfather / malformed /
   hook非実行）を`scripts/verify.py`で固定する。
2. memory / PII adapterは証拠漏洩設計後の後続sliceとする。
