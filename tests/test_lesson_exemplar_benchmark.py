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
    build_exemplar_pack,
    canonical_json_bytes,
    catalog_fingerprint,
    holdout_selection_sha256,
    pack_fingerprint,
    source_identity_sha256,
    QUALIFICATION_POLICY_VERSION,
    MAX_CARD_BYTES,
    validate_authoring_selection_payload,
    validate_catalog_payload,
    validate_card_payload,
    validate_holdout_selection_payload,
    validate_pack_payload,
)
import exemplar_split as exemplar_split_module  # noqa: E402
from exemplar_split import build_split, expected_split, validate_split_payload  # noqa: E402
from validate_benchmark_review import (  # noqa: E402
    DIMENSION_IDS,
    review_summary_for,
    build_course_review_payload,
    validate_benchmark_review_file,
    validate_benchmark_review_payload,
)
from tests.test_lesson_content_v22 import (  # noqa: E402
    DB_SPECS,
    lesson_generator,
    lesson_package_common,
    make_v22_payload,
    run_script,
)
from tests.test_lesson_skill_hardening import lesson_acceptance  # noqa: E402


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> bytes:
    payload = _json_bytes(value)
    path.write_bytes(payload)
    return payload


def make_card(
    index: int,
    *,
    group_id: str | None = None,
    authority_tier: str = "A",
    visibility: str = "public",
    status: str = "QUALIFIED",
    source_type: str = "official_platform",
) -> dict:
    card = {
        "exemplar_id": f"EX-{index:02d}",
        "group_id": group_id or f"GR-{index:02d}",
        "source": {
            "title": f"SYNTHETIC TEST CARD {index}",
            "institution": "synthetic_fixture",
            "author_or_team": "test fixture only",
            "canonical_url": f"https://example.invalid/synthetic/{index}",
            "provided_source_id": None,
            "source_label": None,
            "source_type": source_type,
            "authority_tier": authority_tier,
            "authority_basis": "private_user" if source_type == "private_user_provided" else "official_award",
            "recognition": "synthetic benchmark evidence only",
            "recognition_evidence": ["SYNTHETIC; NON-TEACHING-QUALITY-EVIDENCE"],
            "retrieved_at": "2026-09-27T00:00:00Z",
            "visibility": visibility,
            "source_identity_sha256": "0" * 64,
        },
        "scope": {
            "education_level": "synthetic test fixture",
            "vocational_level": "synthetic test fixture",
            "domain": "synthetic test fixture",
            "course": "synthetic test fixture",
            "scope_mode": "course_specific",
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
    course_name: str = "Synthetic test course",
    major: str = "Synthetic test major",
    audience: str = "Synthetic test audience",
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
    catalog = {
        "exemplar_contract_version": "1.0",
        "qualification_policy_version": QUALIFICATION_POLICY_VERSION,
        "catalog_id": "synthetic-catalog",
        "created_at": "2026-09-27T00:00:00Z",
        "course_context": {
            "course_name": course_name,
            "major": major,
            "audience": audience,
        },
        "catalog_fingerprint": "0" * 64,
        "exemplars": cards,
    }
    refresh_catalog_fingerprint(catalog)
    return catalog


def refresh_catalog_fingerprint(catalog: dict) -> None:
    catalog["catalog_fingerprint"] = catalog_fingerprint(
        catalog["exemplars"],
        qualification_policy_version=catalog["qualification_policy_version"],
        course_context=catalog["course_context"],
        exemplar_contract_version=catalog["exemplar_contract_version"],
    )


def make_content(
    lesson_ids: list[str],
    *,
    course_name: str = "Synthetic test course",
    major: str = "Synthetic test major",
    audience: str = "Synthetic test audience",
) -> dict:
    return {
        "content_contract_version": "2.2",
        "course_name": course_name,
        "major": major,
        "audience": audience,
        "authoring_provenance": {
            "source_snapshot": {"whole_course_outline_sha256": "c" * 64},
            "final_content_sha256": "0" * 64,
        },
        "outline": [{"lesson_id": lesson_id} for lesson_id in lesson_ids],
        "lessons": [{"lesson_id": lesson_id, "synthetic_fixture": True} for lesson_id in lesson_ids],
    }


def make_authoring_selection(catalog: dict, split: dict, pack: dict, content: dict) -> dict:
    ids = list(pack["exemplar_ids"][:1])
    status = "SELECTED" if ids else "UNAVAILABLE"
    return {
        "selection_contract_version": "1.0",
        "selection_role": "authoring",
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_id": split["split_id"],
        "split_fingerprint": split["split_fingerprint"],
        "pack_fingerprint": pack["pack_fingerprint"],
        "source_outline_sha256": content["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"],
        "lessons": [
            {
                "lesson_id": lesson["lesson_id"],
                "status": status,
                "exemplar_ids": list(ids),
                "rationale": "Synthetic fixture only; not a relevance judgment.",
            }
            for lesson in content["outline"]
        ],
    }


def make_holdout_selection(
    catalog: dict,
    split: dict,
    pack: dict,
    content: dict,
    source_digest: str,
    *,
    per_lesson_ids: dict[str, list[str]] | None = None,
) -> dict:
    ids = list(pack["exemplar_ids"][:1])
    lessons = []
    for lesson in content["lessons"]:
        lesson_id = lesson.get("lesson_id", lesson.get("id"))
        selected = list((per_lesson_ids or {}).get(lesson_id, ids))
        status = "SELECTED" if selected else "UNAVAILABLE"
        lessons.append(
            {
                "lesson_id": lesson_id,
                "status": status,
                "exemplar_ids": selected,
                "rationale": "Synthetic fixture only; not a relevance judgment.",
            }
        )
    return {
        "selection_contract_version": "1.0",
        "selection_role": "holdout",
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_id": split["split_id"],
        "split_fingerprint": split["split_fingerprint"],
        "pack_fingerprint": pack["pack_fingerprint"],
        "source_lesson_content_sha256": source_digest,
        "lessons": lessons,
    }


def _semantic_final_digest(content: dict) -> str:
    lessons = content.get("lessons", [])
    if all(isinstance(lesson, dict) and "progression" in lesson for lesson in lessons):
        return lesson_package_common.content_digest_rollup([
            lesson_package_common.canonical_json_sha256(lesson_package_common.lesson_agent_content(lesson))
            for lesson in lessons
        ])
    return _sha256_bytes(canonical_json_bytes(lessons))


def make_lesson_reviews(
    holdout_selection: dict,
    source_digest: str,
    *,
    review_round: int = 1,
    run_id: str = "synthetic-benchmark-run",
    gap: tuple[str, str] | None = None,
) -> list[dict]:
    reviews = []
    for selection_row in holdout_selection["lessons"]:
        lesson_id = selection_row["lesson_id"]
        dimensions = []
        if selection_row["exemplar_ids"]:
            for dimension_id in DIMENSION_IDS:
                is_gap = gap == (lesson_id, dimension_id)
                is_source_truth = dimension_id == "source_truth_alignment"
                dimensions.append({
                    "dimension": dimension_id,
                    "status": "GAP" if is_gap else "MEETS",
                    "severity": "major" if is_gap else "none",
                    "evidence_basis": "SOURCE_TRUTH" if is_source_truth else "HOLDOUT_EXEMPLAR",
                    "current_evidence": "Synthetic benchmark evidence only; controlled test fixture.",
                    "benchmark_pattern": "" if is_source_truth else "Synthetic abstract pattern; no real teaching quality is asserted.",
                    "gap": "Synthetic gap fixture." if is_gap else "",
                    "recommended_direction": "Synthetic direction fixture." if is_gap else "",
                    "insufficiency_reason": "",
                    "source_truth_evidence": ["SYNTHETIC source truth fixture"] if is_source_truth else [],
                    "holdout_exemplar_ids": [] if is_source_truth else list(selection_row["exemplar_ids"]),
                })
        reviews.append({
            "benchmark_contract_version": "1.0",
            "benchmark_run_id": run_id,
            "review_round": review_round,
            "lesson_id": lesson_id,
            "source_lesson_content_sha256": source_digest,
            "selected_holdout_exemplar_ids": list(selection_row["exemplar_ids"]),
            "dimensions": dimensions,
        })
    return reviews


def make_review(
    catalog: dict,
    split: dict,
    holdout_pack: dict,
    holdout_selection: dict,
    source_digest: str,
    *,
    review_round: int = 1,
    gap: tuple[str, str] | None = None,
    prior_review: dict | None = None,
    prior_review_sha256: str | None = None,
    lesson_content: dict | None = None,
    previous_content: dict | None = None,
    previous_content_sha256: str | None = None,
    lesson_reviews: list[dict] | None = None,
    context_mode: str = "separate_contexts",
) -> dict:
    content = lesson_content or make_content(
        [row["lesson_id"] for row in holdout_selection["lessons"]],
        course_name=catalog["course_context"]["course_name"],
        major=catalog["course_context"]["major"],
        audience=catalog["course_context"]["audience"],
    )
    content["authoring_provenance"]["final_content_sha256"] = _semantic_final_digest(content)
    rows = lesson_reviews or make_lesson_reviews(
        holdout_selection, source_digest, review_round=review_round,
        gap=gap,
    )
    hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in rows}
    isolation = (
        {"authoring_exemplars_visible": False, "author_reasoning_visible": False, "holdout_only": True}
        if context_mode == "separate_contexts"
        else {"authoring_exemplars_visible": True, "author_reasoning_visible": True, "holdout_only": False}
    )
    review, errors = build_course_review_payload(
        benchmark_run_id="synthetic-benchmark-run",
        review_round=review_round,
        context_mode=context_mode,
        isolation=isolation,
        catalog=catalog,
        split=split,
        holdout_pack=holdout_pack,
        holdout_selection=holdout_selection,
        lesson_content=content,
        lesson_content_sha256=source_digest,
        lesson_reviews=rows,
        lesson_review_sha256=hashes,
        previous_review=prior_review,
        previous_review_sha256=prior_review_sha256,
        previous_content=previous_content,
        previous_content_sha256=previous_content_sha256,
    )
    if errors:
        raise AssertionError(errors)
    return review


def validate_review_fixture(
    review: dict,
    catalog: dict,
    split: dict,
    holdout_pack: dict,
    holdout_selection: dict,
    content: dict,
    content_digest: str,
    *,
    selection_source_digest: str | None = None,
    previous_review: dict | None = None,
    previous_review_sha256: str | None = None,
    previous_content_sha256: str | None = None,
    previous_content: dict | None = None,
    lesson_reviews: list[dict] | None = None,
    lesson_review_sha256: dict[str, str] | None = None,
) -> list[str]:
    lesson_reviews = lesson_reviews or make_lesson_reviews(
        holdout_selection, content_digest,
        review_round=review.get("review_round", 1),
        run_id=review.get("benchmark_run_id", "synthetic-benchmark-run"),
    )
    lesson_review_sha256 = lesson_review_sha256 or {
        row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in lesson_reviews
    }
    return validate_benchmark_review_payload(
        review,
        catalog=catalog,
        split=split,
        holdout_pack=holdout_pack,
        holdout_selection=holdout_selection,
        lesson_content=content,
        lesson_content_sha256=content_digest,
        holdout_selection_source_sha256=selection_source_digest or content_digest,
        lesson_reviews=lesson_reviews,
        lesson_review_sha256=lesson_review_sha256,
        previous_review=previous_review,
        previous_review_sha256=previous_review_sha256,
        previous_content=previous_content,
        previous_content_sha256=previous_content_sha256,
    )


def make_bundle_files(folder: Path, source: Path, *, group_count: int = 5, major_gap: bool = False) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    content = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(content.get("outline"), list):
        content["outline"] = [
            {"lesson_id": row.get("lesson_id", row.get("id"))}
            for row in content.get("lessons", [])
            if isinstance(row, dict) and isinstance(row.get("lesson_id", row.get("id")), str)
        ]
    if not isinstance(content.get("authoring_provenance"), dict):
        content["authoring_provenance"] = {
            "source_snapshot": {"whole_course_outline_sha256": "c" * 64}
        }
    else:
        content["authoring_provenance"].setdefault(
            "source_snapshot", {"whole_course_outline_sha256": "c" * 64}
        )
        content["authoring_provenance"]["source_snapshot"].setdefault(
            "whole_course_outline_sha256", "c" * 64
        )
    source_digest = _sha256_bytes(source.read_bytes())
    catalog = make_catalog(
        group_count,
        course_name=content["course_name"],
        major=content["major"],
        audience=content["audience"],
    )
    split = build_split(catalog)
    authoring_pack = build_exemplar_pack(catalog, split, "authoring")
    holdout_pack = build_exemplar_pack(catalog, split, "holdout")
    authoring_selection = make_authoring_selection(catalog, split, authoring_pack, content)
    holdout_selection = make_holdout_selection(catalog, split, holdout_pack, content, source_digest)
    review = make_review(
        catalog,
        split,
        holdout_pack,
        holdout_selection,
        source_digest,
        lesson_content=content,
        gap=(holdout_selection["lessons"][0]["lesson_id"], DIMENSION_IDS[0]) if major_gap and holdout_selection["lessons"][0]["exemplar_ids"] else None,
    )
    lesson_reviews = make_lesson_reviews(
        holdout_selection,
        source_digest,
        gap=(holdout_selection["lessons"][0]["lesson_id"], DIMENSION_IDS[0]) if major_gap and holdout_selection["lessons"][0]["exemplar_ids"] else None,
    )
    paths = {
        "catalog": folder / "exemplar-catalog.json",
        "split": folder / "exemplar-split.json",
        "authoring_pack": folder / "exemplar-authoring-pack.json",
        "holdout_pack": folder / "exemplar-holdout-pack.json",
        "authoring_selection": folder / "exemplar-authoring-selection.json",
        "holdout_selection": folder / "exemplar-holdout-selection.json",
        "review": folder / "benchmark-review.json",
        "lesson_reviews_dir": folder / "benchmark-review",
    }
    for key, value in (
        ("catalog", catalog),
        ("split", split),
        ("authoring_pack", authoring_pack),
        ("holdout_pack", holdout_pack),
        ("authoring_selection", authoring_selection),
        ("holdout_selection", holdout_selection),
        ("review", review),
    ):
        _write_json(paths[key], value)
    paths["lesson_reviews_dir"].mkdir(parents=True, exist_ok=True)
    for row in lesson_reviews:
        _write_json(paths["lesson_reviews_dir"] / f"{row['lesson_id']}.json", row)
    # The summary authenticates the exact pretty-printed lesson sidecar bytes.
    review, errors = build_course_review_payload(
        benchmark_run_id="synthetic-benchmark-run",
        review_round=1,
        context_mode="separate_contexts",
        isolation={"authoring_exemplars_visible": False, "author_reasoning_visible": False, "holdout_only": True},
        catalog=catalog, split=split, holdout_pack=holdout_pack,
        holdout_selection=holdout_selection, lesson_content=content,
        lesson_content_sha256=source_digest, lesson_reviews=lesson_reviews,
        lesson_review_sha256={row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in lesson_reviews},
    )
    if errors:
        raise AssertionError(errors)
    _write_json(paths["review"], review)
    return paths


def acceptance_kwargs(paths: dict[str, Path]) -> dict[str, Path]:
    return {
        "benchmark_review_path": paths["review"],
        "benchmark_catalog_path": paths["catalog"],
        "benchmark_split_path": paths["split"],
        "benchmark_holdout_pack_path": paths["holdout_pack"],
        "benchmark_holdout_selection_path": paths["holdout_selection"],
        "benchmark_authoring_pack_path": paths["authoring_pack"],
        "benchmark_authoring_selection_path": paths["authoring_selection"],
        "benchmark_lesson_reviews_dir": paths["lesson_reviews_dir"],
    }


class ExemplarCatalogTests(unittest.TestCase):
    def test_valid_catalog_and_normalized_source_identity(self) -> None:
        card = make_card(1)
        card["source"]["title"] = "  Ａ　 test\tcase  "
        card["source"]["source_identity_sha256"] = source_identity_sha256(card)
        catalog = make_catalog(0)
        catalog["exemplars"] = [card]
        refresh_catalog_fingerprint(catalog)
        self.assertEqual(validate_catalog_payload(catalog), [])

    def test_duplicate_exemplar_id_and_wrong_source_identity_fail(self) -> None:
        first = make_card(1)
        second = make_card(2)
        second["exemplar_id"] = first["exemplar_id"]
        catalog = make_catalog(0)
        catalog["exemplars"] = [first, second]
        refresh_catalog_fingerprint(catalog)
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("duplicate exemplar_id" in error for error in errors), errors)

        first["source"]["source_identity_sha256"] = "0" * 64
        refresh_catalog_fingerprint(catalog)
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("source_identity_sha256" in error for error in errors), errors)

    def test_same_source_cards_must_share_group_but_multiple_cards_are_allowed(self) -> None:
        first = make_card(1, group_id="SAME")
        same_work = copy.deepcopy(first)
        same_work["exemplar_id"] = "EX-02"
        same_work["design_patterns"] = ["Second abstract mode from the same work."]
        allowed = make_catalog(0)
        allowed["exemplars"] = [first, same_work]
        refresh_catalog_fingerprint(allowed)
        self.assertEqual(validate_catalog_payload(allowed), [])

        leaking = copy.deepcopy(allowed)
        leaking["exemplars"][1]["group_id"] = "OTHER"
        refresh_catalog_fingerprint(leaking)
        errors = validate_catalog_payload(leaking)
        self.assertTrue(any("source_identity_sha256" in error and "multiple group_id" in error for error in errors), errors)

    def test_normalized_canonical_url_cannot_span_groups(self) -> None:
        first = make_card(1, group_id="A")
        second = make_card(2, group_id="B")
        second["source"]["canonical_url"] = first["source"]["canonical_url"]
        second["source"]["source_identity_sha256"] = source_identity_sha256(second)
        catalog = make_catalog(0)
        catalog["exemplars"] = [first, second]
        refresh_catalog_fingerprint(catalog)
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("normalized canonical_url" in error for error in errors), errors)

    def test_tier_discovery_private_and_qualified_evidence_rules(self) -> None:
        tier_c = make_card(1, authority_tier="C", status="QUALIFIED")
        private_public = make_card(2, authority_tier="PRIVATE", visibility="public")
        discovery = make_card(3, source_type="discovery_source", authority_tier="A")
        empty_patterns = make_card(4)
        for field in (
            "design_patterns", "difficulty_breakthrough_patterns", "student_activity_patterns",
            "learning_evidence_patterns", "assessment_patterns", "differentiation_patterns",
            "reflection_patterns", "transferable_principles",
        ):
            empty_patterns[field] = []
        no_do_not_copy = make_card(5)
        no_do_not_copy["do_not_copy"] = []
        catalog = make_catalog(0)
        catalog["exemplars"] = [tier_c, private_public, discovery, empty_patterns, no_do_not_copy]
        refresh_catalog_fingerprint(catalog)
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("authority_tier C" in error for error in errors), errors)
        self.assertTrue(any("PRIVATE requires visibility private_session" in error for error in errors), errors)
        self.assertTrue(any("discovery_source" in error and "QUALIFIED" in error for error in errors), errors)
        self.assertTrue(any("benchmark pattern" in error for error in errors), errors)
        self.assertTrue(any("do_not_copy" in error for error in errors), errors)

    def test_provenance_core_strings_cannot_be_empty_or_blank(self) -> None:
        for field in ("title", "institution", "author_or_team", "recognition"):
            card = make_card(1)
            card["source"][field] = " "
            card["source"]["source_identity_sha256"] = source_identity_sha256(card)
            with self.subTest(field=field):
                catalog = make_catalog(0)
                catalog["exemplars"] = [card]
                refresh_catalog_fingerprint(catalog)
                self.assertTrue(validate_catalog_payload(catalog))

    def test_raw_text_and_arbitrary_card_fields_are_rejected(self) -> None:
        card = make_card(1)
        card["raw_text"] = "not allowed"
        catalog = make_catalog(0)
        catalog["exemplars"] = [card]
        refresh_catalog_fingerprint(catalog)
        errors = validate_catalog_payload(catalog)
        self.assertTrue(any("Additional properties are not allowed" in error for error in errors), errors)

    def test_catalog_fingerprint_mismatch_fails(self) -> None:
        catalog = make_catalog(1)
        catalog["catalog_fingerprint"] = "0" * 64
        self.assertTrue(any("catalog_fingerprint" in error for error in validate_catalog_payload(catalog)))

    def test_catalog_fingerprint_binds_context_and_policy_but_not_created_at(self) -> None:
        catalog = make_catalog(1)
        original = catalog["catalog_fingerprint"]
        catalog["created_at"] = "2027-01-01T00:00:00Z"
        refresh_catalog_fingerprint(catalog)
        self.assertEqual(catalog["catalog_fingerprint"], original)
        catalog["course_context"]["audience"] = "A different synthetic audience"
        refresh_catalog_fingerprint(catalog)
        self.assertNotEqual(catalog["catalog_fingerprint"], original)
        context_bound = catalog["catalog_fingerprint"]
        catalog["qualification_policy_version"] = "teaching-exemplar-qualification-v2"
        refresh_catalog_fingerprint(catalog)
        self.assertNotEqual(catalog["catalog_fingerprint"], context_bound)

    def test_public_private_source_provenance_url_safety_and_card_byte_ceiling(self) -> None:
        private = make_card(
            1,
            authority_tier="PRIVATE",
            visibility="private_session",
            source_type="private_user_provided",
        )
        private["source"].update({
            "canonical_url": None,
            "provided_source_id": "user-file-lesson-01",
            "source_label": "User-provided lesson scan",
            "authority_basis": "private_user",
            "recognition_evidence": [],
        })
        private["source"]["source_identity_sha256"] = source_identity_sha256(private)
        self.assertEqual(validate_card_payload(private), [])

        for url, expected in (
            ("https://user:secret@example.invalid/item", "userinfo"),
            ("https://example.invalid/item?access_token=secret", "credential or token"),
        ):
            card = make_card(2)
            card["source"]["canonical_url"] = url
            card["source"]["source_identity_sha256"] = source_identity_sha256(card)
            with self.subTest(url=url):
                self.assertTrue(any(expected in error for error in validate_card_payload(card)))

        oversized = make_card(3)
        for field in (
            "design_patterns", "difficulty_breakthrough_patterns", "student_activity_patterns",
            "learning_evidence_patterns", "assessment_patterns", "differentiation_patterns",
            "reflection_patterns", "transferable_principles",
        ):
            oversized[field] = ["S" * 500 for _ in range(20)]
        self.assertGreater(len(canonical_json_bytes(oversized)), MAX_CARD_BYTES)
        self.assertTrue(any("structural ceiling" in error for error in validate_card_payload(oversized)))

    def test_timestamp_validation_is_timezone_aware(self) -> None:
        card = make_card(1)
        card["source"]["retrieved_at"] = "2026-09-27T09:00:00"
        card["source"]["source_identity_sha256"] = source_identity_sha256(card)
        self.assertTrue(any("retrieved_at" in error for error in validate_card_payload(card)))
        catalog = make_catalog(1)
        catalog["created_at"] = "not-a-timestamp"
        refresh_catalog_fingerprint(catalog)
        self.assertTrue(any("created_at" in error for error in validate_catalog_payload(catalog)))


