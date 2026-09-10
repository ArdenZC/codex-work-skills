# Whole-Course Orchestration Phase 1.1 Closeout — Evidence Authenticity & Browser-Gated Batch QA

Current status: `READY_FOR_WHOLE_COURSE_BLIND_RETRY`

This closeout stays on PR #31 and the existing `feature/whole-course-orchestration` branch. It does not open a new PR, merge, tag, upgrade the Courseware/Practice formal contract versions, run the real 9-PPT whole-course retry, or edit the frozen old UML outputs.

## A. Baseline and scope

- Repository: `ArdenZC/codex-work-skills`
- Branch: `feature/whole-course-orchestration`
- PR: #31
- Pre-closeout HEAD: `2af32d574658ff43c959cd265ef8f5540184e992`
- Validated implementation HEAD: `a1f70e580df695da91c019e5b2b27ed63b0e55af`
- `origin/master`: `3c8fe4a29a4a057cf24e1f3d2b691eb1f9c2408a`
- Frozen benchmark: `WHOLE_COURSE_FAILURE_BENCHMARK_V1`
- Source boundary: the benchmark manifest and its external source/build roots are read-only evidence; no old contract, old HTML, or old repair advice is used as new-generation input.

The final closeout gate moved to `READY_FOR_WHOLE_COURSE_BLIND_RETRY` only after the same-PR clean strict E2E, browser evidence, architecture tests, stable regression matrix, and frozen failure replay passed. Human pedagogical acceptance is a separate boundary and is not silently converted into an automated pass.

## B. Visual observation policy

`collect_visual_evidence.py` now fails closed when any declared visual plan is absent from the final DOM. Overall `PASS` is an all-plans aggregation, not an “any visual passed” aggregation. A declared plan with no real `svg`, `img`, `canvas`, or visual container is `PLANNED_NOT_OBSERVED` and makes the overall report `FAIL`.

Supporting visuals without a typed semantic contract can pass as observed supporting evidence. A typed visual requires both marker plumbing and a structural check. The implementation no longer treats a planned role list or a role-bearing rectangle as a real diagram.

## C. Marker evidence versus semantic structure

The evidence report exposes separate `semantic_marker_evidence` and `semantic_structure_evidence` records. The structural validators cover:

- `class_model`: class nodes, relationship endpoints, relation kinds, and multiplicity labels attached to an edge;
- `sequence_model`: lifelines, message endpoints, order, return messages, and optional fragment;
- `state_model`: state nodes, transition endpoints, and event/guard association;
- `deployment_model`: node/artifact nodes and deployment or communication endpoints;
- `use_case_model`: actor/use-case nodes and typed association/include/extend endpoints;
- `activity_model`: action/control-flow endpoints and decision outgoing paths/guards.

T34–T38 cover missing observation, supporting SVG, marker-only false evidence, and typed structure fixtures. Marker-only migration output is intentionally not a strict PASS; the strict adapter emits explicit typed node/edge fixtures for the architecture E2E.

## D. Real frozen failure evidence and replay

`extract_failure_benchmark_evidence.py` reads the already-frozen source/build records and emits `REAL_FROZEN_FAILURE_EVIDENCE`. It records the benchmark hash, original package hash, recursive source/artifact hashes, extractor version, extraction timestamp, 16 theory sessions, 16 practice sessions, page/block/script/visual/comparison/quiz evidence, task/capability/step/artifact evidence, and starter signatures.

- Snapshot: `benchmarks/WHOLE_COURSE_FAILURE_BENCHMARK_V1/failure-evidence-snapshot.json`
- Snapshot SHA-256: `55a9ebdddeb4b3860448c1ecd4fb86368f3c0bc4036df6a8f7e73b0826c2e500`
- Original package SHA-256: `4948df91029c0ea7a66ecbd0f82501079df0258991a1a18e6530ea1ee013690a`
- Extraction integrity: `PASS`, 510 files checked, no missing files and no mismatches.
- Replay: `benchmarks/WHOLE_COURSE_FAILURE_BENCHMARK_V1/failure-benchmark-replay.json`
- Replay semantics: `EXPECT_FAIL` returned success because the normalized real evidence was classified `FAIL` and all expected findings were observed.

Observed findings include `WHOLE_COURSE_TEMPLATE_COLLAPSE`, `WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE`, `SCRIPT_CROSS_SESSION_TEMPLATE_REUSE`, plus the evidence-derived `COMPARISON_SEMANTIC_ERROR`. This is an immutable regression canary, not a synthetic handwritten failure.

## E. External authority trust layers

External research now records `CLAIMED`, `OBSERVED_METADATA`, and `VERIFIED_IDENTITY` separately. URL/domain parsing is only observed locator metadata. The output status is one of `VERIFIED_OFFICIAL`, `VERIFIED_ACADEMIC`, `ASSESSED_REFERENCE`, `UNVERIFIED_OFFICIAL_CLAIM`, or `UNKNOWN`.

