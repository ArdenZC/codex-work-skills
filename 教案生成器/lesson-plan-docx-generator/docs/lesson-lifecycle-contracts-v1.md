# Lesson Lifecycle Contracts 1.0

Lifecycle 1.0 adds opt-in sidecar contracts for Source Truth, Teacher Review,
Production Authorization, and recorded pipeline state. It does not change the
Lesson generator, Content 2.2/2.3, Acceptance 2.0, Template 1.1.2, Practice
Task Contract 1.1, or the existing Benchmark contracts. These contracts record
evidence and reject stale or contradictory evidence; they do not run workflow
actions and are not the default production orchestrator.

## Canonical digest rules

Lifecycle sidecars use `scripts/lifecycle_digest.py`, separate from the
existing Exemplar and Benchmark canonical JSON helpers so their established
hashes do not change.

- JSON object keys are sorted and UTF-8 strings and keys are normalized to
  Unicode NFC. Two keys that collide after NFC normalization are rejected.
- SHA-256 and Git commit hex strings are canonicalized to lowercase when they
  occupy their contract digest/provenance fields.
- Whitespace in a JSON file does not affect semantic fingerprints. Contract
  fingerprints are computed from parsed values, not source formatting.
- Floating point values and non-standard JSON constants are rejected. Integers,
  booleans, strings, and null are supported.
- Array order is preserved except for `Source Truth.sources`, which is an
  unordered inventory and is sorted by canonical element bytes. The order of
  selected lessons, selection reasons, evidence, and pipeline transitions is
  meaningful and remains unchanged.
- Source Truth `created_at`, Teacher Review `reviewed_at`, Production
  Authorization `created_at`, and each contract's own fingerprint are excluded
  from that contract's semantic fingerprint. Their raw file SHA-256 still
  changes when their bytes change and is used for downstream byte bindings.
- A file digest always hashes exact bytes. A semantic fingerprint hashes the
  contract value after the canonicalization rules above. The two digest kinds
  are intentionally distinct.

All contract timestamps must include a timezone. Source and artifact paths are
ordinary files without symlinked path components. Local Source Truth locators
are normalized relative POSIX paths under the manifest directory; absolute
paths, parent traversal, backslashes, and aliases are rejected. Full byte
validation also rejects missing files; structural-only validation records
that their content is unverified.
URL locators must use HTTPS and may not contain credentials, fragments, or
credential-like query parameters. URL sources are not fetched by validation;
their declared SHA is provenance evidence supplied by the source curator.

## Source Truth Manifest 1.0

`schemas/source-truth-manifest.schema.json` and
`scripts/source_truth.py` define a course identity and a source inventory.
Each source has a stable `source_id`, an allowed `source_type`, a human label,
a locator, a SHA-256, and a provenance note. IDs and semantic source locators
must be unique. Formal Lesson authoring requires both
`confirmed_course_profile` and `whole_course_outline`; `reference_pool` is
optional because Content 2.3 permits no verified external reference.

For local sources the validator resolves each locator under the manifest
directory, rejects symlinks and path escape, then compares exact local bytes
with the declared source SHA. Source list order and `created_at` do not affect
the manifest fingerprint. A source byte change requires a new matching source
SHA and therefore changes the semantic fingerprint and the raw manifest SHA.

## Teacher Review Contract 1.0

`schemas/teacher-review.schema.json` records a pipeline run, exact raw SHA-256
values for Source Truth and Content, an optional Benchmark disposition, an
explicit selected set of Lessons with reasons, per-Lesson ratings for the
five Acceptance 2.0 usability dimensions, whole-course findings, a decision,
and review time. The selected set is supplied by the reviewer; the validator
checks uniqueness and membership in Content and does not choose Lessons.

The accepted decisions are `APPROVED`, `APPROVED_WITH_NOTES`, and
`REVISION_REQUIRED`. Both `APPROVED` and `APPROVED_WITH_NOTES` can satisfy a
Production Authorization review gate; notes remain advisory and never edit or
overlay Content. `REVISION_REQUIRED` cannot authorize production. Any Content byte change makes
the stored `content_sha256` stale and invalidates this review. A revised
Content file needs a new Teacher Review and a new downstream authorization.

Benchmark disposition is a sidecar value and accepts only
`BENCHMARK_REVIEW_COMPLETE`, `BENCHMARK_PARTIAL`, `BENCHMARK_UNAVAILABLE`, or
`BENCHMARK_WAIVED_BY_USER`. A complete disposition requires the exact
Benchmark Authorization and Review file SHA values and corresponding files.
Partial or unavailable dispositions require a byte-verified evidence file. A
user waiver requires both a non-empty waiver reference and byte-verified
evidence. `BENCHMARK_NOT_EXECUTED` is not an authorization disposition.

## Production Authorization Contract 1.0

