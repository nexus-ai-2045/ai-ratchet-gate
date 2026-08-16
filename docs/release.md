# リリース手順

## 前提

- 対象リポジトリ、公開名義、最終HEAD、CI、reviewが一致している
- README、LICENSE、SECURITY.md、PREFLIGHT.md、PUBLIC_READY.mdを人間が確認している
- 最終treeと全commit履歴のsecret・個人path検査が成功している
- PyPIのTrusted Publishingを`nexus-ai-2045/ai-ratchet-gate`へ設定している
- public化、tag、GitHub Release、PyPI送信を個別に承認している

## 配布物の検証

release用依存を導入し、wheelとsource distributionを隔離ビルドします。続いてTwineでmetadataと
READMEの表示互換性を検査し、新しいvenvへ両形式からインストールしてCLIを確認します。

生成物のSHA-256を記録し、GitHub Releaseへ添付するファイルとPyPIへ送るファイルが同一で
あることを照合します。`dist`の既存ファイルを再利用せず、最終tagから作り直します。

## 実行順序

1. 最終HEADを再検査し、release commitを人間レビューする
2. リポジトリのpublic化について、Web全体へ見える内容を提示して明示承認を得る
3. public化後にvisibility、README、LICENSE、履歴をWebから読み戻す
4. 署名対象を確認して`v0.1.0` tagを作成し、pushを別承認する
5. 同じtagからwheelとsource distributionを再生成してhashを照合する
6. GitHub Releaseのtitle、本文、添付物を提示し、作成を別承認する
7. PyPIのproject名、version、metadata、配布物hashを提示し、送信を別承認する
8. GitHub ReleaseとPyPIを読み戻し、インストールsmoke testを実施する

## ロールバックと制約

公開済みのPyPI versionは置換できません。問題がある場合はそのversionをyankし、修正版を新しい
versionで配布します。GitHub Releaseの削除やtagの付け直しを通常の修正手段にせず、公開後の
変更履歴を残します。public化後にPRIVATEへ戻しても、既に取得された履歴や配布物は回収できません。
