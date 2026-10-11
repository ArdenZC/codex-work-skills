# RQ-03F-B3-C2 — Fixed Operator Launcher and TrustContext Provider

## Review state and baseline

This is a candidate implementation for Owner review. PR [#61](https://github.com/ArdenZC/codex-work-skills/pull/61) remains OPEN and Draft. The implementation CI was run on exact code HEAD `47d5aa316b6e0e28871a70cd3c84cbb4fe9673e9`; this report update will create a documentation-only follow-up commit in the same PR and trigger fresh CI for that new HEAD. It does not establish Production Trust, adopt a Policy Pin, install the systemd unit, or authorize protected writes. No formal Trust Anchor checkout was modified.

- Trusted starting master: `997217ebc787397bc0262770305f738171e21ccd`.
- B3-C1 code HEAD: `cd63ba95a972cf9b1e1af876ce9b898084612dcd`; PR #60 is merged.
- C1 Hosted Linux run [38080405391](https://github.com/ArdenZC/codex-work-skills/actions/runs/38080405391): SUCCESS, 25/25.
- C1 Template Package run [38080405449](https://github.com/ArdenZC/codex-work-skills/actions/runs/38080405449): SUCCESS, 40 successful and one conditional skip.
- Rechecked post-merge run [38106618370](https://github.com/ArdenZC/codex-work-skills/actions/runs/38106618370): completed SUCCESS, no failed or in-progress jobs.
- Formal Trust Anchor commit remains `eb4a95c618e05c5ad6413137478bc65dbca75ec9`.
- Development branch: `feature/rq03f-b3c2-fixed-operator-launcher`.
- PR #61 is the only PR for this work and remains Draft; code implementation HEAD is `47d5aa316b6e0e28871a70cd3c84cbb4fe9673e9`.
- Current master still equals the trusted starting master `997217ebc787397bc0262770305f738171e21ccd`.

## Existing interface and trust-boundary audit

The implementation reuses the existing `semantic_lifecycle.operator_context(provider)` and `semantic_lifecycle.context()` contract. The latter calls the Provider for every request, refreshes UTC time, reloads Profile and Index through `TrustContext.load()`, and rechecks all Inventory entries. `TrustContext` enforces Profile 1.1, epoch, Controller allowlist, process UID separation, protected Index, role validity and revocation. It does not provide a cross-restart monotonic epoch high-water mark.

`operator_controller_bootstrap.prepare_isolated_runtime(...)` remains the isolation boundary. Its existing CLI switches (`--build-inventory`, `--build-sha256`, `--controller-root`, `--entrypoint`) are internal verifier inputs and are not exposed by the fixed C2 entrypoint. The launcher starts only with `-I -S -B`, takes no arguments, clears/rejects import-affecting or unexpected environment, and uses compile-time `/etc/rq03f/launch-policy.pin.json` and `/etc/rq03f/launch-policy.json` locations.

The first implementation review found that the pre-parser read those files and imported the Policy validator before proving the files' OS ownership and integrity. The fixed launcher now performs a stdlib-only, no-follow read of the independent Pin, Policy and Build Inventory first. It rejects writable or ACL-bearing ancestors, symlinks, hardlinks, replacement during read, noncanonical paths, malformed/duplicate JSON, mismatched hashes and a Candidate-owned Build Inventory before loading the Policy validator. It verifies the validator and executing Launcher against the protected Build Inventory. The full closed-schema validator and C1 Bootstrap then recheck the same bindings before Controller modules are imported.

## C2-A — Closed Launch Policy and independent pin

Two closed, versioned schemas were added:

- `rq03f-operator-launch-policy-1.0` binds source commit, unique Generation ID and final absolute Generation/operation paths; Controller and Runtime roots; Python executable; Build Inventory key/path/SHA; Profile 1.1 SHA/epoch; Index 1.1 initial adoption SHA and append-only current-state rule; five distinct principal/UID/GID identities; Controller allowlist; hashed role-authority references; revocation references; fixed read-only operation; candidate-only Runtime Closure; dependency Inventory; C3 requirement; and disabled service state.
- `rq03f-operator-policy-pin-1.0` binds the exact canonical Policy SHA, policy identity and adoption status. It is read from a distinct compile-time path and checked before policy-selected code is loaded and again on each Provider call.

The Launch Policy and Pin are still candidate artifacts in this repository. Their production value depends on a future independent Owner-controlled provisioning channel for `/etc/rq03f`; a Git commit, Candidate JSON, Profile role, or local test result is not that channel. Current C2 test material uses `candidate_only` and synthetic hashes.

## C2-B — Fixed Launcher and code closure

The fixed entrypoint rejects all command-line arguments, untrusted Python environment, non-`-I -S -B` startup, wrong real/effective UID or GID, supplementary groups, capabilities, inherited descriptors, unsafe trust paths and mismatched Controller identity. It checks the Policy Pin, Build Inventory, Launcher, Policy validator, C2 Provider, C2 schemas, all C1 Bootstrap-required modules/packages/dependency modules, actual loaded origins, Python executable/site-packages, and Runtime Closure.

Execution order is fixed: safe read and hash the independent Pin/Policy/Build Inventory; validate the fixed Launcher and Policy validator hashes; run the closed Policy checks; check OS process identity; run C1's isolated Bootstrap; verify complete module/package/schema closure and actual imports; validate the installed C2 schemas; create the Provider; then perform a read-only preflight. A failure returns a nonzero status and a short structured record containing UTC time, stage, stable error code, UID, Policy/Build digests when available, and `protected_operation_performed=false`. No old Generation, default Policy, or test authority fallback exists.

## C2-C — Provider lifecycle and write denial

The Provider is constructed only by the fixed Launcher. On each call it reloads the external Pin/Policy, exact Profile SHA and epoch, current Index, Build Inventory, dependency Inventory, Runtime Closure, loaded authority references, process identity, Controller allowlist, revocation and role validity. It applies the existing `TrustContext.load()` checks and returns a `TrustContext` subclass suitable for read-only preflight.

`semantic_lifecycle.context()` has no operation-purpose argument. To close that interface gap, C2's returned `ReadOnlyPreflightTrustContext.role()` always raises `C3_ANTI_ROLLBACK_GATE_REQUIRED`; the Provider can verify the Operator's custodian role internally but does not return that authorization to downstream code. Thus a qualification intake or any production role cannot proceed through the C2 context. The separate `AntiRollbackGate` Protocol is only an interface. `require_protected_write()` rejects both a missing Gate and a fake object returning `True`. C2 has no ledger, no default pass, and no protected write implementation.

Index 1.1 can advance only by append during one Provider lifetime, checked against the last verified bytes. A changed startup snapshot requires a new independently pinned adoption. C3 must supply the protected monotonic high-water state and recovery protocol before any cross-restart write authorization can exist.

The Operator's only allowed Profile role is `qualification_corpus_custodian`. Author, Reviewer, Approver, Teacher, PA and Generation permissions are not inferred. No historical author provenance or Intake record is created by this work.

## C2-D — Candidate systemd service

`systemd/rq03f-operator-preflight.service` is a fixed-path candidate unit with no `[Install]` section, `User=Group=rq03f-operator`, no EnvironmentFile or extra arguments, `NoNewPrivileges`, an empty capability bounding set, private temporary/device/IPC namespaces, read-only system and Generation paths, protected home/kernel/process views, AF_UNIX-only networking, closed device policy, a 30-second timeout, and no restart. It clears Python and systemd-injected environment values that the fixed Launcher does not accept. It has no `ReadWritePaths`; C2 preflight is read-only.

The unit is not installed, enabled, started or activated. Its candidate Generation path and service identity require replacement with exact Owner-adopted values and a new review before any separate deployment task.

## Local verification

| Check | Result |
|---|---|
| C2 schema/Policy/Pin/Provider/Launcher/source-copy deterministic tests | 30/30 passed on exact code HEAD. Includes closed fields, canonical path rejection, role least privilege, append-only Index, fake C3 Gate refusal, `ReadOnlyPreflightTrustContext` role refusal, exact Git blob checks, dirfd source copying, and root-owned runtime symlink target verification. |
| C1 infrastructure deterministic tests | 25 run: 24 passed, one real-ACL case skipped locally because it requires the hosted Linux runner. |
| Test-shard manifest | Full root-discovery parity, C2 Linux-only coverage, and JSON listing: 3/3 passed. Current manifest reports 1,037 full-suite tests and 1,040 CI tests; C1 contributes 25 and C2 contributes 30 Linux-only tests. The six Semantic Scope shards remain 13 cases each (78 total), with exact partition coverage retained. |
| Python compile and C1 shell syntax | Passed. |
| Candidate systemd unit in temporary synthetic root | `systemd-analyze --man=no verify --root ...` exit 0. No installation or service start occurred. `--man=no` avoids a local man-db dependency while retaining unit verification. |
| Full local `tests.test_run_test_shards` | 29 passed, one Gradebook worker failure. The worker invokes the unchanged Gradebook validator, which exits 1 with `Named-range template changed protected workbook structure or formatting.` Template SHA expected and actual are identical (`FEA186D65DCE742FC7DD0370FF24C60D8D5A1004BC357D99FC75F22F06B9C28E`); 20 differences show `font.bold` expected `1` and actual `null`. Local runtime reports LibreOfficeDev `26.8.0.0.alpha0` (`2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`), with xlrd 2.0.1. No Gradebook files, template, or test expectations were changed. Fresh exact-HEAD GitHub Template Package CI passed both Windows and macOS Gradebook jobs, so this failure is limited to the local Codex runtime observed here; it is not recorded as a hosted regression. |

`tools/rq03f_c2/hosted_linux_isolation.py` provisions ephemeral real Linux UIDs/GIDs and a synthetic Policy/Profile/Index/Build/Runtime under an Ubuntu GitHub-hosted runner. It requires the GitHub event's exact source commit, verifies the checked-out `HEAD`, enumerates only regular Git blob modes, and validates each securely copied file against its exact Git blob SHA. Its directory-descriptor copier refuses Candidate symlinks, hardlinks, special files, and files/directories changed during copy. The root test process writes evidence only to stdout; the unprivileged workflow shell captures that output, so root never writes to Candidate-controlled `RUNNER_TEMP`.

Exact C2 hosted run [38110424906](https://github.com/ArdenZC/codex-work-skills/actions/runs/38110424906) passed on code HEAD `47d5aa316b6e0e28871a70cd3c84cbb4fe9673e9`. The evidence artifact records real Linux identities: Operator UID/GID 4601; Candidate 4602; Author 4603; Reviewer 4604; Approver 4605. These are temporary synthetic identities, not production principals. The Operator's fixed read-only preflight exited 0 with `protected_operation_performed=false`. Candidate, Author, Reviewer, and Approver were denied protected Profile/Index reads and protected evidence write, unlink, rename, replacement, symlink, and hardlink operations. Candidate-controlled launch arguments, `PYTHONPATH`, `sitecustomize`, candidate-as-Operator identity, extra supplementary groups, unexpected capability bounding set, inherited policy descriptor, Policy/Pin symlink swaps, candidate Build path, wrong Build SHA, epoch/revocation/expiry changes, Index version drift, and Profile/Controller/Runtime drift all failed closed (expected process exit 2). `systemd-analyze verify` exited 0; the unit was not installed, enabled, started, or activated. Evidence explicitly says `authority_status=synthetic_candidate_only`, Runtime Closure authority is `candidate_only_unverified_host_claims`, the C3 AntiRollbackGate is missing, and `production_trust_established=false`.

The run also executes the inherited C1 real-UID regression; exact C1 hosted run [38110424910](https://github.com/ArdenZC/codex-work-skills/actions/runs/38110424910) passed on the same code HEAD. Both runs clean up temporary identities/files. These hosted results prove behavior in disposable test environments only; they do not establish Owner authority, external Operator isolation on a production host, or a durable trust root.

## CI and coverage

No existing required gate or Semantic Scope partition is disabled or relaxed. The new C2 suite is a separate Linux-only module in the full manifest; its explicit platform guard preserves Windows/macOS test discovery. The new workflow runs on the exact PR head, provisions only synthetic disposable identities, runs both C1 and C2 hosted Linux checks, checks cleanup, and uploads a short-retention synthetic artifact. The existing workflow continues to own the Windows/macOS Semantic Scope and Gradebook gates.

- Post-merge baseline CI [38106618370](https://github.com/ArdenZC/codex-work-skills/actions/runs/38106618370): SUCCESS.
- Exact code-HEAD Template Package CI [38110424920](https://github.com/ArdenZC/codex-work-skills/actions/runs/38110424920): SUCCESS on `47d5aa316b6e0e28871a70cd3c84cbb4fe9673e9`; 40 jobs succeeded and one conditional Documentation checks job was skipped. CI Gate succeeded. Windows/macOS Semantic Scope is 12/12; Gradebook is PASS on Windows and macOS. Lesson final acceptance, semantic lifecycle, all render modes, package contracts, release, tooling, Practice WorkOrder, Practice Class, and HTML Courseware jobs passed.
- Exact code-HEAD C2 Hosted Linux [38110424906](https://github.com/ArdenZC/codex-work-skills/actions/runs/38110424906): SUCCESS; exact code-HEAD C1 Hosted Linux [38110424910](https://github.com/ArdenZC/codex-work-skills/actions/runs/38110424910): SUCCESS.
- This report-only commit changes the PR HEAD after these implementation runs. Fresh exact-HEAD C2, C1, and Template Package checks will be triggered and their results will be checked before handoff; until those finish, the new report HEAD is not represented as CI-verified.

## Files changed

- `.github/scripts/run_test_shards.py`
- `.github/workflows/rq03f-b3c2-launcher-provider.yml`
- `RQ03F_B3C2_FIXED_OPERATOR_LAUNCHER.md`
- `systemd/rq03f-operator-preflight.service`
- `tests/test_rq03f_c2_operator_launcher.py`
- `tests/test_run_test_shards.py`
- `tools/rq03f_c2/hosted_linux_isolation.py`
- `教案生成器/lesson-plan-docx-generator/schemas/rq03f-operator-launch-policy-v1.0.schema.json`
- `教案生成器/lesson-plan-docx-generator/schemas/rq03f-operator-policy-pin-v1.0.schema.json`
- `教案生成器/lesson-plan-docx-generator/scripts/rq03f_fixed_operator_launcher.py`
- `教案生成器/lesson-plan-docx-generator/scripts/rq03f_operator_launch_policy.py`
- `教案生成器/lesson-plan-docx-generator/scripts/rq03f_operator_trust_provider.py`

## Remaining prerequisites and limits

1. An independent deployment Owner must provision and protect the external Policy Pin/Policy channel and exact root-owned final Controller, Runtime, schemas and service path. Candidate repository content cannot establish it.
2. C3 still needs an independently protected monotonic epoch/high-water ledger, anti-rollback checks across restart, explicit revocation/recovery semantics, and a reviewed write API that cannot be reached through the read-only C2 context.
3. The hosted runner is disposable test evidence only. It cannot establish a production Operator identity, Owner adoption, deployment authority or a durable trust root.
4. Runtime Closure host claims remain candidate-only. The target OS, Python standard library, shared libraries, dependency lock and final absolute installation paths still require independent Owner pinning and verification.
5. Production Trust remains **NOT ESTABLISHED**. This report authorizes no install, service activation, Intake, Agent A/B, live qualification, RC-02, release, or Lesson Skill 2.4.

The exact next engineering dependency is C3: implement and independently review the protected monotonic epoch/high-water ledger, anti-rollback behavior across restart, revocation/recovery semantics, and a purpose-bound protected-write API; then supply a separate Owner-controlled external Policy Pin/Policy and final absolute installation path. Until those are independently deployed and adopted, formal protected operations remain blocked.
