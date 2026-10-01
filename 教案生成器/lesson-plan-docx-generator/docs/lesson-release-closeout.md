# Lesson 2.4 Release Closeout — RC-01

Current identity is **Lesson Skill 2.3.1 candidate / pre-2.4 release state**.
LIF-01～05 are implemented. RC-01 closes lifecycle applicability and installer
completeness; it does not qualify, version or publish 2.4.0.

## Canonical production path

```text
Source Truth
→ Quality Eligibility / Benchmark Preparation
→ Content
→ Preproduction QA
→ Benchmark disposition / Review
→ Deterministic Teacher Review Packet
→ Human Teacher Review
→ Production Authorization
→ Canonical Generator
→ Artifact QA
→ Deterministic Visual Review Packet
→ Human Visual Review
→ Acceptance 3.0
→ ACCEPTED
```

Human Teacher/Visual decisions remain external authority. Synthetic evidence only
proves contract closure; it never proves real teaching or visual quality. The
generator's production_pass alone does not mean lifecycle ACCEPTED.

## Closed applicability blocker

Content 2.3 practice_only → lessons=[] remains valid. Canonical Lesson lifecycle
applies only to valid Content with at least one real Lesson, in PREVIEW and
PRODUCTION. `lesson_lifecycle_applicability` validates formal Content first, then
returns APPLICABLE or NOT_APPLICABLE_TO_LESSON_LIFECYCLE based on Lesson count.
`bind-content` rejects zero Lessons before binding Content/waiver or advancing
AUTHORING_COMPLETE, with an explicit lifecycle applicability error. Resume and
Acceptance 3.0 still reject forged/historical/noncanonical zero-Lesson envelopes.

Teacher Review 1.0 keeps its nonempty selected Lesson requirement; no schema
changes, fake Lessons, fake Teacher Packet/Review or fake DOCX resolve this boundary.
Standalone Content tooling and direct generator historical behavior remain
compatible, including Content 2.2/2.3. Requested practice materials route to
Practice Task / WorkOrder. Lesson Acceptance 3.0 does not attest pure practice
workorders, and WorkOrder has no claimed equivalent lifecycle authority.

## Closed installer completeness blocker

Both full-copy entry points share the audited production floor in
`scripts/install_adapters.py`: the existing generator/R0 floor plus separately
named lifecycle runtime and schema floors, combined and deduplicated. The existing
static compatibility floor remains distinct from dynamic installed inventory.

The lifecycle runtime floor is lifecycle_digest, source_truth, teacher_review,
production_authorization, pipeline_state, lifecycle_benchmark,
benchmark_quality_eligibility, benchmark_preparation, run_lesson_pipeline,
teacher_review_packet, final_artifacts, visual_review_authority, visual_sampling,
acceptance_v3 and lesson_lifecycle_applicability (all `scripts/*.py`).

Their direct schemas are pipeline-state, source-truth-manifest, teacher-review,
production-authorization, benchmark-quality-eligibility, benchmark-preparation,
teacher-review-packet, visual-review-packet, visual-review-authority and
lesson-acceptance-v3 (all `schemas/*.schema.json`).

Manual audit starts at run_lesson_pipeline, includes lazy imports and follows the
local production dependency closure. Generator/shared dependencies already in
the generator floor include package_common, content_contract/content_quality,
exemplar_contract/exemplar_split, benchmark_authorization/validate_benchmark_review,
path_safety, generate_lesson_plans, validate_template/validate_output/render_qa,
bookmark_utils/semantic_bookmarks and record/validate_visual_inspection. Existing
Benchmark, Content and shared Practice Task schemas and template assets remain
required. Tests/examples are not lifecycle runtime dependencies. A regression
checks the import/schema closure against the complete critical production floor.

All critical files must be ordinary real files with safe existing parent
components before destination mutation. Missing runtime/schema or symlinked
critical paths fail before partial engine/adapter writes. Existing staging,
atomic commit and rollback architecture remains intact.

Dynamic runtime_inventory/runtime_fingerprint still bind **every actually copied
runtime file**, including noncritical additions; they do not shrink to the floor.
Python cache trees/pyc and .DS_Store remain excluded. Runtime additions/changes and
installed-byte tampering still change freshness/integrity classification.

Installed-copy smoke runs the installed CLI and imports lifecycle modules in a
clean subprocess outside the original repository, after deleting the synthetic
source copy. It resolves every lifecycle schema from the installed tree, rejects
source-repository imports, retains a tree fingerprint and expects null repository
commit without .git. Canonical provenance trust is unchanged: HEAD is recorded
only when the actual Skill tree equals that HEAD.

## Remaining RC-02 blockers — not executed by RC-01

1. Lesson Skill 2.4.0 identity migration.
2. Historical 2.3.1 artifact compatibility.
3. Benchmark Authorization 1.0 version compatibility.
4. Production Authorization 1.0 version compatibility.
5. Generator manifest 2.4 identity.
6. Installer state 2.4 identity.
7. Acceptance 3 CLI exit-code UX.
8. Release Negative Controls.
9. Clean installed-copy release qualification (RC-01 smoke is not qualification).
10. Final README / 简介 / CHANGELOG.
11. Exact-SHA release qualification.
12. Owner Review.
13. Tag / GitHub Release only after explicit approval.

Content 2.3, Template 1.1.2, Teacher Review, Acceptance status vocabulary,
Benchmark rubric, WorkOrder contract and all existing identity versions remain
unchanged. No independent Practice Authority or provider/network workflow is
introduced. The Release Track does not claim 2.4 Stable before RC-02 closes.
