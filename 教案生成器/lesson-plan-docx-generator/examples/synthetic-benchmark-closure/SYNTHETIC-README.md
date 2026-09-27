# Synthetic Benchmark Closure Example

> SYNTHETIC; NON-TEACHING-QUALITY-EVIDENCE. Every source card, course detail, review, and revision in this bundle is fabricated test data using `example.invalid`. It demonstrates contract and provenance plumbing only. It is not a real source catalog, pilot, or teaching-quality result. Never use its Authorization to generate production DOCX files.

The bundle contains exactly three qualified synthetic source groups. Round 1 and Round 2 share the same Catalog, Split, A/B Packs, Authoring Selection, Holdout Selection, and `synthetic-benchmark-run`. Round 1 contains a synthetic major gap and has no final production Authorization; the builder must reject `REVISION_REQUIRED`. Round 2 changes Agent-owned Lesson content and refreshes Content 2.2 `pedagogical_review` history and `authoring_provenance`. Each round has one Review JSON per Lesson and a course summary. Only Round 2 has an Authorization because its status is eligible for a technical artifact.

Both rounds pass `validate_benchmark_review.py`; only Round 2 passes `build_benchmark_authorization.py`. Both Selections pass `exemplar_contract.py`. Content validation used the explicit synthetic fixture allowance. The examples are not teaching evidence. The root `examples/exemplar-catalog.example.json` and `examples/benchmark-review.example.json` are convenience copies from this bundle.

From the repository root, rerun the full bundle validation with:

```powershell
python .github/scripts/run_test_shards.py --suite lesson-benchmark --verbose
```

The canonical-example test reads these files without modifying them, revalidates both rounds and both selections, and writes newly built Authorization outputs only under a temporary directory.
