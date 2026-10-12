# RQ-03F-B3-D1B — Independent Trust-Domain Validation and Decision Matrix

**Disposition: TEST DESIGN ONLY / NOT_RUN — REAL_OWNER_DOMAIN_REQUIRED / PRODUCTION_TRUST_BLOCKED.** Companion to [B3-D1B architecture package](RQ03F_B3D1B_AUTHORITY_ARCHITECTURE_DECISION.md) and [Issue #66](https://github.com/ArdenZC/codex-work-skills/issues/66). No test in this matrix has run in an independent GCP project or on a production Linux host. D1A Emulator assertions are synthetic, not proof of these results.

## 1. Future evidence requirements

Every actual test, if independently authorized in a later work package, must record: exact source/adapter HEAD and Tree, independent Owner-approved target project/account and region (redact secret identifiers as necessary), trusted timestamp/identity, actor/principal and effective inherited IAM, request ID/transition ID, previous and resulting Head sequence/digest/Index SHA, external signed checkpoint/history head, approval/grant/revocation reference and expiry, positive/negative outcome, independent audit reference, unchanged state on rejected writes, cleanup and continued disabled C2 service. A request-side or Emulator assertion is not a substitute for server-side IAM evidence.

**No D1B steps run cloud commands.** The tests below are descriptive contracts, not executable setup instructions or approved permissions. An independently retained denial record is more useful than a simulated principal rejection.

## 2. Real-domain negative and positive contracts

| Test | Future independent actors / scenario | Must prove, on exact real domain | Failure result / current state |
|---|---|---|---|
| T01 Operator direct DML | Real Operator workload attempts direct AuthorityHead/Transition/Role Registry writes | IAM/network boundary rejects; verified DB/Checkpoint remain byte-identical | Any direct DML succeeds => NO_GO; NOT_RUN |
| T02 Operator direct DDL | Operator attempts CREATE/ALTER/DROP on Authority database | Explicit denial, including inherited databaseUser/databaseAdmin/Owner roles | Any schema modification possible => NO_GO; NOT_RUN |
| T03 Impersonation/key path | Operator/Candidate attempts to impersonate service account or issue keys/tokens | No privilege via IAM inheritance, WIF mapping, key creation, service deploy or CI identities | Escalation => NO_GO; NOT_RUN |
| T04 Other business principals | Candidate, Author, Reviewer, Approver attempt protected database and service operations | All unapproved scopes fail closed, real principal identity independently verified | Business role can bypass Authority => NO_GO; NOT_RUN |
| T05 Unknown/forged client | Missing, expired, revoked, forged client credential | Authority Service refuses prior to transaction; no new records; auditing preserved | Success/unknown identity => NO_GO; NOT_RUN |
| T06 Server/endpoint substitution | Correct Operator caller targets wrong DNS, TLS peer, certificate, or service identity | Fixed Owner pin and peer auth reject redirect/rebinding | Client accepts substitute => NO_GO; NOT_RUN |
| T07 Grant expiry at Commit | Valid Prepare, permission expires before Commit | Current independent Owner role source checked atomically at Commit; no Index mutation | A committed write => NO_GO; NOT_RUN |
| T08 Grant revoked at Commit | Valid Prepare, role/reference revoked before Commit | Immediate fail-closed under defined revocation propagation budget | A committed write => NO_GO; NOT_RUN |
| T09 CAS/ABA/revision | Two writers; stale state digest, old Index SHA/revision, duplicate ID or stale fence | Exactly one winner; loser denied; no distinct second business effect or stale replay | Multiple success => NO_GO; NOT_RUN |
| T10 Mixed purpose | Intake proposal inserts Author/Receipt/Qualification Run or mismatched Actor | Service checks exact C3 closed delta, Actor and operation ID | Wrong record accepted => NO_GO; NOT_RUN |
| T11 Commit ACK loss | Commit reached DB, response lost, same-ID status read | Verified Head/history/checkpoint before a trusted committed result; no new-ID retry | False committed/duplicate effect => NO_GO; NOT_RUN |
| T12 DB ahead of checkpoint | DB committed, independent checkpoint update failed or lagged | RECOVERY_REQUIRED, service stops protected writes and preserves exact stage | Auto-advance checkpoint => NO_GO; NOT_RUN |
| T13 DB behind checkpoint | Restore old Spanner Head/history to quarantined database | Detect rollback against independently owned signed checkpoint; do not promote resource | Old restored state becomes active => NO_GO; NOT_RUN |
| T14 Missing/coherently rewritten history | Delete/alter history or modify multiple records with recomputed ordinary hashes | Independent checkpoint/audit binding detects if promised by chosen design; otherwise explicitly remains UNVERIFIED | Unsupported tamper-resistance claim => NO_GO; NOT_RUN |
| T15 Service/IAM administrator crossover | Attempt control-plane access across Operator, Authority deployment, DB admin, checkpoint and backup owners | No single Operator-controlled or Authority DB-admin-controlled principal can replace both current history and independent checkpoint | Shared uncontrolled admin => NO_GO; NOT_RUN |
| T16 Backup/restore custody | Separate backup admin restores new/quarantined DB under partial IAM | No access/promotion to current service without independent Owner re-adoption | Unchecked restored DB active => NO_GO; NOT_RUN |
| T17 Endpoint outage/retry | Authority unavailable mid-request, real Spanner conflict/retry/timeout | No external side effects in retryable callback; typed rejected/committed/unknown outcomes | Retry creates duplicate write => NO_GO; NOT_RUN |
| T18 Revocation and incident audit | Owner revokes role, changes service key, triggers denied request | Identity/role/permission change and denial recorded in separately retained audit evidence | Logs editable by implicated Actor => NO_GO; NOT_RUN |
| T19 Production host isolation | Real Operator/Candidate/Author/Reviewer/Approver processes | Actual UID/GID/ACL/module/runtime/locked Launcher/pinned paths and separate Authority administrative domains | Hosted UID evidence substituted => NO_GO; NOT_RUN |
| T20 Performance/cost | Owner-defined small/normal/burst traffic and historical ledger size | p95/p99, history read growth, Spanner transaction retries, storage, checkpoint/egress and OPEX under Owner limits | No cost/latency budget evidence => NO_GO; NOT_RUN |

No test passes by assertion alone. Baseline D1A research Emulator suite (39 passing) remains classified **SYNTHETIC_ONLY**.

## 3. Owner authority separation matrix

| Resource/decision | Operator/Candidate | Authority Service | DB/schema admin | Independent checkpoint and audit custodian | Independent Trust Owner |
|---|---|---|---|---|---|
| Request narrow protected operation | Proposed constrained RPC only | Validate Actor, purpose, grant and transition | No action | Observe signed commitment | Separately authorize future business scope |
| Write Authority Head/history | **DENY** | Scope-limited DB transaction only | Maintenance by independently approved change, never unilateral production adoption | Cannot rewrite database | Approve exact schema/runtime/process |
| Administer service identity/Owner registry | **DENY** | **DENY** self-grant or deployment privilege | **DENY** or segregated change control | **DENY** role signing unless separately approved | Approve identity and grants |
| Advance independent high-water | **DENY** | Conditional submit-only to Owner service; no admin/reset | **DENY** | Verified monotonic acceptance, signing and retention | Approve checkpoint root / Genesis |
| Backup and restore | **DENY** | Read-only status, no restore privilege | Distinct backup custodian and quarantined restore only | Retain independent latest checkpoint | Approve re-adoption |
| Activate live production trust | **DENY** | **DENY** | **DENY** | **DENY** | Explicit independent A–L GO only |

This is a **proposed policy matrix**, not a claim of existing identities, valid permissions, direct cloud connectivity or an implemented separation.

## 4. A–L crosswalk and staged release

| Gate(s) | D1B work product | Independent missing proof / current verdict |
|---|---|---|
| A–C | OS / Actor / filesystem and role separation design | Real principal UID/GID/ACL and admin domain tests; NO_GO |
| D–F | Exact runtime, code, Build Inventory, Profile/Index, Policy Pin plan | Final target bytes, independent Owner adoption and migration lineage; NO_GO |
| G | Real independent Authority, revocation, checkpoint and rollback test plan | All T01–T18 NOT_RUN in real domain; NO_GO |
| H | Contract states exact single qualification_corpus_intake operation only | Separate explicit future custodian grant and formal Owner business authorization absent; NOT AUTHORIZED |
| I | No inferred historical Authors | Formal source has zero Author evidence; do not fabricate provenance; NO_GO |
| J | Keep qualification-only proof separate | C2 protected writes deny; true production scopes unapproved; NO_GO |
| K | Quarantine backup/restore and unknown-status policy | T11–T18 real evidence absent; NO_GO |
| L | Unsigned Owner decision register | Only independent Owner can sign/adopt exact tuple; NO_GO |

## 5. Owner inputs — no defaults or fabricated values

| Owner input | Purpose | Current state |
|---|---|---|
| Selected backend/service, independent admin owner, approved target/project and cost liability | D0-01 / D0-02 | OWNER_INPUT_REQUIRED |
| Checkpoint custody, signer, durability/append protocol, Genesis and revocation source | D0-10 | OWNER_INPUT_REQUIRED |
| Real Service/Operator identities and trust roots; WIF/OIDC/mTLS selection | AuthN/authZ and revocation | OWNER_INPUT_REQUIRED |
| Authorized non-production cloud test scope and maximum budget | T01–T18 execution | NOT AUTHORIZED |
| Target OS/runtime build, deployment roots, UID/GID, policies | A–G qualification | OWNER_INPUT_REQUIRED |
| p95/p99 target, RPO/RTO, growth and audit retention | Cost and recovery GO | OWNER_INPUT_REQUIRED |
| Whether D1C engineering may begin, and its own permitted scope | Separate future Owner authorization | NOT AUTHORIZED |

Historic Profile 1.0 grants expire at **2026-10-16T11:00:00Z**; this package does not renew them.

## 6. Decision record (unsigned)

- **Recommended evaluation order:** Option B Spanner-backed Authority Service conditional on real IAM/Owner independence, cost limits and durable external checkpoint; independently administered Linux/etcd as alternative if those conditions cannot be satisfied but a real quorum operating capability exists.
- **Formal selection:** NONE.
- **D1C production-intent engineering GO:** NO_GO.
- **Real non-production cloud IAM testing GO:** NO_GO unless separately authorized.
- **Production Trust / formal Intake / Agent A/B / Live Qualification / RC-02 / Lesson Skill 2.4:** NO_GO.
- **Independent Owner signer, adopted SHA / timestamp / approval reference:** OWNER_INPUT_REQUIRED.

The existence, CI success, or later merge of this document MUST NOT count as a decision, signature, Role grant, production Pin or valid Authority Identity.
