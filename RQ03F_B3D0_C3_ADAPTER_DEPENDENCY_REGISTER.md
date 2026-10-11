# RQ-03F-B3-D0 — C3 Production Adapter and Protected-Write Dependency Register

**Current state: `PRODUCTION_AUTHORITY_MISSING`; protected writes remain blocked.** The C2 provider's `require_protected_write()` unconditionally raises `C3_ANTI_ROLLBACK_GATE_REQUIRED`, even if handed a Gate object. This deliberate denial must remain until a separate Owner-approved production implementation exists.

## Current C3 contract boundary

`HighWaterAuthority` is a protocol only in `教案生成器/lesson-plan-docx-generator/scripts/rq03f_monotonic_trust_ledger.py`. The repository contains a temporary six-UID hosted `UnixWitnessAdapter` in `tools/rq03f_c3/hosted_linux_isolation.py`, but no production remote/managed Authority adapter, production key, endpoint, Owner identity channel or production Witness state.

C3's closed purpose-to-Index contract is:

| Purpose | Exact allowed delta | Authorization binding | Current effective production path |
|---|---|---|---|
| `qualification_corpus_intake` | One `qualification_corpus_intakes[]` row | `qualification_corpus_custodian` / `operator_role_operation`; exact Actor, transition/operation ID and proposal digest; same epoch | **Denied by C2.** No formal custodian grant or Intake authorization exists. |
| `production_authoring` | One `authors[]` row | `author` / `operator_role_operation`; exact Actor, transition/operation ID and proposal digest; same epoch | **Denied by C2.** No production authoring transition is activated. |
| `epoch_transition` | No business rows | `owner_policy_transition`; exactly one epoch advance, new Profile and Generation; no revocation addition in same transaction | **Denied by C2.** Owner adoption only. |
| `revocation` | No business rows | `owner_policy_transition`; exactly one epoch advance and at least one monotonic revocation addition | **Denied by C2.** Owner adoption only. |
| `read_only_preflight` | No Index mutation | No business write | Candidate read-only preflight only; no Production Trust. |
| `qualification_review`, `teacher_approval`, `pa_approval`, `generation`, receipts, adjudications and unlisted purposes | No allowed mutation contract | Unspecified/undefined scope fails closed | **Blocked.** Do not infer permission from purpose names or schemas. |

An Intake transaction cannot add `authors`, `receipts`, `qualification_runs`, `adjudications`, or any other business row. Existing Index 1.1 schemas remain closed and unchanged.

## Exact future development work

| Work item | Required implementation | Acceptance evidence | Owner dependency |
|---|---|---|---|
| **1. Select Authority backend** | Implement only the Owner-selected Option A/B adapter. Keep the C3 protocol seam typed and fail-closed. | Architecture record, independent domain diagram, service identity and backend transaction semantics. | Owner decision D0-01 and independent service administrator. |
| **2. Authenticate the Authority channel** | Authenticate both the Operator workload and the Authority peer; derive caller identity from trusted transport/identity, never from a request field. Support rotation, revocation and expiry. | Negative tests for wrong peer, wrong client, expired identity, revoked key, name substitution and endpoint/DNS replacement. | Owner-held identity issuer and key rotation channel. |
| **3. Persist Authority history atomically** | Store the current head, immutable contiguous history, unique transition IDs, prepared/aborted/committed status and fencing data in the same transaction domain or an explicitly reviewed atomic protocol. | Restart/crash/duplicate/concurrent-writer tests; no sequence gap or lost history on committed response. | Chosen backend semantics and independent backup policy. |
| **4. Implement strong current reads and CAS** | `read_current()` must return a current authenticated snapshot and complete verifiable history. `prepare_transition()` compares exact expected sequence/head/Index SHA/revision and issues unique bounded fencing. Commit CAS must reject stale revision, wrong head, old fencing and duplicate/rebound transition ID. | Two concurrent writers yield one commit; old epoch/revision and lost-ACK cases reconcile by transition ID. | Backend-specific linearizable/serializable semantics. |
| **5. Revalidate at Commit** | Re-read current Owner authorization, actor/approver separation, purpose, role, expiry, revocation state, authorization epoch and fencing token atomically with the Authority Commit. Prepare is only a reservation. | Role expires/revokes after Prepare; commit and expired recovery abort without Index state change. Unknown status becomes `RECOVERY_REQUIRED`. | Current independent role registry, trusted time source and revocation source. |
| **6. Enforce exact purpose and subjects** | Reuse the closed C3 map; bind transition ID/operation ID, purpose, Actor, authorization class/reference, approver, subject bytes, exact candidate Index bytes and revision. Reject mixed-purpose deltas and unlisted arrays. | Intake-to-Author/Receipt/Run injection; wrong Actor or authorization; legal exact Intake/Author operations. | Owner-approved operation scopes and role principals. |
| **7. Define business-artifact transaction publication** | Stage immutable artifact bytes and exact Inventory/Index bytes under protected exclusive paths; compute raw SHA before authorization; bind these bytes in the proposal. Only expose/mark a receipt complete after the Authority commits and the local projection re-reads exact committed bytes. If a post-commit install/publication fails, preserve exact staged bytes and block further writes until recovery finalizes that same transition. | Crash injection before/after Prepare, Authority Commit, artifact publication, Index install, and response. Verify no duplicate business effect and no successful receipt for a partial write. | Owner-defined evidence repository and artifact lifecycle contract. |
| **8. Prevent stale-context / TOCTOU use** | On every protected operation, obtain a fresh TrustContext and a fresh Authority check; bind current index revision/SHA and fence through final commit. Do not cache a Gate result, role grant, Profile or revocation snapshot. | Revoke/change epoch between context creation, staging and Commit; verify Commit fails and no changed Index/artifact becomes active. | Owner clock/role source and Provider integration. |
| **9. Handle result ambiguity** | Distinguish explicit rejection, committed-and-proven, and unknown state. Query status using the same transition ID; never resubmit a business operation on timeout. | Lost ACK before/after linearization; unavailable status; return `RECOVERY_REQUIRED`, preserve bytes and stop. | Backend status/history API contract. |
| **10. Enforce recovery without rollback** | Recovery may reconcile only authenticated Authority state and exact staged bytes. No reset, lower epoch, old Index restore, transition ID reuse or authorization re-signing. A prepared transition gets a new current authorization check; expired/revoked grant aborts if known. | Restore old Operator snapshot; restore old Authority backup to a new/quarantined resource; missing history; false/unknown status. | Owner-held independent checkpoint and separate backup/restore administrators. |
| **11. Connect C2 Provider** | Keep default-deny C2 path. A later reviewed change may replace unconditional deny only after the production Gate type is pinned, Authority checks pass, and operation-specific write implementations use the coordinated transition path. | Tests prove absent/wrong Gate, stale Gate, cached TrustContext, Authority outage and uncontracted purpose deny. | Separate Owner approval and complete adapter evidence. |
| **12. Preserve qualification / production separation** | Qualification-only Intake remains custody evidence; it does not prove historical Author identity or satisfy production provenance. Reviewer/approver must remain independent. | Attempt use of Intake artifact in Production Authoring, Teacher/PA/Generation; all denied. | Owner-approved qualification-only role and separate production authorization. |
| **13. Production operational control** | Provision Authority independently, pin service identity and code, monitor quorum/health/certificate/time/backup state, retain immutable audit, and rehearse restore to a quarantined database/cluster. | Target-host deployment acceptance, failed-run evidence, restoration and re-adoption evidence. | Owner and Authority administrator. |

