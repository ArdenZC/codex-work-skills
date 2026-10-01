# Visual Review Authority Contract 1.0

Opt-in LIF-05, Skill 2.3.1. The machine freezes scope; an external human/Agent performs
actual visual inspection. The engine never sees a rendered page and never invents
checks, notes, or decisions. Synthetic CI evidence proves contract closure only,
not real teaching quality or actual human acceptance. Generator `production_pass`
means generator/artifact transaction passed; it is not lifecycle ACCEPTED.

## Required scope

`prepare-visual-review` requires PRODUCTION / ARTIFACT_QA_PASSED. It freezes
`visual-review-packet.json` and its byte binding without a transition. Shared
`visual_sampling.py` is the original Acceptance 2.0 policy: first/last, both sides
of unit boundaries, first Lesson of each project, maximum content/implementation/
evaluation density, maximum retained PDF pages, and deterministic content-seeded
15% supplemental (the historical 10–20% rule). Content order determines the
manifest file mapping. Every sampled file must be in the current Artifact Manifest.
Legacy Acceptance imports the same helper; frozen pre-extraction golden vectors
prove its original output remains unchanged.

Required pages are deterministic: one page -> `[1]`; two -> `[1,2]`; three or more
-> sorted unique `{1, ceil(page_count/2), page_count}`. Page counts come from the
verified retained PDFs. Extra inspected files/pages are allowed if present and
within bounds; all required files/pages must be covered.

Packet binds run ID, Content SHA, Artifact Manifest SHA, Artifact QA SHA, policy,
required files/PDFs/pages/reasons, timestamp and self fingerprint. On every resume
it is rebuilt from current verified artifacts and compared exactly, after checking
its own fingerprint. Recomputing a fake fingerprint cannot choose different scope.

## External inspection and authority

Use existing `record_visual_inspection.py` to record actual inspected files/pages
and all eleven passed/failed checks: clipping, overflow, overlap, blank_pages,
abnormal_page_break, large_blank_block, missing_text, text_outside_table,
abnormal_row_height, table_boundary, broken_nested_evaluation_table.

Evidence and all lifecycle sidecars must remain **outside** the immutable final
output directory; use the run workspace. Never modify an already authorized output.

After actual inspection, build the Authority from the supplied decision and notes:

```text
python scripts/visual_review_authority.py --run <run.json> --evidence <inspection.json> \
  --decision PASSED --notes "external inspection record" --output <authority.json>
python scripts/run_lesson_pipeline.py bind-visual-review --run <run.json> \
  --visual-review <authority.json> --visual-evidence <inspection.json>
```

Decision is only PASSED or REVISION_REQUIRED. PASSED requires eleven passed checks;
REVISION_REQUIRED requires explicitly failed evidence with at least one failed
check. The existing inspector's default remains passed-only for legacy callers;
the new Authority uses its explicit diagnostic option to validate failed evidence.
Notes cannot override a failed check; notes alone do not imply an advisory.

Authority binds all Packet provenance, Packet bytes SHA, inspection bytes SHA,
actual files/pages, the external decision/notes, timestamp and fingerprint. Validator
reruns the existing inspector, full Artifact verification, scope rederivation and
exact Authority rederivation. DOCX, PDF, QA, manifest, Packet or evidence changes
invalidate the Authority. The old DOCX+QA output fingerprint is insufficient by
itself; retained PDF SHA/page verification always runs.

Only PASSED advances ARTIFACT_QA_PASSED -> VISUAL_REVIEW_APPROVED, with Authority
bytes SHA as transition evidence and `visual_review_sha256`. REVISION_REQUIRED is
valid diagnostic evidence but cannot advance. Revisions require a new run and
new generation chain. Candidate sidecars are validated before atomic publication.
