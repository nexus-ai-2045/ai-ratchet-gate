# リリース手順

## 前提

- 対象リポジトリ、公開名義、最終HEAD、CI、reviewが一致している
- README、LICENSE、SECURITY.md、PREFLIGHT.md、PUBLIC_READY.mdを人間が確認している
- 最終treeと全commit履歴のsecret・個人path検査が成功している
- privateリポジトリのpublic化、tagのpush、GitHub Releaseの公開を必要に応じて個別に承認している
- PyPIへ送信しない方針が維持されている

## 配布物の検証

release用依存を導入し、wheelとsource distributionを隔離ビルドします。配布物のmetadataと
同梱ファイルを検査し、新しいvenvへ両形式からインストールしてCLIを確認します。

ビルド後は`python scripts/check_release_artifacts.py --dist-dir dist`を実行します。この検査は
外部送信を行わず、名前、version、MIT license、PyPI拒否classifier、必須ファイル、SHA-256を
確認します。

生成物のSHA-256を記録し、GitHub Releaseへ添付するファイルと検証済みファイルが同一で
あることを照合します。`dist`の既存ファイルを再利用せず、最終tagから作り直します。
CIでも実際に配布物をbuildし、`scripts/smoke_install_artifacts.py`がwheelとsdistを別々の
隔離venvへインストールしてCLIを起動します。独自のファイル検査だけを成功根拠にしません。

## 実行順序

1. 最終HEADを再検査し、release commitを人間レビューする
2. privateの場合だけ、Web全体へ見える内容を提示してpublic化の明示承認を得る。既にpublicなら
   visibility、README、LICENSE、SECURITY.md、履歴をWebから再確認する
3. 署名対象を確認して`v<version>` tagを作成し、pushを別承認する
4. 同じtagからwheelとsource distributionを再生成してhashを照合する
5. draftのtitle、本文、全添付物、hashを提示し、remote作成とuploadの明示承認を得る
6. 承認された内容でGitHub Releaseをdraft作成し、添付物とhashを読み戻す
7. draftの最終内容を人間レビューし、別の明示承認後に公開する。公開前はREADMEのinstall URLを
   未公開versionへ切り替えない
8. 公開したGitHub Releaseを読み戻し、添付物のhash照合とインストールsmoke testを実施する
9. 公開確認後、必要ならREADMEのinstall URLを新versionへ切り替える別PRを作成する

## ロールバックと制約

GitHub Releaseの削除やtagの付け直しを通常の修正手段にせず、問題がある場合は修正版を新しい
versionで配布して変更履歴を残します。public化後にPRIVATEへ戻しても、既に取得された履歴や
配布物は回収できません。
