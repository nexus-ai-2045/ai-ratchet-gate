<!-- repo-preflight:public-readiness-record -->

# 公開準備レビュー

## 現在の判定

**公開済み・v0.1.0リリース済み**です。この文書は、公開時点の検査と実施結果を記録します。

- 対象リポジトリ: `nexus-ai-2045/ai-ratchet-gate`
- 公開対象HEAD: `b53fc2795bbee1b8e680c6d096541e1bc6830e07`
- 現在の公開範囲: `PUBLIC`
- 想定公開名義: `nexus-ai-2045`
- 想定初回バージョン: `0.1.0`
- 採用ライセンス: MIT
- 採用配布先: GitHub Releaseのみ（PyPIへは送信しない）

2026-08-17に最終HEADを再検査し、リポジトリをpublic化した後、同じHEADへ`v0.1.0`を付与して
GitHub Releaseを公開しました。PyPIへの送信は行っていません。

## v0.1.1訂正リリース

`v0.1.0`の配布物内に公開前のPRIVATE／公開未承認表記が残ったため、履歴や既存assetを
差し替えず、文書訂正版を`v0.1.1`とします。機能変更はありません。各versionのtagと
Releaseは、fresh build・検査・人間レビューを経て公開します。

## 確認済み

- README、SECURITY.md、CONTRIBUTING.md、PREFLIGHT.mdが存在する
- ローカルテストがPython 3.13で14件成功した
- GitHub ActionsがUbuntu・Windows、Python 3.11・3.13で成功した
- 現在treeのsecret候補と個人pathは0件だった
- `tracked ∧ ignored` は現存0件、新規0件だった
- wheelとsource distributionの隔離ビルド、インストール、CLI smoke testが成功した
- wheelとsource distributionのmetadata、同梱ファイル、インストール結果を確認した
- remote owner、操作アカウント、実効commit名義は`nexus-ai-2045`で一致した
- 公開後にvisibility、tag、Release、添付物のSHA-256を読み戻した
- GitHub Secret ScanningとPush Protectionを有効化した

## 方針決定済み

- MIT Licenseで公開する
- 配布はGitHub Releaseだけを使い、PyPIへは送信しない

## 公開時に完了した人間判断

- `nexus-ai-2045/ai-ratchet-gate`をMIT Licenseでpublic化する
- 配布名を`ai-ratchet-gate`、初回versionを`v0.1.0`とする
- GitHub Releaseだけで配布し、PyPIへは送信しない
- public化、tag push、GitHub Release公開をそれぞれ人間レビューする

## 公開時に完了した機械検査

- 最終HEADでテスト、ビルド、インストール、CLI smoke testが成功した
- 最終HEADのtreeと全commit履歴をsecret・個人pathについて再検査した
- README、LICENSE、SECURITY.md、PREFLIGHT.mdとパッケージmetadataの整合性を確認した
- dependency advisoryとGitHub Actionsの権限を確認した
- GitHub上のCI、review、visibility、default branch、Release、tagの状態を読み戻した

## 今後の公開操作の停止線

今後のRelease、tag、告知、配布先追加、visibility変更は、公開対象、正確な操作、検査結果を
提示し、このリポジトリ固有の明示承認を得てから実行します。
