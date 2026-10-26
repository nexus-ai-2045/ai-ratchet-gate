#!/usr/bin/env python3
"""ci.* adapter（ADR-0009）が使う外の事実を集め、ci-facts/v1 として書き出す。

読むだけ。GitHub へは `git ls-remote`、配布先URLへの HEAD/GET、
（指定したときだけ）`gh api` の secret 名一覧の GET（repository・environment・organization）を使う。書き込みはしない。
secret は名前だけを扱い、値は読まない・書かない（API も値を返さない）。
事実を確かめられないときは成功を報告しない（exit 2）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ai_ratchet_gate.adapters.ci_facts import (
    CI_FACTS_SCHEMA,
    referenced_asset_urls,
    required_secret_names,
)
from ai_ratchet_gate.model import RatchetError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAG_REPOS = ("nexus-ai-2045/repo-preflight", "nexus-ai-2045/ai-ratchet-gate")
HTTP_TIMEOUT_SECONDS = 20
GIT_TIMEOUT_SECONDS = 60


class FactsError(RuntimeError):
    """事実を確かめられない（fail-closed）。"""


def _sanitized_git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def parse_ls_remote_tags(text: str) -> set[str]:
    """`git ls-remote --tags` の出力からタグが指すcommit SHAを返す。

    注釈付きタグは `^{}` の行（指す先）を使い、軽量タグはその行のSHAを使う。
    """
    direct: dict[str, str] = {}
    peeled: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sha, ref = parts[0].strip(), parts[1].strip()
        if not ref.startswith("refs/tags/") or len(sha) != 40:
            continue
        if ref.endswith("^{}"):
            peeled[ref[: -len("^{}")]] = sha
        else:
            direct[ref] = sha
    return {peeled.get(ref, sha) for ref, sha in direct.items()} | set(peeled.values())


def tagged_shas(tag_repos: tuple[str, ...]) -> list[str]:
    shas: set[str] = set()
    for repo in tag_repos:
        try:
            completed = subprocess.run(
                ["git", "ls-remote", "--tags", f"https://github.com/{repo}"],
                capture_output=True,
                text=True,
                check=False,
                env=_sanitized_git_env(),
                timeout=GIT_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise FactsError(f"タグ一覧を取れません: {repo}") from error
        if completed.returncode != 0:
            raise FactsError(f"タグ一覧を取れません: {repo}")
        shas |= parse_ls_remote_tags(completed.stdout)
    return sorted(shas)


def _status(url: str, method: str) -> int:
    request = urllib.request.Request(url, method=method)
    if method == "GET":
        request.add_header("Range", "bytes=0-0")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def asset_is_live(url: str) -> bool:
    """200（GETの範囲指定なら206）で取れれば生きている。404などは死んでいる。

    通信そのものが失敗したときは判定せず FactsError（fail-closed）。
    """
    try:
        status = _status(url, "HEAD")
        if status in {403, 405}:
            status = _status(url, "GET")
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise FactsError(f"配布先を確かめられません: {url}") from error
    return status in {200, 206}


def _gh_lines(path: str, jq: str) -> list[str]:
    """`gh api --paginate <path> --jq <jq>` の出力行。読めなければ FactsError（不明＝止める）。"""
    try:
        completed = subprocess.run(
            ["gh", "api", "--paginate", path, "--jq", jq],
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FactsError("secret の名前一覧を取れません（不明）") from error
    if completed.returncode != 0:
        raise FactsError("secret の名前一覧を取れません（不明）")
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def registered_secret_names_from_gh(repo: str) -> tuple[list[str], dict[str, list[str]]]:
    """repo から使える secret の名前だけを読む（値は API も返さない）。

    返すのは (repository と organization（repo に許可された分）の名前, environment ごとの名前)。
    environment の secret はその environment を指定した job だけが読めるので、和にせず分けて返す。
    owner が organization なのに organization の一覧を読めないなど、どれか一つでも読めない
    ときは「不明」として FactsError にする。少ない一覧で誤って赤にはしない。
    """
    owner_type = _gh_lines(f"repos/{repo}", ".owner.type")
    if owner_type not in (["User"], ["Organization"]):
        raise FactsError("repo の owner 種別を確かめられません（不明）")
    names = set(_gh_lines(f"repos/{repo}/actions/secrets", ".secrets[].name"))
    environments: dict[str, set[str]] = {}
    for environment in _gh_lines(f"repos/{repo}/environments", ".environments[].name"):
        encoded = urllib.parse.quote(environment, safe="")
        environments.setdefault(environment.lower(), set()).update(
            name.upper()
            for name in _gh_lines(
                f"repos/{repo}/environments/{encoded}/secrets", ".secrets[].name"
            )
        )
    if owner_type == ["Organization"]:
        # repo に許可された organization secret だけが返る
        names.update(
            _gh_lines(f"repos/{repo}/actions/organization-secrets", ".secrets[].name")
        )
    return (
        sorted(name.upper() for name in names),
        {env: sorted(values) for env, values in sorted(environments.items())},
    )


def collect(
    repo: Path,
    *,
    tag_repos: tuple[str, ...],
    secrets_repo: str | None,
) -> dict[str, object]:
    facts: dict[str, object] = {"schema": CI_FACTS_SCHEMA}
    facts["tagged_shas"] = tagged_shas(tag_repos)
    facts["live_release_assets"] = sorted(
        url for url in referenced_asset_urls(repo) if asset_is_live(url)
    )
    needed = required_secret_names(repo)
    if secrets_repo is not None:
        registered, environments = registered_secret_names_from_gh(secrets_repo)
        facts["registered_secret_names"] = registered
        facts["environment_secret_names"] = environments
    elif not needed:
        # 要る名前が無いので、一覧を取らなくても判定は変わらない
        facts["registered_secret_names"] = []
    # 要る名前があるのに一覧の出どころが無いときは欄を書かない
    # → ci.secret_declared は ci_facts_missing_registered_secret_names で fail-closed
    return facts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ci.* adapter 用の ci-facts/v1 を集める")
    parser.add_argument("--repo", type=Path, default=ROOT, help="検査対象repo")
    parser.add_argument("--out", type=Path, required=True, help="出力先（検査対象repoの外）")
    parser.add_argument(
        "--tag-repo",
        action="append",
        default=None,
        help=f"タグを読む repo（owner/name、複数可）。既定: {', '.join(DEFAULT_TAG_REPOS)}",
    )
    parser.add_argument(
        "--secrets-from-gh",
        metavar="OWNER/NAME",
        default=None,
        help="gh api で secret の名前一覧を読む repo（名前だけ。値は扱わない）",
    )
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    out = args.out.resolve()
    if out.is_relative_to(repo):
        print("ERROR [ci-facts]: 出力先は検査対象repoの外にしてください", file=sys.stderr)
        return 2
    try:
        facts = collect(
            repo,
            tag_repos=tuple(args.tag_repo or DEFAULT_TAG_REPOS),
            secrets_repo=args.secrets_from_gh,
        )
    except (FactsError, RatchetError) as error:
        print(f"ERROR [ci-facts]: {error}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "==> ci-facts を書き出しました: "
        f"タグSHA {len(facts['tagged_shas'])} 件 / "
        f"生きている配布先 {len(facts['live_release_assets'])} 件 / "
        + (
            f"登録済み secret 名 {len(facts['registered_secret_names'])} 件"
            if "registered_secret_names" in facts
            else "secret 名一覧なし（要る名前あり→ci.secret_declared は止まる）"
        )
        + f" -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
