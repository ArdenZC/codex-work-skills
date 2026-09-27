# Teaching Exemplar Benchmark Phase 1

This implementation is Lesson Skill **2.3.0** with Lesson Content **2.2**, Lesson Template **1.1.2**, Acceptance Schema **2.0**, Exemplar Contract **1.0**, and Benchmark Review **1.0**. The Word template binary is unchanged.

## Boundary and workflow

Benchmark evidence lives in sidecar JSON files. It does not add `student_evidence`, `success_criteria`, `analysis_basis`, `reflection_mode`, `exemplar_pool`, or `benchmark_review` to Lesson Content 2.2. The fixed nine-stage Lesson format, projectized positioning, theory/practice split, 10 / hours×45 / 15 timing, 85–96 half-point scores, Practice Task and WorkOrder boundaries, Word template, production transaction, and existing `reference_pool` meaning stay unchanged.

The workflow is fixed:

```text
Intake
→ Source Truth
→ Exemplar Discovery/Card
→ Catalog
→ Split
→ Outline
→ Lesson Authoring using A
→ existing pedagogical_review
→ Benchmark Review using B
→ bounded revision (at most two review rounds)
→ final Content 2.2 validation
→ DOCX generation
→ render
→ production publication
→ Acceptance
```

Benchmark Review happens before formal production DOCX publication. It must not trigger a post-render DOCX rewrite.

## Agent and Python responsibilities

The Agent discovers cases, makes the qualitative qualification judgment, abstracts Cards, assesses lesson relevance, chooses Authoring examples, identifies Benchmark gaps, and revises Lesson content. Python validates schemas, hashes, group isolation, A/B membership, sidecar links, round limits, status/count consistency, provenance, and descriptive byte counts. Python does not decide whether a case is good or relevant, or whether a Lesson is pedagogically strong.

Cards store abstract design patterns, not original lesson-plan prose. Do not copy original task wording, student data, case narrative, teacher language, charts, or uniquely named innovations. Phase 1 does not implement text similarity, n-gram checks, a crawler, search automation, downloader, scraper, manual override, or a Development Gold runner.

## Exemplar Card and Catalog

Each Card has the fields in `schemas/teaching-exemplar-card.schema.json`. The Catalog declares `exemplar_contract_version: "1.0"` once at its root. Cards do not repeat it. The schema only permits the enumerated source, scope, qualification, and abstract-pattern fields; it has no arbitrary blob property or raw-source-text property.

`source_identity_sha256` is SHA-256 over canonical JSON containing `canonical_url`, `title`, `institution`, `author_or_team`, and `recognition`. Each value is Unicode NFKC normalized, trimmed, and internal whitespace is collapsed. Canonical JSON uses UTF-8, sorted object keys, no insignificant spaces, and unescaped Unicode. This digest is for provenance and deduplication, not teaching similarity.

`catalog_fingerprint` is SHA-256 over the canonical JSON array of Cards sorted by `exemplar_id`. A Catalog with zero Cards is valid; its availability is decided by Split, not by Catalog validation.

`group_id` is the Agent-assigned identity for one original work and its direct derivatives: editions or lesson sessions of a competition work, PDF/PPT/web copies, course mirrors, press reproductions, and direct revisions by the same team. Python checks group IDs and split isolation; it cannot infer semantic source identity.

## Qualification and visibility

`authority_tier` is `A`, `B`, `C`, or `PRIVATE`; `visibility` is `public` or `private_session`; qualification is `QUALIFIED`, `CONDITIONAL`, `DISCOVERY_ONLY`, or `REJECTED`. Tier A/B may be QUALIFIED; Tier C may not. PRIVATE must use `private_session`. `private_user_provided` also requires PRIVATE and `private_session`. Only QUALIFIED Cards enter the Phase 1 Split. CONDITIONAL, DISCOVERY_ONLY, and REJECTED Cards remain in the Catalog but never enter A or B. Python checks these explicit combinations; the Agent supplies the rationale and patterns.

Private exemplars may be used in a run-time Catalog, Authoring set, or Holdout set. They must not be placed in development holdouts, committed Development Gold, or a shared Catalog.

## Deterministic Split

The Split unit is `group_id`, never an individual Card. For each unique QUALIFIED group, compute:

```text
SHA256(catalog_fingerprint + "\n" + group_id)
```

Sort groups by that lowercase hexadecimal digest, ascending. Assign the fixed repeated pattern `A, B, B, A, B, B, ...`, where A is Authoring and B is Holdout. Every QUALIFIED Card follows its group's assignment. No random function, topic score, or semantic ranking changes the side.

Availability is `UNAVAILABLE` for zero or one qualified groups, `PARTIAL` for two, and `AVAILABLE` for three or more. Thus one group goes to A and has no Holdout; two groups form A/B and remain PARTIAL. A Split is frozen before per-Lesson selection. Its fingerprint covers the deterministic Split contract fields and excludes `created_at`, so regenerating from the same Catalog gives the same membership, `split_id`, and `split_fingerprint` even though the creation timestamp may change.

## Per-Lesson Selection and context report

