# Managed Alias Reviewer Identity Contract 1.0

Status: Issue #52 contract reassessment for Owner review. This design does not
run live qualification, activate Production, change RC-02, or change Lesson 2.4.

## Compatibility map

| Path | Contract | Meaning and validation |
| --- | --- | --- |
| Existing immutable model | Reviewer Configuration 1.0 | Unchanged schema, canonical bytes, fields, validators, and immutable `model_revision` semantics. An agent configuration at 1.0 is the existing immutable-revision mode. |
| Existing human reviewer | Reviewer Configuration 1.0 + Reviewer Qualification 1.0 | Unchanged human procedure/training path. No managed-agent identity is inferred from a human record. |
| Managed service alias | Reviewer Configuration 1.1 | New closed version. `agent_identity_mode` is `managed_alias`; `model_reference` is the exact requested alias; `model_revision` is JSON null. Provider/service, client build, prompt/system/tool/context/decoding policy, fallback prohibition, and observation-policy bytes are bound. |
| Managed service observations | Managed Service Observation 1.0 | A sanitized, per-operation record of the provider/service response metadata. It reports only what the service exposed and never claims that an alias identifies immutable weights. Exact bytes live in the protected evidence inventory. |
| Existing qualification | Reviewer Qualification 1.0 | Unchanged for Configuration 1.0 immutable and human paths. |
| Managed qualification | Reviewer Qualification 1.1 | Required for Configuration 1.1. Retains the existing three-or-more fresh repetitions, complete corpus/holdout coverage, per-case isolation, adjudication, and hard-miss rules. Each operation binds its service observation; all observations must have the same managed-service identity projection. `qualified_at` is derived from the validated protected evidence completion time; qualification validity is at most 24 hours from that time. |
| Existing operation provenance | Operation Provenance Receipt 1.0 | Unchanged for immutable Configuration 1.0 and human paths. |
| Managed operation provenance | Operation Provenance Receipt 1.1 | Required for managed semantic-review operations and managed qualification approvals. It binds the per-operation service observation or the independent approver-evidence record in protected inventory. |
| O2 semantic review and downstream Teacher Review 2.0, Pipeline State 2.0, PA 2.0 | O2 dispatches and validates the managed 1.1 identity chain; downstream teacher, state, and authorization contracts remain unchanged | No lifecycle-state, teacher, PA, rollback, content, template, or acceptance contract changes. O2 accepts only a fully understood, current config/qualification/receipt version combination and fails closed on unknown or mixed versions. |

Reviewer Configuration 1.0 is not extended in place. Configuration 1.1 is the
explicit managed-alias mode; there is no downgrade that converts its null
`model_revision` into a 1.0 revision. A 1.1 configuration, qualification, or
receipt rejected by an older O2 runtime cannot fall back to its 1.0 parser.

Reviewer Qualification 1.0 cannot safely qualify a managed alias: it has no
per-operation service observation bindings and no managed-alias expiry rule.
Qualification 1.1 is therefore the minimum qualification extension needed to
bind the new identity mode. It does not alter Qualification 1.0 semantics.
Operation Provenance Receipt 1.1 is required so a production semantic operation
cannot reuse the qualification-time observation while claiming it describes a
new provider invocation.

## Managed service identity

`managed_alias` means a **managed service behavior window**, not an immutable
model snapshot and not model diversity. The configuration carries the exact
requested alias and provider/service reference. `model_revision` must be null;
copying the alias, client version, deployment label, or request ID into that
field is invalid.

Configuration 1.1 also binds the exact client/harness build, semantic-review
prompt, qualification-approver prompt, system instructions, tool policy,
context policy, decoding settings, and a protected observation-policy file. A
managed request has fallback disabled. If the requested alias is unavailable,
the controller fails closed; it never substitutes another alias or model.

Each actual managed-agent operation has a protected Managed Service Observation
1.0 record binding its operation ID, provider/service reference, requested alias,
any returned model/revision/fingerprint metadata, client build, request and
response hashes, observation-policy hash, and timestamps. Optional provider
metadata remains null when the provider did not report it. Raw credentials,
authorization headers, and secret values are prohibited. The record is hashed
from its exact canonical bytes. Provider-reported metadata is an observation,
not a claim that the weights are immutable.

The qualification controller derives a service-identity fingerprint from the
nonvolatile identity projection (provider/service, requested alias, reported
model metadata, client build, and observation policy). Request IDs, timestamps,
and per-operation request/response hashes are excluded from this projection but
remain bound by each operation receipt. Every qualification observation must
produce the same identity fingerprint. A production semantic operation must
provide a fresh protected observation whose projection equals the currently
approved qualification's fingerprint. Missing, changed, malformed, or
candidate-supplied observations fail closed.

