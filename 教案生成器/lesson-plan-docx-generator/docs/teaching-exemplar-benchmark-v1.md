# Teaching Exemplar Benchmark Phase 1

This implementation is Lesson Skill **2.3.0** with Lesson Content **2.2**, Lesson Template **1.1.2**, Acceptance Schema **2.0**, Exemplar Contract **1.0**, and Benchmark Review **1.0**. The Word template binary is unchanged.

## Fixed boundary and workflow

Benchmark evidence lives in sidecar JSON files. It does not add `student_evidence`, `success_criteria`, `analysis_basis`, `reflection_mode`, `exemplar_pool`, or `benchmark_review` to Lesson Content 2.2. The fixed nine-stage Lesson format, projectized positioning, theory/practice split, 10 / hours×45 / 15 timing, 85–96 half-point scores, Practice Task and WorkOrder boundaries, Word template, production transaction, and existing `reference_pool` meaning stay unchanged.

The workflow and role visibility are fixed:

```text
Intake + Source Truth + whole-course outline
→ Curator-only discovery/Cards/Catalog/Split
→ deterministic physical Authoring Pack A and Holdout Pack B
→ Author receives only Source Truth + outline + Pack A
→ Authoring Selection bound to the existing outline digest
→ Lesson Content 2.2 authoring + existing pedagogical_review
→ Reviewer receives final reviewed Content + Source Truth summary + Pack B + rubric
→ Holdout Selection bound to exact Round 1 Content bytes
→ full-linkage Benchmark Review validation
→ bounded revision (at most two rounds, same frozen Pack B/Selection)
→ final Content 2.2 validation
→ DOCX generation → render → production publication → Acceptance full linkage
```

Benchmark Review validation must finish before DOCX generation, render, and production publication. It must not trigger a post-render DOCX rewrite.

Three logical roles have separate contexts:

- **Curator Agent** may see Source Truth summary, external case materials, the complete Catalog, and deterministic Split. It structures discovery results, qualifies and abstracts Cards, and assigns `group_id`. It does not author Lesson content.
- **Author Agent** may see Source Truth, the whole-course outline, Authoring Pack A, and Authoring Selection. It must not receive the full Catalog, Split B IDs, Holdout Pack, Holdout Selection, or Reviewer output.
- **Reviewer Agent** may see final pedagogically reviewed Lesson Content, Source Truth summary, Holdout Pack B, Holdout Selection, and the Benchmark Rubric. It must not receive Pack A, Author hidden reasoning, or Author prompt transcript.

Catalog and Split are Curator-only provenance, not Author or Reviewer prompt inputs. Separate runtime contexts enforce role visibility. Python validates artifacts and attestations; it cannot prove the actual prompt isolation.

## Exemplar Card and Catalog

Each Card follows `schemas/teaching-exemplar-card.schema.json`. The Catalog declares `exemplar_contract_version: "1.0"` once at its root; Cards do not repeat it. The schema only permits enumerated source, scope, qualification, and abstract-pattern fields, not arbitrary blobs or raw-source text.

`source_identity_sha256` is SHA-256 over canonical JSON containing `canonical_url`, `title`, `institution`, `author_or_team`, and `recognition`. Values use Unicode NFKC normalization, trimming, and collapsed internal whitespace. Canonical JSON uses UTF-8, sorted keys, no insignificant spaces, and unescaped Unicode. This digest supports provenance and deduplication, not teaching similarity. Core provenance strings cannot be empty; the tool does not invent missing source facts.

`catalog_fingerprint` is SHA-256 over the canonical JSON array of Cards sorted by `exemplar_id`. A Catalog with zero Cards is valid; availability is decided by Split.

`group_id` identifies one original work and its direct derivatives: editions or sessions of a competition work, PDF/PPT/web copies, course mirrors, press reproductions, and direct revisions by the same team. Catalog validation rejects a `source_identity_sha256` mapped to multiple group IDs and a normalized canonical URL mapped to multiple groups. Multiple Cards from one source are allowed when they share the same `group_id`. Python cannot infer semantic source identity.

## Qualification, visibility, and Split

`authority_tier` is `A`, `B`, `C`, or `PRIVATE`; `visibility` is `public` or `private_session`; qualification is `QUALIFIED`, `CONDITIONAL`, `DISCOVERY_ONLY`, or `REJECTED`. Tier A/B may be QUALIFIED; Tier C may not. PRIVATE must use `private_session`. `private_user_provided` also requires PRIVATE and `private_session`. A `discovery_source` cannot be QUALIFIED regardless of tier. Only QUALIFIED Cards enter Split.

A QUALIFIED Card must contain at least one item across the eight permitted teaching-pattern arrays and at least one `do_not_copy` item. This is a structural evidence floor, not a quality judgment. CONDITIONAL, DISCOVERY_ONLY, and REJECTED Cards remain in Catalog but never enter A or B.

