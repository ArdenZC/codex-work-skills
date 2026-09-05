"""Read-only Lesson Acceptance V2 evidence collector for Content 2.0/2.1/2.2.

The production Lesson Content QA remains the authority for structural,
similarity, progression, and implementation checks.  This module only reads
the V2 input, the already-produced ``qa-report.json``, and the DOCX output
directory, then writes a compact acceptance report to a caller-selected
report directory.  Teaching-design, visual, and teacher-usability decisions
remain explicit manual evidence rather than new Python hard gates.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
from typing import Any


ACCEPTANCE_SCHEMA_VERSION = "2.0"
CONTENT_CONTRACT_VERSION = "2.2"
COMPATIBLE_CONTENT_CONTRACT_VERSIONS = ("2.0", "2.1", "2.2")
DEFAULT_TEMPLATE_ID = "lesson-plan"
DEFAULT_TEMPLATE_VERSION = "v1.1.2"
SOURCE_TYPES = ("real_agent", "synthetic_fixture", "human_authored", "mixed")
PENDING_STATUS = "PENDING_MANUAL_REVIEW"
FINAL_STATUSES = (
    PENDING_STATUS,
    "PASSED",
    "PASSED_WITH_TEACHER_ADJUSTMENTS",
    "FAILED",
)

KNOWN_SOFTWARE_MODELING_64H_BOUNDARIES = (
    ("L04", "L05"),
    ("L08", "L09"),
    ("L12", "L13"),
    ("L16", "L17"),
    ("L20", "L21"),
    ("L24", "L25"),
    ("L28", "L29"),
)

_DUPLICATE_DETECTORS = (
    "exact_duplicates",
    "adjacent_exact_duplicates",
    "item_duplicates",
    "adjacent_item_duplicates",
    "frequency_item_duplicates",
    "adjacent_similarity_pairs",
    "repeated_sentences",
    "field_similarity_pairs",
    "structural_similarity_pairs",
    "whole_lesson_similarity_pairs",
    "implementation_duplicates",
    "adjacent_implementation_exact_duplicates",
    "implementation_similarity_pairs",
    "implementation_structural_similarity_pairs",
    "evaluation_remark_duplicates",
)
_PAIR_SOURCES = {
    "whole_lesson": "whole_lesson_similarity_pairs",
    "adjacent_lesson": "adjacent_similarity_pairs",
    "fields": "field_similarity_pairs",
    "structural": "structural_similarity_pairs",
    "implementation": "implementation_similarity_pairs",
    "implementation_structural": "implementation_structural_similarity_pairs",
    "evaluation_remarks": "evaluation_remark_duplicates",
}
_HALLUCINATION_KEYS = {
    "school": "school_identity",
    "school_name": "school_identity",
    "teacher": "teacher_identity",
    "teacher_name": "teacher_identity",
    "textbook": "textbook_identity",
    "textbook_title": "textbook_identity",
    "isbn": "isbn_identity",
    "schedule": "schedule_identity",
    "class_schedule": "schedule_identity",
}
_GENERIC_BIBLIOGRAPHY_RE = re.compile(
    r"(?:ISBN|作者|出版社|出版年|版次|标准编号|文献编号|\b20\d{2}\b)",
    re.IGNORECASE,
)
_MANUAL_REVIEW_DIMENSIONS = (
    "scope",
    "progression",
    "task_realism",
    "implementation",
    "qa_gaming",
    "evaluation",
    "reflection",
)
_NEGATIVE_CONTROL_CATALOG = (
    {
        "id": "nursing_sql_contamination",
        "description": "护理课程混入 SQL/数据库技术内容",
        "expected": "reject",
        "detector": "existing Content QA non-IT/domain contamination",
    },
    {
        "id": "database_patient_bp",
        "description": "数据库课程混入患者血压等护理内容",
        "expected": "reject",
        "detector": "existing Content QA non-IT/domain contamination",
    },
    {
        "id": "copied_teacher_actions",
        "description": "连续三课 teacher_actions 完全复制",
        "expected": "reject",
        "detector": "existing implementation duplicate QA",
    },
    {
        "id": "mechanical_scores",
        "description": "评分全部相同或机械等差/循环",
        "expected": "reject",
        "detector": "existing score-pattern QA",
    },
    {
        "id": "generic_fabricated_reference",
        "description": "generic reference 带虚构作者、ISBN、出版社或版次",
        "expected": "reject",
        "detector": "existing generic-reference provenance QA",
    },
    {
        "id": "short_remark",
        "description": "评价备注低于现有最小长度",
        "expected": "reject",
        "detector": "existing evaluation-remark contract QA",
    },
    {
        "id": "v21_reference_placeholder",
        "description": "2.1 reference pool 使用泛化占位文献名称",
        "expected": "reject",
        "detector": "Content 2.1 reference document-likeness QA",
    },
    {
        "id": "v21_textbook_overlap",
        "description": "2.1 reference pool 未经 override 重复课程教材",
        "expected": "reject",
        "detector": "Content 2.1 textbook-overlap hard gate",
    },
    {
        "id": "v21_same_lesson_reference_id",
        "description": "同一课次重复使用相同 reference_id",
        "expected": "reject",
        "detector": "Content 2.1 same-lesson reference ID hard gate",
    },
    {
        "id": "v21_unresolved_reference_id",
        "description": "2.1 课次引用不存在的 reference_id",
        "expected": "reject",
        "detector": "Content 2.1 unresolved reference ID hard gate",
    },
    {
        "id": "v21_resource_only_reference",
        "description": "把投影仪、血压计等纯教学资源写入 reference pool",
        "expected": "reject",
        "detector": "references/resources document-likeness boundary",
    },
    {
        "id": "v21_delivery_hour_mismatch",
        "description": "2.1 delivery_plan 与课次理论/实践课时不守恒",
        "expected": "reject",
        "detector": "Content 2.1 delivery-hour hard gate",
    },
    {
        "id": "v21_practice_link_mismatch",
        "description": "实践任务链接到理论课或任务学时不一致",
        "expected": "reject",
        "detector": "Practice Task Contract V1 handoff hard gate",
    },
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _is_within(path: Path, parent: Path) -> bool:
    path = path.resolve(strict=False)
    parent = parent.resolve(strict=False)
    return path == parent or parent in path.parents


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _normalise_version(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if text.lower().startswith("v") else f"v{text}"


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


def _distribution(values: Iterable[int | float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None, "p10": None, "p90": None}

    def percentile(fraction: float) -> float:
        index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
        return ordered[index]

    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": round(statistics.fmean(ordered), 2),
        "median": round(statistics.median(ordered), 2),
        "p10": percentile(0.10),
        "p90": percentile(0.90),
    }


def content_length_report(lessons: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    per_lesson = lesson_length_metrics(lessons)
    fields = sorted(key for key in per_lesson[0] if key.endswith("_chars")) if per_lesson else []
    return {
        "threshold_policy": "descriptive_only_no_must_differ_gate",
        "per_lesson": per_lesson,
        "course_distribution": {field: _distribution(row[field] for row in per_lesson) for field in fields},
    }


def _pair_score(item: Any) -> float | None:
    if not isinstance(item, Mapping):
        return None
    for key in ("score", "similarity", "ratio", "value"):
        value = _number(item.get(key))
        if value is not None:
            return value
    return None


def _pair_summary(items: Any, field: str | None = None) -> dict[str, Any]:
    if not isinstance(items, list):
        items = []
    selected = [item for item in items if field is None or (isinstance(item, Mapping) and item.get("field") == field)]
    scored = [(score, item) for item in selected if (score := _pair_score(item)) is not None]
    scores = [score for score, _item in scored]
    maximum = max(scored, key=lambda pair: pair[0], default=None)
    return {
        "count": len(selected),
        "scored_count": len(scores),
        "mean": round(statistics.fmean(scores), 4) if scores else None,
        "max": round(max(scores), 4) if scores else None,
        "maximum_pair": _json_safe(maximum[1]) if maximum else None,
    }


def content_quality_evidence(qa_report: Mapping[str, Any]) -> dict[str, Any]:
    """Summarise existing QA output; no detector or new threshold is implemented here."""

    quality = qa_report.get("content_quality")
    if not isinstance(quality, Mapping):
        quality = {}
    detector_counts = {
        key: len(value) if isinstance(value, list) else (0 if value in (None, False) else 1)
        for key, value in quality.items()
        if key in _DUPLICATE_DETECTORS
    }
    fields = sorted(
        {
            str(item.get("field"))
            for item in quality.get("field_similarity_pairs", [])
            if isinstance(item, Mapping) and item.get("field")
        }
    )
    return {
        "source": "existing qa-report.json content_quality; no new hard threshold",
        "status": quality.get("status", "not_available"),
        "detector_counts": detector_counts,
        "errors": list(quality.get("errors", [])) if isinstance(quality.get("errors"), list) else [],
        "similarity": {
            "whole_lesson": _pair_summary(quality.get(_PAIR_SOURCES["whole_lesson"])),
            "adjacent_lesson": _pair_summary(quality.get(_PAIR_SOURCES["adjacent_lesson"])),
            "fields": {
                field: _pair_summary(quality.get(_PAIR_SOURCES["fields"]), field)
                for field in fields
            },
            "structural": _pair_summary(quality.get(_PAIR_SOURCES["structural"])),
            "implementation": _pair_summary(quality.get(_PAIR_SOURCES["implementation"])),
            "implementation_structural": _pair_summary(quality.get(_PAIR_SOURCES["implementation_structural"])),
            "evaluation_remarks": _pair_summary(quality.get(_PAIR_SOURCES["evaluation_remarks"])),
        },
        "reference_reuse": _json_safe(quality.get("reference_provenance", {})),
        "practice_handoff": _json_safe(quality.get("practice_handoff", {})),
    }


def _gate(
    name: str,
    passed: bool,
    observed: Any,
    details: str,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status or ("PASS" if passed else "FAIL"),
        "observed": _json_safe(observed),
        "details": details,
    }


def _not_applicable_gate(name: str, observed: Any, details: str) -> dict[str, Any]:
    return _gate(name, True, observed, details, status="NOT_APPLICABLE")


def _anchor_observation(qa_report: Mapping[str, Any]) -> dict[str, Any]:
    checks = qa_report.get("checks") if isinstance(qa_report.get("checks"), Mapping) else {}
    anchors = checks.get("anchors") if isinstance(checks.get("anchors"), Mapping) else {}
    return {
        "mode": qa_report.get("anchor_mode", anchors.get("mode")),
        "required": qa_report.get("required_anchor_count", anchors.get("required")),
        "preserved": qa_report.get("preserved_anchor_count", anchors.get("preserved")),
        "missing": qa_report.get("missing_anchors", anchors.get("missing", [])),
        "duplicates": qa_report.get("duplicate_anchors", anchors.get("duplicates", [])),
        "invalid_names": qa_report.get("invalid_anchor_names", anchors.get("invalid_names", [])),
        "unexpected_names": qa_report.get("unexpected_anchor_names", anchors.get("unexpected_names", [])),
        "invalid_ids": qa_report.get("invalid_anchor_ids", anchors.get("invalid_ids", [])),
        "boundary_errors": qa_report.get("anchor_boundary_errors", anchors.get("boundary_errors", [])),
    }


def delivery_metrics(data: Mapping[str, Any]) -> dict[str, Any]:
    """Report delivery accounting without changing Content QA thresholds."""

    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    version = data.get("content_contract_version")
    if version not in {"2.1", "2.2"}:
        return {
            "status": "not_applicable",
            "contract_version": version,
            "expected": {},
            "actual": {},
            "lesson_counts": {},
            "mismatches": [],
        }
    plan = data.get("delivery_plan") if isinstance(data.get("delivery_plan"), Mapping) else {}
    expected = {
        "total_hours": _number(plan.get("total_hours")),
        "theory_hours": _number(plan.get("theory_hours")),
        "practice_hours": _number(plan.get("practice_hours")),
    }
    actual = {
        "total_hours": sum((_number(lesson.get("hours")) or 0) for lesson in lessons if isinstance(lesson, Mapping)),
        "theory_hours": sum((_number(lesson.get("theory_hours")) or 0) for lesson in lessons if isinstance(lesson, Mapping)),
        "practice_hours": sum((_number(lesson.get("practice_hours")) or 0) for lesson in lessons if isinstance(lesson, Mapping)),
    }
    counts = {
        lesson_type: sum(1 for lesson in lessons if isinstance(lesson, Mapping) and lesson.get("lesson_type") == lesson_type)
        for lesson_type in ("theory", "practice", "integrated")
    }
    if version == "2.2":
        contract = data.get("practice_task_contract") if isinstance(data.get("practice_task_contract"), Mapping) else {}
        tasks = contract.get("tasks") if isinstance(contract.get("tasks"), list) else []
        lesson_hours = sum((_number(lesson.get("hours")) or 0) for lesson in lessons if isinstance(lesson, Mapping))
        task_hours = sum((_number(task.get("practice_hours")) or 0) for task in tasks if isinstance(task, Mapping))
        actual = {
            "total_hours": lesson_hours + task_hours,
            "theory_hours": sum((_number(lesson.get("theory_hours")) or 0) for lesson in lessons if isinstance(lesson, Mapping)),
            "practice_hours": task_hours,
            "lesson_hours": lesson_hours,
            "practice_task_hours": task_hours,
        }
        mismatches = [
            key for key in ("total_hours", "theory_hours", "practice_hours")
            if expected[key] is None or not math.isclose(expected[key], actual[key], abs_tol=0.01)
        ]
        if expected["theory_hours"] is None or not math.isclose(expected["theory_hours"], actual["lesson_hours"], abs_tol=0.01):
            mismatches.append("lesson_hours")
        return {
            "status": "PASS" if not mismatches else "FAIL",
            "contract_version": "2.2",
            "mode": plan.get("mode"),
            "expected": expected,
            "actual": actual,
            "lesson_counts": counts,
            "mismatches": mismatches,
            "consistency": not mismatches,
        }
    mismatches = [
        key for key in expected
        if expected[key] is None or not math.isclose(expected[key], actual[key], abs_tol=0.01)
    ]
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "contract_version": "2.1",
        "mode": plan.get("mode"),
        "expected": expected,
        "actual": actual,
        "lesson_counts": counts,
        "mismatches": mismatches,
        "consistency": not mismatches,
    }


def reference_metrics(data: Mapping[str, Any], qa_report: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Summarise material/reference gates; cross-lesson reuse is statistics only."""

    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    quality = qa_report.get("content_quality", {}) if isinstance(qa_report, Mapping) else {}
    provenance = quality.get("reference_provenance", {}) if isinstance(quality, Mapping) else {}
    version = data.get("content_contract_version")
    if version not in {"2.1", "2.2"}:
        return {
            "status": "not_applicable",
            "textbook_present": False,
            "pool_size": None,
            "lessons_with_references": None,
            "lessons_without_references": None,
            "reuse_frequency": {},
            "placeholder_count": 0,
            "textbook_overlap_count": 0,
            "same_lesson_duplicate_count": len(provenance.get("same_lesson_duplicates", [])) if isinstance(provenance, Mapping) else 0,
            "unresolved_id_count": 0,
            "cross_lesson_reuse_allowed": True,
        }
    ids_by_lesson = [
        [str(value) for value in lesson.get("reference_ids", [])]
        for lesson in lessons if isinstance(lesson, Mapping)
    ]
    frequency: dict[str, int] = {}
    for ids in ids_by_lesson:
        for reference_id in set(ids):
            frequency[reference_id] = frequency.get(reference_id, 0) + 1
    textbook = (data.get("course_materials") or {}).get("textbook") if isinstance(data.get("course_materials"), Mapping) else None
    placeholder_count = len(provenance.get("placeholder_items", [])) if isinstance(provenance, Mapping) else 0
    overlap_count = len(provenance.get("textbook_overlap", [])) if isinstance(provenance, Mapping) else 0
    duplicate_count = len(provenance.get("same_lesson_duplicates", [])) if isinstance(provenance, Mapping) else 0
    unresolved_count = len(provenance.get("unresolved_ids", [])) if isinstance(provenance, Mapping) else 0
    resource_only_count = len(provenance.get("invalid_resource_only", [])) if isinstance(provenance, Mapping) else 0
    invalid_generic_count = len(provenance.get("invalid_generic", [])) if isinstance(provenance, Mapping) else 0
    empty_count = len(provenance.get("empty_reference_lessons", [])) if isinstance(provenance, Mapping) else 0
    domestic = int(provenance.get("catalog_source_regions", {}).get("domestic", 0)) if isinstance(provenance, Mapping) else 0
    foreign = int(provenance.get("catalog_source_regions", {}).get("foreign", 0)) if isinstance(provenance, Mapping) else 0
    unknown = int(provenance.get("catalog_source_regions", {}).get("unknown", 0)) if isinstance(provenance, Mapping) else 0
    known = domestic + foreign
    domestic_share = domestic / known if known else None
    textbook_overlap_failure = 0 if data.get("allow_textbook_as_reference", False) else overlap_count
    failures = placeholder_count + textbook_overlap_failure + duplicate_count + unresolved_count + resource_only_count + invalid_generic_count + empty_count
    if version == "2.2":
        return {
            "status": "PASS" if failures == 0 else "FAIL",
            "contract_version": "2.2",
            "textbook_present": textbook is not None,
            "textbook_excluded": overlap_count == 0 or bool(data.get("allow_textbook_as_reference", False)),
            "pool_size": len(data.get("reference_pool", [])) if isinstance(data.get("reference_pool"), list) else 0,
            "lessons_with_references": sum(bool(ids) for ids in ids_by_lesson),
            "lessons_without_references": sum(not ids for ids in ids_by_lesson),
            "empty_reference_lesson_count": empty_count,
            "reference_count_by_lesson": [len(ids) for ids in ids_by_lesson],
            "reuse_frequency": dict(sorted(frequency.items())),
            "placeholder_count": placeholder_count,
            "generic_reference_count": sum(
                1 for reference in data.get("reference_pool", [])
                if isinstance(reference, Mapping) and reference.get("source_kind") == "generic"
            ),
            "invalid_generic_count": invalid_generic_count,
            "resource_only_count": resource_only_count,
            "textbook_overlap_count": overlap_count,
            "same_lesson_duplicate_count": duplicate_count,
            "unresolved_id_count": unresolved_count,
            "domestic_source_count": domestic,
            "foreign_source_count": foreign,
            "unknown_source_count": unknown,
            "domestic_share": domestic_share,
            "domestic_share_quality": "warning" if domestic_share is not None and domestic_share < 0.7 else "pass",
            "cross_lesson_reuse_allowed": True,
            "hard_gate_failures": failures,
        }
    return {
        "status": "PASS" if failures == 0 else "FAIL",
        "textbook_present": textbook is not None,
        "pool_size": len(data.get("reference_pool", [])) if isinstance(data.get("reference_pool"), list) else 0,
        "lessons_with_references": sum(bool(ids) for ids in ids_by_lesson),
        "lessons_without_references": sum(not ids for ids in ids_by_lesson),
        "reuse_frequency": dict(sorted(frequency.items())),
        "placeholder_count": placeholder_count,
        "textbook_overlap_count": overlap_count,
        "same_lesson_duplicate_count": duplicate_count,
        "unresolved_id_count": unresolved_count,
        "cross_lesson_reuse_allowed": True,
        "hard_gate_failures": failures,
    }


