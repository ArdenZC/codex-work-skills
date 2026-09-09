"""Small deterministic gates for Practice WorkOrder Content 1.1.

The Agent owns pedagogical judgement. This module only checks schema-shaped
facts, fixed scoring, empty fields, exact duplicate narratives, and explicit
deliverable-to-criterion ID mappings.
"""

from __future__ import annotations

import re
from typing import Any

from content_contract import (
    WorkOrderContractError,
    canonicalise_content,
    normalise_text,
    validate_canonical_content,
)


class WorkOrderQualityError(ValueError):
    pass


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", normalise_text(value)).casefold()


def _display(value: Any) -> str:
    if isinstance(value, dict):
        return normalise_text(value.get("text", ""))
    return normalise_text(value)


def _narrative_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _compact(item.get("title", "")),
        _compact(item.get("description", "")),
        tuple(
            (_compact(value.get("deliverable_id")), _compact(value.get("text")))
            if isinstance(value, dict)
            else _compact(value)
            for value in item.get("deliverables", [])
        ),
        tuple(
            (_compact(value.get("criterion_id")), _compact(value.get("text")))
            if isinstance(value, dict)
            else _compact(value)
            for value in item.get("acceptance_criteria", [])
        ),
    )


def _review_ok(content: dict[str, Any]) -> bool:
    review = content.get("pedagogical_review")
    return (
        isinstance(review, dict)
        and review.get("status") == "approved"
        and review.get("capacity") == "fit"
        and len(normalise_text(review.get("summary", ""))) >= 12
        and isinstance(review.get("checks"), dict)
        and bool(review.get("checks"))
    )


def _answer_leakage(content: dict[str, Any]) -> bool:
    """Keep the student-facing contract free of explicit answer material."""

    fragments: list[str] = []
    for item in content.get("task_items", []):
        if not isinstance(item, dict):
            continue
        fragments.extend(
            [
                normalise_text(item.get("title")),
                normalise_text(item.get("description")),
                *[normalise_text(value) for value in item.get("steps", [])],
                *[_display(value) for value in item.get("deliverables", [])],
                *[_display(value) for value in item.get("acceptance_criteria", [])],
            ]
        )
    text = "\n".join(fragments)
    return bool(
        re.search(
            r"(?:标准答案|参考答案|正确答案|教师答案|答案\s*[:：]|完整(?:的)?\s*(?:SQL|代码|模型|结果))",
            text,
            flags=re.IGNORECASE,
        )
    )


