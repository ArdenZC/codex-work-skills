"""Load and validate WorkOrder inputs without authoring production prose."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "work-order-content.schema.json"
PRACTICE_TASK_SCHEMA_ID = "https://codex-work-skills.local/schemas/shared/practice-task-contract-v1.json"


class WorkOrderContractError(ValueError):
    """Raised when a direct content or Lesson handoff cannot be consumed."""


def normalise_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkOrderContractError(f"cannot read JSON input {path}: {exc}") from exc


def _schema_errors(value: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    return [error.message for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path))]


def _practice_task_schema_path() -> Path:
    """Resolve the one repository/shared schema or an installed local copy."""

    candidates = (
        ROOT / "schemas" / "shared" / "practice-task-contract.schema.json",
        ROOT.parents[1] / "schemas" / "shared" / "practice-task-contract.schema.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise WorkOrderContractError(
        "Practice Task Contract V1 shared schema is unavailable; "
        "install the complete repository/Skill package before using --practice-task-json"
    )


def _practice_task_schema_errors(value: dict[str, Any]) -> list[str]:
    schema_path = _practice_task_schema_path()
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkOrderContractError(f"cannot read shared Practice Task schema {schema_path}: {exc}") from exc
    validator = Draft202012Validator(schema)
    return [error.message for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path))]


def load_work_order_content(path: Path) -> list[dict[str, Any]]:
    """Load one or more direct Content V1 objects and validate the JSON shape."""

    value = _load_json(path)
    values = value if isinstance(value, list) else [value]
    if not values or not all(isinstance(item, dict) for item in values):
        raise WorkOrderContractError("Content V1 input must be an object or a non-empty array of objects")
    for index, item in enumerate(values):
        errors = _schema_errors(item)
        if errors:
            detail = "; ".join(errors[:8])
            raise WorkOrderContractError(f"Content V1 item {index} failed schema validation: {detail}")
    return values


_HANDOFF_REQUIRED = (
    "task_id",
    "project_id",
    "title",
    "lesson_ids",
    "practice_hours",
    "scenario",
    "objectives",
    "required_inputs",
    "tools_or_materials",
    "steps",
    "deliverables",
    "acceptance_criteria",
)


def load_practice_task_contract(path: Path) -> dict[str, Any]:
    """Load the Lesson Practice Task Contract V1 without copying its schema.

    The authoritative schema remains in the Lesson Skill. This function only
    checks the small handoff surface needed by the independent Phase 1 tool.
    """

    value = _load_json(path)
    if isinstance(value, dict) and isinstance(value.get("practice_task_contract"), dict):
        value = value["practice_task_contract"]
    if not isinstance(value, dict) or value.get("contract_version") != "1.0":
        raise WorkOrderContractError("Practice Task Contract V1 requires contract_version=1.0")
    schema_errors = _practice_task_schema_errors(value)
    if schema_errors:
        raise WorkOrderContractError(
            "Practice Task Contract V1 failed canonical schema validation: "
            + "; ".join(schema_errors[:8])
        )
    tasks = value.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise WorkOrderContractError("Practice Task Contract V1 requires a non-empty tasks array")
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise WorkOrderContractError(f"handoff task {index} must be an object")
        missing = [key for key in _HANDOFF_REQUIRED if key not in task]
        if missing:
            raise WorkOrderContractError(f"handoff task {index} is missing: {', '.join(missing)}")
        for key in ("objectives", "required_inputs", "tools_or_materials", "steps", "deliverables", "acceptance_criteria"):
            if not isinstance(task[key], list) or not task[key] or not all(normalise_text(item) for item in task[key]):
                raise WorkOrderContractError(f"handoff task {index}.{key} must be a non-empty text list")
    task_ids = [normalise_text(task["task_id"]) for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise WorkOrderContractError("Practice Task Contract V1 task_id values must be unique")
    total_hours = _as_nonnegative_hours(value["practice_hours"], "practice_hours")
    if value.get("granularity") != "per_task":
        raise WorkOrderContractError(
            "Practice Task Contract V1 granularity must be per_task for WorkOrder generation"
        )
    if total_hours <= 0 or total_hours % 2:
        raise WorkOrderContractError(
            "Practice Task Contract V1 practice_hours must be a positive even number"
        )
    expected_task_count = total_hours // 2
    if len(tasks) != expected_task_count:
        raise WorkOrderContractError(
            "Practice Task Contract V1 task count must equal practice_hours / 2: "
            f"expected {expected_task_count}, got {len(tasks)}"
        )
    task_hours = 0
    for task in tasks:
        item_hours = _as_positive_hours(task["practice_hours"], f"{task['task_id']}.practice_hours")
        if item_hours != 2:
            raise WorkOrderContractError(
                f"{task['task_id']}.practice_hours must equal 2 for one WorkOrder; got {item_hours}"
            )
        task_hours += item_hours
    if total_hours != task_hours:
        raise WorkOrderContractError(
            f"Practice Task Contract V1 practice_hours must equal task sum: expected {total_hours}, got {task_hours}"
        )
    return value


def _as_nonnegative_hours(value: Any, field: str) -> int:
    if value == 0 or value == "0" or value == "0.0":
        return 0
    return _as_positive_hours(value, field)


def _as_positive_hours(value: Any, field: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkOrderContractError(f"{field} must be a positive whole number") from exc
    if number <= 0 or number != int(number):
        raise WorkOrderContractError(f"{field} must be a positive whole number")
    return int(number)


def practice_tasks_to_authoring_skeleton(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract an Agent authoring handoff without creating WorkOrder content.

    The returned objects intentionally contain only upstream facts and an
    explicit authoring checklist.  They do not contain ``task_items`` and
    cannot be passed to the DOCX generator as Content V1.
    """

    course_name = normalise_text(contract.get("course_name"))
    if not course_name:
        raise WorkOrderContractError("Practice Task Contract V1 requires course_name")
    skeletons: list[dict[str, Any]] = []
    for task in contract["tasks"]:
        skeletons.append(
            {
                "practice_task_id": normalise_text(task["task_id"]),
                "course_name": course_name,
                "project_id": normalise_text(task["project_id"]),
                "task_title": normalise_text(task["title"]),
                "lesson_ids": [normalise_text(item) for item in task["lesson_ids"]],
                "practice_hours": _as_positive_hours(
                    task["practice_hours"], f"{task['task_id']}.practice_hours"
                ),
                "scenario": normalise_text(task["scenario"]),
                "objectives": [normalise_text(item) for item in task["objectives"]],
                "required_inputs": [normalise_text(item) for item in task["required_inputs"]],
                "tools_or_materials": [normalise_text(item) for item in task["tools_or_materials"]],
                "steps": [normalise_text(item) for item in task["steps"]],
                "deliverables": [normalise_text(item) for item in task["deliverables"]],
                "acceptance_criteria": [normalise_text(item) for item in task["acceptance_criteria"]],
                "safety_or_compliance": [
                    normalise_text(item) for item in task["safety_or_compliance"]
                ],
                "authoring_requirements": {
                    "task_items": "Agent must author 1-5 executable task items and all student-facing prose.",
                    "scores": "Agent assigns positive integer task-item scores from workload, difficulty and deliverables; their sum must be 90.",
                    "content_contract": "Agent must return a complete Practice Work Order Content V1 object before DOCX generation.",
                },
            }
        )
    return skeletons