def practice_handoff_metrics(data: Mapping[str, Any], qa_report: Mapping[str, Any] | None = None) -> dict[str, Any]:
    quality = qa_report.get("content_quality", {}) if isinstance(qa_report, Mapping) else {}
    existing = quality.get("practice_handoff") if isinstance(quality, Mapping) else None
    if isinstance(existing, Mapping) and existing:
        return _json_safe(existing)
    if data.get("content_contract_version") not in {"2.1", "2.2"}:
        return {"status": "not_applicable", "task_count": 0, "hour_consistent": True}
    contract = data.get("practice_task_contract") if isinstance(data.get("practice_task_contract"), Mapping) else {}
    expected = _number((data.get("delivery_plan") or {}).get("practice_hours")) or 0
    tasks = contract.get("tasks") if isinstance(contract.get("tasks"), list) else []
    actual = sum((_number(item.get("practice_hours")) or 0) for item in tasks if isinstance(item, Mapping))
    return {
        "status": "PASS" if math.isclose(expected, actual, abs_tol=0.01) else "FAIL",
        "task_count": len(tasks),
        "expected_practice_hours": expected,
        "actual_practice_hours": actual,
        "hour_consistent": math.isclose(expected, actual, abs_tol=0.01),
    }


def structural_hard_gates(
    data: Mapping[str, Any],
    qa_report: Mapping[str, Any],
    output_inventory: Mapping[str, Any],
    *,
    template_id: str,
    template_version: str,
) -> dict[str, Any]:
    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    expected_count = len(lessons)
    version = str(data.get("content_contract_version") or qa_report.get("content_contract_version") or "unknown")
    plan = data.get("delivery_plan") if isinstance(data.get("delivery_plan"), Mapping) else {}
    declared_course_hours = _number(data.get("total_hours"))
    declared_lesson_hours = _number(plan.get("theory_hours")) if version == "2.2" else declared_course_hours
    qa_checks = qa_report.get("checks") if isinstance(qa_report.get("checks"), Mapping) else {}
    total_hours_check = qa_checks.get("total_hours") if isinstance(qa_checks.get("total_hours"), Mapping) else {}
    actual_hours = _number(total_hours_check.get("actual"))
    course_hours_check = qa_checks.get("course_hours") if isinstance(qa_checks.get("course_hours"), Mapping) else {}
    actual_course_hours = _number(course_hours_check.get("actual")) if version == "2.2" else actual_hours
    contract = str(data.get("content_contract_version") or qa_report.get("content_contract_version") or "unknown")
    file_count = qa_checks.get("file_count") if isinstance(qa_checks.get("file_count"), Mapping) else {}
    lesson_checks = qa_checks.get("lessons") if isinstance(qa_checks.get("lessons"), list) else []
    lesson_errors = [error for item in lesson_checks if isinstance(item, Mapping) for error in item.get("errors", [])]
    render = qa_report.get("render") if isinstance(qa_report.get("render"), Mapping) else {}
    validation = qa_report.get("validation") if isinstance(qa_report.get("validation"), Mapping) else {}
    anchors = _anchor_observation(qa_report)
    lesson_docx_not_applicable = (
        expected_count == 0
        and bool(output_inventory.get("exists"))
        and _number(output_inventory.get("docx_count")) == 0
        and _number(file_count.get("actual")) == 0
        and _number(qa_report.get("files_checked")) == 0
        and not qa_report.get("errors")
    )

    def lesson_docx_gate(name: str, passed: bool, observed: Any, details: str) -> dict[str, Any]:
        if lesson_docx_not_applicable:
            return _not_applicable_gate(
                name,
                {"expected_lesson_docx_count": expected_count, "observed": observed},
                f"{details} No Lesson DOCX is expected; this gate is not applicable.",
            )
        return _gate(name, passed, observed, details)

    template_observed = {
        "template_id": qa_report.get("template_id"),
        "template_version": _normalise_version(qa_report.get("template_version")),
        "template_path": qa_report.get("template_path"),
    }
    anchor_lists_empty = all(not anchors.get(key) for key in ("missing", "duplicates", "invalid_names", "unexpected_names", "invalid_ids", "boundary_errors"))
    anchor_pass = anchors.get("mode") is not None and (
        anchors.get("mode") != "word_bookmark"
        or (
            _number(anchors.get("required")) is not None
            and _number(anchors.get("preserved")) is not None
            and _number(anchors.get("preserved")) >= _number(anchors.get("required"))
            and anchor_lists_empty
        )
    )
    delivery = delivery_metrics(data)
    references = reference_metrics(data, qa_report)
    practice = practice_handoff_metrics(data, qa_report)
    gates = [
        lesson_docx_gate(
            "docx_inventory",
            bool(output_inventory.get("exists")) and output_inventory.get("docx_count") == expected_count,
            {"expected": expected_count, "actual": output_inventory.get("docx_count")},
            "DOCX inventory must contain exactly one output for every lesson.",
        ),
        lesson_docx_gate(
            "qa_files_checked",
            qa_report.get("files_checked") == expected_count and file_count.get("actual") == expected_count,
            {"qa_files_checked": qa_report.get("files_checked"), "qa_file_count": file_count.get("actual")},
            "Use the existing output QA file-count evidence.",
        ),
        _gate(
            "total_hours",
            (
                declared_lesson_hours is not None
                and actual_hours is not None
                and math.isclose(declared_lesson_hours, actual_hours, abs_tol=0.01)
                and (
                    version != "2.2"
                    or (
                        declared_course_hours is not None
                        and actual_course_hours is not None
                        and math.isclose(declared_course_hours, actual_course_hours, abs_tol=0.01)
                    )
                )
            ),
            {
                "expected": declared_lesson_hours if version == "2.2" else declared_course_hours,
                "actual": actual_hours,
                "course_expected": declared_course_hours if version == "2.2" else None,
                "course_actual": actual_course_hours if version == "2.2" else None,
            },
            "Declared Lesson theory hours and, for Content 2.2, course hours must agree with QA evidence.",
        ),
        _gate(
            "content_contract",
            contract in COMPATIBLE_CONTENT_CONTRACT_VERSIONS and qa_report.get("content_contract_version") in COMPATIBLE_CONTENT_CONTRACT_VERSIONS and contract == qa_report.get("content_contract_version"),
            {"input": contract, "qa": qa_report.get("content_contract_version"), "current": CONTENT_CONTRACT_VERSION},
            "Acceptance V2 reads Content Contract 2.0/2.1 compatibility and current Content Contract 2.2; it does not author content.",
        ),
        _gate(
            "delivery_consistency",
            delivery.get("status") in {"PASS", "not_applicable"},
            delivery,
            "Content 2.1/2.2 delivery hours and lesson/artifact accounting must reconcile.",
        ),
        _gate(
            "reference_hard_gates",
            references.get("status") in {"PASS", "not_applicable"},
            references,
            "Reference placeholders, textbook overlap, same-lesson duplicates, and unresolved IDs must be zero; cross-lesson reuse is allowed.",
        ),
        _gate(
            "practice_handoff",
            str(practice.get("status", "")).lower() in {"pass", "passed", "ok", "not_applicable"},
            practice,
            "Practice Task Contract task links and practice-hour sums must reconcile.",
        ),
        _gate(
            "template_identity",
            qa_report.get("template_id") == template_id and _normalise_version(qa_report.get("template_version")) == _normalise_version(template_version),
            template_observed,
            f"Selected template must be {template_id} {_normalise_version(template_version)}.",
        ),
        lesson_docx_gate(
            "template_names_and_fidelity",
            bool(validation.get("template", True)) and bool(validation.get("output", True)) and not lesson_errors and not any("filename" in str(error).lower() or "layout" in str(error).lower() for error in qa_report.get("errors", [])),
            {"validation": validation, "lesson_error_count": len(lesson_errors), "qa_error_count": len(qa_report.get("errors", [])) if isinstance(qa_report.get("errors"), list) else None},
            "Names, protected layout, writable-field fidelity, and existing QA errors must be clean.",
        ),
        lesson_docx_gate(
            "semantic_bookmarks",
            anchor_pass,
            anchors,
            "Existing semantic bookmark inventory/fidelity evidence must be clean when applicable.",
        ),
        _gate(
            "content_quality",
            qa_report.get("status") == "passed" and isinstance(qa_report.get("content_quality"), Mapping) and qa_report["content_quality"].get("status") == "passed",
            {"qa_status": qa_report.get("status"), "content_quality_status": (qa_report.get("content_quality") or {}).get("status") if isinstance(qa_report.get("content_quality"), Mapping) else None},
            "Content QA status is read from the production qa-report.json.",
        ),
        lesson_docx_gate(
            "render_smoke",
            render.get("status") == "passed",
            {"status": render.get("status"), "files_checked": render.get("files_checked"), "page_count": render.get("page_count")},
            "All DOCX render smoke must pass; visual review remains a separate manual layer.",
        ),
    ]
    return {
        "status": "PASS" if all(gate["status"] in {"PASS", "NOT_APPLICABLE"} for gate in gates) else "FAIL",
        "hard_gate": True,
        "lesson_docx_applicable": not lesson_docx_not_applicable,
        "gates": gates,
    }


