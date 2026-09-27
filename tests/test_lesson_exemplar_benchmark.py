from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "教案生成器" / "lesson-plan-docx-generator"
SCRIPTS = LESSON / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from exemplar_contract import (  # noqa: E402
    catalog_fingerprint,
    context_size_report,
    holdout_selection_sha256,
    source_identity_sha256,
    validate_catalog_payload,
    validate_selection_payload,
)
from exemplar_split import build_split, expected_split, validate_split_payload  # noqa: E402
from validate_benchmark_review import (  # noqa: E402
    DIMENSION_IDS,
    review_summary_for,
    validate_benchmark_review_payload,
)
from tests.test_lesson_content_v22 import DB_SPECS, lesson_generator, make_v22_payload, run_script  # noqa: E402
from tests.test_lesson_skill_hardening import lesson_acceptance  # noqa: E402


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(payload)
    return payload


def make_card(
    index: int,
    *,
    group_id: str | None = None,
    authority_tier: str = "A",
    visibility: str = "public",
    status: str = "QUALIFIED",
    source_type: str = "discovery_source",
) -> dict:
    card = {
        "exemplar_id": f"EX-{index:02d}",
        "group_id": group_id or f"GR-{index:02d}",
        "source": {
            "title": f"SYNTHETIC TEST CARD {index}",
            "institution": "synthetic_fixture",
            "author_or_team": "test fixture only",
            "canonical_url": f"https://example.invalid/synthetic/{index}",
            "source_type": source_type,
            "authority_tier": authority_tier,
            "recognition": "synthetic benchmark evidence only",
            "retrieved_at": "2026-09-27T00:00:00Z",
            "visibility": visibility,
            "source_identity_sha256": "0" * 64,
        },
        "scope": {
            "education_level": "synthetic test fixture",
            "vocational_level": "synthetic test fixture",
            "domain": "synthetic test fixture",
            "course": "synthetic test fixture",
            "topic": "synthetic test fixture",
            "learner_profile": "synthetic test fixture",
            "duration_minutes": 45,
            "teaching_context": "synthetic test fixture only",
        },
        "qualification": {
            "status": status,
            "rationale": "Synthetic fixture for deterministic contract testing; no real teaching-quality claim.",
        },
        "design_patterns": ["Synthetic abstract design pattern."],
        "difficulty_breakthrough_patterns": [],
        "student_activity_patterns": [],
        "learning_evidence_patterns": [],
        "assessment_patterns": [],
        "differentiation_patterns": [],
        "reflection_patterns": [],
        "transferable_principles": [],
        "non_transferable_context": [],
        "do_not_copy": ["Synthetic test data; not source content."],
    }
    card["source"]["source_identity_sha256"] = source_identity_sha256(card)
    return card


def make_catalog(
    group_count: int,
    *,
    cards_per_group: int = 1,
    nonqualified_count: int = 0,
) -> dict:
    cards = [
        make_card(group_index * cards_per_group + card_index + 1, group_id=f"GR-{group_index:02d}")
        for group_index in range(group_count)
        for card_index in range(cards_per_group)
    ]
    for index in range(nonqualified_count):
        cards.append(
            make_card(
                group_count * cards_per_group + index + 1,
                group_id=f"NQ-{index:02d}",
                authority_tier="C",
                status="DISCOVERY_ONLY",
            )
        )
    return {
        "exemplar_contract_version": "1.0",
        "catalog_id": "synthetic-catalog",
        "created_at": "2026-09-27T00:00:00Z",
        "course_context": {
            "course_name": "Synthetic test course",
            "major": "Synthetic test major",
            "audience": "Synthetic test audience",
        },
        "catalog_fingerprint": catalog_fingerprint(cards),
        "exemplars": cards,
    }


