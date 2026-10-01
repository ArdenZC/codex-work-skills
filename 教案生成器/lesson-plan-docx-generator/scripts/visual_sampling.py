"""Shared Acceptance 2.0 visual sampling policy; extraction preserves legacy output."""
from __future__ import annotations
import hashlib
import json
import math
import random
from pathlib import Path
from collections.abc import Mapping, Iterable
from typing import Any

def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _lesson_id(lesson: Mapping[str, Any], index: int) -> str:
    for key in ("id", "lesson_id", "code"):
        value = lesson.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return f"L{index:02d}"


def _value_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, Mapping):
        return sum(_value_chars(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return sum(_value_chars(item) for item in value)
    return len(str(value))


def _values_for_keys(value: Any, keys: set[str]) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in keys:
                yield item
            yield from _values_for_keys(item, keys)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _values_for_keys(item, keys)


def lesson_length_metrics(lessons: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return descriptive content lengths without imposing a difference threshold."""

    metrics: list[dict[str, Any]] = []
    for index, lesson in enumerate(lessons, start=1):
        teaching_content = lesson.get("teaching_content", {})
        implementation = lesson.get("implementation", {})
        evaluation = lesson.get("evaluation", {})
        reflection = lesson.get("reflection", {})
        teacher_actions = _value_chars(list(_values_for_keys(implementation, {"teacher_actions"})))
        student_actions = _value_chars(list(_values_for_keys(implementation, {"student_actions"})))
        evaluation_remarks = _value_chars(list(_values_for_keys(evaluation, {"remarks"})))
        row = {
            "lesson_id": _lesson_id(lesson, index),
            "teaching_content_chars": _value_chars(teaching_content),
            "teacher_actions_chars": teacher_actions,
            "student_actions_chars": student_actions,
            "evaluation_remarks_chars": evaluation_remarks,
            "reflection_chars": _value_chars(reflection),
        }
        row["implementation_chars"] = _value_chars(implementation)
        row["total_chars"] = sum(
            row[key]
            for key in (
                "teaching_content_chars",
                "implementation_chars",
                "evaluation_remarks_chars",
                "reflection_chars",
            )
        )
        metrics.append(row)
    return metrics


def _page_count_map(
    qa_report: Mapping[str, Any],
    artifact_manifest: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    if isinstance(artifact_manifest, Mapping) and isinstance(artifact_manifest.get("artifacts"), list):
        values: dict[str, int] = {}
        for item in artifact_manifest["artifacts"]:
            if not isinstance(item, Mapping) or _number(item.get("actual_pdf_page_count")) is None:
                continue
            count = int(item["actual_pdf_page_count"])
            docx_path = str(item.get("final_docx_path", ""))
            for key in (docx_path, Path(docx_path).name):
                if key:
                    values[key] = count
        if values:
            return values
    render = qa_report.get("render") if isinstance(qa_report.get("render"), Mapping) else {}
    values = render.get("page_counts")
    if not isinstance(values, Mapping):
        return {}
    return {str(key): int(value) for key, value in values.items() if _number(value) is not None}


def visual_sample_selection(
    data: Mapping[str, Any],
    qa_report: Mapping[str, Any],
    output_inventory: Mapping[str, Any],
    artifact_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    metrics = lesson_length_metrics(lessons)
    names = list(output_inventory.get("docx_files", []))
    selected: dict[int, set[str]] = {}

    def add(index: int, reason: str) -> None:
        if 0 <= index < len(lessons):
            selected.setdefault(index, set()).add(reason)

    if lessons:
        add(0, "first_lesson")
        add(len(lessons) - 1, "last_lesson")
    for index in range(len(lessons) - 1):
        if str(lessons[index].get("unit", "")) != str(lessons[index + 1].get("unit", "")):
            add(index, "boundary_before")
            add(index + 1, "boundary_after")
    seen_units: set[str] = set()
    for index, lesson in enumerate(lessons):
        unit = str(lesson.get("unit", ""))
        if unit not in seen_units:
            seen_units.add(unit)
            add(index, "each_project")
    for index in sorted(range(len(metrics)), key=lambda item: metrics[item]["total_chars"], reverse=True)[:1]:
        add(index, "maximum_content_chars")
    for index in sorted(range(len(metrics)), key=lambda item: metrics[item]["implementation_chars"], reverse=True)[:1]:
        add(index, "maximum_implementation_density")
    for index in sorted(range(len(metrics)), key=lambda item: metrics[item]["evaluation_remarks_chars"], reverse=True)[:1]:
        add(index, "maximum_evaluation_density")
    page_counts = _page_count_map(qa_report, artifact_manifest)
    if names and page_counts:
        for index, name in enumerate(names[: len(lessons)]):
            if name in page_counts and page_counts[name] == max(page_counts.values()):
                add(index, "maximum_pages")
    random_count = max(1, round(len(lessons) * 0.15)) if lessons else 0
    candidates = [index for index in range(len(lessons)) if index not in selected]
    seed_source = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    randomizer = random.Random(int(hashlib.sha256(seed_source).hexdigest()[:16], 16))
    for index in randomizer.sample(candidates, min(random_count, len(candidates))):
        add(index, "deterministic_random_10_to_20_percent")
    sample = [
        {
            "lesson_id": _lesson_id(lessons[index], index + 1),
            "file": names[index] if index < len(names) else None,
            "reasons": sorted(reasons),
        }
        for index, reasons in sorted(selected.items())
    ]
    return {
        "policy": "risk_oriented_sample; render smoke remains all-doc; visual inspection is manual",
        "sample_count": len(sample),
        "sample": sample,
        "manual_inspection_status": "not_executed",
        "max_pages_source": "artifact-manifest.json" if artifact_manifest else "qa-report.render.page_counts",
    }