`schemas/production-authorization.schema.json` binds the exact Source Truth,
Content, and approved Teacher Review file bytes to the pipeline run. It also
binds the same Benchmark disposition, Content Contract version, Lesson Skill
provenance, runtime metadata, and canonical Lesson Template identity and
bytes. It supports Content 2.2 and 2.3, Lesson Skill 2.3.1, and canonical
`lesson-plan` Template 1.1.2.

Validation rechecks the actual Source Truth source files, Teacher Review
links, installed Skill tree fingerprint, current repository commit when the
Skill is tracked at its canonical repository path, runtime versions when requested, and template
manifest/binary identity through the existing `package_common` helpers. An
installed copy outside the tracked canonical tree records a null repository
commit and still must carry its installed tree fingerprint. A changed Source Truth, Content, review,
Skill tree, template manifest, or template binary invalidates the matching
authorization evidence. `REVISION_REQUIRED` cannot authorize production;
`APPROVED_WITH_NOTES` can authorize while its notes remain advisory.

## Pipeline Contract 1.0

`schemas/pipeline-state.schema.json` and `scripts/pipeline_state.py` record
these states in order:

```text
INTAKE_CONFIRMED
→ SOURCE_TRUTH_FROZEN
→ [BENCHMARK_PREPARED]
→ AUTHORING_COMPLETE
→ PREPRODUCTION_QA_PASSED
→ [BENCHMARK_REVIEW_COMPLETE]
→ READY_FOR_TEACHER_REVIEW
→ TEACHER_REVIEW_APPROVED
→ PRODUCTION_AUTHORIZED
→ PRODUCTION_GENERATED
→ ARTIFACT_QA_PASSED
→ VISUAL_REVIEW_APPROVED
→ ACCEPTED
```

Square-bracketed Benchmark states are optional. Only the two declared forward
edges into/out of those optional stages are legal; skipping a core stage,
moving backward, repeating a state, or transitioning from `ACCEPTED` is an
error. A state record must replay from `INTAKE_CONFIRMED`, end at its declared
`current_state`, and carry the required artifact hashes for that point.

Validation has three explicit layers: JSON Schema validation, semantic replay
and transition validation, and optional artifact-byte verification against
supplied paths. Authority checks bind the Source Truth and Content hashes,
require a byte-valid `APPROVED` Teacher Review for
`TEACHER_REVIEW_APPROVED`, and require a valid Production Authorization for
`PRODUCTION_AUTHORIZED`. A state fingerprint detects accidental edits; it is
not a signature and Pipeline state alone never grants authority.
Each transition stores the SHA-256 of its stage evidence alongside its source,
destination, and timezone-aware recording time. The helper derives this value
from the relevant artifact index entry and rejects a transition with no stage
evidence. Transition recording time remains part of the Pipeline semantic
fingerprint.

## Invalidation dependencies

`stale_downstream()` returns the transitive stale nodes when evidence changes.
The direct dependency graph is:

```text
Source Truth → Content, Benchmark preparation, Teacher Review, Production Authorization
Content → Benchmark Review, Teacher Review, Production Authorization
Benchmark preparation → Benchmark Review
Benchmark Review → Teacher Review, Production Authorization
Teacher Review → Production Authorization
Production Authorization → final artifacts
final artifacts → Visual Review
Visual Review → Acceptance
```

Preview and Production entry points remain unchanged. LIF-02/03 can add the
next lifecycle evidence and connect a later orchestrator or production gate
after their own qualification.

Validator outcomes use `VALID` when the sidecar and current dependency bytes
both pass, `STALE` when the sidecar is internally valid but its upstream byte
bindings no longer match, and `INVALID` when its own schema, semantic payload,
or fingerprint fails. The shared `validation_status()` helper applies this
precedence. A Source Truth check that deliberately skips local source bytes
reports `STRUCTURALLY_VALID_SOURCE_BYTES_UNVERIFIED`, never `VALID`.

This preserves explicit byte links even when a downstream file happens not to
change: a Source Truth byte change still invalidates review and authorization,
and a Content byte change invalidates Teacher Review and authorization. LIF-01
does not add scheduling, tool invocation, generator switching, mandatory
Benchmark orchestration, Acceptance 3.0 behavior, or production transaction
changes.

## Commands

Each validator exposes `validate` and `fingerprint` commands. Validation is
read-only. The Production Authorization and Pipeline validators require the
referenced sidecar paths to check cross-contract and artifact-byte bindings.

```powershell
python -B scripts/source_truth.py validate source-truth.json
python -B scripts/teacher_review.py validate review.json --source-truth source-truth.json --content lesson-content.json
python -B scripts/production_authorization.py validate authorization.json --source-truth source-truth.json --content lesson-content.json --teacher-review review.json
python -B scripts/pipeline_state.py validate state.json --source-truth source-truth.json --content lesson-content.json --teacher-review review.json --authorization authorization.json
```
