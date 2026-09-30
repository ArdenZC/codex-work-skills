# Deterministic Teacher Review Selection / Packet 1.0

LIF-04 is an opt-in candidate path. Machine selects; human reviews. The Packet
freezes which lessons the Teacher must inspect, with complete selected snapshots
and a lightweight whole-course map. It contains no generated ratings, notes,
assessment or approval. Density and practice complexity are coverage signals,
not teaching-quality scores. Benchmark gaps do not determine the Teacher decision.

## Authority and offline inputs

`scripts/teacher_review_packet.py` builds and independently validates Packet
Contract 1.0 (`schemas/teacher-review-packet.schema.json`). Its public builder and
validator take the actual run envelope. They reuse `validate_run_upstream` to
reread Source Truth (including locally bound source bytes), formally validate
Content with `validate_content_v2_input`, check immutable artifact inventories,
preparation and final disposition, and perform the existing full Benchmark
Authorization claims validation. Actual Review linkage includes Catalog,
Split, both Packs/Selections, every lesson shard, current Content SHA and Review
run/round, and Round 1 inputs when applicable. Only after that validation are
per-lesson shards loaded for gap metrics. A course-summary claim alone is insufficient.

The selector and Packet make no network, provider, LLM or embedding calls, and
read only current bound lifecycle artifacts. Source Truth HTTPS locators retain
existing PREVIEW unverified classification without being fetched.

## Selection policy 1.0

`Content["lessons"]` is the sole order authority; IDs must be unique. Never sort
IDs or filenames. Course positions in the Packet are 1-based. At most six lessons
are selected: courses with 1–6 lessons are reviewed in full; larger courses have
exactly six. Output always follows course order, independent of candidate priority.
All candidate reasons are computed for the whole course before selecting.

Candidate slots are attempted in this order, deduplicating lessons:

1. First lesson.
2. Last lesson (the same lesson can have both anchors in a one-lesson course).
3. Highest Benchmark gap tuple, if an actual fully validated Review exists.
4. The lesson immediately after the representative project boundary, if any.
5. Highest practice-complexity tuple, if actual allocation exists.
6. Highest content density.

A repeated candidate adds a reason and consumes no extra slot. All applicable
boundary reasons are retained, including boundaries other than the representative.
When fewer than six distinct candidates remain, repeatedly select the unselected
position whose minimum absolute distance to current selected positions is greatest.
Ties choose the earlier position, and distances are recomputed after each addition.
These additions carry `deterministic_supplemental`. In short courses only lessons
with no other applicable reason receive that reason.

Reasons always have this exact order:
`first_lesson`, `last_lesson`, `project_boundary_before`,
`project_boundary_after`, `highest_content_density`,
`highest_practice_complexity`, `benchmark_gap`, `deterministic_supplemental`.

## Structural metrics

**Projects:** normalize `unit` with Unicode NFC and collapse/trim whitespace
using `split`/`join`. Adjacent different normalized units define a boundary.
The preceding lesson receives `project_boundary_before`; the following lesson
receives `project_boundary_after`. The representative minimizes the following
lesson position's distance to `(lesson_count + 1) / 2`, ties earlier. Computation
uses integer distance `abs(2 * position - (lesson_count + 1))`; no NLP or floating
point midpoint is used. The six-lesson limit does not expand for additional boundaries.

**Density:** use exactly `teaching_content`, `goals`, `key_point`,
`difficult_point`, `implementation`, `evaluation`, `reflection`. Measure UTF-8
byte length of `lifecycle_digest.canonical_json_bytes` (NFC, sorted object keys,
ordered arrays). No lesson ID, reference metadata or timestamps enter this payload.
Choose maximum bytes, ties earlier. No weights or quality interpretation are added.

**Practice:** lexicographically maximize
`[allocated practice hours, linked task count, total steps, total deliverables,
total acceptance criteria, total tools_or_materials]`, ties earlier.
Content 2.3 supplies lesson `practice_hours` and formally validated
`practice_task_ids` links into `practice_task_contract.tasks`; actual task
`lesson_ids` links also count (including formally related theory work orders).
A task linked on both sides is counted once. Related theory links supply structural
counts, never practice hours. With zero allocations
there is no practice candidate. Content 2.2 has no per-lesson practice-allocation
authority; its metric is zero hours plus actual linked structural fields if present,
and separate work orders do not fabricate lesson allocation. Content and snapshots retain their original JSON numeric values; no allocations
are rounded or invented.