## Expiry and invalidation

For managed-alias Qualification 1.1,
`qualified_at` is a derived evidence-completion timestamp, not artifact
creation time and not approval time. The validator derives it as the maximum
of every validated `qualification_runs[].completed_at` and every protected
adjudication `recorded_at` referenced by a validated golden or holdout result.
An adjudication contributes only after its run/operation/truth bindings,
adjudicator principal, and protected-index capture have been verified. Unused
adjudications and timestamps copied into qualification results do not
contribute. The validator requires exact timestamp equality with this derived
maximum. Delayed serialization, file modification time, current time, and a
new qualification approval cannot refresh older evaluation evidence; a fresh
approver operation over a re-dated qualification still fails this invariant.

The managed-alias maximum is **24 hours from this evidence-derived
`qualified_at`**. `valid_until` may be earlier but never later than
`qualified_at + 24 hours`; authority is invalid at `now == valid_until`. No
automatic extension or grace period exists. A fresh complete qualification
and independent approval are required before first production use and after
expiry.

Any changed config byte, provider/service reference, requested alias, client
build, prompt/system/tool/context/decoding policy, observation policy, or
service-identity fingerprint makes the prior qualification stale or invalid.
Qualification approval revocation, profile pin/epoch changes, role expiry, or
controller revocation continue to invalidate authority under Option B. An
unknown service fallback or changed reported identity is a hard failure.

## Principals and independent operations

Option B remains operator-supplied external process authority. It does not
authenticate a real-world human, and a `principal_id` for a managed agent makes
no human-identity claim. The external operator may authorize two distinct
logical principals, for example `managed-agent:reviewer-a` with
`scope_reviewer` and `managed-agent:qualification-approver-b` with
`qualification_approver`, through separate protected role-authorization records
and the pinned external profile. The protected controller captures their
separate operation IDs and exact evidence.

Both principals may use the same model alias. This is operational independence
through separate operator-granted roles, invocations, fresh contexts, and
protected operation captures; it is **not model diversity**. Reusing a principal
ID, operation ID, invocation, prior reasoning, or reviewer output does not meet
the separation requirement. The qualification approver must inspect the exact
qualification evidence in an independent operation and cannot approve a
qualification by repeating the candidate's disposition. Its protected
qualification-review evidence binds the reviewed evidence set and records that
expected labels, critical truth, holdout truth, adjudication results, and case
identifiers were not exposed to either managed agent. Reviewer A receives only
case-local inputs with prior runs hidden. Reviewer B receives Reviewer A's
complete report evidence in deterministic redacted display form, sorted by
opaque operation reference; raw report hashes and protected receipt/observation
hashes bind each display copy. Corpus case IDs, operation/run names, and artifact
hashes are removed from the display. Those reports are reviewer outputs, not
ground-truth labels. The packet separately exposes the stable per-operation
service-identity projection so Reviewer B can verify consistency; request IDs,
timestamps, and raw service details stay in protected observations. Existing
independent corpus adjudication remains authoritative for truth comparison.

Candidate files cannot select or create principals, role grants, profile pins,
controller IDs, observation records, approval records, or protected index
entries. The existing external `TrustContext`, protected roots, pinned Operator
Authority Profile, and append-only Protected Operation Index remain the only
authority ingress. Candidate-created Reviewer A/B JSON, fake observations,
receipts, or qualifications are ordinary untrusted input and cannot grant
authority.

## Qualification and production invariants

- The exact frozen corpus and blind-holdout truth remain unchanged. Agent
  operations receive only case-local Content, verified sources, outline, and
  frozen configuration; they receive no expected disposition, critical truth,
  holdout truth, adjudication, previous result, or prior reasoning.
- Reviewer Configuration 1.1 carries separate frozen prompt hashes for
  semantic review and qualification-evidence review. Qualification approval
  evidence is bound to the full qualification artifact and complete operation
  evidence set; Reviewer B receives no expected labels, truth, adjudications,
  or case identifiers.
- All current hard misses remain `NOT_QUALIFIED`; no score, vote, or confidence
  threshold can override them. The existing independent corpus adjudicator
  validates critical truth after reviewer output is captured.
- The candidate reviewer, qualification approver, corpus adjudicator, and
  authoring operation retain existing separation rules. In particular, the
  qualification approver principal and operation differ from the candidate
  reviewer and every evaluation author/review operation.
- Configuration 1.0 immutable and human paths remain accepted unchanged.
  Configuration 1.1 is never reinterpreted by a 1.0 validator. Unknown
  configuration, qualification, receipt, or observation versions are rejected.
- No live provider qualification is performed by this contract change. Synthetic
  evidence in tests proves only deterministic contract behavior, not a live
  reviewer qualification or production activation.
