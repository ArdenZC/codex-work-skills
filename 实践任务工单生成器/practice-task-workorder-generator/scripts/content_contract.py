"""Load the canonical Practice Task and WorkOrder Content 1.1 contracts."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "work-order-content.schema.json"
PRACTICE_TASK_SCHEMA_ID = "https://codex-work-skills.local/schemas/shared/practice-task-contract-v1.1.json"
PRACTICE_TASK_SNAPSHOT_FIELDS = (
    "task_id",
    "project_id",
    "title",
    "lesson_ids",
    "practice_hours",
    "scenario",
    "objectives",
    "required_inputs",
    "steps",
    "deliverables",
    "acceptance_criteria",
    "tools_or_materials",
    "safety_or_compliance",
)
COURSE_PROFILE_FIELDS = (
    "course_name",
    "major",
    "audience",
    "total_hours",
    "theory_hours",
    "practice_hours",
    "delivery_mode",
    "default_lesson_hours",
)


class WorkOrderContractError(ValueError):
    """Raised when a WorkOrder input cannot be consumed fail-closed."""


def normalise_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkOrderContractError(f"cannot read JSON input {path}: {exc}") from exc


def _schema_errors(value: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return [error.message for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))]


def _practice_task_schema_path() -> Path:
    candidates = (
        ROOT / "schemas" / "shared" / "practice-task-contract.schema.json",
        ROOT.parents[1] / "schemas" / "shared" / "practice-task-contract.schema.json",
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise WorkOrderContractError(
        "Practice Task Contract 1.1 shared schema is unavailable; install the complete repository/Skill package"
    )


def _practice_task_schema_errors(value: dict[str, Any]) -> list[str]:
    schema_path = _practice_task_schema_path()
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkOrderContractError(f"cannot read shared Practice Task schema {schema_path}: {exc}") from exc
    return [error.message for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: list(item.path))]


def _hours(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise WorkOrderContractError(f"{field} must be a whole number of hours")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise WorkOrderContractError(f"{field} must be a whole number of hours") from exc
    if number != int(number) or (number < 0 if allow_zero else number <= 0):
        raise WorkOrderContractError(f"{field} must be a {'non-negative' if allow_zero else 'positive'} whole number of hours")
    return int(number)


def course_profile_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    profile = contract.get("course_profile")
    if not isinstance(profile, dict):
        raise WorkOrderContractError("Practice Task Contract 1.1 requires course_profile")
    if set(profile) != set(COURSE_PROFILE_FIELDS):
        raise WorkOrderContractError("course_profile must contain exactly the confirmed course profile fields")
    return copy.deepcopy(profile)


def canonical_task_snapshot(task: dict[str, Any]) -> dict[str, Any]:
    """Return the exact upstream fields that a linked WorkOrder must preserve."""

    missing = [field for field in PRACTICE_TASK_SNAPSHOT_FIELDS if field not in task]
    if missing:
        raise WorkOrderContractError("Practice Task is missing snapshot fields: " + ", ".join(missing))
    return {field: copy.deepcopy(task[field]) for field in PRACTICE_TASK_SNAPSHOT_FIELDS}


def _legacy_practice_to_v11(value: dict[str, Any]) -> dict[str, Any]:
    """Isolate the old 1.0 handoff behind an explicit migration adapter."""

    course_name = normalise_text(value.get("course_name"))
    tasks = value.get("tasks") if isinstance(value.get("tasks"), list) else []
    practice_hours = _hours(value.get("practice_hours", 0), "practice_hours", allow_zero=True)
    profile = {
        "course_name": course_name or "待确认课程",
        "major": normalise_text(value.get("major")) or "待确认专业",
        "audience": normalise_text(value.get("audience")) or "待确认对象",
        "total_hours": practice_hours,
        "theory_hours": 0,
        "practice_hours": practice_hours,
        "delivery_mode": "practice_only",
        "default_lesson_hours": 2,
    }
    migrated = {
        "contract_version": "1.1",
        "course_profile": profile,
        "practice_hours": practice_hours,
        "granularity": "per_task",
        "tasks": copy.deepcopy(tasks),
    }
    return migrated


def load_practice_task_contract(path: Path, *, allow_legacy: bool = False) -> dict[str, Any]:
    """Load and validate Practice Task Contract 1.1.

    ``allow_legacy`` exists only for direct migration callers and old fixtures.
    The production CLI passes its explicit ``--legacy`` flag through here.
    """

    value = _load_json(path)
    if isinstance(value, dict) and isinstance(value.get("practice_task_contract"), dict):
        value = value["practice_task_contract"]
    if not isinstance(value, dict):
        raise WorkOrderContractError("Practice Task Contract 1.1 must be an object")
    legacy = value.get("contract_version") == "1.0"
    if legacy:
        if not allow_legacy:
            raise WorkOrderContractError("Practice Task Contract 1.0 is legacy; rerun with --legacy or regenerate as 1.1")
        value = _legacy_practice_to_v11(value)
    if value.get("contract_version") != "1.1":
        raise WorkOrderContractError("Practice Task Contract 1.1 requires contract_version=1.1")
    schema_errors = _practice_task_schema_errors(value)
    if schema_errors:
        raise WorkOrderContractError(
            "Practice Task Contract 1.1 failed canonical schema validation: " + "; ".join(schema_errors[:8])
        )
    profile = course_profile_from_contract(value)
    total_hours = _hours(value["practice_hours"], "practice_hours", allow_zero=True)
    profile_practice = _hours(profile["practice_hours"], "course_profile.practice_hours", allow_zero=True)
    if total_hours != profile_practice:
        raise WorkOrderContractError("Practice Task practice_hours must equal course_profile.practice_hours")
    tasks = value["tasks"]
    task_ids = [normalise_text(task["task_id"]) for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise WorkOrderContractError("Practice Task Contract 1.1 task_id values must be unique")
    if total_hours <= 0 or total_hours % 2:
        raise WorkOrderContractError("Practice Task Contract 1.1 practice_hours must be a positive even number")
    if len(tasks) != total_hours // 2:
        raise WorkOrderContractError(
            "Practice Task Contract 1.1 task count must equal practice_hours / 2: "
            f"expected {total_hours // 2}, got {len(tasks)}"
        )
    task_hours = 0
    for task in tasks:
        item_hours = _hours(task["practice_hours"], f"{task['task_id']}.practice_hours")
        if item_hours != 2:
            raise WorkOrderContractError(
                f"{task['task_id']}.practice_hours must equal 2 for one WorkOrder; got {item_hours}"
            )
        task_hours += item_hours
    if task_hours != total_hours:
        raise WorkOrderContractError(
            f"Practice Task Contract 1.1 practice_hours must equal task sum: expected {total_hours}, got {task_hours}"
        )
    # A compatibility alias is returned to keep migration helpers source-compatible;
    # it is never part of the canonical JSON schema or student-facing output.
    value.setdefault("course_name", profile["course_name"])
    return value


def _compat_aliases(content: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(content)
    profile = value.get("course_profile") if isinstance(value.get("course_profile"), dict) else {}
    if "task_id" in value:
        value.setdefault("practice_task_id", value["task_id"])
    if "task_title" in value:
        value.setdefault("project_name", value["task_title"])
    if profile:
        value.setdefault("course_name", profile.get("course_name", ""))
        value.setdefault("major", profile.get("major", ""))
        value.setdefault("class_or_audience", profile.get("audience", ""))
    return value


def practice_tasks_to_authoring_skeleton(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract upstream facts and an Agent authoring checklist."""

    profile = course_profile_from_contract(contract)
    skeletons: list[dict[str, Any]] = []
    for task in contract["tasks"]:
        skeletons.append(
            {
                "task_id": normalise_text(task["task_id"]),
                "practice_task_id": normalise_text(task["task_id"]),
                "project_id": normalise_text(task["project_id"]),
                "task_title": normalise_text(task["title"]),
                "lesson_ids": [normalise_text(item) for item in task["lesson_ids"]],
                "practice_hours": _hours(task["practice_hours"], f"{task['task_id']}.practice_hours"),
                "course_profile": copy.deepcopy(profile),
                "scenario": normalise_text(task["scenario"]),
                "objectives": [normalise_text(item) for item in task["objectives"]],
                "required_inputs": [normalise_text(item) for item in task["required_inputs"]],
                "tools_or_materials": [normalise_text(item) for item in task["tools_or_materials"]],
                "steps": [normalise_text(item) for item in task["steps"]],
                "deliverables": [normalise_text(item) for item in task["deliverables"]],
                "acceptance_criteria": [normalise_text(item) for item in task["acceptance_criteria"]],
                "safety_or_compliance": [normalise_text(item) for item in task["safety_or_compliance"]],
                "authoring_requirements": {
                    "task_items": "Agent must author 1-5 executable task items and all student-facing prose.",
                    "scores": "Agent assigns positive integer task-item scores from workload and deliverable importance; their sum must be 90.",
                    "content_contract": "Agent must return Practice Work Order Content 1.1 before DOCX generation.",
                    "review": "Agent must review professional accuracy, ordinary 90-minute feasibility, deliverables and acceptance mapping, then rewrite if needed.",
                },
            }
        )
    return skeletons


