# Benchmark Quality Eligibility Contract 1.0 — LIF-02

This offline foundation answers whether a structurally qualified source group
has recorded excellence, relevance, teaching-pattern and transferability
evidence suitable for the current course's excellent-design Benchmark pool.
`QUALIFIED` is structural qualification, not a judgment of excellent teaching.
Tier A alone never implies `QUALITY_ELIGIBLE`.

Lesson Skill stays 2.3.1; Content 2.3 (historical 2.2), Template 1.1.2,
Exemplar/Review/Benchmark Authorization 1.0, Acceptance 2.0 and Lifecycle 1.0
remain unchanged. No generator, production authorization, Acceptance, Split
schema/algorithm, A/B Pack, selection, rubric or round behavior is modified.
Without `benchmark-quality-eligibility.json`, existing defaults still work.

## Authority and judgments

Agents/humans supply group judgments, short rationales and references to existing
Card evidence. Python validates schema, exact coverage, current evidence values,
provenance and deterministic decision consistency. It supplies no quality score,
excellence inference or teaching judgment. Policy-qualified recorded provenance
is **not online fact verification**. There is no search, source fetch, download
or provider call. Recorded recognition can support a judgment but does not prove
that a course's teaching design is excellent or suitable for vocational learners.

The only decisions are `QUALITY_ELIGIBLE`, `CONDITIONAL`, `REJECTED`.
Conditional means further quality/relevance/transferability evidence or human
review is needed; it is excluded from the explicit quality-gated pool. Rejected
means the reviewer identified mismatch, missing excellence/design evidence or
no useful transfer; a rationale is required. Every dimension also requires a
nonblank rationale even for conditional/rejected records.

Private user-provided material has no supported exemplary attestation mechanism
in this foundation. Even structurally qualified private Cards cannot receive
`QUALITY_ELIGIBLE`; they may be conditional or rejected. No new attestation
contract is introduced. A group containing any qualified private Card follows
the same restriction, rather than selecting only its public versions.

## Manifest and group coverage

Canonical schema: `schemas/benchmark-quality-eligibility.schema.json`.
Authority validator/builder: `scripts/benchmark_quality_eligibility.py`.
The manifest contains:

| Field | Binding |
| --- | --- |
| `quality_eligibility_contract_version` | `1.0` |
| `quality_policy_version` | `benchmark-quality-eligibility-v1` |
| `qualification_policy_version` | Current Exemplar qualification policy |
| `catalog_id`, `catalog_fingerprint` | Exact current Catalog identity and fingerprint |
| `created_at` | Timezone-aware timestamp; excluded from fingerprint |
| `groups` | All and only groups with at least one structurally QUALIFIED Card |
| `eligibility_fingerprint` | Lifecycle semantic digest of this manifest |

Catalog is revalidated through the existing Exemplar authority before any quality
decision is accepted. Invalid Cards, Tier C and discovery sources cannot bypass
that layer. Groups with only conditional/discovery/rejected Cards are not manifest
candidates. An empty candidate Catalog permits an empty manifest and unavailable
quality pool; it does not manufacture evidence.

Each group row contains `group_id`, `qualified_exemplar_ids`, `decision`,
`rationale`, and the six assessments below. `qualified_exemplar_ids` must equal
**every current QUALIFIED Card in that group**, including editions, mirrors,
sessions and derivatives. Missing/extra/duplicate group IDs, missing Cards,
other-group Cards and nonqualified Cards fail. Nothing may cherry-pick one
preferred version. Nonqualified Cards remain out of both existing Packs.

Catalog fingerprint already binds course context and complete Cards; this
contract introduces no competing course identity. Any semantic Catalog change
invalidates the old manifest, even if the changed field is not directly cited.

## Evidence assessments and consistency

Every assessment contains `status`, a short `rationale` (at most 2,000 characters),
and `evidence_refs`. Rationales should explain fit and limitations against the
Catalog course context; do not copy source lesson text.

| Assessment | Allowed states | QUALITY_ELIGIBLE requirement |
| --- | --- | --- |
| `authority_excellence_basis` | SUPPORTED, INSUFFICIENT_EVIDENCE | SUPPORTED plus recorded recognition evidence |
| `course_relevance` | DIRECT_MATCH, TRANSFERABLE, MISMATCH, INSUFFICIENT_EVIDENCE | DIRECT_MATCH or evidenced TRANSFERABLE |
| `learner_relevance` | MATCH, ADJACENT, MISMATCH, INSUFFICIENT_EVIDENCE | MATCH or explained ADJACENT |
| `teaching_context_relevance` | MATCH, TRANSFERABLE, MISMATCH, INSUFFICIENT_EVIDENCE | MATCH or evidenced TRANSFERABLE |
| `pattern_evidence` | SUFFICIENT, INSUFFICIENT | SUFFICIENT plus a teaching-pattern reference |
| `transferability` | SUFFICIENT, INSUFFICIENT | SUFFICIENT plus an explicit `transferable_principles` reference and rationale |

All six eligible assessments require actual evidence references. A transferable
course/context assessment requires evidence and rationale for every decision,
including conditional records. Equal course titles are not required. A reviewer
must consider learner level and prerequisites, theory/practice balance,
project/task design, lesson duration, environment, tools/equipment and which
patterns can transfer without importing nontransferable assumptions. High
institutional authority does not establish vocational learner fit.

An eligible decision with mismatch, insufficient evidence/patterns or insufficient
transferability fails. A national-course label or recognition reference alone
cannot establish pattern sufficiency. This is deterministic consistency over
explicit judgments, not an automated numerical evaluation.

