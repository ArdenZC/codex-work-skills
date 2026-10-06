# Semantic Scope Review Contract 1.0 — RQ-03N design

Status: proposed normative contract, awaiting Owner Review. Trusted production
master: `91ded51a2aa7668ba5eec8b70027b018eb03675d` (PR #46 MERGED / QUALIFIED,
post-merge run `37421609102`). This document activates no runtime behavior.
RQ-03 and RC-02 remain BLOCKED. RQ-03O, NC-01 and Lesson 2.4.0 are not started.

## 1. Authority and independent review

Agent/Human reviewers judge instructional meaning. Python validates structure,
identity, coverage, hashes, binding, stale evidence, lifecycle and transactions.
Source Truth integrity, frozen outline equality, course_scope_grounding,
intra-Lesson coherence, Content QA and lexical contamination signals remain
mandatory defense in depth. None proves the absence of arbitrary foreign
instruction in free text. Review PASS cannot replace Human Teacher Review,
render verification or Final Acceptance, and cannot generate human approval.

An independent operation reads the **frozen final candidate**, the entire
relevant Source Truth manifest and its verified sources, the frozen whole-course
outline, and every Lesson including previous/next progression. It reviews every
Lesson, not the Teacher Packet sample. It distinguishes actual instructional
operations from application-domain nouns, and current instruction from an
explicit next_bridge. It checks foreign instruction, mixed instructional intent,
neighbor leakage, task drift, deliverable drift and new unallocated objectives.

Independence requires a separate invocation/review operation, a different logical
reviewer principal from the authoring principal, read-only candidate access and
isolated review context. A different model/provider is neither required nor
sufficient. The same underlying model may serve different independently tracked
invocations. A human reviewer may serve as semantic reviewer and later teacher,
but must not be the authoring principal and must record the two decisions
separately. The authoring pass cannot issue its own scope approval.

Content 2.2/2.3 `authoring_provenance.authoring_id` is an authoring identifier,
not authenticated actor identity. Repository-level 多Agent兼容规范.md describes
provider-neutral adapters and Agent/script responsibilities, not an independent
review-operation registry or authenticated reviewer identities. Existing Benchmark `separate_contexts`
attestations are a useful convention, not proof of identity/isolation. Existing
Teacher Review lacks an identity field. New identity fields are not self-proving:
a trusted orchestration controller must record actual operations and enforce
separation. Author/reviewer principals cannot mint controller receipts.

The future controller supplies an independently authenticated **operation receipt**
(1.0) to the lifecycle inventory. It binds the raw review SHA, input SHA values,
run ID, Content authoring_id, actual author/reviewer principals, operation IDs,
reviewer configuration and independence attestations. The same receipt framework records semantic screening and final human approval
as separate operations, not a second human-review system. The receipt uses a
controller signature verified against an operator-configured trust root, never
a key supplied solely by the report. Freeze Ed25519 signature over existing
lifecycle canonical JSON bytes excluding only `signature`; fields are:
`contract_version="1.0"`, `receipt_id`, `review_kind` (`semantic_scope` or
`teacher_approval`), `pipeline_run_id`, `review_sha256`,
`source_truth_manifest_sha256`, `outline_sha256`, `content_sha256`, `authoring_id`,
`author_principal`, `author_operation_id`, `reviewer_principal`,
`review_operation_id`, `reviewer_configuration_sha256`,
`reviewer_qualification_sha256`, `isolation` (all true: `separate_invocation`,
`author_reasoning_hidden`, `candidate_read_only`), `recorded_at`, `signer_key_id`,
`signature` (base64 Ed25519 bytes). Identity strings/IDs are nonblank, <=160
characters; signature is 64 decoded bytes; timestamp is timezone-aware.
The external receipt points to the report; the report does not point to the
receipt hash, avoiding a hash cycle. Teacher Packet and Teacher Review bind the semantic report and its receipt; PA
binds both plus the separate human approval receipt. Each receipt kind must match
its actual artifact, operation and role; a teacher_approval receipt must record an
authenticated human principal and a review operation different from the scope
operation. No self-asserted human type grants authority. Controller capture/signing belongs to a
future provider-neutral adapter; no controller, signing code or key is added now.

Python can check receipt authenticity, distinct identities/operations and input
binding. It cannot prove cognitive independence, actual model prompt visibility
or semantic correctness from metadata. Controller behavior and reviewer
configuration need qualification and human oversight; hashes are not authority
signatures. A configuration without trusted capture is unavailable for PRODUCTION.

