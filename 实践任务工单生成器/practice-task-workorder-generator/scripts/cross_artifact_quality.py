"""Deterministic QA for the Lesson Practice Task -> WorkOrder handoff.

The Practice Task Contract is the upstream fact source.  This module checks
that a downstream Work Order still represents that task; it never rewrites
either artifact and deliberately avoids embeddings or external NLP services.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from content_contract import WorkOrderContractError, load_work_order_content, normalise_text


_IT_TERMS = ("sql", "mysql", "java", "ide", "api", "数据库", "索引")
_NURSING_TERMS = ("护理", "患者", "血压", "体温", "无菌", "生命体征", "护理模拟")
_GENERIC_ANCHORS = {"完成", "进行", "任务", "实践", "操作", "项目", "设计", "整理", "记录"}


def _compact(value: Any) -> str:
    text = unicodedata.normalize("NFKC", normalise_text(value)).casefold()
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def _text_values(values: Iterable[Any]) -> list[str]:
    return [normalise_text(value) for value in values if normalise_text(value)]


def _artifact_text(content: dict[str, Any]) -> str:
    values: list[Any] = [
        content.get("course_name", ""),
        content.get("major", ""),
        content.get("class_or_audience", ""),
        content.get("practice_task_id", ""),
        content.get("task_title", ""),
        content.get("project_id", ""),
        content.get("project_name", ""),
        *content.get("safety_or_compliance", []),
    ]
    for item in content.get("task_items", []):
        values.extend([item.get("title", ""), item.get("description", "")])
        for key in ("tools_or_materials", "steps", "deliverables", "acceptance_criteria"):
            values.extend(item.get(key, []))
    return " ".join(_text_values(values))


def _practice_task(value: dict[str, Any], task_id: str) -> dict[str, Any]:
    if isinstance(value.get("practice_task_contract"), dict):
        value = value["practice_task_contract"]
    tasks = value.get("tasks")
    if isinstance(tasks, list):
        matches = [task for task in tasks if isinstance(task, dict) and task.get("task_id") == task_id]
        if len(matches) != 1:
            raise WorkOrderContractError(
                f"Practice Task Contract must contain exactly one task for {task_id}; found {len(matches)}"
            )
        return matches[0]
    if value.get("task_id") == task_id:
        return value
    raise WorkOrderContractError(f"Practice Task {task_id} was not found")


def _work_order(value: dict[str, Any] | list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    if isinstance(value, list):
        if not value:
            raise WorkOrderContractError("Work Order content must contain one item")
        matches = [item for item in value if isinstance(item, dict) and item.get("practice_task_id") == task_id]
        if len(matches) != 1:
            raise WorkOrderContractError(
                f"Work Order content must contain exactly one item for {task_id}; found {len(matches)}"
            )
        return matches[0]
    if value.get("practice_task_id") != task_id:
        raise WorkOrderContractError(
            f"Work Order practice_task_id={value.get('practice_task_id')!r} does not match {task_id}"
        )
    return value


def _number(value: Any, field: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkOrderContractError(f"{field} must be a whole number") from exc
    if number != int(number):
        raise WorkOrderContractError(f"{field} must be a whole number")
    return int(number)


def _anchors(value: Any) -> set[str]:
    text = _compact(value)
    if not text:
        return set()
    anchors = {token.casefold() for token in re.findall(r"[a-z0-9]+", str(value))}
    anchors.update(text[index : index + 2] for index in range(len(text) - 1))
    return {anchor for anchor in anchors if anchor not in _GENERIC_ANCHORS and len(anchor) >= 2}


def _covered(source: Any, targets: Iterable[Any]) -> bool:
    source_text = _compact(source)
    if not source_text:
        return False
    for target in targets:
        target_text = _compact(target)
        if source_text in target_text or target_text in source_text:
            return True
        source_anchors = _anchors(source)
        overlap = source_anchors & _anchors(target)
        if len(overlap) >= (2 if len(source_text) >= 8 else 1):
            return True
    return False


def _strongly_covered(source: Any, targets: Iterable[Any]) -> bool:
    source_text = _compact(source)
    return bool(source_text) and any(
        source_text in _compact(target) or _compact(target) in source_text
        for target in targets
        if _compact(target)
    )


def _check(name: str, passed: bool, detail: str, *, errors: list[str], checks: dict[str, Any]) -> None:
    checks[name] = {"status": "pass" if passed else "fail", "detail": detail}
    if not passed:
        errors.append(f"{name}: {detail}")


def validate_cross_artifact(
    practice_task_contract: dict[str, Any],
    work_order_content: dict[str, Any] | list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a cross-artifact report without mutating either input."""

    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    try:
        if isinstance(work_order_content, list):
            work_order_id = work_order_content[0].get("practice_task_id", "") if work_order_content else ""
        elif isinstance(work_order_content, dict):
            work_order_id = work_order_content.get("practice_task_id", "")
        else:
            raise WorkOrderContractError("Work Order content must be an object or a non-empty array")
        source = _practice_task(practice_task_contract, normalise_text(work_order_id))
        downstream = _work_order(work_order_content, normalise_text(work_order_id))
    except WorkOrderContractError as exc:
        return {
            "status": "fail",
            "errors": [str(exc)],
            "warnings": [],
            "checks": {},
            "metrics": {},
        }

    source_id = normalise_text(source.get("task_id"))
    target_id = normalise_text(downstream.get("practice_task_id"))
    _check("identity", source_id == target_id, f"source={source_id}, work_order={target_id}", errors=errors, checks=checks)

    source_lessons = _text_values(source.get("lesson_ids", []))
    target_lessons = _text_values(downstream.get("lesson_ids", []))
    _check(
        "lesson_ids",
        set(source_lessons) == set(target_lessons),
        f"source={source_lessons}, work_order={target_lessons}",
        errors=errors,
        checks=checks,
    )
    if source_lessons != target_lessons and set(source_lessons) == set(target_lessons):
        warnings.append("lesson_ids order differs but the contract-defined set is preserved")

    source_hours = _number(source.get("practice_hours"), "Practice Task practice_hours")
    target_hours = _number(downstream.get("practice_hours"), "Work Order practice_hours")
    _check("practice_hours", source_hours == target_hours, f"source={source_hours}, work_order={target_hours}", errors=errors, checks=checks)
    if target_hours > max(1, len(downstream.get("task_items", [])) * 4):
        warnings.append("workload review required: task breadth may exceed the declared practice hours")

    source_title = normalise_text(source.get("title"))
    target_title = normalise_text(downstream.get("task_title") or downstream.get("project_name"))
    title_pass = bool(_anchors(source_title) & _anchors(target_title)) or _compact(source_title) in _compact(target_title)
    _check("task_title_intent", title_pass, f"source={source_title!r}, work_order={target_title!r}", errors=errors, checks=checks)

    task_items = downstream.get("task_items", [])
    downstream_deliverables = [value for item in task_items for value in item.get("deliverables", [])]
    downstream_criteria = [value for item in task_items for value in item.get("acceptance_criteria", [])]
    source_deliverables = _text_values(source.get("deliverables", []))
    source_criteria = _text_values(source.get("acceptance_criteria", []))
    uncovered_deliverables = [value for value in source_deliverables if not _covered(value, downstream_deliverables)]
    _check(
        "deliverables",
        not uncovered_deliverables,
        "uncovered=" + ", ".join(uncovered_deliverables) if uncovered_deliverables else "all source deliverables are represented",
        errors=errors,
        checks=checks,
    )
    uncovered_criteria = [value for value in source_criteria if not _covered(value, downstream_criteria)]
    _check(
        "acceptance_criteria",
        not uncovered_criteria,
        "uncovered=" + ", ".join(uncovered_criteria) if uncovered_criteria else "all source criteria are represented",
        errors=errors,
        checks=checks,
    )

    source_text = " ".join(
        _text_values(
            [source.get("title"), source.get("scenario"), *source.get("tools_or_materials", []), *source.get("objectives", [])]
        )
    ).casefold()
    target_text = _artifact_text(downstream).casefold()
    source_it = any(term in source_text for term in _IT_TERMS)
    source_nursing = any(term in source_text for term in _NURSING_TERMS)
    target_it = any(term in target_text for term in _IT_TERMS)
    target_nursing = any(term in target_text for term in _NURSING_TERMS)
    conflict = (source_nursing and target_it and not source_it) or (source_it and target_nursing and not source_nursing)
    _check(
        "tools_materials",
        not conflict,
        "downstream terminology conflicts with the upstream domain" if conflict else "no bounded domain/tool conflict detected",
        errors=errors,
        checks=checks,
    )

    source_safety = _text_values(source.get("safety_or_compliance", []))
    target_safety = _text_values(downstream.get("safety_or_compliance", []))
    target_full_text = _artifact_text(downstream)
    missing_safety = [value for value in source_safety if not _strongly_covered(value, target_safety + [target_full_text])]
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
            "practice_task_id": source_id,
            "lesson_ids": source_lessons,
            "practice_hours": source_hours,
            "deliverable_count": len(source_deliverables),
            "acceptance_criteria_count": len(source_criteria),
            "work_order_task_item_count": len(task_items),
        },
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-task-json", required=True, type=Path)
    parser.add_argument("--work-order-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        practice = _read_json(args.practice_task_json)
        work_order = load_work_order_content(args.work_order_json)
        report = validate_cross_artifact(practice, work_order)
    except Exception as exc:
        report = {"status": "fail", "errors": [str(exc)], "warnings": [], "checks": {}, "metrics": {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