**Benchmark:** from each verified lesson shard's 15 dimensions, maximize
`(major_count, GAP_count, minor_count, PARTIAL_count, advisory_count)`, ties earlier.
Counts use exact `severity` and `status`, without guessed text meaning.
A real Review always supplies a candidate, including an all-zero tuple (then the
first lesson wins); this is a structural ranking, not a claim that a gap exists.
Existing REVISION_REQUIRED blocks lifecycle advancement even though the selector's
ranking mechanics can represent major gaps. Each selected lesson gets only counts
and sorted dimension IDs with GAP/PARTIAL, never a copied full Review.
No actual Review means null Review SHA, null gap summaries and no gap reason,
including disposition-only PARTIAL/UNAVAILABLE and WAIVED_BY_USER.

## Packet contents and verification

Packet Contract 1.0 binds `pipeline_run_id`, Source Truth bytes SHA, Content bytes
SHA, the full final `benchmark` object, disposition bytes SHA, nullable Review
bytes SHA, policy version, target count, ordered selected rows and course map.
`packet_id` is `TRP-` plus the lifecycle semantic digest of the run ID; it is
stable for the same immutable run. `created_at` must have a timezone.
Legal Content evaluation weights include decimal numbers such as `0.2`, while
LIF-01 canonical JSON deliberately accepts only integers. Before calling the
existing lifecycle helper, Packet 1.0 projects every finite floating-point scalar
to `{"$packet_decimal": "<Python round-trip numeric spelling>"}`. The same documented
projection is used for density and lesson semantic digests. It neither rewrites
snapshots nor implements another JSON encoder/hash; NFC normalization, key order,
UTF-8 and SHA remain entirely in `lifecycle_digest`. Non-finite numbers are rejected.
Raw Content SHA and exact snapshot rederivation preserve original numeric types.

`packet_fingerprint` uses `lifecycle_digest.semantic_fingerprint`, excluding only
`created_at` and itself. Rebuilding the same input with another timestamp preserves
the semantic fingerprint. Ordinary byte SHA bindings still detect timestamp edits.

Each selected row includes position, canonical reasons, semantic hash of the whole
actual lesson, density bytes, practice tuple, nullable gap summary and an unmodified
deep copy of the current lesson. The full-course map contains only position,
lesson ID, unit, task, hours, and existing theory/practice hours and lesson type.
It supports human progression, scope, theory/practice coherence, repetition and
difficulty review without duplicating every lesson body.

The independent validator rereads upstream artifacts, reruns the selector and
compares the entire expected Packet, including snapshots, map, metrics, order,
reasons and fingerprint. A recomputed attacker fingerprint is insufficient.
Byte changes to Content, disposition, Review or shards invalidate old authority.
Resume checks immutable run binding inventories and semantic Packet derivation.
Create a new run to iterate; rebinding old input bytes is forbidden.

```powershell
python -B scripts/run_lesson_pipeline.py prepare-teacher-review --run F:\lesson-work\prod-run.json
python -B scripts/teacher_review_packet.py --run F:\lesson-work\prod-run.json `
  --packet F:\lesson-work\prod-run-teacher-review-packet.json
```

## Human review and compatibility

READY → `prepare-teacher-review` → Packet → human external Teacher Review 1.0
→ `bind-teacher-review` → TEACHER_REVIEW_APPROVED.
Preparation atomically publishes Packet plus its path/bytes-SHA run binding,
without changing state or recording a fake same-state transition. It only runs
at READY and rejects repeated preparation of an already frozen Packet.
READY can exist without a Packet; a bound Packet is revalidated on every resume.
TEACHER_REVIEW_APPROVED and PRODUCTION_AUTHORIZED require one.

The independent `validate_teacher_review_against_packet` helper locks exact ordered
lesson IDs and ordered reasons. Missing, extra, substituted or reordered lessons,
including cherry-picked easy lessons, are rejected. Ratings, notes, whole-course
assessment and decision remain externally supplied. APPROVED and
APPROVED_WITH_NOTES may advance after all existing validations; REVISION_REQUIRED
cannot advance. PREVIEW can prepare and bind Review but cannot authorize production.
PRODUCTION requires the same Packet gate even for an otherwise valid standalone Review.

Teacher Review 1.0 standalone validation and schema remain unchanged. Skill 2.3.1,
Content 2.2/2.3, all existing Lifecycle/Benchmark/Authorization contracts, Practice
Task, rubric, Template 1.1.2 and Acceptance 2.0 retain their versions. Acceptance
3.0, visual review, final generator integration and final ACCEPTED remain deferred.