## 2. Formal report fields

Artifact: `semantic-scope-review.json`. All objects are closed
(`additionalProperties=false`); all fields below required. JSON Schema draft
2020-12 is the future schema dialect. This table is the schema design, not an
installed schema. Strings have Unicode character limits; nonblank means at least
one non-whitespace character. No probability/confidence or chain-of-thought field.

| Object / field | Type and bound | Meaning |
| --- | --- | --- |
| contract_version | const `1.0` | Independent review contract |
| review_id, pipeline_run_id | nonblank string, 1..128 | Immutable operation/run linkage |
| review_purpose | `production_candidate` or `qualification` | Qualification reports never authorize production |
| content_contract_version | `2.2` or `2.3` | Matches exact candidate |
| source_truth_manifest_sha256 | lowercase hex, 64 | Exact manifest bytes |
| outline_sha256 | lowercase hex, 64 | Exact local frozen whole-course outline file bytes |
| content_sha256 | lowercase hex, 64 | Exact complete final Content file bytes |
| authoring_id | nonblank string, 6..160 | Exact Content provenance identifier |
| reviewer | closed object below | Actual reviewer operation |
| whole_course_disposition | disposition enum below | Submitted cache, recomputed and compared |
| lessons | array, 1..N | Exactly N candidate Lessons, frozen outline order |
| reviewed_at | timezone-aware date-time | Review completion |
| review_fingerprint | lowercase hex, 64 | Lifecycle canonical semantic fingerprint |

Reviewer fields: `type` (`agent`/`human`), `identity` (1..160), `operation_id`
(1..128), `implementation` and `version` (1..160 each),
`configuration_sha256` (lowercase 64-hex), `qualification_sha256` (lowercase
64-hex for production_candidate; null permitted only for qualification).
Identity is a controller-resolved principal, not a model brand. Agent
implementation/version identify the adapter/model configuration; human entries
identify the controlled review interface/procedure/version. Qualification binds
the reviewer configuration to approved corpus evaluation or, for human reviewers,
the authorized scope-review procedure. Provider is not a required field; neutral
configuration evidence may record provider/model metadata without schema changes.
Changes to adapter/model/prompt/configuration require requalification, not just
renaming an identity. Qualification/signing receipts are evidence, never a score. A qualification
operation may have null qualification_sha256 and its receipt may have null
reviewer_qualification_sha256: qualification evidence is issued only after the
evaluation finishes. This avoids a self-binding bootstrap cycle. Such a report
or receipt can never satisfy PA; production_candidate requires actual pre-existing
approved qualification bytes under the configured trust root.

Every Lesson entry is closed with `lesson_id` (1..128), `disposition`,
`rationale` (1..600), `source_references` (1..16 references), `issues` (0..128).
A PASS entry has zero issues and a bounded affirmative rationale grounded in its
current task/output. A non-PASS entry has at least one issue. N is derived from
actual Lesson-bearing Content; zero-Lesson practice_only stays outside the
canonical Lesson chain. Array counts never cap or sample course coverage.

Every issue is closed with `issue_id` (1..128, unique across course), `category`,
`disposition` (only `REVISION_REQUIRED`/`HUMAN_REVIEW_REQUIRED`), `location`,
`bounded_excerpt` (1..320), `rationale` (1..600), `source_references` (1..16).
Category enum: `foreign_instruction`, `neighbor_lesson_leakage`, `scope_expansion`,
`deliverable_mismatch`, `mixed_instructional_claim`, `ambiguous_scope`.
`ambiguous_scope` requires HUMAN_REVIEW_REQUIRED. Other categories may carry an
ambiguity disposition when evidence cannot establish a definite defect. There
are no profession-specific categories or lexical dictionaries.

`location` is closed: `field` (RFC 6901 JSON Pointer, 1..512, relative to the
containing Lesson), `index` (integer >=0 for array item; null for scalar field),
`start` and `end` (Unicode code-point offsets, 0 <= start < end). The pointer
resolves a scalar string or an array whose index resolves a string. All semantic
prose may be referenced, including nested stages/actions/objectives, goals,
student_analysis, teaching methods, resources, evaluation and reflection, not
only teaching_content. The excerpt must equal the exact located substring;
excerpt bounds cannot be used to limit the claim examined. A mixed claim spanning
more than 320 characters uses multiple linked issue locations; review still
judges the whole instructional operation without requiring punctuation splits.