class ExemplarSplitAndPackTests(unittest.TestCase):
    def test_zero_one_two_three_and_six_group_splits_and_role_pack_projection(self) -> None:
        for count in (0, 1, 2, 3, 6):
            with self.subTest(groups=count):
                catalog = make_catalog(count)
                split = build_split(catalog)
                authoring = build_exemplar_pack(catalog, split, "authoring")
                holdout = build_exemplar_pack(catalog, split, "holdout")
                holdout_count = len(split["holdout_group_ids"])
                expected_availability = "UNAVAILABLE" if holdout_count == 0 else "PARTIAL" if holdout_count == 1 else "AVAILABLE"
                self.assertEqual(split["benchmark_availability"], expected_availability)
                self.assertEqual(split["authoring_group_count"], len(split["authoring_group_ids"]))
                self.assertEqual(split["holdout_group_count"], holdout_count)
                self.assertEqual(len(split["authoring_group_ids"]) + holdout_count, count)
                self.assertEqual(validate_split_payload(split, catalog), [])
                self.assertEqual(validate_pack_payload(authoring, catalog, split, expected_role="authoring"), [])
                self.assertEqual(validate_pack_payload(holdout, catalog, split, expected_role="holdout"), [])
                self.assertEqual(authoring["exemplar_ids"], split["authoring_exemplar_ids"])
                self.assertEqual(holdout["exemplar_ids"], split["holdout_exemplar_ids"])

    def test_repeatable_split_and_atomic_cli_generates_both_packs(self) -> None:
        catalog = make_catalog(6)
        first = expected_split(catalog, created_at="2026-09-27T00:00:00Z")
        second = expected_split(catalog, created_at="2026-09-28T00:00:00Z")
        self.assertEqual(first["split_fingerprint"], second["split_fingerprint"])
        self.assertEqual(first["split_id"], second["split_id"])
        original_assignment = {
            group: "A" if group in first["authoring_group_ids"] else "B"
            for group in first["authoring_group_ids"] + first["holdout_group_ids"]
        }
        changed_catalog = copy.deepcopy(catalog)
        changed_catalog["exemplars"][0]["design_patterns"][0] = "Edited mutable card prose."
        refresh_catalog_fingerprint(changed_catalog)
        changed_split = build_split(changed_catalog)
        changed_assignment = {
            group: "A" if group in changed_split["authoring_group_ids"] else "B"
            for group in changed_split["authoring_group_ids"] + changed_split["holdout_group_ids"]
        }
        self.assertEqual(changed_assignment, original_assignment)
        changed_catalog = copy.deepcopy(catalog)
        changed_catalog["exemplars"][0]["source"]["retrieved_at"] = "2027-01-01T00:00:00Z"
        changed_catalog["exemplars"][0]["qualification"]["rationale"] = "Updated curator rationale only."
        refresh_catalog_fingerprint(changed_catalog)
        mutable_split = build_split(changed_catalog)
        retrieval_assignment = {
            group: "A" if group in first["authoring_group_ids"] else "B"
            for group in first["authoring_group_ids"] + first["holdout_group_ids"]
        }
        mutable_assignment = {
            group: "A" if group in mutable_split["authoring_group_ids"] else "B"
            for group in mutable_split["authoring_group_ids"] + mutable_split["holdout_group_ids"]
        }
        self.assertEqual(mutable_assignment, retrieval_assignment)
        changed_catalog["exemplars"].append(make_card(99, group_id="UNRELATED-NEW-GROUP"))
        refresh_catalog_fingerprint(changed_catalog)
        added_split = build_split(changed_catalog)
        added_assignment = {
            group: "A" if group in added_split["authoring_group_ids"] else "B"
            for group in added_split["authoring_group_ids"] + added_split["holdout_group_ids"]
        }
        self.assertTrue(all(added_assignment[group] == side for group, side in original_assignment.items()))

        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-packs-") as temp_name:
            folder = Path(temp_name)
            catalog_path = folder / "catalog.json"
            _write_json(catalog_path, catalog)
            split_path = folder / "split.json"
            authoring_path = folder / "exemplar-authoring-pack.json"
            holdout_path = folder / "exemplar-holdout-pack.json"
            result = run_script(
                SCRIPTS / "exemplar_split.py",
                "--catalog", str(catalog_path),
                "--output", str(split_path),
                "--authoring-pack", str(authoring_path),
                "--holdout-pack", str(holdout_path),
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(split_path.is_file() and authoring_path.is_file() and holdout_path.is_file())
            self.assertEqual(
                json.loads(authoring_path.read_text(encoding="utf-8"))["exemplar_ids"],
                first["authoring_exemplar_ids"],
            )

            old_bytes = catalog_path.read_bytes()
            overlap = run_script(
                SCRIPTS / "exemplar_split.py",
                "--catalog", str(catalog_path),
                "--output", str(catalog_path),
                "--authoring-pack", str(folder / "overlap-authoring.json"),
                "--holdout-pack", str(folder / "overlap-holdout.json"),
            )
            self.assertNotEqual(overlap.returncode, 0)
            self.assertEqual(catalog_path.read_bytes(), old_bytes)

    def test_split_pack_transaction_restores_all_old_files_after_b_pack_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-rollback-") as temp_name:
            folder = Path(temp_name)
            destinations = tuple(folder / name for name in ("split.json", "authoring.json", "holdout.json"))
            originals = (b"old split", b"old authoring", b"old holdout")
            for path, payload in zip(destinations, originals):
                path.write_bytes(payload)
            payloads = (
                {"part": "split"}, {"part": "authoring"}, {"part": "holdout"},
            )
            real_replace = exemplar_split_module.os.replace
            calls = 0

            def fail_on_holdout(source: object, target: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected Holdout Pack replace failure")
                real_replace(source, target)

            with patch.object(exemplar_split_module.os, "replace", side_effect=fail_on_holdout):
                with self.assertRaisesRegex(ValueError, "sidecar bundle commit failed"):
                    exemplar_split_module._replace_bundle(destinations, payloads)
            self.assertEqual(tuple(path.read_bytes() for path in destinations), originals)

    def test_opposite_side_insertion_missing_extra_and_fingerprint_tamper_fail(self) -> None:
        catalog = make_catalog(6, cards_per_group=2)
        split = build_split(catalog)
        authoring = build_exemplar_pack(catalog, split, "authoring")
        holdout = build_exemplar_pack(catalog, split, "holdout")
        self.assertFalse(set(authoring["exemplar_ids"]) & set(split["holdout_exemplar_ids"]))
        self.assertFalse(set(holdout["exemplar_ids"]) & set(split["authoring_exemplar_ids"]))

        injected = copy.deepcopy(authoring)
        opposite_id = split["holdout_exemplar_ids"][0]
        injected["exemplar_ids"].append(opposite_id)
        injected["exemplars"].append(next(card for card in catalog["exemplars"] if card["exemplar_id"] == opposite_id))
        injected["pack_fingerprint"] = pack_fingerprint(injected)
        self.assertTrue(any("exactly match" in error for error in validate_pack_payload(injected, catalog, split)), validate_pack_payload(injected, catalog, split))

        missing = copy.deepcopy(authoring)
        missing["exemplar_ids"].pop()
        missing["exemplars"].pop()
        missing["pack_fingerprint"] = pack_fingerprint(missing)
        self.assertTrue(validate_pack_payload(missing, catalog, split))

        extra = copy.deepcopy(authoring)
        extra["exemplars"].append(copy.deepcopy(extra["exemplars"][0]))
        extra["pack_fingerprint"] = pack_fingerprint(extra)
        self.assertTrue(validate_pack_payload(extra, catalog, split))

        tampered = copy.deepcopy(authoring)
        tampered["pack_fingerprint"] = "0" * 64
        self.assertTrue(any("pack_fingerprint" in error for error in validate_pack_payload(tampered, catalog, split)))

    def test_pack_fingerprint_is_independent_of_array_order(self) -> None:
        catalog = make_catalog(6, cards_per_group=2)
        split = build_split(catalog)
        pack = build_exemplar_pack(catalog, split, "authoring")
        shuffled = copy.deepcopy(pack)
        shuffled["exemplar_ids"].reverse()
        shuffled["exemplars"].reverse()
        self.assertEqual(pack["pack_fingerprint"], pack_fingerprint(shuffled))
        self.assertEqual(validate_pack_payload(shuffled, catalog, split), [])

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
        self.content = make_content(["L01", "L02", "L03"])
        self.content_bytes = _json_bytes(self.content)
        self.content_digest = _sha256_bytes(self.content_bytes)
        self.catalog = make_catalog(6)
        self.split = build_split(self.catalog)
        self.authoring_pack = build_exemplar_pack(self.catalog, self.split, "authoring")
        self.holdout_pack = build_exemplar_pack(self.catalog, self.split, "holdout")
        self.authoring = make_authoring_selection(self.catalog, self.split, self.authoring_pack, self.content)
        self.holdout = make_holdout_selection(
            self.catalog, self.split, self.holdout_pack, self.content, self.content_digest
        )

    def test_valid_role_scoped_selections_and_context_size(self) -> None:
        self.assertEqual(
            validate_authoring_selection_payload(
                self.authoring, self.catalog, self.split, self.authoring_pack, self.content
            ),
            [],
        )
        self.assertEqual(
            validate_holdout_selection_payload(
                self.holdout, self.catalog, self.split, self.holdout_pack, self.content,
                lesson_content_sha256=self.content_digest,
            ),
            [],
        )
        self.assertFalse(set(self.authoring_pack["exemplar_ids"]) & set(self.holdout_pack["exemplar_ids"]))

    def test_selection_ids_are_limited_to_role_pack_and_status_is_consistent(self) -> None:
        authoring_as_holdout = copy.deepcopy(self.holdout)
        authoring_as_holdout["lessons"][0]["exemplar_ids"] = self.split["authoring_exemplar_ids"][:1]
        self.assertTrue(validate_holdout_selection_payload(
            authoring_as_holdout, self.catalog, self.split, self.holdout_pack, self.content,
            lesson_content_sha256=self.content_digest,
        ))

        holdout_as_authoring = copy.deepcopy(self.authoring)
        holdout_as_authoring["lessons"][0]["exemplar_ids"] = self.split["holdout_exemplar_ids"][:1]
        self.assertTrue(validate_authoring_selection_payload(
            holdout_as_authoring, self.catalog, self.split, self.authoring_pack, self.content
        ))

        wrong_status = copy.deepcopy(self.authoring)
        wrong_status["lessons"][0]["status"] = "NO_RELEVANT_EXEMPLAR"
        self.assertTrue(validate_authoring_selection_payload(
            wrong_status, self.catalog, self.split, self.authoring_pack, self.content
        ))

    def test_authoring_binds_existing_outline_digest_and_exact_outline_coverage(self) -> None:
        stale_digest = copy.deepcopy(self.authoring)
        stale_digest["source_outline_sha256"] = "d" * 64
        self.assertTrue(validate_authoring_selection_payload(
            stale_digest, self.catalog, self.split, self.authoring_pack, self.content
        ))

        for mutation in ("missing", "extra", "duplicate"):
            selection = copy.deepcopy(self.authoring)
            if mutation == "missing":
                selection["lessons"].pop()
            elif mutation == "extra":
                selection["lessons"][-1]["lesson_id"] = "L99"
            else:
                selection["lessons"][-1]["lesson_id"] = selection["lessons"][0]["lesson_id"]
            with self.subTest(mutation=mutation):
                self.assertTrue(validate_authoring_selection_payload(
                    selection, self.catalog, self.split, self.authoring_pack, self.content
                ))

    def test_holdout_binds_exact_content_bytes_and_exact_lesson_coverage(self) -> None:
        self.assertTrue(validate_holdout_selection_payload(
            self.holdout, self.catalog, self.split, self.holdout_pack, self.content,
            lesson_content_sha256="0" * 64,
        ))
        for mutation in ("missing", "extra", "duplicate"):
            selection = copy.deepcopy(self.holdout)
            if mutation == "missing":
                selection["lessons"].pop()
            elif mutation == "extra":
                selection["lessons"][-1]["lesson_id"] = "L99"
            else:
                selection["lessons"][-1]["lesson_id"] = selection["lessons"][0]["lesson_id"]
            with self.subTest(mutation=mutation):
                self.assertTrue(validate_holdout_selection_payload(
                    selection, self.catalog, self.split, self.holdout_pack, self.content,
                    lesson_content_sha256=self.content_digest,
                ))

    def test_catalog_context_is_bound_with_nfkc_and_whitespace_normalization(self) -> None:
        normalized_content = make_content(
            ["L01", "L02", "L03"],
            course_name="  Synthetic\u3000test course ",
            major=" Synthetic test\tmajor ",
            audience="Synthetic test audience",
        )
        self.assertEqual(
            validate_authoring_selection_payload(
                self.authoring, self.catalog, self.split, self.authoring_pack, normalized_content
            ),
            [],
        )
        wrong_course = make_content(["L01", "L02", "L03"], course_name="Database course")
        self.assertTrue(validate_authoring_selection_payload(
            self.authoring, self.catalog, self.split, self.authoring_pack, wrong_course
        ))


class BenchmarkReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = make_content(["L01", "L02", "L03"])
        self.content["authoring_provenance"]["final_content_sha256"] = _semantic_final_digest(self.content)
        self.content_bytes = _json_bytes(self.content)
        self.digest = _sha256_bytes(self.content_bytes)
        self.catalog = make_catalog(6)
        self.split = build_split(self.catalog)
        self.authoring_pack = build_exemplar_pack(self.catalog, self.split, "authoring")
        self.holdout_pack = build_exemplar_pack(self.catalog, self.split, "holdout")
        self.authoring_selection = make_authoring_selection(self.catalog, self.split, self.authoring_pack, self.content)
        self.selection = make_holdout_selection(self.catalog, self.split, self.holdout_pack, self.content, self.digest)
        self.lesson_reviews = make_lesson_reviews(self.selection, self.digest)
        self.lesson_hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in self.lesson_reviews}
        self.review = make_review(
            self.catalog, self.split, self.holdout_pack, self.selection, self.digest,
            lesson_content=self.content, lesson_reviews=self.lesson_reviews,
        )

    def validate(self, review: dict, **kwargs: object) -> list[str]:
        return validate_review_fixture(
            review,
            self.catalog,
            self.split,
            self.holdout_pack,
            self.selection,
            self.content,
            kwargs.pop("lesson_content_sha256", self.digest),
            lesson_reviews=kwargs.pop("lesson_reviews", self.lesson_reviews),
            lesson_review_sha256=kwargs.pop("lesson_review_sha256", self.lesson_hashes),
            **kwargs,
        )

    def _rebuild(self, rows: list[dict], *, selection: dict | None = None, content: dict | None = None,
                 source_digest: str | None = None, context_mode: str = "separate_contexts") -> dict:
        selection = selection or self.selection
        content = content or self.content
        source_digest = source_digest or self.digest
        return make_review(
            self.catalog, self.split, self.holdout_pack, selection, source_digest,
            lesson_content=content, lesson_reviews=rows, context_mode=context_mode,
        )

    def test_per_lesson_reviews_have_exact_coverage_and_small_shards(self) -> None:
        self.assertEqual(self.validate(self.review), [])
        rows = self.review["lesson_reviews"]
        self.assertEqual({row["lesson_id"] for row in rows}, {"L01", "L02", "L03"})
        self.assertEqual(self.review["lesson_review_count"], 3)
        self.assertTrue(all(len(row["dimensions"]) == 15 for row in self.lesson_reviews))
        self.assertFalse("lessons" in self.review)
        self.assertLessEqual(max(len(_json_bytes(row)) for row in self.lesson_reviews), 20 * 1024)

    def test_summary_and_sidecar_coverage_tampering_fail(self) -> None:
        missing = copy.deepcopy(self.review)
        missing["lesson_reviews"].pop()
        self.assertTrue(self.validate(missing))
        duplicate = copy.deepcopy(self.review)
        duplicate["lesson_reviews"][-1]["lesson_id"] = duplicate["lesson_reviews"][0]["lesson_id"]
        self.assertTrue(self.validate(duplicate))
        extra_rows = copy.deepcopy(self.lesson_reviews)
        extra_rows[-1]["lesson_id"] = "L99"
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in extra_rows}
        self.assertTrue(self.validate(self.review, lesson_reviews=extra_rows, lesson_review_sha256=hashes))
        short = copy.deepcopy(self.lesson_reviews)
        short[0]["dimensions"].pop()
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in short}
        self.assertTrue(any("15 rubric dimensions" in error for error in self.validate(
            self.review, lesson_reviews=short, lesson_review_sha256=hashes
        )))

    def test_evidence_basis_insufficient_evidence_and_na_policy(self) -> None:
        insufficient = copy.deepcopy(self.lesson_reviews)
        dimension = insufficient[0]["dimensions"][1]
        dimension.update({
            "status": "INSUFFICIENT_EVIDENCE", "severity": "advisory",
            "current_evidence": "Synthetic evidence only.", "benchmark_pattern": "",
            "gap": "The available evidence does not resolve this dimension.",
            "recommended_direction": "Ask a reviewer to inspect a relevant source.",
            "insufficiency_reason": "No selected Card provides enough evidence.",
            "holdout_exemplar_ids": [],
        })
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in insufficient}
        summary = self._rebuild(insufficient)
        self.assertEqual(self.validate(summary, lesson_reviews=insufficient, lesson_review_sha256=hashes), [])

        missing_reason = copy.deepcopy(insufficient)
        missing_reason[0]["dimensions"][1]["insufficiency_reason"] = ""
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in missing_reason}
        self.assertTrue(any("insufficiency_reason" in error for error in self.validate(
            summary, lesson_reviews=missing_reason, lesson_review_sha256=hashes
        )))

        wrong_truth_basis = copy.deepcopy(self.lesson_reviews)
        wrong_truth_basis[0]["dimensions"][0]["evidence_basis"] = "HOLDOUT_EXEMPLAR"
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in wrong_truth_basis}
        self.assertTrue(any("evidence_basis" in error for error in self.validate(
            self.review, lesson_reviews=wrong_truth_basis, lesson_review_sha256=hashes
        )))

        forbidden_na = copy.deepcopy(self.lesson_reviews)
        forbidden_na[0]["dimensions"][1].update({
            "status": "NOT_APPLICABLE", "severity": "none", "evidence_basis": "LESSON_INTERNAL",
            "current_evidence": "Synthetic explanation.", "benchmark_pattern": "", "gap": "",
            "recommended_direction": "", "insufficiency_reason": "", "source_truth_evidence": [],
            "holdout_exemplar_ids": [],
        })
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in forbidden_na}
        self.assertTrue(any("NOT_APPLICABLE_ALLOWLIST" in error for error in self.validate(
            self.review, lesson_reviews=forbidden_na, lesson_review_sha256=hashes
        )))

        allowed_na = copy.deepcopy(self.lesson_reviews)
        allowed_na[0]["dimensions"][9].update({
            "status": "NOT_APPLICABLE", "severity": "none", "evidence_basis": "LESSON_INTERNAL",
            "current_evidence": "Synthetic explanation.", "benchmark_pattern": "", "gap": "",
            "recommended_direction": "", "insufficiency_reason": "", "source_truth_evidence": [],
            "holdout_exemplar_ids": [],
        })
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in allowed_na}
        rebuilt = self._rebuild(allowed_na)
        self.assertEqual(self.validate(rebuilt, lesson_reviews=allowed_na, lesson_review_sha256=hashes), [])

    def test_citations_must_belong_to_holdout_pack_and_selection(self) -> None:
        outside_a = copy.deepcopy(self.lesson_reviews)
        outside_a[0]["dimensions"][1]["holdout_exemplar_ids"] = self.split["authoring_exemplar_ids"][:1]
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in outside_a}
        self.assertTrue(any("outside Holdout Pack" in error for error in self.validate(
            self.review, lesson_reviews=outside_a, lesson_review_sha256=hashes
        )))

        changed_selection = copy.deepcopy(self.selection)
        changed_selection["lessons"][0]["exemplar_ids"] = self.holdout_pack["exemplar_ids"][1:2]
        bad_rows = copy.deepcopy(self.lesson_reviews)
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in bad_rows}
        errors = validate_review_fixture(
            self.review, self.catalog, self.split, self.holdout_pack, changed_selection,
            self.content, self.digest, lesson_reviews=bad_rows, lesson_review_sha256=hashes,
        )
        self.assertTrue(any("selected Holdout IDs do not match Selection" in error for error in errors), errors)

    def test_availability_no_relevance_and_context_mode_are_distinct(self) -> None:
        unavailable_catalog = make_catalog(0)
        unavailable_split = build_split(unavailable_catalog)
        unavailable_pack = build_exemplar_pack(unavailable_catalog, unavailable_split, "holdout")
        unavailable_selection = make_holdout_selection(unavailable_catalog, unavailable_split, unavailable_pack, self.content, self.digest)
        unavailable_reviews = make_lesson_reviews(unavailable_selection, self.digest)
        unavailable = make_review(
            unavailable_catalog, unavailable_split, unavailable_pack, unavailable_selection, self.digest,
            lesson_content=self.content, lesson_reviews=unavailable_reviews,
        )
        self.assertEqual(unavailable["course_summary"]["decision"], "BENCHMARK_UNAVAILABLE")
        self.assertEqual(unavailable["status"], "BENCHMARK_UNAVAILABLE")

        no_relevant_selection = copy.deepcopy(self.selection)
        for row in no_relevant_selection["lessons"]:
            row["status"] = "NO_RELEVANT_EXEMPLAR"
            row["exemplar_ids"] = []
        no_relevant_reviews = make_lesson_reviews(no_relevant_selection, self.digest)
        no_relevant = make_review(
            self.catalog, self.split, self.holdout_pack, no_relevant_selection, self.digest,
            lesson_content=self.content, lesson_reviews=no_relevant_reviews,
        )
        self.assertEqual(no_relevant["course_summary"]["decision"], "HUMAN_REVIEW_REQUIRED")
        self.assertEqual(no_relevant["status"], "BENCHMARK_PARTIAL")
        self.assertNotEqual(no_relevant["status"], "BENCHMARK_UNAVAILABLE")

        single = make_review(
            self.catalog, self.split, self.holdout_pack, self.selection, self.digest,
            lesson_content=self.content, lesson_reviews=self.lesson_reviews, context_mode="single_context",
        )
        self.assertEqual(single["course_summary"]["decision"], "BENCHMARK_PARTIAL")
        self.assertEqual(single["status"], "BENCHMARK_PARTIAL")
        forged_visibility = copy.deepcopy(single)
        forged_visibility["isolation"]["author_reasoning_visible"] = False
        self.assertTrue(self.validate(forged_visibility))

    def test_round_two_requires_semantic_revision_same_run_and_revalidated_review(self) -> None:
        prior_content = make_v22_payload(
            course="Synthetic test course",
            major="Synthetic test major",
            audience="Synthetic test audience",
            theory_hours=6,
            lesson_count=3,
            specs=DB_SPECS,
        )
        lesson_package_common.validate_test_fixture_content_v2_input(prior_content)
        prior_bytes = _json_bytes(prior_content)
        prior_digest = _sha256_bytes(prior_bytes)
        selection = make_holdout_selection(self.catalog, self.split, self.holdout_pack, prior_content, prior_digest)
        prior_rows = make_lesson_reviews(selection, prior_digest, gap=("L01", DIMENSION_IDS[1]))
        prior_review = make_review(
            self.catalog, self.split, self.holdout_pack, selection, prior_digest,
            lesson_content=prior_content, lesson_reviews=prior_rows,
        )
        prior_sha = _sha256_bytes(_json_bytes(prior_review))

        def refresh_pedagogical_review(*, revise_content: bool) -> dict:
            revised_content = copy.deepcopy(prior_content)
            first_digests: list[str] = []
            final_digests: list[str] = []
            for index, lesson in enumerate(revised_content["lessons"]):
                original_agent_content = lesson_package_common.lesson_agent_content(prior_content["lessons"][index])
                if revise_content and index == 0:
                    lesson["teaching_content"][0] += " 修订后补充边界条件与操作依据。"
                final_agent_content = lesson_package_common.lesson_agent_content(lesson)
                first_digest = lesson_package_common.canonical_json_sha256(original_agent_content)
                final_digest = lesson_package_common.canonical_json_sha256(final_agent_content)
                needs_revision = revise_content and index == 0
                issue = {
                    "category": "capacity",
                    "severity": "minor",
                    "message": "Synthetic review requests a clearer boundary condition.",
                }
                lesson["pedagogical_review"] = {
                    "issues": [],
                    "draft_content": copy.deepcopy(original_agent_content),
                    "revised_content": copy.deepcopy(final_agent_content),
                    "decision": "approved",
                    "review_history": [
                        {
                            "round": 1,
                            "issues": [issue] if needs_revision else [],
                            "decision": "needs_revision" if needs_revision else "approved",
                            "content_sha256": first_digest,
                        },
                        {
                            "round": 2,
                            "issues": [],
                            "decision": "approved",
                            "content_sha256": final_digest,
                        },
                    ],
                }
                first_digests.append(first_digest)
                final_digests.append(final_digest)
            provenance = revised_content["authoring_provenance"]
            provenance["review_rounds"] = 2
            provenance["draft_content_sha256"] = lesson_package_common.content_digest_rollup(first_digests)
            provenance["final_content_sha256"] = lesson_package_common.content_digest_rollup(final_digests)
            lesson_package_common.validate_test_fixture_content_v2_input(revised_content)
            return revised_content

        revised = refresh_pedagogical_review(revise_content=True)
        revised_bytes = _json_bytes(revised)
        revised_digest = _sha256_bytes(revised_bytes)
        current_rows = make_lesson_reviews(selection, revised_digest, review_round=2)
        current_review = make_review(
            self.catalog, self.split, self.holdout_pack, selection, revised_digest,
            review_round=2, prior_review=prior_review, prior_review_sha256=prior_sha,
            lesson_content=revised, previous_content=prior_content,
            previous_content_sha256=prior_digest, lesson_reviews=current_rows,
        )
        hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in current_rows}
        self.assertEqual(validate_review_fixture(
            current_review, self.catalog, self.split, self.holdout_pack, selection,
            revised, revised_digest, selection_source_digest=prior_digest,
            previous_review=prior_review, previous_review_sha256=prior_sha,
            previous_content=prior_content, previous_content_sha256=prior_digest,
            lesson_reviews=current_rows, lesson_review_sha256=hashes,
        ), [])

        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-round2-authorization-") as temp_name:
            folder = Path(temp_name)
            paths = {
                "prior_content": folder / "lesson-content-round1.json",
                "current_content": folder / "lesson-content-round2.json",
                "catalog": folder / "catalog.json",
                "split": folder / "split.json",
                "authoring_pack": folder / "authoring-pack.json",
                "authoring_selection": folder / "authoring-selection.json",
                "holdout_pack": folder / "holdout-pack.json",
                "holdout_selection": folder / "holdout-selection.json",
                "prior_review": folder / "benchmark-review-round1.json",
                "current_review": folder / "benchmark-review-round2.json",
                "prior_reviews_dir": folder / "lesson-reviews-round1",
                "current_reviews_dir": folder / "lesson-reviews-round2",
                "authorization": folder / "benchmark-authorization-round2.json",
            }
            _write_json(paths["prior_content"], prior_content)
            _write_json(paths["current_content"], revised)
            _write_json(paths["catalog"], self.catalog)
            _write_json(paths["split"], self.split)
            _write_json(paths["authoring_pack"], self.authoring_pack)
            authoring_selection = make_authoring_selection(
                self.catalog, self.split, self.authoring_pack, prior_content
            )
            _write_json(paths["authoring_selection"], authoring_selection)
            _write_json(paths["holdout_pack"], self.holdout_pack)
            _write_json(paths["holdout_selection"], selection)
            _write_json(paths["prior_review"], prior_review)
            _write_json(paths["current_review"], current_review)
            for key, rows in (("prior_reviews_dir", prior_rows), ("current_reviews_dir", current_rows)):
                paths[key].mkdir()
                for row in rows:
                    _write_json(paths[key] / f"{row['lesson_id']}.json", row)
            authorization_run = run_script(
                SCRIPTS / "build_benchmark_authorization.py",
                "--lesson-content", str(paths["current_content"]),
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--authoring-pack", str(paths["authoring_pack"]),
                "--authoring-selection", str(paths["authoring_selection"]),
                "--holdout-pack", str(paths["holdout_pack"]),
                "--holdout-selection", str(paths["holdout_selection"]),
                "--benchmark-review", str(paths["current_review"]),
                "--lesson-reviews-dir", str(paths["current_reviews_dir"]),
                "--previous-lesson-content", str(paths["prior_content"]),
                "--previous-review", str(paths["prior_review"]),
                "--previous-lesson-reviews-dir", str(paths["prior_reviews_dir"]),
                "--output", str(paths["authorization"]),
                "--allow-test-fixture-authoring",
            )
            self.assertEqual(authorization_run.returncode, 0, authorization_run.stderr + authorization_run.stdout)
            authorization = json.loads(paths["authorization"].read_text(encoding="utf-8"))
            self.assertEqual(authorization["review_round"], 2)
            self.assertEqual(authorization["benchmark_run_id"], current_review["benchmark_run_id"])
            self.assertEqual(authorization["source_final_content_sha256"], revised["authoring_provenance"]["final_content_sha256"])

        changed_run = copy.deepcopy(current_review)
        changed_run["benchmark_run_id"] = "different-benchmark-run"
        self.assertTrue(any("benchmark_run_id" in error for error in validate_review_fixture(
            changed_run, self.catalog, self.split, self.holdout_pack, selection,
            revised, revised_digest, selection_source_digest=prior_digest,
            previous_review=prior_review, previous_review_sha256=prior_sha,
            previous_content=prior_content, previous_content_sha256=prior_digest,
            lesson_reviews=current_rows, lesson_review_sha256=hashes,
        )))

        whitespace_only = refresh_pedagogical_review(revise_content=False)
        whitespace_bytes = json.dumps(whitespace_only, ensure_ascii=False, indent=4).encode("utf-8")
        whitespace_digest = _sha256_bytes(whitespace_bytes)
        whitespace_rows = make_lesson_reviews(selection, whitespace_digest, review_round=2)
        whitespace_review = make_review(
            self.catalog, self.split, self.holdout_pack, selection, whitespace_digest,
            review_round=2, prior_review=prior_review, prior_review_sha256=prior_sha,
            lesson_content=whitespace_only, previous_content=prior_content,
            previous_content_sha256=prior_digest, lesson_reviews=whitespace_rows,
        )
        whitespace_hashes = {row["lesson_id"]: _sha256_bytes(_json_bytes(row)) for row in whitespace_rows}
        errors = validate_review_fixture(
            whitespace_review, self.catalog, self.split, self.holdout_pack, selection,
            whitespace_only, whitespace_digest, selection_source_digest=prior_digest,
            previous_review=prior_review, previous_review_sha256=prior_sha,
            previous_content=prior_content, previous_content_sha256=prior_digest,
            lesson_reviews=whitespace_rows, lesson_review_sha256=whitespace_hashes,
        )
        self.assertTrue(any("semantic final_content_sha256 must differ" in error for error in errors), errors)

    def test_course_summary_schema_rejects_unmodeled_fields_and_forged_counts(self) -> None:
        changed = copy.deepcopy(self.review)
        changed["course_summary"]["lessons_reviewed"] = 1
        self.assertTrue(any("course_summary.lessons_reviewed" in error for error in self.validate(changed)))
        changed = copy.deepcopy(self.review)
        changed["course_summary"]["overall_pedagogy_score"] = 95
        self.assertTrue(self.validate(changed))
        changed = copy.deepcopy(self.review)
        changed["course_summary"]["similarity"] = 0.7
        self.assertTrue(self.validate(changed))

    def test_report_path_aliases_are_rejected_before_any_input_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-report-paths-") as temp_name:
            folder = Path(temp_name)
            payload = make_v22_payload(
                course="Synthetic report path course",
                major="Synthetic major",
                audience="Synthetic audience",
                theory_hours=6,
                lesson_count=3,
                specs=DB_SPECS,
            )
            source = folder / "lesson-content.json"
            _write_json(source, payload)
            paths = make_bundle_files(folder / "bundle", source)
            full_linkage = (
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--authoring-pack", str(paths["authoring_pack"]),
                "--authoring-selection", str(paths["authoring_selection"]),
                "--holdout-pack", str(paths["holdout_pack"]),
                "--holdout-selection", str(paths["holdout_selection"]),
                "--lesson-content", str(source),
                "--lesson-reviews-dir", str(paths["lesson_reviews_dir"]),
            )
            protected = [source, paths["catalog"], paths["split"], paths["authoring_pack"],
                         paths["authoring_selection"], paths["holdout_pack"], paths["holdout_selection"],
                         paths["review"]]
            before = {path: path.read_bytes() for path in protected}
            for report_alias in protected:
                result = run_script(
                    SCRIPTS / "validate_benchmark_review.py",
                    "--review", str(paths["review"]),
                    *full_linkage,
                    "--report", str(report_alias),
                )
                with self.subTest(report_alias=report_alias.name):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("paths must not overlap", result.stderr)
                    self.assertEqual({path: path.read_bytes() for path in protected}, before)


