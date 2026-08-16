# コントリビューション

このリポジトリはprivate運用です。変更は専用branchで行い、Pull Requestでレビューします。

## 変更手順

1. `main`の最新状態からbranchを作成する。
2. 実装変更には対応するテストを追加する。
3. ユーザー向けの説明、エラー文、運用文書は日本語を既定にする。
4. 次の検証を実行する。

```bash
python -m pytest -q
python ai_ratchet_gate.py --repo .
```

5. repo-preflightでsecret候補、個人path、必須文書、差分整合性を検査する。
6. commit、push、Pull Request、mergeはそれぞれの承認境界を守る。

baselineへ例外を追加する場合は、対象path、例外が必要な理由、通常修復できない理由を
Pull Request本文へ記録してください。`AI_RATCHET_GATE_SKIP=1`を恒久対応にしないでください。