def make_selection(catalog: dict, split: dict, source_digest: str, lesson_ids: list[str]) -> dict:
    authoring_ids = split["authoring_exemplar_ids"]
    holdout_ids = split["holdout_exemplar_ids"]
    lessons = []
    for lesson_id in lesson_ids:
        authoring_status = "SELECTED" if authoring_ids else "UNAVAILABLE"
        holdout_status = "SELECTED" if holdout_ids else "UNAVAILABLE"
        lessons.append(
            {
                "lesson_id": lesson_id,
                "authoring": {
                    "status": authoring_status,
                    "exemplar_ids": authoring_ids[:1],
                    "rationale": "Synthetic fixture selection; not a semantic relevance judgment.",
                },
                "holdout": {
                    "status": holdout_status,
                    "exemplar_ids": holdout_ids[:1],
                    "rationale": "Synthetic fixture selection; not a semantic relevance judgment.",
                },
            }
        )
    return {
        "selection_contract_version": "1.0",
        "catalog_id": catalog["catalog_id"],
        "split_id": split["split_id"],
        "source_lesson_content_sha256": source_digest,
        "lessons": lessons,
    }


def make_review(
    catalog: dict,
    split: dict,
    selection: dict,
    source_digest: str,
    *,
    review_round: int = 1,
    gap: tuple[str, str] | None = None,
    prior_review: dict | None = None,
    prior_review_sha256: str | None = None,
) -> dict:
    lessons = []
    for selected_lesson in selection["lessons"]:
        holdout = selected_lesson["holdout"]
        dimensions = []
        if holdout["exemplar_ids"]:
            for index, dimension_id in enumerate(DIMENSION_IDS):
                is_gap = gap is not None and gap[0] == selected_lesson["lesson_id"] and gap[1] == dimension_id
                dimensions.append(
                    {
                        "dimension": dimension_id,
                        "status": "GAP" if is_gap else "MEETS",
                        "severity": "major" if is_gap else "none",
                        "current_evidence": "Synthetic benchmark evidence only; controlled test fixture.",
                        "benchmark_pattern": "Synthetic abstract pattern; no real teaching quality is asserted.",
                        "gap": "Synthetic gap fixture." if is_gap else "",
                        "recommended_direction": "Synthetic direction fixture." if is_gap else "",
                        "holdout_exemplar_ids": list(holdout["exemplar_ids"]),
                    }
                )
        lessons.append(
            {
                "lesson_id": selected_lesson["lesson_id"],
                "holdout_selection": {
                    "status": holdout["status"],
                    "exemplar_ids": list(holdout["exemplar_ids"]),
                },
                "dimensions": dimensions,
            }
        )
    summary = review_summary_for(
        lessons,
        review_round=review_round,
        benchmark_availability=split["benchmark_availability"],
    )
    review = {
        "benchmark_contract_version": "1.0",
        "benchmark_run_id": f"synthetic-review-round-{review_round}",
        "catalog_id": catalog["catalog_id"],
        "split_id": split["split_id"],
        "split_fingerprint": split["split_fingerprint"],
        "benchmark_availability": split["benchmark_availability"],
        "source_lesson_content_sha256": source_digest,
        "holdout_selection_sha256": holdout_selection_sha256(selection),
        "rubric_version": "lesson-teaching-benchmark-v1",
        "review_round": review_round,
        "status": summary["status"],
        "isolation": {
            "authoring_exemplars_visible": False,
            "author_reasoning_visible": False,
            "holdout_only": True,
        },
        "lessons": lessons,
        "course_summary": {key: summary[key] for key in (
            "major_gap_count", "minor_gap_count", "insufficient_evidence_count",
            "lessons_reviewed", "lessons_without_holdout", "decision",
        )},
    }
    if review_round == 2:
        assert prior_review is not None
        review["prior_review_sha256"] = prior_review_sha256 or "b" * 64
        review["prior_source_lesson_content_sha256"] = prior_review["source_lesson_content_sha256"]
    return review


