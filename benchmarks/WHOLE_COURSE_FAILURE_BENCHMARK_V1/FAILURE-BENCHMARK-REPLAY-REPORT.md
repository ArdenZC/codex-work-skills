# WHOLE_COURSE_FAILURE_BENCHMARK_V1 — Frozen Evidence Replay

Status: `EXPECT_FAIL` replay `PASS`; the frozen course itself remains `FAIL`.

This report is bound to the immutable benchmark manifest and to the normalized snapshot produced by `extract_failure_benchmark_evidence.py`. The extractor reads the already-frozen source/build outputs and never reruns, edits, or uses the old UML course as new-generation input.

## Provenance

- Benchmark: `WHOLE_COURSE_FAILURE_BENCHMARK_V1`
- Frozen shape: 9 source PPTs, 1,035 source slides, 16 theory sessions, 16 practice sessions, 120 theory minutes and 120 practice minutes per session.
- Frozen renderer baseline: Courseware `1.2.1`; Practice `1.2.0`.
- Snapshot type: `REAL_FROZEN_FAILURE_EVIDENCE`
- Snapshot SHA-256: `55a9ebdddeb4b3860448c1ecd4fb86368f3c0bc4036df6a8f7e73b0826c2e500`
- Original frozen package SHA-256: `4948df91029c0ea7a66ecbd0f82501079df0258991a1a18e6530ea1ee013690a`
- Extraction integrity: `PASS`; 510 frozen files checked, with no missing file and no hash mismatch.

The source/build roots recorded in the manifest remain external frozen evidence. CI replays the normalized snapshot and verifies the manifest hash; it does not require those external roots to be present and does not regenerate the historical course.

## Replay result

`replay_failure_benchmark.py --expect-fail` returned exit code 0 because the snapshot was verified, the review classified the course as `FAIL`, and all expected finding codes were observed.

Expected findings from the frozen manifest:

- `SCRIPT_CROSS_SESSION_TEMPLATE_REUSE`
- `WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE`
- `WHOLE_COURSE_TEMPLATE_COLLAPSE`

Observed findings derived from normalized theory/practice evidence:

- `COMPARISON_SEMANTIC_ERROR` (additional evidence-derived finding)
- `SCRIPT_CROSS_SESSION_TEMPLATE_REUSE`
- `WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE`
- `WHOLE_COURSE_TEMPLATE_COLLAPSE`

The replay is therefore an immutable regression canary: it must continue to fail for the historical evidence, while the new strict synthetic downstream path is evaluated independently.
