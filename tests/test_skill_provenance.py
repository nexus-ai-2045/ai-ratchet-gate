from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from ai_ratchet_gate.adapters import ScanContext, SkillProvenanceAdapter
from ai_ratchet_gate.cli import main
from ai_ratchet_gate.engine import evaluate
from ai_ratchet_gate.model import RatchetError


def _sanitized_git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _init_repo(path: Path) -> dict[str, str]:
    env = _sanitized_git_env()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env=env)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path, check=True, env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=path, check=True, env=env,
    )
    return env


def _write_skill(
    repo: Path,
    skill_id: str,
    *,
    name: str | None = None,
    description: str = "demo skill",
    allowed_tools: str | None = "Read",
    extra_body: str = "# body\n",
    frontmatter: str | None = None,
) -> Path:
    skill_dir = repo / "skills" / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    if frontmatter is not None:
        text = frontmatter
    else:
        skill_name = name or skill_id
        tools_line = (
            f"allowed-tools: {allowed_tools}\n" if allowed_tools is not None else ""
        )
        text = (
            f"---\nname: {skill_name}\ndescription: {description}\n"
            f"{tools_line}---\n{extra_body}"
        )
    path = skill_dir / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


def _track(repo: Path, env: dict[str, str], *rels: str) -> None:
    subprocess.run(
        ["git", "add", "--", *rels],
        cwd=repo, check=True, env=env,
    )


