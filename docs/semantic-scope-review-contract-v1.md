# Semantic Scope Review Contract 1.0 — RQ-03N design

Status: merged normative contract (PR #47). RQ-03O1 is MERGED_AND_QUALIFIED
at `a6789d12b95d23385bbdcedd91d14c381da7b898` (PR #49; post-merge run
`37715531429`). Issue #50 authorizes opt-in RQ-03O2 implementation, synthetic
integration qualification and one Draft PR, without production activation.
Live reviewer qualification, RC-02 and Lesson 2.4 remain separate blocked gates.
Historical design-stage references below do not change this normative policy.

Issue #52 has a separate draft extension for providers that expose managed model
aliases without immutable revisions: [Managed Alias Reviewer Identity Contract](managed-alias-reviewer-identity-contract-v1.md).
It adds closed Configuration 1.1, Qualification 1.1 and operation receipt 1.1
branches; the Reviewer Configuration 1.0 and human-reviewer clauses below stay
unchanged.

## 1. Authority and independent review

Agent/Human reviewers judge instructional meaning. Python validates structure,
declared operation metadata, coverage, hashes, binding, stale evidence, lifecycle and transactions.
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

Content 2.2/2.3 `authoring_provenance.authoring_id` identifies an authoring
operation, not a real-world actor. Repository 多Agent兼容规范.md and Benchmark
`separate_contexts` are compatibility/provenance conventions, not identity proof.
Python checks declared principal metadata and operation separation. **Python
cannot authenticate real-world human/model identity from these artifacts.**
A hash proves identity of bytes, not authority of those bytes.

### 1.1 Operation authority decision — Option B

| Option | Authority requirement | Decision |
| --- | --- | --- |
| A: cryptographically authenticated receipts | Externally provisioned trust-root artifact, kind-scoped signer authorization, secure private-key custody, bootstrap, rotation/revocation, exact encodings/canonical signed bytes and domain separation; none exists in this repository | Rejected for this contract; a signature field alone cannot supply these obligations |
| B: lifecycle controller provenance receipts | Operator-controlled canonical pipeline/orchestrator, protected evidence ingress and an explicitly configured external authority profile | Selected; auditable operation provenance, no cryptographic identity claim |

There is no Ed25519 requirement, signature field, key, PKI or cryptographic trust
root in the selected design. The authority root is **operator-supplied external
process authority**, not installed Skill authority and not a self-declaration in
JSON. The operator is responsible for authenticating people at the external
controlled ingress and approving which roles they may exercise. That controlled
process, not Python reading a name, establishes actual human participation.

Before PRODUCTION, an operator outside the author/reviewer role explicitly
configures a protected controller entry point, protected evidence repository and
an authority profile path plus its exact raw SHA pin in controller launch policy.
The launch policy and repository are not writable by authoring/review adapters;
only the operator may change the pin. An artifact cannot supply its own trusted
profile path/pin. Installer must not generate, infer, copy-as-trusted or silently
approve a root/profile. Missing profile/pin, uncontrolled ingress or inaccessible
current policy fails closed. PREVIEW is still explicitly unauthorized.

The external `operator-authority-profile.json` is a closed controller deployment
record under this contract (not a separate new Skill contract). Required fields:
`profile_version="1.0"`, `authority_profile_id`, `policy_epoch` (integer >=1),
`operator_reference`, `controller_id`, `controller_implementation`,
`controller_version`, `ingress_procedure_reference`, `evidence_repository_reference`,
`roles`, `revoked_authority_ids`, `created_at`. References/IDs are nonblank 1..160;
created_at is timezone-aware. Each roles entry is closed: `principal_id`,
`allowed_roles` (nonempty unique subset of `author`, `scope_reviewer`,
`qualification_approver`, `corpus_adjudicator`, `teacher_approver`),
`authorization_reference`, `valid_from`, `valid_until`, `revoked_at` (nullable
timezone-aware date-times except validity endpoints), `revocation_reason`
(nullable nonblank 1..600, required when revoked). Principal IDs are unique;
valid_until > valid_from. References resolve protected operator records of
actual authorization/ingress procedure, with inventory paths and raw SHA pins.
They are not arbitrary URLs or text-only grants. Profile changes increment epoch
and require an operator-reconfigured pin; no candidate-triggered automatic update.

Controller-only evidence writes use protected ingress, immutable unique IDs and
an append-only operation index, with allowlisted operator-controlled controller
code/version and enforcement of roles/separation. An adapter may submit a draft
report or evaluation result; it cannot bind an authoritative receipt by supplying
JSON. For human decisions the controller records the decision only after the
external process captures the authorized person's explicit approval of the exact
artifact bytes. Noninteractive authoring jobs must have no teacher/qualification
approval authority. A profile containing different principal names does not by
itself prove different people or isolated processes.

**Local trust limit:** an operator with write access to policy, controller code
and protected repository can create/alter provenance. Option B does not prevent
that or prove provenance to an untrusted recipient of a copied folder. If the
author controls these surfaces, operation separation cannot be trusted and
PRODUCTION must be unavailable. Threat protection against a malicious local
operator would require a separately reviewed Option A design, not a hidden
signature or an honest-looking hash. Trusted process capture is an explicit
precondition, not evidence that current runtime already supplies it.

`operation-provenance-receipt.json` uses Operation Provenance Receipt 1.0, a single
closed tagged contract for these kinds, rather than separate authority sidecars:

| Field | Required type / rule |
| --- | --- |
| contract_version | const `1.0` |
| receipt_id, operation_id, controller_id, actor_principal | nonblank 1..160; IDs immutable and unique in protected operation index |
| review_kind | `semantic_scope`, `teacher_approval`, `qualification`, `corpus_approval` |
| authority_profile_sha256, subject_sha256 | lowercase 64-hex; actual external profile and reviewed/approved subject bytes |
| subject_inventory_key | nonblank 1..160, resolves actual subject in inventory |
| pipeline_run_id | 1..128 for semantic/teacher; null for qualification/corpus authority operations |
| input_bindings | closed mapping of required inventory keys to exact raw SHA values, by kind below; no unrecognized keys |
| author_principal, author_operation_id | 1..160 for semantic/teacher, null for qualification/corpus |
| isolation | semantic: closed all-true `separate_invocation`, `author_reasoning_hidden`, `candidate_read_only`; other kinds null |
| decision | semantic: `REVIEW_RECORDED`; teacher: `APPROVED`/`APPROVED_WITH_NOTES`/`REVISION_REQUIRED`; qualification/corpus: `APPROVED`/`REJECTED` |
| approval_procedure_reference, recorded_at | protected procedure record reference 1..160, timezone-aware timestamp |

Required input_bindings: semantic uses source_truth_manifest, outline, content,
reviewer_configuration, and reviewer_qualification (only null for a
qualification-purpose report); teacher uses source_truth_manifest, outline,
content, semantic_scope_review and semantic_scope_operation_receipt;
qualification uses reviewer_configuration, qualification_corpus,
blind_holdout_truth and corpus_approval_receipt for agent evaluations, or
human_training_authorization and human_procedure for human authorization;
corpus_approval uses qualification_corpus and blind_holdout_truth.
These are raw SHA bindings to actual inventory entries, not values supplied by
candidate metadata. Receipt subject is respectively Semantic Review, Teacher
Review, Reviewer Qualification, or qualification_corpus. A corpus receipt also
approves the bound holdout truth. Teacher decision must match Teacher Review;
qualification/corpus APPROVED is an independent authority decision, not a model
output. The subject never binds the SHA of its own receipt. The controller's
protected index matches receipt bytes/ID/operation/actor/subject, preventing mere
candidate-folder receipts from becoming authority. Python verifies these records
and role authorization both at recorded_at and at the current check;
controller_id must match the pinned profile. This is process provenance validation, not
cryptographic or real-world identity authentication. For semantic capture,
actor_principal/operation_id match report reviewer.identity/operation_id;
author_principal must differ. The protected author operation maps the actual
Content authoring_id to its principal; an author cannot invent an unrelated
principal for separation. For teacher capture, actor/operation match the human
Teacher Review fields and teacher operation differs from semantic operation.
Human scope+teacher roles may belong to the same person with separate decisions.
A receipt kind/subject mismatch is INVALID; semantic provenance can never stand
in for teacher, corpus or qualification approval even without signatures.

At every resume/PA/publication check the live operator-pinned profile is required.
Expired/revoked actor roles, revoked receipt/qualification/corpus IDs, a changed
profile pin/epoch or controller/procedure authority invalidates prior receipts
for new PA and resume, even if issued before revocation. Completed outputs and
old audit records remain historical records with a current invalidation annotation;
no retroactive deletion or silent claim of current authority. Operator profile
rotation is conservative: old receipts must be recaptured/reapproved under the
new epoch; no grandfathering. No key rotation is involved in Option B.

### 1.2 Exact reviewer configuration

`reviewer-configuration.json` is a closed canonical configuration artifact, not
a loose collection of version names. `reviewer_configuration_sha256` always
hashes its **actual file bytes**. Its stored bytes must be lifecycle canonical
JSON: UTF-8, NFC strings/keys, sorted object keys, compact separators, no trailing
newline/BOM; ordered arrays retained, no unordered-array rule, no excluded field.
Reject duplicate/NFC-colliding keys, all floating-point JSON numbers and
noncanonical input; integer JSON fields remain allowed.
For decoding settings use decimal strings, avoiding numeric serialization drift.
All references below point to actual ordinary files in the dependency inventory.

Common required fields: `configuration_version="1.0"`, `reviewer_type`
(`agent`/`human`), `implementation`, `version`, `implementation_build_sha256`,
`context_policy` and exactly one of `agent`/`human` (the other null).
IDs/versions are nonblank 1..160; SHA fields are lowercase 64-hex.
implementation_build_sha256 resolves the actual immutable adapter/controller
build inventory manifest, whose entries/digests are verified against installed
ordinary files. context_policy is closed: `policy_sha256`,
`whole_course=true`, `verified_sources_only=true`, `author_reasoning_hidden=true`,
`candidate_read_only=true`. policy_sha256 resolves a frozen policy file defining
full Source Truth/outline/Content exposure and operation isolation.

Agent fields are closed and required: `model_reference` (neutral 1..160),
`model_revision` (immutable service/local revision 1..160), `provider_reference`
(nullable 1..160; no prescribed provider), `semantic_prompt_sha256`,
`system_instructions_sha256`, `decoding`, `tool_permissions_sha256`.
Prompt, system and tool-permission SHAs resolve exact template/instruction/policy
files including all included text, not a name or implied default. decoding is
closed: `temperature`, `top_p`, `seed` (nullable decimal strings <=64),
`max_output_tokens` (integer >=1), `additional_parameters` (ordered unique
name/value entries, names 1..160, values decimal/string/bool/null <=600).
All effective judgment-affecting service defaults must be materialized here;
unknown defaults or unpinnable model revision make production unavailable.
Tool policy names the complete allowlist, read/write scope and external context
policy; dynamic candidate bytes are separate review inputs, not config fields.

Human fields are closed and required: `procedure_id`, `procedure_version`
(1..160), `procedure_sha256`, `interface_policy_sha256`. They resolve an approved
whole-course scope procedure and controlled ingress/interface policy. There are
no model, sampling, prompt or agent-corpus-test fields for humans. Per-person
training/authorization belongs to qualification below. Interface/build/context
fields still bind what the reviewer sees and what the controller captures.

Changing implementation/build, model/revision/provider, semantic prompt, system
instructions, decoding affecting judgment, tools/context exposure, human
procedure/interface or corpus contract/truth invalidates old qualification.
Configuration fields have no decorative timestamp/log destination. Nonsemantic
log path, correlation labels and retry transport telemetry may live only in an
external operational log, never change instructions, sampling, access or reviewed
inputs, and need no requalification. A runtime setting outside the canonical
artifact that affects judgment is an invalid unqualified configuration.

### 1.3 Reviewer Qualification Contract 1.0

Artifact: `semantic-reviewer-qualification.json`. All objects are closed, all
fields below required; SHA values are lowercase 64-hex, IDs/versions nonblank
1..160, timestamps timezone-aware. Human and agent branches share this one
contract but carry different evidence, not fictitious human model configuration.

| Field | Type / authority meaning |
| --- | --- |
| contract_version, qualification_id | const `1.0`; immutable ID |
| qualification_purpose | `agent_corpus_evaluation` or `human_scope_authority` |
| reviewer_configuration_sha256 | actual canonical configuration bytes, correct reviewer_type |
| reviewer_implementation, reviewer_version | equal configuration values |
| corpus_contract_version, corpus_sha256, blind_holdout_sha256 | agent: version and actual approved corpus/holdout truth files; human: null |
| qualification_runs | agent: >=3 complete fresh repetitions, closed entries below; human: empty array |
| golden_results, holdout_results | agent: complete closed derived result arrays below; human: empty arrays |
| disposition | `QUALIFIED` or `NOT_QUALIFIED`, recomputed; no accuracy score |
| qualified_at | completion timestamp; does not itself grant authority |
| valid_until | future operator-approved expiry timestamp, greater than qualified_at |
| human_authority | human: closed object below; agent: null |
| qualification_fingerprint | lifecycle canonical semantic fingerprint excluding only qualified_at and this field; arrays ordered |

Each qualification_runs entry: `run_id`, `repetition` (integer >=1),
`started_at`, `completed_at`, `operations` (one per exact corpus+holdout case).
Each operation entry is closed: `case_id`, `review_operation_id`,
`review_inventory_key`, `review_sha256`, `receipt_inventory_key`, `receipt_sha256`.
They resolve actual qualification-purpose review/receipt bytes and candidate
case inputs. Every operation ID is fresh and unique, complete course coverage
and valid isolation are required, no cached/production reviews or majority vote.
Each golden_results/holdout_results entry: `case_id`, `expected_disposition`,
`expected_critical_truth_sha256`, `observations` (one per required repetition),
`hard_miss` (boolean). Each observation: `run_id`, `review_operation_id`,
`observed_disposition`, `critical_truth_satisfied` (boolean),
`adjudication_inventory_key` (1..160), `adjudication_sha256` (64-hex). Expected disposition
uses the three scope enums; expected_critical_truth_sha256 resolves the exact
critical-truth file declared by that approved case. Observations must match the
actual reports. Python checks exact coverage/repeats and recomputes cached flags;
independent adjudication determines semantic critical-truth satisfaction and
records its frozen evaluation evidence in the protected qualification inventory.
Each adjudication entry resolves a closed record: case_id, run_id,
review_operation_id, review_sha256, critical_truth_sha256,
critical_truth_satisfied, bounded_rationale (1..600), adjudicator_principal,
recorded_at. The independent authorized corpus_adjudicator is distinct from
candidate reviewer/author; controller index captures their evaluation operation
and exact record. Qualification approval validates all these records.
The approver verifies that evidence, not the reviewer's claim about itself.

QUALIFIED for agents requires all exact expected dispositions and critical
issue truth in every repetition. Any golden negative PASS, negative ambiguity
instead of required revision, required positive REVISION_REQUIRED or
HUMAN_REVIEW_REQUIRED, ambiguity case other than HUMAN_REVIEW_REQUIRED,
missing/invalid/reused repetition, or any blind holdout hard miss yields
NOT_QUALIFIED. Each case has at least three fresh complete operations and
holdout spans at least three course contexts. A mean score cannot mask a miss.
Unresolved corpus/adjudication disputes block authority rather than manufacture
QUALIFIED. Result caches and a self-written QUALIFIED never authorize production.

For human_scope_authority, human_authority is closed: `principal_id`,
`teacher_authority_reference`, `procedure_id`, `procedure_version`,
`procedure_sha256`, `training_authorization_sha256`. References resolve protected
external teacher authorization records; hashes resolve actual approved procedure
and per-person training/authorization record. That record states principal,
procedure/version, authorized scope, validity and issuer. QUALIFIED requires
current teacher/scope-reviewer role authorization, matching approved procedure,
valid training authorization and independent qualification approval. No three-run
model-style examination is required; final teacher approval is still a separate
operation. Human qualification is per person/configuration, not transferable.

Authority issuer: an Owner-designated `qualification_approver` in the pinned
external profile approves the exact qualification bytes through controlled ingress.
They cannot be the candidate reviewer or authoring principal, cannot alter corpus
truth during evaluation and cannot approve themselves. The canonical controller
checks roles, evaluates completeness/hard rules and records a **qualification-kind
receipt**. A controller can reject inconsistent results; it cannot invent Owner
approval or promote NOT_QUALIFIED. Production requires both QUALIFIED and this
independent APPROVED receipt in the protected index, plus current validity.
An authorization receipt for a human uses the same mechanism; no second PKI.

Bootstrap is non-circular: operator authorizes approver/adjudicator/teacher roles
via external policy; adjudicator first freezes and approves corpus/holdout truth;
agent evaluation reports have review_purpose=qualification and null qualification
binding; approver reviews their actual evidence, then controller records approval
of the completed qualification file. Production reviews bind those pre-existing
qualification bytes/receipt. Human path starts from external teacher/procedure
training authorization and independent approval, not a model corpus. Nothing
qualifies its own issuer or binds the hash of its own approval receipt.

Corpus authority: `qualification-corpus.json` and `blind-holdout-truth.json`
are closed manifests with `corpus_contract_version`, `corpus_version`, `corpus_id`,
`cases`, `created_at`; each case contains `case_id`, `course_context`, input
inventory keys/raw SHAs for Content/manifest/outline and source closure,
`expected_disposition`, `critical_truth_inventory_key`, `critical_truth_sha256`.
Critical truth defines current task/output/progression, required defect issue
locations/categories or affirmative/ambiguity truth, and adjudication rationale;
exact bytes are frozen. Protected inventory includes every case input/source and
truth file. An independent corpus_adjudicator approves both exact manifests via
corpus_approval receipt before evaluation, independent of reviewer/author; the pending reviewer cannot edit
manifests, expected truth or approval records. Any changed case byte, expected
disposition/critical truth or corpus contract needs a new corpus_version, fresh
approval and full requalification; no silent relabel or threshold adjustment.

Holdout manifests/truth/labels stay outside reviewer access during execution.
Controller provides only case inputs in fresh isolated contexts, never expected
labels, golden/holdout result caches or prior evaluation reasoning. Adjudicator
freezes truth beforehand; protected runs record input exposure policy. Completed
qualification may record case IDs, outcomes and hashes, with truth/evaluation
files available to approver/validator in protected inventory; ordinary report
exports contain no holdout labels or case contents. A revealed holdout cannot be
called blind in a later test: replace/version it before retesting that reviewer.
Secrecy forever is unnecessary; absence of label leakage at test time is required.

Changing configuration or corpus, expiry, qualification/corpus approval revocation
or authority-profile epoch invalidates qualification for new PA/resume. Historic
results remain auditable. Requalification cannot be achieved by copying digests,
renaming reviewer/version or invoking an unqualified substitute. A production
human/agent report must match current configuration and qualification exactly.

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

Reviewer fields: `type` (`agent`/`human`), `identity` (declared principal,
1..160), `operation_id` (1..128), `implementation` and `version` (1..160 each),
`configuration_sha256` (lowercase 64-hex), `qualification_sha256` (lowercase
64-hex for production_candidate; null only for qualification-purpose evaluation).
Values must match actual configuration, qualification and captured provenance.
Agent uses agent_corpus_evaluation; human uses human_scope_authority for that
principal, with procedure/training authorization rather than model testing.
The production dependency is a pre-existing independently approved qualification,
not the reviewer's self-declaration. Evaluation reports/receipts may have null
qualification bindings and cannot authorize production. No provider is required.

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
derivation, uncaptured/unrecognized receipt, invalid location/coverage or unsupported version is
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
configuration/approved qualification/operation provenance -> review;
review/provenance -> Teacher Packet/Teacher Review -> PA -> output,
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
no semantic report hash, issue IDs, per-issue resolution, captured human
authority or resolution binding. Ordinary APPROVED/APPROVED_WITH_NOTES is therefore
insufficient to resolve HUMAN_REVIEW_REQUIRED. Add explicit fields in a future
Teacher Review 2.0 rather than a parallel human-review service.

Teacher Review 2.0 retains all current human usability/course assessments and
decisions, and adds a closed `semantic_scope` object with:
`contract_version="1.0"`, `review_sha256`, `operation_receipt_sha256`,
`outline_sha256`, `human_reviewer` (`identity`, `review_operation_id`,
`authority_reference`, each nonblank 1..160), and `resolutions`.
Existing run/source/content bindings remain mandatory. The external controlled
Teacher Review ingress authenticates the authorized person according to the
operator procedure; Python does not authenticate a person by reading JSON.
The controller captures a separate teacher_approval receipt binding exact Teacher
Review bytes, input hashes, declared actor/operation, profile and procedure.
authority_reference resolves its immutable receipt ID in the protected index;
the run inventory binds its raw SHA. This role uses the same operator profile
and protected ingress as scope provenance/qualification, with teacher_approver
permission; a semantic reviewer receipt cannot be used for human final approval.
Existing runtime does not implement this process capture. Generic notes, an
agent-declared type=human or a manually copied receipt cannot grant approval.
Teacher Review never hashes its own teacher_approval receipt; its authority
reference is an ID, so no circular digest results.

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
existing deterministic QA, valid independently captured report/receipt for the
exact final Content and a qualified reviewer configuration. Missing, malformed,
stale, unresolved, unavailable or REVISION_REQUIRED evidence blocks PA and all
production generation/publication. Deterministic scope PASS is no fallback.
HUMAN_REVIEW_REQUIRED can reach the human escalation input stage, but cannot
be authorized until explicit bound human resolution derives effective PASS.

PA 2.0 adds a closed `semantic_scope` object: `contract_version="1.0"`,
`review_sha256`, `operation_receipt_sha256`, `outline_sha256`,
`reviewer_configuration_sha256`, `reviewer_qualification_sha256`,
`qualification_approval_receipt_sha256`, `authority_profile_sha256`,
`human_authority_receipt_sha256`, `effective_whole_course_disposition="PASS"`.
Existing raw manifest/Content/Teacher Review hashes remain. Each required SHA
must resolve a concrete ordinary file through inventory, not just match hex syntax.
Legacy PA 1.0 or Teacher Review 1.0 is historical audit evidence, never a downgrade
path for this new canonical gate. Benchmark waiver cannot waive semantic scope.

The future validation chain is:

```text
Source Truth manifest + every source -> frozen Outline + final Content
Reviewer Configuration + its actual build/prompt/policy/procedure files
Operator-pinned authority profile + protected operation/authorization records
Approved corpus/holdout + actual evaluation evidence (agent)
  OR approved human procedure/training authorization (human)
  -> Reviewer Qualification + independent qualification approval provenance
  -> Semantic Review + semantic operation provenance
  -> Teacher Review + separate human authority provenance
  -> PA (recompute effective PASS) -> production publication
```

PA rereads all these actual bytes, verifies inventory completeness, roles and
protected index provenance, configuration/qualification branch and current
validity, report isolation, full coverage/disposition derivation and exact
source/content/outline/run/version links. Agent qualification hard rules and
actual evaluation/adjudication records are checked, or human authority/procedure
validity is checked. Teacher receipt must match its exact review and approval
operation; explicit ambiguity resolutions are recomputed. No PA cache, name,
fingerprint or SHA format assertion replaces actual dependency validation.

Validate before creating a generator candidate directory, during resume and
immediately before publication. A current profile cannot be unavailable/revoked
without blocking publication. Missing/stale/rejected evidence means no PA, no
publication, byte-identical old output and no leftover backup/staging artifacts.
Existing transaction rollback and lock/path safety remain mandatory. A controller
receipt records trusted-process provenance; it does not prove semantic truth or
real-world identity. Reviewer qualification and final human approval stay separate.

## 7. Pipeline and version impact recommendation

Current pipeline uses PREPRODUCTION_QA_PASSED -> optional
BENCHMARK_REVIEW_COMPLETE -> READY_FOR_TEACHER_REVIEW ->
TEACHER_REVIEW_APPROVED -> PRODUCTION_AUTHORIZED, with immutable bindings,
forward-only replay, actual-file authority validation and transitive staleness.
Current disposition-only Benchmark binding can directly advance to READY.

Retain the existing state vocabulary; do not add a PASS state that would incorrectly
exclude legitimate human escalation. Insert a mandatory artifact-bearing review
stage before READY: future `bind-semantic-scope-review` records reviewed report
and captured operation receipt while staying at the pre-READY state.
Both Benchmark paths must stop auto-advancing to READY until all required evidence
is bound; a single readiness gate checks existing Benchmark policy plus VALID
semantic PASS/HUMAN_REVIEW_REQUIRED. REVISION_REQUIRED cannot advance.
At TEACHER_REVIEW_APPROVED and every later stage, effective semantic PASS and
actual human approval are rechecked. State strings/fingerprints cannot bypass
file authority validation. Add the inventory closure below to state artifacts
and run inventory; review binding publishes atomically under
existing locks. No backward transition or same-state history entry is invented.

| Contract | Current | Future recommendation / reason |
| --- | --- | --- |
| Semantic Scope Review | absent | New 1.0 independent sidecar |
| Operation Provenance Receipt | absent | One new 1.0 tagged contract for scope, teacher, qualification and corpus capture; no signature contract |
| Reviewer Qualification | absent | New 1.0 with agent/human branches and independent process approval |
| Pipeline State | 1.0 | 2.0: new mandatory bindings and stricter READY/authorization policy |
| Orchestrator envelope | implementation 1.0 | 2.0 dispatch/validation policy; no silent replay of 1.0 as new authority |
| Production Authorization | 1.0 | 2.0: mandatory semantic dependency breaks old payload authority |
| Teacher Review | 1.0 | 2.0: required semantic binding, identity and explicit resolutions |
| Teacher Packet | 1.0 | 2.0: required complete issue index and report/receipt links |
| Content / Source Truth | 2.2/2.3 / 1.0 | No bump; final bytes and existing outline source bind independent sidecars |
| Lesson Skill / Template | 2.3.1 / 1.1.2 | Frozen release identities; no 2.4 migration |
| Acceptance | 3.0 | Identity frozen now; future PA/Teacher dependency validation and compatibility audit required |

Version minimization: only Semantic Review, Operation Provenance Receipt and
Reviewer Qualification add independent artifact contracts. Reviewer configuration,
corpus manifests and operator profile are closed supporting records defined here,
not separate versioned Skill products. Pipeline State and PA need major 2.0 payload
versions because required authority fields change; Teacher Review 2.0 is required
for bound explicit human resolutions. Keep Teacher Packet 1.0 as a historical
reader, recommend 2.0 only for its changed required issue/index payload. Orchestrator
2.0 is an implementation policy version using Pipeline 2.0, not another sidecar
contract. Share one authority/provenance framework; no qualification-signature,
teacher PKI, independent trust-root contract or second human-review system.

### 7.1 Future run inventory and concrete SHA resolution

Every entry is closed `inventory_key`, `path`, `sha256`, `storage_class`
(`run`/`protected_external`). Paths resolve actual ordinary files under existing
path/alias/symlink protections; external paths only use controller-configured
protected repositories. No author-controlled arbitrary authority locator.
The controller records an immutable dependency closure and checks each file
against its SHA. Raw hashes bind all records except configuration whose stored
bytes are additionally required to be canonical. Profile pin comes from launch
policy, never solely the run inventory. Artifact changes require a successor run.

| Inventory entry / group | Actual bytes resolved and authority use |
| --- | --- |
| source_truth_manifest, outline, content; source entries | Existing full verified manifest/source closure, frozen outline file and final Content |
| reviewer_configuration; config_dependencies | Canonical config; exact build manifest/files, context policy, agent prompt/system/tool policies OR human procedure/interface files; all config SHA fields resolve here |
| reviewer_qualification | Qualification file; report qualification_sha256 and PA/receipt reviewer_qualification_sha256 resolve here |
| qualification_approval_receipt | Independent APPROVED qualification receipt from protected index; PA approval hash resolves here |
| qualification_corpus, blind_holdout_truth, corpus_approval_receipt; qualification_evidence | Agent only: exact approved case/truth/source closure, all qualification review/receipt/run/adjudication files; corpus/holdout, critical-truth and result report/receipt SHAs resolve here |
| human_training_authorization, human_procedure | Human only: actual controlled teacher training/authorization and scope procedure; qualification human hashes resolve here, human_procedure may reuse the same configuration dependency entry |
| authority_profile; authority_records; operation_index_records | Operator-pinned external profile, role/procedure/operator records and protected operation records for every receipt; all authority/authorization references resolve here |
| semantic_scope_review, semantic_scope_operation_receipt | Exact report and captured scope receipt; downstream review/operation_receipt hashes resolve here |
| teacher_review, teacher_approval_receipt | Exact Teacher Review and separate teacher operation receipt; human_authority_receipt hash resolves here |
| teacher_packet, production_authorization | Existing packet/PA entries, expanded actual dependency links |

Qualification evidence is a protected external closure, referenced by inventory,
not copied holdout truth in public Teacher Packets. File entries can be shared
when genuinely identical (e.g. human procedure); do not duplicate authority in
additional unsigned approval sidecars. All receipt subject_sha256 resolves
subject_inventory_key; every input_bindings key resolves the corresponding
inventory file. Source references retain manifest source_id resolution.
review_fingerprint and qualification_fingerprint are explicitly canonical caches
of their own files, not unresolved external-artifact hashes. No other SHA in
this design is permitted without a defined actual dependency entry.

Hash DAG: configuration dependencies -> config; case inputs/critical truth ->
corpus/holdout -> corpus approval receipt; evaluation review -> evaluation
receipt -> qualification -> qualification approval receipt; production review
-> scope receipt -> Teacher Review -> teacher receipt -> PA. Operator policy
precedes every operation. Corpus/qualification/review subjects do not hash their
own approval receipts; Teacher Review uses a teacher receipt ID, not its digest.
The protected append-only operation index is a controller lookup source, not a
subject's hash dependency. Qualification-purpose reviews omit qualification
hashes, so there is no bootstrap cycle. Profile does not hash its dependent
receipts or qualifications. Existing run inventory binds all immutable bytes
without requiring those files to hash that same final inventory snapshot.

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

Agent corpus qualification uses the entire mandatory corpus plus a frozen independent
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

The section 1.3 qualification contract and protected approval bind corpus/version/
input digests, configuration,
implementation/model/prompt versions, operation isolation and exact individual
outcomes. Changed configuration/model/prompt/corpus requires requalification;
provider outage or revoked process authority/qualification makes production
unavailable.
No timeout skip, majority vote or reviewer substitution without qualification.
Offline operation is allowed with a qualified local reviewer and verified local
sources; otherwise PRODUCTION fails closed and PREVIEW stays explicitly
unauthorized. No provider is named as required by this contract.

## 9. Repository audit and future change map

| Audited path (relative to the Lesson Skill unless marked repository) | Current limitation / future change, RQ-03O only |
| --- | --- |
| 多Agent兼容规范.md (repository) | provider-neutral compatibility convention; no actual independent-operation/identity capture yet |
| schemas/lesson-plan-input.schema.json | authoring_id/review_rounds have no captured independent reviewer provenance; Content remains unchanged |
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
not semantic performance or proof of real human approval. Do not activate a
production gate before independent reviewer configuration and human ingress are
qualified. Any Acceptance/release identity impact requires separate approval.

Proposed future deterministic tests: closed fields/enums/bounds; exact ordered
coverage/duplicate/missing IDs; issue location/excerpt/source resolution;
per-issue/Lesson/course derivation; raw-byte and source-file staleness; same-author
declared principal/operation rejection; candidate-supplied/uncaptured/aliased receipt rejection;
configuration qualification mismatch/revocation/expiry; actual config/approval/corpus bytes
required; profile bootstrap/epoch checks; label leakage and holdout exposure
rejected; human authorization branch without agent repetitions; explicit full ambiguity resolution beyond
sample; ordinary approval cannot bypass ambiguity; definite issues cannot be
human-waived; Teacher edit forces new candidate/review/approval; both Benchmark
paths cannot skip readiness; forged state with real missing evidence fails;
PREVIEW missing/unavailable review stays unauthorized; legacy contract downgrade
fails; original NC-02 rejects before staging/publication; output sentinel/hash,
backup and staging invariants; existing 32-Lesson render and coverage retained.
These are a test plan, not executable new release tests or activated contracts.

## 11. RQ-03N1 Owner authority answers

1. **Who may declare this configuration qualified?** An externally authorized
   Owner-designated qualification_approver, separate from the reviewer/author,
   explicitly approves exact QUALIFIED bytes; the controller records that decision.
2. **What actual evidence does Python read?** Canonical configuration and its
   dependency files, the closed qualification artifact, protected approved corpus/
   holdout/evaluation closure or human procedure/training authorization, independent
   approval receipt and protected operation index, plus current pinned policy.
3. **Who may declare this human teacher approved?** The operator-authorized
   teacher_approver through controlled external Teacher Review ingress. The
   controller captures exact review bytes and the separate human approval operation;
   JSON naming a teacher is insufficient.
4. **Why cannot an author forge receipt authority?** The author can write JSON
   but cannot write the protected controller index/ingress/policy. Candidate-supplied
   receipts are rejected. A local operator controlling those surfaces can forge
   process provenance; Option B explicitly trusts that operator and does not offer
   cryptographic or real-world identity proof. Such copied/uncontrolled evidence
   cannot be used by a new deployment without explicit operator authority capture.
5. **Where does the root come from?** Explicit external operator configuration
   and raw profile pin in protected launch policy, never Skill installation or a
   self-certifying candidate file. No cryptographic key/root is claimed.
6. **What invalidates authority?** Config/build/model/prompt/policy/context/procedure
   or corpus truth/version changes require fresh qualification; expiry/revocation
   or profile epoch/pin/controller/procedure changes block old evidence for new
   PA/resume and require recapture/reapproval. Historical audit stays preserved.
   There is no key lifecycle in this selected model.

This revision closes the design decision only. No schema file, signature code,
keys, model call, adapter, runtime/installer/CI change or version bump is added.
PR #47 is merged as the normative design. Issue #50 authorizes RQ-03O2 code
integration; live qualification, production activation, RC-02 and Lesson 2.4
remain outside that authorization.