Evidence refs are not only provenance links. For `QUALITY_ELIGIBLE`, the
validator also requires **dimension-appropriate evidence** under
`DIMENSION_EVIDENCE_FIELDS`. Each assessment must include at least one current,
valid reference from its required set:

| Dimension | Required evidence fields |
| --- | --- |
| Authority/excellence | `source.recognition_evidence` |
| Course DIRECT_MATCH | `scope.course`, `scope.domain`, `scope.topic`, `scope.education_level`, or `scope.vocational_level` |
| Course TRANSFERABLE | The course-match set above, or `scope.scope_mode`, with rationale |
| Learner MATCH/ADJACENT | `scope.learner_profile`, `scope.education_level`, or `scope.vocational_level` |
| Context MATCH/TRANSFERABLE | `scope.teaching_context`, `scope.scope_mode`, or non-null `scope.duration_minutes` |
| Pattern SUFFICIENT | One of the existing `PATTERN_FIELDS` |
| Transferability SUFFICIENT | At least one explicit `transferable_principles` item, with rationale |

Recognition does not establish course relevance; authority does not establish
learner fit. A learner-profile reference alone does not establish teaching
context. A design pattern alone does not establish transferability: explicit
transferable-principle evidence is mandatory for an eligible transferability
judgment. Ordinary patterns and `non_transferable_context` may supplement it.
For a direct course match, scope mode alone is insufficient.

The global evidence-ref field enum is unchanged. Globally allowed fields may
supplement the required types, but cannot replace them. Conditional/rejected
records may retain missing or dimension-incomplete evidence to explain gaps;
this new evidence-type hard gate applies only to `QUALITY_ELIGIBLE`. Existing
reference integrity and nonblank rationale rules still apply. The validator
checks policy consistency and linkage, not whether the prose is pedagogically
convincing. It performs no fuzzy text comparison, NLP scoring or automated
teaching-quality judgment.

## References to current Card values

Each reference has `exemplar_id`, `field`, `item_index`, `value_sha256`.
The ID must belong to the row's current qualified group. Allowed fields:

- `source.recognition_evidence`
- `design_patterns`, `difficulty_breakthrough_patterns`, `student_activity_patterns`
- `learning_evidence_patterns`, `assessment_patterns`, `differentiation_patterns`
- `reflection_patterns`, `transferable_principles`, `non_transferable_context`
- The existing scalar `scope` fields (education/vocational level, domain, course,
  scope mode, topic, learner profile, duration minutes, teaching context)

For arrays, `item_index` is a nonnegative in-range integer; for scalar scope
values it is `null`. Null/blank values, illegal fields, wrong IDs, duplicate refs
in an assessment and out-of-range indexes fail. `value_sha256` is generated by
`evidence_value_fingerprint(current_value)`, which uses LIF-01
`semantic_fingerprint({"value": current_value})`. The validator resolves the
current Catalog value and recalculates it. Updating the Catalog binding alone
cannot conceal a changed referenced value.

## Fingerprint

`quality_eligibility_fingerprint` reuses `lifecycle_digest.semantic_fingerprint`:
NFC strings, sorted property keys, no floats, normalized hash casing. It excludes
only top-level `created_at` and self `eligibility_fingerprint`. Group rows,
qualified ID sets and per-assessment evidence ref sets are explicitly unordered.
Reordering any of those sets or object keys leaves the fingerprint unchanged;
decision, rationale, evidence, Catalog binding or policy changes alter it.
Duplicates are rejected by validation even when hashing can represent them.

## Explicit quality helpers

`validate_split_quality_eligibility(split, catalog, eligibility,
authoring_pack=..., holdout_pack=...)` first revalidates the manifest and the
existing deterministic Split. Every A and B group must be `QUALITY_ELIGIBLE`.
Optional supplied Packs go through the existing exact-membership/Card/hash
validator. Conditional/rejected groups in either Pack fail. This helper does
not filter or generate Packs, change the stable split, or alter default callers.
With a mixed-quality Catalog, an existing complete Split can correctly fail
the opt-in gate; this foundation does not invent a replacement split algorithm.

`quality_aware_availability(split, catalog, eligibility)` separately reports
eligible group counts and availability on the existing A/B sides. Zero is
`UNAVAILABLE`, one is `PARTIAL`, two or more is `AVAILABLE` **per side**.
`benchmark_quality_availability` follows Holdout B, matching the existing
structural availability convention; Authoring availability remains separately
visible. Counting includes only eligible groups, never conditional/rejected
groups. Availability is diagnostic and does not mean the complete Split passed
the quality gate. Invalid/stale linkage raises an error rather than returning
an optimistic count.

## Offline CLI and regression entry

Supply an agent/human reviewed JSON object containing only `{"groups": [...]}`.
The builder binds these records and validates them; it does not create judgments
or silently repair references. It atomically writes output after validation and
rejects input/output aliases and symlink output traversal.

```powershell
python -B scripts/benchmark_quality_eligibility.py build --catalog exemplar-catalog.json --records reviewed-quality-groups.json --output benchmark-quality-eligibility.json
python -B scripts/benchmark_quality_eligibility.py validate --catalog exemplar-catalog.json --eligibility benchmark-quality-eligibility.json
python -B .github/scripts/run_test_shards.py --suite lesson-quality
```

The shard command runs from repository root. CLI failures return nonzero; a
successful offline validation does not attest online truth or human teaching
quality. New tests use explicitly SYNTHETIC data to prove contract closure only;
the existing synthetic Benchmark bundle is unchanged and gains no quality claim.

Mandatory production integration, orchestrator, teacher selector, default mode
switch, Acceptance 3.0 and private exemplary attestation are deferred. No
installer critical floor or version bump is introduced here.
