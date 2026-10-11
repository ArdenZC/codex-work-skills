# RQ-03F-B3-D0 — Independent Deployment Readiness and Production Trust Decision Package

## Executive disposition

**B3-D0 PREPARATION ONLY — PRODUCTION TRUST NOT ESTABLISHED — NO GO FOR LIVE QUALIFICATION.**

The C1 allocator/build verifier, C2 fixed candidate Launcher/TrustContext Provider, and C3 monotonic Ledger/High-Water protocol are present on trusted master. Their code has hosted synthetic verification. A production High-Water Authority, production Owner pins, final production Profile 1.1 / Index 1.1, path-bound adopted Build Inventory, target-host identity evidence, and independent Owner adoption do not exist in this evidence set. C2 continues to reject every protected write.

This package records repository evidence and prepares decisions. No command ran on an Operator/production host. No account, Authority, certificate, service, Profile/Index, Generation, pin, formal Intake, protected write, or Owner approval was created or modified. No Agent A/B, Live Reviewer Qualification, RC-02, or Lesson Skill 2.4 was started. No merge, close, release, service activation or Trust Anchor update was performed.

## Baseline and verification labels

| Item | Verified value |
|---|---|
| Starting `origin/master` | `bc109e30e3223a9cb780f20c13c73963f356866e` |
| Freshly fetched `origin/master` at D0 start | Same as starting SHA; local D0 branch created from this exact commit |
| PR #62 | Merged; PR head `8a71e2a89f77750fb9d6bbe1ea56c55642c0988e`; merge commit/master `bc109e30e3223a9cb780f20c13c73963f356866e` |
| PR #62 final master CI | [Run 38142580454](https://github.com/ArdenZC/codex-work-skills/actions/runs/38142580454), associated with master commit `bc109e30e3223a9cb780f20c13c73963f356866e`; final outcome is recorded below after checking the run and CI Gate |
| Formal Trust Anchor | `eb4a95c618e05c5ad6413137478bc65dbca75ec9`, detached clean checkout under `/workspace/rq03-operator-trust/eb4a95c618e05c5ad6413137478bc65dbca75ec9` |
| Formal Anchor Profile 1.0 SHA-256 | `d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4` |
| Formal Anchor Index 1.0 SHA-256 | `52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4` |
| D0 branch | `docs/rq03f-b3d0-independent-deployment-readiness`, based on the verified master SHA above |

Labels used below:

- `VERIFIED_FROM_REPO` — checked against the exact source commit, raw bytes or repository record identified here.
- `HOSTED_SYNTHETIC_ONLY` — temporary hosted runner/protocol evidence; not an Owner-controlled production trust root.
- `OWNER_ADOPTION_REQUIRED` — exact value or authorization must be supplied and adopted independently by the Trust Owner.
- `TARGET_HOST_EVIDENCE_REQUIRED` — no production target host was inspected or used in D0.
- `PRODUCTION_AUTHORITY_MISSING` — no independently operated production High-Water Authority is present.
- `UNVERIFIED` — cannot be established from repository/hosted evidence.
- `NO_GO` — the condition blocks deployment, protected write, or live qualification.

## Post-merge CI and CI Gate

PR #62's merge commit is the exact trusted master baseline. The merge commit differs from the tested C3 implementation head `7009189626de7564f68c2cfd0fc468daf1635a92` only in `RQ03F_B3C3_MONOTONIC_TRUST_LEDGER.md`; C1/C2/C3 production-source paths have no intervening source diff. The exact implementation-head hosted evidence and the required post-merge result are separate records:

