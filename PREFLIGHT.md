<!-- repo-preflight:review-record -->

# Repo Preflight レビュー記録

## 対象

- リポジトリ: `nexus-ai-2045/ai-ratchet-gate`
- 公開範囲: `PRIVATE`
- 用途: trackedかつignoredになったGit上の矛盾が増えることを止める

## 機械検査

- Gitの現在treeと履歴にあるsecret候補・個人path
- README、LICENSE、SECURITY.md、CONTRIBUTING.md、PREFLIGHT.mdの存在
- CI workflowとテスト
- repo固有の文書・実装・テストの変更連鎖

検査時のHEAD、日時、実行結果はPull Request本文または検証ログに記録します。この文書は
検査済みであることや公開可能であることを単独で証明しません。

## 人間レビュー境界

- baselineの拡大、skipの利用、hook配線変更は人間がdiffを確認する。
- push、Pull Request、merge、release、visibility変更は別々に承認する。
- このリポジトリをpublicにする場合は、README、LICENSE、SECURITY.md、secret scan、
  personal path scan、commit historyを再確認し、リポジトリ固有の明示承認を得る。