def _status_from_existing(link: Mapping[str, Any]) -> str:
    raw = str(link.get("status", "")).lower()
    if raw in {"failed", "fail", "error"}:
        return "FAIL"
    if link.get("requires_agent_review") or link.get("agent_review") or raw in {"review", "needs_review", "warning"}:
        return "REVIEW"
    return "PASS" if raw in {"passed", "pass", "ok"} else "REVIEW"


def sequence_review(data: Mapping[str, Any], qa_report: Mapping[str, Any]) -> dict[str, Any]:
    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    quality = qa_report.get("content_quality") if isinstance(qa_report.get("content_quality"), Mapping) else {}
    progression = quality.get("progression") if isinstance(quality.get("progression"), Mapping) else {}
    source_links = progression.get("sequence_links") if isinstance(progression.get("sequence_links"), list) else []
    source_by_pair = {
        (str(item.get("from")), str(item.get("to"))): item
        for item in source_links
        if isinstance(item, Mapping) and item.get("from") is not None and item.get("to") is not None
    }
    physical: list[dict[str, Any]] = []
    for index in range(max(0, len(lessons) - 1)):
        current = lessons[index]
        following = lessons[index + 1]
        from_id = _lesson_id(current, index + 1)
        to_id = _lesson_id(following, index + 2)
        source = source_by_pair.get((from_id, to_id))
        same_unit = str(current.get("unit", "")) == str(following.get("unit", ""))
        status = _status_from_existing(source) if source else "REVIEW"
        physical.append(
            {
                "from": from_id,
                "to": to_id,
                "same_unit": same_unit if source is None else source.get("same_unit", same_unit),
                "status": status,
                "source_status": source.get("status") if source else "missing_from_existing_qa",
                "boundary": not same_unit,
                "details": _json_safe(source or {"reason": "existing sequence link was not present"}),
            }
        )
    attention = [item for item in physical if item["status"] != "PASS" or item["boundary"]]
    known_case = len(lessons) == 32 and math.isclose(_number(data.get("total_hours")) or -1, 64.0, abs_tol=0.01)
    known_boundaries: list[dict[str, Any]] = []
    if known_case:
        by_pair = {(item["from"], item["to"]): item for item in physical}
        for from_id, to_id in KNOWN_SOFTWARE_MODELING_64H_BOUNDARIES:
            item = by_pair.get((from_id, to_id))
            known_boundaries.append(
                {
                    "from": from_id,
                    "to": to_id,
                    "status": item["status"] if item else "REVIEW",
                    "details": item["details"] if item else {"reason": "expected boundary link missing from existing QA"},
                }
            )
    return {
        "source": "existing content_quality.progression.sequence_links",
        "physical_transition_count": len(physical),
        "physical_transitions": physical,
        "attention_transitions": attention,
        "summary": {
            "PASS": sum(item["status"] == "PASS" for item in physical),
            "REVIEW": sum(item["status"] == "REVIEW" for item in physical),
            "FAIL": sum(item["status"] == "FAIL" for item in physical),
            "boundaries": sum(item["boundary"] for item in physical),
        },
        "known_software_modeling_64h": known_case,
        "known_boundaries": known_boundaries,
    }


