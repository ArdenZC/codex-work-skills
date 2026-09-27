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
    validate_authoring_selection_payload,
    validate_catalog_payload,
    validate_holdout_selection_payload,
    validate_pack_payload,
)
from exemplar_split import build_split, expected_split, validate_split_payload  # noqa: E402
from validate_benchmark_review import (  # noqa: E402
    DIMENSION_IDS,
    review_summary_for,
    validate_benchmark_review_file,
    validate_benchmark_review_payload,
)
from tests.test_lesson_content_v22 import DB_SPECS, lesson_generator, make_v22_payload, run_script  # noqa: E402
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
    return {
        "exemplar_contract_version": "1.0",
        "catalog_id": "synthetic-catalog",
        "created_at": "2026-09-27T00:00:00Z",
        "course_context": {
            "course_name": course_name,
            "major": major,
            "audience": audience,
        },
        "catalog_fingerprint": catalog_fingerprint(cards),
        "exemplars": cards,
    }


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
) -> dict:
    lessons = []
    selection_by_id = {row["lesson_id"]: row for row in holdout_selection["lessons"]}
    for lesson_id in [row["lesson_id"] for row in holdout_selection["lessons"]]:
        selection_row = selection_by_id[lesson_id]
        dimensions = []
        if selection_row["exemplar_ids"]:
            for dimension_id in DIMENSION_IDS:
                is_gap = gap == (lesson_id, dimension_id)
                dimensions.append(
                    {
                        "dimension": dimension_id,
                        "status": "GAP" if is_gap else "MEETS",
                        "severity": "major" if is_gap else "none",
                        "current_evidence": "Synthetic benchmark evidence only; controlled test fixture.",
                        "benchmark_pattern": "Synthetic abstract pattern; no real teaching quality is asserted.",
                        "gap": "Synthetic gap fixture." if is_gap else "",
                        "recommended_direction": "Synthetic direction fixture." if is_gap else "",
                        "holdout_exemplar_ids": list(selection_row["exemplar_ids"]),
                    }
                )
        lessons.append({"lesson_id": lesson_id, "dimensions": dimensions})
    summary = review_summary_for(
        lessons,
        selection_by_id,
        review_round=review_round,
        benchmark_availability=split["benchmark_availability"],
    )
    review = {
        "benchmark_contract_version": "1.0",
        "benchmark_run_id": f"synthetic-review-round-{review_round}",
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_id": split["split_id"],
        "split_fingerprint": split["split_fingerprint"],
        "holdout_pack_fingerprint": holdout_pack["pack_fingerprint"],
        "benchmark_availability": split["benchmark_availability"],
        "source_lesson_content_sha256": source_digest,
        "holdout_selection_sha256": holdout_selection_sha256(holdout_selection),
        "rubric_version": "lesson-teaching-benchmark-v1",
        "review_round": review_round,
        "status": summary["status"],
        "isolation": {
            "authoring_exemplars_visible": False,
            "author_reasoning_visible": False,
            "holdout_only": True,
        },
        "lessons": lessons,
        "course_summary": {
            key: summary[key]
            for key in (
                "major_gap_count", "minor_gap_count", "insufficient_evidence_count",
                "lessons_reviewed", "lessons_without_holdout", "decision",
            )
        },
    }
    if review_round == 2:
        assert prior_review is not None
        review["prior_review_sha256"] = prior_review_sha256 or "b" * 64
        review["prior_source_lesson_content_sha256"] = prior_review["source_lesson_content_sha256"]
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
) -> list[str]:
    return validate_benchmark_review_payload(
        review,
        catalog=catalog,
        split=split,
        holdout_pack=holdout_pack,
        holdout_selection=holdout_selection,
        lesson_content=content,
        lesson_content_sha256=content_digest,
        holdout_selection_source_sha256=selection_source_digest or content_digest,
        previous_review=previous_review,
        previous_review_sha256=previous_review_sha256,
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
    return paths


def acceptance_kwargs(paths: dict[str, Path]) -> dict[str, Path]:
    return {
        "benchmark_review_path": paths["review"],
        "benchmark_catalog_path": paths["catalog"],
        "benchmark_split_path": paths["split"],
        "benchmark_holdout_pack_path": paths["holdout_pack"],
        "benchmark_holdout_selection_path": paths["holdout_selection"],
    }


class ExemplarCatalogTests(unittest.TestCase):
    def test_valid_catalog_and_normalized_source_identity(self) -> None:
        card = make_card(1)
        card["source"]["title"] = "  Ａ　 test\tcase  "
        card["source"]["source_identity_sha256"] = source_identity_sha256(card)
        catalog = make_catalog(0)
        catalog["exemplars"] = [card]
        catalog["catalog_fingerprint"] = catalog_fingerprint([card])
        self.assertEqual(validate_catalog_payload(catalog), [])

    def test_duplicate_exemplar_id_and_wrong_source_identity_fail(self) -> None:
        first = make_card(1)
        second = make_card(2)
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

    def test_same_source_cards_must_share_group_but_multiple_cards_are_allowed(self) -> None:
        first = make_card(1, group_id="SAME")
        same_work = copy.deepcopy(first)
        same_work["exemplar_id"] = "EX-02"
        same_work["design_patterns"] = ["Second abstract mode from the same work."]
        allowed = make_catalog(0)
        allowed["exemplars"] = [first, same_work]
        allowed["catalog_fingerprint"] = catalog_fingerprint(allowed["exemplars"])
        self.assertEqual(validate_catalog_payload(allowed), [])

        leaking = copy.deepcopy(allowed)
        leaking["exemplars"][1]["group_id"] = "OTHER"
        leaking["catalog_fingerprint"] = catalog_fingerprint(leaking["exemplars"])
        errors = validate_catalog_payload(leaking)
        self.assertTrue(any("source_identity_sha256" in error and "multiple group_id" in error for error in errors), errors)

    def test_normalized_canonical_url_cannot_span_groups(self) -> None:
        first = make_card(1, group_id="A")
        second = make_card(2, group_id="B")
        second["source"]["canonical_url"] = "HTTPS://EXAMPLE.INVALID/synthetic/1"
        second["source"]["source_identity_sha256"] = source_identity_sha256(second)
        catalog = make_catalog(0)
        catalog["exemplars"] = [first, second]
        catalog["catalog_fingerprint"] = catalog_fingerprint(catalog["exemplars"])
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
        catalog["catalog_fingerprint"] = catalog_fingerprint(catalog["exemplars"])
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
                self.assertTrue(validate_catalog_payload({
                    **make_catalog(0),
                    "exemplars": [card],
                    "catalog_fingerprint": catalog_fingerprint([card]),
                }))

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


class ExemplarSplitAndPackTests(unittest.TestCase):
    def test_zero_one_two_three_and_six_group_splits_and_role_pack_projection(self) -> None:
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
                authoring = build_exemplar_pack(catalog, split, "authoring")
                holdout = build_exemplar_pack(catalog, split, "holdout")
                self.assertEqual(split["benchmark_availability"], availability)
                self.assertEqual(len(split["authoring_group_ids"]), authoring_count)
                self.assertEqual(len(split["holdout_group_ids"]), holdout_count)
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
        ranked = sorted(
            {card["group_id"] for card in catalog["exemplars"]},
            key=lambda group_id: hashlib.sha256(
                f"{catalog['catalog_fingerprint']}\n{group_id}".encode("utf-8")
            ).hexdigest(),
        )
        pattern = ["A" if group in first["authoring_group_ids"] else "B" for group in ranked]
        self.assertEqual(pattern, ["A", "B", "B", "A", "B", "B"])

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
        self.content_bytes = _json_bytes(self.content)
        self.digest = _sha256_bytes(self.content_bytes)
        self.catalog = make_catalog(5)
        self.split = build_split(self.catalog)
        self.authoring_pack = build_exemplar_pack(self.catalog, self.split, "authoring")
        self.holdout_pack = build_exemplar_pack(self.catalog, self.split, "holdout")
        self.authoring_selection = make_authoring_selection(self.catalog, self.split, self.authoring_pack, self.content)
        self.selection = make_holdout_selection(
            self.catalog, self.split, self.holdout_pack, self.content, self.digest
        )
        self.review = make_review(
            self.catalog, self.split, self.holdout_pack, self.selection, self.digest
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
            **kwargs,
        )

    def test_valid_review_covers_every_lesson_with_exactly_15_dimensions(self) -> None:
        self.assertEqual(self.validate(self.review), [])
        report_ids = [row["lesson_id"] for row in self.review["lessons"]]
        self.assertEqual(set(report_ids), {"L01", "L02", "L03"})
        self.assertTrue(all(len(row["dimensions"]) == 15 for row in self.review["lessons"]))

    def test_missing_extra_duplicate_lessons_and_dimensions_fail(self) -> None:
        for mutation in ("missing", "extra", "duplicate"):
            review = copy.deepcopy(self.review)
            if mutation == "missing":
                review["lessons"].pop()
            elif mutation == "extra":
                review["lessons"][-1]["lesson_id"] = "L99"
            else:
                review["lessons"][-1]["lesson_id"] = review["lessons"][0]["lesson_id"]
            with self.subTest(mutation=mutation):
                self.assertTrue(self.validate(review))

        missing_dimension = copy.deepcopy(self.review)
        missing_dimension["lessons"][0]["dimensions"].pop()
        self.assertTrue(any("15 rubric dimensions" in error for error in self.validate(missing_dimension)))
        duplicate_dimension = copy.deepcopy(self.review)
        duplicate_dimension["lessons"][0]["dimensions"][-1]["dimension"] = DIMENSION_IDS[0]
        self.assertTrue(self.validate(duplicate_dimension))

    def test_vacuous_and_incomplete_dimension_evidence_fail(self) -> None:
        vacuous = copy.deepcopy(self.review)
        for dimension in vacuous["lessons"][0]["dimensions"]:
            dimension["current_evidence"] = ""
            dimension["benchmark_pattern"] = ""
            dimension["holdout_exemplar_ids"] = []
        errors = self.validate(vacuous)
        self.assertTrue(any("current_evidence" in error for error in errors), errors)
        self.assertTrue(any("benchmark_pattern" in error for error in errors), errors)
        self.assertTrue(any("holdout_exemplar_ids" in error for error in errors), errors)

        cases = (
            ("MEETS", "current_evidence", ""),
            ("MEETS", "benchmark_pattern", ""),
            ("PARTIAL", "gap", ""),
            ("PARTIAL", "recommended_direction", ""),
            ("GAP", "gap", ""),
            ("GAP", "recommended_direction", ""),
            ("INSUFFICIENT_EVIDENCE", "recommended_direction", ""),
            ("NOT_APPLICABLE", "current_evidence", ""),
        )
        for status, field, value in cases:
            review = copy.deepcopy(self.review)
            dimension = review["lessons"][0]["dimensions"][0]
            dimension["status"] = status
            dimension["severity"] = {
                "MEETS": "none",
                "PARTIAL": "minor",
                "GAP": "major",
                "INSUFFICIENT_EVIDENCE": "advisory",
                "NOT_APPLICABLE": "none",
            }[status]
            if status == "NOT_APPLICABLE":
                dimension["benchmark_pattern"] = ""
                dimension["holdout_exemplar_ids"] = []
            elif status in {"PARTIAL", "GAP", "INSUFFICIENT_EVIDENCE"}:
                dimension["gap"] = "some gap"
                dimension["recommended_direction"] = "some direction"
            dimension[field] = value
            with self.subTest(status=status, field=field):
                self.assertTrue(self.validate(review))

    def test_meets_and_not_applicable_allow_only_the_documented_empty_fields(self) -> None:
        review = copy.deepcopy(self.review)
        not_applicable = review["lessons"][0]["dimensions"][0]
        not_applicable.update({
            "status": "NOT_APPLICABLE",
            "severity": "none",
            "current_evidence": "This dimension is not applicable to the supplied course.",
            "benchmark_pattern": "",
            "gap": "",
            "recommended_direction": "",
            "holdout_exemplar_ids": [],
        })
        self.assertEqual(self.validate(review), [])

        meets = copy.deepcopy(self.review)
        dimension = meets["lessons"][0]["dimensions"][0]
        dimension["gap"] = ""
        dimension["recommended_direction"] = ""
        self.assertEqual(self.validate(meets), [])

    def test_holdout_citations_must_belong_to_pack_and_that_lessons_selection(self) -> None:
        outside_a = copy.deepcopy(self.review)
        outside_a["lessons"][0]["dimensions"][0]["holdout_exemplar_ids"] = self.split["authoring_exemplar_ids"][:1]
        self.assertTrue(any("outside Holdout Pack" in error for error in self.validate(outside_a)))

        selection = copy.deepcopy(self.selection)
        other_ids = self.holdout_pack["exemplar_ids"][1:2]
        selection["lessons"][0]["exemplar_ids"] = other_ids
        review = copy.deepcopy(self.review)
        review["holdout_selection_sha256"] = holdout_selection_sha256(selection)
        errors = validate_review_fixture(
            review,
            self.catalog,
            self.split,
            self.holdout_pack,
            selection,
            self.content,
            self.digest,
        )
        self.assertTrue(any("outside this Lesson's Holdout Selection" in error for error in errors), errors)

    def test_unavailable_review_has_full_lesson_rows_and_no_dimensions(self) -> None:
        catalog = make_catalog(0)
        split = build_split(catalog)
        pack = build_exemplar_pack(catalog, split, "holdout")
        selection = make_holdout_selection(catalog, split, pack, self.content, self.digest)
        review = make_review(catalog, split, pack, selection, self.digest)
        self.assertEqual(self.validate_review_payload_with(catalog, split, pack, selection, review), [])
        self.assertEqual(len(review["lessons"]), 3)
        self.assertTrue(all(row["dimensions"] == [] for row in review["lessons"]))
        self.assertEqual(review["course_summary"]["decision"], "BENCHMARK_UNAVAILABLE")

    def validate_review_payload_with(self, catalog: dict, split: dict, pack: dict, selection: dict, review: dict) -> list[str]:
        return validate_review_fixture(
            review, catalog, split, pack, selection, self.content, self.digest
        )

    def test_catalog_course_context_mismatch_fails(self) -> None:
        catalog = copy.deepcopy(self.catalog)
        catalog["course_context"]["course_name"] = "护理"
        catalog["catalog_fingerprint"] = catalog_fingerprint(catalog["exemplars"])
        errors = validate_review_fixture(
            self.review, catalog, self.split, self.holdout_pack, self.selection,
            self.content, self.digest,
        )
        self.assertTrue(any("course_context.course_name" in error for error in errors), errors)

    def test_summary_severity_isolation_and_unmodeled_fields_fail(self) -> None:
        changed = copy.deepcopy(self.review)
        changed["isolation"]["authoring_exemplars_visible"] = True
        self.assertTrue(any("isolation" in error for error in self.validate(changed)))

        wrong_summary = copy.deepcopy(self.review)
        wrong_summary["course_summary"]["lessons_reviewed"] = 1
        self.assertTrue(any("lessons_reviewed" in error for error in self.validate(wrong_summary)))

        with_score = copy.deepcopy(self.review)
        with_score["course_summary"]["score"] = 95
        self.assertTrue(self.validate(with_score))
        with_similarity = copy.deepcopy(self.review)
        with_similarity["lessons"][0]["dimensions"][0]["similarity"] = 0.7
        self.assertTrue(self.validate(with_similarity))

    def test_round_two_requires_revision_and_changed_content_with_frozen_holdout(self) -> None:
        round_one = make_review(
            self.catalog, self.split, self.holdout_pack, self.selection, self.digest,
            gap=("L01", DIMENSION_IDS[0]),
        )
        prior_bytes = _json_bytes(round_one)
        round_one_digest = _sha256_bytes(prior_bytes)
        revised_content = copy.deepcopy(self.content)
        revised_content["lessons"][0]["revision_note"] = "synthetic revision"
        revised_bytes = _json_bytes(revised_content)
        revised_digest = _sha256_bytes(revised_bytes)
        round_two = make_review(
            self.catalog, self.split, self.holdout_pack, self.selection, revised_digest,
            review_round=2,
            prior_review=round_one,
            prior_review_sha256=round_one_digest,
        )
        self.assertEqual(
            validate_review_fixture(
                round_two, self.catalog, self.split, self.holdout_pack, self.selection,
                revised_content, revised_digest, selection_source_digest=self.digest,
                previous_review=round_one, previous_review_sha256=round_one_digest,
                previous_content_sha256=self.digest,
            ),
            [],
        )

        no_review = validate_review_fixture(
            round_two, self.catalog, self.split, self.holdout_pack, self.selection,
            revised_content, revised_digest, selection_source_digest=self.digest,
        )
        self.assertTrue(any("previous Review" in error for error in no_review), no_review)
        same_digest = copy.deepcopy(round_two)
        same_digest["source_lesson_content_sha256"] = self.digest
        self.assertTrue(self.validate_round_two(same_digest, round_one, round_one_digest, revised_content, self.digest))

        changed_selection = copy.deepcopy(self.selection)
        changed_selection["lessons"][0]["exemplar_ids"] = self.holdout_pack["exemplar_ids"][1:2]
        changed_selection["source_lesson_content_sha256"] = self.digest
        changed_selection_digest = holdout_selection_sha256(changed_selection)
        changed_review = copy.deepcopy(round_two)
        changed_review["holdout_selection_sha256"] = changed_selection_digest
        self.assertTrue(validate_review_fixture(
            changed_review, self.catalog, self.split, self.holdout_pack, changed_selection,
            revised_content, revised_digest, selection_source_digest=self.digest,
            previous_review=round_one, previous_review_sha256=round_one_digest,
            previous_content_sha256=self.digest,
        ))

        rejected_round_one = copy.deepcopy(round_one)
        rejected_round_one["course_summary"]["decision"] = "NO_REVISION_REQUIRED"
        self.assertTrue(self.validate_round_two(
            round_two, rejected_round_one, _sha256_bytes(_json_bytes(rejected_round_one)),
            revised_content, revised_digest,
        ))

    def validate_round_two(self, review: dict, previous_review: dict, previous_hash: str, content: dict, digest: str) -> list[str]:
        return validate_review_fixture(
            review, self.catalog, self.split, self.holdout_pack, self.selection,
            content, digest, selection_source_digest=self.digest,
            previous_review=previous_review, previous_review_sha256=previous_hash,
            previous_content_sha256=self.digest,
        )

    def test_round_two_file_validator_rechecks_round_one_full_linkage(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-benchmark-round2-") as temp_name:
            folder = Path(temp_name)
            first_content = folder / "round1-content.json"
            first_bytes = _write_json(first_content, self.content)
            first_digest = _sha256_bytes(first_bytes)
            selection = make_holdout_selection(
                self.catalog, self.split, self.holdout_pack, self.content, first_digest
            )
            selection_path = folder / "holdout-selection.json"
            _write_json(selection_path, selection)
            catalog_path = folder / "catalog.json"
            split_path = folder / "split.json"
            pack_path = folder / "holdout-pack.json"
            _write_json(catalog_path, self.catalog)
            _write_json(split_path, self.split)
            _write_json(pack_path, self.holdout_pack)
            first_review = make_review(
                self.catalog, self.split, self.holdout_pack, selection, first_digest,
                gap=("L01", DIMENSION_IDS[0]),
            )
            first_review_path = folder / "round1-review.json"
            first_review_bytes = _write_json(first_review_path, first_review)
            second_content = copy.deepcopy(self.content)
            second_content["lessons"][0]["revision_note"] = "revised"
            second_content_path = folder / "round2-content.json"
            second_bytes = _write_json(second_content_path, second_content)
            second_digest = _sha256_bytes(second_bytes)
            second_review = make_review(
                self.catalog, self.split, self.holdout_pack, selection, second_digest,
                review_round=2, prior_review=first_review,
                prior_review_sha256=_sha256_bytes(first_review_bytes),
            )
            second_review_path = folder / "round2-review.json"
            _write_json(second_review_path, second_review)
            _, errors = validate_benchmark_review_file(
                second_review_path,
                catalog_path=catalog_path,
                split_path=split_path,
                holdout_pack_path=pack_path,
                holdout_selection_path=selection_path,
                lesson_content_path=second_content_path,
                previous_review_path=first_review_path,
                previous_lesson_content_path=first_content,
            )
            self.assertEqual(errors, [], errors)

            invalid_first = copy.deepcopy(first_review)
            invalid_first["split_fingerprint"] = "0" * 64
            _write_json(first_review_path, invalid_first)
            _, errors = validate_benchmark_review_file(
                second_review_path,
                catalog_path=catalog_path,
                split_path=split_path,
                holdout_pack_path=pack_path,
                holdout_selection_path=selection_path,
                lesson_content_path=second_content_path,
                previous_review_path=first_review_path,
                previous_lesson_content_path=first_content,
            )
            self.assertTrue(any("Round 1 full validation" in error for error in errors), errors)


class AcceptanceBenchmarkIntegrationTests(unittest.TestCase):
    def _acceptance_fixture(self, folder: Path) -> tuple[Path, Path, Path]:
        from tests.test_lesson_skill_hardening import LessonSkillHardeningTests

        helper = LessonSkillHardeningTests()
        source, output, qa, _ = helper._acceptance_fixture(folder)
        return source, output, qa

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

            forged = json.loads(paths["review"].read_text(encoding="utf-8"))
            forged["split_fingerprint"] = "0" * 64
            forged["lessons"][0]["dimensions"][0]["holdout_exemplar_ids"] = json.loads(
                paths["split"].read_text(encoding="utf-8")
            )["authoring_exemplar_ids"][:1]
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
            with patch.object(lesson_acceptance, "_final_status", return_value="PASSED"):
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
            self.assertEqual(unavailable["structural_hard_gates"]["status"], "PASS")
            self.assertEqual(unavailable["metadata"]["production_status"], baseline["metadata"]["production_status"])
            self.assertNotEqual(unavailable["final_status"], "FAILED")


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
            review = make_review(
                catalog, split, holdout_pack, holdout_selection, content_digest
            )

            paths = {
                "catalog": folder / "exemplar-catalog.json",
                "split": folder / "exemplar-split.json",
                "authoring_pack": folder / "exemplar-authoring-pack.json",
                "holdout_pack": folder / "exemplar-holdout-pack.json",
                "authoring_selection": folder / "exemplar-authoring-selection.json",
                "holdout_selection": folder / "exemplar-holdout-selection.json",
                "review": folder / "benchmark-review.json",
            }
            for key, value in (
                ("catalog", catalog), ("split", split), ("authoring_pack", authoring_pack),
                ("holdout_pack", holdout_pack), ("authoring_selection", authoring_selection),
                ("holdout_selection", holdout_selection), ("review", review),
            ):
                _write_json(paths[key], value)

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

            events: list[str] = []
            events.append("benchmark-full-linkage")
            review_check = run_script(
                SCRIPTS / "validate_benchmark_review.py",
                "--review", str(paths["review"]),
                "--catalog", str(paths["catalog"]),
                "--split", str(paths["split"]),
                "--holdout-pack", str(paths["holdout_pack"]),
                "--holdout-selection", str(paths["holdout_selection"]),
                "--lesson-content", str(source),
            )
            self.assertEqual(review_check.returncode, 0, review_check.stderr + review_check.stdout)
            self.assertEqual(json.loads(review_check.stdout)["status"], "PASS")
            events.append("generator")

            output = folder / "production"
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json", str(source),
                "--output-dir", str(output),
                "--render",
            )
            self.assertLess(events.index("benchmark-full-linkage"), events.index("generator"))
            self.assertEqual(generated.returncode, 0, generated.stderr + generated.stdout)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(qa["content_contract_version"], "2.2")
            self.assertEqual(qa["status"], "passed")
            self.assertEqual(qa["production_status"], "production_pass")
            manifest = json.loads((output / "artifact-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(lesson_generator._verify_artifact_manifest(output, manifest, source), "production_pass")
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
                "--benchmark-holdout-pack", str(paths["holdout_pack"]),
                "--benchmark-holdout-selection", str(paths["holdout_selection"]),
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
            self.assertIn("Synthetic abstract pattern", review["lessons"][0]["dimensions"][0]["benchmark_pattern"])

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
                "--benchmark-holdout-pack", str(unavailable_paths["holdout_pack"]),
                "--benchmark-holdout-selection", str(unavailable_paths["holdout_selection"]),
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
