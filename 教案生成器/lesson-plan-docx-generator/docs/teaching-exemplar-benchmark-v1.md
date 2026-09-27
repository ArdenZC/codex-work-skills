# Lesson Teaching Exemplar Benchmark 1.0

适用于 Lesson Skill **2.3.0**、Lesson Content Contract **2.2**、Lesson Template **1.1.2**、Exemplar Contract **1.0**、Benchmark Review **1.0** 和 Acceptance Schema **2.0**。Benchmark 只写独立 sidecar；Content 2.2 schema、九阶段、现有 Word 模板与 WorkOrder 合同均不变。

本合同验证来源、选择、隔离声明、Review 和生产输入之间的完整链接。它不计算教学质量分数，也不能证明 Agent 实际收到的上下文符合声明。样例目录 `examples/synthetic-benchmark-closure/` 含 3 个合成来源组、Round 1/2 完整 sidecar 与授权，所有内容都标记为合成数据，不是教学质量证据。

## Production state flow

```text
freeze Intake, Source Truth and whole-course outline
→ Curator creates Cards and validates Catalog
→ Split CLI creates Split and physical Authoring A / Holdout B Packs atomically
→ Author sees only per-Lesson selected A Cards and records Authoring Selection
→ author and review all Lesson Content 2.2 through pedagogical_review
→ Reviewer sees final reviewed Lesson Content, Source Truth summary and selected B Cards
→ freeze Holdout Selection; create one Review JSON per Lesson
→ aggregate course summary and validate all provenance links
→ build immutable Benchmark Authorization
→ generate DOCX with --benchmark-mode required --benchmark-authorization <file>
→ retain render artifacts, validate manifest and complete Acceptance linkage
```

If a bounded revision is required, preserve Round 1 Content, course Review and every Lesson Review. Revise Agent-owned Lesson content, refresh Content 2.2 pedagogical review history and provenance, then run Round 2 with the same benchmark run, B Pack and Holdout Selection. Revalidate Round 1 and Round 2 before building a new authorization. Round 3 is invalid.

The generator defaults to `--benchmark-mode none` for existing 2.2 callers. `optional` allows an absent or valid authorization. `required` demands a valid authorization and is the required production mode for 2.3. `none` rejects an authorization file. Any supplied authorization is checked against the source Content bytes and semantic final-content digest; authorization bytes are copied to the output and bound by the artifact manifest.

## Catalog and source provenance

Each Card conforms to `schemas/teaching-exemplar-card.schema.json`; the Catalog applies its contract version once at the root. Cards allow only enumerated source, scope, qualification, and abstract-pattern fields. Raw source text, arbitrary fields and over-size Cards are rejected. Each Card is limited to 12 KiB of canonical UTF-8 JSON. Retrieval and Catalog creation timestamps must include a timezone.

`source_identity_sha256` hashes canonical normalized source identity fields. `catalog_fingerprint` hashes the Exemplar Contract version, qualification-policy version, normalized course context, and all Cards sorted by `exemplar_id`; `created_at` is excluded. A source identity or normalized canonical URL cannot map to multiple `group_id` values. Public sources must pass URL safety checks; private user-provided material must be labeled private and cannot masquerade as a public URL. Do not invent missing source fields or retrieve real source Cards as part of synthetic examples.

Qualification is structural and explicit. Only `QUALIFIED` Cards with eligible A/B authority enter Split. Tier C, discovery-only sources, and `CONDITIONAL`, `DISCOVERY_ONLY`, or `REJECTED` Cards remain out of both Packs. A qualified Card needs at least one non-empty abstract teaching-pattern field and one `do_not_copy` entry. These checks do not judge source relevance or teaching quality.

## Stable group split and physical packs

The Split partitions whole `group_id` clusters, including editions, sessions, mirrors, reproductions, and direct derivatives. A group's side is derived from the split-policy version, canonical course-context digest, and group ID. It does not depend on Catalog fingerprint, mutable prose, retrieval time, or insertion of an unrelated group. Context, policy, or group identity changes can alter side assignment. All side memberships and Split fingerprints are revalidated.

Availability is calculated separately for Authoring and Holdout: zero groups is `UNAVAILABLE`, one is `PARTIAL`, and two or more is `AVAILABLE`. Benchmark availability follows Holdout availability. Do not add unrelated exemplars to raise availability. Run `exemplar_split.py` once to create Split plus both Pack files; callers cannot hand-filter Catalog into Packs. The operation stages and atomically replaces all three outputs, restoring all originals if a replacement fails.

The complete Catalog and Split are Curator/orchestrator provenance. Runtime agent context contains only the Cards selected for the current Lesson. Author receives A selections only; Reviewer receives B selections only. Full Packs remain available to validators and the orchestrator for membership and hash verification, not as an agent prompt payload.

## Per-Lesson selections and Review shards

Authoring and Holdout selections are separate files and cannot be combined. Authoring Selection must cover every outline Lesson and bind the pre-existing `authoring_provenance.source_snapshot.whole_course_outline_sha256`. Holdout Selection must cover every Lesson and bind exact Round 1 Content JSON bytes. Each Lesson row is `SELECTED`, `NO_RELEVANT_EXEMPLAR`, or `UNAVAILABLE`, with matching IDs and a rationale. Authoring allows at most five Cards; Holdout allows at most four. Targets are guidance, not quotas.

