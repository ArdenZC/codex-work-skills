"""Validate Teaching Exemplar Benchmark Review Contract 1.0 sidecars."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from exemplar_contract import (
    ContractError,
    HEX_SHA256,
    holdout_selection_sha256,
    load_json,
    review_holdout_selection_sha256,
    schema_errors,
    sha256_file,
    validate_catalog_payload,
    validate_selection_payload,
)
from exemplar_split import validate_split_payload

RUBRIC_VERSION = "lesson-teaching-benchmark-v1"
DIMENSION_IDS = (
    "source_truth_alignment",
    "learner_analysis",
    "objective_quality",
    "content_selection",
    "key_difficult_point_resolution",
    "teacher_action_quality",
    "student_cognitive_activity",
    "learning_evidence",
    "objective_activity_evidence_assessment_alignment",
    "authentic_vocational_context",
    "differentiation_scaffold",
    "interaction_deep_learning",
    "assessment_quality",
    "progression_capacity",
    "teacher_usability",
)
DIMENSION_SEVERITY = {
    "MEETS": {"none", "advisory"},
    "PARTIAL": {"minor", "advisory"},
    "GAP": {"major", "minor"},
    "NOT_APPLICABLE": {"none"},
    "INSUFFICIENT_EVIDENCE": {"major", "minor", "advisory"},
}


def review_summary_for(
    lessons: list[Mapping[str, Any]],
    *,
    review_round: int,
    benchmark_availability: str,
) -> dict[str, Any]:
    major = 0
    minor = 0
    insufficient = 0
    reviewed = 0
    without_holdout = 0
    has_gap = False
    for lesson in lessons:
        holdout = lesson.get("holdout_selection", {})
        selected = holdout.get("exemplar_ids", []) if isinstance(holdout, Mapping) else []
        if selected:
            reviewed += 1
        else:
            without_holdout += 1
        for dimension in lesson.get("dimensions", []):
            status = dimension.get("status")
            severity = dimension.get("severity")
            if status == "GAP":
                has_gap = True
                if severity == "major":
                    major += 1
                elif severity == "minor":
                    minor += 1
            elif status == "INSUFFICIENT_EVIDENCE":
                insufficient += 1

    if reviewed == 0 or benchmark_availability == "UNAVAILABLE":
        decision = "BENCHMARK_UNAVAILABLE"
    elif review_round == 2 and major:
        decision = "HUMAN_REVIEW_REQUIRED"
    elif major:
        decision = "REVISION_REQUIRED"
    elif insufficient:
        decision = "HUMAN_REVIEW_REQUIRED"
    elif benchmark_availability == "PARTIAL" or without_holdout:
        decision = "BENCHMARK_PARTIAL"
    else:
        decision = "NO_REVISION_REQUIRED"

    if decision == "BENCHMARK_UNAVAILABLE":
        status = "BENCHMARK_UNAVAILABLE"
    elif decision == "HUMAN_REVIEW_REQUIRED":
        status = "HUMAN_REVIEW_REQUIRED"
    elif decision == "BENCHMARK_PARTIAL":
        status = "BENCHMARK_PARTIAL"
    elif has_gap:
        status = "BENCHMARK_GAPS_FOUND"
    else:
        status = "BENCHMARK_REVIEW_COMPLETE"
    return {
        "major_gap_count": major,
        "minor_gap_count": minor,
        "insufficient_evidence_count": insufficient,
        "lessons_reviewed": reviewed,
        "lessons_without_holdout": without_holdout,
        "decision": decision,
        "status": status,
    }


def validate_benchmark_review_payload(
    review: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any] | None = None,
    split: Mapping[str, Any] | None = None,
    selection: Mapping[str, Any] | None = None,
    lesson_content_sha256: str | None = None,
    previous_review: Mapping[str, Any] | None = None,
    previous_review_sha256: str | None = None,
) -> list[str]:
    errors = schema_errors(review, "benchmark-review.schema.json")
    if errors:
        return errors

    if review["rubric_version"] != RUBRIC_VERSION:
        errors.append(f"rubric_version must be {RUBRIC_VERSION}")
    if not all(review["isolation"].get(key) is value for key, value in (
        ("authoring_exemplars_visible", False),
        ("author_reasoning_visible", False),
        ("holdout_only", True),
    )):
        errors.append("isolation attestation must be authoring_exemplars_visible=false, author_reasoning_visible=false, holdout_only=true")
    if not HEX_SHA256.fullmatch(review["source_lesson_content_sha256"]):
        errors.append("source_lesson_content_sha256 must be a SHA-256 digest")
    if lesson_content_sha256 is not None and review["source_lesson_content_sha256"].casefold() != lesson_content_sha256.casefold():
        errors.append("source_lesson_content_sha256 does not match supplied Lesson content")

    round_number = review["review_round"]
    if round_number == 1:
        if "prior_review_sha256" in review or "prior_source_lesson_content_sha256" in review:
            errors.append("round 1 must not contain prior review provenance")
    else:
        if "prior_review_sha256" not in review or "prior_source_lesson_content_sha256" not in review:
            errors.append("round 2 requires prior_review_sha256 and prior_source_lesson_content_sha256")
        if review.get("prior_source_lesson_content_sha256", "").casefold() == review["source_lesson_content_sha256"].casefold():
            errors.append("round 2 source_lesson_content_sha256 must differ from round 1")
        if previous_review_sha256 is not None and review.get("prior_review_sha256", "").casefold() != previous_review_sha256.casefold():
            errors.append("prior_review_sha256 does not match supplied round 1 review file")
        if previous_review is not None:
            previous_schema_errors = schema_errors(previous_review, "benchmark-review.schema.json")
            errors.extend(f"previous review: {error}" for error in previous_schema_errors)
            if previous_review.get("review_round") != 1:
                errors.append("previous review must have review_round=1")
            previous_summary = previous_review.get("course_summary")
            if not isinstance(previous_summary, Mapping) or previous_summary.get("decision") != "REVISION_REQUIRED":
                errors.append("round 2 is only valid after a round 1 REVISION_REQUIRED decision")
            if review.get("prior_source_lesson_content_sha256", "").casefold() != str(previous_review.get("source_lesson_content_sha256", "")).casefold():
                errors.append("prior_source_lesson_content_sha256 does not match round 1")
            for field in ("catalog_id", "split_id", "split_fingerprint", "holdout_selection_sha256", "rubric_version"):
                if review.get(field) != previous_review.get(field):
                    errors.append(f"round 2 {field} must match round 1")
            if review["source_lesson_content_sha256"].casefold() == str(previous_review.get("source_lesson_content_sha256", "")).casefold():
                errors.append("round 2 digest must differ from round 1")

    if catalog is not None:
        catalog_errors = validate_catalog_payload(catalog)
        errors.extend(f"catalog: {error}" for error in catalog_errors)
        if catalog_errors:
            return errors
        if review["catalog_id"] != catalog.get("catalog_id"):
            errors.append("review.catalog_id does not match catalog")
            return errors
    if split is not None:
        if catalog is None:
            errors.append("catalog is required when split is supplied")
            return errors
        else:
            split_errors = validate_split_payload(dict(split), dict(catalog))
            errors.extend(f"split: {error}" for error in split_errors)
            if split_errors:
                return errors
        if review["split_id"] != split.get("split_id"):
            errors.append("review.split_id does not match split")
            return errors
        if review["split_fingerprint"].casefold() != str(split.get("split_fingerprint", "")).casefold():
            errors.append("review.split_fingerprint does not match split")
            return errors
        if review["benchmark_availability"] != split.get("benchmark_availability"):
            errors.append("review.benchmark_availability does not match split")
            return errors
    if selection is not None:
        if catalog is None or split is None:
            errors.append("catalog and split are required when selection is supplied")
            return errors
        else:
            selection_errors = validate_selection_payload(dict(selection), dict(catalog), dict(split))
            errors.extend(f"selection: {error}" for error in selection_errors)
            if selection_errors:
                return errors
        if selection.get("catalog_id") != review["catalog_id"] or selection.get("split_id") != review["split_id"]:
            errors.append("selection catalog_id/split_id do not match review")
        if holdout_selection_sha256(selection).casefold() != review["holdout_selection_sha256"].casefold():
            errors.append("holdout_selection_sha256 does not match selection sidecar")

    if review_holdout_selection_sha256(review["lessons"], review["catalog_id"], review["split_id"]).casefold() != review["holdout_selection_sha256"].casefold():
        errors.append("holdout_selection_sha256 does not match review lesson selections")

    selection_by_lesson: dict[str, Mapping[str, Any]] = {}
    if selection is not None:
        selection_by_lesson = {item["lesson_id"]: item for item in selection["lessons"]}
        if set(selection_by_lesson) != {item["lesson_id"] for item in review["lessons"]}:
            errors.append("review lessons must match selection lesson IDs")

    holdout_ids_by_lesson: dict[str, set[str]] = {}
    if selection is not None:
        holdout_ids_by_lesson = {
            item["lesson_id"]: set(item["holdout"]["exemplar_ids"])
            for item in selection["lessons"]
        }
    elif split is not None:
        holdout_ids_by_lesson = {item["lesson_id"]: set(split["holdout_exemplar_ids"]) for item in review["lessons"]}
    cards_by_id = {card["exemplar_id"]: card for card in catalog["exemplars"]} if catalog is not None else {}
    split_holdout_ids = set(split["holdout_exemplar_ids"]) if split is not None else None

    lesson_ids: set[str] = set()
    for lesson_index, lesson in enumerate(review["lessons"]):
        lesson_id = lesson["lesson_id"]
        if lesson_id in lesson_ids:
            errors.append(f"duplicate review lesson_id: {lesson_id}")
        lesson_ids.add(lesson_id)
        holdout_selection = lesson["holdout_selection"]
        selected_ids = set(holdout_selection["exemplar_ids"])
        if holdout_selection["status"] == "SELECTED" and not selected_ids:
            errors.append(f"lessons[{lesson_index}] SELECTED holdout requires exemplar_ids")
        if holdout_selection["status"] != "SELECTED" and selected_ids:
            errors.append(f"lessons[{lesson_index}] non-SELECTED holdout requires empty exemplar_ids")
        if selection is not None:
            selected = selection_by_lesson.get(lesson_id)
            if selected is not None and (
                holdout_selection["status"] != selected["holdout"]["status"]
                or holdout_selection["exemplar_ids"] != selected["holdout"]["exemplar_ids"]
            ):
                errors.append(f"lessons[{lesson_index}].holdout_selection does not match selection sidecar")
        allowed_ids = holdout_ids_by_lesson.get(lesson_id, selected_ids)
        if not selected_ids and lesson["dimensions"]:
            errors.append(f"lessons[{lesson_index}] without selected Holdout cards must have no dimensions")
        if selected_ids and len(lesson["dimensions"]) != len(DIMENSION_IDS):
            errors.append(f"lessons[{lesson_index}] with selected Holdout cards requires all 15 dimensions")
        observed_dimensions: list[str] = []
        for dimension_index, dimension in enumerate(lesson["dimensions"]):
            dimension_id = dimension["dimension"]
            observed_dimensions.append(dimension_id)
            if dimension["severity"] not in DIMENSION_SEVERITY[dimension["status"]]:
                errors.append(
                    f"lessons[{lesson_index}].dimensions[{dimension_index}] has invalid status/severity combination"
                )
            for exemplar_id in dimension["holdout_exemplar_ids"]:
                if exemplar_id not in allowed_ids:
                    errors.append(f"dimension {dimension_id} cites unselected Holdout exemplar {exemplar_id}")
                if split_holdout_ids is not None and exemplar_id not in split_holdout_ids:
                    errors.append(f"dimension {dimension_id} cites exemplar {exemplar_id} outside Holdout side B")
                card = cards_by_id.get(exemplar_id)
                if card is not None and card["qualification"]["status"] != "QUALIFIED":
                    errors.append(f"dimension {dimension_id} cites non-QUALIFIED exemplar {exemplar_id}")
        if selected_ids and set(observed_dimensions) != set(DIMENSION_IDS):
            missing = sorted(set(DIMENSION_IDS) - set(observed_dimensions))
            unknown = sorted(set(observed_dimensions) - set(DIMENSION_IDS))
            errors.append(f"lessons[{lesson_index}] dimensions must contain each rubric dimension exactly once; missing={missing}, unknown={unknown}")
        if len(observed_dimensions) != len(set(observed_dimensions)):
            errors.append(f"lessons[{lesson_index}] dimension IDs must be unique")

    summary = review_summary_for(
        review["lessons"],
        review_round=round_number,
        benchmark_availability=review["benchmark_availability"],
    )
    for field in (
        "major_gap_count",
        "minor_gap_count",
        "insufficient_evidence_count",
        "lessons_reviewed",
        "lessons_without_holdout",
        "decision",
    ):
        if review["course_summary"][field] != summary[field]:
            errors.append(f"course_summary.{field} does not match deterministic review counts/rules")
    if review["status"] != summary["status"]:
        errors.append("status does not match deterministic review counts/rules")
    return errors


def validate_benchmark_review_file(
    review_path: Path,
    *,
    catalog_path: Path | None = None,
    split_path: Path | None = None,
    selection_path: Path | None = None,
    lesson_content_path: Path | None = None,
    previous_review_path: Path | None = None,
    require_full_linkage: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    review = load_json(review_path, "benchmark review")
    catalog = load_json(catalog_path, "catalog") if catalog_path else None
    split = load_json(split_path, "split") if split_path else None
    selection = load_json(selection_path, "selection") if selection_path else None
    previous_review = load_json(previous_review_path, "previous benchmark review") if previous_review_path else None
    linkage_errors: list[str] = []
    if require_full_linkage:
        if catalog is None or split is None or selection is None or lesson_content_path is None:
            linkage_errors.append("full validation requires --catalog, --split, --selection, and --lesson-content")
        if review.get("review_round") == 2 and previous_review_path is None:
            linkage_errors.append("round 2 validation requires --previous-review")
    digest = None
    if lesson_content_path is not None:
        digest = sha256_file(lesson_content_path)
    previous_digest = sha256_file(previous_review_path) if previous_review_path is not None else None
    errors = linkage_errors + validate_benchmark_review_payload(
        review,
        catalog=catalog,
        split=split,
        selection=selection,
        lesson_content_sha256=digest,
        previous_review=previous_review,
        previous_review_sha256=previous_digest,
    )
    return review, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--split", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--lesson-content", type=Path)
    parser.add_argument("--previous-review", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--review-only", action="store_true", help="validate only the Review sidecar itself; no Catalog/Split/Selection linkage is checked")
    args = parser.parse_args(argv)
    try:
        review, errors = validate_benchmark_review_file(
            args.review,
            catalog_path=args.catalog,
            split_path=args.split,
            selection_path=args.selection,
            lesson_content_path=args.lesson_content,
            previous_review_path=args.previous_review,
            require_full_linkage=not args.review_only,
        )
        if errors:
            raise ContractError("benchmark review validation failed: " + "; ".join(errors))
        result = {
            "status": "PASS",
            "benchmark_run_id": review["benchmark_run_id"],
            "benchmark_status": review["status"],
            "decision": review["course_summary"]["decision"],
            "review_round": review["review_round"],
            "major_gap_count": review["course_summary"]["major_gap_count"],
            "minor_gap_count": review["course_summary"]["minor_gap_count"],
            "insufficient_evidence_count": review["course_summary"]["insufficient_evidence_count"],
        }
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
