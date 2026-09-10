# Whole-Course Orchestration Phase 1.2 Closeout — Content Integrity & Generalization

Current status: `READY_FOR_WHOLE_COURSE_BLIND_RETRY`

This closeout remains on PR #31 and the existing `feature/whole-course-orchestration` branch. It does not merge the PR, create another PR, upgrade the Courseware/Practice formal contracts, run the real 9-PPT blind retry, or claim teacher/pedagogical acceptance.

## A. Baseline, scope, and source boundary

- Repository: `ArdenZC/codex-work-skills`
- Branch: `feature/whole-course-orchestration`
- PR: #31
- Phase 1.1 baseline / Phase 1.2 pre-closeout HEAD: `436fc4a65cbb9eb2831690957ae19d3edfbafea9`
- Phase 1.2 implementation HEAD: `9c6bebef8d5a2513630a4e1f595106580acb792d`
- Closeout report commit: the final commit that contains this report
- `origin/master`: `3c8fe4a29a4a057cf24e1f3d2b691eb1f9c2408a`
- Frozen benchmark: `WHOLE_COURSE_FAILURE_BENCHMARK_V1`

Only domain-neutral orchestration, evidence, schema, packaging, and regression behavior was changed. The frozen legacy benchmark remains read-only evidence and is replayed as an intentional failure; it is not reused as new-generation input.

## B. Content-integrity and generalization fixes

The Phase 1.2 implementation closes the following correctness boundaries:

- Empty or malformed upstream inputs now fail closed before architecture readiness is reported; required collections and cross-artifact session coverage are checked.
- Theory and Practice duration invariants are enforced. Future knowledge cannot enter a session, and a teaching question is preserved as one coherent question with time-distributed beats/pages.
- Final student evidence is independent from teacher evidence. Marker plumbing is separate from typed semantic structure, and every planned visual must be observed in the final student artifact.
- Quiz quality, comparison semantics, page-specific script grounding, per-session Practice evidence, and per-task starter evidence are evaluated from rendered outputs rather than plan metadata.
- Practice similarity is normalized by knowledge and capability semantics, while healthy variation is retained; missing `rendered_practice` can never pass.
- PPTX mining follows `presentation.xml` relationship order, same-stem presentations use a full source-identity namespace, and legacy `.ppt` conversion preserves original provenance after temporary conversion.
- Decorative or low-value slides are not promoted to teaching content. Typed non-UML fixtures cover single-class, tree/graph, relational, and topology/dataflow structures without course-specific rules.
- External research retains explicit states and blocks when required research state is omitted. Final packaging is fail-closed on missing, failed, or blocked QA.

The implementation is in the Whole-Course scripts and schemas under `整门课程编排器/whole-course-orchestrator/`, with the downstream DOM evidence attributes in `HTML课件生成器/courseware-html-generator/scripts/render_courseware.py`.

## C. A–Z regression matrix

`tests/test_phase_1_2.py` contains 23 tests covering all requested scenarios:

| Cases | Covered assertion |
|---|---|
| A–F | Empty input, theory/practice duration, future knowledge, student-only observation, and marker-only fake all block or fail closed. |
| G–J | Single-class, tree/graph, relational, and topology/dataflow typed structures pass. |
| K–O | Generic grounding, trivial quiz, invalid distractors, and broken comparison fail; specific grounding and valid distractors pass. |
| P–Q | Missing Practice task and missing rendered Practice evidence fail session closure/release. |
| R–T | Presentation order, same-stem media identity, and legacy provenance are preserved. |
| U–V | Decorative classification and fail-closed final packaging are enforced. |
| W | Actual synthetic E2E and replay outputs validate against the runtime schemas. |
| X–Y | Near-identical Practice collapses; healthy varied Practice does not false-collapse. |
| Z | Omitted required research state blocks when gaps exist. |

## D. Schema and output validation

