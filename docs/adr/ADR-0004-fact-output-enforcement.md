# ADR-0004: structured fact-output enforcement point

- Status: Proposed
- Date: 2026-08-29
- Depends on: ADR-0001, ADR-0003

## Context

Agent instructions that say “cite facts” or “mark uncertainty” are useful guidance, but guidance alone is
not a structural guarantee. A runtime can still emit an unlabeled or unsupported claim and present it to a
human before any deterministic check runs.

The repository already separates deterministic observation/decision from model behavior. ADR-0003 adds
verified solution knowledge, but knowledge reuse does not itself guarantee that a user-visible response
passed the expected claim/source contract.

The required primitive is not a new truth system and must not become the canonical vocabulary for any
specific project. Project-specific meanings (for example, which labels exist and which label requires a
source) stay in that project's reviewed policy/SSOT.

## Prior art

This design follows established policy-enforcement and structured-output patterns:

1. produce a machine-readable envelope before presentation,
2. validate against a reviewed schema/policy,
3. fail closed on malformed or ambiguous input,
4. allow rendering only after the enforcement point succeeds.

Provider-native structured output can reduce malformed envelopes, but the deterministic validator remains
necessary because provider capability and runtime integration differ.

## Decision

Add an agent-independent `agent.fact_output` adapter with two inputs:

- `fact-output/v1` document: an ordered set of claims (`key`, `label`, `text`, `source`),
- `fact-output-policy/v1`: allowed labels and per-label source requirement.

The adapter does **not** hard-code label names. Therefore a project can keep its label vocabulary in its
existing canonical SSOT and materialize a small reviewed policy for the runtime.

### Validation boundary

Malformed or ambiguous input is a tool error (exit 2 / `RatchetError`) and fails closed. Examples:

- unknown schema,
- duplicate JSON object key,
- duplicate claim key,
- invalid policy shape,
- oversized or non-regular input.

Well-formed semantic policy violations become normal Findings:

- `fact-output.claim-required`,
- `fact-output.unsupported-label`,
- `fact-output.source-required`,
- `fact-output.source-forbidden`.

The same input yields the same Finding identity.

### Runtime contract

A compliant runtime uses this sequence:

```text
model/tool result
  -> structured claim envelope
  -> fact-output validator
  -> exit 0: render only validated claims
  -> exit 1: hold response, repair/retry/escalate
  -> exit 2: hold response, repair runtime/input path
```

Free-form text that bypasses the envelope is outside the trusted path. A runtime must not append unvalidated
prose after validation and still claim enforcement.

The adapter is read-only with respect to the target project. The optional CLI output is only an Observation
artifact for audit/evaluation.

### Product/runtime boundary

This package can provide the deterministic enforcement primitive but cannot install itself into every
chat product. Each runtime must connect its pre-render/output boundary explicitly. A runtime without such a
hook is `not_enforced`; prompt instructions alone must not be reported as mechanical enforcement.

For API-based runtimes, provider structured-output/schema features may be used to generate the envelope,
but this adapter is the provider-independent verification boundary.

## Canonicalization rule

Project-specific fact semantics remain outside this repository. If an existing project already owns the
fact labels and source semantics, this repository references that contract through a policy artifact rather
than copying the prose into a new SSOT.

The repository owns only:

- the generic envelope schema,
- the generic policy schema,
- deterministic validation behavior,
- the CLI/read-only integration contract.

## MPC / failure forecast

Before rollout, assume these failure modes:

1. **Bypass:** runtime validates JSON then appends free text. Mitigation: render envelope-only.
2. **Policy drift:** runtime embeds stale label rules. Mitigation: pin/digest reviewed policy in the outer
   runtime receipt.
3. **Provider mismatch:** model cannot guarantee schema. Mitigation: validator remains authoritative; retry
   or hold instead of rendering malformed output.
4. **False “enforced” claim:** package is installed but output hook is not connected. Mitigation: runtime
   smoke must intentionally submit an invalid envelope and observe a blocked render path.
5. **SSOT duplication:** project vocabulary is copied into this package. Mitigation: code is vocabulary-free;
   project policy remains external and reviewed.

## Verification / done criteria

Core implementation is complete when:

- valid claims produce zero findings,
- missing/forbidden sources and unsupported labels produce stable findings,
- malformed/duplicate inputs fail closed,
- label vocabulary can change by policy without code change,
- CLI returns 0/1/2 for allow/deny/tool-error,
- CI passes on supported Python/OS matrix.

Operational enforcement for a specific runtime is complete only after that runtime has a pre-render hook and
a negative smoke proves an invalid claim is not shown to the user.

## Non-goals

- deciding whether a source is substantively true,
- inventing project-specific fact labels,
- automatically rewriting user-visible prose,
- installing hooks into third-party chat products,
- treating model self-reported compliance as evidence of enforcement.