## Proposed transaction shape for a later approved adapter

This is a design checklist, not executable code or permission to write:

1. Receive a canonical operation request from the fixed Launcher; derive real Actor identity from the protected process plus Owner role registry.
2. Read a fresh Authority head and verify the local Index bytes exactly match its SHA/revision. Reject any outstanding recovery marker or pending transition.
3. Canonicalize and stage immutable artifact bytes and the complete candidate Index using exclusive, no-follow paths. Fsync bytes and parent directories; retain a unique transition ID. Staged content remains non-authoritative and unavailable to downstream production consumers.
4. Ask Authority to prepare against the expected sequence/head/Index hash, exact purpose, role/authorization reference, actor/approver, expiry and complete proposed-state digest. The Authority independently verifies all bindings and returns a short-lived fenced reservation.
5. Re-read current state; ask Authority to Commit. The Authority atomically revalidates current grant/expiry/revocation/fence, then CASes state, appends history, records transition status and binds exact candidate Index SHA/revision. This is the only linearization point.
6. Re-read Authority state/status and compare exact ledger/history/head. Install/publish the exact staged bytes only under the recovery-aware coordinator. Do not report success or create a usable receipt until the published artifact and Index hashes match the committed state.
7. If a response, install or post-commit read is unknown, mark `RECOVERY_REQUIRED`, deny subsequent writes, and reconcile the same transition ID. Never retry as a new operation.

The consistency boundary between the external Authority and local evidence filesystem is not a single physical transaction. The production adapter must prove staging, publication, idempotency, durable fsync, crash recovery and no premature consumer visibility. A generic “database committed” message is not sufficient evidence that the protected business artifact was safely published.

## Mandatory regression suite for the later package

- Purpose/record mapping and exact counts for all currently allowed scopes; mixed-purpose append and every unscoped purpose denied.
- Operator/Actor/Approver/authorization reference/role class mismatch; duplicate transition/operation IDs; modified proposal or Index bytes.
- Authorization expires or is revoked after Prepare; expired prepared Recovery; fencing token changes; old epoch/revision and stale index bytes.
- Authority explicitly denies, commits, loses ACK after commit, returns unknown, becomes unavailable, or restores old history. Verify final Authority state and local Index/artifact bytes for each outcome.
- Concurrent CAS writers; exactly one successful state transition; other writers rejected as stale/fenced.
- Recovery with missing/corrupt stage, wrong stage SHA, wrong status, missing History, stale backup, old Operator snapshot, different Authority identity or newer independent checkpoint.
- C2 default deny still holds for missing Gate, fake Gate, wrong Gate type, cached Context and protected purposes not in the closed map.
- Qualification Intake cannot become production Author/Teacher/PA/Generation evidence.

## Work boundary

The D0 repository change does not implement any work item above and does not alter `require_protected_write()`. All production writes remain disabled. No formal Intake, Agent A/B, Live Qualification, RC-02 or Lesson Skill 2.4 is permitted by this register.
