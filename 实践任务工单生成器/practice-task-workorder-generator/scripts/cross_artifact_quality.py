"""Deterministic Lesson Practice Task -> WorkOrder contract checks.

The upstream Practice Task is the source of linked facts. A linked WorkOrder
must carry the canonical course profile and an exact source-task snapshot;
student-facing task items may then organise or expand that material. Semantic
quality and workload judgement belong to the Agent pedagogical review.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from content_contract import (
    COURSE_PROFILE_FIELDS,
    WorkOrderContractError,
    canonical_task_snapshot,
    canonicalise_content,
    course_profile_from_contract,
    load_work_order_content,
    normalise_text,
)


def _unwrap_contract(value: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value.get("practice_task_contract"), dict):
        return value["practice_task_contract"]
    return value


def _legacy_contract(value: dict[str, Any]) -> dict[str, Any]:
    """Convert the old handoff shape for explicit compatibility callers."""

    tasks = value.get("tasks")
    if not isinstance(tasks, list):
        raise WorkOrderContractError("Practice Task Contract requires a tasks array")
    practice_hours = value.get("practice_hours", 0)
    try:
        hours = int(float(practice_hours))
    except (TypeError, ValueError) as exc:
        raise WorkOrderContractError("Practice Task practice_hours must be a whole number") from exc
    profile = {
        "course_name": normalise_text(value.get("course_name")) or "待确认课程",
        "major": normalise_text(value.get("major")) or "待确认专业",
        "audience": normalise_text(value.get("class_or_audience", value.get("audience"))) or "待确认对象",
        "total_hours": hours,
        "theory_hours": 0,
        "practice_hours": hours,
        "delivery_mode": "practice_only",
        "default_lesson_hours": 2,
    }
    return {
        "contract_version": "1.1",
        "course_profile": profile,
        "practice_hours": hours,
        "granularity": "per_task",
        "tasks": copy.deepcopy(tasks),
    }


def _canonical_contract(
    value: dict[str, Any],
    *,
    require_collection_shape: bool = True,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    contract = copy.deepcopy(_unwrap_contract(value))
    if not isinstance(contract, dict):
        raise WorkOrderContractError("Practice Task Contract must be an object")
    if contract.get("contract_version") == "1.0":
        if not allow_legacy:
            raise WorkOrderContractError("Practice Task Contract 1.0 is legacy; rerun with --legacy or regenerate as 1.1")
        contract = _legacy_contract(contract)
    if contract.get("contract_version") != "1.1":
        raise WorkOrderContractError("linked WorkOrder requires Practice Task Contract 1.1")
    profile = course_profile_from_contract(contract)
    if not isinstance(contract.get("tasks"), list) or not contract["tasks"]:
        raise WorkOrderContractError("Practice Task Contract must contain at least one task")
    total_hours = _hours(contract.get("practice_hours"), "Practice Task practice_hours")
    profile_hours = _hours(profile.get("practice_hours"), "course_profile.practice_hours")
    if total_hours != profile_hours:
        raise WorkOrderContractError("Practice Task practice_hours must equal course_profile.practice_hours")
    if require_collection_shape and (total_hours <= 0 or total_hours % 2 or len(contract["tasks"]) != total_hours // 2):
        raise WorkOrderContractError("Practice Task Contract must contain exactly practice_hours / 2 two-hour tasks")
    for task in contract["tasks"]:
        if not isinstance(task, dict) or _hours(task.get("practice_hours"), "Practice Task item practice_hours") != 2:
            raise WorkOrderContractError("every Practice Task in a linked handoff must be exactly 2 hours")
    return contract


def _canonical_content(value: dict[str, Any], *, allow_legacy: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkOrderContractError("WorkOrder Content must be an object")
    compatibility = value.get("content_contract_version") == "1.0"
    if compatibility and not allow_legacy:
        raise WorkOrderContractError("WorkOrder Content 1.0 is legacy; rerun with --legacy or regenerate as 1.1")
    content = canonicalise_content(value, compatibility=compatibility)
    if content.get("content_contract_version") != "1.1":
        raise WorkOrderContractError("linked WorkOrder requires WorkOrder Content 1.1")
    return content


def _check(name: str, passed: bool, detail: str, *, errors: list[str], checks: dict[str, Any]) -> None:
    checks[name] = {"status": "pass" if passed else "fail", "detail": detail}
    if not passed:
        errors.append(f"{name}: {detail}")


def _hours(value: Any, field: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkOrderContractError(f"{field} must be a whole number") from exc
    if number != int(number):
        raise WorkOrderContractError(f"{field} must be a whole number")
    return int(number)


def _profile_key(profile: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        _hours(profile[field], f"course_profile.{field}")
        if field in {"total_hours", "theory_hours", "practice_hours", "default_lesson_hours"}
        else normalise_text(profile[field])
        for field in COURSE_PROFILE_FIELDS
    )


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return normalise_text(value.get("text", ""))
    return normalise_text(value)


def _task_for_id(contract: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [
        task for task in contract.get("tasks", [])
        if isinstance(task, dict) and normalise_text(task.get("task_id")) == task_id
    ]
    if len(matches) != 1:
        raise WorkOrderContractError(
            f"Practice Task Contract must contain exactly one task for {task_id}; found {len(matches)}"
        )
    return matches[0]


def _target_for_id(
    value: dict[str, Any] | list[dict[str, Any]],
    task_id: str,
    *,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    values = value if isinstance(value, list) else [value]
    matches = [
        item for item in values
        if isinstance(item, dict)
        and normalise_text(item.get("task_id", item.get("practice_task_id"))) == task_id
    ]
    if len(matches) != 1:
        raise WorkOrderContractError(
            f"WorkOrder Content must contain exactly one item for {task_id}; found {len(matches)}"
        )
    return _canonical_content(matches[0], allow_legacy=allow_legacy)


def _snapshot_equal(source: dict[str, Any], target: dict[str, Any]) -> bool:
    try:
        expected = canonical_task_snapshot(source)
    except (KeyError, WorkOrderContractError):
        return False
    actual = target.get("source_task_snapshot")
    return isinstance(actual, dict) and actual == expected


def _downstream_values(content: dict[str, Any], field: str) -> list[Any]:
    return [
        value
        for item in content.get("task_items", [])
        if isinstance(item, dict)
        for value in item.get(field, [])
    ]


def validate_cross_artifact_collection(
    practice_task_contract: dict[str, Any],
    work_order_content: list[dict[str, Any]],
    *,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    """Validate one WorkOrder for every upstream Practice Task."""

    errors: list[str] = []
    checks: dict[str, Any] = {}
    try:
        contract = _canonical_contract(practice_task_contract, allow_legacy=allow_legacy)
    except WorkOrderContractError as exc:
        return {"status": "fail", "errors": [str(exc)], "warnings": [], "checks": {}, "reports": [], "metrics": {}}
    source_ids = [normalise_text(task.get("task_id")) for task in contract["tasks"] if isinstance(task, dict)]
    target_ids = [
        normalise_text(item.get("task_id", item.get("practice_task_id")))
        for item in work_order_content
        if isinstance(item, dict)
    ]
    source_unique = len(source_ids) == len(set(source_ids))
    target_unique = len(target_ids) == len(set(target_ids))
    mapping_ok = (
        bool(source_ids)
        and bool(target_ids)
        and source_unique
        and target_unique
        and len(source_ids) == len(target_ids)
        and set(source_ids) == set(target_ids)
    )
    _check(
        "one_to_one_mapping",
        mapping_ok,
        f"practice_tasks={len(source_ids)}, work_orders={len(target_ids)}, "
        f"same_ids={set(source_ids) == set(target_ids)}, "
        f"unique_source={source_unique}, unique_work_orders={target_unique}",
        errors=errors,
        checks=checks,
    )
    reports: list[dict[str, Any]] = []
    for index, item in enumerate(work_order_content):
        if not isinstance(item, dict):
            errors.append(f"work_order[{index}] must be an object")
            continue
        item_id = normalise_text(item.get("task_id", item.get("practice_task_id")))
        try:
            single_contract = copy.deepcopy(contract)
            single_contract["tasks"] = [_task_for_id(contract, item_id)]
            report = validate_cross_artifact(single_contract, item, _single=True, allow_legacy=allow_legacy)
        except WorkOrderContractError as exc:
            report = {"status": "fail", "errors": [str(exc)]}
        reports.append(report)
        if report.get("status") != "pass":
            errors.extend(f"work_order[{index}] {message}" for message in report.get("errors", []))
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": [],
        "checks": checks,
        "reports": reports,
        "metrics": {
            "practice_task_count": len(source_ids),
            "work_order_count": len(target_ids),
            "one_to_one": mapping_ok,
        },
    }


def validate_cross_artifact(
    practice_task_contract: dict[str, Any],
    work_order_content: dict[str, Any] | list[dict[str, Any]],
    *,
    _single: bool = False,
    allow_legacy: bool = False,
) -> dict[str, Any]:
    """Return a fail-closed cross-artifact report without mutating inputs."""

    try:
        contract = _canonical_contract(
            practice_task_contract,
            require_collection_shape=not _single,
            allow_legacy=allow_legacy,
        )
        values = work_order_content if isinstance(work_order_content, list) else [work_order_content]
        if not _single and (len(values) != 1 or len(contract.get("tasks", [])) != 1):
            return validate_cross_artifact_collection(contract, values, allow_legacy=allow_legacy)
        raw_id = normalise_text(values[0].get("task_id", values[0].get("practice_task_id")))
        source = _task_for_id(contract, raw_id)
        downstream = _target_for_id(values, raw_id, allow_legacy=allow_legacy)
    except (WorkOrderContractError, AttributeError, TypeError) as exc:
        return {"status": "fail", "errors": [str(exc)], "warnings": [], "checks": {}, "metrics": {}}

    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    source_id = normalise_text(source.get("task_id"))
    target_id = normalise_text(downstream.get("task_id"))
    _check("identity", source_id == target_id, f"source={source_id}, work_order={target_id}", errors=errors, checks=checks)
    _check(
        "mode",
        downstream.get("mode") == "linked",
        f"linked cross-artifact QA requires WorkOrder mode=linked, got {downstream.get('mode')!r}",
        errors=errors,
        checks=checks,
    )

    source_profile = course_profile_from_contract(contract)
    target_profile = downstream.get("course_profile")
    profile_ok = isinstance(target_profile, dict) and _profile_key(source_profile) == _profile_key(target_profile)
    _check(
        "course_profile",
        profile_ok,
        f"source={source_profile}, work_order={target_profile}",
        errors=errors,
        checks=checks,
    )

    source_project = normalise_text(source.get("project_id"))
    target_project = normalise_text(downstream.get("project_id"))
    _check("project_id", source_project == target_project, f"source={source_project}, work_order={target_project}", errors=errors, checks=checks)

    source_lessons = [normalise_text(value) for value in source.get("lesson_ids", [])]
    target_lessons = [normalise_text(value) for value in downstream.get("lesson_ids", [])]
    _check("lesson_ids", source_lessons == target_lessons, f"source={source_lessons}, work_order={target_lessons}", errors=errors, checks=checks)

    source_hours = _hours(source.get("practice_hours"), "Practice Task practice_hours")
    target_hours = _hours(downstream.get("practice_hours"), "WorkOrder practice_hours")
    _check("practice_hours", source_hours == target_hours, f"source={source_hours}, work_order={target_hours}", errors=errors, checks=checks)
    _check(
        "practice_hours_unit",
        source_hours == 2 and target_hours == 2,
        f"source={source_hours}, work_order={target_hours}; each mapping must represent exactly 2 hours",
        errors=errors,
        checks=checks,
    )

    source_title = normalise_text(source.get("title"))
    target_title = normalise_text(downstream.get("task_title"))
    _check(
        "task_title_intent",
        source_title == target_title,
        f"source={source_title!r}, work_order={target_title!r}; linked titles must be identical",
        errors=errors,
        checks=checks,
    )
    _check(
        "source_task_snapshot",
        _snapshot_equal(source, downstream),
        "linked WorkOrder must preserve the exact canonical Practice Task snapshot",
        errors=errors,
        checks=checks,
    )

    task_items = [item for item in downstream.get("task_items", []) if isinstance(item, dict)]
    downstream_deliverables = _downstream_values(downstream, "deliverables")
    downstream_criteria = _downstream_values(downstream, "acceptance_criteria")
    source_deliverables = [normalise_text(value) for value in source.get("deliverables", [])]
    source_criteria = [normalise_text(value) for value in source.get("acceptance_criteria", [])]
    missing_deliverables = [
        value for value in source_deliverables
        if not any(value == _text(item) or value in _text(item) for item in downstream_deliverables)
    ]
    _check(
        "deliverables",
        not missing_deliverables,
        "uncovered=" + ", ".join(missing_deliverables) if missing_deliverables else "all source deliverables are represented",
        errors=errors,
        checks=checks,
    )
    missing_criteria = [
        value for value in source_criteria
        if not any(value == _text(item) or value in _text(item) for item in downstream_criteria)
    ]
    _check(
        "acceptance_criteria",
        not missing_criteria,
        "uncovered=" + ", ".join(missing_criteria) if missing_criteria else "all source acceptance criteria are represented",
        errors=errors,
        checks=checks,
    )

    source_tools = [normalise_text(value) for value in source.get("tools_or_materials", [])]
    downstream_tools = _downstream_values(downstream, "tools_or_materials")
    missing_tools = [
        value for value in source_tools
        if not any(value == _text(item) or value in _text(item) for item in downstream_tools)
    ]
    tools_ok = not missing_tools
    _check(
        "tools_materials_preservation",
        tools_ok,
        "missing upstream tool/material: " + ", ".join(missing_tools) if missing_tools else "all upstream tools/materials are preserved",
        errors=errors,
        checks=checks,
    )
    # Compatibility names remain, but they are now the same exact-field check;
    # no domain vocabulary or lexical similarity is used.
    checks["tools_materials"] = checks["tools_materials_preservation"]
    checks["tools_materials_domain"] = checks["tools_materials_preservation"]

    source_safety = [normalise_text(value) for value in source.get("safety_or_compliance", [])]
    target_safety = [normalise_text(value) for value in downstream.get("safety_or_compliance", [])]
    missing_safety = [value for value in source_safety if value not in target_safety]
    _check(
        "safety_or_compliance",
        not missing_safety,
        "missing=" + ", ".join(missing_safety) if missing_safety else "all upstream safety/compliance constraints are retained",
        errors=errors,
        checks=checks,
    )

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "metrics": {
            "task_id": source_id,
            "practice_task_id": source_id,
            "lesson_ids": source_lessons,
            "practice_hours": source_hours,
            "deliverable_count": len(source_deliverables),
            "acceptance_criteria_count": len(source_criteria),
            "tool_material_count": len(source_tools),
            "work_order_task_item_count": len(task_items),
            "semantic_quality_source": "Agent pedagogical review",
        },
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-task-json", required=True, type=Path)
    parser.add_argument("--work-order-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Explicitly enable the non-production 1.0 compatibility adapter",
    )
    args = parser.parse_args(argv)
    try:
        practice = _read_json(args.practice_task_json)
        work_order = load_work_order_content(args.work_order_json, allow_legacy=args.legacy)
        report = validate_cross_artifact(practice, work_order, allow_legacy=args.legacy)
    except Exception as exc:
        report = {"status": "fail", "errors": [str(exc)], "warnings": [], "checks": {}, "metrics": {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
