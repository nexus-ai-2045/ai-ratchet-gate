# リリース手順

## 前提

- 対象リポジトリ、公開名義、最終HEAD、CI、reviewが一致している
- README、LICENSE、SECURITY.md、PREFLIGHT.md、PUBLIC_READY.mdを人間が確認している
- 最終treeと全commit履歴のsecret・個人path検査が成功している
- public化、tag、GitHub Release作成を個別に承認している
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
2. リポジトリのpublic化について、Web全体へ見える内容を提示して明示承認を得る
3. public化後にvisibility、README、LICENSE、履歴をWebから読み戻す
4. 署名対象を確認して`v0.1.0` tagを作成し、pushを別承認する
5. 同じtagからwheelとsource distributionを再生成してhashを照合する
6. GitHub Releaseのtitle、本文、添付物を提示し、作成を別承認する
7. GitHub Releaseを読み戻し、添付物のhash照合とインストールsmoke testを実施する

## ロールバックと制約

GitHub Releaseの削除やtagの付け直しを通常の修正手段にせず、問題がある場合は修正版を新しい
versionで配布して変更履歴を残します。public化後にPRIVATEへ戻しても、既に取得された履歴や
配布物は回収できません。