`exemplar-selection.json` is an Agent-authored semantic selection. Authoring IDs must come from A and Holdout IDs from B. A group can never cross sides. Per Lesson, Authoring is capped at five Cards and Holdout at four. The target is three Authoring Cards and two or three Holdout Cards, not a quota. Zero is valid when status matches: `SELECTED` requires IDs; `NO_RELEVANT_EXEMPLAR` and `UNAVAILABLE` require an empty list; a side with no Cards must be UNAVAILABLE.

Validating selection prints descriptive `catalog_total_bytes`, `selected_authoring_card_bytes_per_lesson`, and `selected_holdout_card_bytes_per_lesson`. Byte counts are canonical UTF-8 JSON sizes. There is no semantic context threshold.

## Reviewer isolation and Review contract

Reviewer input is limited to final reviewed Lesson content, confirmed course context/Source Truth summary, selected Holdout Cards, and the Benchmark Rubric. Do not include Author hidden reasoning, Authoring Cards, or the Author prompt transcript. The Review attests:

```json
{
  "authoring_exemplars_visible": false,
  "author_reasoning_visible": false,
  "holdout_only": true
}
```

Python rejects a false attestation but cannot prove what an Agent prompt actually contained.

Every Lesson with selected Holdout Cards has exactly one review for each of the 15 fixed dimensions. A Lesson without selected Holdout Cards has no dimension review and contributes to `lessons_without_holdout`. Dimension statuses and allowed severity are:

| Status | Allowed severity |
| --- | --- |
| `MEETS` | `none`, `advisory` |
| `PARTIAL` | `minor`, `advisory` |
| `GAP` | `major`, `minor` |
| `NOT_APPLICABLE` | `none` |
| `INSUFFICIENT_EVIDENCE` | `major`, `minor`, `advisory` |

The 15 dimension IDs are fixed in `schemas/benchmark-review.schema.json`. No score, total, rating, percentage, rank, or similarity field is allowed. Python only reports `major_gap_count` (major GAP dimensions), `minor_gap_count` (minor GAP dimensions), and `insufficient_evidence_count`; it does not calculate a pedagogy score.

`source_lesson_content_sha256` is SHA-256 of the exact UTF-8 Lesson Content JSON bytes reviewed. `holdout_selection_sha256` hashes canonical JSON of `catalog_id`, `split_id`, and each sorted Lesson's holdout status and sorted selected IDs; authoring IDs and author rationale are excluded. `rubric_version` is `lesson-teaching-benchmark-v1`. Round 2 must cite the Round 1 review SHA and source digest, and its source digest must differ. The validator rejects any round beyond 2 and requires the Catalog, Split, Selection, and Holdout selection digest to stay fixed between rounds.

Decision rules are deterministic over the Agent-authored dimension statuses:

- Any major GAP in Round 1 means `REVISION_REQUIRED`.
- Any major GAP in Round 2 means `HUMAN_REVIEW_REQUIRED`.
- Any insufficient-evidence dimension means `HUMAN_REVIEW_REQUIRED`.
- With no major or insufficient-evidence dimensions, a minor/advisory-only review can be `NO_REVISION_REQUIRED`.
- A two-group or otherwise incomplete review with Holdout evidence is `BENCHMARK_PARTIAL` unless a stronger gap decision applies. With no Lesson Holdout evidence, it is `BENCHMARK_UNAVAILABLE`.

These are decision gates over explicit evidence counts, not a quality score. Benchmark decisions cannot declare a whole course failed.

## Acceptance and unavailable cases

Acceptance Schema stays 2.0. `tests/lesson_acceptance.py --benchmark-review <path>` is optional. Without it, the old report and status behavior are unchanged. With it, Acceptance validates Review 1.0, adds a compact optional `benchmark_review` report object, and checks the reviewed Lesson digest against the Content 2.2 input. If the decision is `REVISION_REQUIRED` or `HUMAN_REVIEW_REQUIRED`, an otherwise passing result is capped at `PENDING_MANUAL_REVIEW`. Existing teacher, visual, and Teaching Design manual layers remain required. Only an explicit human failure decision can set `FAILED`.

`BENCHMARK_UNAVAILABLE` is not a structural error. Lesson validation, DOCX generation, rendering, and production status continue under their existing gates; Acceptance still requires its existing human evidence. Never add unrelated Cards to turn the Benchmark available.

## Phase 2 exclusions

This Phase 1 implementation reserves schemas, split semantics, and fingerprints only. Development Gold execution/scoring, automatic web discovery, `student_evidence` as a Content field, `analysis_basis`, `reflection_mode`, Template upgrade, and Content Contract upgrade are deferred to a separate phase.

## Local sidecar commands

```powershell
python scripts/exemplar_contract.py catalog examples/exemplar-catalog.example.json
python scripts/exemplar_split.py --catalog examples/exemplar-catalog.example.json --output exemplar-split.json
python scripts/exemplar_contract.py selection --catalog examples/exemplar-catalog.example.json --split exemplar-split.json --selection <selection.json>
python scripts/validate_benchmark_review.py --review examples/benchmark-review.example.json --review-only
```

The example review is explicitly unavailable and has no teaching quality judgment. E2E synthetic benchmark evidence is test scaffolding only; it does not claim real teaching quality.
