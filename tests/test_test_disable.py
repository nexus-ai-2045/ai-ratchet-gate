"""test.disable adapter の決定論的観測と脅威モデル回帰。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_ratchet_gate.adapters import (
    ScanContext,
    TestDisableAdapter,
)
from ai_ratchet_gate.cli import main
from ai_ratchet_gate.engine import evaluate
from ai_ratchet_gate.model import Finding, Observation, RatchetError
from ai_ratchet_gate.waiver import (
    WaiverDocument,
    observation_digest,
    review_binding_sha256,
    select_waived_finding_ids,
)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _by_rule(observation: Observation, rule_id: str) -> list[Finding]:
    return [item for item in observation.findings if item.rule_id == rule_id]


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_python_unconditional_skip_finding(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_skip.py",
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_muted():\n"
        "    assert 1 == 1\n"
        "\n"
        "@pytest.mark.skip(reason='temporarily disabled')\n"
        "def test_reason_is_not_permit():\n"
        "    assert True\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    skips = _by_rule(observation, "unconditional_skip")
    assert {item.subject_key for item in skips} == {
        "tests/test_skip.py::test_muted",
        "tests/test_skip.py::test_reason_is_not_permit",
    }
    assert all(item.subject_kind == "test_case" for item in skips)


def test_python_skipif_is_not_c1(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_skipif.py",
        "import sys\n"
        "import pytest\n"
        "\n"
        "@pytest.mark.skipif(sys.platform != 'darwin', reason='mac only')\n"
        "def test_platform():\n"
        "    assert True\n"
        "\n"
        "@pytest.mark.skipif(True, reason='always')\n"
        "def test_skipif_empty():\n"
        "    pass\n"
        "\n"
        "def test_real():\n"
        "    assert 1 + 1 == 2\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    assert _by_rule(observation, "unconditional_skip") == []
    # skipif は C3 hollow にもしない（実行されない可能性がある）
    assert _by_rule(observation, "hollow_test") == []


def test_python_pytest_skip_call_is_c1_not_hollow(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_runtime_skip.py",
        "import pytest\n"
        "\n"
        "def test_runtime_skip():\n"
        "    pytest.skip('not implemented: #456')\n"
        "\n"
        "def test_skip_then_assert():\n"
        "    pytest.skip('muted')\n"
        "    assert True\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    skips = _by_rule(observation, "unconditional_skip")
    assert {item.subject_key for item in skips} == {
        "tests/test_runtime_skip.py::test_runtime_skip",
        "tests/test_runtime_skip.py::test_skip_then_assert",
    }
    assert _by_rule(observation, "hollow_test") == []


def test_python_hollow_assert_true(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_hollow.py",
        "def test_empty():\n"
        "    pass\n"
        "\n"
        "def test_assert_true():\n"
        "    assert True\n"
        "\n"
        "def test_real():\n"
        "    assert 2 + 2 == 4\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    hollow = _by_rule(observation, "hollow_test")
    assert {item.subject_key for item in hollow} == {
        "tests/test_hollow.py::test_empty",
        "tests/test_hollow.py::test_assert_true",
    }


def test_python_unittest_skip_decorator(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_unittest_skip.py",
        "import unittest\n"
        "\n"
        "@unittest.skip('muted')\n"
        "class TestMuted(unittest.TestCase):\n"
        "    def test_a(self):\n"
        "        self.assertEqual(1, 1)\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    skips = _by_rule(observation, "unconditional_skip")
    assert any(
        item.subject_key == "tests/test_unittest_skip.py::TestMuted"
        for item in skips
    )


def test_js_skip_only_hollow_and_todo(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/app.test.ts",
        "test.skip('muted', () => {\n"
        "  expect(1).toBe(1);\n"
        "});\n"
        "\n"
        "it.only('focused', () => {\n"
        "  expect(1).toBe(1);\n"
        "});\n"
        "\n"
        "fit('also focused', () => {\n"
        "  expect(1).toBe(1);\n"
        "});\n"
        "\n"
        "test('hollow', () => {\n"
        "  expect(true).toBe(true);\n"
        "});\n"
        "\n"
        "test.todo('not implemented yet');\n"
        "\n"
        "test('real', () => {\n"
        "  expect(1 + 1).toBe(2);\n"
        "});\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    assert {item.subject_key for item in _by_rule(observation, "unconditional_skip")} == {
        "src/app.test.ts::muted",
    }
    assert {item.subject_key for item in _by_rule(observation, "focused_only")} == {
        "src/app.test.ts::focused",
        "src/app.test.ts::also focused",
    }
    assert {item.subject_key for item in _by_rule(observation, "hollow_test")} == {
        "src/app.test.ts::hollow",
    }
    # test.todo は hollow でも skip でもない
    assert not any(
        "not implemented yet" in item.subject_key for item in observation.findings
    )


def test_js_xit_xdescribe_fdescribe(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "spec/x.spec.js",
        "xit('legacy skip', () => {});\n"
        "xdescribe('legacy suite', () => {});\n"
        "fdescribe('focused suite', () => {\n"
        "  it('nested', () => { expect(1).toBe(1); });\n"
        "});\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    skips = {item.subject_key for item in _by_rule(observation, "unconditional_skip")}
    onlys = {item.subject_key for item in _by_rule(observation, "focused_only")}
    assert "spec/x.spec.js::legacy skip" in skips
    assert "spec/x.spec.js::legacy suite" in skips
    assert "spec/x.spec.js::focused suite" in onlys


def test_grandfathered_skip_allows_under_ratchet(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_known.py",
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_old():\n"
        "    assert 1 == 1\n",
    )
    adapter = TestDisableAdapter()
    observation = adapter.observe(ScanContext(tmp_path, "repo:tests@1"))
    baseline_ids = [item.finding_id for item in observation.findings]
    decision = evaluate(observation, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "allow"

    _write(
        tmp_path,
        "tests/test_known.py",
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_old():\n"
        "    assert 1 == 1\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_new():\n"
        "    assert 1 == 1\n",
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:tests@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert any(
        item.rule_id == "unconditional_skip"
        and item.subject_key.endswith("::test_new")
        and item.finding_id in decision.new
        for item in current.findings
    )


def test_focused_only_uses_existing_strict_mode(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/focus.test.js",
        "test.only('focused', () => { expect(1).toBe(1); });\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    only = _by_rule(observation, "focused_only")
    assert len(only) == 1
    # 新契約ではなく既存 strict（1件でも deny）
    decision = evaluate(observation, [], mode="strict", policy="new_only")
    assert decision.status == "deny"
    # ratchet でも baseline 外なら deny（grandfather しない運用を推奨）
    ratchet = evaluate(observation, [], mode="ratchet", policy="new_only")
    assert ratchet.status == "deny"


def test_waiver_can_except_skip_without_new_schema(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_waiver.py",
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_flaky():\n"
        "    assert 1 == 1\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    finding = _by_rule(observation, "unconditional_skip")[0]
    digest = observation_digest(observation)
    expires_at = "2099-01-01T00:00:00Z"
    record = {
        "waiver_id": "w1",
        "finding_id": finding.finding_id,
        "observation_sha256": digest,
        "expires_at": expires_at,
        "review_binding_sha256": review_binding_sha256(
            adapter_id=observation.adapter_id,
            adapter_version=observation.adapter_version,
            subject=observation.subject,
            waiver_id="w1",
            finding_id=finding.finding_id,
            expires_at=expires_at,
            observation_sha256=digest,
        ),
    }
    document = WaiverDocument.from_dict(
        {
            "schema": "ai-ratchet-gate.waivers/v1",
            "adapter_id": observation.adapter_id,
            "adapter_version": observation.adapter_version,
            "subject": observation.subject,
            "waivers": [record],
        }
    )
    waived = select_waived_finding_ids(document, observation, now=NOW)
    decision = evaluate(
        observation,
        [],
        mode="ratchet",
        policy="new_only",
        waived_finding_ids=waived,
    )
    assert decision.status == "allow"
    assert finding.finding_id in decision.waived


def test_symlink_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    _write(real, "test_ok.py", "def test_ok():\n    assert 1 == 1\n")
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(RatchetError, match="test_symlink_rejected"):
        TestDisableAdapter().observe(ScanContext(link, "repo:tests@1"))


def test_symlink_file_inside_tree_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_real.py", "def test_ok():\n    assert 1 == 1\n")
    target = tmp_path / "outside.py"
    target.write_text("def test_x():\n    pass\n", encoding="utf-8")
    link = tmp_path / "tests" / "test_linked.py"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(RatchetError, match="test_symlink_rejected"):
        TestDisableAdapter().observe(ScanContext(tmp_path, "repo:tests@1"))


def test_non_utf8_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "tests" / "test_bin.py"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"def test_x():\n    assert True\n" + b"\xff\xfe")
    with pytest.raises(RatchetError, match="test_non_utf8"):
        TestDisableAdapter().observe(ScanContext(tmp_path, "repo:tests@1"))


def test_python_syntax_error_fails_closed(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_bad.py", "def test_x(\n")
    with pytest.raises(RatchetError, match="test_python_parse_failed"):
        TestDisableAdapter().observe(ScanContext(tmp_path, "repo:tests@1"))


def test_js_ambiguous_body_fails_closed(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/amb.test.js",
        "test('unclosed', () => {\n  expect(true).toBe(true);\n",
    )
    with pytest.raises(RatchetError, match="test_js_parse_ambiguous"):
        TestDisableAdapter().observe(ScanContext(tmp_path, "repo:tests@1"))


def test_subject_key_nfc_stable(tmp_path: Path) -> None:
    # NFC composed vs NFD decomposed in filename handled via path NFC
    _write(
        tmp_path,
        "tests/test_nfc.py",
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_cafe():\n"
        "    assert 1 == 1\n",
    )
    first = TestDisableAdapter().observe(ScanContext(tmp_path, "repo:tests@1"))
    second = TestDisableAdapter().observe(ScanContext(tmp_path, "repo:tests@1"))
    assert [item.finding_id for item in first.findings] == [
        item.finding_id for item in second.findings
    ]
    assert first.findings[0].subject_key == "tests/test_nfc.py::test_cafe"


def test_skips_node_modules_and_venv(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "node_modules/pkg/x.test.js",
        "test.skip('hidden', () => {});",
    )
    _write(
        tmp_path,
        ".venv/lib/test_hidden.py",
        "import pytest\n@pytest.mark.skip\ndef test_hidden():\n    pass\n",
    )
    _write(
        tmp_path,
        "tests/test_visible.py",
        "def test_ok():\n    assert 1 == 1\n",
    )
    observation = TestDisableAdapter().observe(
        ScanContext(tmp_path, "repo:tests@1")
    )
    assert observation.findings == ()


def test_observe_cli_test_disable_feeds_evaluate(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(
        repo,
        "tests/test_cli.py",
        "import pytest\n"
        "\n"
        "@pytest.mark.skip\n"
        "def test_muted():\n"
        "    assert 1 == 1\n",
    )
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "test.disable",
            "--subject",
            "repo:cli@head",
            "--out",
            str(observation),
        ]
    ) == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    assert payload["adapter_id"] == "test.disable"
    assert payload["findings"]
    assert all(item["subject_kind"] == "test_case" for item in payload["findings"])
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "test.disable",
                "adapter_version": "1",
                "subject": "repo:cli@head",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    assert main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--expected-subject",
            "repo:cli@head",
        ]
    ) == 1


def test_observe_cli_default_adapter_remains_git(tmp_path: Path) -> None:
    import os
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True)
    (repo / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (repo / "generated.txt").write_text("x", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".gitignore", "generated.txt"],
        cwd=repo,
        env=env,
        check=True,
    )
    observation = tmp_path / "observation.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--subject",
            "repo:x@head",
            "--out",
            str(observation),
        ]
    ) == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    assert payload["adapter_id"] == "git.tracked_ignored"


def test_baseline_from_other_adapter_cannot_mask(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(
        repo,
        "tests/test_cross.py",
        "import pytest\n@pytest.mark.skip\ndef test_x():\n    pass\n",
    )
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "test.disable",
            "--subject",
            "repo:cross@head",
            "--out",
            str(observation),
        ]
    ) == 0
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "git.tracked_ignored",
                "adapter_version": "1",
                "subject": "repo:cross@head",
                "policy": "new_only",
                "finding_ids": [],
            }
        ),
        encoding="utf-8",
    )
    capsys.readouterr()
    code = main(
        [
            "evaluate",
            "--observation",
            str(observation),
            "--baseline",
            str(baseline),
            "--expected-subject",
            "repo:cross@head",
        ]
    )
    assert code == 2
    assert "baseline_identity_mismatch" in capsys.readouterr().out


def test_hollow_improvement_resolves(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_improve.py",
        "def test_stub():\n    assert True\n",
    )
    adapter = TestDisableAdapter()
    before = adapter.observe(ScanContext(tmp_path, "repo:tests@1"))
    baseline_ids = [item.finding_id for item in before.findings]
    assert baseline_ids
    _write(
        tmp_path,
        "tests/test_improve.py",
        "def test_stub():\n    assert 2 + 2 == 4\n",
    )
    after = adapter.observe(ScanContext(tmp_path, "repo:tests@1"))
    decision = evaluate(after, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "allow"
    assert decision.resolved == tuple(sorted(baseline_ids))
    assert after.findings == ()
