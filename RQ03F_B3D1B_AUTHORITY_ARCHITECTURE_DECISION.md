# RQ-03F-B3-D1B — Independent Authority Architecture Decision Package

**Disposition: READY_FOR_OWNER_REVIEW — DECISION PACKAGE ONLY / PRODUCTION_TRUST_BLOCKED.**

**Status:** UNSIGNED, NOT ADOPTED, NO DEPLOYMENT. This report does **not** select Spanner, authorize costs, provision a real GCP resource, create IAM grants, issue Owner pins, upgrade Profile/Index, or enable protected writes. The Owner retains D0-01, D0-02 and D0-10 decisions. Issue [#66](https://github.com/ArdenZC/codex-work-skills/issues/66).

## 1. Verified baseline and evidence hierarchy

- Repository: ArdenZC/codex-work-skills; baseline master: **d52fff74ddf717fc89d3195e8940eee57abc87fe**.
- D0 readiness PR #63 and D1A synthetic research PR #65 are merged; D1A Issue #64 is closed as *research completed only*.
- Exact-master D1A [Spanner Emulator CI 38184204473](https://github.com/ArdenZC/codex-work-skills/actions/runs/38184204473) completed SUCCESS. [Template Package CI 38184204506](https://github.com/ArdenZC/codex-work-skills/actions/runs/38184204506) completed SUCCESS: 40 success, one conditional documentation skip; Windows/macOS Semantic Scope 12/12, both Gradebook jobs and CI Gate PASS.
- Source basis: [D0 decision register](RQ03F_B3D0_OWNER_DECISION_REGISTER.md), [D0 authority options](RQ03F_B3D0_PRODUCTION_AUTHORITY_OPTIONS.md), [D0 A–L matrix](RQ03F_B3D0_ACCEPTANCE_MATRIX.md), [D0 C3 adapter dependencies](RQ03F_B3D0_C3_ADAPTER_DEPENDENCY_REGISTER.md), [D1A research report](RQ03F_B3D1A_SPANNER_AUTHORITY_FEASIBILITY.md), and C3 monotonic ledger protocol.
- Formal Trust Anchor **eb4a95c618e05c5ad6413137478bc65dbca75ec9**, historical Profile 1.0 SHA **d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4**, historical Index 1.0 SHA **52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4** are reference values, not new production adoption. D1B does not touch these files.
- The historic role-grant expiry is **2026-10-16T11:00:00Z**. D1B does not extend, reissue, backdate, or transfer any grant. A future custodian role is NOT present in Profile 1.0.

**Evidence labels:** VERIFIED_FROM_REPO = source/CI baseline; VERIFIED_VENDOR_DOCUMENTATION = cited published product behavior, **not** our deployed behavior; SYNTHETIC_ONLY = branch-controlled D1A Emulator; OWNER_INPUT_REQUIRED = no independent owner evidence; NOT_RUN = real service/host tests were not performed; NO_GO = no deployment, formal Intake, or Live Qualification.

## 2. Candidate trust topology and non-negotiable boundary

**Option B — Spanner-backed Authority Service, conditional candidate, not selected:**

1. **Operator client:** locked candidate Launcher and restricted C2/C3 request payload; does not hold Spanner credentials, database session roles, DML/DDL, IAM administration, backup/restore permissions, or credentials capable of impersonating the Authority Service. Its real OS/workload identity and service peer authentication are still UNKNOWN.
2. **Independent Authority Service:** separate Owner administration and deployment control, authenticated narrow RPC, server-derived Actor/Role/Approver binding, verification of exact C3 purpose, Index bytes and append delta, current Owner authorization and revocation, Profile/Epoch/Generation/Build bindings, fencing and transition ID. It alone executes authorized database transactions. No service is actually deployed.
3. **Spanner transaction store:** proposed strongly consistent storage primitive for Head, Role Registry, Transition Records/Events and Index History. A production implementation must recheck authorization **inside the Commit transaction**, not only at Prepare. Data storage is not itself the Owner, verifier, or external trust root.
4. **Independent Owner checkpoint + audit domain:** outside both Operator rollback privileges and Authority database restore/admin control. Records durable monotonic commitments and authenticated history head, protected by independent key/control. Currently absent; D1A used a deliberately non-durable in-memory stub.

The D1A prototype demonstrates only a research-only simulation of this topology. No production service RPC, TLS, IAM, cloud identity, independent checkpoint, real role source or tested production data isolation exists. Explicitly: **An Operator with any direct Authority-table update privilege could bypass service authorization; database transaction correctness cannot compensate for this.**

The C2 production provider continues to deny all protected writes. No change to its unconditional denial is part of D1B.

## 3. Identity, permissions, and administrative-separation matrix (PROPOSED; no grants)

| Principal/domain | Required access | Explicitly forbidden access | Owner evidence / negative probe |
|---|---|---|---|
| Candidate, Author, Reviewer, Approver | Own bounded nonprivileged workflow only | Direct Spanner access, Authority RPC write except separately approved exact role, Authority/Owner admin and recovery | Actual principal mapping + IAM permission inventory; attempts denied |
| Operator workload | Authenticated, purpose-scoped RPC to Authority; no database handle or cloud impersonation chain | Spanner SELECT/INSERT/UPDATE/DELETE/DDL, Spanner session grants, Authority service deployment, role registry admin, backup/restore, checkpoint write/admin | Real IAM deny on DML, DDL, API, service-account impersonation, endpoint substitution |
| Authority Service workload | Only the database and table privileges needed for its exact transition protocol; independent service identity | Cloud project-wide admin, IAM policy modification, Owner checkpoint admin, credential issuance, unreviewed schema migration | Enumerated effective permissions + service-auth positive/negative probes |
| Owner role/authorization registrar | Owner-approved issue/revoke under documented signing and dual control | Acting as Operator, silently rewriting historical grants, bypassing Audit/Owner adoption | Separate admin principals, expiry/revocation propagation and audit |
| Spanner database/schema administrator | Bounded break-glass/schema maintenance under separate change approval | Operator identity, checkpoint signing/admin, declaring restored backup active | Real admin policy and immutable audit; prove rollback requires external approval |
| Backup/restore custodian | Backup, restore only to quarantined new resource; never promote alone | Writeable checkpoint/admin, old restored state becoming current, rollback to arbitrary revision | Cross-account backup custody, quarantine restoration and checkpoint comparison |
| Checkpoint/audit custodian | Monotonic independent commitment, review/signing and log retention | Same rollback domain or privilege set as Operator/Authority DB administrator | Independent control-plane inventory, signed checkpoints and denial probes |
| Independent Trust Owner | Approve architecture, exact pins, role grants and formal GO/NO-GO through existing process | Delegation to candidate-authored file, Github CI bot or test identity | Documented Owner decision, exact tuple adoption and independent witness proof |

**Privilege pitfalls found in official Spanner guidance:** predefined \`roles/spanner.databaseUser\` includes broad database read/write and DDL privileges, and must not be given to the Operator. Spanner fine-grained access control can grant database object privileges through database roles, but **database-level IAM roles can take precedence** when no fine-grained role is selected; FGAC is no substitute for reviewing effective IAM, inherited roles, impersonation, service-account key creation, and administrative escalation. For the Authority Service evaluate an FGAC database role plus fine-grained IAM bindings (or a narrowly justified custom IAM policy); never presume either is sufficient without a real denial test. Sources: [Spanner IAM](https://docs.cloud.google.com/spanner/docs/iam), [Spanner fine-grained access](https://docs.cloud.google.com/spanner/docs/configure-fgac), [FGAC access semantics](https://docs.cloud.google.com/spanner/docs/access-with-fgac).

**Identity channel proposal:** evaluate short-lived service identities with Owner-managed trust roots, mTLS or independently verifiable identity tokens for Operator → Authority Service; for suitable external GCP workloads evaluate Workload Identity Federation instead of static service account keys, strictly limited to an independently owned service principal. This is a DESIGN OPTION, not an activated trust channel. [Google WIF overview](https://docs.cloud.google.com/iam/docs/workload-identity-federation).

**Separation failure:** merely using separate GCP projects while sharing a cloud Organization admin who can replace both the Authority and its checkpoint is not proven rollback-domain independence. Effective IAM includes inherited organization/folder access, impersonation, key issuance, CI deploy identities, audit/log writers and backup administrators. D1C must demonstrate absence of a principal able to modify both the Authority history and the latest independent checkpoint without independent Owner approval.

## 4. Authority contract, checkpoint, and recovery decision

All methods from C3 HighWaterAuthority—read_current, prepare_transition, verify_transition_authorization, commit_transition, abort_transition and read_transition—must keep their existing semantics. The closed purpose-to-Index mapping is unchanged: exactly one Intake row for qualification_corpus_intake; exactly one Author row for production_authoring; Owner-only epoch transition or revocation with no business rows; all other purposes denied unless separately designed and reviewed. Qualification evidence can NEVER stand in for historical authoring provenance.

**Required conditional transaction:** atomic CAS of expected sequence/head/Index SHA and revision, unique transition ID, current role validity/revocation/expiry, Owner-approved purpose and Actor, current fencing token; append immutable-intent record and Index history together with Head update. Unknown result is not success and is not a reason to issue a new Transition ID. Transaction callbacks must not invoke external checkpoint or protected filesystem side effects: SDK retries may rerun them.

**Independent checkpoint tuple (proposal, not adopted):** Authority service identity, owner/adoption reference, Genesis binding, sequence and fencing, C3 Head digest, exact Profile/Index/Build/Generation and policy epoch, revocation digest, last committed Transition ID, entire committed-history commitment or independently retained hash chain root, prior checkpoint digest, signed issuer, durable acceptance timestamp and independent monotonic position. A bare integer sequence or local HMAC key writable by the Operator is inadequate. Exact signer, format and cryptographic properties require Owner selection.

**Cross-domain gap:** the Spanner transaction and the external checkpoint advance are two separately administered operations, not one physical transaction. A DB Commit may succeed with its response lost or before checkpoint acknowledgment. Required state machine:

| Observed states | Required action |
|---|---|
| DB and independently confirmed checkpoint equal, full history valid | A verified read/transition status MAY inform synthetic protocol reconciliation; never grants production Intake |
| DB ahead of checkpoint or checkpoint unavailable | RECOVERY_REQUIRED; quarantine stage and stop new writes; no silent checkpoint promotion |
| DB behind checkpoint, restored old snapshot, divergent hash/epoch/fence/history | ROLLBACK_DETECTED / NO_GO; isolate resource; only independent Owner-controlled restore and re-adoption |
| Prepared with unexpired grant | Revalidate grant and fencing on Commit; Prepare alone never grants Commit |
| Prepared with expired/revoked role | Explicit abort if status proven; otherwise RECOVERY_REQUIRED; no automatic retry |
| Unknown Commit or missing ACK | Query same transition ID only using verified Head/History/Checkpoint; if not trustworthy, remain RECOVERY_REQUIRED |
| Coordinated rewrite by privileged DB/admin and its own audit | NOT DETECTABLY PREVENTED by Emulator/plain hashes; independent signed checkpoint/audit evidence is mandatory |
| Different Authority endpoint, identity or Genesis | Reject: never infer equivalence from DNS or a matching local file |

**Performance implication:** D1A currently verifies the full committed history for each trusted read. This may be O(history) and expensive under managed service billing; any incremental proof/cache/checkpoint optimization requires its own correctness, freshness and bounded-resource tests, and may not skip required security validation.

## 5. Alternative A: independently operated Linux Witness + etcd

Option A can provide compare-and-update and quorum-backed linearizable operations but adds multi-node deployment, patching, health, network, certificates, membership changes, backups and recoverability ownership. It does not automatically provide Owner-grant semantics, admin separation or trusted last-committed checkpoint. A single VM/SQLite or same-host restore domain is NOT an equivalent production high-water root. Etcd restore/revision bumps cannot prove the recovered application Head equals the latest independently adopted history.

**Decision criteria, not a vendor winner:** prefer Spanner ONLY if the Owner already possesses a genuinely independent cloud administrative domain, can fund the selected minimum footprint, and agrees to an Owner-controlled checkpoint/audit model. Prefer etcd evaluation if cloud ownership, networking, region/cost and IAM independence cannot be met AND an independently administered multi-node quorum/backup capability actually exists. If neither set of requirements is met, **NO-GO**—do not replace these choices with an unsafe local fallback. See [etcd API guarantees](https://etcd.io/docs/v3.5/learning/api_guarantees/) and [etcd recovery](https://etcd.io/docs/v3.7/op-guide/recovery/).

## 6. Cost, latency, retention and operational decision inputs

**No numeric price or design-region promise is authorized or asserted.** Owner must provide region, instance edition/configuration, planned processing units, chosen minimum compute capacity, projected Authority requests/sec and transactions/sec, read amplifications from full-history checks, record bytes, retention horizon, backups, log retention, networking topology, service hosting, secrets/identity, audit export, checkpoint storage, ops labor and support.

Quote a defensible monthly scenario using official current region-specific rates for compute, storage, backup, egress and optional observability; compare at least small/normal/burst workloads. For Option A include quorum-host cost, patch/backup/on-call and networking. State assumptions and worst-case budget limit, not an invented generic Spanner monthly price. Source: [Spanner pricing](https://cloud.google.com/spanner/pricing), [compute units](https://docs.cloud.google.com/spanner/docs/compute-capacity).

Required Owner-defined SLOs: availability window; p95/p99 Prepare/Commit/verified status; recovery RTO/RPO (RPO=0 cannot be claimed without full evidence), queue behavior when checkpoint offline; role-revocation maximum propagation, backup rotation and audit retention. Do not turn these blanks into default commitments.

## 7. GO/NO-GO sequence and D0 gates

**D1B:** Prepare, compare and review this unsigned design plus [real-domain evidence matrix](RQ03F_B3D1B_REAL_DOMAIN_VALIDATION_MATRIX.md). Owner reviews proposal. No production GO.

**Owner architecture gate (D0-01/D0-02/D0-10):** an independent Owner must choose the architecture, identity/control-plane/backup isolation, proposed checkpoint custody and allowable spend. Written decision is separate from GitHub merge. WITHOUT THIS, D1C production adapter authorization remains **NO-GO**.

**Possible separately authorized D1C:** Develop a production-intent adapter in Codex Cloud only AFTER architecture selection, retaining C2 unconditional write rejection. First execution on a separately Owner-owned, expressly approved non-production account/cluster with real IAM and recovery drills. A developer's cloud account or Emulator can never substitute for that independent domain. D1C scope needs fresh Owner review.

**Target-host acceptance:** D0 A–L remain NO_GO. A–G are real host/Authority evidence; H formal qualification Intake requires independent later business approval; I never fabricates historical author identity; J never upgrades qualification custody to production provenance; K requires real backup/restore; L requires a separate independent Trust Owner signature. Profile 1.1 / Index 1.1 / Build / Generation / Policy Pin / Genesis are unissued. Do not infer expiry extension or Owner admission from merged D1A.

**Hard stop:** no production Authority service, real Operator-host provisioning, role grants, cloud account/IAM changes, protected writes, Agent A/B, Live Qualification, RC-02, Lesson Skill 2.4, release, Codex Review or historical Trust Anchor edits in D1B.

## 8. Owner decision register — unsigned, unanswered

| Decision ID | Required independent Owner choice | Current status |
|---|---|---|
| D1B-01 / D0-01 | Spanner service vs independently administered Linux+etcd vs NO-GO | OWNER_DECISION_REQUIRED |
| D1B-02 / D0-02 | Who controls service, project/org, IAM, backup, restore, checkpoints, audit, security reviews? Prove separation beyond account names | OWNER_INPUT_REQUIRED |
| D1B-03 / D0-10 | Who holds signed independent checkpoint, Genesis and revocation registry? How is ahead/behind divergence resolved without bypass? | OWNER_INPUT_REQUIRED |
| D1B-04 | Target Linux host and Operator/Authority real process/workload identity, security channel/rotation | OWNER_INPUT_REQUIRED |
| D1B-05 | Region, budget cap, minimum deployed footprint, cost owner and procurement permission | OWNER_INPUT_REQUIRED |
| D1B-06 | Availability/latency/RPO/RTO, worst-case history growth and retention limits | OWNER_INPUT_REQUIRED |
| D1B-07 | Auth issuer/role and revocation authority; current historical grants expire 2026-10-16T11:00:00Z | NOT AUTHORIZED TO EXTEND |
| D1B-08 | Whether to authorize non-production **real IAM** verification on an independently controlled account | NOT AUTHORIZED |
| D1B-09 | Whether to authorize any subsequent D1C production-adapter engineering changes | NOT AUTHORIZED |
| D1B-10 | Real A–L adoption, exact production pins, formal Intake and business operations | NO_GO — SEPARATE FUTURE DECISIONS |

The Owner has not answered any of these by permitting this document to be drafted or reviewed. Sign-off field: **OWNER_INPUT_REQUIRED**.

## 9. Source and review honesty

Vendor documentation proves the **availability of features** only; our repository evidence proves **research behavior** only. No IAM denial, production mTLS, independent cloud project, admin-collusion resistance, durable checkpoint, recovery after disaster, actual provider cost, production role grant or host-specific security result was tested. Evidence placeholders must stay NOT_RUN until independent artifacts are available.

**Final D1B disposition:** ARCHITECTURE PACKET PROPOSED / D0-01, D0-02, D0-10 UNDECIDED / PRODUCTION_TRUST_BLOCKED / LIVE_QUALIFICATION_NO_GO.