A source reference is closed with `source_id` (1..128), `sha256` (lowercase
64-hex), `pointer` (RFC 6901 string, 0..512), `start`, `end` (nullable code-point
offsets, both null unless referencing a verified text substring). source_id must
exist in the actual frozen manifest and sha256 equal its verified bytes. For
JSON sources, pointer must resolve; for non-JSON sources pointer is empty and
any offsets must reference the frozen UTF-8 text. Other binary sources may be
referenced as a whole with null offsets. The whole-course outline is referenced
through its manifest source_id; a neighboring Lesson reference must identify its
actual frozen row and explain why it is neighbor context rather than current
instruction. No invented references, URLs or whole-lesson copies in rationales.

## 3. Dispositions and deterministic derivation

Enum: `PASS`, `REVISION_REQUIRED`, `HUMAN_REVIEW_REQUIRED`.
A definite out-of-scope instructional claim requires REVISION_REQUIRED even
alongside legal instruction in the same node, sentence or unpunctuated clause.
Ambiguity never automatically becomes PASS. No confidence threshold grants
Production Authorization.

For each non-PASS Lesson, derive its disposition from issue dispositions:
any REVISION_REQUIRED wins; otherwise HUMAN_REVIEW_REQUIRED. For the course:
any REVISION_REQUIRED Lesson wins; otherwise any HUMAN_REVIEW_REQUIRED wins;
otherwise PASS. Validate both submitted Lesson and course caches against these
rules. A course PASS cannot hide a missing Lesson, issue or invalid reference.
The reviewer remains responsible for finding issues: deterministic derivation
cannot detect a semantic issue that the reviewer failed to record.

Keep judgment separate from validation outcome: `VALID`, `STALE`, `INVALID`
follow existing lifecycle conventions. Missing report is MISSING; unavailable
reviewer is UNAVAILABLE. Neither is a semantic PASS. Malformed schema, inconsistent
derivation, forged receipt, invalid location/coverage or unsupported version is
INVALID. Internally valid evidence with changed upstream binding is STALE.
Every non-VALID condition blocks production; unverified source bytes cannot PASS
the production authority chain.

## 4. Binding, invalidation and revalidation

Hash exact raw bytes for manifest, frozen outline and full candidate. Verify the
entire Source Truth source inventory offline, course identity, local outline
source digest, and existing canonical equality/self-snapshot checks. The existing
Content canonical-outline self digest is not substituted for outline_sha256.
Changing JSON whitespace changes a raw binding and invalidates downstream
review even when canonical semantic fingerprint stays equal.

review_fingerprint reuses lifecycle NFC/canonical JSON rules, excluding only
reviewed_at and review_fingerprint; ordered Lesson/issue/reference arrays are
preserved. Downstream consumers bind raw report and raw receipt SHA, not just
this fingerprint. Actual files must be ordinary, safe, distinct files under
existing path/alias/symlink rules; hash strings in state cannot replace files.

Content revision (including teacher edits), Source Truth replacement, any source
byte mutation, outline regeneration/replacement, or canonical Content rebinding
invalidates the old review for the changed candidate. A new run ID also prevents
review reuse even if candidate bytes match. An explicitly repeated read-only
binding of identical bytes in the same immutable run is not a new candidate;
a different-byte rebind is prohibited by current immutable-run policy.

Dependency additions: Source Truth/frozen outline/Content -> semantic review;
review/receipt/qualification -> Teacher Packet/Teacher Review -> PA -> output,
Artifact QA, Visual Review and Acceptance. Any review raw-byte/receipt/configuration
change also invalidates resolution and PA. Every status/resume/transition,
authorize and pre-publication check rereads evidence and validates freshness.
A teacher-requested revision requires a new final candidate, independent semantic
review and new Human Teacher Review/authorization; old teacher approval or
ordinary notes cannot patch this chain. Existing forward-only state history is
not rewound: create a successor immutable run, retaining stale history for audit.
A Source Truth/outline plan change likewise requires a new frozen plan and run.

## 5. Human escalation in the existing Teacher Review

Teacher Review 1.0 `whole_course_review.scope` has only assessment/notes. It has
no semantic report hash, issue IDs, per-issue resolution, authenticated human
identity or resolution binding. Ordinary APPROVED/APPROVED_WITH_NOTES is therefore
insufficient to resolve HUMAN_REVIEW_REQUIRED. Add explicit fields in a future
Teacher Review 2.0 rather than a parallel human-review service.

