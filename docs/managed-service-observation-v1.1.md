# Managed Service Observation 1.1

Status: proposed contract correction for Issue #55. This adds a versioned
capture path for managed providers whose internal routing is not exposed. It
does not run live qualification or activate production.

## Version dispatch

Managed Service Observation 1.0 remains unchanged. Its `fallback_detected` field
continues to mean the strict claim that the service did not fall back; `null` or
unknown remains invalid.

Observation 1.1 is the explicit opaque-provider path. It uses the existing
Reviewer Configuration 1.1, Qualification 1.1, and Operation Provenance Receipt
1.1. Dispatch is by the exact `observation_version`, with an independently
versioned protected Observation Policy 1.1. A 1.0 observation with a 1.1 policy,
or a 1.1 observation without that policy, fails closed. The observation version
is included in the identity fingerprint, so a qualification cannot silently
switch or downgrade observation semantics.

## Fallback layers

Observation 1.1 has separate fields for the two fallback layers:

| Field | Meaning |
| --- | --- |
| `controller_fallback_performed` | Always `false`. The local controller must invoke the configured requested alias exactly and must not substitute another model or service. A substitution rejects the operation. |
| `provider_fallback_status` | `not_observable`, `reported_false`, or `reported_true`, describing only provider-internal routing evidence actually exposed in the captured trace. |

`reported_true` is rejected. `reported_false` is accepted only when the
protected Observation Policy 1.1 names a JSON Pointer in the raw trace and the
pointer resolves to the literal JSON boolean `false`. If no policy-approved
provider signal is present, the only truthful value is `not_observable`; it is
not evidence that provider fallback did not happen.

## Protected Codex CLI capture

For a ChatGPT-authenticated Codex CLI operation, the controller captures and
protects the following ordinary files before validation:

1. The exact request/context bytes saved before invocation. The same bytes are
   sent on stdin; the controller does not regenerate or normalize them after
   capture.
2. A canonical capture manifest recording the logical principal, operation ID,
   operation timestamps, exact argv, request inventory key/hash, raw response
   inventory key/hash, and `codex --version` evidence key/hash.
3. The exact stdout bytes from the successful `codex exec --json --model
   <requested_alias> -` process, retained as JSONL without parsing/re-encoding.
4. The exact stdout bytes from `codex --version`.
5. The protected Reviewer Configuration/build inventory and the pinned
   Observation Policy 1.1. The controller build SHA in the observation must
   equal the configuration's `implementation_build_sha256`.
6. The parsed Semantic Scope Review artifact, separately protected and hashed
   through the existing qualification operation or receipt binding.

The capture policy pins the argv template and the only JSON Pointer paths that
count as provider-reported metadata. For every configured provider metadata
path, validators read the actual raw JSONL event. A value is copied into the
observation only when the trace contains that value at the configured path;
conflicting or malformed values fail. When the Codex trace exposes no model
revision, provider request ID, service fingerprint, or API version, the
corresponding observation fields remain JSON `null`. A requested alias, local
thread ID, controller operation ID, or CLI version is not substituted for
provider-reported metadata.

For an opaque Codex/ChatGPT route with no provider metadata in the trace, the
policy's five `provider_metadata_json_pointers` arrays and its
`provider_fallback_json_pointers` array are empty. A path may be added only
when a real protected trace shows that provider field at that exact location;
the policy hash then changes and invalidates prior qualification.

`request_sha256` is computed over the exact protected request/context bytes
actually sent to the invocation. `response_sha256` is computed over the exact
raw JSONL stdout bytes from that invocation. The capture manifest must bind both
digests to their protected inventory entries, and the validator recomputes both
from those bytes. Placeholder digests, candidate-created files, missing files,
or byte changes fail closed. The CLI version is likewise checked against its
protected raw output bytes. The observation also binds operation start, request
capture, invocation, response capture, and operation completion timestamps and
the logical principal recorded for that operation.

The protected capture excludes credentials, authorization headers, and
secrets. Stderr is not an identity source; if operationally retained, it must
be sanitized and separately protected. The trace validator requires a
successful Codex JSONL turn and a completed agent message. The operation's
parsed Semantic Scope Review remains a separate artifact with the existing
qualification/receipt SHA binding.

## Identity and qualification

The Observation 1.1 identity projection includes only the provider/service
reference, requested alias, provider-reported model/revision/fingerprint/API
metadata, the protected controller/client build SHA, exact Codex CLI version,
Observation Policy SHA, and `provider_visibility_mode`.
`provider_visibility_mode="provider_internals_opaque"` is explicit in the
projection. Request IDs, operation IDs, timestamps, per-operation request and
response hashes, and raw trace bytes remain operation-bound and are excluded
from stable identity. The resulting fingerprint identifies a
**client-observed managed-service behavior window**; it does not identify
provider-internal deployment, routing, or model weights.

Observation 1.1 is accepted only from protected inventory. Its logical principal
must equal the principal on the operation receipt or qualification operation.
The configured alias, service reference, controller build, and policy hash must
match the current protected configuration. A fresh production observation must
have the same identity projection as the current qualification.

All existing compensation and authority boundaries remain in force: at least
three fresh repetitions; hard-miss and blind holdout rules; case isolation and
truth blindness; separate logical principals and operations for Reviewer A and
the qualification approver; protected TrustContext, roles, and operation
index; 24-hour evidence-derived expiry; O2 qualification revalidation; and
Teacher Review 2.0, Production Authorization 2.0, and rollback controls. Provider
opacity is compensated by short validity and behavioral requalification; it is
never converted into a false assertion that provider fallback was absent.
