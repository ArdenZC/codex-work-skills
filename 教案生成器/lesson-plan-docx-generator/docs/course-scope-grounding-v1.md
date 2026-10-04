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

Structural binding catches full-Lesson replacement. Every required instructional
body node independently needs strong direct evidence from the current frozen
`task`, `deliverable`, or `next_bridge`, or an explicit operation on the current
frozen deliverable. Unit and prior-learning matches remain context evidence.
The shared extraction helper supplies direct evidence; the bounded deliverable
helper supplies exact-object relation evidence. `_intra_lesson_coherence()` and
its task component remain unchanged and prove coherence only. Connection to
another legal node cannot authorize an otherwise foreign body node.

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

## Per-node frozen authority

Every `teaching_content[i]`, `key_point.content[i]`, and
`difficult_point.content[i]` independently requires either strong direct frozen
`task`/`deliverable`/`next_bridge` evidence, or an explicit operation on the
current row's exact frozen deliverable. Graph connectivity continues to prove
coherence; it never supplies course authority. Unit/prior-learning matches are
context only. A single two-character residual does not grant authority.

Direct strength uses the shared extraction evidence: a shared acronym, one
independent residual of at least three characters, or at least two independent
residuals within one frozen field. This rule does not use domain dictionaries,
frequency, or body-to-body inheritance.

The calibrated D1 relation is deliberately limited to the complete statement
`示范形成<exact current frozen deliverable>的关键步骤`, optionally preceded by one
of the three reviewed generic scaffolds (`让每个步骤都留下可复查证据`,
`为关键结论保留依据来源`, or `把操作规范转成检查清单`). Scaffolds and action words
never authorize a node by themselves. NFKC/whitespace normalization preserves
the exact output identity; the whole statement must match. Bare mentions,
negation, extra instructional clauses, derived artifacts, and other outputs do
not receive D1 evidence. A named output operation conflicting with the current
row cannot borrow lexical authority from a future bridge. No neighboring row or
other body node participates in this decision.

Per-node `scope_authority` records status, path (`direct_frozen`,
`frozen_deliverable_relation`, or `none`), matched outline field, strength, and
relation type. Diagnostics remain bounded and hash-addressed. The same shared
validator feeds Content QA, pipeline binding/preproduction checks, Production
Authorization, and generator preflight for Content 2.2 and 2.3.

### NC-02 production control

`tests/fixtures/lesson-original-nc02.json` preserves the original contaminated
payload byte for byte (SHA-256
`878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`). Its two
foreign nursing nodes have no substantive direct frozen residual and no current
deliverable relation. It tests **per-node frozen course authority plus
intra-Lesson coherence**, not nursing keywords or a short-residual detector.
The separate “结果” nursing sentence is an adversarial synthetic calibration
control and is never substituted for the original production control.
