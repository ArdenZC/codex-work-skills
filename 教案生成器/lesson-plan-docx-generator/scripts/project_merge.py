"""Validate per-project authoring results against one frozen full-course outline."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from package_common import canonical_json_sha256


def _decimal(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be numeric") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return number


def validate_project_merge(
    outline: list[Mapping[str, Any]],
    project_payloads: list[Mapping[str, Any]],
    *,
    course_case_facts_sha256: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    expected_by_project: dict[str, list[dict[str, Any]]] = {}
    for row in outline:
        expected_by_project.setdefault(str(row.get("unit", "")), []).append(dict(row))
    if not outline:
        errors.append("frozen outline must not be empty")
    ids = [str(row.get("lesson_id", "")) for row in outline]
    duplicates = sorted(value for value, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append("frozen outline has duplicate Lesson IDs: " + ", ".join(duplicates))

    received_by_project: dict[str, list[dict[str, Any]]] = {}
    returned_ids: list[str] = []
    for index, payload in enumerate(project_payloads):
        project_id = str(payload.get("project_id", ""))
        if course_case_facts_sha256 is not None and str(payload.get("course_case_facts_sha256", "")).upper() != course_case_facts_sha256.upper():
            errors.append(f"project {project_id} does not bind the frozen shared course case facts")
        if project_id not in expected_by_project:
            errors.append(f"project payload {index} has unknown project_id {project_id!r}")
            continue
        if project_id in received_by_project:
            errors.append(f"duplicate project result for {project_id}")
            continue
        lessons = payload.get("lessons")
        if not isinstance(lessons, list):
            errors.append(f"project {project_id} must return a lessons array")
            continue
        received_by_project[project_id] = [item for item in lessons if isinstance(item, dict)]
        expected_lesson_ids = [str(row.get("lesson_id")) for row in expected_by_project[project_id]]
        returned_lesson_ids = [str(item.get("lesson_id", "")) for item in lessons if isinstance(item, dict)]
        if returned_lesson_ids != expected_lesson_ids:
            errors.append(
                f"project {project_id} Lesson IDs must preserve frozen outline order: "
                f"expected {expected_lesson_ids}, got {returned_lesson_ids}"
            )
        scope_ids = {str(row.get("lesson_id")) for row in expected_by_project[project_id]}
        for lesson in lessons:
            if not isinstance(lesson, dict):
                errors.append(f"project {project_id} contains a non-object Lesson")
                continue
            lesson_id = str(lesson.get("lesson_id", ""))
            returned_ids.append(lesson_id)
            if lesson_id not in scope_ids:
                errors.append(f"project {project_id} returned Lesson {lesson_id} outside its frozen project scope")
            if str(lesson.get("unit", "")) != project_id:
                errors.append(f"Lesson {lesson_id} unit {lesson.get('unit')!r} conflicts with project {project_id!r}")
            expected = next((row for row in expected_by_project[project_id] if str(row.get("lesson_id")) == lesson_id), None)
            if expected:
                for field in ("task", "lesson_type", "hours", "theory_hours", "practice_hours"):
                    if lesson.get(field) != expected.get(field):
                        errors.append(f"Lesson {lesson_id}.{field} conflicts with the frozen outline")
        if payload.get("outline_sha256") != canonical_json_sha256(expected_by_project[project_id]):
            errors.append(f"project {project_id} was not bound to its frozen outline slice")

    missing_projects = sorted(set(expected_by_project) - set(received_by_project))
    if missing_projects:
        errors.append("missing project results: " + ", ".join(missing_projects))
    counts = Counter(returned_ids)
    duplicate_lessons = sorted(lesson_id for lesson_id, count in counts.items() if count > 1)
    if duplicate_lessons:
        errors.append("project merge returned duplicate Lesson IDs: " + ", ".join(duplicate_lessons))
    expected_ids = set(ids)
    missing_ids = sorted(expected_ids - set(returned_ids))
    extra_ids = sorted(set(returned_ids) - expected_ids)
    if missing_ids:
        errors.append("project merge omitted Lesson IDs: " + ", ".join(missing_ids))
    if extra_ids:
        errors.append("project merge includes unplanned Lesson IDs: " + ", ".join(extra_ids))

    outline_total = sum((_decimal(row.get("hours", 0), "outline.hours") for row in outline), Decimal("0"))
    outline_theory = sum((_decimal(row.get("theory_hours", 0), "outline.theory_hours") for row in outline), Decimal("0"))
    outline_practice = sum((_decimal(row.get("practice_hours", 0), "outline.practice_hours") for row in outline), Decimal("0"))
    merged = [lesson for project in expected_by_project for lesson in received_by_project.get(project, [])]
    merged_total = sum((_decimal(row.get("hours", 0), "lesson.hours") for row in merged), Decimal("0"))
    merged_theory = sum((_decimal(row.get("theory_hours", 0), "lesson.theory_hours") for row in merged), Decimal("0"))
    merged_practice = sum((_decimal(row.get("practice_hours", 0), "lesson.practice_hours") for row in merged), Decimal("0"))
    if merged_total != outline_total or merged_theory != outline_theory or merged_practice != outline_practice:
        errors.append(
            f"project-hour mismatch: outline {outline_total}/{outline_theory}/{outline_practice}, "
            f"returned {merged_total}/{merged_theory}/{merged_practice} (total/theory/practice)"
        )

    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "duplicate_lesson_ids": duplicate_lessons,
        "project_scope_conflicts": [error for error in errors if "project scope" in error or "outside its frozen" in error or "conflicts with project" in error],
        "project_ids": list(expected_by_project),
        "frozen_outline_sha256": canonical_json_sha256(outline),
        "project_input_sha256": {
            project_id: canonical_json_sha256(rows)
            for project_id, rows in expected_by_project.items()
        },
        "project_output_sha256": {
            project_id: canonical_json_sha256(received_by_project.get(project_id, []))
            for project_id in expected_by_project
        },
        "merged_lesson_ids": [str(row.get("lesson_id")) for row in merged],
        "hours": {"total": str(merged_total), "theory": str(merged_theory), "practice": str(merged_practice)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outline", type=Path, required=True)
    parser.add_argument("--project", type=Path, action="append", required=True)
    parser.add_argument("--course-case-facts", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    outline_data = json.loads(args.outline.read_text(encoding="utf-8-sig"))
    outline = outline_data.get("outline") if isinstance(outline_data, dict) else outline_data
    payloads = [json.loads(path.read_text(encoding="utf-8-sig")) for path in args.project]
    facts_sha = None
    if args.course_case_facts:
        import hashlib

        facts_sha = hashlib.sha256(args.course_case_facts.read_bytes()).hexdigest().upper()
    report = validate_project_merge(outline, payloads, course_case_facts_sha256=facts_sha)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