def _legacy_score_split(count: int, total: int = 90) -> list[int]:
    if count < 1 or count > 5:
        raise WorkOrderContractError("a work order supports 1 to 5 task items")
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _legacy_task_items_from_handoff(task: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [normalise_text(item) for item in task["steps"]]
    # Keep the mapping lossless and bounded by the template's five task rows.
    if len(steps) > 5:
        steps = steps[:4] + ["；".join(steps[4:])]
    scores = _legacy_score_split(len(steps))
    common = [normalise_text(item) for item in task["tools_or_materials"]]
    deliverables = [normalise_text(item) for item in task["deliverables"]]
    criteria = [normalise_text(item) for item in task["acceptance_criteria"]]
    scenario = normalise_text(task["scenario"])
    objectives = [normalise_text(item) for item in task["objectives"]]
    required_inputs = [normalise_text(item) for item in task["required_inputs"]]
    items: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        title = step if len(step) <= 72 else f"步骤 {index}"
        items.append(
            {
                "title": title,
                "description": format_task_description(
                    scenario=scenario,
                    objectives=objectives,
                    required_inputs=required_inputs,
                    step=step,
                    tools_or_materials=common,
                    deliverables=deliverables,
                    acceptance_criteria=criteria,
                ),
                "score": scores[index - 1],
                "tools_or_materials": common,
                "steps": [step],
                "deliverables": deliverables,
                "acceptance_criteria": criteria,
            }
        )
    return items


def practice_tasks_to_content(
    contract: dict[str, Any],
    *,
    major: str,
    class_or_audience: str,
    allow_non_production: bool = False,
) -> list[dict[str, Any]]:
    """Legacy fixture/migration mapper; never use it for production generation.

    The old deterministic expansion remains available only to explicitly
    marked tests or migrations.  The production CLI requires Agent-authored
    Content V1 and never calls this function.
    """

    if not allow_non_production:
        raise WorkOrderContractError(
            "Practice Task handoff is not production WorkOrder Content; "
            "Agent must author complete Content V1 before DOCX generation "
            "(use allow_non_production=True only for fixtures or migration)."
        )

    course_name = normalise_text(contract.get("course_name"))
    if not course_name:
        raise WorkOrderContractError("Practice Task Contract V1 requires course_name")
    outputs: list[dict[str, Any]] = []
    for task in contract["tasks"]:
        task_id = normalise_text(task["task_id"])
        lesson_ids = [normalise_text(item) for item in task["lesson_ids"]]
        outputs.append(
            {
                "content_contract_version": "1.0",
                "course_name": course_name,
                "major": normalise_text(major),
                "class_or_audience": normalise_text(class_or_audience),
                "practice_task_id": task_id,
                "task_title": normalise_text(task["title"]),
                "project_id": normalise_text(task["project_id"]),
                "lesson_ids": lesson_ids,
                "granularity": contract.get("granularity", "per_task"),
                "project_name": normalise_text(task["title"]),
                "practice_hours": _as_positive_hours(task["practice_hours"], f"{task_id}.practice_hours"),
                "group": {
                    "name": "第____组",
                    "leader_placeholder": "组长：____________",
                    "member_placeholder": "成员：____________",
                },
                "task_items": _legacy_task_items_from_handoff(task),
                "safety_or_compliance": [normalise_text(item) for item in task["safety_or_compliance"]],
                "teacher_evaluation": {
                    "description": "沿用 canonical 模板固定教师评价，不在 Content V1 中重写。"
                },
            }
        )
    return outputs


def format_task_description(
    *,
    scenario: str,
    objectives: Iterable[str],
    required_inputs: Iterable[str],
    step: str,
    tools_or_materials: Iterable[str],
    deliverables: Iterable[str],
    acceptance_criteria: Iterable[str],
) -> str:
    """Format supplied handoff fields; this function does not invent answers."""

    def joined(values: Iterable[str]) -> str:
        return "；".join(normalise_text(item) for item in values if normalise_text(item))

    return (
        f"场景：{normalise_text(scenario)}\n"
        f"目标：{joined(objectives)}\n"
        f"输入：{joined(required_inputs)}\n"
        f"本步：{normalise_text(step)}\n"
        f"工具/材料：{joined(tools_or_materials)}\n"
        f"交付物：{joined(deliverables)}\n"
        f"验收：{joined(acceptance_criteria)}"
    )


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", normalise_text(value))
    return cleaned.strip("._")[:80] or "work-order"
