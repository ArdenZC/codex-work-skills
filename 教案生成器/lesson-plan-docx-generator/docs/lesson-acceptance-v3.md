# Lesson Acceptance Contract 3.0

Independent opt-in LIF-05 authority, `scripts/acceptance_v3.py` and
`schemas/lesson-acceptance-v3.schema.json`. Skill 2.3.1, Content 2.2/2.3, Template
1.1.2, Lifecycle 1.0, Teacher Review/Packet 1.0 and Benchmark versions remain fixed.
Acceptance 2.0 / `lesson_acceptance.py` remains the standalone 2.3.1 compatibility
path, including its R0 fail-closed behavior. Existing users need not migrate.
Generator `production_pass` means generator/artifact transaction passed, never
Lesson lifecycle ACCEPTED. Final authority requires Acceptance 3.0 + Pipeline ACCEPTED.

## Twelve blocking gates

| Gate | Actual authority |
| --- | --- |
| pipeline_identity | Immutable run ID/mode, valid envelope and byte bindings |
| source_truth | Source Truth and actual offline source bytes |
| content | Formal Content 2.2/2.3, frozen identity and hours |
| preproduction_qa | Rederived existing Content QA machine report |
| benchmark_disposition | Final explicit disposition and full Review/Authorization claims when present |
| teacher_review_packet | Current deterministic Packet, exact rederivation |
| teacher_review | External approval, exact IDs/order/reasons and all linkage |
| production_authorization | Current Source/Content/Teacher/Benchmark/Skill/Template/runtime authority |
| artifact_manifest | Existing generator's public read-only verifier, actual DOCX/PDF inventory and hashes |
| artifact_qa | Existing `qa-report.json` bytes, passed QA and retained render |
| visual_review | Current Visual Authority and actual required-file/page inspection evidence |
| lifecycle_state | Valid complete transition prefix through VISUAL_REVIEW_APPROVED |

Each gate records PASS/FAIL/PENDING/NOT_APPLICABLE, evidence SHA, contract/version
and notes/reason. This canonical nonzero-Lesson path has no NOT_APPLICABLE blocking
gates. Missing evidence remains PENDING, never NOT_APPLICABLE. Every blocking gate
must PASS before successful finalization.

`evaluate-acceptance` is purely read-only; it can inspect an incomplete late chain.
Optional external diagnostic Teacher/Visual/Benchmark evidence can be passed to
classify valid revision decisions; it never alters bindings or state. Original
integrity is verified first. Invalid/stale bytes, schemas, claims, paths, transitions
or fabricated states => FAILED, with integrity taking precedence over revision.
Valid human/Benchmark revision => REVISION_REQUIRED. Otherwise incomplete evidence
=> PENDING_REVIEW. PREVIEW may evaluate a legitimate chain as PENDING_REVIEW, and
cannot hold final production authority.

All gates PASS => ACCEPTED only with BENCHMARK_REVIEW_COMPLETE, Teacher APPROVED
and Visual PASSED. Teacher APPROVED_WITH_NOTES or final BENCHMARK_PARTIAL,
BENCHMARK_UNAVAILABLE or BENCHMARK_WAIVED_BY_USER => ACCEPTED_WITH_NOTES. Limitations
are explicit and deterministic. Nonempty visual notes alone do not change status.
Visual has no implicit advisory classification in Contract 1.0.

## Finalization and stale authority

`finalize-acceptance` requires PRODUCTION / VISUAL_REVIEW_APPROVED and an evaluated
ACCEPTED or ACCEPTED_WITH_NOTES candidate. It stages and validates
`lesson-acceptance-v3.json`, atomically publishes it with the run, then records the
ACCEPTED transition using acceptance bytes SHA. Status revalidates the artifact and
all upstream evidence; state alone never grants authority.

Acceptance binds run/mode, all twelve gates, Source/Content/QA/Benchmark disposition
and nullable Review SHA, Teacher Packet/Review, Production Authorization, Artifact
Manifest/QA, Visual Authority, current Skill fingerprint and Template version/SHA.
Inventory summary records DOCX/PDF counts, total PDF pages, manifest identity/SHA,
output inventory fingerprint and render status. The full file list remains solely
in Artifact Manifest; no duplicated QA report or file byte-metadata list.

Fingerprint uses the existing `lifecycle_digest`, excludes timestamp and self only.
To avoid a circular dependency, lifecycle-state evidence hashes the validated
VISUAL_REVIEW_APPROVED transition prefix, excluding the final ACCEPTED transition
and acceptance digest. It is identical immediately before and after finalization.
Validator checks schema, self fingerprint and exact full-chain rederivation.
Upstream changes, including actual output files/PDFs, make Acceptance stale.

Per-course Acceptance 3.0 does not run or require Negative Controls. They belong
to subsequent Skill Release Qualification; historical Acceptance 2.0 remains
compatible. This PR does not qualify or release Skill 2.4 Stable.

## Lifecycle applicability (RC-01)

Formal Content 2.3 `practice_only` requires `lessons=[]` and remains valid.
Canonical Lesson lifecycle requires at least one real Lesson, in PREVIEW and
PRODUCTION. Shared applicability validation rejects zero-Lesson at bind-content,
before any binding or AUTHORING_COMPLETE transition. It is not a schema failure.
Teacher Review 1.0 remains unchanged with its nonempty selected Lesson requirement.
Acceptance 3.0 preserves zero-Lesson → FAILED as defense in depth for forged,
historical or noncanonical callers. It cannot falsely Accept practice-only and
never fabricates a Lesson, Teacher Review or DOCX. Practice Task / WorkOrder
handles requested practice materials; its teaching acceptance is not asserted by
Lesson Acceptance 3.0 and it has no claimed equivalent lifecycle authority.

RC-01 closes applicability and installer floor blockers. Skill stays 2.3.1
candidate / pre-2.4; remaining RC-02 work is listed in `lesson-release-closeout.md`.