def _score_split(count: int, total: int = 90) -> list[int]:
    if count < 1 or count > 5:
        raise WorkOrderContractError("a WorkOrder supports 1 to 5 task items")
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _legacy_task_items_from_handoff(task: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [normalise_text(item) for item in task["steps"]]
    if len(steps) > 5:
        steps = steps[:4] + ["；".join(steps[4:])]
    scores = _score_split(len(steps))
    common = [normalise_text(item) for item in task["tools_or_materials"]]
    source_deliverables = [normalise_text(item) for item in task["deliverables"]]
    source_criteria = [normalise_text(item) for item in task["acceptance_criteria"]]
    deliverables = [
        {"deliverable_id": f"D{index}", "text": value}
        for index, value in enumerate(source_deliverables, 1)
    ]
    criteria = [
        {"criterion_id": f"C{index}", "text": value, "covers": [item["deliverable_id"] for item in deliverables]}
        for index, value in enumerate(source_criteria, 1)
    ]
    items: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        items.append(
            {
                "title": step if len(step) <= 72 else f"步骤 {index}",
                "description": format_task_description(
                    scenario=task["scenario"],
                    objectives=task["objectives"],
                    required_inputs=task["required_inputs"],
                    step=step,
                    tools_or_materials=common,
                    deliverables=source_deliverables,
                    acceptance_criteria=source_criteria,
                ),
                "score": scores[index - 1],
                "tools_or_materials": common,
                "steps": [step],
                "deliverables": copy.deepcopy(deliverables),
                "acceptance_criteria": copy.deepcopy(criteria),
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
    """Legacy fixture/migration mapper; never the production authoring path."""

    if not allow_non_production:
        raise WorkOrderContractError(
            "Practice Task handoff is not production WorkOrder Content; Agent must author complete Content 1.1"
        )
    if contract.get("contract_version") == "1.0" or not isinstance(contract.get("course_profile"), dict):
        contract = _legacy_practice_to_v11(contract)
    profile = course_profile_from_contract(contract)
    outputs: list[dict[str, Any]] = []
    for task in contract["tasks"]:
        task_id = normalise_text(task["task_id"])
        content = {
            "content_contract_version": "1.1",
            "mode": "linked",
            "course_profile": copy.deepcopy(profile),
            "task_id": task_id,
            "project_id": normalise_text(task["project_id"]),
            "task_title": normalise_text(task["title"]),
            "lesson_ids": [normalise_text(item) for item in task["lesson_ids"]],
            "granularity": "per_task",
            "practice_hours": 2,
            "group": {
                "name": "第____组",
                "leader_placeholder": "组长：____________",
                "member_placeholder": "成员：____________",
            },
            "task_items": _legacy_task_items_from_handoff(task),
            "safety_or_compliance": [normalise_text(item) for item in task["safety_or_compliance"]],
            "source_task_snapshot": canonical_task_snapshot(task),
            "pedagogical_review": {
                "status": "approved",
                "capacity": "fit",
                "summary": "迁移适配器仅用于测试与迁移，不代表生产内容的人工审阅结论。",
                "checks": {"legacy_adapter": True},
            },
        }
        outputs.append(content)
    return outputs


def canonicalise_content(content: dict[str, Any], *, compatibility: bool = False) -> dict[str, Any]:
    """Return canonical 1.1 content while accepting aliases from migration callers."""

    value = copy.deepcopy(content)
    profile = value.get("course_profile") if isinstance(value.get("course_profile"), dict) else {}
    if compatibility and not profile:
        profile = {
            "course_name": value.get("course_name", ""),
            "major": value.get("major", ""),
            "audience": value.get("class_or_audience", value.get("audience", "")),
            "total_hours": value.get("practice_hours", 2),
            "theory_hours": 0,
            "practice_hours": value.get("practice_hours", 2),
            "delivery_mode": "practice_only",
            "default_lesson_hours": 2,
        }
    elif profile:
        profile = copy.deepcopy(profile)
        if compatibility:
            for alias, field in (("course_name", "course_name"), ("major", "major"), ("class_or_audience", "audience")):
                if alias in value:
                    profile[field] = value[alias]
    value["course_profile"] = profile
    value["task_id"] = value.get("task_id", value.get("practice_task_id", "")) if compatibility else value.get("task_id", "")
    value["task_title"] = value.get("task_title", value.get("project_name", "")) if compatibility else value.get("task_title", "")
    value["project_id"] = value.get("project_id", "")
    value["lesson_ids"] = list(value.get("lesson_ids", []))
    if compatibility:
        value["mode"] = value.get("mode", "standalone")
        value["granularity"] = value.get("granularity", "per_task")
    else:
        value["mode"] = value.get("mode", "")
        value["granularity"] = value.get("granularity", "")
    value["practice_hours"] = _hours(value.get("practice_hours", 0), "practice_hours", allow_zero=True)
    if compatibility:
        value.pop("practice_task_id", None)
        value.pop("course_name", None)
        value.pop("major", None)
        value.pop("class_or_audience", None)
        value.pop("audience", None)
        value.pop("project_name", None)
        value.pop("teacher_evaluation", None)
    for item in value.get("task_items", []):
        if compatibility and isinstance(item, dict):
            deliverables = item.get("deliverables", [])
            if deliverables and isinstance(deliverables[0], str):
                item["deliverables"] = [
                    {"deliverable_id": f"D{index}", "text": str(text)}
                    for index, text in enumerate(deliverables, 1)
                ]
            criteria = item.get("acceptance_criteria", [])
            if criteria and isinstance(criteria[0], str):
                item["acceptance_criteria"] = [
                    {
                        "criterion_id": f"C{index}",
                        "text": str(text),
                        "covers": [item_value["deliverable_id"] for item_value in item.get("deliverables", [])],
                    }
                    for index, text in enumerate(criteria, 1)
                ]
    if compatibility:
        value["content_contract_version"] = "1.1"
        value.setdefault(
            "pedagogical_review",
            {
                "status": "approved",
                "capacity": "fit",
                "summary": "迁移适配器仅用于兼容旧测试数据。",
                "checks": {"legacy_adapter": True},
            },
        )
    return value


def schema_view(content: dict[str, Any], *, compatibility: bool = False) -> dict[str, Any]:
    """Build the schema view without hiding legacy aliases from strict validation."""

    return canonicalise_content(content, compatibility=compatibility)


def validate_canonical_content(content: dict[str, Any]) -> dict[str, Any]:
    """Validate a WorkOrder Content 1.1 object and return its canonical copy."""

    value = canonicalise_content(content)
    errors = _schema_errors(schema_view(value))
    if errors:
        raise WorkOrderContractError(
            "WorkOrder Content 1.1 failed canonical schema validation: " + "; ".join(errors[:8])
        )
    return value


def load_work_order_content(path: Path, *, allow_legacy: bool = False) -> list[dict[str, Any]]:
    """Load canonical Content 1.1; legacy 1.0 is accepted only by migration callers."""

    value = _load_json(path)
    values = value if isinstance(value, list) else [value]
    if not values or not all(isinstance(item, dict) for item in values):
        raise WorkOrderContractError("WorkOrder Content 1.1 input must be an object or a non-empty array")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        if item.get("content_contract_version") == "1.0" and not allow_legacy:
            raise WorkOrderContractError("WorkOrder Content 1.0 is legacy; rerun with --legacy or regenerate as 1.1")
        compatibility = item.get("content_contract_version") == "1.0"
        canonical = canonicalise_content(item, compatibility=compatibility)
        errors = _schema_errors(schema_view(canonical, compatibility=compatibility))
        if errors:
            raise WorkOrderContractError(
                f"WorkOrder Content 1.1 item {index} failed canonical schema validation: " + "; ".join(errors[:8])
            )
        result.append(canonical)
    return result


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