The runtime validation gate covers the actual strict E2E output tree and the frozen replay output. It validated 13 JSON outputs in the hosted Whole-Course job. The Phase 1.2 schema set covers plan QA, render QA, whole-course E2E, visual evidence, starter evidence, contact-sheet evidence, failure replay, external research, whole-course QA, and the current/legacy knowledge-graph asset-link shapes.

The installer dry-run, JSON loading, Python compilation, static package contracts, and clean-worktree checks also passed. No installer step silently installs Python dependencies.

## E. Local regression and strict E2E evidence

Local results from the committed implementation checkout:

- Whole-Course suite: `74 tests`, `OK`, `4 skipped` for optional local browser/provenance conditions.
- Courseware HTML suite: `38 tests`, `OK`.
- Practice Class HTML suite: `67 tests`, `OK`.
- CI change classifier: `16 tests`, `OK`.
- Workflow contract tests: `8 tests`, `OK`, `4 skipped` for unavailable Windows/macOS-specific local conditions.
- Static package contracts: `7` canonical package contracts, `PASS`.
- JSON schema loading, `compileall`, `git diff --check`, and install dry-run: `PASS`.

The local strict downstream run reached all three Courseware and all three Practice renderers, with strict Courseware/Practice QA, typed visual evidence, starter evidence, and final QA all `PASS`. The local machine did not expose a browser runtime for this run, so its contact sheet remained truthfully `DEGRADED` with `0` screenshots and `10` fallback thumbnails; this is not used as browser PASS evidence.

## F. Hosted strict E2E, browser proof, and failure replay

Hosted CI run for implementation HEAD: [34484730964](https://github.com/ArdenZC/codex-work-skills/actions/runs/34484730964), head `9c6bebef8d5a2513630a4e1f595106580acb792d`.

The Whole-Course job passed compilation, the 74-test architecture suite, strict downstream E2E, the real Chromium/Playwright contact-sheet proof, intentional migration-trust blocked regression, frozen failure replay, 13-output schema validation, installer dry-run, and clean-worktree verification. The strict command returned `status: PASS`, `browser_smoke_status: PASS`, with three Courseware and three Practice outputs.

The final closeout CI run prints the contact-sheet evidence directly: `status=PASS`, `browser_rendered=true`, `screenshot_count` greater than zero, `fallback_count=0`, Chromium/Playwright runtime, and `thumbnail_count` from the actual output. Any incomplete browser set fails the job; local fallback evidence is never upgraded to PASS.

Frozen replay remains an `EXPECT_FAIL` canary and returned `status: PASS` because the real normalized evidence returned `review_status: FAIL` with the expected findings: `COMPARISON_SEMANTIC_ERROR`, `SCRIPT_CROSS_SESSION_TEMPLATE_REUSE`, `WHOLE_COURSE_PRACTICE_SIMILARITY_COLLAPSE`, `WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE`, and `WHOLE_COURSE_TEMPLATE_COLLAPSE`. Snapshot SHA-256: `55a9ebdddeb4b3860448c1ecd4fb86368f3c0bc4036df6a8f7e73b0826c2e500`.

## G. Review disposition and remaining boundary

All five correctness review threads on PR #31 were replied to with commit-specific evidence and resolved. Final verification must report `0` unresolved correctness review threads. The PR remains open and unmerged.

Human review remains required for representative page readability, teaching value, Practice capacity, cross-session differentiation, external-source usefulness/licensing, and actual teacher acceptance. The real 9-PPT × 16-theory + 16-Practice blind retry is intentionally not executed in this phase.

## H. Final gate

`READY_FOR_WHOLE_COURSE_BLIND_RETRY` is a readiness gate only. It means the Phase 1.2 architecture, content-integrity, generalization, schema, packaging, hosted strict E2E, browser, replay, and review-thread gates are green. It does not mean the real course has passed, and it does not authorize the blind retry without a separate explicit step.