def _mapping_errors(item: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    deliverables = item.get("deliverables", [])
    criteria = item.get("acceptance_criteria", [])
    if any(not isinstance(value, dict) for value in deliverables):
        errors.append(f"task_items[{index}].deliverables must use objects with deliverable_id and text")
        return errors
    if any(not isinstance(value, dict) for value in criteria):
        errors.append(f"task_items[{index}].acceptance_criteria must use objects with criterion_id, text, and covers")
        return errors
    deliverable_ids = [str(value.get("deliverable_id")) for value in deliverables]
    criterion_ids = [str(value.get("criterion_id")) for value in criteria]
    if len(deliverable_ids) != len(set(deliverable_ids)):
        errors.append(f"task_items[{index}].deliverables contains duplicate deliverable_id")
    if len(criterion_ids) != len(set(criterion_ids)):
        errors.append(f"task_items[{index}].acceptance_criteria contains duplicate criterion_id")
    covered: set[str] = set()
    known = set(deliverable_ids)
    for criterion in criteria:
        covers = criterion.get("covers", [])
        unknown = [str(value) for value in covers if str(value) not in known]
        if unknown:
            errors.append(
                f"task_items[{index}] criterion {criterion.get('criterion_id')} covers unknown deliverable IDs: {', '.join(unknown)}"
            )
        covered.update(str(value) for value in covers if str(value) in known)
    missing = [value for value in deliverable_ids if value not in covered]
    if missing:
        errors.append(
            f"task_items[{index}] deliverables are not mapped to acceptance criteria: {', '.join(missing)}"
        )
    return errors


def _canonical_for_quality(content: dict[str, Any], *, allow_legacy: bool) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(content, dict):
        return None, ["WorkOrder Content must be an object"]
    legacy = content.get("content_contract_version") == "1.0"
    if legacy and not allow_legacy:
        return None, ["WorkOrder Content 1.0 is legacy; use the explicit legacy adapter"]
    try:
        value = canonicalise_content(content, compatibility=legacy)
        if not legacy:
            value = validate_canonical_content(value)
        return value, []
    except WorkOrderContractError as exc:
        return None, [str(exc)]


def validate_content(content: dict[str, Any], *, allow_legacy: bool = False) -> dict[str, Any]:
    """Validate fixed facts and explicit ID mappings; pedagogy is Agent-owned."""

    canonical, errors = _canonical_for_quality(content, allow_legacy=allow_legacy)
    if canonical is None:
        return {
            "status": "fail",
            "errors": errors,
            "warnings": [],
            "categories": {"schema": "fail", "domain": "agent_reviewed"},
            "metrics": {"semantic_quality_source": "Agent pedagogical review"},
        }
    structural_errors: list[str] = []
    mapping_errors: list[str] = []
    practice_hours = canonical.get("practice_hours")
    if practice_hours != 2:
        errors.append("practice_hours must equal 2 because one WorkOrder represents exactly one 2-hour Practice Task")
    if canonical.get("mode") not in {"linked", "standalone"}:
        errors.append("mode must be linked or standalone")
    if not _review_ok(canonical):
        errors.append("pedagogical_review must be approved with capacity=fit before DOCX generation")
    answer_leakage = _answer_leakage(canonical)
    if answer_leakage:
        errors.append("answer/key leakage is not allowed in student-facing WorkOrder content")
    task_items = canonical.get("task_items", [])
    if not isinstance(task_items, list) or not 1 <= len(task_items) <= 5:
        structural_errors.append("task_items must contain between 1 and 5 items")
        task_items = task_items if isinstance(task_items, list) else []
    total_task_score = 0
    narrative_keys: list[tuple[Any, ...]] = []
    for index, item in enumerate(task_items, start=1):
        if not isinstance(item, dict):
            structural_errors.append(f"task_items[{index}] must be an object")
            continue
        if not normalise_text(item.get("title")) or not normalise_text(item.get("description")):
            structural_errors.append(f"task_items[{index}] title and description must be non-empty")
        for key in ("tools_or_materials", "steps", "deliverables", "acceptance_criteria"):
            if not item.get(key):
                structural_errors.append(f"task_items[{index}].{key} must contain non-empty values")
        try:
            total_task_score += int(item.get("score", 0))
        except (TypeError, ValueError):
            structural_errors.append(f"task_items[{index}].score must be an integer")
        narrative_keys.append(_narrative_key(item))
        mapping_errors.extend(_mapping_errors(item, index))
    errors.extend(structural_errors)
    errors.extend(mapping_errors)
    if total_task_score != 90:
        errors.append(f"task item scores must total 90, got {total_task_score}")
    duplicate_narrative = len(narrative_keys) != len(set(narrative_keys))
    if duplicate_narrative:
        errors.append("task item narrative duplicates are not allowed within one WorkOrder")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": [],
        "categories": {
            "schema": "pass",
            "practice_hours_unit": "pass" if practice_hours == 2 else "fail",
            "executability": "fail" if structural_errors else "pass",
            "capacity": "pass" if _review_ok(canonical) else "fail",
            "deliverable": "fail" if mapping_errors else "pass",
            "acceptance": "fail" if mapping_errors else "pass",
            "repetition": "fail" if duplicate_narrative else "pass",
            "score": "pass" if total_task_score == 90 else "fail",
            "domain": "agent_reviewed",
            "answer_boundary": "fail" if answer_leakage else "pass",
        },
        "metrics": {
            "practice_hours": practice_hours,
            "task_count": len(task_items),
            "attendance_score": 10,
            "task_score": total_task_score,
            "total_score": 100 if total_task_score == 90 else 10 + total_task_score,
            "deliverable_acceptance_mapping": "id_based",
            "semantic_quality_source": "Agent pedagogical review",
        },
    }


def validate_collection(contents: list[dict[str, Any]], *, allow_legacy: bool = False) -> dict[str, Any]:
    reports = [validate_content(content, allow_legacy=allow_legacy) for content in contents]
    errors = [
        f"content[{index}]: {error}"
        for index, report in enumerate(reports)
        for error in report["errors"]
    ]
    canonical_items = [
        canonicalise_content(content, compatibility=allow_legacy and content.get("content_contract_version") == "1.0")
        for content in contents
    ]
    skeletons = [tuple(_narrative_key(item) for item in content.get("task_items", [])) for content in canonical_items]
    if len(skeletons) > 1 and len(set(skeletons)) == 1:
        errors.append("all generated WorkOrders have the same task narrative skeleton")
    all_narratives = [
        _narrative_key(item)
        for content in canonical_items
        for item in content.get("task_items", [])
        if isinstance(item, dict)
    ]
    if len(all_narratives) != len(set(all_narratives)):
        errors.append("duplicate task narrative is not allowed across WorkOrders")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": [],
        "reports": reports,
        "metrics": {
            "content_count": len(contents),
            "total_score": 100,
            "repetition_scope": ["task_items.title", "task_items.description", "task_items.deliverables", "task_items.acceptance_criteria"],
            "semantic_quality_source": "Agent pedagogical review",
        },
    }
