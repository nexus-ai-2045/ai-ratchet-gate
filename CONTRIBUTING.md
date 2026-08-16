# コントリビューション

公開範囲にかかわらず、変更は専用branchで行い、Pull Requestでレビューします。

## 変更手順

1. `main`の最新状態からbranchを作成する。
2. 実装変更には対応するテストを追加する。
3. ユーザー向けの説明、エラー文、運用文書は日本語を既定にする。
4. 次の検証を実行する。

```bash
python -m pip install -e ".[test]"
python scripts/verify.py
python ai_ratchet_gate.py --repo .
```

`pytest`を直接実行せず、`scripts/verify.py`を標準経路にします。このスクリプトは、選択した
Python自身にtest依存があることを先に検査し、別のPython環境を誤って使った場合は修復コマンドを
表示して停止します。

5. repo-preflightでsecret候補、個人path、必須文書、差分整合性を検査する。
6. commit、push、Pull Request、mergeはそれぞれの承認境界を守る。

## レビュー指摘後の再検証

レビュー指摘を修正した場合は、修正だけで完了扱いにせず、次を1サイクルとして実行します。

1. 指摘を再現する回帰テストを追加し、全テストとratchet検査を実行する。
2. secret候補、個人path、差分整合性を再検査する。
3. 修正をcommit、pushし、remoteのHEAD一致を読み戻す。
4. GitHub Actionsの全対象jobが成功するまで確認する。
5. 最新HEADを明記して自動レビューを再依頼し、旧HEADのコメントと区別して回収する。

このサイクルは最新HEADへの新規指摘がなくなるまで繰り返します。CI成功や自動レビュー完了は
merge承認を兼ねません。merge、公開範囲変更、Release作成は、それぞれ人間確認を残します。

baselineへ例外を追加する場合は、対象path、例外が必要な理由、通常修復できない理由を
Pull Request本文へ記録してください。`AI_RATCHET_GATE_SKIP=1`を恒久対応にしないでください。
