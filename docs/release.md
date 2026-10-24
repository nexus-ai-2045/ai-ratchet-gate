# リリース手順

## 前提

- 対象リポジトリ、公開名義、最終HEAD、CI、reviewが一致している
- README、LICENSE、SECURITY.md、PREFLIGHT.mdを人間が確認している
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

1. `CHANGELOG.md`の先頭に空の`## [Unreleased]`を残し、直後を
   `## [<version>] - YYYY-MM-DD`としてrelease PRを人間レビューする
2. GitHub Actionsの`Release preflight`へversionを入力する。preflightはリポジトリ内のversionと
   CHANGELOGの構文・versionを照合し、read-only権限でテスト、build、artifact検査、hash記録まで
   行う。日付、公開タイミング、tag、Draft、人間承認は判定せず、tagやReleaseも作らない
3. 最終HEAD、preflight結果、CI、reviewが一致していることを再確認する
4. privateの場合だけ、Web全体へ見える内容を提示してpublic化の明示承認を得る。既にpublicなら
   visibility、README、LICENSE、SECURITY.md、履歴をWebから再確認する
5. 署名対象を確認して`v<version>` tagをローカルに作成する。この時点ではpushしない
6. ローカルtagからwheelとsource distributionを再生成し、検査、隔離install、hash照合を行う
7. tag名、commit SHA、draftのtitle、本文、全添付物、hashを提示し、tag push、remote draft作成、
   uploadの明示承認を得る
8. 承認されたtagをpushし、承認された内容でGitHub Releaseをdraft作成して、添付物とhashを読み戻す
9. draftの最終内容を人間レビューし、別の明示承認後に公開する。公開前はREADMEのinstall URLを
   未公開versionへ切り替えない
10. 公開したGitHub Releaseを読み戻し、添付物のhash照合とインストールsmoke testを実施する
11. 公開確認後、必要ならREADMEのinstall URLを新versionへ切り替える差分をローカルで作成する。
   差分を提示し、branch pushと別PR作成の明示承認を得てから外部へ反映する

## 公開後の導入先更新

手順10の公開リリース・対象コミット・添付物ハッシュ・インストール確認の読戻し後、リリース担当が
導入先の担当へ版と検証済み配布物`URL`／`SHA-256`を渡し、導入先担当が採用差分を準備する。
本家の修正マージや未公開ビルドだけでは導入先の固定版を変えない。本家の公開完了と導入先の採用完了は
別に確認し、更新しない対象にも理由と次の採用条件を既存`PR`のレビュー記録へ残す。

導入先では、存在する`CI`の配布物固定版、追跡済みフックの導入案内、フックインストーラの代替導入案内、
運用文書の4入口を同じ`PR`で整合させる。`URL`・版・`SHA-256`と実際の実行経路を照合し、
隔離環境で新しい配布物のインストールと既存`CLI`の互換確認、導入先の既存検査を通してレビューする。
新アダプターの強制適用や基準一覧の拡大は版更新と分け、[運用手順](../OPERATIONS.md)の
人間停止線に従う。外部へのプッシュ／`PR`作成は対象・差分の明示承認後に行う。

`PR`のマージだけでは各端末の導入済みパッケージやフック設定は更新されない。各端末の担当が
既存導入手順でインストール・必要な設定変更・実行経路を確認する別工程として扱い、未確認端末を
反映済みにしない。リリース担当と導入先担当は、公開・固定版採用・端末導入の各結果を既存の
リリース／`PR`記録で照合して閉じる。

## ロールバックと制約

当日公開の判断、tagとDraftの対象SHA・asset hash照合、人間承認、公開実行、公開台帳は、
リポジトリ内preflightの責務ではなく外部のrelease運用で扱います。

GitHub Releaseの削除やtagの付け直しを通常の修正手段にせず、問題がある場合は修正版を新しい
versionで配布して変更履歴を残します。public化後にPRIVATEへ戻しても、既に取得された履歴や
配布物は回収できません。
