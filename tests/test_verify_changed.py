"""scripts/verify.py --changed：差分に関係するテストだけを選び、決まらなければ全部に戻す。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verify", ROOT / "scripts" / "verify.py")
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)


def test_source_change_selects_tests_that_mention_module():
    tests = verify.related_tests(["src/ai_ratchet_gate/harness.py"])
    assert "tests/test_harness.py" in tests
    assert "tests/test_waiver.py" not in tests


def test_test_change_selects_itself():
    assert verify.related_tests(["tests/test_engine.py"]) == ["tests/test_engine.py"]


def test_shared_or_config_change_falls_back_to_full():
    assert verify.related_tests(["pyproject.toml"]) is None
    assert verify.related_tests(["tests/conftest.py"]) is None
    assert verify.related_tests([".github/workflows/ci.yml"]) is None


def test_unmatched_source_falls_back_to_full():
    unmatched = "scripts/" + "no_test_" + "mentions.py"
    assert verify.related_tests([unmatched]) is None


def test_docs_only_change_runs_no_tests():
    assert verify.related_tests(["README.md"]) == []


def test_default_is_full_mode(monkeypatch):
    called = []
    monkeypatch.setattr(verify, "_preflight", lambda: 0)
    monkeypatch.setattr(verify, "run_full", lambda: called.append("full") or 0)
    monkeypatch.setattr(verify, "run_changed", lambda base: called.append(base) or 0)
    assert verify.main([]) == 0
    assert verify.main(["--changed"]) == 0
    assert called == ["full", "origin/main"]


def test_indirect_consumer_tests_are_selected():
    # engine を cli 経由で使う試験も選ぶ（Codex 指摘の回帰）
    tests = verify.related_tests(["src/ai_ratchet_gate/engine.py"])
    assert "tests/test_generic_cli.py" in tests


def test_log_path_outside_root_is_shown_relative(tmp_path):
    root = tmp_path / "wt"
    log = tmp_path / "main" / ".git" / "worktrees" / "wt" / "verify" / "x.log"
    assert verify.display_path(log, root) == "../main/.git/worktrees/wt/verify/x.log"


def test_log_redacts_home_python_and_root(tmp_path):
    text = f"{Path.home()}/a {verify.sys.executable} {tmp_path}/b"
    out = verify.redact(text, tmp_path)
    assert str(Path.home()) not in out
    assert verify.sys.executable not in out
    assert "<repo>/b" in out
