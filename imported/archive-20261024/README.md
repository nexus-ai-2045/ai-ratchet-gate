# 控えから取り込んだ古い版（2026-10-24）

このフォルダには、履歴を作り直す前の非公開の控えにだけ残っていた中身を、消さずに残すために置いています。

- 置き方: `<控えの枝またはタグ>/<元のパス>`。中身は控えのままです（下の「伏せたもの」を除く）。
- ここにあるファイルは実行も読み込みもされません。テストの収集からも外しています。
- 今のコードへ採り入れるかは、ファイルごとに別のPRで決めます。
- 公開側の履歴に同じ中身があるもの、行がすべて公開側にあるもの、ほかの版で行がそろうものは入れていません。
- 意図して外されていたもの（個人の情報を含む、公開側で削除済みなど）は入れていません。

## 入れたファイル

| 元のパス | 控えの枝・タグ | 置き場所 | 備考 |
|---|---|---|---|
| `.github/workflows/preflight.yml` | `ci/add-preflight-gate` | `ci/add-preflight-gate/.github/workflows/preflight.yml` |  |
| `PREFLIGHT.md` | `ci/add-preflight-gate` | `ci/add-preflight-gate/PREFLIGHT.md` |  |
| `.repo-preflight-consistency.json` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/.repo-preflight-consistency.json` |  |
| `AGENTS.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/AGENTS.md` |  |
| `CHANGELOG.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか1 | `codex/ahead-validate-artifacts-before-remote-release-20261007/CHANGELOG.md` |  |
| `CONTRIBUTING.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/CONTRIBUTING.md` |  |
| `MANIFEST.in` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/MANIFEST.in` |  |
| `OPERATIONS.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/OPERATIONS.md` |  |
| `PUBLIC_READY.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか1 | `codex/ahead-validate-artifacts-before-remote-release-20261007/PUBLIC_READY.md` |  |
| `README.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか1 | `codex/ahead-validate-artifacts-before-remote-release-20261007/README.md` |  |
| `docs/architecture.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/docs/architecture.md` |  |
| `docs/release.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか1 | `codex/ahead-validate-artifacts-before-remote-release-20261007/docs/release.md` |  |
| `docs/threat-model.md` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/docs/threat-model.md` |  |
| `scripts/check_release_artifacts.py` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/scripts/check_release_artifacts.py` |  |
| `src/ai_ratchet_gate/cli.py` | `codex/ahead-validate-artifacts-before-remote-release-20261007` ほか2 | `codex/ahead-validate-artifacts-before-remote-release-20261007/src/ai_ratchet_gate/cli.py` |  |
| `CHANGELOG.md` | `codex/operation-contracts-20260924` | `codex/operation-contracts-20260924/CHANGELOG.md` |  |
| `README.md` | `codex/operation-contracts-20260924` | `codex/operation-contracts-20260924/README.md` |  |
| `docs/adr/ADR-0008-operation-evidence-contracts.md` | `codex/operation-contracts-20260924` | `codex/operation-contracts-20260924/docs/adr/ADR-0008-operation-evidence-contracts.md` |  |
| `docs/adr/README.md` | `codex/operation-contracts-20260924` | `codex/operation-contracts-20260924/docs/adr/README.md` |  |
| `src/ai_ratchet_gate/__init__.py` | `codex/operation-contracts-20260924` | `codex/operation-contracts-20260924/src/ai_ratchet_gate/__init__.py` |  |
| `tests/test_operation_contracts.py` | `codex/operation-contracts-20260924` | `codex/operation-contracts-20260924/tests/test_operation_contracts.py` |  |
| `CHANGELOG.md` | `tags/v0.1.0` | `tags/v0.1.0/CHANGELOG.md` |  |
| `PREFLIGHT.md` | `tags/v0.1.0` | `tags/v0.1.0/PREFLIGHT.md` |  |
| `PUBLIC_READY.md` | `tags/v0.1.0` | `tags/v0.1.0/PUBLIC_READY.md` |  |
| `README.md` | `tags/v0.1.0` | `tags/v0.1.0/README.md` |  |
| `ai_ratchet_gate.py` | `tags/v0.1.0` | `tags/v0.1.0/ai_ratchet_gate.py` |  |
| `docs/release.md` | `tags/v0.1.0` | `tags/v0.1.0/docs/release.md` |  |
| `pyproject.toml` | `tags/v0.1.0` | `tags/v0.1.0/pyproject.toml` |  |
| `src/ai_ratchet_gate/__init__.py` | `tags/v0.1.0` | `tags/v0.1.0/src/ai_ratchet_gate/__init__.py` |  |
| `tests/test_ai_ratchet_gate.py` | `tags/v0.1.0` | `tags/v0.1.0/tests/test_ai_ratchet_gate.py` |  |
| `tests/test_package_metadata.py` | `tags/v0.1.0` | `tags/v0.1.0/tests/test_package_metadata.py` |  |

## 伏せたもの

- なし
