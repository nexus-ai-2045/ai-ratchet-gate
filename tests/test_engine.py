from __future__ import annotations

import json
import os

import pytest

from ai_ratchet_gate.engine import evaluate
from ai_ratchet_gate.model import Finding, Observation, RatchetError
from ai_ratchet_gate.receipt import build_receipt
from ai_ratchet_gate.adapters import ScanContext, TrackedIgnoredAdapter


def finding(subject: str, *, message: str = "説明") -> Finding:
    return Finding.create(
        adapter_id="example.guard",
        adapter_version="1",
        rule_id="no-regression",
        subject_kind="artifact",
        subject_key=subject,
        message=message,
        evidence_sha256="a" * 64,
    )


def test_finding_id_is_stable_across_display_text_changes() -> None:
    assert finding("a", message="old").finding_id == finding(
        "a", message="new"
    ).finding_id
    assert finding("a").finding_id != finding("b").finding_id


def test_ratchet_partitions_findings_and_blocks_only_new() -> None:
    accepted = finding("accepted")
    new = finding("new")
    resolved = finding("resolved")
    decision = evaluate(
        Observation.create("example.guard", "1", "repo:abc", [new, accepted]),
        baseline_ids=[accepted.finding_id, resolved.finding_id],
        mode="ratchet",
        policy="new_only",
    )
    assert decision.status == "deny"
    assert decision.accepted == (accepted.finding_id,)
    assert decision.new == (new.finding_id,)
    assert decision.resolved == (resolved.finding_id,)


def test_exact_baseline_blocks_stale_baseline_but_new_only_allows_it() -> None:
    old = finding("old")
    observation = Observation.create("example.guard", "1", "repo:abc", [])
    assert evaluate(
        observation, [old.finding_id], mode="ratchet", policy="new_only"
    ).status == "allow"
    assert evaluate(
        observation, [old.finding_id], mode="ratchet", policy="exact_baseline"
    ).status == "deny"


def test_duplicate_finding_id_is_rejected() -> None:
    duplicate = finding("same")
    with pytest.raises(RatchetError, match="duplicate_finding_id"):
        Observation.create("example.guard", "1", "repo:abc", [duplicate, duplicate])


def test_receipt_is_canonical_and_order_independent() -> None:
    first, second = finding("a"), finding("b")
    baseline = ["f" * 64]
    one = evaluate(
        Observation.create("example.guard", "1", "repo:abc", [first, second]),
        baseline,
        mode="observe",
    )
    two = evaluate(
        Observation.create("example.guard", "1", "repo:abc", [second, first]),
        baseline,
        mode="observe",
    )
    assert build_receipt(one) == build_receipt(two)
    assert json.loads(build_receipt(one))["receipt_sha256"]


def test_receipt_hash_binds_message_without_echoing_it() -> None:
    secret = "github_pat_" + "R" * 30
    old = evaluate(
        Observation.create("example.guard", "1", "repo:abc", [finding("a", message=secret)]),
        [], mode="observe",
    )
    new = evaluate(
        Observation.create("example.guard", "1", "repo:abc", [finding("a", message="changed")]),
        [], mode="observe",
    )
    assert json.loads(build_receipt(old))["observation_sha256"] != json.loads(
        build_receipt(new)
    )["observation_sha256"]
    assert secret not in build_receipt(old)


@pytest.mark.parametrize("value", ["../secret", "/absolute", "a\x00b"])
def test_subject_key_rejects_ambiguous_or_unsafe_values(value: str) -> None:
    with pytest.raises(RatchetError, match="invalid_subject_key"):
        finding(value)


def test_subject_key_preserves_posix_backslash_filename() -> None:
    assert finding(r"a\b.log").subject_key == r"a\b.log"


def test_unknown_mode_and_policy_fail_closed() -> None:
    observation = Observation.create("example.guard", "1", "repo:abc", [])
    with pytest.raises(RatchetError, match="invalid_mode"):
        evaluate(observation, [], mode="magic")
    with pytest.raises(RatchetError, match="invalid_policy"):
        evaluate(observation, [], mode="ratchet", policy="magic")
    with pytest.raises(RatchetError, match="invalid_baseline_ids"):
        evaluate(observation, ["a" * 64, 1], mode="ratchet")


