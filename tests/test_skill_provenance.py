"""skill.provenance adapter の決定論的観測と脅威モデル回帰。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_ratchet_gate.adapters import (
    DEFAULT_SKILLS_ROOT,
    ScanContext,
    SkillProvenanceAdapter,
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


def _write_skill(
    root: Path,
    name: str,
    *,
    allowed_tools: str | list[str] | None = None,
    scripts: dict[str, str] | None = None,
    frontmatter_extra: str = "",
) -> Path:
    skill_dir = root / DEFAULT_SKILLS_ROOT / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(allowed_tools, list):
        tools_block = "allowed-tools:\n" + "".join(
            f"  - {item}\n" for item in allowed_tools
        )
    elif isinstance(allowed_tools, str):
        tools_block = f"allowed-tools: {allowed_tools}\n"
    else:
        tools_block = ""
    text = (
        "---\n"
        f"name: {name}\n"
        f"description: fixture skill {name}\n"
        f"{tools_block}"
        f"{frontmatter_extra}"
        "---\n"
        f"# {name}\n"
    )
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    if scripts:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        for relative, body in scripts.items():
            path = scripts_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    return skill_dir


def _by_rule(observation: Observation, rule_id: str) -> list[Finding]:
    return [item for item in observation.findings if item.rule_id == rule_id]


def test_grandfathered_skill_allows_under_baseline(tmp_path: Path) -> None:
    _write_skill(tmp_path, "known", allowed_tools="Read", scripts={"run.sh": "echo ok"})
    adapter = SkillProvenanceAdapter()
    observation = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in observation.findings]
    decision = evaluate(observation, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "allow"
    assert decision.new == ()
    assert {item.rule_id for item in observation.findings} == {
        "skill_present",
        "skill_allowed_tool",
        "skill_scripts_digest",
    }


def test_new_skill_is_denied_as_independent_axis(tmp_path: Path) -> None:
    _write_skill(tmp_path, "known", allowed_tools="Read")
    adapter = SkillProvenanceAdapter()
    baseline_obs = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in baseline_obs.findings]

    _write_skill(tmp_path, "brand-new", allowed_tools="Read")
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    new_rules = {
        item.rule_id
        for item in current.findings
        if item.finding_id in decision.new
    }
    assert "skill_present" in new_rules
    assert any(
        item.subject_key == f"{DEFAULT_SKILLS_ROOT}/brand-new"
        for item in _by_rule(current, "skill_present")
    )


def test_allowed_tools_expansion_denies_without_netting_scripts(
    tmp_path: Path,
) -> None:
    _write_skill(
        tmp_path,
        "expand",
        allowed_tools="Read",
        scripts={"a.sh": "echo 1"},
    )
    adapter = SkillProvenanceAdapter()
    baseline_obs = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in baseline_obs.findings]

    _write_skill(
        tmp_path,
        "expand",
        allowed_tools="Read Write",
        scripts={"a.sh": "echo 1"},
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    new_findings = [
        item for item in current.findings if item.finding_id in decision.new
    ]
    assert all(item.rule_id == "skill_allowed_tool" for item in new_findings)
    assert any(item.subject_key.endswith("::Write") for item in new_findings)
    # scripts digest は不変なので resolved にも new にも出ない
    assert not any(item.rule_id == "skill_scripts_digest" for item in new_findings)


def test_scripts_payload_change_denies_without_netting_tools(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "payload",
        allowed_tools=["Read", "Bash(git:*)"],
        scripts={"run.sh": "echo old"},
    )
    adapter = SkillProvenanceAdapter()
    baseline_obs = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    baseline_ids = [item.finding_id for item in baseline_obs.findings]

    _write_skill(
        tmp_path,
        "payload",
        allowed_tools=["Read", "Bash(git:*)"],
        scripts={"run.sh": "echo new"},
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    new_findings = [
        item for item in current.findings if item.finding_id in decision.new
    ]
    assert len(new_findings) == 1
    assert new_findings[0].rule_id == "skill_scripts_digest"
    assert new_findings[0].subject_key.startswith(f"{DEFAULT_SKILLS_ROOT}/payload@")
    # tool 軸は改善も悪化もしていない
    assert not any(item.rule_id == "skill_allowed_tool" for item in new_findings)
    assert decision.resolved  # 旧 digest finding が resolved


def test_axes_do_not_net_out_across_skills(tmp_path: Path) -> None:
    """一方のskillでtoolを減らし、他方でscriptsを改変しても相殺しない。"""
    _write_skill(tmp_path, "left", allowed_tools="Read Write")
    _write_skill(tmp_path, "right", allowed_tools="Read", scripts={"x.sh": "old"})
    adapter = SkillProvenanceAdapter()
    baseline_ids = [
        item.finding_id
        for item in adapter.observe(ScanContext(tmp_path, "repo:skills@1")).findings
    ]

    _write_skill(tmp_path, "left", allowed_tools="Read")  # tool 縮小 = 改善
    _write_skill(tmp_path, "right", allowed_tools="Read", scripts={"x.sh": "new"})
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert any(
        item.rule_id == "skill_scripts_digest" and item.finding_id in decision.new
        for item in current.findings
    )


def test_observation_fails_closed_when_skills_root_missing(tmp_path: Path) -> None:
    adapter = SkillProvenanceAdapter()
    with pytest.raises(RatchetError, match="skills_root_missing"):
        adapter.observe(ScanContext(tmp_path, "repo:skills@1"))


def test_invalid_frontmatter_fails_closed(tmp_path: Path) -> None:
    skill_dir = tmp_path / DEFAULT_SKILLS_ROOT / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
    with pytest.raises(RatchetError, match="skill_frontmatter_missing"):
        SkillProvenanceAdapter().observe(ScanContext(tmp_path, "repo:skills@1"))


def test_path_spoof_skills_root_rejected() -> None:
    with pytest.raises(RatchetError, match="invalid_skills_root"):
        SkillProvenanceAdapter(skills_root="../outside")
    with pytest.raises(RatchetError, match="invalid_skills_root"):
        SkillProvenanceAdapter(skills_root="/abs/skills")


def test_symlink_skill_rejected(tmp_path: Path) -> None:
    real = tmp_path / "outside"
    real.mkdir()
    (real / "SKILL.md").write_text(
        "---\nname: outside\ndescription: x\n---\n", encoding="utf-8"
    )
    skills = tmp_path / DEFAULT_SKILLS_ROOT
    skills.mkdir()
    try:
        (skills / "linked").symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(RatchetError, match="skill_symlink_rejected"):
        SkillProvenanceAdapter().observe(ScanContext(tmp_path, "repo:skills@1"))


def test_subject_key_uses_path_not_declared_name(tmp_path: Path) -> None:
    skill_dir = tmp_path / DEFAULT_SKILLS_ROOT / "path-key"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: declared-other\ndescription: x\nallowed-tools: Read\n---\n",
        encoding="utf-8",
    )
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    present = _by_rule(observation, "skill_present")
    assert present[0].subject_key == f"{DEFAULT_SKILLS_ROOT}/path-key"
    assert "declared-other" not in present[0].subject_key


def test_label_swap_does_not_reuse_finding_identity(tmp_path: Path) -> None:
    """rule_id を差し替えた偽物は別 finding_id になり、baseline を欺けない。"""
    _write_skill(tmp_path, "swap", allowed_tools="Read")
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    present = _by_rule(observation, "skill_present")[0]
    spoofed = Finding.create(
        adapter_id=present.adapter_id,
        adapter_version=present.adapter_version,
        rule_id="skill_allowed_tool",
        subject_kind=present.subject_kind,
        subject_key=present.subject_key,
        message=present.message,
        evidence_sha256=present.evidence_sha256,
    )
    assert spoofed.finding_id != present.finding_id
    decision = evaluate(
        Observation.create(
            observation.adapter_id,
            observation.adapter_version,
            observation.subject,
            [spoofed],
        ),
        [present.finding_id],
        mode="ratchet",
        policy="new_only",
    )
    assert decision.status == "deny"
    assert decision.new == (spoofed.finding_id,)


def test_waiver_on_tool_axis_does_not_cover_scripts_change(tmp_path: Path) -> None:
    _write_skill(
        tmp_path, "bound", allowed_tools="Read", scripts={"a.sh": "old"}
    )
    adapter = SkillProvenanceAdapter()
    baseline_obs = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    tool = _by_rule(baseline_obs, "skill_allowed_tool")[0]

    _write_skill(
        tmp_path,
        "bound",
        allowed_tools="Read Write",
        scripts={"a.sh": "new"},
    )
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    # tool 拡大だけを waiver しても scripts 改変は残る
    expanded_tool = next(
        item
        for item in _by_rule(current, "skill_allowed_tool")
        if item.subject_key.endswith("::Write")
    )
    digest = observation_digest(current)
    record = {
        "waiver_id": "w1",
        "finding_id": expanded_tool.finding_id,
        "observation_sha256": digest,
        "expires_at": "2099-01-01T00:00:00Z",
        "review_binding_sha256": review_binding_sha256(
            adapter_id=current.adapter_id,
            adapter_version=current.adapter_version,
            subject=current.subject,
            waiver_id="w1",
            finding_id=expanded_tool.finding_id,
            expires_at="2099-01-01T00:00:00Z",
            observation_sha256=digest,
        ),
    }
    document = WaiverDocument.from_dict(
        {
            "schema": "ai-ratchet-gate.waivers/v1",
            "adapter_id": current.adapter_id,
            "adapter_version": current.adapter_version,
            "subject": current.subject,
            "waivers": [record],
        }
    )
    waived = select_waived_finding_ids(document, current, now=NOW)
    baseline_ids = [item.finding_id for item in baseline_obs.findings]
    decision = evaluate(
        current, baseline_ids, mode="ratchet", policy="new_only",
        waived_finding_ids=waived,
    )
    assert decision.status == "deny"
    assert expanded_tool.finding_id in decision.waived
    assert any(
        item.rule_id == "skill_scripts_digest" and item.finding_id in decision.new
        for item in current.findings
    )


def test_observe_cli_skill_adapter_feeds_evaluate(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill(repo, "cli-skill", allowed_tools="Read")
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "skill.provenance",
            "--subject",
            "repo:cli@head",
            "--out",
            str(observation),
        ]
    ) == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    assert payload["adapter_id"] == "skill.provenance"
    assert payload["findings"]
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "skill.provenance",
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
    """--adapter 未指定時は git.tracked_ignored のまま（legacy互換）。"""
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
        cwd=repo, env=env, check=True,
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


def test_stable_ids_across_tool_list_syntax(tmp_path: Path) -> None:
    _write_skill(tmp_path, "syntax", allowed_tools="Read Write")
    string_form = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    _write_skill(tmp_path, "syntax", allowed_tools=["Write", "Read"])
    list_form = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@1")
    )
    assert {item.finding_id for item in string_form.findings} == {
        item.finding_id for item in list_form.findings
    }


def test_empty_skills_root_observes_zero_findings(tmp_path: Path) -> None:
    (tmp_path / DEFAULT_SKILLS_ROOT).mkdir()
    observation = SkillProvenanceAdapter().observe(
        ScanContext(tmp_path, "repo:skills@empty")
    )
    assert observation.findings == ()
    assert evaluate(observation, [], mode="ratchet", policy="new_only").status == "allow"


def test_scripts_added_from_absent_tree_denies(tmp_path: Path) -> None:
    _write_skill(tmp_path, "grow", allowed_tools="Read")
    adapter = SkillProvenanceAdapter()
    baseline_ids = [
        item.finding_id
        for item in adapter.observe(ScanContext(tmp_path, "repo:skills@1")).findings
    ]
    _write_skill(tmp_path, "grow", allowed_tools="Read", scripts={"boot.sh": "echo hi"})
    current = adapter.observe(ScanContext(tmp_path, "repo:skills@1"))
    decision = evaluate(current, baseline_ids, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert any(
        item.rule_id == "skill_scripts_digest" and item.finding_id in decision.new
        for item in current.findings
    )


def test_operational_observe_evaluate_receipt_allow(
    tmp_path: Path, capsys
) -> None:
    """運用経路: observe → grandfather baseline → evaluate → receipt allow。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill(
        repo, "ops", allowed_tools="Read", scripts={"run.sh": "echo ops"}
    )
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    receipt = tmp_path / "receipt.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "skill.provenance",
            "--subject",
            "repo:ops@head",
            "--out",
            str(observation),
        ]
    ) == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    baseline.write_text(
        json.dumps(
            {
                "schema": "ai-ratchet-gate.baseline/v1",
                "adapter_id": "skill.provenance",
                "adapter_version": "1",
                "subject": "repo:ops@head",
                "policy": "new_only",
                "finding_ids": [item["finding_id"] for item in payload["findings"]],
            },
            ensure_ascii=False,
            sort_keys=True,
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
            "repo:ops@head",
            "--receipt",
            str(receipt),
        ]
    ) == 0
    decision = json.loads(receipt.read_text(encoding="utf-8"))
    assert decision["decision"]["status"] == "allow"
    assert decision["decision"]["new"] == []
    assert decision["receipt_sha256"]


def test_observe_cli_missing_skills_root_fails_closed(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    code = main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "skill.provenance",
            "--subject",
            "repo:missing@head",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "tool_error"
    assert payload["error"] == "skills_root_missing"


def test_baseline_from_git_adapter_cannot_mask_skill_findings(
    tmp_path: Path, capsys
) -> None:
    """別adapterのbaseline finding IDでは skill 軸を隠せない（identity mismatch）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_skill(repo, "cross", allowed_tools="Read")
    observation = tmp_path / "observation.json"
    baseline = tmp_path / "baseline.json"
    assert main(
        [
            "observe",
            "--repo",
            str(repo),
            "--adapter",
            "skill.provenance",
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
