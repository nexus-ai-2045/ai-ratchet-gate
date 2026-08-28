"""CLI entry point for deterministic fact-output validation.

Usage:
    python -m ai_ratchet_gate.fact_output_cli \
      --document response.json --policy policy.json --evidence evidence.json \
      --subject turn:123

Exit codes:
    0: valid (no findings)
    1: semantic policy findings present; do not render
    2: malformed/ambiguous input or tool failure; fail closed
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from .fact_output import canonical_sha256, observe_fact_output
from .model import RatchetError

MAX_JSON_BYTES = 2 * 1024 * 1024


def _reject_duplicate_object_names(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RatchetError("duplicate_json_object_key")
        result[key] = value
    return result


def _read_json(path: Path) -> object:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RatchetError("json_input_not_regular_file")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(MAX_JSON_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > MAX_JSON_BYTES:
            raise RatchetError("json_input_too_large")
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_object_names,
        )
    except RatchetError:
        raise
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise RatchetError("invalid_json_input") from error


def _paths_alias(left: Path, right: Path) -> bool:
    try:
        if left.exists() and right.exists() and os.path.samefile(left, right):
            return True
    except OSError:
        pass
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, raw_temp = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            os.chmod(temp, target_mode)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _emit_utf8(text: str) -> None:
    encoded = text.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(encoded)
        buffer.flush()
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="structured fact-output envelopeをpolicy/evidenceでfail-closed検査する"
    )
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--subject", required=True)
    parser.add_argument(
        "--out",
        type=Path,
        help="observation JSON出力先。省略時はstdoutへ出力",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        inputs = (args.document, args.policy, args.evidence)
        if args.out is not None and any(_paths_alias(args.out, path) for path in inputs):
            raise RatchetError("output_path_aliases_input")

        document = _read_json(args.document)
        policy = _read_json(args.policy)
        evidence = _read_json(args.evidence)
        observation = observe_fact_output(
            document,
            policy,
            evidence,
            subject=args.subject,
        )
        text = json.dumps(
            observation.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        if len(text.encode("utf-8")) > MAX_JSON_BYTES:
            raise RatchetError("observation_too_large")

        if args.out is not None:
            _atomic_write_text(args.out, text)
            _emit_utf8(
                json.dumps(
                    {
                        "status": "allow" if not observation.findings else "deny",
                        "finding_count": len(observation.findings),
                        "observation": str(args.out),
                        "policy_sha256": canonical_sha256(policy),
                        "evidence_sha256": canonical_sha256(evidence),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
        else:
            _emit_utf8(text)
        return 0 if not observation.findings else 1
    except (RatchetError, OSError) as error:
        _emit_utf8(
            json.dumps(
                {"status": "tool_error", "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