@pytest.mark.parametrize("policy", [[], {}, 1, None])
def test_malformed_policy_type_fails_closed(policy: object) -> None:
    observation = Observation.create("example.guard", "1", "repo:abc", [])
    with pytest.raises(RatchetError, match="invalid_policy"):
        evaluate(observation, [], mode="ratchet", policy=policy)  # type: ignore[arg-type]


def test_lone_utf16_surrogate_fails_closed() -> None:
    with pytest.raises(RatchetError, match="invalid_message"):
        Finding.create(
            adapter_id="example.guard",
            adapter_version="1",
            rule_id="rule",
            subject_kind="artifact",
            subject_key="a",
            message="\ud800",
            evidence_sha256="a" * 64,
        )


def _sanitized_git_env() -> dict[str, str]:
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git_env["GIT_CONFIG_GLOBAL"] = os.devnull
    git_env["GIT_CONFIG_SYSTEM"] = os.devnull
    return git_env


def test_builtin_git_adapter_produces_stable_findings(tmp_path, monkeypatch) -> None:
    import subprocess

    git_env = _sanitized_git_env()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=git_env)
    (tmp_path / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (tmp_path / "generated.txt").write_text("x", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".gitignore", "generated.txt"],
        cwd=tmp_path, check=True, env=git_env,
    )
    adapter = TrackedIgnoredAdapter()
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "does-not-exist"))
    first = adapter.observe(ScanContext(tmp_path, "repo:test"))
    second = adapter.observe(ScanContext(tmp_path, "repo:test"))
    assert first == second
    assert first.findings[0].subject_key == "generated.txt"


def test_adapter_disables_repo_fsmonitor_hook(tmp_path) -> None:
    import subprocess

    git_env = _sanitized_git_env()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=git_env)
    (tmp_path / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (tmp_path / "generated.txt").write_text("x", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".gitignore", "generated.txt"],
        cwd=tmp_path, check=True, env=git_env,
    )
    hook = tmp_path / "fsmonitor-hook.sh"
    marker = tmp_path / "fsmonitor-ran"
    hook.write_text(
        "#!/bin/sh\necho ran > \"$(dirname \"$0\")/fsmonitor-ran\"\nexit 1\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    subprocess.run(
        ["git", "config", "core.fsmonitor", str(hook)],
        cwd=tmp_path, check=True, env=git_env,
    )
    observation = TrackedIgnoredAdapter().observe(ScanContext(tmp_path, "repo:test"))
    assert observation.findings[0].subject_key == "generated.txt"
    assert not marker.exists()


def test_adapter_ignores_external_excludes_file(tmp_path) -> None:
    import subprocess

    git_env = _sanitized_git_env()
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=git_env)
    (tmp_path / ".gitignore").write_text("generated.txt\n", encoding="utf-8")
    (tmp_path / "generated.txt").write_text("x", encoding="utf-8")
    (tmp_path / "extra.txt").write_text("y", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", ".gitignore", "generated.txt", "extra.txt"],
        cwd=tmp_path, check=True, env=git_env,
    )
    external = tmp_path / "external.excludes"
    external.write_text("extra.txt\n", encoding="utf-8")
    subprocess.run(
        ["git", "config", "core.excludesFile", str(external)],
        cwd=tmp_path, check=True, env=git_env,
    )
    # 外部 excludesFile が効くと extra.txt も tracked∧ignored になるが、
    # adapter は固定空 excludesFile で隔離するため generated.txt のみ。
    with_external = subprocess.run(
        ["git", "-C", str(tmp_path), "ls-files", "-i", "-c", "--exclude-standard", "-z"],
        capture_output=True, check=True, env=git_env,
    )
    assert b"extra.txt" in with_external.stdout
    observation = TrackedIgnoredAdapter().observe(ScanContext(tmp_path, "repo:test"))
    keys = {item.subject_key for item in observation.findings}
    assert keys == {"generated.txt"}
