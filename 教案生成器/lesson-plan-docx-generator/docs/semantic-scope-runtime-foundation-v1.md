# Semantic Scope Review runtime foundation (RQ-03O1)

This opt-in foundation implements the repository normative
`docs/semantic-scope-review-contract-v1.md` and the Owner's human training
implementation clarification. It adds no mandatory production dependency and
activates no Teacher, Packet, Pipeline, PA or generator version.

Python validates externally supplied judgments and controlled-process evidence.
There is no semantic model execution, lexical scope classifier, signature or PKI.
Neither these helpers nor synthetic tests prove human identity, actual context
isolation or reviewer semantic performance. The operator must enforce protected
policy/ingress/index access outside authoring and reviewing adapters.

## Entry points

- `semantic_scope_records.Inventory`: explicit key -> absolute ordinary-file
  path/raw SHA/storage-class closure. Run and protected roots are supplied by
  the controller and must be disjoint. All paths undergo existing symlink and
  alias checks. Reads verify both inventory pins and supplied artifact bindings.
- `semantic_scope_records.TrustContext`: externally supplied profile path/raw
  pin, current epoch, protected operation-index path, controller implementation
  allowlist, and timezone-aware current check time. None is discovered from
  candidate JSON. Profile and index must match protected inventory files.
- `validate_configuration`: canonical bytes, exact agent/human branch, all
  build/prompt/system/tool/context/procedure/interface dependencies. Build
  manifests enumerate actual inventory keys/digests. Decimal decoding strings
  avoid float serialization. Mutable default revision aliases are rejected;
  other opaque provider-neutral revisions must be pinned by controlled setup.
  This foundation does not contact a provider to authenticate its revision.
- `semantic_scope_review.validate_review` / `review_status`: exact externally
  frozen Lesson order, actual Content/outline equality, full offline Source Truth
  closure, source pointers/ranges, exact excerpts, derived Lesson/course caches,
  configuration and captured receipt. Production-purpose reports always require
  current independently approved qualification. Qualification-purpose reports
  have null qualification hashes and cannot stand in for production reviews.
- `operation_provenance.validate_receipt`: exact caller-selected kind and subject,
  kind-specific bindings, raw bytes, profile/controller, protected capture, role
  validity at capture and now, actual protected Content author mapping, and
  operation/principal separation. Teacher-kind checks describe future subject
  operation/binding fields only; they do not implement Teacher Review 2.0,
  resolutions or lifecycle integration. Semantic provenance cannot replace
  teacher, qualification or corpus approval.
- `reviewer_qualification.validate_qualification` / `qualification_status`:
  agent mandatory corpus and three or more fresh complete runs, independently
  captured adjudications, exact hard-miss derivation, approved blind holdout from
  three contexts, and independent qualification approval; or controlled human
  training/procedure qualification. `require_approval=False` is an explicit
  evidence-only pre-capture check to avoid a digest cycle, never current authority.
  Default checks and production-purpose review validation require APPROVED.

Status helpers return existing `VALID`, `STALE`, `INVALID` vocabulary. Changed
upstream bytes are STALE; malformed records, uncaptured operations and invalid
current authority are INVALID. Structural/coverage failures are rejected even
when a candidate labels itself NOT_QUALIFIED. Valid complete evaluations with
any disposition or critical-truth miss derive NOT_QUALIFIED; means and majority
votes are absent. Historical files are never deleted. Exact-byte/schema validation
may be cached, keyed by both bytes and schema digest; file hashes, policy/index,
revocations and time are reread at each check.

## Supporting formats

Only Semantic Review, Operation Provenance Receipt and Reviewer Qualification
are independent artifact contracts. The other installed schemas are supporting
record encodings, not Skill products or a separate authority system:

- Operator role authorization: closed `record_version`, `principal_id`,
  `allowed_roles`, matching the profile role; validity/revocation remains in the
  operator profile. Other operator/procedure/repository references resolve actual
  protected inventory bytes under operator policy.
- Protected operation index: closed version/controller/epoch, `receipts`,
  `authors`, `adjudications`, `qualification_runs`. Receipt entries capture ID,
  operation, actor, subject key/hash and receipt key/hash. Author entries map
  exact Content authoring ID/hash to principal and operation. Adjudication
  entries capture operation, actor and exact subject key/hash. Run records list
  exact review operations and exposed case/configuration keys with all-true
  label-hidden, prior-reasoning-hidden and fresh-context declarations. This is
  the externally controlled lookup source, not a subject hash dependency.
- Corpus/holdout: ordered cases with three named input key/hash pairs (`content`,
  `source_truth_manifest`, `outline`), a `sources` closure, expected disposition
  and exact critical-truth key/hash. Critical-truth semantics remain independently
  adjudicated; Python checks actual bytes and captured evaluation results.
- Human training: exact `authorized_scope="semantic_scope_review"`; procedure
  ID/version/SHA matches configuration and qualification; subject has current
  scope_reviewer authority. Issuer has qualification_approver at issued_at and
  is not currently revoked, is not subject or applicable author, and may also
  independently approve the completed qualification. No teacher_approver role
  is required. The historical `teacher_authority_reference` names the subject's
  protected scope authorization record. Training does not grant teacher,
  authoring, adjudication or qualification-approval roles.

The acyclic sequence remains dependencies -> configuration/corpus -> corpus
approval -> evaluation review -> evaluation receipt -> qualification -> independent
qualification approval -> production review -> scope receipt. Review and
qualification fingerprints exclude exactly the normative completion timestamp
and own cache field. Configuration and receipt fingerprint helpers hash raw bytes;
receipts have no invented canonical cache field.

## Test fixtures and installation

`tests/fixtures/semantic-scope` freezes the N01..P14 IDs, labels, actual fixture
inputs/truth hashes and three synthetic context records. N01 is recovered from
historical commit `b7bf79a64201f9cec9699605127b6b543fddfe82` without rewriting
`tests/fixtures/lesson-original-nc02.json`; its expected raw SHA is
`878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`.
Its three Source Truth/profile/outline files preserve the historical helper's
serialization and fingerprint semantics. P11 includes the merged corrected
L05/L06 prose; P12 has 32 Lessons; N05/P14 retain full neighboring Lesson context.
These are deterministic linkage fixtures. Actual reviewer qualification still
needs independently approved realistic P12 and genuinely blind holdout evidence;
no real reviewer was executed or qualified in O1.

All new schema/script files are under the installable Skill tree. The unchanged
installer inventories the full ordinary-file tree and uses `copytree`, followed
by staged byte-inventory comparison. It does not provision or approve an operator
profile. Root-level tests/fixtures and audit reports are outside the installed
Skill. Existing release/version identities and the 35-minute CI budget remain.