| Evidence | Exact source | Observed result |
|---|---|---|
| C1 Hosted Operator Infrastructure [38132872876](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132872876) | Final PR head `8a71e2a89f77750fb9d6bbe1ea56c55642c0988e` | `workflow_dispatch`, one hosted job completed `success`; temporary identities and files only |
| C2 Hosted Launcher/Provider [38132868799](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132868799) | Final PR head `8a71e2a89f77750fb9d6bbe1ea56c55642c0988e` | Pull-request run, one hosted job completed `success`; synthetic Policy/Profile/Index/Build and read-only preflight only |
| B3 Hosted Operator Isolation [38132868797](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132868797) | Final PR head `8a71e2a89f77750fb9d6bbe1ea56c55642c0988e` | Pull-request run, one hosted job completed `success`; temporary UID separation only |
| C3 Hosted Witness [38132868815](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132868815) | Final PR head `8a71e2a89f77750fb9d6bbe1ea56c55642c0988e` | Pull-request run, one hosted job completed `success`; temporary synthetic Witness/CAS/recovery only |
| C3 Template Package CI [38132868787](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132868787) | Final PR head `8a71e2a89f77750fb9d6bbe1ea56c55642c0988e` | 41 jobs complete: 40 success, one conditional documentation job skipped, 0 failures; CI Gate success; Windows/macOS Semantic Scope 12/12; Windows/macOS Gradebook pass |
| Post-merge master Template Package CI [38142580454](https://github.com/ArdenZC/codex-work-skills/actions/runs/38142580454) | Merge commit `bc109e30e3223a9cb780f20c13c73963f356866e` | **Final result and CI Gate must be recorded after run completion; no post-merge completion claim is made while pending.** |

A green hosted or PR run does not establish post-merge qualification. A green post-merge CI Gate is still software CI evidence, not live Reviewer Qualification or Production Trust. If run `38142580454` does not finish successfully or its required CI Gate is not green, the D0 delivery conclusion must be `BLOCKED — POST-MERGE MASTER CI GATE NOT SUCCESSFUL`.

## C1–C3 implementation versus deployment contract

The earlier [B3-B deployment readiness report](RQ03F_B3B_OPERATOR_DEPLOYMENT_READINESS.md) is a historical report from before C1–C3. Its statements that no candidate Launcher, Provider or Ledger implementation existed are now superseded by the merged C1–C3 code and their reports. Its conclusion that Production Trust was blocked remains accurate. The original report is left unchanged.

All file SHA-256 values below were independently recomputed from the `VERIFIED_FROM_REPO` commit `bc109e30e3223a9cb780f20c13c73963f356866e`. Component-introduction commit and current master identify the code lineage; these source digests are not Owner-approved production Build Inventory pins.

| Component | Source path(s), exact introducing commit and SHA-256 | Existing CI evidence | Current classification and missing deployment condition |
|---|---|---|---|
| C1 exclusive Archive/Generation allocator | `tools/rq03f_c1/operator_allocator.py` — introduced by `997217ebc787397bc0262770305f738171e21ccd`; SHA-256 `1ed9f7752cda46fa9429c8b53a5193e093d6bc6f7ea05ff5c39d24e9282ef421` | C1 Linux real-UID suite [38132872876](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132872876) at final PR head; [C1 report](RQ03F_B3C1_INFRASTRUCTURE_FOUNDATION.md) | `IMPLEMENTED_CANDIDATE`; `HOSTED_VERIFIED`; `OWNER_ADOPTION_REQUIRED`; target allocator plan/root/identity remain unapproved. |
| C1 locked install, Inventory builder, verifier and runtime closure | `tools/rq03f_c1/build_inventory.py` SHA-256 `8696a0eab60d5b2a52242c8e82578eedca646c786dcf458cc5f39dd5985bb9e4`; `locked_install.py` `63afb78fb69490e81bbccf32d7efb70656f5f8563eb6003f8379265df406a49d`; `verify_inventory.py` `1a45400417727f3c202aa16c45f4254127e86a36fdfd8bc3399d784a8f6c871d`; `runtime_closure.py` `cc5445df70c052225f53db650c78472461b5daf6ef013942ce5c66d3c83a22c7` | Same C1 hosted run; Template CI linked above | Inventory 1.1 is candidate shape/checking, not Owner adoption. No production lock/wheelhouse, final paths, full OS/shared-library digest or production Inventory SHA. |
| C2 fixed Launcher and closed Launch Policy | `rq03f_fixed_operator_launcher.py` — introduced by `b894077fb5967a9aed8713892f448acfa5b65b62`; SHA-256 `cd4ca2e0adc1e48da49cb37cf9ffc736a802bc5cea4b0ae3e23dcc2bf628d226`; `rq03f_operator_launch_policy.py` `2947ada40dcf46119f3ce24139cb49337bfabce75e787eccc9a61eadfd73babe` | C2 Hosted [38132868799](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132868799); exact Template CI [38132868787](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132868787) includes existing matrix | `IMPLEMENTED_CANDIDATE`; `HOSTED_VERIFIED`; candidate Pin/Policy only. No externally Owner-pinned production paths or policy. |
| C2 TrustContext Provider and bootstrap closure | `rq03f_operator_trust_provider.py` SHA-256 `ae52e618d92728127dce99f2882250a4a635d97c72481677b49c5d20b9158d2b`; `operator_controller_bootstrap.py` `e9cea105d21cbf9e73cefe43d7fbc66d38718a53d39727d3f218722295d3a2ba` | Same final-head C2 Hosted run; see [C2 report](RQ03F_B3C2_FIXED_OPERATOR_LAUNCHER.md) | `require_protected_write()` unconditionally denies. No production write path, external TrustContext/Policy Pin provider or adopted service identity. |
| Candidate systemd unit | `systemd/rq03f-operator-preflight.service` SHA-256 `7aebd1fd87f7a7f5ebc98a8383c1fb42fb17630c9c83cd71eecc5e4c21161ec5` | Hosted syntax verification is synthetic; no unit install/start | Candidate unit has no `[Install]` section, fixed test Generation path and read-only preflight. It is not installed, enabled or started. `TARGET_HOST_EVIDENCE_REQUIRED`; deployment must STOP. |
| C3 monotonic ledger, purpose map and coordinator | `rq03f_monotonic_trust_ledger.py` — introduced by `bc109e30e3223a9cb780f20c13c73963f356866e`; SHA-256 `43e14398f80679172830b4ff0916fe475c02088df5813a4f6d7a7dd2d49a3a70` | C3 Hosted Witness [38132868815](https://github.com/ArdenZC/codex-work-skills/actions/runs/38132868815); [C3 report](RQ03F_B3C3_MONOTONIC_TRUST_LEDGER.md) records exact test coverage | `IMPLEMENTED_CANDIDATE`; `HOSTED_VERIFIED`; no production `HighWaterAuthority` implementation or service identity. |
| C3 six-UID hosted Witness adapter | `tools/rq03f_c3/hosted_linux_isolation.py` SHA-256 `da75ff2ddc5a7723358f1b881571c2307a28519078937209216a4c6d7f857b64` | Same C3 Hosted run | `HOSTED_SYNTHETIC_ONLY`; temporary state and approval material cannot become formal trust evidence. |
| Candidate C2/C3 Hosted boundaries | `tools/rq03f_c2/hosted_linux_isolation.py` SHA-256 `07262955c8c4e73fdb4f9247332d407873bfb141231b35c8714a59906a8f1a3f`; `tools/rq03f_c3/hosted_linux_isolation.py` above | Final-head C2/C3 runs above | Workflow and test code are branch-controlled; neither test runner is an independent Owner. |

### Contract/schema inventory

The following schema files are present at master `bc109e30e3223a9cb780f20c13c73963f356866e`. Their SHA-256 values are source verification values; production documents still require independent adoption.

| Contract | Repository path | SHA-256 | Current condition |
|---|---|---|---|
| Profile 1.0 | `教案生成器/lesson-plan-docx-generator/schemas/operator-authority-profile.schema.json` | `1b8c26a219e97ac7f44d0317c64e4bc62ff062e970badfa1eb6c6650a25136b1` | Existing historical contract; do not reinterpret. |
| Profile 1.1 | `教案生成器/lesson-plan-docx-generator/schemas/operator-authority-profile-v1.1.schema.json` | `d49e2fd973dc411e775e4173b1690c41612d64437354780a1b49c62edabb0876` | Closed candidate migration contract; new Owner-issued file required. |
| Index 1.0 | `教案生成器/lesson-plan-docx-generator/schemas/protected-operation-index.schema.json` | `70c2bf66c049237df4749f5214d3cd0c3cec57de435475ae36e9b491a81de505` | Existing historical contract; no in-place upgrade. |
| Index 1.1 | `教案生成器/lesson-plan-docx-generator/schemas/protected-operation-index-v1.1.schema.json` | `cc73f37b727eeec7e6277fe1d0e48ff6b86c0699906a81d5abf8cf09b82828bb` | Closed candidate extension adds `qualification_corpus_intakes`; no production Index issued. |
| Build Inventory 1.1 | `教案生成器/lesson-plan-docx-generator/schemas/operator-controller-build-inventory-v1.1.schema.json` | `f0d5a5b3177981f20be3273e30055ce6ffb55dcaabbf1a7974b5b0282055e030` | Candidate build contract; paths and all runtime bytes require final host pin. |
| Launch Policy 1.0 | `教案生成器/lesson-plan-docx-generator/schemas/rq03f-operator-launch-policy-v1.0.schema.json` | `f65be88535b2ab40200d56e1c91c0cfe71022c4d59abd0147ef56b13cb5e1aaa` | Candidate policy only. |
| Policy Pin 1.0 | `教案生成器/lesson-plan-docx-generator/schemas/rq03f-operator-policy-pin-v1.0.schema.json` | `c337190f806ca12e0a0fb8f26927acd913c1cd33a152814fa6a3fbebce0dd05a` | Candidate schema; independent pin channel absent. |
| Ledger / Ledger Record 1.0 | `rq03f-monotonic-trust-ledger-v1.0.schema.json` SHA-256 `69d129ae396764b4ce772b977c64da7a3c662002ae1a247c68d857f49c9c771f`; `rq03f-monotonic-trust-ledger-record-v1.0.schema.json` SHA-256 `c0a962910ccc5fea3e0f164ab47b7bf1b4a566126a1c28b64060eeced506c833` | Paths under `教案生成器/lesson-plan-docx-generator/schemas/` | Candidate C3 format; no production Authority state. |
| Transition / Authority Response 1.0 | `rq03f-trust-transition-v1.0.schema.json` SHA-256 `f35ed649e8082842978f68ae34f2ebd605dab725e0ccd66a85fbc3dff320860a`; `rq03f-high-water-authority-response-v1.0.schema.json` SHA-256 `34381e34eba051f02ecea9ce8b3bb8fbddcf2092b3df96b62ff314ace00d3a4d` | Paths under `教案生成器/lesson-plan-docx-generator/schemas/` | Candidate closed schemas; no external identity or live authority. |
| Qualification Corpus Intake 1.0 | `qualification-corpus-intake-v1.0.schema.json` SHA-256 `f630f1371e4fb589dbb48cc48ffd85da461297d2850e91c5ec8d9c01e3033697` | `教案生成器/lesson-plan-docx-generator/schemas/qualification-corpus-intake-v1.0.schema.json` | Qualification-only custody contract; never historical author proof or production author provenance. |

## Formal Anchor, corpus and history

`VERIFIED_FROM_REPO`: detached Anchor checkout HEAD is `eb4a95c618e05c5ad6413137478bc65dbca75ec9`; Git reports clean. The Profile is version 1.0 / epoch 1 and the Index is version 1.0 / epoch 1. The four existing authorization entries are for `author`, `scope_reviewer`, `qualification_approver` + `teacher_approver`, and `corpus_adjudicator`. All four end at `2026-10-16T11:00:00Z`; none is a `qualification_corpus_custodian` grant. No historical grant is extended or reissued here.

The existing protected Index contains zero records in `receipts`, `authors`, `adjudications` and `qualification_runs`. It has no 1.1 Intake array. Nothing in this package asserts a historical protected Author for the 17 cases or proves Reviewer independence from an unknown historical Author. Intake custody, when separately authorized, records only controlled corpus enrollment and does not become authoring history.

The following raw SHA values were recomputed on the D0 source checkout. The 17 `.content` entries were individually checked against `fixture-files.json`; all 17 matched with zero mismatches.

| Frozen material | Exact SHA-256 | D0 recheck |
|---|---|---|
| Golden qualification corpus | `96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a` | MATCH |
| Blind holdout truth | `268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a` | MATCH |
| Original NC-02 | `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352` | MATCH; N01 Content |
| 17 frozen Content bytes | Per-case hashes in [`RQ03F_B3C1_INFRASTRUCTURE_FOUNDATION.md`](RQ03F_B3C1_INFRASTRUCTURE_FOUNDATION.md) and [`RQ03F_B3B_OPERATOR_DEPLOYMENT_READINESS.md`](RQ03F_B3B_OPERATOR_DEPLOYMENT_READINESS.md) | 17/17 MATCH |

No frozen bytes, golden labels, holdout truth, Formal Trust Anchor, Profile or Index was changed. The independent formal Anchor checkout remains unmodified.

## High-Water Authority decision

The full option comparison is in [Production Authority Options](RQ03F_B3D0_PRODUCTION_AUTHORITY_OPTIONS.md). **Proposed preference:** Option B, an Owner-controlled managed strong-consistency service such as Spanner in a separately administered project, because the Authority's critical contract is conditional, ordered, purpose-bound CAS and the product documents serializable external consistency. This remains `PROPOSED — OWNER_DECISION_REQUIRED`; it is not a selected provider or established guarantee for this deployment. A Linux Witness with quorum-backed etcd is the fallback if the Owner does not have an acceptable independent cloud domain. TPM may supplement a data service but is not a complete Ledger/Authority.

The selected service still must validate all C3 bindings inside its current Commit transaction and maintain an independent Owner checkpoint. Managed availability or database consistency does not itself prevent a privileged backup restore from being promoted as current, prove an external service identity, register production roles, or authorize a business operation.

## Target host and unsigned Owner pins

The [Target Host Requirements](RQ03F_B3D0_TARGET_HOST_REQUIREMENTS.md) template has every unknown host, identity, account, path, build, runtime, network, Authority and backup value marked `OWNER_INPUT_REQUIRED`. No UID/GID, IP address, system ID, certificate, secret, cloud project, service endpoint or authorization has been invented.

The [Production Pin / Migration Checklist](RQ03F_B3D0_PRODUCTION_PINS_MIGRATION_CHECKLIST.md) records known old raw hashes and the full future adoption sequence. New Profile 1.1, Index 1.1, Generation, Controller/Runtime paths, Build Inventory, OS/runtime closure, Launch Policy/Pin, Authority identity, Genesis Ledger, epoch/role registry, revocations, migration lineage and independent Owner adoption record are all `OWNER_INPUT_REQUIRED`.

## A–L independent acceptance

The detailed [A–L Acceptance Matrix](RQ03F_B3D0_ACCEPTANCE_MATRIX.md) records candidate code, existing hosted evidence, missing production proof, Owner decisions, required actor, preconditions, positive/negative results and STOP behavior. The current production gate summary is:

| Gates | Current state |
|---|---|
| A–G: real identities, file denial, repository, code/runtime, Launcher, exact pins, Authority | `NO_GO — TARGET_HOST_EVIDENCE_REQUIRED / PRODUCTION_AUTHORITY_MISSING` |
| H: formal qualification Intake | `NO_GO — NOT AUTHORIZED`; requires a separate explicit Owner business authorization |
| I: historical author identity | `NO_GO FOR DEPLOYMENT`; do not fabricate; no historic authors are proven |
| J: Qualification/Production separation | `NO_GO FOR DEPLOYMENT`; hosted contract tests only, C2 write still denied |
| K: backups/recovery/service failure | `NO_GO — production Authority and target restore unverified` |
| L: Owner adoption | `NO_GO — not started; independent Owner only` |

Completion of A–G cannot automatically execute H. Only the independent Owner can perform L. No production gate has passed in D0.

## Protected writes and exact next engineering dependencies

The [C3 Adapter & Protected-Write Dependency Register](RQ03F_B3D0_C3_ADAPTER_DEPENDENCY_REGISTER.md) describes the future production adapter contract. C3's current `HighWaterAuthority` is a Protocol, and the hosted Witness is a test adapter. C2's `require_protected_write()` still raises unconditionally. This must remain unchanged.

Before a later protected operation can be considered, an Owner-selected production adapter must authenticate Operator and Authority independently; revalidate current authorization/expiry/revocation/fencing in Prepare and atomically at Commit; bind exact purpose/Actor/approver/role authorization/transition ID/state digest/Index revision and SHA; enforce CAS; and expose typed `rejected`, `committed`, or `unknown` results. Unknown Commit status remains `RECOVERY_REQUIRED` with no automatic business retry. Candidate artifacts and exact Index bytes must be staged exclusively and made visible only through recovery-aware publication after the Authority's linearization point. Orphaned or partially published state blocks further writes.

Existing candidate C3 purpose scopes are closed: Intake permits exactly one Intake row; production authoring permits exactly one Author row; Owner epoch transition and revocation permit no business rows. `qualification_review`, `teacher_approval`, `pa_approval`, `generation`, receipt, adjudication and all undefined scopes remain blocked. The adapter package must preserve this map and keep C2 default deny until its independent Owner and target-host review.

## Failure and recovery decisions

| Event | Decision | Required response |
|---|---|---|
| Witness/Authority unavailable | `NO_GO` | No cached Gate or local fallback; deny new writes. If a transition could be pending, `RECOVERY_REQUIRED`. |
| Authority state appears rolled back or its history/head is incomplete | `NO_GO` | `RECOVERY_REQUIRED`; stop the service and retain bytes/logs. Restore only to quarantine and compare an independent Owner checkpoint. |
| Operator old disk snapshot restored | `NO_GO` until proven current | Compare its exact Ledger/Index/Profile/Generation to the live Authority; mismatch is `RECOVERY_REQUIRED`; never reactivate the old snapshot. |
| Profile epoch decreases or old revoked role reappears | `NO_GO` | Reject; require a new Owner-controlled nondecreasing transition and revocation evidence. |
| Index bytes/revision disagree with High-Water state | `NO_GO` | `RECOVERY_REQUIRED`; no local Index selection, regeneration or overwrite. |
| Prepared transition remains open | `RECOVERY_REQUIRED` | Re-read typed status and current authorization. Expired/revoked authorization must abort when status is known; unknown status remains unresolved. |
| Commit ACK is lost | `RECOVERY_REQUIRED` until proven | Read by the same transition ID. If committed, reconcile exact bytes; if unknown, do not retry. |
| Multiple writers race | `NO_GO` for stale losers | Authority CAS/fencing permits one winner only. Unknown outcome requires same-ID recovery. |
| Multiple Generation directories or active pointer ambiguity | `NO_GO` | Keep service disabled; only one Owner-adopted Generation can be selected by a fixed root-controlled launcher. Never rename/repoint ad hoc. |
| Controller/runtime/OS bytes drift | `NO_GO` | Inventory and affected pins invalid; rebuild candidate at final absolute paths, independently recalculate and obtain fresh Owner approval. |
| Certificate expires or rotation is interrupted | `NO_GO` | Deny the channel; no fallback to expired/old credentials. Complete independently approved rotation and verify both peers. |
| Authority backup restored on another host/resource | `NO_GO` | Keep restored state quarantined; verify identity and checkpoint, then Owner-approved re-adoption. |
| Latest high-water cannot be independently confirmed | `RECOVERY_REQUIRED` | Do not reset, infer from local data, or accept a stale backup. |
| Owner approval or adoption is incomplete | `NO_GO` | No Profile/Index/Pin issuance, service start, Intake or live qualification. |

No recovery path may clear the Ledger, reset the epoch, restore an older Index as current, reuse an old Generation, or re-sign expired historical authorization.

## Owner decisions and next work package

The [Owner Decision Register](RQ03F_B3D0_OWNER_DECISION_REGISTER.md) contains 14 unsigned decisions. The immediate decisions are: select Option A/B, identify its independent administrator and recovery domain, supply target-host requirements, and determine whether any new role grant is authorized. The currently adopted role grant window expires at `2026-10-16T11:00:00Z`; no extension is implied.

**Proposed next package:** `RQ-03F-B3-D1 — Owner-Selected High-Water Authority Adapter Contract and Synthetic Integration`. It should implement only the option the Owner selects, keep all inputs synthetic, preserve the C2 write denial, and test outages, CAS, fencing, authorization expiry/revocation, commit ambiguity and restore rollback. A later separately authorized deployment acceptance must collect real target-host evidence. Formal Intake and Live Reviewer Qualification remain separate Owner decisions and later work.

## D0 file scope and validation

This D0 change adds only documents and source-backed evidence indexes. No source module, schema, workflow, trust material, production authorization, frozen fixture, or formal artifact is changed. The final D0 PR HEAD, local link/SHA/diff validation, secret scan, and automatic exact-HEAD check URLs are reported in the delivery response and the Draft PR.

**Current governing state:** `B3-D0 PREPARATION ONLY — PRODUCTION TRUST NOT ESTABLISHED — NO GO FOR LIVE QUALIFICATION.`
