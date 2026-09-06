"""Validation helpers for Practice Class Content Contract 1.0.

The practice skill deliberately keeps this validator small.  It checks the
relationships that make a practice class teachable (theory links, task
levels, scaffolds, and interaction purpose) without importing the old
practice-workorder hardening stack.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "1.0"
LEVELS = ("core", "optional", "challenge")
INTERACTION_TYPES = {"choice", "match", "stepper"}
CODING_MODALITIES = {"coding", "sql", "programming", "mixed"}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique_strings(values: Any, location: str, errors: list[str]) -> set[str]:
    if not isinstance(values, list) or not values:
        errors.append(f"{location} must be a non-empty list")
        return set()
    result: set[str] = set()
    for index, value in enumerate(values):
        if not _non_empty(value):
            errors.append(f"{location}[{index}] must be a non-empty string")
        else:
            if value in result:
                errors.append(f"{location} contains duplicate id: {value}")
            result.add(value)
    return result


def _required_strings(item: Any, fields: tuple[str, ...], location: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{location} must be an object")
        return
    for field in fields:
        if not _non_empty(item.get(field)):
            errors.append(f"{location}.{field} must be a non-empty string")


def _check_id_refs(
    values: Any,
    valid: set[str],
    location: str,
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> set[str]:
    if not isinstance(values, list) or (not values and not allow_empty):
        errors.append(f"{location} must be a {'possibly empty' if allow_empty else 'non-empty'} list")
        return set()
    refs = {value for value in values if isinstance(value, str)}
    for value in values:
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{location} contains an empty/non-string reference")
        elif value not in valid:
            errors.append(f"{location} references unknown id: {value}")
    return refs


def _courseware_ids(courseware: dict[str, Any] | None, errors: list[str]) -> set[str]:
    if courseware is None:
        return set()
    if not isinstance(courseware, dict):
        errors.append("courseware content must be an object")
        return set()
    if courseware.get("contract_version") != CONTRACT_VERSION:
        errors.append("courseware contract_version must be 1.0")
    slides = courseware.get("slides")
    if not isinstance(slides, list) or len(slides) < 2:
        errors.append("courseware slides must contain at least two pages")
        return set()
    ids: set[str] = set()
    for index, slide in enumerate(slides):
        location = f"courseware.slides[{index}]"
        if not isinstance(slide, dict) or not _non_empty(slide.get("id")):
            errors.append(f"{location}.id must be a non-empty string")
            continue
        slide_id = slide["id"]
        if slide_id in ids:
            errors.append(f"courseware contains duplicate slide.id: {slide_id}")
        ids.add(slide_id)
    return ids


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def load_courseware(path: Path) -> dict[str, Any]:
    """Load the upstream Courseware Content Contract and expose its stable IDs."""

    content = load_json(path)
    probe_errors: list[str] = []
    _courseware_ids(content, probe_errors)
    if probe_errors:
        raise ValueError("invalid Courseware Content Contract: " + "; ".join(probe_errors))
    return content


def _validate_interaction(interaction: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(interaction, dict):
        errors.append(f"{location} must be an object")
        return {}
    kind = interaction.get("type")
    if kind not in INTERACTION_TYPES:
        errors.append(f"{location}.type must be one of {sorted(INTERACTION_TYPES)}")
    if not _non_empty(interaction.get("prompt")):
        errors.append(f"{location}.prompt must be a non-empty string")
    if kind in {"choice", "match"}:
        options = interaction.get("options")
        if not isinstance(options, list) or len(options) < 2:
            errors.append(f"{location}.options must contain at least two options")
        else:
            for index, option in enumerate(options):
                if not isinstance(option, dict) or not _non_empty(option.get("label")) or not _non_empty(option.get("feedback")):
                    errors.append(f"{location}.options[{index}] needs label and feedback")
        answer = interaction.get("answer_index")
        if not isinstance(answer, int) or isinstance(answer, bool):
            errors.append(f"{location}.answer_index must be an integer")
        elif isinstance(options, list) and not 0 <= answer < len(options):
            errors.append(f"{location}.answer_index is out of range")
    if kind == "stepper":
        steps = interaction.get("steps")
        if not isinstance(steps, list) or len(steps) < 2:
            errors.append(f"{location}.steps must contain at least two steps")
        else:
            for index, step in enumerate(steps):
                if not isinstance(step, dict) or not _non_empty(step.get("title")) or not _non_empty(step.get("text")):
                    errors.append(f"{location}.steps[{index}] needs title and text")
    return interaction


def validate_content(content: Any, courseware: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a JSON-serialisable structural and relationship QA report."""

    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "knowledge_links": 0,
        "tasks": 0,
        "core_tasks": 0,
        "optional_tasks": 0,
        "challenge_tasks": 0,
        "task_minutes": 0,
        "core_minutes": 0,
        "interactions": 0,
        "starter_assets": 0,
        "todo_count": 0,
    }
    if not isinstance(content, dict):
        return {"status": "fail", "errors": ["practice content root must be an object"], "warnings": [], "metrics": metrics, "source_slide_refs": []}

    allowed = {
        "contract_version", "course_title", "practice_title", "audience", "duration_minutes",
        "source_courseware", "knowledge_links", "tasks", "learning_center", "study_guide",
        "foundation_kit", "teacher_guide", "starter_assets",
    }
    errors.extend(f"content has unsupported field: {field}" for field in sorted(set(content) - allowed))
    if content.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version must be 1.0")
    _required_strings(content, ("course_title", "practice_title", "audience"), "content", errors)
    duration = content.get("duration_minutes")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 30:
        errors.append("duration_minutes must be an integer of at least 30")

    source = content.get("source_courseware")
    if not isinstance(source, dict):
        errors.append("source_courseware must be an object")
        source = {}
    if source.get("mode") not in {"courseware", "independent"}:
        errors.append("source_courseware.mode must be courseware or independent")
    if source.get("contract_version") != CONTRACT_VERSION:
        errors.append("source_courseware.contract_version must be 1.0")
    _required_strings(source, ("chapter_title",), "source_courseware", errors)
    taught_ids = _unique_strings(source.get("taught_slide_ids"), "source_courseware.taught_slide_ids", errors) if source.get("taught_slide_ids") else set()
    if source.get("mode") == "courseware" and not taught_ids:
        errors.append("courseware mode requires taught_slide_ids")
    actual_slide_ids = _courseware_ids(courseware, errors)
    if source.get("mode") == "courseware" and courseware is None:
        errors.append("courseware mode requires the upstream Courseware Content Contract (--courseware-json)")
    if actual_slide_ids:
        missing_taught = sorted(taught_ids - actual_slide_ids)
        if missing_taught:
            errors.append("taught_slide_ids are absent from courseware: " + ", ".join(missing_taught))

    knowledge = _list(content.get("knowledge_links"))
    if not knowledge:
        errors.append("knowledge_links must contain at least one item")
    knowledge_ids: set[str] = set()
    source_slide_refs: set[str] = set()
    for index, item in enumerate(knowledge):
        location = f"knowledge_links[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(item, ("id", "title", "summary", "student_can_do"), location, errors)
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in knowledge_ids:
                errors.append(f"duplicate knowledge link id: {item_id}")
            knowledge_ids.add(item_id)
        refs = item.get("source_slide_ids")
        if not isinstance(refs, list):
            errors.append(f"{location}.source_slide_ids must be a list")
            refs = []
        if source.get("mode") == "courseware" and not refs:
            errors.append(f"{location}.source_slide_ids must not be empty in courseware mode")
        for ref in refs:
            if not isinstance(ref, str) or not ref.strip():
                errors.append(f"{location}.source_slide_ids contains an empty reference")
            else:
                source_slide_refs.add(ref)
                if taught_ids and ref not in taught_ids:
                    errors.append(f"{location}.source_slide_ids references an untaught slide: {ref}")
                if actual_slide_ids and ref not in actual_slide_ids:
                    errors.append(f"{location}.source_slide_ids references missing slide.id: {ref}")
    metrics["knowledge_links"] = len(knowledge_ids)

    tasks = _list(content.get("tasks"))
    if len(tasks) < 3:
        errors.append("tasks must contain at least three items")
    task_ids: set[str] = set()
    task_by_id: dict[str, dict[str, Any]] = {}
    for index, task in enumerate(tasks):
        location = f"tasks[{index}]"
        if not isinstance(task, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(task, ("id", "title", "overview", "scaffold"), location, errors)
        level = task.get("level")
        if level not in LEVELS:
            errors.append(f"{location}.level must be one of {LEVELS}")
        task_id = task.get("id")
        if isinstance(task_id, str):
            if task_id in task_ids:
                errors.append(f"duplicate task id: {task_id}")
            task_ids.add(task_id)
            task_by_id[task_id] = task
        refs = _check_id_refs(task.get("knowledge_link_ids"), knowledge_ids, f"{location}.knowledge_link_ids", errors)
        task["_validated_knowledge_ids"] = sorted(refs)
        task_source_refs = {
            source_ref
            for item in knowledge
            if isinstance(item, dict) and item.get("id") in refs
            for source_ref in item.get("source_slide_ids", [])
            if isinstance(source_ref, str)
        }
        if level == "core" and source.get("mode") == "courseware" and not task_source_refs:
            errors.append(f"{location} core task has no source_slide_ids through its knowledge links")
        steps = task.get("steps")
        if not isinstance(steps, list) or len(steps) < 2:
            errors.append(f"{location}.steps must contain at least two steps")
        else:
            for step_index, step in enumerate(steps):
                _required_strings(step, ("title", "instruction"), f"{location}.steps[{step_index}]", errors)
        for field in ("acceptance", "help_refs"):
            if not isinstance(task.get(field), list) or not task[field]:
                errors.append(f"{location}.{field} must be a non-empty list")
        minutes = task.get("estimated_minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 5:
            errors.append(f"{location}.estimated_minutes must be an integer of at least 5")
        else:
            metrics["task_minutes"] += minutes
            if level == "core":
                metrics["core_minutes"] += minutes
        modality = task.get("modality")
        if not _non_empty(modality):
            errors.append(f"{location}.modality must be a non-empty string")
        if level == "core" and source.get("mode") == "courseware" and not refs:
            errors.append(f"{location} core task must link to taught knowledge")
        if level == "core" and modality in CODING_MODALITIES:
            starter_values = task.get("starter_asset_ids")
            if not isinstance(starter_values, list) or not starter_values:
                errors.append(f"{location}.starter_asset_ids must be a non-empty list")
            todo_count = task.get("todo_count")
            if not isinstance(todo_count, int) or not 2 <= todo_count <= 8:
                errors.append(f"{location}.todo_count must be between 2 and 8 for a coding core task")
        elif not _non_empty(task.get("scaffold")):
            errors.append(f"{location}.scaffold is required for a non-coding task")
    metrics["tasks"] = len(task_ids)
    metrics["core_tasks"] = sum(1 for task in task_by_id.values() if task.get("level") == "core")
    metrics["optional_tasks"] = sum(1 for task in task_by_id.values() if task.get("level") == "optional")
    metrics["challenge_tasks"] = sum(1 for task in task_by_id.values() if task.get("level") == "challenge")
    if not all(metrics[key] > 0 for key in ("core_tasks", "optional_tasks", "challenge_tasks")):
        errors.append("tasks must include at least one core, optional, and challenge task")

    assets = _list(content.get("starter_assets"))
    asset_ids: set[str] = set()
    for index, asset in enumerate(assets):
        location = f"starter_assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(asset, ("id", "path", "language", "task_id", "content"), location, errors)
        asset_id = asset.get("id")
        if isinstance(asset_id, str):
            if asset_id in asset_ids:
                errors.append(f"duplicate starter asset id: {asset_id}")
            asset_ids.add(asset_id)
        if isinstance(asset.get("task_id"), str) and asset["task_id"] not in task_ids:
            errors.append(f"{location}.task_id references unknown task: {asset['task_id']}")
        path = asset.get("path")
        if isinstance(path, str) and (Path(path).is_absolute() or ".." in Path(path).parts):
            errors.append(f"{location}.path must stay inside starter/: {path}")
        metrics["todo_count"] += len(re.findall(r"\bTODO\s+\d+\b", _text(asset.get("content"))))
    metrics["starter_assets"] = len(asset_ids)
    for task in task_by_id.values():
        starter_refs = task.get("starter_asset_ids", [])
        if starter_refs:
            _check_id_refs(starter_refs, asset_ids, f"tasks[{task.get('id')}].starter_asset_ids", errors)
        if task.get("level") == "core" and task.get("modality") in CODING_MODALITIES:
            actual_todo = sum(len(re.findall(r"\bTODO\s+\d+\b", _text(asset.get("content")))) for asset in assets if isinstance(asset, dict) and asset.get("id") in starter_refs)
            if actual_todo != task.get("todo_count"):
                errors.append(f"task {task.get('id')} todo_count does not match starter content ({actual_todo})")

    centers = _list(content.get("learning_center"))
    center_ids: set[str] = set()
    for index, center in enumerate(centers):
        location = f"learning_center[{index}]"
        if not isinstance(center, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(center, ("id", "title", "purpose"), location, errors)
        center_id = center.get("id")
        if isinstance(center_id, str):
            if center_id in center_ids:
                errors.append(f"duplicate learning center id: {center_id}")
            center_ids.add(center_id)
        _check_id_refs(center.get("knowledge_link_ids"), knowledge_ids, f"{location}.knowledge_link_ids", errors)
        _check_id_refs(center.get("task_ids"), task_ids, f"{location}.task_ids", errors)
        _validate_interaction(center.get("interaction"), f"{location}.interaction", errors)
        metrics["interactions"] += 1

    guides = _list(content.get("study_guide"))
    guide_ids: set[str] = set()
    for index, guide in enumerate(guides):
        location = f"study_guide[{index}]"
        if not isinstance(guide, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(guide, ("id", "title", "body"), location, errors)
        guide_id = guide.get("id")
        if isinstance(guide_id, str):
            if guide_id in guide_ids:
                errors.append(f"duplicate study guide id: {guide_id}")
            guide_ids.add(guide_id)
        _check_id_refs(guide.get("knowledge_link_ids"), knowledge_ids, f"{location}.knowledge_link_ids", errors)
        if not isinstance(guide.get("checkpoints"), list) or not guide["checkpoints"]:
            errors.append(f"{location}.checkpoints must be a non-empty list")

    kits = _list(content.get("foundation_kit"))
    kit_ids: set[str] = set()
    for index, kit in enumerate(kits):
        location = f"foundation_kit[{index}]"
        if not isinstance(kit, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(kit, ("id", "title", "kind", "content"), location, errors)
        kit_id = kit.get("id")
        if isinstance(kit_id, str):
            if kit_id in kit_ids:
                errors.append(f"duplicate foundation kit id: {kit_id}")
            kit_ids.add(kit_id)
        if not isinstance(kit.get("steps"), list) or not kit["steps"]:
            errors.append(f"{location}.steps must be a non-empty list")

    teacher = content.get("teacher_guide")
    if not isinstance(teacher, dict):
        errors.append("teacher_guide must be an object")
    else:
        _required_strings(teacher, ("purpose", "theory_bridge"), "teacher_guide", errors)
        for field in ("timing", "task_guidance", "common_errors", "pace_adjustments", "closing_checks"):
            if not isinstance(teacher.get(field), list) or not teacher[field]:
                errors.append(f"teacher_guide.{field} must be a non-empty list")
        for index, item in enumerate(_list(teacher.get("task_guidance"))):
            if not isinstance(item, dict) or item.get("task_id") not in task_ids:
                errors.append(f"teacher_guide.task_guidance[{index}].task_id references an unknown task")

    all_help_refs = [ref for task in task_by_id.values() for ref in _list(task.get("help_refs"))]
    valid_help = guide_ids | kit_ids
    for ref in all_help_refs:
        if ref not in valid_help:
            warnings.append(f"help_refs item is not a study guide or foundation kit id: {ref}")
    if isinstance(duration, int) and metrics["task_minutes"] != duration:
        warnings.append(f"task minutes total {metrics['task_minutes']} differs from class duration {duration}")
    if source.get("mode") == "courseware" and not source_slide_refs:
        errors.append("courseware mode requires at least one source slide reference")

    for task in task_by_id.values():
        task.pop("_validated_knowledge_ids", None)
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "source_slide_refs": sorted(source_slide_refs),
    }


def require_valid(content: dict[str, Any], courseware: dict[str, Any] | None = None) -> dict[str, Any]:
    report = validate_content(content, courseware)
    if report["status"] != "pass":
        raise ValueError("invalid Practice Class Content Contract: " + "; ".join(report["errors"]))
    return report