Write each Lesson's assessment to its own `lesson_id.json` using `schemas/benchmark-lesson-review.schema.json`. The course summary in `schemas/benchmark-review.schema.json` holds the per-Lesson Review file hashes and deterministic totals, not every dimension's prose. It must exactly cover the Content Lesson IDs and match each shard's run ID, round, content hash, selection, and IDs.

Each reviewed Lesson has the fixed 15 dimensions. `evidence_basis` is one of `SOURCE_TRUTH`, `HOLDOUT_EXEMPLAR`, `SOURCE_TRUTH_AND_HOLDOUT`, or `LESSON_INTERNAL`. Source Truth alignment must use Source Truth evidence and cannot cite an exemplar; the other dimensions cannot use Source Truth alone. A Holdout citation must be both in Pack B and selected for that Lesson. Evidence text fields are limited to 600 characters. `NOT_APPLICABLE` is limited to `authentic_vocational_context` and `differentiation_scaffold`, with an explanation and no exemplar citation. `INSUFFICIENT_EVIDENCE` requires an explanation, the current evidence, a gap and a recommended direction, and it forces human review.

Decision rules are gates over explicit evidence states, not scores. Round 1 major GAP requests revision; Round 2 major GAP requires human review. Minor/advisory findings do not become a score. If the B Pack is non-empty but every Lesson says `NO_RELEVANT_EXEMPLAR`, report a partial benchmark requiring human explanation, not `UNAVAILABLE`. `separate_contexts` attests no A Card or author reasoning was visible and that only B exemplars were used. `single_context` must state that A and author reasoning were visible, `holdout_only=false`, and is downgraded to partial. Attestations are validated but cannot prove actual prompt isolation.

## Round 2 semantic revision

Round 2 requires the original Content JSON, summary Review and per-Lesson Review shards. Validation reruns the complete Round 1 chain with the same Catalog, Split, Packs and Holdout Selection, then binds Round 2 to the same `benchmark_run_id` and frozen B inputs. Round 2 Content must differ by exact byte hash and by the semantic digest of Agent-owned lesson content. Formatting-only or JSON key-order changes are not revision evidence. A substantive change must pass Content Contract 2.2 validation and update the relevant `pedagogical_review.review_history`, `draft_content`, `revised_content`, decision and `authoring_provenance` digests. A prior review status alone cannot establish a valid revision.

## Authorization, generation and Acceptance

`build_benchmark_authorization.py` accepts only a full valid chain: Content 2.2, Catalog, Split, A and B Packs, both Selections, course Review, all per-Lesson Reviews and (for Round 2) all Round 1 snapshots. It writes a content-addressed `benchmark-authorization.json` containing source-byte and semantic digests, package and selection fingerprints, Review hash, run/round, status, decision, context mode, version and creation time. Its fingerprint covers all authorization fields except itself.

The production command includes:

```powershell
python scripts/generate_lesson_plans.py `
  --tasks-json lesson-content.json `
  --benchmark-mode required `
  --benchmark-authorization benchmark-authorization.json `
  --output-dir output `
  --render
```

The artifact manifest records the source label and digest, local-only source-path diagnostic policy, capability mode, authorization hash, and matching benchmark provenance. The generator re-reads and validates the authorization sidecar when checking the manifest. `validate_output.py --render` is diagnostic only; production requires the generator's retained DOCX/PDF artifacts, successful SHA/page checks, output QA and transaction verification. `production_pass` means the artifact production chain passed, not that the Benchmark or human teaching review passed.

Acceptance Schema 2.0 takes `--benchmark-review`, `--benchmark-catalog`, `--benchmark-split`, `--benchmark-authoring-pack`, `--benchmark-authoring-selection`, `--benchmark-holdout-pack`, `--benchmark-holdout-selection`, and `--benchmark-lesson-reviews-dir`. Round 2 additionally takes the Round 1 course Review, Lesson Content and Lesson Review directory. All inputs and report destinations are checked for path alias/overlap before writing. Missing linkage fails closed. Benchmark does not automatically turn Acceptance into `PASSED`; teacher, visual, teaching-design and human failure decisions remain with their existing owners.

## Synthetic closure bundle and local validators

`examples/synthetic-benchmark-closure/` is a closed, synthetic example with three qualified groups, frozen A/B inputs, three per-Lesson Review shards in each round, two full authorization files and an explicitly revised Content 2.2 Round 2 payload. `SYNTHETIC-README.md` states the evidence limits and gives the validation command. The example is not a teaching-quality claim and is not a real-source benchmark.

Run the end-to-end tests on Windows and macOS with:

```powershell
python .github/scripts/run_test_shards.py --suite lesson-benchmark --verbose
```

The tests cover real rendered synthetic outputs, full A/B Acceptance linkage, Round 2 Content 2.2 review history, tamper and path-alias rejection, the checked-in canonical bundle and the 20/32 Lesson Review shard sizes. Authorization outputs created during the canonical-bundle test go to a temporary directory.
