---
title: テスト無効化（skip / only / hollow）adapter
type: adr
status: accepted
created: 2026-08-28
updated: 2026-08-28
owner: nexus-ai-2045
related:
  - ../../ROADMAP.md
  - ../architecture.md
  - ../threat-model.md
  - ADR-0001-generic-ratchet-engine.md
---

# ADR-0005 テスト無効化 adapter（Issue #11）

## Context

Issue #11は、実行されないテストの集合がbaselineを超えて増えないことを
Phase 2の第三built-in adapter候補として提案する。AIエージェントはredをgreenにする
最短経路としてskip / `.only` / 空洞assertを選びやすく、gitの対症療法と同型である。

v1はPythonとJS/TSに限定する。C4（削除・rename）と逆さまテスト（仕様をバグに固定する
assert）はスコープ外。自由記述のskip reasonは許可条件にしない。例外は既存の
`ai-ratchet-gate.waivers/v1`で扱う（新waiver schemaは作らない）。

## Decision

- built-in adapter IDは`test.disable`とする。
- `observe --adapter test.disable`でopt-in。既定は`git.tracked_ignored`。
- 対象ファイル: `test_*.py` / `*_test.py` / `*.test.js|ts|jsx|tsx` / `*.spec.js|ts|jsx|tsx`。
  既定走査rootは対象repo全体だが、`.git` / `node_modules` / `.venv` / `venv` /
  `__pycache__` / `.tox` は除外する。symlink・repo外・非UTF-8・曖昧構文はfail-closed。
- Finding軸（独立。net-zeroなし）:

| rule_id | 分類 | 意味 | evaluate上の扱い |
|---|---|---|---|
| `unconditional_skip` | C1 | 無条件skip | `ratchet`（baseline外の新規だけdeny） |
| `focused_only` | C2 | `.only` / `fit` / `fdescribe` | 既存`strict`（1件でもdeny）。新契約ではない |
| `hollow_test` | C3 | 空本体または`assert True`/`expect(true)`のみ | `ratchet` |

- `subject_kind`は常に`test_case`。`subject_key`は`{repo相対path}::{test_name}`（NFC）。
  pathまたはtest_nameに`::`を含む場合はfail-closed。
- C1: `@pytest.mark.skip` / `@unittest.skip` / 本体先頭の`pytest.skip()` /
  `raise SkipTest` / `test.skip` / `it.skip` / `xit` / `describe.skip` 等。
  **`skipif` / `skipIf`（条件付き）はC1に含めない**（別物）。さらにskipif付きテストは
  実行されない可能性があるため**C3 hollowにもしない**（hollowは実行されるテストだけ）。
  reason文字列の有無は許可条件にしない。
- C2: `test.only` / `it.only` / `describe.only` / `fit` / `fdescribe`。pytestに構文等価はなく、
  CLIの`-k`/`-m`は静的観測外。
- C3: 空body、または恒真assertのみ。**実行されるテストだけ**が対象。
  `test.todo`は正当な未実装申告でありhollowではない。無条件skip済みもhollowではない。
- Pythonは`ast`で解析する。JS/TSは保守的な構文走査（完全なTS parserは持ち込まない）。
- LLM判定なし。OPA/Regoなし。

## Allowed

- read-only観測とFinding正規化
- C1/C3のgrandfatherと既存waiver消費
- C2を`evaluate --mode strict`で常時deny

## Prohibited

- テストの自動修復・生成
- 自由記述reasonを機械許可条件にすること
- C4（削除・rename）や逆さまテストの検出主張
- 新waiver schemaの導入
- baseline自動拡大・waiver自動承認

## Human Review Gate

baseline拡大（特に`focused_only`の記名禁止を破るもの）、waiver追加・延長、
adapterのenforce昇格、merge / release / 公開は人間レビュー必須。

## Consequences

### 肯定的

- 第三の独立adapterを既存core上で検証できる（v1.0の3-adapter条件へ前進）。
- `.only`を新契約ではなく既存`strict`へ載せられる。
- skipifと無条件skipを混同しない。

### 否定的

- JS/TSは保守的走査のため、高度なマクロ／動的生成は見逃しまたはfail-closedになり得る。
- C2とC1/C3を同一observationで混ぜる場合、運用は`focused_only`有無に応じてmodeを分けるか、
  `focused_only`をbaselineへ入れない運用が必要。

## Next Actions

1. `TestDisableAdapter`とCLI opt-inを実装する。
2. C1/C2/C3 fixture・skipif非検知・todo非hollow・fail-closedの回帰を追加する。
3. ROADMAP / architecture / threat-model / ADR index / READMEを更新する。