Teacher Review 2.0 retains all current human usability/course assessments and
decisions, and adds a closed `semantic_scope` object with:
`contract_version="1.0"`, `review_sha256`, `operation_receipt_sha256`,
`outline_sha256`, `human_reviewer` (`identity`, `review_operation_id`,
`authority_reference`, each nonblank 1..160), and `resolutions`.
Existing run/source/content bindings remain mandatory. The controlled human
review ingress must authenticate the named authorized teacher; an agent cannot
satisfy it by declaring type=human. Its teacher_approval operation receipt must bind exact Teacher Review bytes,
input hashes, named human identity/operation and the operator-authorized review
procedure under the same configured controller trust root. authority_reference
resolves that unique immutable receipt ID; the run inventory binds its raw SHA.
Existing code only accepts externally supplied human review evidence and does
not implement this authenticated capture; this is a future extension of that
ingress, not a claim about current authentication. Generic notes are never authority.

Each resolution is closed: `issue_id`, `decision` (`RESOLVED_IN_SCOPE` or
`REVISION_REQUIRED`), `bounded_rationale` (1..600), `source_references` (1..16,
same definition), `resolved_at` (timezone-aware). Resolve every ambiguity issue
across all Lessons, including outside the teacher's deterministic sample, exactly
once. Missing/duplicate/unknown issue IDs fail closed. PASS reports require an
empty resolutions array. A teacher cannot override a definite REVISION_REQUIRED
issue; content must change and be independently re-reviewed. No waiver decision.

For unchanged candidate bytes, explicit RESOLVED_IN_SCOPE may settle ambiguity
without another AI invocation. The original report remains HUMAN_REVIEW_REQUIRED;
Python derives an **effective whole-course disposition** from that report and
valid human resolutions: unresolved ambiguity remains HUMAN_REVIEW_REQUIRED;
any definite issue/human REVISION_REQUIRED yields REVISION_REQUIRED; otherwise
PASS. General human decision must separately be APPROVED or APPROVED_WITH_NOTES.
Even a Semantic Scope Review performed by a human does not manufacture this
separate final Teacher Review approval.

Teacher Packet 2.0 adds raw report/receipt/outline bindings and a deterministic
complete issue index with locations, bounded evidence and disposition. Existing
Lesson selection policy and sampling quotas remain unchanged; the issue index
includes every ambiguity Lesson outside the sample. Preparation only produces
inputs, never human decisions. A resolution using changed Content is STALE,
not an overlay or an implicit approval. Avoid digest cycles: Teacher Review
binds raw semantic report/receipt; neither report/receipt binds Teacher Review.
PA binds all of them and derives effective PASS after Teacher Review.

## 6. PREVIEW, PRODUCTION and PA design

PREVIEW may author, bind structurally valid Content, inspect QA and missing or
unresolved semantic-review diagnostics. Status must explicitly display
`not production authorized`, review validation/disposition and missing/stale
inputs; it cannot call the candidate release-ready or issue PA. No relaxed review
can publish a production candidate. Existing PREVIEW prohibition on authorize /
production generation stays. Reaching READY_FOR_TEACHER_REVIEW requires a valid
complete semantic report (PASS or HUMAN_REVIEW_REQUIRED), even in PREVIEW;
missing evidence can remain at QA for inspection, not fabricate readiness.

Future canonical PRODUCTION requires verified local Source Truth/outline,
existing deterministic QA, valid authentic independent report/receipt for the
exact final Content and a qualified reviewer configuration. Missing, malformed,
stale, unresolved, unavailable or REVISION_REQUIRED evidence blocks PA and all
production generation/publication. Deterministic scope PASS is no fallback.
HUMAN_REVIEW_REQUIRED can reach the human escalation input stage, but cannot
be authorized until explicit bound human resolution derives effective PASS.

PA 2.0 adds a closed `semantic_scope` object: `contract_version="1.0"`,
`review_sha256`, `operation_receipt_sha256`, `outline_sha256`,
`reviewer_qualification_sha256`, `human_authority_receipt_sha256`,
`effective_whole_course_disposition="PASS"`.
Existing raw manifest/Content/Teacher Review hashes remain. PA verifies actual
report, receipt, qualification, identity/isolation, full coverage, derivation,
source/content/outline/run/version bindings, authenticated teacher_approval
receipt and Teacher Review 2.0 approval;
it recomputes effective PASS and does not trust the PA cache. Legacy PA 1.0 or
Teacher Review 1.0 can be read for historical audit, never used as a downgrade
path for the new canonical production gate. Benchmark waiver cannot waive scope.