def test_new_skill_is_denied_against_empty_baseline(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _write_skill(tmp_path, "alpha", allowed_tools="Read")
    _track(tmp_path, env, "skills/alpha/SKILL.md")

    observation = SkillProvenanceAdapter(skills_root="skills").observe(
        ScanContext(tmp_path, "repo:skills@head")
    )
    decision = evaluate(observation, [], mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert {item.rule_id for item in observation.findings} >= {
        "skill_present", "skill_digest", "skill_capability",
    }


def test_digest_change_is_denied(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    skill = _write_skill(tmp_path, "alpha", allowed_tools="Read")
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    adapter = SkillProvenanceAdapter(skills_root="skills")
    first = adapter.observe(ScanContext(tmp_path, "repo:skills@head"))
    baseline = [item.finding_id for item in first.findings]

    skill.write_text(
        skill.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8"
    )
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    second = adapter.observe(ScanContext(tmp_path, "repo:skills@head"))
    decision = evaluate(second, baseline, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    assert any(item.rule_id == "skill_digest" for item in second.findings)
    new_rules = {
        item.rule_id
        for item in second.findings
        if item.finding_id in decision.new
    }
    assert "skill_digest" in new_rules


def test_permission_expansion_is_denied(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    skill = _write_skill(tmp_path, "alpha", allowed_tools="Read")
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    adapter = SkillProvenanceAdapter(skills_root="skills")
    first = adapter.observe(ScanContext(tmp_path, "repo:skills@head"))
    baseline = [item.finding_id for item in first.findings]

    skill.write_text(
        "---\nname: alpha\ndescription: demo skill\n"
        "allowed-tools: Read Bash(git:*)\n---\n# body\n",
        encoding="utf-8",
    )
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    second = adapter.observe(ScanContext(tmp_path, "repo:skills@head"))
    decision = evaluate(second, baseline, mode="ratchet", policy="new_only")
    assert decision.status == "deny"
    new_caps = [
        item for item in second.findings
        if item.finding_id in decision.new and item.rule_id == "skill_capability"
    ]
    assert new_caps


def test_grandfathered_baseline_allows(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _write_skill(tmp_path, "alpha", allowed_tools="Read Write")
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    adapter = SkillProvenanceAdapter(skills_root="skills")
    observation = adapter.observe(ScanContext(tmp_path, "repo:skills@head"))
    baseline = [item.finding_id for item in observation.findings]
    decision = evaluate(observation, baseline, mode="ratchet", policy="new_only")
    assert decision.status == "allow"
    assert decision.new == ()


def test_malformed_skill_md_fails_closed(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _write_skill(
        tmp_path,
        "broken",
        frontmatter="---\ndescription: missing name\n---\n# body\n",
    )
    _track(tmp_path, env, "skills/broken/SKILL.md")
    with pytest.raises(RatchetError, match="invalid_skill_"):
        SkillProvenanceAdapter(skills_root="skills").observe(
            ScanContext(tmp_path, "repo:skills@head")
        )


def test_missing_frontmatter_fails_closed(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    skill_dir = tmp_path / "skills" / "raw"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# no frontmatter\n", encoding="utf-8")
    _track(tmp_path, env, "skills/raw/SKILL.md")
    with pytest.raises(RatchetError, match="invalid_skill_frontmatter"):
        SkillProvenanceAdapter(skills_root="skills").observe(
            ScanContext(tmp_path, "repo:skills@head")
        )


def test_adapter_disables_repo_fsmonitor_hook(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _write_skill(tmp_path, "alpha", allowed_tools="Read")
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    hook = tmp_path / "fsmonitor-hook.sh"
    marker = tmp_path / "fsmonitor-ran"
    hook.write_text(
        "#!/bin/sh\necho ran > \"$(dirname \"$0\")/fsmonitor-ran\"\nexit 1\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    subprocess.run(
        ["git", "config", "core.fsmonitor", str(hook)],
        cwd=tmp_path, check=True, env=env,
    )
    observation = SkillProvenanceAdapter(skills_root="skills").observe(
        ScanContext(tmp_path, "repo:skills@head")
    )
    assert any(item.rule_id == "skill_present" for item in observation.findings)
    assert not marker.exists()


def test_adapter_ignores_parent_git_env(tmp_path: Path, monkeypatch) -> None:
    env = _init_repo(tmp_path)
    _write_skill(tmp_path, "alpha", allowed_tools="Read")
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "does-not-exist"))
    observation = SkillProvenanceAdapter(skills_root="skills").observe(
        ScanContext(tmp_path, "repo:skills@head")
    )
    assert observation.adapter_id == "skill.provenance"


def test_skills_root_missing_fails_closed(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    with pytest.raises(RatchetError, match="skills_root_missing"):
        SkillProvenanceAdapter(skills_root="skills").observe(
            ScanContext(tmp_path, "repo:skills@head")
        )


def test_observe_cli_skill_provenance_feeds_evaluate(
    tmp_path: Path, capsys
) -> None:
    env = _init_repo(tmp_path)
    _write_skill(tmp_path, "alpha", allowed_tools="Read")
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    out = tmp_path.parent / "skill-observation.json"
    assert main([
        "observe",
        "--repo", str(tmp_path),
        "--subject", "repo:skills@head",
        "--adapter", "skill.provenance",
        "--skills-root", "skills",
        "--out", str(out),
    ]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["adapter_id"] == "skill.provenance"
    assert payload["schema"] == "ai-ratchet-gate.observation/v1"

    baseline = tmp_path.parent / "skill-baseline.json"
    baseline.write_text(
        json.dumps({
            "schema": "ai-ratchet-gate.baseline/v1",
            "adapter_id": "skill.provenance",
            "adapter_version": "1",
            "subject": "repo:skills@head",
            "policy": "new_only",
            "finding_ids": [item["finding_id"] for item in payload["findings"]],
        }),
        encoding="utf-8",
    )
    assert main([
        "evaluate",
        "--observation", str(out),
        "--baseline", str(baseline),
        "--expected-subject", "repo:skills@head",
    ]) == 0
    assert "allow" in capsys.readouterr().out


def test_observe_cli_requires_skills_root_for_skill_adapter(
    tmp_path: Path, capsys
) -> None:
    code = main([
        "observe",
        "--repo", str(tmp_path),
        "--subject", "repo:x",
        "--adapter", "skill.provenance",
    ])
    assert code == 2
    assert "skills_root_required" in capsys.readouterr().out


def test_list_form_allowed_tools_parsed(tmp_path: Path) -> None:
    env = _init_repo(tmp_path)
    _write_skill(
        tmp_path,
        "alpha",
        frontmatter=(
            "---\nname: alpha\ndescription: demo\nallowed-tools:\n"
            "  - Read\n  - Write\n---\n# body\n"
        ),
    )
    _track(tmp_path, env, "skills/alpha/SKILL.md")
    observation = SkillProvenanceAdapter(skills_root="skills").observe(
        ScanContext(tmp_path, "repo:skills@head")
    )
    caps = [
        item for item in observation.findings if item.rule_id == "skill_capability"
    ]
    assert len(caps) == 2


def test_adapter_maps_timeout_to_ratchet_error(tmp_path: Path, monkeypatch) -> None:
    from ai_ratchet_gate.adapters import skill_provenance as module

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(module.subprocess, "run", _raise_timeout)
    (tmp_path / "skills").mkdir()
    with pytest.raises(RatchetError, match="adapter_observation_timeout"):
        SkillProvenanceAdapter(skills_root="skills").observe(
            ScanContext(tmp_path, "repo:skills@head")
        )
