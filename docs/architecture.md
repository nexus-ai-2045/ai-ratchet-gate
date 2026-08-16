# アーキテクチャ

## 構成

- `src/ai_ratchet_gate/cli.py`: 検査、baseline比較、CLIの正本
- `ai_ratchet_gate.py`: ソースcheckoutからの従来利用を維持する互換ラッパー
- `.ai-ratchet-gate/baseline.txt`: 導入時点で許容した既存矛盾のパス集合
- `scripts/verify.py`: 選択したPythonでテストとCLI smoke testを実行する検証入口
- `tests/`: 列挙、baseline差分、互換ラッパー、CLI動作の回帰テスト

## データの流れ

1. CLIが対象リポジトリでgitの標準コマンドを実行する。
2. Gitで追跡済みかつignore対象のパスを、NUL区切りのUTF-8として受け取る。
3. baselineのパス集合と比較する。
4. 新規パスがなければ成功し、あれば修復案を表示して失敗する。
5. 明示されたbaseline更新時だけ、baselineファイルを書き換える。

## 信頼境界

- 対象リポジトリのgit metadataとignoreルールは検査入力であり、信頼済みとはみなさない。
- 通常検査はread-onlyで、baseline更新だけがファイル書き込みを行う。
- commit hookやCIへの接続は利用側の責務であり、このパッケージ単体では強制できない。
