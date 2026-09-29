"""Teacher Review Contract 1.0 validation for Lesson lifecycle sidecars."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any
import unicodedata

from lifecycle_digest import (
    LifecycleContractError,
    assert_distinct_safe_paths,
    read_json_object,
    schema_errors,
    semantic_fingerprint,
    sha256_bytes,
    sha256_file,
    timezone_aware_timestamp,
    validation_status,
)
from lifecycle_benchmark import validate_completed_benchmark_evidence


FINGERPRINT_EXCLUDED_FIELDS = {"reviewed_at", "review_fingerprint"}
BENCHMARK_DISPOSITIONS = {
    "BENCHMARK_REVIEW_COMPLETE", "BENCHMARK_PARTIAL", "BENCHMARK_UNAVAILABLE", "BENCHMARK_WAIVED_BY_USER"
}


def teacher_review_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(payload, excluded_fields=FINGERPRINT_EXCLUDED_FIELDS)


def _content_lesson_ids(content: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    lessons = content.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        return set(), ["Content JSON must contain a non-empty lessons array"]
    identifiers: set[str] = set()
    for index, lesson in enumerate(lessons):
        if not isinstance(lesson, Mapping) or not isinstance(lesson.get("lesson_id"), str) or not lesson["lesson_id"].strip():
            errors.append(f"Content lessons[{index}].lesson_id is missing")
            continue
        lesson_id = unicodedata.normalize("NFC", lesson["lesson_id"]).strip()
        if lesson_id in identifiers:
            errors.append(f"Content lessons contain duplicate lesson_id {lesson_id!r}")
        identifiers.add(lesson_id)
    return identifiers, errors


def _benchmark_evidence_errors(
    benchmark: Any,
    *,
    authorization_path: str | Path | None,
    review_path: str | Path | None,
    evidence_path: str | Path | None,
) -> list[str]:
    errors: list[str] = []
    if benchmark is None:
        return errors
    disposition = benchmark.get("disposition")
    checks: list[tuple[str, str | Path | None, str]] = []
    if disposition == "BENCHMARK_REVIEW_COMPLETE":
        checks.extend([
            ("authorization_sha256", authorization_path, "benchmark authorization"),
            ("review_sha256", review_path, "benchmark review"),
        ])
    elif disposition in {"BENCHMARK_PARTIAL", "BENCHMARK_UNAVAILABLE", "BENCHMARK_WAIVED_BY_USER"}:
        checks.append(("evidence_sha256", evidence_path, "benchmark evidence"))
    for field, path, label in checks:
        if path is None:
            errors.append(f"{disposition} requires the {label} file for byte verification")
            continue
        try:
            actual = sha256_file(path)
            if actual.casefold() != str(benchmark.get(field, "")).casefold():
                errors.append(f"benchmark.{field} does not match {label} file bytes")
        except LifecycleContractError as exc:
            errors.append(f"cannot verify {label}: {exc}")
    return errors


def validate_teacher_review_payload(
    payload: Mapping[str, Any],
    *,
    source_truth_manifest_sha256: str | None = None,
    content_sha256: str | None = None,
    content: Mapping[str, Any] | None = None,
    benchmark_authorization_path: str | Path | None = None,
    benchmark_review_path: str | Path | None = None,
    benchmark_evidence_path: str | Path | None = None,
    require_benchmark_bytes: bool = True,
) -> list[str]:
    errors = schema_errors(payload, "teacher-review.schema.json")
    if errors:
        return errors
    if not timezone_aware_timestamp(payload.get("reviewed_at")):
        errors.append("reviewed_at must include a timezone")
    for field in ("teacher_review_id", "pipeline_run_id", "decision_notes"):
        if not str(payload.get(field, "")).strip():
            errors.append(f"{field} must contain non-whitespace text")
    if payload.get("review_fingerprint", "").casefold() != teacher_review_fingerprint(payload):
        errors.append("review_fingerprint does not match canonical semantic content")
    if source_truth_manifest_sha256 is not None and payload.get("source_truth_manifest_sha256", "").casefold() != source_truth_manifest_sha256.casefold():
        errors.append("source_truth_manifest_sha256 is stale or does not match the bound manifest bytes")
    if content_sha256 is not None and payload.get("content_sha256", "").casefold() != content_sha256.casefold():
        errors.append("content_sha256 is stale or does not match the bound Content JSON bytes")
    selected_ids = [
        unicodedata.normalize("NFC", row.get("lesson_id", "")).strip()
        for row in payload.get("selected_lessons", [])
    ]
    if len(selected_ids) != len(set(selected_ids)):
        errors.append("selected_lessons contains duplicate lesson_id values")
    for index, row in enumerate(payload.get("selected_lessons", [])):
        for field in ("lesson_id", "notes"):
            if not str(row.get(field, "")).strip():
                errors.append(f"selected_lessons[{index}].{field} must contain non-whitespace text")
        for dimension in (
            "directly_teachable", "task_executable", "steps_operable",
            "evaluation_observable", "reflection_improvable",
        ):
            if not str(row.get(dimension, {}).get("notes", "")).strip():
                errors.append(f"selected_lessons[{index}].{dimension}.notes must contain evidence text")
    if content is not None:
        known_ids, content_errors = _content_lesson_ids(content)
        errors.extend(content_errors)
        unknown = sorted(set(selected_ids) - known_ids)
        if unknown:
            errors.append("selected_lessons references unknown Content lesson_id values: " + ", ".join(unknown))
    benchmark = payload.get("benchmark")
    if benchmark is not None and benchmark.get("disposition") not in BENCHMARK_DISPOSITIONS:
        errors.append("benchmark.disposition is not a supported Lifecycle 1.0 disposition")
    if isinstance(benchmark, Mapping) and benchmark.get("disposition") == "BENCHMARK_WAIVED_BY_USER":
        if not str(benchmark.get("waiver_reference") or "").strip():
            errors.append("BENCHMARK_WAIVED_BY_USER requires a non-empty waiver_reference")
    whole_course = payload.get("whole_course_review", {})
    for dimension in (
        "progression", "scope", "theory_practice_coherence", "repetition_template_risk", "difficulty_fit",
    ):
        if not str(whole_course.get(dimension, {}).get("notes", "")).strip():
            errors.append(f"whole_course_review.{dimension}.notes must contain evidence text")
    if not str(whole_course.get("overall_notes", "")).strip():
        errors.append("whole_course_review.overall_notes must contain evidence text")
    if require_benchmark_bytes:
        errors.extend(_benchmark_evidence_errors(
            benchmark,
            authorization_path=benchmark_authorization_path,
            review_path=benchmark_review_path,
            evidence_path=benchmark_evidence_path,
        ))
    return errors


def validate_teacher_review_files(
    review_path: str | Path,
    *,
    source_truth_path: str | Path,
    content_path: str | Path,
    benchmark_authorization_path: str | Path | None = None,
    benchmark_review_path: str | Path | None = None,
    benchmark_evidence_path: str | Path | None = None,
    require_approved: bool = False,
) -> tuple[dict[str, Any], bytes, list[str]]:
    distinct_paths: dict[str, str | Path] = {
        "teacher_review": review_path,
        "source_truth_manifest": source_truth_path,
        "lesson_content": content_path,
    }
    for label, path in (
        ("benchmark_authorization", benchmark_authorization_path),
        ("benchmark_review", benchmark_review_path),
        ("benchmark_evidence", benchmark_evidence_path),
    ):
        if path is not None:
            distinct_paths[label] = path
    assert_distinct_safe_paths(distinct_paths)
    review, review_raw = read_json_object(review_path, "teacher_review")
    _source_truth, source_truth_raw = read_json_object(source_truth_path, "source_truth_manifest")
    content, content_raw = read_json_object(content_path, "lesson_content")
    errors = validate_teacher_review_payload(
        review,
        source_truth_manifest_sha256=sha256_bytes(source_truth_raw),
        content_sha256=sha256_bytes(content_raw),
        content=content,
        benchmark_authorization_path=benchmark_authorization_path,
        benchmark_review_path=benchmark_review_path,
        benchmark_evidence_path=benchmark_evidence_path,
        require_benchmark_bytes=True,
    )
    benchmark = review.get("benchmark")
    if (
        require_approved
        and isinstance(benchmark, Mapping)
        and benchmark.get("disposition") == "BENCHMARK_REVIEW_COMPLETE"
    ):
        errors.extend(validate_completed_benchmark_evidence(
            benchmark,
            benchmark_authorization_path=benchmark_authorization_path,
            benchmark_review_path=benchmark_review_path,
            content=content,
            content_raw=content_raw,
        ))
    if require_approved and review.get("decision") not in {"APPROVED", "APPROVED_WITH_NOTES"}:
        errors.append("only APPROVED or APPROVED_WITH_NOTES can satisfy an approval authority check")
    return review, review_raw, errors


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("review", type=Path)
    validate.add_argument("--source-truth", type=Path, required=True)
    validate.add_argument("--content", type=Path, required=True)
    validate.add_argument("--benchmark-authorization", type=Path)
    validate.add_argument("--benchmark-review", type=Path)
    validate.add_argument("--benchmark-evidence", type=Path)
    validate.add_argument("--require-approved", action="store_true")
    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("review", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "fingerprint":
            payload, _raw = read_json_object(args.review, "teacher_review")
            print(teacher_review_fingerprint(payload))
            return 0
        review, raw, errors = validate_teacher_review_files(
            args.review,
            source_truth_path=args.source_truth,
            content_path=args.content,
            benchmark_authorization_path=args.benchmark_authorization,
            benchmark_review_path=args.benchmark_review,
            benchmark_evidence_path=args.benchmark_evidence,
            require_approved=args.require_approved,
        )
        self_errors = validate_teacher_review_payload(review, require_benchmark_bytes=False)
        status = validation_status(self_errors, errors)
    except LifecycleContractError as exc:
        errors = [str(exc)]
        raw = b""
        status = "INVALID"
    if errors:
        print(status)
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"VALID teacher_review_sha256={sha256_bytes(raw)} decision={review['decision']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
