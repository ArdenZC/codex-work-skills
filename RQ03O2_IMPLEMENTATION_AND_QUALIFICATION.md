# RQ-03O2 implementation and qualification

Issue: https://github.com/ArdenZC/codex-work-skills/issues/50

Exact starting master: `a6789d12b95d23385bbdcedd91d14c381da7b898`.
One branch: `feature/lesson-semantic-scope-lifecycle-o2`; one substantive Draft PR.
No Owner Review, merge, release, RC-02, live reviewer qualification, external
production invocation or production activation is claimed by this implementation.

## Policy before and after

Historical Orchestrator/Pipeline/Teacher/Packet/PA 1.0 continue their original
dispatch. The new **opt-in 2.0** route requires actual final Content, frozen
outline, complete verified Source Truth closure, canonical reviewer configuration,
current independently approved qualification, protected scope receipt and current
operator-pinned authority. It reuses O1 validation APIs, without semantic
classification in deterministic Python or a second authority system.

Both completed Benchmark and disposition/waiver routes stop before READY until
the same semantic gate passes. PASS and HUMAN_REVIEW_REQUIRED permit escalation;
REVISION_REQUIRED does not. Teacher approval and PA require independently derived
effective whole-course PASS. Ambiguities across all Lessons must be resolved
exactly once with verified references and bounded rationale through a separately
captured authorized teacher operation. Definite revisions cannot be waived.

All authority is provided by an external operator-controlled `TrustContext`
factory. No candidate path, digest, principal name, installed profile or copied
receipt can bootstrap authority. Missing external provisioning fails closed.
The embedding operator must enforce protected launch policy/profile pin,
repositories/index, role separation and authenticated ingress. The code checks
process records; it cannot prove identity, actual model isolation or ACL protection.

## File-level inventory

Paths below are relative to `教案生成器/lesson-plan-docx-generator` unless marked
repository-level.

| Files | Change / validation purpose |
| --- | --- |
| `scripts/semantic_lifecycle.py` | Strict external context registration, fresh authority checks, O1 review/receipt/qualification reuse, immutable dependency closure, complete issue index, Teacher resolution and effective PASS validation, PA bindings |
| `schemas/pipeline-state-v2.schema.json` | Closed 2.0 artifact bindings without changing state vocabulary |
| `schemas/teacher-review-v2.schema.json` | Closed semantic binding, actor/operation/receipt ID, full explicit resolutions; existing usability assessments retained |
| `schemas/teacher-review-packet-v2.schema.json` | Closed complete course issue appendix and raw review/receipt/outline bindings; quota unchanged |
| `schemas/production-authorization-v2.schema.json` | Closed semantic/configuration/qualification/approval/profile bindings and effective PASS |
| `scripts/run_lesson_pipeline.py` | Explicit 1.0/2.0 dispatch, atomic semantic binding, shared READY gate, independently approved Teacher/PA validation, same-process canonical generator under external context, failed final state-commit cleanup |
| `scripts/pipeline_state.py` | Versioned schemas/initial state, concrete required artifact bindings, 2.0 transitive dependency graph; legacy graph unchanged |
| `scripts/teacher_review.py`, `scripts/teacher_review_packet.py` | Versioned validation, original deterministic selection, full issue appendix and separate authority validation |
| `scripts/production_authorization.py` | Actual O2 run and current external evidence required for PA 2.0; existing Content/template/Skill/runtime/Benchmark checks retained |
| `scripts/generate_lesson_plans.py` | O2 guard before candidate creation, before publication and inside existing rollback validator; exact canonical inputs/template/schema and required render; artifact PA byte copy and provenance binding |
| `scripts/final_artifacts.py` | Exact O2 PA-to-output manifest/copy linkage, followed by existing DOCX/PDF/hash/page-count checks |
| `scripts/acceptance_v3.py` | Existing 3.0 identity; version-aware inherited gates and actual Teacher 2.0 authority validation |
| `scripts/install_adapters.py` | Full-engine source floor includes O2 controller helper and schemas; no profile/authority provisioning |
| `docs/semantic-scope-lifecycle-v2.md` | Versions, immutable migration, explicit operator setup, transaction policy and qualification limits |
| `SKILL.md`, `AGENTS.md`, `通用提示词.md`, lifecycle/orchestrator/selection/foundation docs | Opt-in O2 instructions; existing release identities and historical policy preserved |
| repository `docs/semantic-scope-review-contract-v1.md` | Correct stale status prose only; normative judgments and authority rules unchanged |
| repository `tests/test_semantic_lifecycle.py` | Synthetic actual entry-point lifecycle/installer/generator/rollback and authority controls |
| repository `.github/scripts/run_test_shards.py` | Exact canonical-generation, installed-copy, final-rollback and evidence partitions included in full discovery; existing Core and 12 semantic partitions unchanged |
| repository `.github/workflows/template-package-ci.yml` | Three independently required real-render test lanes plus the evidence lane run on Windows/macOS, each with the existing 30-minute cap and all enforced by CI Gate; docs-only skip logic retained |
| repository `tests/test_run_test_shards.py`, `tests/test_template_packages.py` | Suite-disjointness and gate contract assertions require every new matrix lane |