Private exemplars may be used in a runtime Catalog, Authoring Pack, or Holdout Pack. They must not enter development holdouts, committed Development Gold, or a shared Catalog.

Split partitions `group_id`, never individual Cards. For each unique QUALIFIED group, compute:

```text
SHA256(catalog_fingerprint + "\n" + group_id)
```

Sort groups by lowercase hexadecimal digest, ascending. Assign the fixed repeated pattern `A, B, B, A, B, B, ...`; all Cards in a group follow the same side. No random function, topic score, or semantic ranking changes the side.

Availability is `UNAVAILABLE` for zero or one qualified groups, `PARTIAL` for two, and `AVAILABLE` for three or more. A Split is frozen before per-Lesson selection. Its fingerprint covers deterministic Split fields and excludes `created_at`, so regenerating from the same Catalog gives identical membership, `split_id`, and `split_fingerprint`.

## Deterministic physical Packs

`build_exemplar_pack(catalog, split, role)` creates a role-scoped Pack. Authoring Pack contains exactly `split.authoring_exemplar_ids`; Holdout Pack contains exactly `split.holdout_exemplar_ids`. Pack fingerprints cover role, Catalog and Split IDs/fingerprints, sorted exemplar IDs, and sorted Card payloads using canonical JSON. Validation recomputes the fingerprint and requires exact membership; missing, extra, substituted, or reordered Cards cannot alter the result.

Generate the Split and both physically separate Packs with one `exemplar_split.py` invocation. Callers must not filter the complete Catalog themselves. Author runtime loads only the Authoring Pack; Reviewer runtime loads only the Holdout Pack.

## Separate per-Lesson Selections

`exemplar-authoring-selection.json` and `exemplar-holdout-selection.json` are distinct sidecars; neither combines both roles.

- Authoring Selection IDs must belong to Pack A. Its Lesson ID set must exactly equal `outline[].lesson_id`, and `source_outline_sha256` must equal the existing `authoring_provenance.source_snapshot.whole_course_outline_sha256`. It binds the already-defined outline digest, not a new hash or final Lesson digest.
- Holdout Selection IDs must belong to Pack B. Its Lesson ID set must exactly cover every Lesson Content lesson ID. `source_lesson_content_sha256` is SHA-256 of the exact Lesson Content JSON bytes used to freeze Round 1 selection.

Each row has `SELECTED`, `NO_RELEVANT_EXEMPLAR`, or `UNAVAILABLE` status, a rationale, and zero or more IDs. SELECTED requires IDs; the other statuses require none; an empty side must be UNAVAILABLE. Per Lesson caps are five Authoring and four Holdout Cards. Targets of three Authoring and two or three Holdout Cards are guidance, not quotas; zero is allowed when status matches.

Selection validation reports descriptive Catalog/Pack and per-Lesson selected Card byte counts. Counts are canonical UTF-8 JSON sizes; there is no semantic context threshold.

## Reviewer isolation and Review evidence

The Review attests:

```json
{
  "authoring_exemplars_visible": false,
  "author_reasoning_visible": false,
  "holdout_only": true
}
```

Python rejects a false attestation but cannot prove what a prompt actually contained. The Review `lessons` rows contain only `lesson_id` and `dimensions`; selection rows stay in the Holdout Selection sidecar. Full validation requires Review IDs, Holdout Selection IDs, and Lesson Content IDs to match exactly, with no missing, extra, or duplicate Lesson.

A Lesson with selected Holdout Cards must have exactly one review for each of the 15 fixed dimensions. A Lesson without selected Holdout Cards has zero dimensions and contributes to `lessons_without_holdout`. For `MEETS`, `PARTIAL`, `GAP`, and `INSUFFICIENT_EVIDENCE`, `current_evidence`, `benchmark_pattern`, and at least one Holdout citation are required. `PARTIAL`, `GAP`, and `INSUFFICIENT_EVIDENCE` also require non-empty `gap` and `recommended_direction`. `NOT_APPLICABLE` requires an explanation in `current_evidence`; other evidence and citations may be empty. Every citation must belong to Pack B and that Lesson's Holdout Selection.

Dimension statuses and allowed severity are:

| Status | Allowed severity |
| --- | --- |
| `MEETS` | `none`, `advisory` |
| `PARTIAL` | `minor`, `advisory` |
| `GAP` | `major`, `minor` |
| `NOT_APPLICABLE` | `none` |
| `INSUFFICIENT_EVIDENCE` | `major`, `minor`, `advisory` |

The 15 dimension IDs are fixed in `schemas/benchmark-review.schema.json`. No score, total, rating, percentage, rank, or similarity field is allowed. Python reports explicit major/minor GAP and insufficient-evidence counts; it does not calculate a pedagogy score.

