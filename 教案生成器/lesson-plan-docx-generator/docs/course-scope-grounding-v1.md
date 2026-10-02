# Frozen Outline and Course-Scope Grounding 1.0

## Problem and root cause

The RC-02 preflight exposed a course-scope trust gap: a database course could
replace an entire Lesson with coherent nursing instruction, while structural
Content validation and generation still accepted it.

Three facts explain the gap:

1. `_intra_lesson_coherence()` checks whether a Lesson's task, instructional
   body, implementation, and deliverable form one substantive semantic chain.
   It does not decide whether that chain belongs to the current course. A
   nursing task, nursing body, and nursing deliverable can be internally
   coherent and still be outside a database course's frozen plan. The detector
   is an intra-Lesson coherence gate, not a course-domain detector.
2. `authoring_provenance.source_snapshot.whole_course_outline_sha256` currently
   binds `Content.outline` to a digest carried by that same Content. It detects
   a stale self-snapshot, but it does not bind Content to the outline frozen in
   Source Truth. Rewriting both the outline and its self-snapshot leaves that
   trust gap open.
3. The `database_patient_bp` Negative Control described the detector as
   `existing Content QA non-IT/domain contamination`. Production had no
   course-level scope detector that justified that claim. The catalog now names
   the actual frozen-outline grounding and intra-Lesson gates.

## Authority chain

Course scope comes from the outline confirmed and frozen before Lesson
authoring. The Source Truth Manifest Contract remains 1.0 and uses its existing
`whole_course_outline` source type:

```text
Confirmed course facts
  -> frozen whole-course outline JSON bytes
  -> Source Truth source_id / locator / SHA-256 / provenance
  -> exact Content.outline binding and existing self-snapshot check
  -> Lesson-to-outline structural alignment
  -> outline-anchor grounding plus intra-Lesson coherence
  -> Content QA / canonical pipeline / generator
```

The frozen file is the canonical Content outline array, encoded as UTF-8 JSON.
The shared validator reads local bytes offline, verifies the Source Truth SHA,
rejects aliases and symlinked paths, validates every row with the existing
Content outline schema, preserves array order, and requires unique lesson IDs.
Production does not fetch HTTPS outline sources. PREVIEW may report an outline
as bytes-unverified; that state cannot reach Production Authorization.

The validator separately checks all three identity fields (`course_name`,
`major`, and `audience`) against Source Truth. It also checks both bindings:

- canonical `Content.outline` equals the parsed frozen outline;
- `authoring_provenance.source_snapshot.whole_course_outline_sha256` equals the
  canonical digest of `Content.outline`.

For each Lesson, the shared planning fields and progression values must exactly
match the row with the same `lesson_id`. The Lesson ID set and order must match
the frozen outline. Lesson authoring may expand its teaching and assessment
content, but changing the planned task, output, capability stage, or bridge
requires a new outline, Source Truth, and run.

## Semantic gates

Structural binding catches full-Lesson replacement. For each Lesson, the
validator considers frozen `unit`, `task`, `prior_learning`, `deliverable`, and
`next_bridge` anchors. Authorization requires task-connected instructional
body content to form an existing substantive anchor with the frozen `task`,
`deliverable`, or `next_bridge`; unit and prior-learning matches remain bounded
context evidence. It reuses `_intra_anchor_evidence()` and
`_intra_lesson_coherence()`; it does not introduce a second NLP system or
keyword blacklist. Intra-Lesson coherence also rejects body items that are
disconnected from the Lesson's main component and its task/deliverable/
progression anchors, which catches partial insertions that briefly leave
scope and then return to the planned task.

The outline is domain-agnostic. A database Lesson may use patient, order, or
financial records as data while teaching SQL, schema design, constraints,
queries, or indexes. Python may analyze temperature data while teaching Python
data processing. Accounting may use database software while teaching voucher
processing. The application context does not change the frozen instructional
task.

## Integration and compatibility

`scripts/course_scope_grounding.py` is the single implementation used by
Content QA, `bind-content`, every canonical pipeline resume/authorization
check, Production Authorization validation, and the generator's `--source-truth`
preflight. A failed report fails Content QA and the canonical Production path
before Content binding or output publication. The report contains statuses,
hashes, lesson IDs, bounded anchor evidence, and failure codes; it does not copy
teaching paragraphs into diagnostics.

Content Contracts 2.2 and 2.3 share the gate because both carry an outline and
authoring provenance. `practice_only` keeps its existing zero-Lesson routing.
Historical Source Truth 1.0 manifests without an outline remain auditable, but
cannot authorize a current canonical Lesson production candidate. An
HTTPS-only outline can remain a PREVIEW `unverified` result, but cannot pass
Production.

Standalone generator calls without `--source-truth` keep their 2.3.1 legacy
structural behavior and are explicitly unscoped. Canonical production passes
`--source-truth`; it cannot report `production_pass` or publish output without
the shared gate. Lesson Skill remains at 2.3.1 during this remediation; this
document does not declare a 2.4 release.
