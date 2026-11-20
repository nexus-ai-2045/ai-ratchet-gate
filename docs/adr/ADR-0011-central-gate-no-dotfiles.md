# ADR-0011: ラチェットを中央から呼び、導入先へ設定ファイルを置かない

- 状態: 提案（2026-11-14。マージをもって採用）
- 日付: 2026-11-14
- 依存: ADR-0001、ADR-0010
- 範囲: 呼び出し方（配線）と、既定の baseline が無いときの扱いだけ。規則の数・判定の中身・
  個人情報ゲート（repo-preflight）は変えない。ADR-0010 の上限（約 30 本）には数えない（規則を足さないため）。

## 背景

2026-11-14 の実測（作業メモ「ラチェット不発とドットファイル-実測-2026-11-14」）で、次が分かった。

1. 公開リポの必須チェックは `all-green` だけで、`all-green` は repo-preflight の `gate` しか待っていない。
   ラチェットは別の workflow に置かれているため、赤でもマージできる。
2. 非公開リポは無料プランのため、ブランチ保護も ruleset も使えない（API が 403）。さらに
   Actions のジョブが支払いの理由で起動していない。ラチェットは一度も実行されずに「失敗」と出ている。
3. 導入のたびに `.ai-ratchet-gate/baseline.txt` と専用の workflow が各リポへコピーされる。
   16 リポの baseline のうち 13 本は中身が空（見出しのコメントだけ）で、うち 4 リポはどの workflow も
   ラチェットを呼んでいない。置いてあるだけで効いていない。
4. 導入先の workflow は v0.2.0 の wheel の URL と hash を各自で持っている。直しても配られない。

## 決定

1. 中央の reusable workflow `.github/workflows/ratchet-gate.yml`（`workflow_call`）を正本にする。
   導入先は、既存の `preflight.yml` に次のジョブを足し、`all-green` の `needs` に `ratchet` を入れるだけにする。
   新しいファイルは増やさない。

   ```yaml
   ratchet:
     uses: nexus-ai-2045/ai-ratchet-gate/.github/workflows/ratchet-gate.yml@<40桁SHA>
     with:
       ratchet-ref: <同じ40桁SHA>
   ```

   - 版は 40 桁の SHA で固定する（repo-preflight の preflight-gate と同じ作法）。枝名・タグ名は受けない。
   - 導入先と ai-ratchet-gate を別の場所（`target/` と `tool/`）へ取り出し、導入先の作業ツリーへは何も書かない。
   - 呼び出し側の `AI_RATCHET_GATE_SKIP` では素通りさせない（ジョブ内で空にする）。
2. 既定の baseline（`<repo>/.ai-ratchet-gate/baseline.txt`）が無いときは、見逃し 0 件として判定する。
   - 既存の矛盾があれば全部止まる。今まで（baseline 無しは exit 2）より緩くなる場面は無い。
   - `--baseline` で名指ししたファイルが無いときは、打ち間違いの恐れがあるので今までどおり exit 2。
   - baseline を置くのは、見逃す既存の矛盾が 1 件以上あるリポだけにする。
3. このリポ自身も同じ呼び方にし、`all-green` が `ratchet` を待つ。

## 比べた案

| 案 | 導入先に増えるもの | 必須になるか | 無料・非公開で効くか | 判断 |
|---|---|---|---|---|
| A. いまのまま（各リポに専用 workflow と baseline をコピー） | workflow 1 本＋baseline | ならない（`all-green` が待たない） | 効かない | 不採用（不発の原因そのもの） |
| B. 中央の reusable workflow を既存 `preflight.yml` から呼び、`all-green` で待つ | 既存ファイルに 4 行 | なる（既存の必須 `all-green` に乗る） | 公開は効く。非公開は Actions の支払いと保護の制約が残る | **採用** |
| C. repo-preflight の preflight-gate の中でラチェットも呼ぶ | 0 行 | なる | B と同じ | 最終形の候補。repo-preflight 側の変更なので、エンジニアリングリードのリファクタと合わせて決める |
| D. 組織の ruleset の required workflow で全リポに強制 | 0 行 | なる | 個人アカウント（無料）なので使えない | 不採用（使えない） |
| E. ローカルの pre-commit / pre-push だけ | フック一式 | ならない（`--no-verify` や未導入で抜ける） | 手元だけ | 補助のみ。フックを各リポへコピーしない |

B を選んだ理由: 導入先の新しいファイルが 0 本で、既に必須になっている `all-green` に乗るので、
設定を変えずにマージを止められる。C は B の呼び出し 4 行も消せるが repo-preflight の変更が要るため、
まず B で効かせ、C は調整のうえで別に進める。

## 影響

- 非公開リポでは、B でも Actions が起動しない限り効かない。支払いの解決か、公開化か、
  手元のフック（中央から呼ぶ形）で補うかは人が決める。
- 既に各リポにある空の baseline と専用 workflow は、B へ切り替えたあと消せる。消すのは人の承認のあと。
- 導入先の版を上げるときは、`preflight.yml` の SHA を 2 か所（`uses` の `@` と `ratchet-ref`）だけ変える。