def _load_optional_json(path: Path | None, label: str) -> dict[str, Any] | None:
    return _read_json(path, label) if path else None


def course_scope_review(data: Mapping[str, Any], payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    projects: list[str] = []
    for lesson in lessons:
        unit = str(lesson.get("unit", "未命名项目")).strip() or "未命名项目"
        if unit not in projects:
            projects.append(unit)
    result = {
        "status": "not_executed",
        "hard_gate": False,
        "allowed_classifications": ["CORE", "EXTENSION", "POSSIBLE_SCOPE_DRIFT"],
        "projects": [
            {"project": project, "classification": "REVIEW_REQUIRED", "notes": "需要人工判断项目是否属于课程范围"}
            for project in projects
        ],
        "notes": "Scope review is a human topic-scope review, not a Python hard gate.",
    }
    if payload:
        result.update(_json_safe(payload))
    return result


def teaching_design_review(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "not_executed",
        "hard_gate": False,
        "dimensions": {dimension: {"status": "not_executed", "notes": ""} for dimension in _MANUAL_REVIEW_DIMENSIONS},
        "notes": "Review scope, progression, task realism, implementation, QA gaming, evaluation, and reflection manually.",
    }
    if payload:
        result.update(_json_safe(payload))
    return result


def _page_count_map(qa_report: Mapping[str, Any]) -> dict[str, int]:
    render = qa_report.get("render") if isinstance(qa_report.get("render"), Mapping) else {}
    values = render.get("page_counts")
    if not isinstance(values, Mapping):
        return {}
    return {str(key): int(value) for key, value in values.items() if _number(value) is not None}


def visual_sample_selection(data: Mapping[str, Any], qa_report: Mapping[str, Any], output_inventory: Mapping[str, Any]) -> dict[str, Any]:
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
    page_counts = _page_count_map(qa_report)
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
        "max_pages_source": "qa-report.render.page_counts",
    }