## Evidence and acceptance coverage

The synthetic controller tests exercise actual public `execute` commands through
PREPRODUCTION_QA, READY, Teacher approval, PA, canonical generation with retained
render, Artifact QA, Visual Review, Acceptance 3.0 and ACCEPTED. They also run
installed-copy modules in a fresh process, reject a copied source-run QA inventory,
and execute a fresh installed-copy production chain with explicit synthetic
external provisioning.

Negative controls cover waiver/Benchmark readiness bypass, definite revision,
missing/duplicate/human-revision ambiguity resolutions, Teacher 1.0 downgrade,
unprovisioned authority, raw report staleness, transitive build mutation even when
the external inventory is repinned, current teacher revocation/profile rotation,
and final stale generation rollback.

The exact historical NC-02 JSON is read without rewriting and checked against
SHA-256 `878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352`.
Its historical Source Truth manifest, frozen outline and confirmed profile are
copied byte-for-byte from the existing fixture. The test binds a contract-valid
synthetic `WAIVED_BY_USER` record to those exact Source Truth and Content bytes;
`bind-content`, Preproduction QA and final Benchmark disposition all pass. The
independently validated Semantic Scope Review is then bound to the O2 run with
`whole_course_disposition=REVISION_REQUIRED`. The actual
`ready-for-teacher-review` call fails with `semantic REVISION_REQUIRED blocks
READY`, and the run remains `PREPRODUCTION_QA_PASSED`. No Teacher Packet, Teacher
Review/approval, PA or generated artifact is bound. A pre-existing output
sentinel remains byte-identical, and no candidate or backup remains. Thus this
is an exact historical-byte regression that reaches and is rejected by the
actual semantic readiness gate; its failure is not caused by missing
pre-semantic prerequisites.

The Teacher Packet CLI regression creates and validates real 1.0 and 2.0
packets through the lifecycle builder. It invokes the CLI for both; the O2
invocation registers the test's externally supplied `TrustContext` in its fresh
process, so packet derivation and validation run without a mock or trust bypass.
Successful JSON output reports the validated packet's own contract version.

The 32-Lesson course test verifies complete semantic coverage and a bounded
six-Lesson Teacher sample with a complete issue index containing an unselected
ambiguity. It uses a fresh production-compatible synthetic integrated-course input,
not the O1 P12 fixture (whose explicit fixture mode remains unchanged and cannot
bypass Content production validation). It is not approval of realistic P12 prose
or evidence of an actual reviewer invocation. Existing O1 golden/control,
configuration, qualification, provenance, exposure, self-approval, forged/replayed
receipt, revocation/expiry and source-byte tests remain required in all 12 matrix
legs. Existing Content 2.2/2.3, practice_only zero-Lesson, Acceptance/render,
Gradebook, Release and 32-Lesson retained-render E2E suites remain required.

Local verification before the final commit:

- All 24 O2 integration tests passed in the final uninterrupted local run.
- 175 existing lifecycle, pipeline and Teacher-selection regression tests passed.
- 144 Final Acceptance, release compatibility and Lesson skill-hardening tests passed.
- Seven static canonical template package identity/hash/schema checks passed;
  full Windows/macOS package validators remain required in CI. The Lesson template remains
  SHA-256 `6ffafa579d3aacbc535ba624d0a6a766644868b0af1fce6ac37b20ba8f3d8fc1`.
- After the render-timeout correction, 11 focused shard/workflow/gate assertions passed. The manifest lists three exact singleton render partitions
  plus the complementary 21-test evidence partition; the three render partitions are
  pairwise disjoint and together with evidence cover all 24 O2 tests. The full shard
  runner suite had one unrelated local Gradebook validator failure: it reports a
  protected workbook formatting mismatch. No Gradebook code or template bytes changed;
  the required Windows/macOS CI remains the qualification gate for those validators.
- The new suite additionally exercises 12 original N02–N06/P07–P11/A13/P14
  control scenarios at actual O2 entry points. It preserves original claim and
  frozen source bytes; new production-compatible candidates add legitimate SQL
  teaching context to meet the existing Content schema. Original fixtures are
  unchanged. No synthetic report grants live reviewer qualification.

## Exact-HEAD CI evidence

The final Draft PR description is the append-only external CI evidence record:
it records final commit SHA, exact-HEAD PR and full workflow_dispatch run URLs,
job outcomes and Windows Core whole-job elapsed time. Keeping the final run
identifiers outside the commit avoids a report/self-commit SHA cycle. This report
defines the checked implementation inventory; final CI qualification is reported
only after both runs are green with zero failed/cancelled required jobs and
Windows Core within 30:00, under the unchanged 35-minute timeout.

Code and synthetic qualification readiness grants only Owner Review eligibility.
Real provider/model or human reviewer qualification and Owner-controlled external
deployment remain separate post-code gates. Skill 2.3.1, Content 2.3, Template
1.1.2, Acceptance 3.0, template binary and Benchmark policies are unchanged.