Validate these dependencies before a generator candidate directory is created,
again during resume and immediately before publication. Missing/stale/rejected
scope evidence means no PA, no candidate publication, byte-identical old output
and no leftover backup/staging artifacts. Existing transaction rollback and
lock/path safety remain mandatory. A controller receipt authenticates provenance,
not the truth of a semantic decision; independent reviewer qualification and
final human approval remain separate obligations.

## 7. Pipeline and version impact recommendation

Current pipeline uses PREPRODUCTION_QA_PASSED -> optional
BENCHMARK_REVIEW_COMPLETE -> READY_FOR_TEACHER_REVIEW ->
TEACHER_REVIEW_APPROVED -> PRODUCTION_AUTHORIZED, with immutable bindings,
forward-only replay, actual-file authority validation and transitive staleness.
Current disposition-only Benchmark binding can directly advance to READY.

Retain the existing state vocabulary; do not add a PASS state that would incorrectly
exclude legitimate human escalation. Insert a mandatory artifact-bearing review
stage before READY: future `bind-semantic-scope-review` records reviewed report
and authenticated operation receipt while staying at the pre-READY state.
Both Benchmark paths must stop auto-advancing to READY until all required evidence
is bound; a single readiness gate checks existing Benchmark policy plus VALID
semantic PASS/HUMAN_REVIEW_REQUIRED. REVISION_REQUIRED cannot advance.
At TEACHER_REVIEW_APPROVED and every later stage, effective semantic PASS and
actual human approval are rechecked. State strings/fingerprints cannot bypass
file authority validation. Add review/receipt/outline/qualification/human-approval-receipt bindings to
state artifacts and run inventory; review binding publishes atomically under
existing locks. No backward transition or same-state history entry is invented.

| Contract | Current | Future recommendation / reason |
| --- | --- | --- |
| Semantic Scope Review | absent | New 1.0 independent sidecar |
| Operation receipt | absent | New 1.0 provider-neutral controller provenance |
| Pipeline State | 1.0 | 2.0: new mandatory bindings and stricter READY/authorization policy |
| Orchestrator envelope | implementation 1.0 | 2.0 dispatch/validation policy; no silent replay of 1.0 as new authority |
| Production Authorization | 1.0 | 2.0: mandatory semantic dependency breaks old payload authority |
| Teacher Review | 1.0 | 2.0: required semantic binding, identity and explicit resolutions |
| Teacher Packet | 1.0 | 2.0: required complete issue index and report/receipt links |
| Content / Source Truth | 2.2/2.3 / 1.0 | No bump; final bytes and existing outline source bind independent sidecars |
| Lesson Skill / Template | 2.3.1 / 1.1.2 | Frozen release identities; no 2.4 migration |
| Acceptance | 3.0 | Identity frozen now; future PA/Teacher dependency validation and compatibility audit required |

Mandatory authority changes warrant major lifecycle contract recommendations
rather than claiming backward-compatible minor optional fields. None is applied
in RQ-03N. Existing Content fields/prose/digests do not gain semantic review
fields. Existing standalone historical generator behavior is not silently
redefined by this design; future scope-qualified canonical claims require the
new gate, and unscoped calls cannot claim semantic review qualification.

## 8. Golden corpus truth and future reviewer qualification

Each future corpus case freezes case ID, raw Content/Source Truth/outline bytes
and SHA, current task/output/progression truth, expected per-Lesson/course
outcome, expected issue locations/categories, purpose and reviewer-visible
inputs. Owner-approved truth is fixed before evaluation; failures cannot be
removed or relabeled to improve results. No model is run in RQ-03N.