def visual_review(payload: Mapping[str, Any] | None, sample: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "not_executed",
        "hard_gate": False,
        "sample_selection": sample,
        "inspected_lessons": [],
        "notes": "No actual page inspection is claimed until an Agent records evidence.",
    }
    if payload:
        result.update(_json_safe(payload))
    return result


def negative_controls(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "not_executed",
        "hard_gate": False,
        "cases": [deepcopy(item) for item in _NEGATIVE_CONTROL_CATALOG],
        "transaction_safety": {
            "candidate_cleanup": "not_executed",
            "old_output_preserved": "not_executed",
            "protocol": "run each mutation through the real generator with a sentinel old output",
        },
    }
    if payload:
        result.update(_json_safe(payload))
    return result


def negative_control_catalog() -> list[dict[str, str]]:
    return [deepcopy(item) for item in _NEGATIVE_CONTROL_CATALOG]


def _walk_values(value: Any, path: str = "") -> Iterable[tuple[str, Any, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield child_path, item, str(key).lower()
            yield from _walk_values(item, child_path)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _walk_values(item, f"{path}[{index}]")


def hallucination_review(data: Mapping[str, Any]) -> dict[str, Any]:
    flags: list[dict[str, Any]] = []
    for path, value, key in _walk_values(data):
        if key in _HALLUCINATION_KEYS and value not in (None, "", [], {}):
            flags.append(
                {
                    "kind": _HALLUCINATION_KEYS[key],
                    "path": path,
                    "value_preview": str(value)[:120],
                    "status": "REVIEW",
                }
            )
    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    for lesson_index, lesson in enumerate(lessons, start=1):
        references = lesson.get("references", []) if isinstance(lesson, Mapping) else []
        if not isinstance(references, list):
            continue
        for reference_index, reference in enumerate(references, start=1):
            if not isinstance(reference, Mapping) or reference.get("source_kind") != "generic":
                continue
            title = str(reference.get("title") or reference.get("name") or "")
            if _GENERIC_BIBLIOGRAPHY_RE.search(title):
                flags.append(
                    {
                        "kind": "generic_detailed_bibliographic_identity",
                        "path": f"lessons[{lesson_index - 1}].references[{reference_index - 1}]",
                        "value_preview": title[:120],
                        "status": "REVIEW",
                    }
                )
    return {
        "status": "REVIEW_REQUIRED" if flags else "no_flags",
        "flags": flags,
        "notes": "Flags are review prompts, not automatic claims that user-provided identities are false.",
    }


def _git_head(repo_root: Path | None) -> str:
    if repo_root is None:
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def output_inventory(output_dir: Path) -> dict[str, Any]:
    if not output_dir.is_dir():
        return {"exists": False, "docx_count": 0, "files": [], "docx_files": [], "fingerprint": None}
    records: list[dict[str, Any]] = []
    for path in sorted((item for item in output_dir.rglob("*") if item.is_file()), key=lambda item: item.relative_to(output_dir).as_posix().casefold()):
        relative = path.relative_to(output_dir).as_posix()
        records.append({"path": relative, "size": path.stat().st_size, "sha256": _sha256_file(path)})
    fingerprint_source = "\n".join(
        f"{record['path']}\t{record['size']}\t{record['sha256']}" for record in records
    ).encode("utf-8")
    return {
        "exists": True,
        "docx_count": sum(path.lower().endswith(".docx") for path in (record["path"] for record in records)),
        "docx_files": [record["path"] for record in records if record["path"].lower().endswith(".docx")],
        "file_count": len(records),
        "files": records,
        "fingerprint": hashlib.sha256(fingerprint_source).hexdigest().upper(),
    }


def validate_report_schema(report: Mapping[str, Any]) -> list[str]:
    required_top = {
        "acceptance_schema_version",
        "metadata",
        "structural_hard_gates",
        "content_quality_evidence",
        "sequence_review",
        "course_scope_review",
        "content_length",
        "visual_review",
        "negative_controls",
        "hallucination_review",
        "teaching_design_review",
        "teacher_usability",
        "final_status",
    }
    required_metadata = {
        "course",
        "major",
        "audience",
        "lesson_count",
        "total_hours",
        "source_type",
        "master_commit",
        "content_contract_version",
        "template_version",
        "input_sha256",
        "qa_report_sha256",
        "output_inventory_fingerprint",
        "render_status",
        "visual_status",
    }
    errors = [f"missing top-level key: {key}" for key in sorted(required_top - set(report))]
    metadata = report.get("metadata")
    if not isinstance(metadata, Mapping):
        errors.append("metadata must be an object")
    else:
        errors.extend(f"missing metadata key: {key}" for key in sorted(required_metadata - set(metadata)))
        if metadata.get("source_type") not in SOURCE_TYPES:
            errors.append("metadata.source_type is not a supported source type")
    if report.get("acceptance_schema_version") != ACCEPTANCE_SCHEMA_VERSION:
        errors.append("acceptance_schema_version is not 2.0")
    if report.get("final_status") not in FINAL_STATUSES:
        errors.append("final_status is not a supported acceptance status")
    structural = report.get("structural_hard_gates")
    if not isinstance(structural, Mapping) or structural.get("status") not in {"PASS", "FAIL"}:
        errors.append("structural_hard_gates.status must be PASS or FAIL")
    return errors


def _final_status(
    structural: Mapping[str, Any],
    visual: Mapping[str, Any],
    design: Mapping[str, Any],
    teacher: Mapping[str, Any],
    negative: Mapping[str, Any],
) -> str:
    if structural.get("status") == "FAIL":
        return "FAILED"
    if any(str(item.get("status", "")).lower() in {"failed", "fail", "rejected"} for item in (visual, design, teacher, negative)):
        return "FAILED"
    teacher_status = str(teacher.get("status", "not_executed")).lower()
    if teacher_status in {"passed", "pass", "completed"}:
        usable = _number(teacher.get("usable_count"))
        tweaks = _number(teacher.get("tweak_count"))
        if usable is not None and usable <= 2:
            return "FAILED"
        if tweaks is not None and tweaks > 0:
            return "PASSED_WITH_TEACHER_ADJUSTMENTS"
        return "PASSED"
    if teacher_status in {"passed_with_teacher_adjustments", "adjustments"}:
        return "PASSED_WITH_TEACHER_ADJUSTMENTS"
    return PENDING_STATUS


def build_acceptance_report(
    input_json: Path,
    output_dir: Path,
    qa_report_path: Path,
    *,
    source_type: str,
    report_dir: Path | None = None,
    master_commit: str | None = None,
    repo_root: Path | None = None,
    template_id: str = DEFAULT_TEMPLATE_ID,
    template_version: str = DEFAULT_TEMPLATE_VERSION,
    scope_review_path: Path | None = None,
    design_review_path: Path | None = None,
    teacher_review_path: Path | None = None,
    visual_review_path: Path | None = None,
    negative_controls_path: Path | None = None,
    historical_baseline_path: Path | None = None,
) -> dict[str, Any]:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {SOURCE_TYPES}")
    input_json = input_json.expanduser().resolve()
    qa_report_path = qa_report_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if report_dir is not None:
        report_dir = report_dir.expanduser().resolve()
        if _is_within(report_dir, output_dir) or _is_within(output_dir, report_dir):
            raise ValueError("report_dir must not overlap output_dir; acceptance must not mutate generated content")
    data = _read_json(input_json, "input JSON")
    qa_report = _read_json(qa_report_path, "QA report")
    lessons = data.get("lessons") if isinstance(data.get("lessons"), list) else []
    inventory = output_inventory(output_dir)
    render = qa_report.get("render") if isinstance(qa_report.get("render"), Mapping) else {}
    visual_payload = _load_optional_json(visual_review_path, "visual review JSON")
    scope_payload = _load_optional_json(scope_review_path, "scope review JSON")
    design_payload = _load_optional_json(design_review_path, "teaching design review JSON")
    teacher_payload = _load_optional_json(teacher_review_path, "teacher review JSON")
    negative_payload = _load_optional_json(negative_controls_path, "negative controls JSON")
    baseline_payload = _load_optional_json(historical_baseline_path, "historical baseline JSON")
    sample = visual_sample_selection(data, qa_report, inventory)
    visual = visual_review(visual_payload, sample)
    design = teaching_design_review(design_payload)
    teacher = {
        "status": "not_executed",
        "hard_gate": False,
        "selected_lessons": sample.get("sample", []),
        "rubric_scale": "1-5",
        "usable_threshold": ">=4 usable lessons",
        "tweak_threshold": "3 teacher tweaks are adjustment evidence",
        "acceptance_issue_threshold": "<=2 usable lessons",
        "usable_count": None,
        "tweak_count": None,
        "notes": "Read 4-6 representative lessons in full, including L01, a boundary before/after, a complex lesson, and L32 when present.",
    }
    if teacher_payload:
        teacher.update(_json_safe(teacher_payload))
    negative = negative_controls(negative_payload)
    structural = structural_hard_gates(
        data,
        qa_report,
        inventory,
        template_id=template_id,
        template_version=template_version,
    )
    contract_version = str(data.get("content_contract_version") or qa_report.get("content_contract_version") or "unknown")
    delivery = delivery_metrics(data)
    references = reference_metrics(data, qa_report)
    practice = practice_handoff_metrics(data, qa_report)
    observed_total_hours = _number(data.get("total_hours"))
    visual_status = str(visual.get("status", "not_executed"))
    metadata = {
        "acceptance_schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "course": data.get("course_name"),
        "major": data.get("major"),
        "audience": data.get("audience"),
        "lesson_count": len(lessons),
        "total_hours": observed_total_hours,
        "source_type": source_type,
        "master_commit": master_commit or _git_head(repo_root),
        "content_contract_version": contract_version,
        "template_version": _normalise_version(template_version),
        "input_sha256": _sha256_file(input_json),
        "qa_report_sha256": _sha256_file(qa_report_path),
        "output_inventory_fingerprint": inventory.get("fingerprint"),
        "render_status": render.get("status", "not_executed"),
        "visual_status": visual_status,
        "delivery_mode": (data.get("delivery_plan") or {}).get("mode") if isinstance(data.get("delivery_plan"), Mapping) else None,
        "theory_hours": _number((data.get("delivery_plan") or {}).get("theory_hours")) if isinstance(data.get("delivery_plan"), Mapping) else None,
        "practice_hours": _number((data.get("delivery_plan") or {}).get("practice_hours")) if isinstance(data.get("delivery_plan"), Mapping) else None,
    }
    final_status = _final_status(structural, visual, design, teacher, negative)
    report = {
        "acceptance_schema_version": ACCEPTANCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata,
        "course_name": data.get("course_name"),
        "major": data.get("major"),
        "audience": data.get("audience"),
        "lesson_count": len(lessons),
        "total_hours": observed_total_hours,
        "source_type": source_type,
        "master_commit": metadata["master_commit"],
        "content_contract_version": contract_version,
        "template_version": metadata["template_version"],
        "input_sha256": metadata["input_sha256"],
        "qa_report_sha256": metadata["qa_report_sha256"],
        "output_inventory_fingerprint": metadata["output_inventory_fingerprint"],
        "render_status": metadata["render_status"],
        "visual_status": visual_status,
        "input_json": str(input_json),
        "qa_report": str(qa_report_path),
        "output_dir": str(output_dir),
        "output_inventory": inventory,
        "structural_hard_gates": structural,
        "content_quality_evidence": content_quality_evidence(qa_report),
        "sequence_review": sequence_review(data, qa_report),
        "course_scope_review": course_scope_review(data, scope_payload),
        "content_length": content_length_report(lessons),
        "visual_review": visual,
        "negative_controls": negative,
        "hallucination_review": hallucination_review(data),
        "teaching_design_review": design,
        "teacher_usability": teacher,
        "delivery_metrics": delivery,
        "reference_metrics": references,
        "practice_handoff_metrics": practice,
        "historical_baseline": {
            "status": "provided_for_comparison_only" if baseline_payload else "not_provided",
            "hard_gate": False,
            "data": _json_safe(baseline_payload) if baseline_payload else None,
            "notes": "Historical baseline is comparative context only; it creates no acceptance threshold.",
        },
        "final_status": final_status,
        "manual_completion_required": [
            name
            for name, value in (
                ("visual_review", visual),
                ("teaching_design_review", design),
                ("teacher_usability", teacher),
                ("negative_controls", negative),
            )
            if str(value.get("status", "")).lower() == "not_executed"
        ],
    }
    schema_errors = validate_report_schema(report)
    if schema_errors:
        raise ValueError("acceptance report schema failed: " + "; ".join(schema_errors))
    return report


def acceptance_markdown(report: Mapping[str, Any]) -> str:
    metadata = report.get("metadata", {})
    structural = report.get("structural_hard_gates", {})
    sequence = report.get("sequence_review", {})
    quality = report.get("content_quality_evidence", {})
    lines = [
        "# Lesson Acceptance V2 Report",
        "",
        f"- Final status: **{report.get('final_status')}**",
        f"- Course: {metadata.get('course')} / {metadata.get('major')} / {metadata.get('audience')}",
        f"- Lessons/hours: {metadata.get('lesson_count')} / {metadata.get('total_hours')}",
        f"- Source: `{metadata.get('source_type')}`; master: `{metadata.get('master_commit')}`",
        f"- Content Contract: `{metadata.get('content_contract_version')}`; template: `{metadata.get('template_version')}`",
        f"- Delivery: `{(report.get('delivery_metrics') or {}).get('status')}`; reference gates: `{(report.get('reference_metrics') or {}).get('status')}`; practice handoff: `{(report.get('practice_handoff_metrics') or {}).get('status')}`",
        f"- Input SHA256: `{metadata.get('input_sha256')}`",
        f"- QA SHA256: `{metadata.get('qa_report_sha256')}`",
        f"- Output inventory SHA256: `{metadata.get('output_inventory_fingerprint')}`",
        "",
        "## Structural hard gates",
        "",
        f"Overall: **{structural.get('status')}**",
        "",
    ]
    for gate in structural.get("gates", []):
        lines.append(f"- `{gate.get('status')}` {gate.get('name')}: {gate.get('details')}")
    lines.extend(
        [
            "",
            "## Existing Content QA evidence",
            "",
            f"- QA status: `{quality.get('status')}`; detector counts: `{json.dumps(quality.get('detector_counts', {}), ensure_ascii=False, sort_keys=True)}`",
            "- Similarity/duplicate values are evidence copied from the existing QA report; this harness adds no new hard threshold.",
            "- Reference reuse remains course-reusable; only same-lesson duplicate/resource-only decisions belong to the existing reference QA.",
            "",
            "## Sequence and boundaries",
            "",
            f"- Physical transitions: {sequence.get('physical_transition_count')}; summary: `{json.dumps(sequence.get('summary', {}), ensure_ascii=False, sort_keys=True)}`",
            "- Review details are expanded for failed/review links and unit boundaries only.",
            "",
            "## Manual review status",
            "",
            f"- Visual: `{(report.get('visual_review') or {}).get('status')}`",
            f"- Teaching design: `{(report.get('teaching_design_review') or {}).get('status')}`",
            f"- Teacher usability: `{(report.get('teacher_usability') or {}).get('status')}`",
            "- Read 4-6 representative lessons in full: L01, a boundary before/after, a complex/high-density lesson, and L32 when present.",
            "- Teacher rubric is 1-5. At least 4 usable lessons is the pass signal; 3 teacher tweaks means PASSED_WITH_TEACHER_ADJUSTMENTS; 2 or fewer is an acceptance issue.",
            "",
            "## Scope and length",
            "",
            "- Course scope is a manual review for each project using CORE / EXTENSION / POSSIBLE_SCOPE_DRIFT. It is not a Python hard gate.",
            "- Length values are descriptive distributions only. There is no must-differ rule.",
            "",
            "## Negative controls",
            "",
            "- Run the six catalogued mutations through the real generator with a sentinel old output; verify reject, candidate cleanup, and old-output preservation.",
            f"- Current negative-control status: `{(report.get('negative_controls') or {}).get('status')}`",
            "",
            "## Provenance and hallucination review",
            "",
            "- Real Agent A/B generation is local-only evidence and is not a CI test.",
            "- School, teacher, textbook, ISBN, schedule, and generic detailed bibliography fields are review flags; user-provided evidence must be distinguished from unverified claims.",
            "- Historical baselines are comparison-only and do not create thresholds.",
            "",
            "## Interpretation",
            "",
            "- `PENDING_MANUAL_REVIEW` is not a pass claim. Only after visual, teaching-design, negative-control, and teacher-usability evidence is recorded should the final status become PASSED, PASSED_WITH_TEACHER_ADJUSTMENTS, or FAILED.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_acceptance_report(report: Mapping[str, Any], report_dir: Path) -> tuple[Path, Path]:
    report_dir = report_dir.expanduser().resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "lesson-acceptance-report.json"
    markdown_path = report_dir / "lesson-acceptance-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(acceptance_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--qa-report", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--source-type", choices=SOURCE_TYPES, default="mixed")
    parser.add_argument("--master-commit", default="")
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--template-id", default=DEFAULT_TEMPLATE_ID)
    parser.add_argument("--template-version", default=DEFAULT_TEMPLATE_VERSION)
    parser.add_argument("--scope-review", type=Path)
    parser.add_argument("--design-review", type=Path)
    parser.add_argument("--teacher-review", type=Path)
    parser.add_argument("--visual-review", type=Path)
    parser.add_argument("--negative-controls", type=Path)
    parser.add_argument("--historical-baseline", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_acceptance_report(
            args.input_json,
            args.output_dir,
            args.qa_report,
            source_type=args.source_type,
            report_dir=args.report_dir,
            master_commit=args.master_commit or None,
            repo_root=args.repo_root,
            template_id=args.template_id,
            template_version=args.template_version,
            scope_review_path=args.scope_review,
            design_review_path=args.design_review,
            teacher_review_path=args.teacher_review,
            visual_review_path=args.visual_review,
            negative_controls_path=args.negative_controls,
            historical_baseline_path=args.historical_baseline,
        )
        json_path, markdown_path = write_acceptance_report(report, args.report_dir)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Acceptance V2 failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["final_status"], "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False, indent=2))
    return 1 if report["final_status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