`source_lesson_content_sha256` hashes exact Lesson Content bytes. `holdout_selection_sha256` hashes the entire canonical Holdout Selection payload; Authoring Selection is never included. `rubric_version` is `lesson-teaching-benchmark-v1`.

Decision rules are deterministic over Agent-authored statuses:

- Any major GAP in Round 1 means `REVISION_REQUIRED`.
- Any major GAP in Round 2 means `HUMAN_REVIEW_REQUIRED`.
- Any insufficient-evidence dimension means `HUMAN_REVIEW_REQUIRED`.
- With no major or insufficient-evidence dimensions, a minor/advisory-only review can be `NO_REVISION_REQUIRED`.
- Incomplete Holdout coverage is `BENCHMARK_PARTIAL` unless a stronger gap decision applies. With no Lesson Holdout evidence, it is `BENCHMARK_UNAVAILABLE`.

These are gates over evidence counts, not a quality score. Benchmark decisions cannot declare a whole course failed.

## Round 2 provenance

At most two review rounds are allowed. Round 2 must provide `--previous-review` and `--previous-lesson-content` and fully revalidate Round 1 against the same Catalog, Split, Holdout Pack, Holdout Selection, Lesson coverage, dimensions, citations, counts, decision, isolation, and status.

The validator proves:

```text
SHA256(previous Lesson Content)
== Round 1.source_lesson_content_sha256
== Round 2.prior_source_lesson_content_sha256
== Holdout Selection.source_lesson_content_sha256

SHA256(current Round 2 Lesson Content)
== Round 2.source_lesson_content_sha256
!= prior_source_lesson_content_sha256
```

Holdout Pack and Holdout Selection stay frozen; do not reselect easier examples. Preserve `benchmark-round1-lesson-content.json` and `benchmark-round1-review.json` as provenance outside production Lesson Content.

## Acceptance and unavailable cases

Acceptance Schema remains 2.0, with an optional `benchmark_review` object. Without Benchmark input, the existing report and status behavior is unchanged. If `--benchmark-review` is supplied, Acceptance requires `--benchmark-catalog`, `--benchmark-split`, `--benchmark-holdout-pack`, and `--benchmark-holdout-selection` and performs full-linkage validation. Round 2 additionally requires `--benchmark-previous-review` and `--benchmark-previous-content`. Missing provenance fails closed. The report records validated Catalog, Split, Pack, Holdout Selection, and Review digests. The validator's `--review-only` mode is schema/debug inspection only, not production Acceptance evidence.

If the decision is `REVISION_REQUIRED` or `HUMAN_REVIEW_REQUIRED`, an otherwise passing result is capped at `PENDING_MANUAL_REVIEW`. Existing teacher, visual, and Teaching Design manual layers remain required. Only an explicit human failure decision can set `FAILED`.

`BENCHMARK_UNAVAILABLE` is not a structural error. Lesson validation, DOCX generation, rendering, and production status continue under existing gates. `production_pass` means the artifact production technical chain passed; it does not mean Benchmark is complete. Never add unrelated Cards to turn the Benchmark available.

## Phase 2 exclusions

This Phase 1 implementation reserves schemas, split semantics, and fingerprints only. Development Gold execution/scoring, automatic web discovery, `student_evidence` as a Content field, `analysis_basis`, `reflection_mode`, Template upgrade, and Content Contract upgrade are deferred to a separate phase. Do not browse, download, or create real-source Cards as part of this implementation; synthetic test evidence is not a teaching-quality claim.

## Local sidecar commands

```powershell
python scripts/exemplar_contract.py catalog examples/exemplar-catalog.example.json
python scripts/exemplar_split.py --catalog examples/exemplar-catalog.example.json --output exemplar-split.json --authoring-pack exemplar-authoring-pack.json --holdout-pack exemplar-holdout-pack.json
python scripts/exemplar_contract.py pack --catalog examples/exemplar-catalog.example.json --split exemplar-split.json --pack exemplar-authoring-pack.json
python scripts/exemplar_contract.py authoring-selection --catalog <catalog.json> --split <split.json> --pack <authoring-pack.json> --selection <authoring-selection.json> --lesson-content <lesson-content.json>
python scripts/exemplar_contract.py holdout-selection --catalog <catalog.json> --split <split.json> --pack <holdout-pack.json> --selection <holdout-selection.json> --lesson-content <lesson-content.json>
python scripts/validate_benchmark_review.py --review examples/benchmark-review.example.json --review-only
```

The example review is schema/debug-only and explicitly unavailable; it has no teaching-quality judgment. A production Review validation command must provide full provenance and finish before invoking `generate_lesson_plans.py --render`. E2E synthetic evidence is test scaffolding only.
