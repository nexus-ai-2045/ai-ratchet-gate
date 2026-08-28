# ADR-0004: structured fact-output enforcement point

- Status: Proposed
- Date: 2026-08-29
- Depends on: ADR-0001, ADR-0003

## Context

Agent instructions that say “cite facts” or “mark uncertainty” are useful guidance, but guidance alone is
not a structural guarantee. A runtime can still emit an unlabeled or unsupported claim and present it to a
human before any deterministic check runs. Requiring a non-empty `source` string is also insufficient: a
model can invent a plausible-looking source identifier.

The repository already separates deterministic observation/decision from model behavior. ADR-0003 adds
verified solution knowledge, but knowledge reuse does not itself guarantee that a user-visible response
passed the expected claim/source contract.

The required primitive is not a new truth system and must not become the canonical vocabulary for any
specific project. Project-specific meanings (for example, which labels exist and which label requires a
source) stay in that project's reviewed policy/SSOT.

## Prior art

This design follows established policy-enforcement and structured-output patterns:

1. produce a machine-readable envelope before presentation,
2. bind references to data supplied by a trusted outer runtime,
3. validate against reviewed schema/policy,
4. fail closed on malformed or ambiguous input,
5. bind the allow result to the exact validated document,
6. allow rendering only after the enforcement point succeeds.

Provider-native structured output can reduce malformed envelopes, but the deterministic validator remains
necessary because provider capability and runtime integration differ.

## Decision

Add an agent-independent `agent.fact_output` adapter with three independent inputs:

- `fact-output/v1` document: model-controlled claims (`key`, `label`, `text`, `source`),
- `fact-output-policy/v1`: reviewed allowed labels and per-label source requirement,
- `fact-evidence/v1`: runtime-controlled source registry (`id`, `evidence_sha256`).

The adapter does **not** hard-code label names. Therefore a project can keep its label vocabulary in its
existing canonical SSOT and materialize a small reviewed policy for the runtime.

A claim source is not trusted merely because it is syntactically present. Every non-forbidden source must
refer to an ID already present in the runtime evidence registry. The model does not get to mint trusted
source IDs. The outer runtime creates the registry from tool/file/command evidence and can pin both policy
and evidence registry with canonical SHA-256 digests in its receipt.

### Validation boundary

Malformed or ambiguous input is a tool error (exit 2 / `RatchetError`) and fails closed. Examples:

- unknown schema,
- duplicate JSON object/claim/source key,
- whitespace-only or over-limit strings,
- invalid policy/evidence shape,
- invalid evidence digest,
- oversized or non-regular input.

Well-formed semantic policy violations become normal Findings:

- `fact-output.claim-required`,
- `fact-output.unsupported-label`,
- `fact-output.source-required`,
- `fact-output.source-forbidden`,
- `fact-output.unknown-source`.

The same semantic violation yields the same Finding identity. Input string limits are aligned with the
common Observation model so an input accepted by this adapter does not fail later merely because a Finding
message or subject exceeds the shared model limit.

### Runtime contract

A compliant runtime uses this sequence:

```text
trusted tools/files/commands -> evidence registry
reviewed project SSOT         -> label policy
model/tool synthesis          -> structured claim envelope
                                  |
                                  v
                         fact-output validator
                         /          |          \
                    exit 0       exit 1       exit 2
                    render        hold         hold
```

Only exit 0 may reach the renderer. Free-form text that bypasses the envelope is outside the trusted path.
A runtime must not append unvalidated prose after validation and still claim enforcement.

The CLI itself is read-only and writes no Observation file. It emits a validation envelope to stdout with
canonical SHA-256 digests for the exact document, policy, and evidence registry used in validation. A
cross-process renderer must verify `document_sha256` against the exact canonical document it will present;
exit 0 alone must not authorize reopening an unbound mutable file. This closes the validate-then-replace
TOCTOU path without adding a new filesystem mutation exception.

### Product/runtime boundary

This package can provide the deterministic enforcement primitive but cannot install itself into every chat
product. Each runtime must connect its pre-render/output boundary explicitly. A runtime without such a hook
is `not_enforced`; prompt instructions alone must not be reported as mechanical enforcement.

For API-based runtimes, provider structured-output/schema features may be used to generate the envelope,
but this adapter is the provider-independent verification boundary.

## Canonicalization rule

Project-specific fact semantics remain outside this repository. If an existing project already owns the
fact labels and source semantics, this repository references that contract through a policy artifact rather
than copying the prose into a new SSOT.

The repository owns only:

- the generic claim envelope schema,
- the generic policy schema,
- the generic trusted evidence registry schema,
- deterministic validation behavior,
- the read-only CLI/integration contract.

## MPC / failure forecast

Before rollout, assume these failure modes:

1. **Bypass:** runtime validates JSON then appends free text. Mitigation: render envelope-only.
2. **Invented citation:** model emits a plausible fake source. Mitigation: source ID must exist in the
   runtime-produced evidence registry.
3. **Validate-then-replace:** a mutable document changes after CLI validation. Mitigation: allow result is
   bound to `document_sha256`; renderer verifies the exact canonical document before presentation.
4. **Policy/evidence drift:** runtime embeds stale inputs. Mitigation: pin canonical policy/evidence digests
   in the outer runtime receipt.
5. **Provider mismatch:** model cannot guarantee schema. Mitigation: validator remains authoritative; retry
   or hold instead of rendering malformed output.
6. **False “enforced” claim:** package is installed but output hook is not connected. Mitigation: runtime
   smoke intentionally submits an invalid envelope and verifies it never reaches rendering.
7. **SSOT duplication:** project vocabulary is copied into this package. Mitigation: code is vocabulary-free;
   project policy remains external and reviewed.

## Verification / done criteria

Core implementation is complete when:

- valid claims bound to registered evidence produce zero findings,
- missing/forbidden/unregistered/blank sources and unsupported labels produce stable fail-closed results,
- malformed/duplicate inputs fail closed,
- label vocabulary can change by policy without code change,
- policy/evidence/document canonical digests are reproducible,
- CLI is read-only and returns 0/1/2 for allow/deny/tool-error,
- CI passes on supported Python/OS matrix and release artifact smoke passes.

Operational enforcement for a specific runtime is complete only after that runtime has a pre-render hook and
a negative smoke proves an invalid, invented-source, or document-mismatch claim is not shown to the user.

## Non-goals

- deciding whether the underlying evidence itself is substantively true,
- inventing project-specific fact labels,
- automatically rewriting user-visible prose,
- installing hooks into third-party chat products,
- treating model self-reported compliance as evidence of enforcement.
