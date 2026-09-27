"""Build and validate lesson-sharded Teaching Exemplar Benchmark reviews."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from exemplar_contract import (
    ContractError,
    HEX_SHA256,
    assert_distinct_file_paths,
    canonical_json_bytes,
    holdout_selection_sha256,
    load_json,
    load_json_bytes,
    schema_errors,
    sha256_file,
    validate_catalog_course_context,
    validate_catalog_payload,
    validate_authoring_selection_payload,
    validate_holdout_selection_payload,
    validate_pack_payload,
    write_json_atomic,
)
from exemplar_split import validate_split_payload

RUBRIC_VERSION = "lesson-teaching-benchmark-v1"
DIMENSION_IDS = (
    "source_truth_alignment", "learner_analysis", "objective_quality", "content_selection",
    "key_difficult_point_resolution", "teacher_action_quality", "student_cognitive_activity",
    "learning_evidence", "objective_activity_evidence_assessment_alignment",
    "authentic_vocational_context", "differentiation_scaffold", "interaction_deep_learning",
    "assessment_quality", "progression_capacity", "teacher_usability",
)
NOT_APPLICABLE_ALLOWLIST = frozenset({"authentic_vocational_context", "differentiation_scaffold"})
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


def _final_content_sha256(lesson_content: Mapping[str, Any]) -> str | None:
    provenance = lesson_content.get("authoring_provenance")
    value = provenance.get("final_content_sha256") if isinstance(provenance, Mapping) else None
    return value if isinstance(value, str) and HEX_SHA256.fullmatch(value) else None


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
    return {str(row.get("lesson_id")): row for row in rows if isinstance(row.get("lesson_id"), str) and row.get("lesson_id")}


def _validate_dimension(dimension: Mapping[str, Any], lesson_id: str, selected_ids: set[str], holdout_ids: set[str]) -> list[str]:
    errors: list[str] = []
    dimension_id = str(dimension.get("dimension"))
    status = dimension.get("status")
    basis = dimension.get("evidence_basis")
    severity = dimension.get("severity")
    prefix = f"Lesson {lesson_id} dimension {dimension_id}"
    if severity not in DIMENSION_SEVERITY.get(str(status), set()):
        errors.append(f"{prefix} has severity inconsistent with status")
    if any(len(dimension.get(field, "")) > 600 for field in ("current_evidence", "benchmark_pattern", "gap", "recommended_direction", "insufficiency_reason")):
        errors.append(f"{prefix} exceeds the 600-character evidence prose budget")
    if dimension_id == "source_truth_alignment":
        if basis != "SOURCE_TRUTH":
            errors.append(f"{prefix} evidence_basis must be SOURCE_TRUTH")
        if not dimension.get("source_truth_evidence"):
            errors.append(f"{prefix} requires non-empty source_truth_evidence")
        if dimension.get("benchmark_pattern"):
            errors.append(f"{prefix} benchmark_pattern must be empty; exemplars are not source truth")
        if dimension.get("holdout_exemplar_ids"):
            errors.append(f"{prefix} holdout_exemplar_ids must be empty; exemplars are not source truth")
    else:
        if basis == "SOURCE_TRUTH":
            errors.append(f"{prefix} cannot use SOURCE_TRUTH without the source_truth_alignment dimension")
        if basis == "SOURCE_TRUTH_AND_HOLDOUT" and not dimension.get("source_truth_evidence"):
            errors.append(f"{prefix} SOURCE_TRUTH_AND_HOLDOUT requires source_truth_evidence")
        if basis != "SOURCE_TRUTH_AND_HOLDOUT" and dimension.get("source_truth_evidence"):
            errors.append(f"{prefix} source_truth_evidence requires SOURCE_TRUTH_AND_HOLDOUT")

    citations = set(dimension.get("holdout_exemplar_ids", []))
    if not citations <= holdout_ids:
        errors.append(f"{prefix} cites exemplar outside Holdout Pack")
    if not citations <= selected_ids:
        errors.append(f"{prefix} cites exemplar outside this Lesson's Holdout Selection")

    if status == "NOT_APPLICABLE":
        if dimension_id not in NOT_APPLICABLE_ALLOWLIST:
            errors.append(f"{prefix} NOT_APPLICABLE is forbidden by NOT_APPLICABLE_ALLOWLIST")
        if basis != "LESSON_INTERNAL" or citations or dimension.get("source_truth_evidence"):
            errors.append(f"{prefix} NOT_APPLICABLE requires LESSON_INTERNAL evidence and no citations")
        if not _nonempty(dimension.get("current_evidence")):
            errors.append(f"{prefix} NOT_APPLICABLE requires a non-empty explanation")
        return errors

    if status == "INSUFFICIENT_EVIDENCE":
        for field in ("current_evidence", "gap", "recommended_direction", "insufficiency_reason"):
            if not _nonempty(dimension.get(field)):
                errors.append(f"{prefix} INSUFFICIENT_EVIDENCE requires non-empty {field}")
        has_pattern = _nonempty(dimension.get("benchmark_pattern"))
        if basis == "HOLDOUT_EXEMPLAR" and bool(citations) != has_pattern:
            errors.append(f"{prefix} HOLDOUT_EXEMPLAR insufficiency requires both a selected citation and benchmark_pattern, or neither")
        if basis == "SOURCE_TRUTH_AND_HOLDOUT" and citations and not has_pattern:
            errors.append(f"{prefix} HOLDOUT citation requires a non-empty benchmark_pattern")
        if basis == "LESSON_INTERNAL" and (
            citations or has_pattern or dimension.get("source_truth_evidence")
        ):
            errors.append(f"{prefix} LESSON_INTERNAL insufficiency must not include Holdout or source-truth evidence")
        return errors

    if status not in {"MEETS", "PARTIAL", "GAP"}:
        return errors
    if not _nonempty(dimension.get("current_evidence")):
        errors.append(f"{prefix} {status} requires non-empty current_evidence")
    if status in {"PARTIAL", "GAP"}:
        for field in ("gap", "recommended_direction"):
            if not _nonempty(dimension.get(field)):
                errors.append(f"{prefix} {status} requires non-empty {field}")
    if dimension_id != "source_truth_alignment":
        if basis in {"HOLDOUT_EXEMPLAR", "SOURCE_TRUTH_AND_HOLDOUT"}:
            if not _nonempty(dimension.get("benchmark_pattern")) or not citations:
                errors.append(f"{prefix} {basis} requires a benchmark pattern and selected Holdout citation")
        elif basis == "LESSON_INTERNAL" and (dimension.get("benchmark_pattern") or citations):
            errors.append(f"{prefix} LESSON_INTERNAL evidence must not cite or describe a Holdout exemplar")
    return errors


def review_summary_for(
    lesson_reviews: Sequence[Mapping[str, Any]],
    selection_by_lesson: Mapping[str, Mapping[str, Any]],
    *,
    review_round: int,
    benchmark_availability: str,
    context_mode: str = "separate_contexts",
    authoring_availability: str = "AVAILABLE",
    holdout_availability: str | None = None,
) -> dict[str, Any]:
    major = minor = insufficient = reviewed = without_holdout = no_relevant = 0
    has_gap = False
    for lesson in lesson_reviews:
        lesson_id = str(lesson.get("lesson_id"))
        selection = selection_by_lesson.get(lesson_id, {})
        selected = selection.get("status") == "SELECTED" and bool(selection.get("exemplar_ids"))
        if selected:
            reviewed += 1
        else:
            without_holdout += 1
            if selection.get("status") == "NO_RELEVANT_EXEMPLAR":
                no_relevant += 1
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

    holdout_availability = holdout_availability or benchmark_availability
    if holdout_availability == "UNAVAILABLE":
        decision = "BENCHMARK_UNAVAILABLE"
    elif review_round == 2 and major:
        decision = "HUMAN_REVIEW_REQUIRED"
    elif major:
        decision = "REVISION_REQUIRED"
    elif insufficient:
        decision = "HUMAN_REVIEW_REQUIRED"
    elif reviewed == 0:
        # A non-empty B Pack with no relevant lesson selection needs a human
        # explanation; it is not the same as having no exemplar source.
        decision = "HUMAN_REVIEW_REQUIRED"
    elif holdout_availability == "PARTIAL" or without_holdout:
        decision = "BENCHMARK_PARTIAL"
    elif context_mode == "single_context":
        decision = "BENCHMARK_PARTIAL"
    else:
        decision = "NO_REVISION_REQUIRED"

    if decision == "BENCHMARK_UNAVAILABLE":
        status = "BENCHMARK_UNAVAILABLE"
    elif decision == "HUMAN_REVIEW_REQUIRED":
        status = "BENCHMARK_PARTIAL" if reviewed == 0 else "HUMAN_REVIEW_REQUIRED"
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
        "no_relevant_holdout_lesson_count": no_relevant,
        "context_mode": context_mode,
        "authoring_availability": authoring_availability,
        "holdout_availability": holdout_availability,
        "decision": decision,
        "status": status,
    }


def _file_digest_for_payload(review: Mapping[str, Any]) -> str:
    raw = (json.dumps(review, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_lesson_reviews(directory: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if directory.is_symlink() or not directory.is_dir():
        raise ContractError(f"per-Lesson review directory is missing or symbolic: {directory}")
    reviews: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
            raise ContractError(f"per-Lesson review directory may contain only normal .json files: {path}")
        review, raw = load_json_bytes(path, f"per-Lesson review {path.name}")
        lesson_id = review.get("lesson_id")
        if not isinstance(lesson_id, str) or not lesson_id or path.stem != lesson_id:
            raise ContractError(f"per-Lesson review filename must match lesson_id: {path.name}")
        if lesson_id in digests:
            raise ContractError(f"duplicate per-Lesson review for {lesson_id}")
        reviews.append(review)
        digests[lesson_id] = hashlib.sha256(raw).hexdigest()
    return reviews, digests


def validate_benchmark_review_payload(
    review: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    holdout_pack: Mapping[str, Any],
    holdout_selection: Mapping[str, Any],
    authoring_pack: Mapping[str, Any] | None = None,
    authoring_selection: Mapping[str, Any] | None = None,
    lesson_content: Mapping[str, Any],
    lesson_content_sha256: str,
    holdout_selection_source_sha256: str,
    lesson_reviews: Sequence[Mapping[str, Any]],
    lesson_review_sha256: Mapping[str, str],
    previous_review: Mapping[str, Any] | None = None,
    previous_review_sha256: str | None = None,
    previous_content: Mapping[str, Any] | None = None,
    previous_content_sha256: str | None = None,
) -> list[str]:
    errors = schema_errors(review, "benchmark-review.schema.json")
    if errors:
        return errors
    if review["rubric_version"] != RUBRIC_VERSION:
        errors.append(f"rubric_version must be {RUBRIC_VERSION}")
    mode = review["isolation"]["context_mode"]
    if mode == "separate_contexts" and not all(review["isolation"].get(key) is value for key, value in (
        ("authoring_exemplars_visible", False), ("author_reasoning_visible", False), ("holdout_only", True),
    )):
        errors.append("separate_contexts requires isolated holdout attestation")
    if mode == "single_context" and not all(review["isolation"].get(key) is value for key, value in (
        ("authoring_exemplars_visible", True), ("holdout_only", False),
    )):
        errors.append("single_context must not claim blind Holdout isolation")
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
    if authoring_pack is not None or authoring_selection is not None:
        if authoring_pack is None or authoring_selection is None:
            errors.append("Authoring Pack and Authoring Selection must be supplied together")
        else:
            authoring_pack_errors = validate_pack_payload(
                authoring_pack, catalog, split, expected_role="authoring"
            )
            errors.extend(f"authoring Pack: {error}" for error in authoring_pack_errors)
            if not authoring_pack_errors:
                errors.extend(validate_authoring_selection_payload(
                    authoring_selection, catalog, split, authoring_pack, lesson_content
                ))
    selection_errors = validate_holdout_selection_payload(
        holdout_selection, catalog, split, holdout_pack, lesson_content,
        lesson_content_sha256=holdout_selection_source_sha256,
    )
    errors.extend(f"holdout Selection: {error}" for error in selection_errors)
    if selection_errors:
        return errors

    for field, expected in (
        ("catalog_id", catalog["catalog_id"]),
        ("catalog_fingerprint", catalog["catalog_fingerprint"]),
        ("split_id", split["split_id"]),
        ("split_fingerprint", split["split_fingerprint"]),
        ("holdout_pack_fingerprint", holdout_pack["pack_fingerprint"]),
        ("benchmark_availability", split["benchmark_availability"]),
    ):
        actual = review[field]
        if str(actual).casefold() != str(expected).casefold():
            errors.append(f"review.{field} does not match supplied evidence")
    if review["holdout_selection_sha256"].casefold() != holdout_selection_sha256(holdout_selection).casefold():
        errors.append("holdout_selection_sha256 does not match canonical Holdout Selection payload")

    lesson_ids = _source_lesson_ids(lesson_content)
    if len(lesson_ids) != len(lesson_content.get("lessons", [])):
        errors.append("Lesson Content must have a non-empty lesson_id on every Lesson")
    selection_rows = holdout_selection["lessons"]
    selection_by_id = _exact_ids("Holdout Selection", selection_rows, lesson_ids, errors)
    review_meta = review["lesson_reviews"]
    review_meta_by_id = _exact_ids("Course Review references", review_meta, lesson_ids, errors)
    lesson_review_by_id = _exact_ids("Per-Lesson Reviews", list(lesson_reviews), lesson_ids, errors)
    if review["lesson_review_count"] != len(lesson_reviews) or review["lesson_review_count"] != len(lesson_ids):
        errors.append("lesson_review_count must equal exact Lesson Content coverage")
    holdout_pack_ids = set(holdout_pack["exemplar_ids"])
    for lesson_id in lesson_ids:
        sidecar = lesson_review_by_id.get(lesson_id)
        meta = review_meta_by_id.get(lesson_id)
        selection = selection_by_id.get(lesson_id)
        if sidecar is None or meta is None or selection is None:
            continue
        file_sha = lesson_review_sha256.get(lesson_id)
        if not isinstance(file_sha, str) or meta.get("review_sha256", "").casefold() != file_sha.casefold():
            errors.append(f"Course Review SHA does not match per-Lesson Review {lesson_id}")
        schema_errors_for_lesson = schema_errors(sidecar, "benchmark-lesson-review.schema.json")
        errors.extend(f"{lesson_id}: {error}" for error in schema_errors_for_lesson)
        if schema_errors_for_lesson:
            continue
        for field, expected in (
            ("benchmark_contract_version", "1.0"),
            ("benchmark_run_id", review["benchmark_run_id"]),
            ("review_round", review["review_round"]),
            ("source_lesson_content_sha256", lesson_content_sha256),
            ("lesson_id", lesson_id),
        ):
            if sidecar.get(field) != expected:
                errors.append(f"Per-Lesson Review {lesson_id} {field} does not match the course run")
        selected_ids = list(selection["exemplar_ids"])
        if sidecar["selected_holdout_exemplar_ids"] != selected_ids:
            errors.append(f"Per-Lesson Review {lesson_id} selected Holdout IDs do not match Selection")
        dimensions = sidecar["dimensions"]
        if selected_ids:
            observed = [dimension["dimension"] for dimension in dimensions]
            if len(observed) != len(DIMENSION_IDS) or set(observed) != set(DIMENSION_IDS):
                errors.append(f"Lesson {lesson_id} requires each of the 15 rubric dimensions exactly once")
        elif dimensions:
            errors.append(f"Lesson {lesson_id} has no relevant Holdout selection and must have no Review dimensions")
        if len({dimension.get("dimension") for dimension in dimensions}) != len(dimensions):
            errors.append(f"Lesson {lesson_id} Review dimension IDs must be unique")
        for dimension in dimensions:
            errors.extend(_validate_dimension(dimension, lesson_id, set(selected_ids), holdout_pack_ids))

    summary = review_summary_for(
        lesson_reviews,
        selection_by_id,
        review_round=review["review_round"],
        benchmark_availability=review["benchmark_availability"],
        context_mode=mode,
        authoring_availability=split["authoring_availability"],
        holdout_availability=split["holdout_availability"],
    )
    for field, value in summary.items():
        if review["course_summary"].get(field) != value:
            errors.append(f"course_summary.{field} does not match deterministic aggregation")
    if review["status"] != summary["status"]:
        errors.append("status does not match deterministic aggregation")

    if review["review_round"] == 1:
        if any(value is not None for value in (previous_review, previous_review_sha256, previous_content, previous_content_sha256)):
            errors.append("Round 1 must not supply prior Review or Lesson Content")
        if holdout_selection["source_lesson_content_sha256"].casefold() != lesson_content_sha256.casefold():
            errors.append("Round 1 Holdout Selection must bind current Lesson Content bytes")
    else:
        if any(value is None for value in (previous_review, previous_review_sha256, previous_content, previous_content_sha256)):
            errors.append("Round 2 requires fully validated Round 1 Review and Lesson snapshot")
        else:
            if review.get("prior_review_sha256", "").casefold() != str(previous_review_sha256).casefold():
                errors.append("prior_review_sha256 does not match the Round 1 Review file")
            if review.get("prior_source_lesson_content_sha256", "").casefold() != str(previous_content_sha256).casefold():
                errors.append("prior_source_lesson_content_sha256 does not match the Round 1 Lesson bytes")
            if holdout_selection["source_lesson_content_sha256"].casefold() != str(previous_content_sha256).casefold():
                errors.append("Round 2 must retain the Holdout Selection bound to Round 1 Lesson Content")
            if review["source_lesson_content_sha256"].casefold() == str(previous_content_sha256).casefold():
                errors.append("Round 2 current Lesson Content bytes must differ from Round 1")
            if previous_review.get("review_round") != 1:
                errors.append("previous Review must have review_round=1")
            if previous_review.get("benchmark_run_id") != review.get("benchmark_run_id"):
                errors.append("Round 2 benchmark_run_id must remain fixed from Round 1")
            prior_summary = previous_review.get("course_summary")
            if not isinstance(prior_summary, Mapping) or prior_summary.get("decision") != "REVISION_REQUIRED":
                errors.append("Round 2 is only valid after a Round 1 REVISION_REQUIRED decision")
            if previous_review.get("source_lesson_content_sha256", "").casefold() != str(previous_content_sha256).casefold():
                errors.append("Round 1 Review source digest does not match its Lesson snapshot")
            for field in ("catalog_id", "catalog_fingerprint", "split_id", "split_fingerprint", "holdout_pack_fingerprint", "holdout_selection_sha256", "rubric_version"):
                if review[field] != previous_review.get(field):
                    errors.append(f"Round 2 {field} must remain fixed from Round 1")
            prior_final = _final_content_sha256(previous_content)
            current_final = _final_content_sha256(lesson_content)
            if prior_final is None or current_final is None:
                errors.append("Round 2 requires valid prior/current authoring_provenance.final_content_sha256")
            else:
                if review.get("prior_final_content_sha256", "").casefold() != prior_final.casefold():
                    errors.append("prior_final_content_sha256 does not match Round 1 semantic content digest")
                if review.get("current_final_content_sha256", "").casefold() != current_final.casefold():
                    errors.append("current_final_content_sha256 does not match current semantic content digest")
                if prior_final.casefold() == current_final.casefold():
                    errors.append("Round 2 semantic final_content_sha256 must differ from Round 1")
    return errors


def build_course_review_payload(
    *,
    benchmark_run_id: str,
    review_round: int,
    context_mode: str,
    isolation: Mapping[str, Any],
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    holdout_pack: Mapping[str, Any],
    holdout_selection: Mapping[str, Any],
    lesson_content: Mapping[str, Any],
    lesson_content_sha256: str,
    lesson_reviews: Sequence[Mapping[str, Any]],
    lesson_review_sha256: Mapping[str, str],
    previous_review: Mapping[str, Any] | None = None,
    previous_review_sha256: str | None = None,
    previous_content: Mapping[str, Any] | None = None,
    previous_content_sha256: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    lesson_ids = _source_lesson_ids(lesson_content)
    selection_by_id = {row["lesson_id"]: row for row in holdout_selection.get("lessons", []) if isinstance(row, Mapping) and isinstance(row.get("lesson_id"), str)}
    lesson_review_by_id = {row["lesson_id"]: row for row in lesson_reviews if isinstance(row, Mapping) and isinstance(row.get("lesson_id"), str)}
    if set(lesson_review_by_id) != set(lesson_ids) or len(lesson_review_by_id) != len(lesson_reviews):
        errors.append("per-Lesson Reviews must exactly cover Lesson Content")
    rows = [
        {"lesson_id": lesson_id, "review_sha256": lesson_review_sha256.get(lesson_id, _file_digest_for_payload(lesson_review_by_id.get(lesson_id, {})))}
        for lesson_id in lesson_ids
    ]
    context_mode = context_mode.strip()
    summary = review_summary_for(
        list(lesson_review_by_id.values()),
        selection_by_id,
        review_round=review_round,
        benchmark_availability=str(split.get("benchmark_availability")),
        context_mode=context_mode,
        authoring_availability=str(split.get("authoring_availability")),
        holdout_availability=str(split.get("holdout_availability")),
    )
    review: dict[str, Any] = {
        "benchmark_contract_version": "1.0",
        "benchmark_run_id": benchmark_run_id,
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_id": split["split_id"],
        "split_fingerprint": split["split_fingerprint"],
        "holdout_pack_fingerprint": holdout_pack["pack_fingerprint"],
        "benchmark_availability": split["benchmark_availability"],
        "source_lesson_content_sha256": lesson_content_sha256,
        "holdout_selection_sha256": holdout_selection_sha256(holdout_selection),
        "rubric_version": RUBRIC_VERSION,
        "review_round": review_round,
        "status": summary["status"],
        "isolation": {
            "context_mode": context_mode,
            "authoring_exemplars_visible": isolation.get("authoring_exemplars_visible"),
            "author_reasoning_visible": isolation.get("author_reasoning_visible"),
            "holdout_only": isolation.get("holdout_only"),
        },
        "lesson_review_count": len(rows),
        "lesson_reviews": rows,
        "course_summary": summary,
    }
    if review_round == 2 and previous_review is not None and previous_content is not None:
        review["prior_review_sha256"] = previous_review_sha256
        review["prior_source_lesson_content_sha256"] = previous_content_sha256
        review["prior_final_content_sha256"] = _final_content_sha256(previous_content)
        review["current_final_content_sha256"] = _final_content_sha256(lesson_content)
    return review, errors


def _validate_round_one_inputs(
    previous_review_path: Path,
    previous_lesson_reviews_dir: Path,
    previous_lesson_content_path: Path,
    *,
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    holdout_pack: Mapping[str, Any],
    holdout_selection: Mapping[str, Any],
    authoring_pack: Mapping[str, Any],
    authoring_selection: Mapping[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], bytes, list[dict[str, Any]], dict[str, str], list[str]]:
    previous_review = load_json(previous_review_path, "previous Review")
    previous_content, previous_bytes = load_json_bytes(previous_lesson_content_path, "previous Lesson Content")
    previous_reviews, previous_hashes = _load_lesson_reviews(previous_lesson_reviews_dir)
    previous_digest = hashlib.sha256(previous_bytes).hexdigest()
    errors = validate_benchmark_review_payload(
        previous_review,
        catalog=catalog, split=split, holdout_pack=holdout_pack,
        holdout_selection=holdout_selection, authoring_pack=authoring_pack,
        authoring_selection=authoring_selection, lesson_content=previous_content,
        lesson_content_sha256=previous_digest, holdout_selection_source_sha256=previous_digest,
        lesson_reviews=previous_reviews, lesson_review_sha256=previous_hashes,
    )
    return previous_review, sha256_file(previous_review_path), previous_content, previous_bytes, previous_reviews, previous_hashes, errors


def validate_benchmark_review_file(
    review_path: Path,
    *,
    catalog_path: Path | None = None,
    split_path: Path | None = None,
    holdout_pack_path: Path | None = None,
    holdout_selection_path: Path | None = None,
    authoring_pack_path: Path | None = None,
    authoring_selection_path: Path | None = None,
    lesson_content_path: Path | None = None,
    lesson_reviews_dir: Path | None = None,
    previous_review_path: Path | None = None,
    previous_lesson_reviews_dir: Path | None = None,
    previous_lesson_content_path: Path | None = None,
    require_full_linkage: bool = True,
    report_path: Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    review = load_json(review_path, "benchmark course review")
    if not require_full_linkage:
        return review, schema_errors(review, "benchmark-review.schema.json")
    required = {
        "catalog": catalog_path, "split": split_path, "holdout Pack": holdout_pack_path,
        "holdout Selection": holdout_selection_path, "authoring Pack": authoring_pack_path,
        "authoring Selection": authoring_selection_path, "Lesson Content": lesson_content_path,
        "per-Lesson Reviews": lesson_reviews_dir,
    }
    missing = [f"--{label.lower().replace(' ', '-')}" for label, path in required.items() if path is None]
    if missing:
        return review, ["full validation requires " + ", ".join(missing)]
    input_paths: dict[str, Path] = {
        "review": review_path, "catalog": catalog_path, "split": split_path,
        "holdout Pack": holdout_pack_path, "holdout Selection": holdout_selection_path,
        "authoring Pack": authoring_pack_path, "authoring Selection": authoring_selection_path,
        "Lesson Content": lesson_content_path, "per-Lesson Reviews": lesson_reviews_dir,
    }
    if previous_review_path is not None:
        input_paths["previous Review"] = previous_review_path
    if previous_lesson_reviews_dir is not None:
        input_paths["previous per-Lesson Reviews"] = previous_lesson_reviews_dir
    if previous_lesson_content_path is not None:
        input_paths["previous Lesson Content"] = previous_lesson_content_path
    assert_distinct_file_paths(input_paths)
    if report_path is not None:
        assert_distinct_file_paths({**input_paths, "report": report_path}, outputs={"report"})

    catalog = load_json(catalog_path, "catalog")
    split = load_json(split_path, "split")
    holdout_pack = load_json(holdout_pack_path, "holdout Pack")
    holdout_selection = load_json(holdout_selection_path, "holdout Selection")
    authoring_pack = load_json(authoring_pack_path, "authoring Pack")
    authoring_selection = load_json(authoring_selection_path, "authoring Selection")
    lesson_content, lesson_bytes = load_json_bytes(lesson_content_path, "Lesson Content")
    lesson_digest = hashlib.sha256(lesson_bytes).hexdigest()
    lesson_reviews, lesson_hashes = _load_lesson_reviews(lesson_reviews_dir)

    previous_review = None
    previous_review_digest = None
    previous_content = None
    previous_content_digest = None
    errors: list[str] = []
    if review.get("review_round") == 2:
        if previous_review_path is None or previous_lesson_reviews_dir is None or previous_lesson_content_path is None:
            return review, ["Round 2 full validation requires --previous-review, --previous-lesson-reviews-dir, and --previous-lesson-content"]
        (
            previous_review, previous_review_digest, previous_content, previous_bytes,
            _previous_reviews, _previous_hashes, previous_errors,
        ) = _validate_round_one_inputs(
            previous_review_path, previous_lesson_reviews_dir, previous_lesson_content_path,
            catalog=catalog, split=split, holdout_pack=holdout_pack, holdout_selection=holdout_selection,
            authoring_pack=authoring_pack, authoring_selection=authoring_selection,
        )
        previous_content_digest = hashlib.sha256(previous_bytes).hexdigest()
        errors.extend(f"Round 1 full validation: {error}" for error in previous_errors)
    elif any(path is not None for path in (previous_review_path, previous_lesson_reviews_dir, previous_lesson_content_path)):
        return review, ["Round 1 must not supply previous Review or Lesson Content"]

    selection_source_digest = previous_content_digest if review.get("review_round") == 2 else lesson_digest
    errors.extend(validate_benchmark_review_payload(
        review,
        catalog=catalog, split=split, holdout_pack=holdout_pack,
        holdout_selection=holdout_selection, authoring_pack=authoring_pack,
        authoring_selection=authoring_selection, lesson_content=lesson_content,
        lesson_content_sha256=lesson_digest,
        holdout_selection_source_sha256=selection_source_digest or "",
        lesson_reviews=lesson_reviews, lesson_review_sha256=lesson_hashes,
        previous_review=previous_review,
        previous_review_sha256=previous_review_digest,
        previous_content=previous_content,
        previous_content_sha256=previous_content_digest,
    ))
    if errors:
        return review, errors
    return review, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aggregate", action="store_true", help="deterministically aggregate lesson-sharded review files")
    parser.add_argument("--review", type=Path, help="course summary to validate")
    parser.add_argument("--output", type=Path, help="course summary output used with --aggregate")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--split", type=Path)
    parser.add_argument("--holdout-pack", type=Path)
    parser.add_argument("--holdout-selection", type=Path)
    parser.add_argument("--authoring-pack", type=Path)
    parser.add_argument("--authoring-selection", type=Path)
    parser.add_argument("--lesson-content", type=Path)
    parser.add_argument("--lesson-reviews-dir", type=Path)
    parser.add_argument("--previous-review", type=Path)
    parser.add_argument("--previous-lesson-reviews-dir", type=Path)
    parser.add_argument("--previous-lesson-content", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--review-round", type=int, choices=(1, 2))
    parser.add_argument("--context-mode", choices=("separate_contexts", "single_context"))
    parser.add_argument("--report", type=Path, help="atomically write a compact validation report")
    parser.add_argument("--review-only", action="store_true", help="schema/debug inspection only; not acceptance evidence")
    args = parser.parse_args(argv)
    try:
        if args.aggregate:
            required = (args.output, args.catalog, args.split, args.holdout_pack, args.holdout_selection,
                        args.authoring_pack, args.authoring_selection,
                        args.lesson_content, args.lesson_reviews_dir, args.run_id, args.review_round, args.context_mode)
            if any(value is None for value in required):
                raise ContractError("--aggregate requires --output, all full-linkage inputs, --run-id, --review-round, and --context-mode")
            catalog = load_json(args.catalog, "catalog")
            split = load_json(args.split, "split")
            holdout_pack = load_json(args.holdout_pack, "holdout Pack")
            selection = load_json(args.holdout_selection, "holdout Selection")
            authoring_pack = load_json(args.authoring_pack, "authoring Pack")
            authoring_selection = load_json(args.authoring_selection, "authoring Selection")
            content, content_bytes = load_json_bytes(args.lesson_content, "Lesson Content")
            content_digest = hashlib.sha256(content_bytes).hexdigest()
            reviews, hashes = _load_lesson_reviews(args.lesson_reviews_dir)
            previous_review = None
            previous_review_digest = None
            previous_content = None
            previous_content_digest = None
            errors: list[str] = []
            if args.review_round == 2:
                if not all((args.previous_review, args.previous_lesson_reviews_dir, args.previous_lesson_content)):
                    raise ContractError("Round 2 aggregation requires --previous-review, --previous-lesson-reviews-dir, and --previous-lesson-content")
                (
                    previous_review, previous_review_digest, previous_content, previous_bytes,
                    _prior_reviews, _prior_hashes, prior_errors,
                ) = _validate_round_one_inputs(
                    args.previous_review, args.previous_lesson_reviews_dir, args.previous_lesson_content,
                    catalog=catalog, split=split, holdout_pack=holdout_pack, holdout_selection=selection,
                    authoring_pack=authoring_pack, authoring_selection=authoring_selection,
                )
                previous_content_digest = hashlib.sha256(previous_bytes).hexdigest()
                errors.extend(prior_errors)
            review, build_errors = build_course_review_payload(
                benchmark_run_id=args.run_id,
                review_round=args.review_round,
                context_mode=args.context_mode,
                isolation=(
                    {"authoring_exemplars_visible": False, "author_reasoning_visible": False, "holdout_only": True}
                    if args.context_mode == "separate_contexts"
                    else {"authoring_exemplars_visible": True, "author_reasoning_visible": True, "holdout_only": False}
                ),
                catalog=catalog, split=split, holdout_pack=holdout_pack,
                holdout_selection=selection, lesson_content=content,
                lesson_content_sha256=content_digest, lesson_reviews=reviews,
                lesson_review_sha256=hashes,
                previous_review=previous_review,
                previous_review_sha256=previous_review_digest,
                previous_content=previous_content,
                previous_content_sha256=previous_content_digest,
            )
            errors.extend(build_errors)
            errors.extend(validate_benchmark_review_payload(
                review, catalog=catalog, split=split, holdout_pack=holdout_pack,
                holdout_selection=selection, authoring_pack=authoring_pack,
                authoring_selection=authoring_selection, lesson_content=content,
                lesson_content_sha256=content_digest,
                holdout_selection_source_sha256=previous_content_digest or content_digest,
                lesson_reviews=reviews, lesson_review_sha256=hashes,
                previous_review=previous_review, previous_review_sha256=previous_review_digest,
                previous_content=previous_content, previous_content_sha256=previous_content_digest,
            ))
            if errors:
                raise ContractError("course aggregation failed validation: " + "; ".join(errors))
            input_paths = {
                "catalog": args.catalog, "split": args.split, "holdout Pack": args.holdout_pack,
                "holdout Selection": args.holdout_selection, "authoring Pack": args.authoring_pack,
                "authoring Selection": args.authoring_selection, "Lesson Content": args.lesson_content,
                "per-Lesson Reviews": args.lesson_reviews_dir,
            }
            if args.review_round == 2:
                input_paths.update({
                    "previous Review": args.previous_review,
                    "previous per-Lesson Reviews": args.previous_lesson_reviews_dir,
                    "previous Lesson Content": args.previous_lesson_content,
                })
            assert_distinct_file_paths({**input_paths, "output": args.output}, outputs={"output"})
            write_json_atomic(args.output, review)
            result = {
                "status": "PASS",
                "benchmark_status": review["status"],
                "decision": review["course_summary"]["decision"],
                "output": str(args.output),
                "lesson_review_count": len(reviews),
                "course_summary": review["course_summary"],
            }
        else:
            if args.review is None:
                raise ContractError("--review is required unless --aggregate is used")
            full_inputs = (
                args.catalog, args.split, args.holdout_pack, args.holdout_selection,
                args.authoring_pack, args.authoring_selection, args.lesson_content,
                args.lesson_reviews_dir, args.previous_review,
                args.previous_lesson_reviews_dir, args.previous_lesson_content,
            )
            if args.review_only and any(value is not None for value in full_inputs):
                raise ContractError("--review-only cannot be combined with provenance inputs")
            review, errors = validate_benchmark_review_file(
                args.review,
                catalog_path=args.catalog, split_path=args.split,
                holdout_pack_path=args.holdout_pack, holdout_selection_path=args.holdout_selection,
                authoring_pack_path=args.authoring_pack, authoring_selection_path=args.authoring_selection,
                lesson_content_path=args.lesson_content, lesson_reviews_dir=args.lesson_reviews_dir,
                previous_review_path=args.previous_review,
                previous_lesson_reviews_dir=args.previous_lesson_reviews_dir,
                previous_lesson_content_path=args.previous_lesson_content,
                require_full_linkage=not args.review_only, report_path=args.report,
            )
            if errors:
                raise ContractError("benchmark review validation failed: " + "; ".join(errors))
            result = {
                "status": "PASS",
                "benchmark_run_id": review["benchmark_run_id"],
                "benchmark_status": review["status"],
                "decision": review["course_summary"]["decision"],
                "course_summary": review["course_summary"],
            }
            if args.report:
                write_json_atomic(args.report, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
