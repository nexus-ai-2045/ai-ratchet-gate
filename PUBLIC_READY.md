<!-- repo-preflight:public-readiness-record -->

# 公開準備レビュー

## 現在の判定

**公開未承認・リリース未実施**です。この文書は公開許可ではありません。

- 対象リポジトリ: `nexus-ai-2045/ai-ratchet-gate`
- 検査起点HEAD: `e9dd81a45086a0244b2f200bfe61ffcd22107717`
- 現在の公開範囲: `PRIVATE`
- 想定公開名義: `nexus-ai-2045`
- 想定初回バージョン: `0.1.0`

この準備文書を含むcommitは、上記HEADの検査結果へ文書を追加する後続commitとして扱います。
public化またはreleaseの直前に、最終HEADを対象として全項目を再検査します。

## 確認済み

- README、SECURITY.md、CONTRIBUTING.md、PREFLIGHT.mdが存在する
- ローカルテストがPython 3.13で14件成功した
- GitHub ActionsがUbuntu・Windows、Python 3.11・3.13で成功した
- 現在treeのsecret候補と個人pathは0件だった
- `tracked ∧ ignored` は現存0件、新規0件だった
- wheelとsource distributionの隔離ビルド、インストール、CLI smoke testが成功した
- Twineによる両配布物のmetadata・README検査が成功した
- 2026-08-16時点でPyPIの`ai-ratchet-gate` JSON APIは404だった。ただし名前は公開まで予約されない
- remote owner、操作アカウント、実効commit名義は`nexus-ai-2045`で一致した
- リポジトリはPRIVATEであり、公開操作は行っていない

## 公開前に人間判断が必要

- オープンソースライセンスを選ぶ。現在のLICENSEはAll Rights Reservedのため、そのまま公開配布しない
- PyPIへ公開するか、GitHub Releaseだけにするか、両方にするかを選ぶ
- `ai-ratchet-gate`という配布名の利用可否と所有権を公開先で確認する
- 公開される全ファイルとcommit履歴を最終目視する
- `Private :: Do Not Upload`を外す最終差分を確認する
- public化、tag、GitHub Release、パッケージ送信をそれぞれ明示承認する

## 公開直前の機械検査

- 最終HEADでテスト、ビルド、インストール、CLI smoke testを成功させる
- 最終HEADのtreeと全commit履歴をsecret・個人pathについて再検査する
- README、LICENSE、SECURITY.md、PREFLIGHT.mdとパッケージmetadataの整合性を確認する
- dependency advisoryとGitHub Actionsの権限を確認する
- GitHub上のCI、review、visibility、default branch、release/tagの状態を読み戻す

## 公開操作の停止線

public化すると、READMEやソースだけでなく、GitHub上のファイルとcommit履歴がWeb全体から
閲覧可能になります。公開対象、正確な操作、最終検査結果を提示し、このリポジトリ固有の
明示承認を得るまでvisibilityを変更しません。