| ID | Frozen truth / teaching operation | Expected scope disposition |
| --- | --- | --- |
| N01 | Original byte-identical NC-02; raw SHA `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`, nursing teaching inserted into database Lesson | REVISION_REQUIRED / foreign_instruction |
| N02 | Same node contains valid SQL plus nursing operation, including one unpunctuated mixed sentence | REVISION_REQUIRED / mixed_instructional_claim |
| N03 | Foreign instruction connected only through generic/transitive bridge overlap | REVISION_REQUIRED / foreign_instruction |
| N04 | Patient-data context introduces measuring blood pressure or infusion procedure as an instructional operation | REVISION_REQUIRED / foreign_instruction |
| N05 | L14 structure-combination body makes L15 performance assessment a current objective | REVISION_REQUIRED / neighbor_lesson_leakage |
| N06 | Current task instructs creation of an unallocated foreign deliverable | REVISION_REQUIRED / deliverable_mismatch |
| P07 | Patient-information tables with SQL querying/indexing; no nursing operation | PASS |
| P08 | Financial/order records with SQL aggregation; no accounting instruction expansion | PASS |
| P09 | Legitimate multidisciplinary data/application context while allocated operation/output remain unchanged | PASS |
| P10 | Demonstration/practice forming the allocated current deliverable | PASS |
| P11 | Reviewed L05 stack/queue and L06 boundary/error validation fixtures from merged PR46 | PASS |
| P12 | Realistic full-course prose, >=32 Lessons, legal adjacent bridges; every Lesson reviewed | PASS |
| A13 | Source Truth leaves an instructional operation's allocation genuinely unclear; no definite defect established | HUMAN_REVIEW_REQUIRED / ambiguous_scope |
| P14 | L14 next_bridge legitimately mentions next-Lesson performance work without teaching it now | PASS |