class AcceptanceBenchmarkIntegrationTests(unittest.TestCase):
    def _acceptance_fixture(self, folder: Path) -> tuple[Path, Path, Path]:
        folder.mkdir(parents=True, exist_ok=True)
        payload = make_v22_payload(
            course="Synthetic Acceptance Benchmark",
            major="Synthetic test major",
            audience="Synthetic test audience",
            theory_hours=6,
            lesson_count=3,
            specs=DB_SPECS,
        )
        source = folder / "lesson-content-v2.2.json"
        _write_json(source, payload)
        output = folder / "generated"
        generated = run_script(
            SCRIPTS / "generate_lesson_plans.py",
            "--tasks-json", str(source),
            "--output-dir", str(output),
        )
        if generated.returncode != 0:
            raise AssertionError(generated.stderr + generated.stdout)
        return source, output, output / "qa-report.json"

    def test_no_benchmark_keeps_old_report_shape_and_full_linkage_is_additive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-acceptance-") as temp_name:
            folder = Path(temp_name)
            source, output, qa = self._acceptance_fixture(folder)
            old = lesson_acceptance.build_acceptance_report(
                source, output, qa, source_type="synthetic_fixture", report_dir=folder / "report-old"
            )
            self.assertNotIn("benchmark_review", old)
            self.assertEqual(old["acceptance_schema_version"], "2.0")
            self.assertEqual(lesson_acceptance.validate_report_schema(old), [])
            legacy_manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(legacy_manifest["lesson_skill_capability"], "2.2-compatible")
            self.assertEqual(legacy_manifest["teaching_exemplar_benchmark"], {"status": "not_provided"})

            paths = make_bundle_files(folder, source)
            updated = lesson_acceptance.build_acceptance_report(
                source,
                output,
                qa,
                source_type="synthetic_fixture",
                report_dir=folder / "report-new",
                **acceptance_kwargs(paths),
            )
            benchmark = updated["benchmark_review"]
            self.assertEqual(benchmark["decision"], "NO_REVISION_REQUIRED")
            self.assertEqual(updated["acceptance_schema_version"], "2.0")
            self.assertEqual(lesson_acceptance.validate_report_schema(updated), [])
            self.assertEqual(benchmark["review_sha256"], _sha256_bytes(paths["review"].read_bytes()))
            self.assertEqual(benchmark["holdout_selection_sha256"], holdout_selection_sha256(
                json.loads(paths["holdout_selection"].read_text(encoding="utf-8"))
            ))
            from jsonschema import Draft202012Validator

            schema = json.loads((ROOT / "docs" / "lesson-acceptance-report.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(updated)), [])

    def test_acceptance_requires_every_linkage_input_and_rejects_forged_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-acceptance-forged-") as temp_name:
            folder = Path(temp_name)
            source, output, qa = self._acceptance_fixture(folder)
            paths = make_bundle_files(folder, source)
            with self.assertRaisesRegex(ValueError, "requires --benchmark-catalog"):
                lesson_acceptance.build_acceptance_report(
                    source, output, qa, source_type="synthetic_fixture",
                    benchmark_review_path=paths["review"],
                )
            with self.assertRaisesRegex(ValueError, "requires --benchmark-authoring-pack"):
                lesson_acceptance.build_acceptance_report(
                    source, output, qa, source_type="synthetic_fixture",
                    benchmark_review_path=paths["review"],
                    benchmark_catalog_path=paths["catalog"],
                    benchmark_split_path=paths["split"],
                )

            forged = json.loads(paths["review"].read_text(encoding="utf-8"))
            forged["split_fingerprint"] = "0" * 64
            _write_json(paths["review"], forged)
            with self.assertRaisesRegex(ValueError, "benchmark review validation failed"):
                lesson_acceptance.build_acceptance_report(
                    source, output, qa, source_type="synthetic_fixture",
                    **acceptance_kwargs(paths),
                )

    def test_benchmark_gaps_do_not_rewrite_production_status_and_unavailable_is_legal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-acceptance-gates-") as temp_name:
            folder = Path(temp_name)
            source, output, qa = self._acceptance_fixture(folder)
            baseline = lesson_acceptance.build_acceptance_report(
                source, output, qa, source_type="synthetic_fixture", report_dir=folder / "baseline"
            )
            major_paths = make_bundle_files(folder / "major", source, major_gap=True)
            with patch.object(lesson_acceptance._runtime, "_final_status", return_value="PASSED"):
                major = lesson_acceptance.build_acceptance_report(
                    source, output, qa, source_type="synthetic_fixture",
                    report_dir=folder / "report-major", **acceptance_kwargs(major_paths),
                )
            self.assertEqual(major["benchmark_review"]["decision"], "REVISION_REQUIRED")
            self.assertEqual(major["final_status"], "PENDING_MANUAL_REVIEW")
            self.assertEqual(major["metadata"]["production_status"], baseline["metadata"]["production_status"])

            unavailable_paths = make_bundle_files(folder / "unavailable", source, group_count=0)
            unavailable = lesson_acceptance.build_acceptance_report(
                source, output, qa, source_type="synthetic_fixture",
                report_dir=folder / "report-unavailable", **acceptance_kwargs(unavailable_paths),
            )
            self.assertEqual(unavailable["benchmark_review"]["decision"], "BENCHMARK_UNAVAILABLE")
            self.assertEqual(unavailable["structural_hard_gates"]["status"], baseline["structural_hard_gates"]["status"])
            self.assertEqual(unavailable["metadata"]["production_status"], baseline["metadata"]["production_status"])
            self.assertIn("benchmark_review", unavailable["manual_completion_required"])


class CanonicalSyntheticExampleTests(unittest.TestCase):
    def test_canonical_three_group_round1_round2_bundle_is_fully_linked(self) -> None:
        bundle = LESSON / "examples" / "synthetic-benchmark-closure"
        self.assertIn("SYNTHETIC; NON-TEACHING-QUALITY-EVIDENCE", (bundle / "SYNTHETIC-README.md").read_text(encoding="utf-8"))
        inputs = bundle / "inputs"
        catalog = json.loads((inputs / "exemplar-catalog.json").read_text(encoding="utf-8"))
        split = json.loads((inputs / "exemplar-split.json").read_text(encoding="utf-8"))
        self.assertEqual(len({row["group_id"] for row in catalog["exemplars"]}), 3)
        self.assertTrue(split["authoring_group_count"] > 0 and split["holdout_group_count"] > 0)

        common_args = [
            "--catalog", str(inputs / "exemplar-catalog.json"),
            "--split", str(inputs / "exemplar-split.json"),
            "--authoring-pack", str(inputs / "exemplar-authoring-pack.json"),
            "--authoring-selection", str(inputs / "exemplar-authoring-selection.json"),
            "--holdout-pack", str(inputs / "exemplar-holdout-pack.json"),
            "--holdout-selection", str(inputs / "exemplar-holdout-selection.json"),
        ]
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-canonical-example-") as temp_name:
            temp = Path(temp_name)
            for name in ("authoring", "holdout"):
                if name == "authoring":
                    command = ["authoring-selection", "--catalog", str(inputs / "exemplar-catalog.json"),
                               "--split", str(inputs / "exemplar-split.json"), "--pack", str(inputs / "exemplar-authoring-pack.json"),
                               "--selection", str(inputs / "exemplar-authoring-selection.json"),
                               "--lesson-content", str(bundle / "round1" / "lesson-content.json")]
                else:
                    command = ["holdout-selection", "--catalog", str(inputs / "exemplar-catalog.json"),
                               "--split", str(inputs / "exemplar-split.json"), "--pack", str(inputs / "exemplar-holdout-pack.json"),
                               "--selection", str(inputs / "exemplar-holdout-selection.json"),
                               "--lesson-content", str(bundle / "round1" / "lesson-content.json")]
                result = run_script(SCRIPTS / "exemplar_contract.py", *command)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            for round_number in (1, 2):
                round_dir = bundle / f"round{round_number}"
                review_args = [
                    "--review", str(round_dir / "course-review.json"), *common_args,
                    "--lesson-content", str(round_dir / "lesson-content.json"),
                    "--lesson-reviews-dir", str(round_dir / "lesson-reviews"),
                ]
                previous = bundle / "round1"
                if round_number == 2:
                    review_args.extend([
                        "--previous-review", str(previous / "course-review.json"),
                        "--previous-lesson-reviews-dir", str(previous / "lesson-reviews"),
                        "--previous-lesson-content", str(previous / "lesson-content.json"),
                    ])
                result = run_script(SCRIPTS / "validate_benchmark_review.py", *review_args)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(json.loads(result.stdout)["status"], "PASS")

                auth_args = [
                    "--lesson-content", str(round_dir / "lesson-content.json"), *common_args,
                    "--benchmark-review", str(round_dir / "course-review.json"),
                    "--lesson-reviews-dir", str(round_dir / "lesson-reviews"),
                    "--output", str(temp / f"authorization-round{round_number}.json"),
                    "--allow-test-fixture-authoring",
                ]
                if round_number == 2:
                    auth_args.extend([
                        "--previous-lesson-content", str(previous / "lesson-content.json"),
                        "--previous-review", str(previous / "course-review.json"),
                        "--previous-lesson-reviews-dir", str(previous / "lesson-reviews"),
                    ])
                result = run_script(SCRIPTS / "build_benchmark_authorization.py", *auth_args)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                stored = json.loads((round_dir / "benchmark-authorization.json").read_text(encoding="utf-8"))
                self.assertEqual(stored["review_round"], round_number)
                self.assertEqual(stored["benchmark_run_id"], "synthetic-benchmark-run")
                from benchmark_authorization import validate_authorization_payload

                source_bytes = (round_dir / "lesson-content.json").read_bytes()
                source_content = json.loads(source_bytes.decode("utf-8"))
                self.assertEqual(validate_authorization_payload(
                    stored,
                    source_lesson_content_sha256=_sha256_bytes(source_bytes),
                    source_final_content_sha256=source_content["authoring_provenance"]["final_content_sha256"],
                ), [])


class BenchmarkScaleTests(unittest.TestCase):
    def test_20_and_32_lesson_sharded_cli_scale(self) -> None:
        for lesson_count in (20, 32):
            with self.subTest(lesson_count=lesson_count), tempfile.TemporaryDirectory(
                prefix=f"lesson-benchmark-scale-{lesson_count}-"
            ) as temp_name:
                folder = Path(temp_name)
                lesson_ids = [f"L{index:02d}" for index in range(1, lesson_count + 1)]
                content = make_content(lesson_ids, course_name=f"Synthetic Scale {lesson_count}")
                source = folder / "lesson-content.json"
                _write_json(source, content)
                content_digest = _sha256_bytes(source.read_bytes())
                catalog = make_catalog(
                    10,
                    course_name=content["course_name"],
                    major=content["major"],
                    audience=content["audience"],
                )
                split = build_split(catalog)
                authoring_pack = build_exemplar_pack(catalog, split, "authoring")
                holdout_pack = build_exemplar_pack(catalog, split, "holdout")
                authoring_selection = make_authoring_selection(catalog, split, authoring_pack, content)
                holdout_selection = make_holdout_selection(catalog, split, holdout_pack, content, content_digest)
                reviews = make_lesson_reviews(
                    holdout_selection, content_digest, run_id=f"synthetic-scale-{lesson_count}"
                )
                paths = {
                    "catalog": folder / "catalog.json",
                    "split": folder / "split.json",
                    "authoring_pack": folder / "authoring-pack.json",
                    "authoring_selection": folder / "authoring-selection.json",
                    "holdout_pack": folder / "holdout-pack.json",
                    "holdout_selection": folder / "holdout-selection.json",
                    "lesson_reviews_dir": folder / "lesson-reviews",
                    "review": folder / "course-summary.json",
                }
                for key, value in (
                    ("catalog", catalog), ("split", split),
                    ("authoring_pack", authoring_pack),
                    ("authoring_selection", authoring_selection),
                    ("holdout_pack", holdout_pack),
                    ("holdout_selection", holdout_selection),
                ):
                    _write_json(paths[key], value)
                paths["lesson_reviews_dir"].mkdir()
                for review in reviews:
                    _write_json(paths["lesson_reviews_dir"] / f"{review['lesson_id']}.json", review)

                aggregate = run_script(
                    SCRIPTS / "aggregate_benchmark_reviews.py",
                    "--output", str(paths["review"]),
                    "--catalog", str(paths["catalog"]),
                    "--split", str(paths["split"]),
                    "--authoring-pack", str(paths["authoring_pack"]),
                    "--authoring-selection", str(paths["authoring_selection"]),
                    "--holdout-pack", str(paths["holdout_pack"]),
                    "--holdout-selection", str(paths["holdout_selection"]),
                    "--lesson-content", str(source),
                    "--lesson-reviews-dir", str(paths["lesson_reviews_dir"]),
                    "--run-id", f"synthetic-scale-{lesson_count}",
                    "--review-round", "1",
                    "--context-mode", "separate_contexts",
                )
                self.assertEqual(aggregate.returncode, 0, aggregate.stderr + aggregate.stdout)
                validate = run_script(
                    SCRIPTS / "validate_benchmark_review.py",
                    "--review", str(paths["review"]),
                    "--catalog", str(paths["catalog"]),
                    "--split", str(paths["split"]),
                    "--authoring-pack", str(paths["authoring_pack"]),
                    "--authoring-selection", str(paths["authoring_selection"]),
                    "--holdout-pack", str(paths["holdout_pack"]),
                    "--holdout-selection", str(paths["holdout_selection"]),
                    "--lesson-content", str(source),
                    "--lesson-reviews-dir", str(paths["lesson_reviews_dir"]),
                )
                self.assertEqual(validate.returncode, 0, validate.stderr + validate.stdout)
                summary = json.loads(paths["review"].read_text(encoding="utf-8"))
                self.assertEqual(summary["lesson_review_count"], lesson_count)
                self.assertEqual([row["lesson_id"] for row in summary["lesson_reviews"]], lesson_ids)
                self.assertNotIn("dimensions", summary)
                self.assertEqual(len(list(paths["lesson_reviews_dir"].glob("*.json"))), lesson_count)
                total_bytes = paths["review"].stat().st_size + sum(
                    path.stat().st_size for path in paths["lesson_reviews_dir"].glob("*.json")
                )
                maximum_shard_bytes = max(path.stat().st_size for path in paths["lesson_reviews_dir"].glob("*.json"))
                summary_bytes = paths["review"].stat().st_size
                self.assertLess(summary_bytes, 12 * 1024)
                self.assertLess(maximum_shard_bytes, 20 * 1024)
                print(
                    f"synthetic_scale lessons={lesson_count} summary_bytes={summary_bytes} "
                    f"max_lesson_review_bytes={maximum_shard_bytes} total_review_bytes={total_bytes}"
                )


class TeachingExemplarBenchmarkE2ETests(unittest.TestCase):
    def test_three_lesson_benchmark_validation_precedes_render_and_acceptance_fully_links(self) -> None:
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
            content = json.loads(source.read_text(encoding="utf-8"))
            content_digest = _sha256_bytes(source.read_bytes())

            catalog = make_catalog(
                5,
                course_name=content["course_name"],
                major=content["major"],
                audience=content["audience"],
            )
            split = build_split(catalog)
            self.assertEqual(split["benchmark_availability"], "AVAILABLE")
            authoring_pack = build_exemplar_pack(catalog, split, "authoring")
            holdout_pack = build_exemplar_pack(catalog, split, "holdout")
            authoring_selection = make_authoring_selection(catalog, split, authoring_pack, content)
            holdout_selection = make_holdout_selection(
                catalog, split, holdout_pack, content, content_digest
            )
            lesson_reviews = make_lesson_reviews(
                holdout_selection, content_digest, run_id="synthetic-e2e-run"
            )

            paths = {
                "catalog": folder / "exemplar-catalog.json",
                "split": folder / "exemplar-split.json",
                "authoring_pack": folder / "exemplar-authoring-pack.json",
                "holdout_pack": folder / "exemplar-holdout-pack.json",
                "authoring_selection": folder / "exemplar-authoring-selection.json",
                "holdout_selection": folder / "exemplar-holdout-selection.json",
                "review": folder / "benchmark-review.json",
                "lesson_reviews_dir": folder / "benchmark-review",
            }
            paths["lesson_reviews_dir"].mkdir()
            for key, value in (
                ("catalog", catalog), ("split", split), ("authoring_pack", authoring_pack),
                ("holdout_pack", holdout_pack), ("authoring_selection", authoring_selection),
                ("holdout_selection", holdout_selection),
            ):
                _write_json(paths[key], value)
            for row in lesson_reviews:
                _write_json(paths["lesson_reviews_dir"] / f"{row['lesson_id']}.json", row)

            events: list[str] = ["outline-freeze", "catalog", "split-packs", "authoring-selection", "lesson-content", "pedagogical-review", "holdout-selection"]
            paths["review"] = folder / "benchmark-course-summary.json"
            aggregated = run_script(
                SCRIPTS / "aggregate_benchmark_reviews.py",
                "--output", str(paths["review"]),
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--authoring-pack", str(paths["authoring_pack"]),
                "--authoring-selection", str(paths["authoring_selection"]),
                "--holdout-pack", str(paths["holdout_pack"]),
                "--holdout-selection", str(paths["holdout_selection"]),
                "--lesson-content", str(source),
                "--lesson-reviews-dir", str(paths["lesson_reviews_dir"]),
                "--run-id", "synthetic-e2e-run",
                "--review-round", "1",
                "--context-mode", "separate_contexts",
            )
            self.assertEqual(aggregated.returncode, 0, aggregated.stderr + aggregated.stdout)
            review = json.loads(paths["review"].read_text(encoding="utf-8"))

            authoring_check = run_script(
                SCRIPTS / "exemplar_contract.py",
                "authoring-selection",
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--pack", str(paths["authoring_pack"]),
                "--selection", str(paths["authoring_selection"]),
                "--lesson-content", str(source),
            )
            self.assertEqual(authoring_check.returncode, 0, authoring_check.stderr + authoring_check.stdout)
            authoring_size = json.loads(authoring_check.stdout)
            self.assertEqual(set(authoring_size["selected_card_bytes_per_lesson"]), {"L01", "L02", "L03"})

            holdout_check = run_script(
                SCRIPTS / "exemplar_contract.py",
                "holdout-selection",
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--pack", str(paths["holdout_pack"]),
                "--selection", str(paths["holdout_selection"]),
                "--lesson-content", str(source),
            )
            self.assertEqual(holdout_check.returncode, 0, holdout_check.stderr + holdout_check.stdout)

            events.append("per-lesson-benchmark-review")
            review_check = run_script(
                SCRIPTS / "validate_benchmark_review.py",
                "--review", str(paths["review"]),
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--holdout-pack", str(paths["holdout_pack"]),
                "--holdout-selection", str(paths["holdout_selection"]),
                "--authoring-pack", str(paths["authoring_pack"]),
                "--authoring-selection", str(paths["authoring_selection"]),
                "--lesson-content", str(source),
                "--lesson-reviews-dir", str(paths["lesson_reviews_dir"]),
            )
            self.assertEqual(review_check.returncode, 0, review_check.stderr + review_check.stdout)
            self.assertEqual(json.loads(review_check.stdout)["status"], "PASS")
            events.append("benchmark-full-linkage")

            authorization_path = folder / "benchmark-authorization.json"
            authorization = run_script(
                SCRIPTS / "build_benchmark_authorization.py",
                "--lesson-content", str(source),
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--authoring-pack", str(paths["authoring_pack"]),
                "--authoring-selection", str(paths["authoring_selection"]),
                "--holdout-pack", str(paths["holdout_pack"]),
                "--holdout-selection", str(paths["holdout_selection"]),
                "--benchmark-review", str(paths["review"]),
                "--lesson-reviews-dir", str(paths["lesson_reviews_dir"]),
                "--output", str(authorization_path),
                "--allow-test-fixture-authoring",
            )
            self.assertEqual(authorization.returncode, 0, authorization.stderr + authorization.stdout)
            auth_payload = json.loads(authorization_path.read_text(encoding="utf-8"))
            events.append("benchmark-authorization")

            bypass = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json", str(source),
                "--output-dir", str(folder / "bypass-output"),
                "--benchmark-mode", "required",
            )
            self.assertNotEqual(bypass.returncode, 0)
            self.assertIn("needs --benchmark-authorization", bypass.stderr)
            tampered_auth = copy.deepcopy(auth_payload)
            tampered_auth["split_fingerprint"] = "0" * 64
            tampered_auth_path = folder / "benchmark-authorization-tampered.json"
            _write_json(tampered_auth_path, tampered_auth)
            tampered_run = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json", str(source),
                "--output-dir", str(folder / "tampered-output"),
                "--benchmark-authorization", str(tampered_auth_path),
                "--benchmark-mode", "required",
            )
            self.assertNotEqual(tampered_run.returncode, 0)
            self.assertIn("authorization_fingerprint", tampered_run.stderr)

            output = folder / "production"
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json", str(source),
                "--output-dir", str(output),
                "--benchmark-authorization", str(authorization_path),
                "--benchmark-mode", "required",
                "--render",
            )
            events.append("generator")
            self.assertLess(events.index("benchmark-full-linkage"), events.index("generator"))
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(qa["content_contract_version"], "2.2")
            self.assertEqual(qa["status"], "passed")
            self.assertEqual(qa["production_status"], "production_pass")
            manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(lesson_generator._verify_artifact_manifest(output, manifest, source), "production_pass")
            self.assertEqual(manifest["lesson_skill_capability"], "2.3-benchmark-complete")
            self.assertEqual(manifest["teaching_exemplar_benchmark"]["benchmark_authorization_sha256"], _sha256_bytes(authorization_path.read_bytes()))
            self.assertEqual(manifest["teaching_exemplar_benchmark"]["authoring_selection_sha256"], auth_payload["authoring_selection_sha256"])
            self.assertEqual(manifest["source_label"], source.name)
            self.assertEqual(manifest["source_json_path_privacy"], "local_diagnostic")
            altered_manifest = copy.deepcopy(manifest)
            altered_manifest["teaching_exemplar_benchmark"]["catalog_fingerprint"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "Benchmark block does not match"):
                lesson_generator._verify_artifact_manifest(output, altered_manifest, source)
            self.assertEqual(len(manifest["artifacts"]), 3)
            self.assertTrue(all(item["actual_pdf_page_count"] > 0 for item in manifest["artifacts"]))
            self.assertTrue(all((output / item["final_pdf_path"]).is_file() for item in manifest["artifacts"]))

            report_dir = folder / "acceptance"
            acceptance = run_script(
                ROOT / "tests" / "lesson_acceptance.py",
                "--input-json", str(source),
                "--output-dir", str(output),
                "--qa-report", str(output / "qa-report.json"),
                "--report-dir", str(report_dir),
                "--source-type", "synthetic_fixture",
                "--benchmark-review", str(paths["review"]),
                "--benchmark-catalog", str(paths["catalog"]),
                "--benchmark-split", str(paths["split"]),
                "--benchmark-authoring-pack", str(paths["authoring_pack"]),
                "--benchmark-authoring-selection", str(paths["authoring_selection"]),
                "--benchmark-holdout-pack", str(paths["holdout_pack"]),
                "--benchmark-holdout-selection", str(paths["holdout_selection"]),
                "--benchmark-lesson-reviews-dir", str(paths["lesson_reviews_dir"]),
            )
            self.assertEqual(acceptance.returncode, 0, acceptance.stderr + acceptance.stdout)
            report = json.loads((report_dir / "lesson-acceptance-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["acceptance_schema_version"], "2.0")
            self.assertEqual(report["benchmark_review"]["decision"], "NO_REVISION_REQUIRED")
            self.assertEqual(report["structural_hard_gates"]["status"], "PASS")
            self.assertEqual(report["metadata"]["production_status"], "production_pass")
            self.assertEqual(report["benchmark_review"]["source_sha256"], content_digest)
            self.assertEqual(report["benchmark_review"]["review_sha256"], _sha256_bytes(paths["review"].read_bytes()))
            self.assertEqual(report["benchmark_review"]["holdout_selection_sha256"], holdout_selection_sha256(holdout_selection))
            first_review = json.loads((paths["lesson_reviews_dir"] / "L01.json").read_text(encoding="utf-8"))
            pattern_dimension = next(
                item for item in first_review["dimensions"] if item["dimension"] != "source_truth_alignment"
            )
            self.assertIn("Synthetic abstract pattern", pattern_dimension["benchmark_pattern"])

            unavailable_paths = make_bundle_files(folder / "unavailable", source, group_count=0)
            unavailable_report_dir = folder / "acceptance-unavailable"
            unavailable_acceptance = run_script(
                ROOT / "tests" / "lesson_acceptance.py",
                "--input-json", str(source),
                "--output-dir", str(output),
                "--qa-report", str(output / "qa-report.json"),
                "--report-dir", str(unavailable_report_dir),
                "--source-type", "synthetic_fixture",
                "--benchmark-review", str(unavailable_paths["review"]),
                "--benchmark-catalog", str(unavailable_paths["catalog"]),
                "--benchmark-split", str(unavailable_paths["split"]),
                "--benchmark-authoring-pack", str(unavailable_paths["authoring_pack"]),
                "--benchmark-authoring-selection", str(unavailable_paths["authoring_selection"]),
                "--benchmark-holdout-pack", str(unavailable_paths["holdout_pack"]),
                "--benchmark-holdout-selection", str(unavailable_paths["holdout_selection"]),
                "--benchmark-lesson-reviews-dir", str(unavailable_paths["lesson_reviews_dir"]),
            )
            self.assertEqual(unavailable_acceptance.returncode, 0, unavailable_acceptance.stderr + unavailable_acceptance.stdout)
            unavailable_report = json.loads(
                (unavailable_report_dir / "lesson-acceptance-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(unavailable_report["metadata"]["production_status"], "production_pass")
            self.assertEqual(unavailable_report["benchmark_review"]["decision"], "BENCHMARK_UNAVAILABLE")
            self.assertEqual(unavailable_report["structural_hard_gates"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