class ExemplarCatalogTests(unittest.TestCase):
    def test_valid_catalog_and_canonical_identity(self) -> None:
        card = make_card(1)
        card["source"]["title"] = "  Ａ　 test\tcase  "
        card["source"]["source_identity_sha256"] = source_identity_sha256(card)
        catalog = make_catalog(0)
        catalog["exemplars"] = [card]
        catalog["catalog_fingerprint"] = catalog_fingerprint([card])
        self.assertEqual(validate_catalog_payload(catalog), [])

    def test_duplicate_exemplar_id_and_wrong_source_identity_fail(self) -> None:
        first = make_card(1)
        second = make_card(2, group_id="GR-OTHER")
        second["exemplar_id"] = first["exemplar_id"]
        catalog = make_catalog(0)
        catalog["exemplars"] = [first, second]
        catalog["catalog_fingerprint"] = catalog_fingerprint([first, second])
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("duplicate exemplar_id" in error for error in errors), errors)

        first["source"]["source_identity_sha256"] = "0" * 64
        catalog["catalog_fingerprint"] = catalog_fingerprint([first, second])
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("source_identity_sha256" in error for error in errors), errors)

    def test_tier_c_cannot_be_qualified_and_private_cannot_be_public(self) -> None:
        tier_c = make_card(1, authority_tier="C", status="QUALIFIED")
        private_public = make_card(2, authority_tier="PRIVATE", visibility="public")
        catalog = make_catalog(0)
        catalog["exemplars"] = [tier_c, private_public]
        catalog["catalog_fingerprint"] = catalog_fingerprint(catalog["exemplars"])
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("authority_tier C" in error and "QUALIFIED" in error for error in errors), errors)
        self.assertTrue(any("PRIVATE requires visibility private_session" in error for error in errors), errors)

    def test_raw_text_and_arbitrary_card_fields_are_rejected(self) -> None:
        card = make_card(1)
        card["raw_text"] = "not allowed"
        catalog = make_catalog(0)
        catalog["exemplars"] = [card]
        catalog["catalog_fingerprint"] = catalog_fingerprint([card])
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("Additional properties are not allowed" in error for error in errors), errors)

    def test_catalog_fingerprint_mismatch_fails(self) -> None:
        catalog = make_catalog(1)
        catalog["catalog_fingerprint"] = "0" * 64
        self.assertTrue(any("catalog_fingerprint" in error for error in validate_catalog_payload(catalog)))


class ExemplarSplitTests(unittest.TestCase):
    def test_zero_one_two_three_and_six_group_splits(self) -> None:
        expected = {
            0: ("UNAVAILABLE", 0, 0),
            1: ("UNAVAILABLE", 1, 0),
            2: ("PARTIAL", 1, 1),
            3: ("AVAILABLE", 1, 2),
            6: ("AVAILABLE", 2, 4),
        }
        for count, (availability, authoring_count, holdout_count) in expected.items():
            with self.subTest(groups=count):
                catalog = make_catalog(count)
                split = build_split(catalog)
                self.assertEqual(split["benchmark_availability"], availability)
                self.assertEqual(len(split["authoring_group_ids"]), authoring_count)
                self.assertEqual(len(split["holdout_group_ids"]), holdout_count)
                self.assertEqual(validate_split_payload(split, catalog), [])

    def test_assignment_is_repeatable_and_follows_a_b_b_pattern(self) -> None:
        catalog = make_catalog(6)
        first = expected_split(catalog, created_at="2026-09-27T00:00:00Z")
        second = expected_split(catalog, created_at="2026-09-28T00:00:00Z")
        self.assertEqual(first["split_fingerprint"], second["split_fingerprint"])
        self.assertEqual(first["split_id"], second["split_id"])
        ranked = sorted(
            {card["group_id"] for card in catalog["exemplars"]},
            key=lambda group_id: hashlib.sha256(
                f"{catalog['catalog_fingerprint']}\n{group_id}".encode("utf-8")
            ).hexdigest(),
        )
        pattern = ["A" if group in first["authoring_group_ids"] else "B" for group in ranked]
        self.assertEqual(pattern, ["A", "B", "B", "A", "B", "B"])

    def test_group_leakage_nonqualified_membership_and_catalog_mismatch_fail(self) -> None:
        catalog = make_catalog(3, nonqualified_count=1)
        split = build_split(catalog)
        leaking = copy.deepcopy(split)
        leaking["holdout_group_ids"].append(leaking["authoring_group_ids"][0])
        errors = validate_split_payload(leaking, catalog)
        self.assertTrue(any("overlap" in error or "deterministic split" in error for error in errors), errors)

        nonqualified = copy.deepcopy(split)
        nonqualified["holdout_exemplar_ids"].append("EX-04")
        errors = validate_split_payload(nonqualified, catalog)
        self.assertTrue(any("deterministic split" in error or "non-QUALIFIED" in error for error in errors), errors)

        stale_catalog = copy.deepcopy(catalog)
        stale_catalog["catalog_fingerprint"] = "f" * 64
        self.assertTrue(validate_split_payload(split, stale_catalog))


class ExemplarSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = make_catalog(6, cards_per_group=3)
        self.split = build_split(self.catalog)
        self.selection = make_selection(self.catalog, self.split, "a" * 64, ["L01"])

    def test_valid_authoring_and_holdout_selection_and_size_report(self) -> None:
        self.assertEqual(validate_selection_payload(self.selection, self.catalog, self.split), [])
        report = context_size_report(self.catalog, self.selection)
        self.assertGreater(report["catalog_total_bytes"], 0)
        self.assertGreater(report["selected_authoring_card_bytes_per_lesson"]["L01"], 0)
        self.assertGreater(report["selected_holdout_card_bytes_per_lesson"]["L01"], 0)

    def test_a_b_unknown_and_max_item_leakage_fail(self) -> None:
        authoring_as_holdout = copy.deepcopy(self.selection)
        authoring_as_holdout["lessons"][0]["holdout"]["exemplar_ids"] = self.split["authoring_exemplar_ids"][:1]
        self.assertTrue(validate_selection_payload(authoring_as_holdout, self.catalog, self.split))

        holdout_as_authoring = copy.deepcopy(self.selection)
        holdout_as_authoring["lessons"][0]["authoring"]["exemplar_ids"] = self.split["holdout_exemplar_ids"][:1]
        self.assertTrue(validate_selection_payload(holdout_as_authoring, self.catalog, self.split))

        unknown = copy.deepcopy(self.selection)
        unknown["lessons"][0]["authoring"]["exemplar_ids"] = ["NOT-IN-CATALOG"]
        self.assertTrue(validate_selection_payload(unknown, self.catalog, self.split))

        too_many = copy.deepcopy(self.selection)
        too_many["lessons"][0]["authoring"]["exemplar_ids"] = self.split["authoring_exemplar_ids"][:6]
        self.assertTrue(validate_selection_payload(too_many, self.catalog, self.split))
        too_many["lessons"][0]["authoring"]["exemplar_ids"] = self.split["authoring_exemplar_ids"][:1]
        too_many["lessons"][0]["holdout"]["exemplar_ids"] = self.split["holdout_exemplar_ids"][:5]
        self.assertTrue(validate_selection_payload(too_many, self.catalog, self.split))

    def test_status_and_empty_id_combinations_fail(self) -> None:
        no_relevant_with_ids = copy.deepcopy(self.selection)
        no_relevant_with_ids["lessons"][0]["authoring"]["status"] = "NO_RELEVANT_EXEMPLAR"
        self.assertTrue(validate_selection_payload(no_relevant_with_ids, self.catalog, self.split))

        selected_empty = copy.deepcopy(self.selection)
        selected_empty["lessons"][0]["authoring"]["exemplar_ids"] = []
        self.assertTrue(validate_selection_payload(selected_empty, self.catalog, self.split))


class BenchmarkReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = make_catalog(5)
        self.split = build_split(self.catalog)
        self.content_a = b'{"content_contract_version":"2.2","lessons":["synthetic"]}\n'
        self.digest_a = _sha256_bytes(self.content_a)
        self.selection = make_selection(self.catalog, self.split, self.digest_a, ["L01", "L02", "L03"])
        self.review = make_review(self.catalog, self.split, self.selection, self.digest_a)

    def validate(self, review: dict) -> list[str]:
        return validate_benchmark_review_payload(
            review,
            catalog=self.catalog,
            split=self.split,
            selection=self.selection,
            lesson_content_sha256=self.digest_a,
        )

    def test_valid_round_one_and_round_two_changed_digest(self) -> None:
        self.assertEqual(self.validate(self.review), [])
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-rounds-") as temp_name:
            folder = Path(temp_name)
            round_one = make_review(
                self.catalog,
                self.split,
                self.selection,
                self.digest_a,
                gap=("L01", DIMENSION_IDS[0]),
            )
            round_one_path = folder / "round-1.json"
            round_one_bytes = _write_json(round_one_path, round_one)
            content_b = self.content_a + b"revised\n"
            digest_b = _sha256_bytes(content_b)
            round_two = make_review(
                self.catalog,
                self.split,
                self.selection,
                digest_b,
                review_round=2,
                prior_review=round_one,
                prior_review_sha256=_sha256_bytes(round_one_bytes),
            )
            errors = validate_benchmark_review_payload(
                round_two,
                catalog=self.catalog,
                split=self.split,
                selection=self.selection,
                lesson_content_sha256=digest_b,
                previous_review=round_one,
                previous_review_sha256=_sha256_bytes(round_one_bytes),
            )
            self.assertEqual(errors, [])

    def test_round_three_isolation_dimensions_and_forbidden_fields_fail(self) -> None:
        round_three = copy.deepcopy(self.review)
        round_three["review_round"] = 3
        self.assertTrue(validate_benchmark_review_payload(round_three))

        isolation = copy.deepcopy(self.review)
        isolation["isolation"]["authoring_exemplars_visible"] = True
        self.assertTrue(any("isolation" in error for error in validate_benchmark_review_payload(isolation)))

        invalid_dimension = copy.deepcopy(self.review)
        invalid_dimension["lessons"][0]["dimensions"][0]["dimension"] = "made_up_dimension"
        self.assertTrue(validate_benchmark_review_payload(invalid_dimension))

        missing_dimension = copy.deepcopy(self.review)
        missing_dimension["lessons"][0]["dimensions"].pop()
        self.assertTrue(any("all 15 dimensions" in error for error in validate_benchmark_review_payload(missing_dimension)))

        with_score = copy.deepcopy(self.review)
        with_score["course_summary"]["score"] = 95
        self.assertTrue(validate_benchmark_review_payload(with_score))
        with_similarity = copy.deepcopy(self.review)
        with_similarity["lessons"][0]["dimensions"][0]["similarity"] = 0.7
        self.assertTrue(validate_benchmark_review_payload(with_similarity))

    def test_gap_decisions_holdout_membership_and_selection_digest_fail_closed(self) -> None:
        major = make_review(
            self.catalog,
            self.split,
            self.selection,
            self.digest_a,
            gap=("L01", DIMENSION_IDS[0]),
        )
        major["course_summary"]["decision"] = "NO_REVISION_REQUIRED"
        self.assertTrue(any("course_summary.decision" in error for error in self.validate(major)))

        round_one_major = make_review(
            self.catalog,
            self.split,
            self.selection,
            self.digest_a,
            gap=("L01", DIMENSION_IDS[0]),
        )
        round_one_path_bytes = (json.dumps(round_one_major, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        digest_b = _sha256_bytes(self.content_a + b"round two")
        round_two_major = make_review(
            self.catalog,
            self.split,
            self.selection,
            digest_b,
            review_round=2,
            gap=("L01", DIMENSION_IDS[0]),
            prior_review=round_one_major,
            prior_review_sha256=_sha256_bytes(round_one_path_bytes),
        )
        round_two_major["course_summary"]["decision"] = "REVISION_REQUIRED"
        round_two_major["status"] = "BENCHMARK_GAPS_FOUND"
        errors = validate_benchmark_review_payload(
            round_two_major,
            catalog=self.catalog,
            split=self.split,
            selection=self.selection,
            lesson_content_sha256=digest_b,
            previous_review=round_one_major,
        )
        self.assertTrue(any("course_summary.decision" in error or "status does not match" in error for error in errors), errors)

        outside_b = copy.deepcopy(self.review)
        outside_b["lessons"][0]["dimensions"][0]["holdout_exemplar_ids"] = self.split["authoring_exemplar_ids"][:1]
        errors = self.validate(outside_b)
        self.assertTrue(any("outside Holdout side B" in error or "unselected Holdout" in error for error in errors), errors)

        stale_selection_hash = copy.deepcopy(self.review)
        stale_selection_hash["holdout_selection_sha256"] = "0" * 64
        self.assertTrue(any("holdout_selection_sha256" in error for error in self.validate(stale_selection_hash)))


class AcceptanceBenchmarkIntegrationTests(unittest.TestCase):
    def _review_for_acceptance(self, source: Path, *, group_count: int = 5, major_gap: bool = False) -> Path:
        catalog = make_catalog(group_count)
        split = build_split(catalog)
        selection = make_selection(
            catalog,
            split,
            _sha256_bytes(source.read_bytes()),
            ["L01", "L02", "L03"],
        )
        review = make_review(
            catalog,
            split,
            selection,
            _sha256_bytes(source.read_bytes()),
            gap=("L01", DIMENSION_IDS[0]) if major_gap else None,
        )
        target = source.parent / "benchmark-review.json"
        _write_json(target, review)
        return target

    def _acceptance_fixture(self, folder: Path) -> tuple[Path, Path, Path]:
        from tests.test_lesson_skill_hardening import LessonSkillHardeningTests

        helper = LessonSkillHardeningTests()
        source, output, qa, _ = helper._acceptance_fixture(folder)
        return source, output, qa

    def test_no_benchmark_keeps_old_report_shape_and_additive_review_validates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-acceptance-") as temp_name:
            folder = Path(temp_name)
            source, output, qa = self._acceptance_fixture(folder)
            old = lesson_acceptance.build_acceptance_report(
                source, output, qa, source_type="synthetic_fixture", report_dir=folder / "report-old"
            )
            self.assertNotIn("benchmark_review", old)
            self.assertEqual(old["acceptance_schema_version"], "2.0")
            self.assertEqual(lesson_acceptance.validate_report_schema(old), [])

            review_path = self._review_for_acceptance(source)
            updated = lesson_acceptance.build_acceptance_report(
                source,
                output,
                qa,
                source_type="synthetic_fixture",
                report_dir=folder / "report-new",
                benchmark_review_path=review_path,
            )
            self.assertIn("benchmark_review", updated)
            self.assertEqual(updated["benchmark_review"]["decision"], "NO_REVISION_REQUIRED")
            self.assertEqual(updated["acceptance_schema_version"], "2.0")
            self.assertEqual(lesson_acceptance.validate_report_schema(updated), [])
            from jsonschema import Draft202012Validator

            schema = json.loads((ROOT / "docs" / "lesson-acceptance-report.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(updated)), [])

    def test_major_gap_caps_would_be_passed_status_and_unavailable_is_not_structural_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-acceptance-gates-") as temp_name:
            folder = Path(temp_name)
            source, output, qa = self._acceptance_fixture(folder)
            major_review = self._review_for_acceptance(source, major_gap=True)
            with patch.object(lesson_acceptance, "_final_status", return_value="PASSED"):
                report = lesson_acceptance.build_acceptance_report(
                    source,
                    output,
                    qa,
                    source_type="synthetic_fixture",
                    report_dir=folder / "report-major",
                    benchmark_review_path=major_review,
                )
            self.assertEqual(report["benchmark_review"]["decision"], "REVISION_REQUIRED")
            self.assertEqual(report["final_status"], "PENDING_MANUAL_REVIEW")

            unavailable = self._review_for_acceptance(source, group_count=0)
            report = lesson_acceptance.build_acceptance_report(
                source,
                output,
                qa,
                source_type="synthetic_fixture",
                report_dir=folder / "report-unavailable",
                benchmark_review_path=unavailable,
            )
            self.assertEqual(report["benchmark_review"]["decision"], "BENCHMARK_UNAVAILABLE")
            self.assertEqual(report["structural_hard_gates"]["status"], "PASS")
            self.assertNotEqual(report["final_status"], "FAILED")

    def test_invalid_supplied_review_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-acceptance-invalid-") as temp_name:
            folder = Path(temp_name)
            source, output, qa = self._acceptance_fixture(folder)
            review_path = self._review_for_acceptance(source)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            review["holdout_selection_sha256"] = "0" * 64
            _write_json(review_path, review)
            with self.assertRaisesRegex(ValueError, "holdout_selection_sha256"):
                lesson_acceptance.build_acceptance_report(
                    source,
                    output,
                    qa,
                    source_type="synthetic_fixture",
                    report_dir=folder / "report-invalid",
                    benchmark_review_path=review_path,
                )


class TeachingExemplarBenchmarkE2ETests(unittest.TestCase):
    def test_three_lesson_render_acceptance_e2e_with_five_synthetic_groups(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-23-exemplar-e2e-") as temp_name:
            folder = Path(temp_name)
            payload = make_v22_payload(
                course="Synthetic Exemplar E2E",
                major="Synthetic test major",
                audience="Synthetic test audience",
                theory_hours=6,
                lesson_count=3,
                specs=DB_SPECS,
            )
            source = folder / "lesson-content-v2.2.json"
            _write_json(source, payload)
            output = folder / "production"
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json", str(source),
                "--output-dir", str(output),
                "--render",
            )
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(qa["content_contract_version"], "2.2")
            self.assertEqual(qa["status"], "passed")
            self.assertEqual(qa["production_status"], "production_pass")
            manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(lesson_generator._verify_artifact_manifest(output, manifest, source), "production_pass")
            self.assertEqual(len(manifest["artifacts"]), 3)
            self.assertTrue(all(item["actual_pdf_page_count"] > 0 for item in manifest["artifacts"]))

            catalog = make_catalog(5)
            split = build_split(catalog)
            self.assertEqual(split["benchmark_availability"], "AVAILABLE")
            ranked_groups = sorted(
                {card["group_id"] for card in catalog["exemplars"]},
                key=lambda group_id: hashlib.sha256(
                    f"{catalog['catalog_fingerprint']}\n{group_id}".encode("utf-8")
                ).hexdigest(),
            )
            pattern = ["A" if group in split["authoring_group_ids"] else "B" for group in ranked_groups]
            self.assertEqual(pattern, ["A", "B", "B", "A", "B"])
            catalog_path = folder / "exemplar-catalog.json"
            split_path = folder / "exemplar-split.json"
            selection_path = folder / "exemplar-selection.json"
            review_path = folder / "benchmark-review.json"
            _write_json(catalog_path, catalog)
            _write_json(split_path, split)
            selection = make_selection(catalog, split, _sha256_bytes(source.read_bytes()), ["L01", "L02", "L03"])
            _write_json(selection_path, selection)

            selection_check = run_script(
                SCRIPTS / "exemplar_contract.py",
                "selection",
                "--catalog", str(catalog_path),
                "--split", str(split_path),
                "--selection", str(selection_path),
            )
            self.assertEqual(selection_check.returncode, 0, selection_check.stderr + selection_check.stdout)
            size_report = json.loads(selection_check.stdout)
            self.assertGreater(size_report["catalog_total_bytes"], 0)
            self.assertEqual(set(size_report["selected_authoring_card_bytes_per_lesson"]), {"L01", "L02", "L03"})
            self.assertEqual(set(size_report["selected_holdout_card_bytes_per_lesson"]), {"L01", "L02", "L03"})

            review = make_review(catalog, split, selection, _sha256_bytes(source.read_bytes()))
            _write_json(review_path, review)
            review_check = run_script(
                SCRIPTS / "validate_benchmark_review.py",
                "--review", str(review_path),
                "--catalog", str(catalog_path),
                "--split", str(split_path),
                "--selection", str(selection_path),
                "--lesson-content", str(source),
            )
            self.assertEqual(review_check.returncode, 0, review_check.stderr + review_check.stdout)
            self.assertIn("Synthetic abstract pattern", review["lessons"][0]["dimensions"][0]["benchmark_pattern"])

            report_dir = folder / "acceptance"
            acceptance = run_script(
                ROOT / "tests" / "lesson_acceptance.py",
                "--input-json", str(source),
                "--output-dir", str(output),
                "--qa-report", str(output / "qa-report.json"),
                "--report-dir", str(report_dir),
                "--source-type", "synthetic_fixture",
                "--benchmark-review", str(review_path),
            )
            self.assertEqual(acceptance.returncode, 0, acceptance.stderr + acceptance.stdout)
            report = json.loads((report_dir / "lesson-acceptance-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["acceptance_schema_version"], "2.0")
            self.assertEqual(report["benchmark_review"]["decision"], "NO_REVISION_REQUIRED")
            self.assertEqual(report["structural_hard_gates"]["status"], "PASS")
            self.assertEqual(report["final_status"], "PENDING_MANUAL_REVIEW")
            self.assertEqual(_sha256_bytes(source.read_bytes()), report["benchmark_review"]["source_sha256"])


if __name__ == "__main__":
    unittest.main()
