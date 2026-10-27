# ADR-0008: 外部操作・対象範囲・残務の証拠契約

- 状態: 採用（2026-10-22、独立したopt-in API）
- 日付: 2026-08-29

## 背景

外部変更を伴うagent運用では、commandが終了コード0を返しても、非同期処理や反映遅延により実際の対象状態が未確定なことがある。また、process cwdと明示targetが異なる時に親repositoryを誤走査したり、task固有残務と別ownerの既存WIPを混ぜてcloseoutを誤判定したりする。

これらは対象固有のGitHub操作やcleanup実装ではなく、上位Harnessが証拠を組み立てる際の汎用契約として固定できる。

## 決定

既存`ResolutionReceipt v2`とCLIを変更せず、opt-in Python APIとして次の独立schemaを追加する。

### 1. `operation-receipt/v1`

外部操作のterminal status・終了コード・terminal証拠と、期待状態・独立readback状態・readback証拠を別々に固定する。成功条件は次のANDのみとする。

```text
terminal_status == succeeded
AND exit_code == 0
AND readback_state_sha256 == expected_state_sha256
AND readback_evidence_sha256 is present
AND readback_evidence_sha256 != terminal_evidence_sha256
```

command成功だけ、readback欠落、不一致、timeout、状態不明は`denied`とする。receiptはcanonical JSON bodyのSHA-256へ束縛し、未信頼JSONは`verify_operation_receipt`でexact schema・自己hash・意味条件を再計算する。これは証拠の整合性であり真正性ではないため、署名やCI attestationなしに承認根拠へ昇格しない。

### 2. `scope-binding/v1`

観測pathをprocess cwdではなく明示`target_root`へ束縛する。相対pathはtarget root基準で解決し、target外へ出るpathが1件でもあればfail-closedにする。空観測は完了証拠にせず、期待件数とenumerator証拠hashを必須化する。対象固有のGit列挙やrepository resolverは上位層に残す。

### 3. `residual-report/v1`

残務を`task_residual`、`repo_residual`、`unrelated_existing_wip`、`ui_archive_residual`へ分類する。task/repo/UIはopenまたはunknownならcloseoutをblockする。証拠付き`unrelated_existing_wip`は件数を保持するが、taskの残務ゼロ判定へ混ぜない。

## 境界

- GitHub API、Git push、cleanup、UI archiveなどのmutation primitiveは内蔵しない。
- receiptは承認書・真正性証明ではない。必要な署名やCI attestationは外層で行う。
- 保存済みの3 schemaは各`verify_*`関数だけをconsume入口とし、raw dataclassや未検証JSONをauthorityとして使わない。
- subject、target、owner、pathへsecretや個人情報を入れず、保存・ログ側でopaque IDまたはredactionを使う。
- collectionは上限4096件。scopeのresolve後から後続mutationまでのsymlink/junction差替えは防がないため、信頼済みdirectoryまたはhandle-based consumerを使う。
- 既存adapter、baseline、waiver、legacy CLIの判定意味は変更しない。
- Projects固有path、repository名、account名はfixtureにも埋め込まない。

## 回帰テスト

- exit 0でも独立readbackが欠落・不一致ならdeny
- `parent/.repos/child`で親cwdから実行しても子targetへ束縛
- 親repositoryのpath混入をdeny
- task残務0＋unrelated WIPありをcloseout可
- task/repo/UI残務のopenをcloseout不可
- 未知status/categoryをfail-closedで拒否

## 検証できる範囲

hashの相違だけでは取得経路の独立性や真正性を証明しない。信頼したcollectorが証拠を取得し、必要なら外層が署名・attestationを照合する。

scopeの件数一致は完全列挙の証明ではなく、各pathの実在も検証しない。enumeratorの信頼性、同一対象の全件を観測したこと、後続操作までの状態維持は呼出元が検証する。絶対pathを含むreceiptは公開ログへ出さず、私用pathを含まない隔離fixtureを使う。

無関係WIPの分類と残務一覧は呼出元の入力であり、hashだけで無関係性や網羅性を証明しない。`residual_zero`は供給された分類済み項目に対する判定であり、未列挙の残務がない保証ではない。

この追加は既存CLI・adapter・公開済みwheelを変更しない。sourceの版は公開API追加として0.3.0とする。API追加と実運用consumerでの強制適用は別に検証する。

UTF-8で表現できないfilesystem pathやreceipt文字列は、値を含まない `RatchetError` で拒否する。通常のUTF-8入力の正規化・digest形式は変更しない。
