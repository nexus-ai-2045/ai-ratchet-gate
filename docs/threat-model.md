# 脅威モデル

## 守る対象

- `tracked ∧ ignored` の矛盾を増やさないという不変条件
- baseline変更を差分としてレビューできること
- 検査不能を成功として扱わないこと

## 想定する入力と失敗

- `git add -f`によるignore対象ファイルの強制追加
- 追跡済みファイルへ後から追加されたignoreルール
- 日本語など非ASCII文字を含むパス
- git実行不能、対象パス不正、baseline欠落
- baselineの意図しない拡大やskipの常用

## 対応

- gitのNUL区切り出力を使い、パスの曖昧な分割を避ける
- baselineにない新規パスをdenyする
- git実行失敗とbaseline欠落ではfail-closedにする
- baseline更新とskipを人間レビュー対象として運用文書に残す

## 対象外

- secret、malware、依存関係脆弱性、コード品質全般の検出
- hookを通らないcommit経路の強制阻止
- 悪意ある利用者によるコード、baseline、CI設定そのものの改変