Normative minimal claim examples (context/task/output above remain mandatory):
N02 `用 SQL 查询患者记录后测量患者血压并实施输液` has no punctuation boundary,
yet requires revision. N03 `依据本课记录执行输液护理并复核数据库结果` remains
foreign instruction despite generic record/bridge overlap. N04 `以患者信息表为依据
示范静脉输液和用药观察` teaches nursing rather than querying data. N06
`提交输液操作记录` mismatches a frozen SQL-query-result deliverable. P07
`查询患者信息表并解释索引对检索的作用` and P08 `用 SQL 汇总财务订单金额并说明分组
条件` retain database operations. P09 may associate equipment/patient identifiers
with SQL while teaching no medical or mechanical operation. A13's `根据记录执行
处置并说明依据` escalates when frozen sources do not clarify what “处置” allocates;
it is not relabeled a definite nursing operation merely because patient data is
present. These are corpus claim definitions, not executed model evaluations.
P12 must use owner-approved realistic prose; a toy synthetic course cannot alone
satisfy that qualification case.

N01 is verified locally against recovered original bytes, Content 2.3, one Lesson;
never substitute the later result-collision synthetic negative or rewrite it.
Associated original frozen source/outline evidence must accompany it. N01 must
produce REVISION_REQUIRED in reviewer qualification even if another deterministic
gate also rejects. Future canonical end-to-end qualification must REJECT, issue
no PA, preserve old output bytes and leave no staging/backup leak; it does not
require course_scope_grounding alone to prove rejection. Qualification-purpose
reports/test receipts never authorize actual production.

Future qualification uses the entire mandatory corpus plus a frozen independent
blind holdout of realistic long-course and application-context cases from at
least three course contexts. At least three fresh independent invocations per
case/configuration must exactly match expected disposition; all negatives must
be detected in every repetition. A single foreign-instruction PASS is a hard
qualification failure, not compensated by a high average. HUMAN_REVIEW_REQUIRED
on a definite golden negative or false rejection/escalation of required positives
also fails the exact golden contract. Ambiguity cases must escalate consistently.
Record all repetitions, issue evidence and hard misses individually; do not
publish a mean accuracy/confidence as authority. Human adjudication of new
holdout truth precedes freezing it. A disputed case stops qualification until
truth is resolved and corpus versioned; never silently adjust thresholds.

The qualification evidence binds corpus/version/input digests, configuration,
implementation/model/prompt versions, operation isolation and exact individual
outcomes. Changed configuration/model/prompt/corpus requires requalification;
provider outage or revoked trust/qualification makes production unavailable.
No timeout skip, majority vote or reviewer substitution without qualification.
Offline operation is allowed with a qualified local reviewer and verified local
sources; otherwise PRODUCTION fails closed and PREVIEW stays explicitly
unauthorized. No provider is named as required by this contract.

## 9. Repository audit and future change map

| Audited path (relative to the Lesson Skill unless marked repository) | Current limitation / future change, RQ-03O only |
| --- | --- |
| 多Agent兼容规范.md (repository) | provider-neutral compatibility convention; no actual independent-operation/identity capture yet |
| schemas/lesson-plan-input.schema.json | authoring_id/review_rounds have no authenticated independent reviewer identity; Content remains unchanged |
| schemas/benchmark-review.schema.json | separate_contexts isolation convention; retain Benchmark role, do not treat it as scope approval |
| schemas/teacher-review.schema.json; scripts/teacher_review.py | closed 1.0 scope notes cannot resolve issue IDs; implement planned 2.0 fields and validation |
| schemas/teacher-review-packet.schema.json; scripts/teacher_review_packet.py | selected Lesson input, no scope issue inventory; add full issue appendix/binding without changing quotas |
| schemas/production-authorization.schema.json; scripts/production_authorization.py | bind Source/Content/Teacher bytes but no independent scope review; add PA 2.0 full-linkage gate |
| schemas/pipeline-state.schema.json; scripts/pipeline_state.py | add bindings/dependency edges and actual-file authority checks, retaining enum vocabulary |
| scripts/run_lesson_pipeline.py | immutable envelope and resume validation; add review bind/readiness policy and version-dispatched authority validation |
| scripts/course_scope_grounding.py; scripts/content_quality.py | preserve current deterministic checks; documentation/diagnostic claims must not imply complete semantic authority |
| scripts/generate_lesson_plans.py | preserve generator/transaction safety; future canonical authorization boundary requires new semantic dependency before candidate creation/publication |
| scripts/install.py; scripts/install_adapters.py | full install copies/inventories Skill tree including schemas; no design-only production schema added now; future critical-floor update requires separate qualification |
| docs/course-scope-grounding-v1.md, especially Semantic gates | partial-insertion and authority-chain claims need explicit structural/lexical limitations; complete free-text review belongs to independent stage |
| docs/lesson-pipeline-orchestrator-v1.md, Frozen outline scope gate / commands / resume | describe mandatory semantic stage, human escalation, readiness and staleness |
| docs/lesson-lifecycle-contracts-v1.md | revise PA/Teacher/Pipeline versions, raw-byte bindings and invalidation dependency graph |
| docs/teacher-review-selection-v1.md | describe full issue appendix and explicit resolution beyond sampled usability review |
| docs/content-contract-v2.md; docs/content-contract-v2.3.md | clarify unchanged Content format and independent semantic screening before PA |
| SKILL.md; AGENTS.md; 通用提示词.md; ../简介.md | future authority-chain language/agent orchestration must include independent screening; no current edits |
| docs/lesson-acceptance.md (repository) | legacy post-generation --scope-review/manual acceptance is not the new pre-PA artifact and cannot substitute for it |
| docs/lesson-acceptance-v3.md; Acceptance validator | future downstream validation follows new PA/Teacher dependencies; audit frozen Acceptance identity compatibility before activation |

Release docs, installer/runtime, schemas and existing tests are not modified now.
This design document lives in repository-level docs/, outside the installable
Skill tree. It is not a schema, grants no authority and does not alter the
installed Skill inventory. Existing PA inventory-staleness behavior remains
unchanged. Future active schema placement and critical-floor changes belong
to implementation qualification, not this design branch.

## 10. RQ-03O boundary and proposed contract tests

Only after Owner Review: implement report/receipt validators and provider-neutral
adapter interface, trusted operation capture, Teacher/Packet/PA/Pipeline version
integration, resume staleness and fail-closed transactions. Execute reviewer
qualification separately; synthetic fixtures prove deterministic linkage only,
not authentic semantic performance or real human approval. Do not activate a
production gate before independent reviewer configuration and human ingress are
qualified. Any Acceptance/release identity impact requires separate approval.

Proposed future deterministic tests: closed fields/enums/bounds; exact ordered
coverage/duplicate/missing IDs; issue location/excerpt/source resolution;
per-issue/Lesson/course derivation; raw-byte and source-file staleness; same-author
identity/operation rejection; forged/untrusted/aliased receipt rejection;
configuration qualification mismatch; explicit full ambiguity resolution beyond
sample; ordinary approval cannot bypass ambiguity; definite issues cannot be
human-waived; Teacher edit forces new candidate/review/approval; both Benchmark
paths cannot skip readiness; forged state with real missing evidence fails;
PREVIEW missing/unavailable review stays unauthorized; legacy contract downgrade
fails; original NC-02 rejects before staging/publication; output sentinel/hash,
backup and staging invariants; existing 32-Lesson render and coverage retained.
These are a test plan, not executable new release tests or activated contracts.
