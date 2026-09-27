"""Validate fully linked Teaching Exemplar Benchmark Review Contract 1.0 evidence."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any

from exemplar_contract import (
    ContractError,
    HEX_SHA256,
    holdout_selection_sha256,
    load_json,
    load_json_bytes,
    schema_errors,
    sha256_file,
    validate_catalog_course_context,
    validate_catalog_payload,
    validate_holdout_selection_payload,
    validate_pack_payload,
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


def _source_lesson_ids(lesson_content: Mapping[str, Any]) -> list[str]:
    lessons = lesson_content.get("lessons")
    if not isinstance(lessons, list):
        return []
    return [
        row.get("lesson_id", row.get("id"))
        for row in lessons
        if isinstance(row, Mapping)
        and isinstance(row.get("lesson_id", row.get("id")), str)
        and row.get("lesson_id", row.get("id"))
    ]


def review_summary_for(
    lessons: list[Mapping[str, Any]],
    selection_by_lesson: Mapping[str, Mapping[str, Any]],
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
        lesson_id = lesson.get("lesson_id")
        selected_row = selection_by_lesson.get(str(lesson_id), {})
        has_holdout = selected_row.get("status") == "SELECTED" and bool(selected_row.get("exemplar_ids"))
        if has_holdout:
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


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _exact_ids(label: str, rows: list[Mapping[str, Any]], expected_ids: list[str], errors: list[str]) -> dict[str, Mapping[str, Any]]:
    ids = [row.get("lesson_id") for row in rows]
    if not all(isinstance(value, str) and value for value in ids):
        errors.append(f"{label} must contain non-empty lesson_id values")
    if len(ids) != len(set(ids)):
        errors.append(f"{label} lesson_id values must be unique")
    if set(ids) != set(expected_ids) or len(ids) != len(expected_ids):
        errors.append(f"{label} lesson IDs must exactly match Lesson Content lesson IDs")
    return {
        str(row.get("lesson_id")): row
        for row in rows
        if isinstance(row.get("lesson_id"), str) and row.get("lesson_id")
    }


def validate_benchmark_review_payload(
    review: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    holdout_pack: Mapping[str, Any],
    holdout_selection: Mapping[str, Any],
    lesson_content: Mapping[str, Any],
    lesson_content_sha256: str,
    holdout_selection_source_sha256: str,
    previous_review: Mapping[str, Any] | None = None,
    previous_review_sha256: str | None = None,
    previous_content_sha256: str | None = None,
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
    if review["source_lesson_content_sha256"].casefold() != lesson_content_sha256.casefold():
        errors.append("source_lesson_content_sha256 does not match exact supplied Lesson Content bytes")

    catalog_errors = validate_catalog_payload(catalog)
    errors.extend(f"catalog: {error}" for error in catalog_errors)
    if catalog_errors:
        return errors
    split_errors = validate_split_payload(dict(split), dict(catalog))
    errors.extend(f"split: {error}" for error in split_errors)
    if split_errors:
        return errors
    pack_errors = validate_pack_payload(holdout_pack, catalog, split, expected_role="holdout")
    errors.extend(f"holdout Pack: {error}" for error in pack_errors)
    if pack_errors:
        return errors
    errors.extend(validate_catalog_course_context(catalog, lesson_content))

    selection_errors = validate_holdout_selection_payload(
        holdout_selection,
        catalog,
        split,
        holdout_pack,
        lesson_content,
        lesson_content_sha256=holdout_selection_source_sha256,
    )
    errors.extend(f"holdout Selection: {error}" for error in selection_errors)
    if selection_errors:
        return errors

    linked_values = (
        ("catalog_id", catalog["catalog_id"]),
        ("catalog_fingerprint", catalog["catalog_fingerprint"]),
        ("split_id", split["split_id"]),
        ("split_fingerprint", split["split_fingerprint"]),
        ("holdout_pack_fingerprint", holdout_pack["pack_fingerprint"]),
        ("benchmark_availability", split["benchmark_availability"]),
    )
    for field, expected in linked_values:
        actual = review[field]
        if isinstance(expected, str) and isinstance(actual, str):
            matches = actual.casefold() == expected.casefold()
        else:
            matches = actual == expected
        if not matches:
            errors.append(f"review.{field} does not match supplied evidence")
    expected_selection_digest = holdout_selection_sha256(holdout_selection)
    if review["holdout_selection_sha256"].casefold() != expected_selection_digest.casefold():
        errors.append("holdout_selection_sha256 does not match canonical Holdout Selection payload")

    lesson_ids = _source_lesson_ids(lesson_content)
    if len(lesson_ids) != len(lesson_content.get("lessons", [])):
        errors.append("Lesson Content must have a non-empty lesson_id on every Lesson")
    selection_rows = holdout_selection["lessons"]
    review_rows = review["lessons"]
    selection_by_id = _exact_ids("Holdout Selection", selection_rows, lesson_ids, errors)
    review_by_id = _exact_ids("Review", review_rows, lesson_ids, errors)
    holdout_pack_ids = set(holdout_pack["exemplar_ids"])

    for lesson_id in sorted(set(lesson_ids) & set(review_by_id)):
        selection_row = selection_by_id.get(lesson_id)
        review_row = review_by_id[lesson_id]
        if selection_row is None:
            continue
        selected_ids = set(selection_row["exemplar_ids"])
        dimensions = review_row["dimensions"]
        if selected_ids:
            observed = [dimension["dimension"] for dimension in dimensions]
            if len(observed) != len(DIMENSION_IDS) or set(observed) != set(DIMENSION_IDS):
                missing = sorted(set(DIMENSION_IDS) - set(observed))
                unknown = sorted(set(observed) - set(DIMENSION_IDS))
                errors.append(f"Lesson {lesson_id} requires each of the 15 rubric dimensions exactly once; missing={missing}, unknown={unknown}")
        elif dimensions:
            errors.append(f"Lesson {lesson_id} has no Holdout exemplars and must not contain Review dimensions")

        observed_dimensions: list[str] = []
        for dimension in dimensions:
            dimension_id = dimension["dimension"]
            observed_dimensions.append(dimension_id)
            if dimension["severity"] not in DIMENSION_SEVERITY[dimension["status"]]:
                errors.append(f"Lesson {lesson_id} dimension {dimension_id} has severity inconsistent with status")
            status = dimension["status"]
            if status in {"MEETS", "PARTIAL", "GAP", "INSUFFICIENT_EVIDENCE"}:
                for field in ("current_evidence", "benchmark_pattern"):
                    if not _nonempty(dimension[field]):
                        errors.append(f"Lesson {lesson_id} dimension {dimension_id} {field} must be non-empty for {status}")
                if not dimension["holdout_exemplar_ids"]:
                    errors.append(f"Lesson {lesson_id} dimension {dimension_id} {status} requires at least one Holdout citation")
            elif status == "NOT_APPLICABLE" and not _nonempty(dimension["current_evidence"]):
                errors.append(f"Lesson {lesson_id} dimension {dimension_id} NOT_APPLICABLE requires a non-empty explanation")
            if status in {"PARTIAL", "GAP", "INSUFFICIENT_EVIDENCE"}:
                for field in ("gap", "recommended_direction"):
                    if not _nonempty(dimension[field]):
                        errors.append(f"Lesson {lesson_id} dimension {dimension_id} {status} requires non-empty {field}")
            citations = set(dimension["holdout_exemplar_ids"])
            if not citations <= holdout_pack_ids:
                errors.append(f"Lesson {lesson_id} dimension {dimension_id} cites exemplar outside Holdout Pack")
            if not citations <= selected_ids:
                errors.append(f"Lesson {lesson_id} dimension {dimension_id} cites exemplar outside this Lesson's Holdout Selection")
        if len(observed_dimensions) != len(set(observed_dimensions)):
            errors.append(f"Lesson {lesson_id} Review dimension IDs must be unique")

    round_number = review["review_round"]
    if round_number == 1:
        if previous_review is not None or previous_review_sha256 is not None or previous_content_sha256 is not None:
            errors.append("round 1 must not supply prior review or Lesson Content")
        if holdout_selection["source_lesson_content_sha256"].casefold() != lesson_content_sha256.casefold():
            errors.append("round 1 Holdout Selection must bind the current Lesson Content bytes")
    else:
        if previous_review is None or previous_review_sha256 is None or previous_content_sha256 is None:
            errors.append("round 2 requires a fully validated previous Review and previous Lesson Content")
        else:
            if review["prior_review_sha256"].casefold() != previous_review_sha256.casefold():
                errors.append("prior_review_sha256 does not match the supplied Round 1 Review file")
            if review["prior_source_lesson_content_sha256"].casefold() != previous_content_sha256.casefold():
                errors.append("prior_source_lesson_content_sha256 does not match supplied Round 1 Lesson Content bytes")
            if holdout_selection["source_lesson_content_sha256"].casefold() != previous_content_sha256.casefold():
                errors.append("Round 2 must retain the Holdout Selection bound to Round 1 Lesson Content")
            if review["source_lesson_content_sha256"].casefold() == previous_content_sha256.casefold():
                errors.append("Round 2 current Lesson Content digest must differ from Round 1")
            if previous_review.get("review_round") != 1:
                errors.append("previous Review must have review_round=1")
            previous_summary = previous_review.get("course_summary")
            if not isinstance(previous_summary, Mapping) or previous_summary.get("decision") != "REVISION_REQUIRED":
                errors.append("Round 2 is only valid after a Round 1 REVISION_REQUIRED decision")
            if previous_review.get("source_lesson_content_sha256", "").casefold() != previous_content_sha256.casefold():
                errors.append("Round 1 Review source digest does not match the supplied Round 1 Lesson Content")
            for field in (
                "catalog_id", "catalog_fingerprint", "split_id", "split_fingerprint",
                "holdout_pack_fingerprint", "benchmark_availability", "holdout_selection_sha256", "rubric_version",
            ):
                if review[field] != previous_review.get(field):
                    errors.append(f"Round 2 {field} must remain fixed from Round 1")

    summary = review_summary_for(
        review["lessons"],
        selection_by_id,
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
    holdout_pack_path: Path | None = None,
    holdout_selection_path: Path | None = None,
    lesson_content_path: Path | None = None,
    previous_review_path: Path | None = None,
    previous_lesson_content_path: Path | None = None,
    require_full_linkage: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    review = load_json(review_path, "benchmark review")
    if not require_full_linkage:
        return review, schema_errors(review, "benchmark-review.schema.json")

    required = {
        "catalog": catalog_path,
        "split": split_path,
        "holdout Pack": holdout_pack_path,
        "holdout Selection": holdout_selection_path,
        "Lesson Content": lesson_content_path,
    }
    missing = [f"--{label.lower().replace(' ', '-')}" for label, path in required.items() if path is None]
    if missing:
        return review, ["full validation requires " + ", ".join(missing)]
    catalog = load_json(catalog_path, "catalog")
    split = load_json(split_path, "split")
    holdout_pack = load_json(holdout_pack_path, "holdout Pack")
    holdout_selection = load_json(holdout_selection_path, "holdout Selection")
    lesson_content, lesson_bytes = load_json_bytes(lesson_content_path, "Lesson Content")
    lesson_digest = hashlib.sha256(lesson_bytes).hexdigest()

    previous_review: dict[str, Any] | None = None
    previous_content: dict[str, Any] | None = None
    previous_digest: str | None = None
    previous_review_digest: str | None = None
    if review.get("review_round") == 2:
        if previous_review_path is None or previous_lesson_content_path is None:
            return review, ["Round 2 full validation requires --previous-review and --previous-lesson-content"]
        previous_review = load_json(previous_review_path, "previous Review")
        previous_content, previous_bytes = load_json_bytes(previous_lesson_content_path, "previous Lesson Content")
        previous_digest = hashlib.sha256(previous_bytes).hexdigest()
        previous_review_digest = sha256_file(previous_review_path)
    elif previous_review_path is not None or previous_lesson_content_path is not None:
        return review, ["Round 1 must not supply --previous-review or --previous-lesson-content"]

    selection_source_digest = previous_digest if review.get("review_round") == 2 else lesson_digest
    errors = validate_benchmark_review_payload(
        review,
        catalog=catalog,
        split=split,
        holdout_pack=holdout_pack,
        holdout_selection=holdout_selection,
        lesson_content=lesson_content,
        lesson_content_sha256=lesson_digest,
        holdout_selection_source_sha256=selection_source_digest or "",
        previous_review=previous_review,
        previous_review_sha256=previous_review_digest,
        previous_content_sha256=previous_digest,
    )
    if previous_review is not None and previous_content is not None and previous_digest is not None:
        previous_errors = validate_benchmark_review_payload(
            previous_review,
            catalog=catalog,
            split=split,
            holdout_pack=holdout_pack,
            holdout_selection=holdout_selection,
            lesson_content=previous_content,
            lesson_content_sha256=previous_digest,
            holdout_selection_source_sha256=previous_digest,
        )
        errors.extend(f"Round 1 full validation: {error}" for error in previous_errors)
    return review, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--split", type=Path)
    parser.add_argument("--holdout-pack", type=Path)
    parser.add_argument("--holdout-selection", type=Path)
    parser.add_argument("--lesson-content", type=Path)
    parser.add_argument("--previous-review", type=Path)
    parser.add_argument("--previous-lesson-content", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="schema/debug inspection only; not production acceptance evidence",
    )
    args = parser.parse_args(argv)
    try:
        full_args = (
            args.catalog, args.split, args.holdout_pack, args.holdout_selection,
            args.lesson_content, args.previous_review, args.previous_lesson_content,
        )
        if args.review_only and any(value is not None for value in full_args):
            raise ContractError("--review-only cannot be combined with provenance inputs")
        review, errors = validate_benchmark_review_file(
            args.review,
            catalog_path=args.catalog,
            split_path=args.split,
            holdout_pack_path=args.holdout_pack,
            holdout_selection_path=args.holdout_selection,
            lesson_content_path=args.lesson_content,
            previous_review_path=args.previous_review,
            previous_lesson_content_path=args.previous_lesson_content,
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
            "catalog_fingerprint": review.get("catalog_fingerprint"),
            "split_fingerprint": review.get("split_fingerprint"),
            "holdout_pack_fingerprint": review.get("holdout_pack_fingerprint"),
            "holdout_selection_sha256": review.get("holdout_selection_sha256"),
            "source_lesson_content_sha256": review.get("source_lesson_content_sha256"),
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
