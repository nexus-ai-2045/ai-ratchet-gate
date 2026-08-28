# ADR-0004: 解決知識を適用・再検証するHarness境界

- Status: Proposed
- Date: 2026-08-29

## Context

ADR-0003で、既知問題はcentral/localの解決知識からresolverを選択し、外側のagent harnessが適用後に再検証する方針を定めた。
しかしresolver選択だけでは、人間へ同じ問題が戻る経路を閉じられない。一方で、`ai-ratchet-gate`へGitHub APIや特定repository向け修復コードを直接埋め込むと、汎用coreと運用権限の境界を壊す。

## Decision

`ai-ratchet-gate`は薄いHarness契約を提供する。対象固有のmutation primitiveは内蔵せず、呼び出し側が明示的に登録したresolver callbackだけを実行する。

固定ループは次とする。

```text
Resolve knowledge
  -> Snapshot(before)
  -> Pre-Verify
  -> exact resolver_id + resolver_version lookup
  -> Apply (caller-provided resolver)
  -> Snapshot(after)
  -> Post-Verify
  -> Resolution Receipt
```

### 1. Pre-Verifyを必須にする

すでに解消済みならresolverを再適用せず`already_resolved`を返す。これにより非冪等resolverの不要な再実行を避ける。

### 2. Resolver identityを固定する

knowledgeが指す`resolver_id`と`resolver_version`の完全一致だけを実行する。未登録や重複registryはfail-closedとし、似た名前のresolverへfallbackしない。

### 3. Apply成功を解決成功とみなさない

resolver callbackが例外なく終了しても、post-verifierが`resolved=true`を返すまで成功としない。失敗時は`verification_failed`としてreceiptに残す。

### 4. 未知問題は変更しない

`unknown / no_verified_solution`はresolverを実行せず、`human_resolution_required`として返す。未知問題への推測修正をしない。

### 5. Receiptをbefore/afterと検証証拠へ結ぶ

receiptは少なくともsubject、problem key、knowledge ID、resolver identity、before/after digest、verifier identity/evidence、statusを持ち、canonical JSONの自己hashを付ける。

### 6. 信頼境界

- Resolver callback、snapshot、verifierは呼び出し側Harnessの信頼済み入力である。
- 本packageはfilesystem、GitHub mutation、secret、settings変更のbuilt-in resolverを持たない。
- 実運用ではresolverを隔離worktree等へ適用し、post-verify成功後だけ上位orchestratorがcommit/push/PR更新を行う。
- receiptは真正性証明ではない。必要ならCI attestation等の外層へ結ぶ。

## MPC/FDE上の固定軸

MVPでは次の5軸だけを機械契約にする。

1. 対象identity
2. resolver identity/version
3. before/after state digest
4. verifier identity/evidence
5. terminal status

権限、merge、release、配布戦略等は別層に残し、Harness contractへ押し込まない。

## MVP completion criteria

- repo A由来のcentral knowledgeをrepo B相当のtargetへ適用できる
- pre-verify済みtargetへresolverを再適用しない
- unknown problemを変更しない
- resolver未登録/重複/例外はfail-closed
- post-verify失敗を成功と報告しない
- receiptがbefore/afterとverifier evidenceを固定する
- Python 3.11/3.13、Windows/Linuxの既存CIとrelease artifact検査がGreen
