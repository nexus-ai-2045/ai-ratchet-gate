<!-- repo-preflight:review-record -->
<!-- repo-preflight:public-readiness-record -->

# Repo Preflight レビュー記録

## 対象

- リポジトリ: `nexus-ai-2045/ai-ratchet-gate`
- 公開範囲: `PUBLIC`
- 公開対象HEAD（初回公開時）: `b53fc2795bbee1b8e680c6d096541e1bc6830e07`
- 想定公開名義: `nexus-ai-2045`
- 初回バージョン: `0.1.0`（訂正版 `0.1.1`）
- 採用ライセンス: MIT
- 採用配布先: GitHub Releaseのみ（PyPIへは送信しない）
- 用途: trackedかつignoredになったGit上の矛盾が増えることを止める

## 現在の判定

**公開済み・v0.1.1リリース済み**です。この文書は、公開時点の検査と実施結果を記録します。

2026-08-17に最終HEADを再検査し、リポジトリをpublic化した後、同じHEADへ
`v0.1.0`を付与してGitHub Releaseを公開しました。PyPIへの送信は行っていません。

### v0.1.1訂正リリース

`v0.1.0`の配布物内に公開前のPRIVATE／公開未承認表記が残ったため、履歴や既存assetを
差し替えず、文書訂正版を`v0.1.1`として2026-08-19にGitHub Releaseへ公開しました。
機能変更はありません。fresh build・検査・人間レビューを経て、`v0.1.1`のtagと
Release assetを公開済みです。現行のinstall URLは`v0.1.1`を指します。

## 機械検査

- Gitの現在treeと履歴にあるsecret候補・個人path
- README、LICENSE、SECURITY.md、CONTRIBUTING.md、PREFLIGHT.mdの存在
- CI workflowとテスト
- repo固有の文書・実装・テストの変更連鎖
- dependency advisoryとGitHub Actionsの権限
- wheelとsource distributionの隔離ビルド、インストール、CLI smoke test
- パッケージmetadataと同梱ファイルの整合性

検査時のHEAD、日時、実行結果はPull Request本文または検証ログに記録します。この文書は
検査済みであることや公開可能であることを単独で証明しません。

## 人間レビュー境界

- baselineの拡大、skipの利用、hook配線変更は人間がdiffを確認する。
- push、Pull Request、merge、release、visibility変更は別々に承認する。
- 今後のreleaseやvisibility変更では、README、LICENSE、SECURITY.md、secret scan、
  personal path scan、commit historyを再確認し、リポジトリ固有の明示承認を得る。
- 今後のRelease、tag、告知、配布先追加、visibility変更は、公開対象、正確な操作、検査結果を
  提示し、このリポジトリ固有の明示承認を得てから実行する。

## 公開時に完了した方針・確認

- MIT Licenseで公開し、配布はGitHub Releaseだけを使い、PyPIへは送信しない
- 配布名を`ai-ratchet-gate`、初回versionを`v0.1.0`とする
- public化、tag push、GitHub Release公開をそれぞれ人間レビューする
- README、SECURITY.md、CONTRIBUTING.md、PREFLIGHT.mdが存在する
- ローカルテストがPython 3.13で成功し、GitHub ActionsがUbuntu・Windows、
  Python 3.11・3.13で成功した
- 最終HEADでテスト、ビルド、インストール、CLI smoke testが成功した
- wheelとsource distributionの隔離ビルド、インストール、CLI smoke testが成功し、
  metadata・同梱ファイル・インストール結果を確認した
- 最終HEADのtreeと全commit履歴をsecret・個人pathについて再検査し、現在treeの
  secret候補と個人pathは0件、`tracked ∧ ignored` は現存0件・新規0件だった
- README、LICENSE、SECURITY.md、PREFLIGHT.mdとパッケージmetadataの整合性を確認した
- dependency advisoryとGitHub Actionsの権限を確認した
- remote owner、操作アカウント、実効commit名義は`nexus-ai-2045`で一致した
- GitHub上のCI、review、visibility、default branch、Release、tagの状態を読み戻した
- 公開後にvisibility、tag、Release、添付物のSHA-256を読み戻し、
  GitHub Secret ScanningとPush Protectionを有効化した