- R1: fake official domain remains `UNVERIFIED_OFFICIAL_CLAIM` and `external-reference`.
- R2: explicit trusted publisher/domain evidence produces `VERIFIED_OFFICIAL` and `web_official`.
- R3: explicit academic publisher plus trusted registry evidence produces `VERIFIED_ACADEMIC` and `web_academic`.

No URL-only candidate is allowed to become authoritative.

## F. Strict Courseware E2E

The strict path invokes the real Courseware renderer with `--evidence-mode strict` and a source root containing source-backed facts. It does not rely on a fake renderer or a handwritten QA result. Strict provenance requires a committed clean worktree; the final local and CI runs both used clean committed checkouts.

Local strict execution at final closeout HEAD: `PASS` in a committed clean worktree; three Courseware sessions reached the real renderer, strict QA passed, and typed semantic structure evidence passed. The same strict command passed in CI run [34467928760](https://github.com/ArdenZC/codex-work-skills/actions/runs/34467928760).

## G. Strict Practice E2E

The strict path invokes the real Practice renderer with the same strict source-evidence boundary, observes the generated starter/manifest/QA/behavior artifacts, and keeps the migration-trust path separate. No Practice renderer version or contract version is changed.

Local strict execution at final closeout HEAD: `PASS` in a committed clean worktree; three Practice sessions reached the real renderer, generated starters/manifests/behavior evidence, and strict QA passed. The same strict command passed in CI run [34467928760](https://github.com/ArdenZC/codex-work-skills/actions/runs/34467928760).

## H. Browser runtime gate

The Whole-Course CI job now provisions Node 20, installs Playwright, installs Chromium, and passes the installed package root to the contact-sheet collector. The formal strict E2E command has no `--no-browser` and no `--allow-degraded-browser`.

The task-scoped local Windows proof used Node Playwright with Chromium `153.0.8010.12`; CI independently installed the Linux Chromium runtime and completed the real browser gate. The formal strict E2E command had no `--no-browser` or `--allow-degraded-browser`.

## I. Contact-sheet evidence

`contact_sheets.py` records browser runtime, browser version, viewport, render method, screenshot count, fallback count, and browser failures. With no runtime it returns `DEGRADED`; when a browser attempt produces a partial screenshot set it returns `FAIL`; only complete real Chromium screenshots can return `PASS`.

The synthetic E2E and CI formal gate request real theory-page, visual-artifact, and Practice `student-task.html` screenshots. At final local proof the contact sheet was `PASS` with 10 screenshots, 0 fallbacks, Chromium `153.0.8010.12`, and viewport `1280x800`. Source-image/SVG fallback is retained as review material but cannot satisfy the browser gate. CI logs independently show the strict browser command returned `PASS`.

## J. Phase 1.1 tests

Local final result: `51 tests`, `OK`, `0 skipped`, including the real Chromium contact-sheet and supporting-SVG screenshot tests. CI run [34467928760](https://github.com/ArdenZC/codex-work-skills/actions/runs/34467928760) also reports `Ran 51 tests ... OK`. T34–T45, R1–R3, the partial-browser-failure boundary, and the cross-platform frozen-snapshot path are present in the suite.

## K. Stable downstream regressions

The closeout preserves the existing downstream renderer boundaries and adds no Courseware/Practice formal version upgrade. Previously verified stable Courseware and Practice regression suites remain separate from this architecture evidence. The final same-PR CI run re-confirmed the repository’s Courseware, Practice, package-contract, tooling, release, lesson-plan, gradebook, and WorkOrder checks successfully.

## L. CI and install coverage

The Whole-Course job now performs, in order: Node/Playwright/Chromium setup, compile, architecture tests, strict browser-enabled downstream E2E, intentional migration-trust compatibility E2E, real frozen failure replay, installer dry-run, and clean-worktree verification. The migration compatibility run is accepted only when its intentionally marker-only visual evidence remains blocked; it cannot satisfy the strict gate.

The installer required-file list includes both benchmark evidence scripts. No Python dependency is silently installed by the installer.

CI status: `PASS` for [run 34467928760](https://github.com/ArdenZC/codex-work-skills/actions/runs/34467928760), head `a1f70e580df695da91c019e5b2b27ed63b0e55af`. The Whole-Course job passed architecture tests, strict browser-enabled E2E, the intentional migration-trust blocked regression, frozen failure replay, installer dry-run, and clean-worktree verification.

## M. Remaining P0/P1/P2 boundaries

- P0: no remaining automated architecture P0 after the same-PR green CI gate. The real 9-PPT × 16 theory + 16 practice blind retry is intentionally not authorized or executed in this phase.
- P1: human review of representative theory pages, typed diagrams, Practice starters, capacity, and cross-session differentiation remains separate and unevaluated.
- P2: external-source copyright/licensing and pedagogical usefulness still require human review when external sources are actually selected.

No code path upgrades a missing browser, marker-only visual, or automated QA result into a final whole-course PASS.

## N. Final status gate

Current final status:

```text
READY_FOR_WHOLE_COURSE_BLIND_RETRY
```

This transition records only that the architecture and evidence gates are ready. It does not authorize or execute the blind retry itself; that remains a later, explicit phase. Human pedagogical acceptance is reported separately and is never implied by this gate.
