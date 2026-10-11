# RQ-03F-B3-C3 — Monotonic Trust Ledger, Anti-Rollback & Recovery Foundation

## Delivery status

- Starting trusted master: `b894077fb5967a9aed8713892f448acfa5b65b62`.
- Starting C2 post-merge run [38114284561](https://github.com/ArdenZC/codex-work-skills/actions/runs/38114284561): `SUCCESS` at the starting master SHA.
- C1 Hosted [38112567308](https://github.com/ArdenZC/codex-work-skills/actions/runs/38112567308), C2 Hosted [38112567301](https://github.com/ArdenZC/codex-work-skills/actions/runs/38112567301), and Template Package [38112567310](https://github.com/ArdenZC/codex-work-skills/actions/runs/38112567310): `SUCCESS` at C2 PR head `b32e9c53f183e1a1ec5e4137411e53f1e9be4840`.
- Formal Trust Anchor: `eb4a95c618e05c5ad6413137478bc65dbca75ec9` (not changed or written).
- Branch: `feature/rq03f-b3c3-monotonic-trust-ledger`.
- Draft PR: [#62](https://github.com/ArdenZC/codex-work-skills/pull/62), implementation commits are on `feature/rq03f-b3c3-monotonic-trust-ledger`.
- Formal Production Operator Trust, external High-Water Authority, protected Intake, Agent A/B, Live Qualification, RC-02, and Lesson Skill 2.4 remain blocked/not started.

## Scope and threat model

C3 addresses rollback or split-brain of the Operator's local Profile/Index/Ledger projection after filesystem restore, stale process state, concurrent writers, partial persistence, or a lost commit response. Candidate-controlled JSON, hashes, paths, Python import paths, and local locks are not trust roots. The local ledger detects local inconsistency but cannot detect a complete rollback of its own storage domain.

The protocol therefore separates the Operator-owned projection from a `HighWaterAuthority` contract. A future Authority must be separately provisioned and authenticated, enforce linearizable compare-and-swap (CAS) with fencing, and retain a durable non-rollback history outside the Operator snapshot/backup domain. C3 deliberately includes no production Authority adapter, key, endpoint, or Owner approval credential. The hosted Witness is synthetic, branch-controlled code on the same temporary GitHub runner; it demonstrates the protocol and Linux UID boundary only.

## Versioned contracts

Four new closed JSON Schemas reject unknown properties:

| Contract | Version | Purpose |
| --- | --- | --- |
| `rq03f-monotonic-trust-ledger-v1.0.schema.json` | Ledger 1.0 | Complete ordered local projection of committed Authority history. |
| `rq03f-monotonic-trust-ledger-record-v1.0.schema.json` | Ledger Record 1.0 | One sequence-bound committed state and its previous-state/record links. |
| `rq03f-trust-transition-v1.0.schema.json` | Transition 1.0 | Closed transition request and lifecycle status contract. |
| `rq03f-high-water-authority-response-v1.0.schema.json` | Authority Response 1.0 | Typed current snapshot, freshness, fencing token, and pending IDs. |

Every committed state binds policy identity and epoch, Profile SHA-256, Build Inventory SHA-256, Controller and Generation IDs, Index 1.1 SHA-256 and revision, revocation-state SHA-256, and revoked authority/role references. Every Ledger record binds its Authority identity, contiguous sequence, previous committed state digest, previous record SHA-256, current state digest, transition ID, purpose, committed status, approval reference, and UTC audit timestamp. Genesis is sequence zero with no previous digests. Timestamps are audit metadata; monotonicity is the Authority sequence and CAS state.

The C3 module strictly parses duplicate-free JSON, verifies closed schemas, exact history length and order, both record chains, and the snapshot head against the complete Authority history. It refuses an unavailable Authority, stale response, identity mismatch, pending transition, local recovery marker, missing/truncated/reordered history, old Index, same-revision/different-SHA state, and mixed Profile/Index/Generation bindings.

## State validation

- Epoch cannot decrease or skip. An epoch change requires Authority-verified `owner_policy_transition` authorization bound to the exact transition and proposed-state digest, a different approver from actor, a new Profile SHA, and a new Generation ID.
- Policy identity, Profile, Build Inventory, Controller, Generation, and revocation digest are fixed within one epoch. A Profile/role/revocation change therefore requires the next Owner-approved epoch under this contract.
- Revoked authority IDs and role authorization references are monotonic sets; an old revocation cannot disappear from history. `revocation_state(profile)` hashes role identity, authorization reference, allowed roles, validity window, revocation time/reason, and revoked authority IDs.
- Index 1.1 transitions must have exact old-array prefixes, continuous revision, matching byte hashes, correct epoch/Controller, and unique operation/receipt/authoring/run/intake IDs. Same-epoch changes must append a row; a policy-epoch transition may change the Index epoch without fabricating a record.
- Gate results are exact `GateResult` objects, never booleans or Candidate JSON. They bind authority identity, policy, epoch, Profile, Build, Controller, Generation, Index revision/SHA, revocation digest, operation purpose, freshness, and fencing token. Each sensitive C2 request constructs a fresh request and rechecks the Authority; Gate results are not cached.

## Commit protocol and linearization point

`MonotonicTransitionCoordinator.commit()` follows this order:

1. Read and validate the current Authority snapshot and complete local Ledger projection; reject recovery markers or pending transitions.
2. Compare the exact local Index bytes to the Authority state and validate the proposal, independent authorization, epoch/revocation successor, and append-only Index.
3. Ask the Authority to reserve the transition against the current sequence/state digest. The Authority returns a unique typed fencing token.
4. Exclusively stage and fsync the exact candidate Index bytes in the Operator projection; reread and compare the staged bytes.
5. Ask the Authority to perform the conditional commit. **The Authority's successful CAS is the linearization point.** This is the only point at which the proposed state becomes committed.
6. Install the staged Index, then project the Authority's complete committed Ledger history locally, with file and parent-directory durability checks.
7. Reread the Authority and independently verify the latest snapshot, Index SHA, Ledger chain, sequence, and absence of pending transitions before returning success.

An ordinary `rename()` never claims to make the two trust domains atomic. Before the Authority commit, an abort is permitted only if the old committed Index still matches the Authority. After the commit, any uncertain local state receives a recovery marker and returns `RECOVERY_REQUIRED`. A local marker blocks the Gate. Recovery may install only the exact staged bytes whose SHA matches the latest Authority commit; missing, divergent, or ambiguous bytes stay blocked. It never resets the ledger, restores an old index, lowers an epoch, or reuses a committed ID.

```mermaid
stateDiagram-v2
    [*] --> Prepared: Authority CAS reservation
    Prepared --> Staged: exact candidate bytes fsynced
    Staged --> Committed: Authority conditional commit (linearization)
    Staged --> Aborted: Authority abort, old Index still verified
    Committed --> Projected: install Index and Ledger projection
    Projected --> Verified: independent reread succeeds
    Committed --> RecoveryRequired: ACK, fsync, or projection uncertain
    RecoveryRequired --> Projected: exact latest committed bytes verified
    RecoveryRequired --> [*]: unresolved or conflicting evidence; remain blocked
```

| Failure point | Required result |
| --- | --- |
| Before prepare | No committed state change; reject. |
| After prepare / before staging | Abort only while current Index still matches the old Authority state; otherwise mark recovery-required. |
| After staging / before Authority commit | Abort only against the unchanged old Index; the transition ID remains consumed. |
| Authority commit accepted but ACK lost | Mark recovery-required; query the Authority, reconcile the exact staged committed bytes, then permit idempotent retry of that same transition. |
| After Authority commit / before or after local Index replacement | Keep writes blocked and recover only from exact staged bytes and current Authority history. |
| Ledger projection fsync or final reread fails | Keep writes blocked; do not claim success until an independent reread verifies the projection. |
| Authority unavailable, sequence conflict, stale fencing token, or unknown status | Fail closed; unresolved status is not inferred as committed or aborted. |

Recovery runbook: stop all writers; obtain a fresh authenticated Authority snapshot and transition status; validate Authority identity and full chain; compare local committed and staged bytes; follow only the exact committed or still-prepared outcome returned by the Authority; fsync and reread all local projections; clear a marker only after independent final verification. If any step lacks an authoritative answer or exact bytes, preserve evidence and leave `RECOVERY_REQUIRED` for Owner-directed recovery.

## C2 integration and default deny

`operator_controller_bootstrap.py` adds the C3 module and all four C3 schemas to the trusted installed-code closure. The build inventory must therefore be rebuilt and independently reviewed/approved before any future installation can pin this closure. The provider constructs fresh C3 request bindings from its revalidated C2 Policy/Profile/Build/Index state and accepts only the pinned `MonotonicAntiRollbackGate` implementation and its complete typed result.

C2 `ReadOnlyPreflightTrustContext` and `require_protected_write()` remain unconditional. C3 verification does not grant a production role, write access, Intake capability, Teacher/PA/Generation authorization, or service activation. No environment switch or CLI argument enables writes. Tests explicitly pass a successful synthetic Gate to the C2 provider and verify that protected writes are still denied.

## Deterministic tests and local environment evidence

The new C3 module has 53 tests covering closed schemas and duplicate JSON, Ledger chain and Authority freshness, state/epoch/profile/Generation/revocation/Index mismatches, stale and replayed transitions, duplicate operation IDs, stale fencing/CAS, two writers racing one revision, definite CAS rejection after a competing commit, ABA restoration, C2 old-context behavior, transaction/recovery failure injection before prepare, after prepare, after staging, after Authority commit, after Index install, after local Ledger projection, before final reread, and after lost ACK. Filesystem tests exercise exclusive staging, symlink/hardlink rejection, and exact atomic projection behavior. The hosted harness also checks that every disposable Linux role/group name remains within the 32-character login-name limit.

Local regression results:

- C3 + C2 + C1 deterministic modules, the targeted C3 shard-manifest assertion, and the inherited qualification-intake suite passed **127 tests** (`C3 53`, `C2 31`, `C1 25`, shard assertion 1, intake 17); one inherited C1 POSIX ACL test is intentionally skipped locally and runs in hosted Linux.
- The intake fixture derives its pinned module and schema rows from the current closed C2 `REQUIRED_MODULES` / `REQUIRED_SCHEMAS` sets and preloads the C3 ledger module.
- The C3 filesystem projection tests passed with a private test parent supplied through `RQ03F_C3_PROJECTION_TEST_ROOT`.
- Workflow YAML parsing, Python compilation, and `git diff --check` passed.

The full `tests.test_run_test_shards` module has an existing Gradebook validator failure described below.

The Gradebook failure was reproduced on this branch and on an isolated clean worktree at the same trusted base `b894077fb5967a9aed8713892f448acfa5b65b62`; no Gradebook code, workbook asset, or Gradebook test is modified here. The base and branch both fail `test_gradebook_discovery_worker_does_not_reuse_lesson_package_common` because the nested `test_template_validator` returns 1 with `Named-range template changed protected workbook structure or formatting.` The Codex runtime resolves `soffice` to `/opt/codex/runtimes/codex-primary-runtime/dependencies/bin/override/soffice`, version `LibreOfficeDev 26.8.0.0.alpha0 2c87e51eeaa2b413ff4ae097b2705eea1995d8e5`. The validator reports 20 protected-signature differences; the observed difference is `font.charset` changing from `1` to `null` on LibreOfficeDev XLS round-trip (first reported at `non_target_sheets.Sheet1.cells[1][1].format.font`). This is a reproduced baseline/environment incompatibility, not reported as a pass. Fresh Template Package CI remains required to establish the hosted result.

## Hosted Linux evidence boundary

The new `rq03f-b3c3-monotonic-trust-ledger` workflow checks out the exact PR head with no persisted token, installs only temporary runner prerequisites, reruns C3/C2/C1 deterministic tests and C1/C2 hosted regressions, and runs `tools/rq03f_c3/hosted_linux_isolation.py --root-test` as root solely for provisioning. The C1 deterministic suite runs in a separate process with the actual hosted runner UID and primary GID, using `setpriv --clear-groups --bounding-set=-all`; the process reports its real UID/GID and verifies `os.getgroups()` is empty and effective capabilities are zero. No identity APIs are mocked. The C3 filesystem projection tests use a newly created private fixture parent under `/var/lib`, owned by the runner UID with mode `0700`, because the hosted runner's home path carries an extended ACL that the production projection validator correctly rejects. The fixture is created exclusively and removed on success or failure.

The C3 hosted harness creates collision-checked, separate real UIDs for Operator, Candidate, Author, Reviewer, Approver, and Witness; drops all capabilities before role work; closes inherited non-standard file descriptors; records `/proc` UID/GID/capability evidence; applies and checks directory/file ownership, modes and ACLs; and requires cleanup of all temporary users, groups, sockets, and directories.

The test Operator can use the fixed synthetic protocol to commit through a Unix-socket Witness with a different UID. The synthetic Witness is separately owned and not readable/writable by the Operator UID. The hosted sequence exercises a committed write with a deliberately dropped ACK and exact recovery/idempotent retry, a two-writer same-revision CAS race with exactly one winner, an Owner-authorized synthetic epoch/Profile/Generation rotation with role revocation (old request rejected), a Witness process restart, complete restoration of the old Operator Index/Ledger snapshot (rejected against the persisted Witness high-water state), candidate `PYTHONPATH` module shadowing, and fail-closed behavior with the Witness unavailable. Test state and approvals are synthetic and never copied into formal trust storage.

This hosted workflow is authored by the PR and runs on a GitHub-hosted temporary VM. Even a green result proves only that the submitted harness exercised ordinary Linux UID/mode/ACL and protocol behavior in that VM. It does not prove that the PR-controlled test code, test-only Witness, VM snapshot, GitHub control plane, or Owner production deployment has an independent anti-rollback trust root. The production result remains `PRODUCTION_TRUST_BLOCKED`.

## CI and exact-head tracking

- C2 post-merge baseline: [run 38114284561](https://github.com/ArdenZC/codex-work-skills/actions/runs/38114284561), `SUCCESS`, head `b894077fb5967a9aed8713892f448acfa5b65b62`.
- Earlier exact-head CI at `0b7335bed315de48c6e7e23857d902922c9ed6af` exposed three actionable issues; none is reported as passing:
  - C3 workflow [38116342934](https://github.com/ArdenZC/codex-work-skills/actions/runs/38116342934) failed because two projection tests used the hosted home directory, whose extended ACL is rejected by the production validator, and the combined C1 deterministic suite inherited supplementary groups. The workflow now uses an exclusive private fixture parent and clears groups while retaining the actual runner UID/GID.
  - C1 Hosted [38116342885](https://github.com/ArdenZC/codex-work-skills/actions/runs/38116342885) failed before its intended trust assertions because the C1 intake test fixture hard-coded an older controller module/schema list. The C2 closure now requires the C3 module and three C3 schemas, so the fixture reported `operator controller build inventory is incomplete`; later expected error assertions consequently failed. The fixture now derives rows from the closed C2 required sets and preloads the new C3 module. Local intake tests pass 17/17.
  - C2 Hosted [38116342886](https://github.com/ArdenZC/codex-work-skills/actions/runs/38116342886) passed on that earlier head.
- The Template Package run [38116342889](https://github.com/ArdenZC/codex-work-skills/actions/runs/38116342889) at that earlier head retained the complete matrix, including all 12 Windows/macOS Semantic Scope shards. At least seven semantic shards had failed while other jobs were still queued, so this run is not accepted as passing; the updated fixture is exercised again by the fresh final-head matrix.
- The next exact-head C3 run [38117066981](https://github.com/ArdenZC/codex-work-skills/actions/runs/38117066981) failed its deterministic step for two harness issues: an unconditional shell `EXIT` trap removed the private fixture parent before tests used it, and the shard-coverage test imported `tests.test_template_packages` without `openpyxl` installed. The fixture cleanup now runs only on setup failure or in the final cleanup step, and `openpyxl` is installed for the manifest test. These fixes require fresh exact-head CI.
- C3 run [38117727630](https://github.com/ArdenZC/codex-work-skills/actions/runs/38117727630) passed the C3/C2 deterministic suites and manifest assertion, then failed the C1 deterministic suite because its default `REPO_ROOT` temp parent traverses `/home`, where the hosted runner has an extended ACL that C1 correctly refuses. The workflow now sets C1's supported `RQ03F_C1_TEST_TMPDIR` to the same isolated private `/var/lib` fixture parent; allocator checks remain unchanged.
- C3 run [38118003416](https://github.com/ArdenZC/codex-work-skills/actions/runs/38118003416), exact head `73a6a89812691cdb09c5031de912b8feca624797`, passed all 84 C3/C2/manifest tests and verified the C1 process identity (`uid=euid=1001`, `gid=egid=1001`, no supplementary groups, `CapEff=0`). It then failed during C1 `TestRQ03FCandidateBuildInventory.setUpClass`: the workflow passed `actions/setup-python`'s `/opt/hostedtoolcache/Python/3.12.15/x64/bin/python3.12` as `build_python_executable`, and C1 correctly rejected that group/world-writable executable. The 14 remaining C1 cases passed and its POSIX ACL test was skipped as expected. The workflow now resolves and verifies the root-owned, non-writable `/usr/bin/python3` executable, confirms its pip module, and runs the same C1 suite under the real runner UID with groups and capabilities cleared; no validator or test expectation is weakened. This fix requires fresh exact-head CI.
- C3 run [38118515992](https://github.com/ArdenZC/codex-work-skills/actions/runs/38118515992), exact head `e436571b9fc90a4ed2601eaed9ec87361e1a3ff2`, passed the 84 C3/C2/manifest tests and all 25 C1 deterministic tests under the verified system Python. The six-UID Witness phase then failed because the generated `rq03c3-<16 hex>-candidate` login name was 33 characters, beyond Linux `useradd`'s 32-character limit. The failure artifact records `useradd: invalid user name`; the hosted cleanup check passed with no remaining accounts, groups, or temporary paths. The generator now uses a 14-hex-character random token and checks the 32-character bound before provisioning; a deterministic regression covers every role/group name and token format. This fix requires a new exact-head run.
- C3 run [38118772482](https://github.com/ArdenZC/codex-work-skills/actions/runs/38118772482), exact head `9b7cdf64b05629ccc0b2948f452468aeee02a113`, passed 85 C3/C2/manifest tests and the C1 deterministic suite (25 tests, one hosted ACL case skipped). Its Witness phase then failed because child UIDs could not traverse the runner-owned checkout path to open `tools/rq03f_c3/hosted_linux_isolation.py`; the evidence reports `Permission denied`, and final cleanup passed. The harness now copies only tracked regular, singly linked source/schema files after checking their Git blob IDs and SHA-256 bytes into a root-owned read-only tree (`dirs 0755`, files 0444), then runs Operator, role probes, and Witness from that exact copy. Hosted evidence includes the copy manifest digest. This fix requires a new exact-head run.
- C1 Hosted [38117067025](https://github.com/ArdenZC/codex-work-skills/actions/runs/38117067025) passed its deterministic intake/semantic suites but failed the real-UID qualification because the direct trusted bootstrap `--entrypoint` path imported only the probe, not every now-required verified controller module. `TrustContext.load()` correctly failed closed when `rq03f_monotonic_trust_ledger` was absent from `sys.modules`. The bootstrap now preloads and checks the full required module closure from the hash-verified install root before invoking a pinned entrypoint. This changes the bootstrap bytes and therefore any future Build Inventory pin must be rebuilt and independently approved.
- After that bootstrap fix, C1 Hosted [38117727612](https://github.com/ArdenZC/codex-work-skills/actions/runs/38117727612) passed at implementation HEAD `9034515dae850ba860b7c58ee09a9078f45af865`: the disposable Linux test reported operator UID `999`, three synthetic qualification-only intake rows, zero authors/production artifacts, `B3_SUMMARY=failures:0`, and complete temporary-user/path cleanup. These are hosted synthetic results only.
- Fresh exact-head CI for the final pushed commit is required after these fixes. The C3, C1, C2, and Template Package workflows check out or validate the exact PR head and retain the required gates. Final run URLs and outcomes are reported in the delivery response; no pending result is presented as a pass.

## Files changed

- `.github/workflows/rq03f-b3c3-monotonic-trust-ledger.yml` — independent temporary Linux Witness workflow and evidence artifact.
- `.github/scripts/run_test_shards.py`, `tests/test_run_test_shards.py` — explicit Linux-only C3 shard registration and exact coverage assertion.
- `教案生成器/lesson-plan-docx-generator/scripts/rq03f_monotonic_trust_ledger.py` — strict schemas, state verification, Gate, projection, transition and recovery contracts.
- `教案生成器/lesson-plan-docx-generator/scripts/operator_controller_bootstrap.py` — include C3 code/schema in pinned installed closure.
- `教案生成器/lesson-plan-docx-generator/scripts/rq03f_operator_trust_provider.py` — fresh C3 Gate request/result validation while retaining unconditional protected-write denial.
- Four `rq03f-*-v1.0.schema.json` files under `教案生成器/lesson-plan-docx-generator/schemas/`.
- `tests/test_rq03f_c3_monotonic_trust_ledger.py` and one C2 negative integration test.
- `tests/test_qualification_corpus_intake.py` — keep its synthetic pinned Build Inventory fixture aligned with the current closed controller module/schema sets and preload the C3 closure module.
- `tools/rq03f_c3/hosted_linux_isolation.py` — disposable six-UID synthetic Witness integration test.
- `RQ03F_B3C3_MONOTONIC_TRUST_LEDGER.md` — this report.

## Remaining production prerequisites

Before Production Trust could be considered, an independent deployment owner must provision an Authority outside the Operator rollback domain; define and enforce its identity/authentication and durable CAS/fencing semantics; independently pin its service/device identity and C3 build; define Owner approval, key/role revocation and epoch-rotation processes; demonstrate backup/restore and disaster-recovery behavior without lowering its high-water state; deploy a production launcher/TrustContext provider with a reviewed write path; and pass a separate Owner-led deployment acceptance. The current C2 launcher remains read-only, its system service remains disabled, and this PR creates no formal authority evidence or trust records.

## Final review fields

- Implementation HEAD before the final report commit is recorded in the delivery response; the final PR head is the report commit recorded in PR #62.
- Draft PR: [#62](https://github.com/ArdenZC/codex-work-skills/pull/62), remains Draft; no merge requested or performed.
- Hosted Linux UID/Witness and Template Package CI: exact-head results are available from [PR #62 Checks](https://github.com/ArdenZC/codex-work-skills/pull/62/checks) and listed in the delivery response.
- Production trust: **not established**; Formal Trust Anchor unchanged.
