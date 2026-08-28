"""CLI entry point for deterministic fact-output validation.

Usage:
    python -m ai_ratchet_gate.fact_output_cli \
      --document response.json --policy policy.json --evidence evidence.json \
      --subject turn:123

Exit codes:
    0: valid (no findings)
    1: semantic policy findings present; do not render
    2: malformed/ambiguous input or tool failure; fail closed

The CLI is read-only. It emits a validation receipt-like envelope to stdout. A
renderer must verify `document_sha256` against the exact canonical document it will
present; exit 0 alone must not authorize reopening an unbound mutable file.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from .fact_output import canonical_sha256, observe_fact_output
from .model import RatchetError

MAX_JSON_BYTES = 2 * 1024 * 1024
VALIDATION_SCHEMA = "ai-ratchet-gate.fact-output-validation/v1"


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
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        document = _read_json(args.document)
        policy = _read_json(args.policy)
        evidence = _read_json(args.evidence)
        observation = observe_fact_output(
            document,
            policy,
            evidence,
            subject=args.subject,
        )
        result = {
            "schema": VALIDATION_SCHEMA,
            "status": "allow" if not observation.findings else "deny",
            "document_sha256": canonical_sha256(document),
            "policy_sha256": canonical_sha256(policy),
            "evidence_sha256": canonical_sha256(evidence),
            "observation": observation.to_dict(),
        }
        _emit_utf8(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 0 if not observation.findings else 1
    except (RatchetError, OSError) as error:
        _emit_utf8(
            json.dumps(
                {"schema": VALIDATION_SCHEMA, "status": "tool_error", "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
