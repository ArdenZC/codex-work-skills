"""Validation helpers for Practice Class Content Contract 1.0.

This validator intentionally stays focused on teaching relationships: upstream
slide references, task levels, modality-appropriate scaffolds, content-linked
interactions, and the split student/teacher reference contract.  It does not
import the former practice-workorder hardening stack.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "1.0"
LEVELS = ("core", "optional", "challenge")
LEVEL_LABELS = {"core": "核心必做", "optional": "有余力", "challenge": "提高挑战"}
INTERACTION_TYPES = {
    "choice",
    "match",
    "stepper",
    "trace",
    "classify",
    "reorder",
    "diagnose",
    "predict-next",
    "build-relation",
    "state-simulator",
    "compare-strategies",
    "multi-question",
    "scenario-decision",
}
OPTION_INTERACTIONS = {
    "choice",
    "match",
    "diagnose",
    "predict-next",
    "build-relation",
    "compare-strategies",
    "scenario-decision",
}
CODING_MODALITIES = {"coding", "sql", "programming", "mixed"}
MIN_TASKS = 7
MIN_CORE_TASKS = 5
MIN_OPTIONAL_TASKS = 1
MIN_CHALLENGE_TASKS = 1
MIN_CENTER_ZONES = 5
MAX_CENTER_ZONES = 8
MIN_INTERACTION_TYPES = 4
MIN_GUIDE_SECTIONS = 6
MAX_GUIDE_SECTIONS = 10
MIN_KIT_TOPICS = 5
MAX_KIT_TOPICS = 10
MIN_TASK_STEPS = 3
PROCESS_INTERACTIONS = {"stepper", "trace", "state-simulator"}
CONTEXT_STRING_FIELDS = {
    "course_name",
    "audience",
    "language",
    "platform",
    "software",
    "database_dialect",
    "framework",
}
CONTEXT_LIST_FIELDS = {"tools", "other_constraints"}
CONTEXT_FIELDS = CONTEXT_STRING_FIELDS | CONTEXT_LIST_FIELDS


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
        elif value in result:
            errors.append(f"{location} contains duplicate id: {value}")
        else:
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


def _check_slide_refs(values: Any, valid: set[str], location: str, errors: list[str]) -> set[str]:
    """Validate slide reference shape; only reject unknown IDs when an upstream set exists."""

    if not isinstance(values, list) or not values:
        errors.append(f"{location} must be a non-empty list")
        return set()
    refs = {value for value in values if isinstance(value, str)}
    for value in values:
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{location} contains an empty/non-string reference")
        elif valid and value not in valid:
            errors.append(f"{location} references unknown id: {value}")
    return refs


def _validate_course_context(value: Any, location: str, errors: list[str]) -> dict[str, Any] | None:
    """Validate the small, intentionally generic course/toolchain context."""

    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object")
        return None
    extra = sorted(set(value) - CONTEXT_FIELDS)
    errors.extend(f"{location} has unsupported field: {field}" for field in extra)
    for field in sorted(CONTEXT_STRING_FIELDS & set(value)):
        if not _non_empty(value[field]):
            errors.append(f"{location}.{field} must be a non-empty string")
    for field in sorted(CONTEXT_LIST_FIELDS & set(value)):
        values = value[field]
        if not isinstance(values, list) or not values or any(not _non_empty(item) for item in values):
            errors.append(f"{location}.{field} must be a non-empty string list")
    if not value:
        errors.append(f"{location} must contain at least one context field")
    return value


def _courseware_ids(courseware: dict[str, Any] | None, errors: list[str]) -> set[str]:
    if courseware is None:
        return set()
    if not isinstance(courseware, dict):
        errors.append("courseware content must be an object")
        return set()
    if courseware.get("contract_version") != CONTRACT_VERSION:
        errors.append("courseware contract_version must be 1.0")
    _validate_course_context(courseware.get("course_context"), "courseware.course_context", errors)
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


def _validate_options(interaction: dict[str, Any], location: str, errors: list[str]) -> list[dict[str, Any]]:
    options = interaction.get("options")
    if not isinstance(options, list) or len(options) < 2:
        errors.append(f"{location}.options must contain at least two options")
        return []
    for index, option in enumerate(options):
        if not isinstance(option, dict) or not _non_empty(option.get("label")) or not _non_empty(option.get("feedback")):
            errors.append(f"{location}.options[{index}] needs label and feedback")
    answer = interaction.get("answer_index")
    correct_flags = [option.get("correct") is True for option in options if isinstance(option, dict)]
    if answer is None and not any(correct_flags):
        errors.append(f"{location} needs answer_index or one option with correct=true")
    if answer is not None:
        if not isinstance(answer, int) or isinstance(answer, bool):
            errors.append(f"{location}.answer_index must be an integer")
        elif not 0 <= answer < len(options):
            errors.append(f"{location}.answer_index is out of range")
    return options


def _validate_interaction(interaction: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(interaction, dict):
        errors.append(f"{location} must be an object")
        return {}
    kind = interaction.get("type")
    if kind not in INTERACTION_TYPES:
        errors.append(f"{location}.type must be one of {sorted(INTERACTION_TYPES)}")
    if not _non_empty(interaction.get("prompt")):
        errors.append(f"{location}.prompt must be a non-empty string")

    if kind in OPTION_INTERACTIONS:
        _validate_options(interaction, location, errors)
    elif kind in {"stepper", "trace"}:
        steps = interaction.get("steps")
        if not isinstance(steps, list) or len(steps) < 2:
            errors.append(f"{location}.steps must contain at least two steps")
        else:
            for index, step in enumerate(steps):
                if not isinstance(step, dict) or not _non_empty(step.get("title")) or not _non_empty(step.get("text")):
                    errors.append(f"{location}.steps[{index}] needs title and text")
    elif kind == "classify":
        categories = interaction.get("categories")
        if not isinstance(categories, list) or len(categories) < 2 or any(not _non_empty(item) for item in categories):
            errors.append(f"{location}.categories must contain at least two non-empty strings")
        items = interaction.get("items")
        if not isinstance(items, list) or len(items) < 2:
            errors.append(f"{location}.items must contain at least two classification items")
        else:
            for index, item in enumerate(items):
                if not isinstance(item, dict) or not _non_empty(item.get("id")) or not _non_empty(item.get("label")) or not _non_empty(item.get("answer")) or not _non_empty(item.get("feedback")):
                    errors.append(f"{location}.items[{index}] needs id, label, answer and feedback")
                elif isinstance(categories, list) and item["answer"] not in categories:
                    errors.append(f"{location}.items[{index}].answer is not in categories")
    elif kind == "reorder":
        items = interaction.get("items")
        order = interaction.get("correct_order")
        item_ids = [item.get("id") for item in items] if isinstance(items, list) and all(isinstance(item, dict) for item in items) else []
        if not isinstance(items, list) or len(items) < 2 or any(not isinstance(item, dict) or not _non_empty(item.get("id")) or not _non_empty(item.get("label")) for item in items):
            errors.append(f"{location}.items must contain at least two items with id and label")
        if not isinstance(order, list) or order != item_ids or len(set(order)) != len(order):
            errors.append(f"{location}.correct_order must list every item id exactly once")
    elif kind == "state-simulator":
        state = interaction.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("values"), list) or len(state.get("values", [])) < 2 or "target" not in state:
            errors.append(f"{location}.state needs values, target and a non-empty array")
        rounds = interaction.get("rounds")
        required_round_fields = ("left", "right", "mid", "next_left", "next_right", "feedback")
        if not isinstance(rounds, list) or len(rounds) < 2:
            errors.append(f"{location}.rounds must contain at least two rounds")
        else:
            for index, item in enumerate(rounds):
                if not isinstance(item, dict) or any(field not in item for field in required_round_fields) or not _non_empty(item.get("feedback")):
                    errors.append(f"{location}.rounds[{index}] needs interval values and feedback")
                elif any(not isinstance(item[field], int) or isinstance(item[field], bool) for field in required_round_fields[:-1]):
                    errors.append(f"{location}.rounds[{index}] interval values must be integers")
    elif kind == "multi-question":
        questions = interaction.get("questions")
        if not isinstance(questions, list) or len(questions) < 2:
            errors.append(f"{location}.questions must contain at least two questions")
        else:
            for index, question in enumerate(questions):
                q_location = f"{location}.questions[{index}]"
                if not isinstance(question, dict) or not _non_empty(question.get("prompt")):
                    errors.append(f"{q_location}.prompt must be a non-empty string")
                    continue
                _validate_options(question, q_location, errors)
    return interaction


def _validate_teacher_guide(teacher: Any, task_ids: set[str], location: str, errors: list[str]) -> None:
    if not isinstance(teacher, dict):
        errors.append(f"{location} must be an object")
        return
    _required_strings(teacher, ("purpose", "theory_bridge"), location, errors)
    timing = teacher.get("timing")
    if not isinstance(timing, list) or not timing:
        errors.append(f"{location}.timing must be a non-empty list")
    else:
        for index, item in enumerate(timing):
            item_location = f"{location}.timing[{index}]"
            if not isinstance(item, dict) or not isinstance(item.get("minutes"), int) or isinstance(item.get("minutes"), bool) or item["minutes"] <= 0 or not _non_empty(item.get("focus")):
                errors.append(f"{item_location} needs a positive integer minutes and non-empty focus")
    guidance = teacher.get("task_guidance")
    if not isinstance(guidance, list) or not guidance:
        errors.append(f"{location}.task_guidance must be a non-empty list")
    else:
        for index, item in enumerate(guidance):
            item_location = f"{location}.task_guidance[{index}]"
            if not isinstance(item, dict) or item.get("task_id") not in task_ids:
                errors.append(f"{item_location}.task_id references an unknown task")
            elif not _non_empty(item.get("look_for")) or not _non_empty(item.get("ask_when_stuck")):
                errors.append(f"{item_location} needs look_for and ask_when_stuck")
    common_errors = teacher.get("common_errors")
    if not isinstance(common_errors, list) or not common_errors:
        errors.append(f"{location}.common_errors must be a non-empty list")
    else:
        for index, item in enumerate(common_errors):
            if not isinstance(item, dict) or not _non_empty(item.get("symptom")) or not _non_empty(item.get("intervention")):
                errors.append(f"{location}.common_errors[{index}] needs symptom and intervention")
    for field in ("pace_adjustments", "closing_checks"):
        values = teacher.get(field)
        if not isinstance(values, list) or not values or any(not _non_empty(item) for item in values):
            errors.append(f"{location}.{field} must be a non-empty string list")


def _validate_teacher_reference(
    value: Any,
    task_by_id: dict[str, dict[str, Any]],
    knowledge_by_id: dict[str, dict[str, Any]],
    actual_slide_ids: set[str],
    location: str,
    errors: list[str],
) -> None:
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object")
        return
    references = value.get("task_references")
    if not isinstance(references, list) or not references:
        errors.append(f"{location}.task_references must be a non-empty list")
        return
    seen: set[str] = set()
    for index, item in enumerate(references):
        item_location = f"{location}.task_references[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_location} must be an object")
            continue
        _required_strings(item, ("task_id", "title", "reference_answer"), item_location, errors)
        task_id = item.get("task_id")
        if task_id not in task_by_id:
            errors.append(f"{item_location}.task_id references an unknown task")
        elif task_id in seen:
            errors.append(f"{item_location}.task_id is duplicated")
        else:
            seen.add(task_id)
        refs = _check_slide_refs(item.get("source_slide_ids"), actual_slide_ids, f"{item_location}.source_slide_ids", errors)
        if task_id in task_by_id:
            task_refs = set(task_by_id[task_id].get("source_slide_ids", []))
            if refs != task_refs:
                errors.append(f"{item_location}.source_slide_ids must match the task's source_slide_ids")
        for field in ("key_steps", "acceptable_variants", "common_errors", "acceptance_basis"):
            values = item.get(field)
            if not isinstance(values, list) or not values or any(not _non_empty(entry) for entry in values):
                errors.append(f"{item_location}.{field} must be a non-empty string list")
        if "reference_result" in item and not _non_empty(item.get("reference_result")):
            errors.append(f"{item_location}.reference_result must be a non-empty string when present")
    missing = sorted(set(task_by_id) - seen)
    if missing:
        errors.append(f"{location}.task_references is missing tasks: {', '.join(missing)}")


def _validate_editable_gaps(asset: dict[str, Any], location: str, errors: list[str]) -> int:
    """Require every declared starter gap to be a real, locatable edit point.

    A gap is intentionally small and generic: the contract does not prescribe a
    programming language.  The marker and replacement must occur on the same
    source line so a TODO cannot merely describe an already-complete answer.
    """

    gaps = asset.get("editable_gaps", [])
    if gaps is None:
        return 0
    if not isinstance(gaps, list):
        errors.append(f"{location}.editable_gaps must be a list")
        return 0
    content = _text(asset.get("content"))
    seen: set[str] = set()
    for index, gap in enumerate(gaps):
        gap_location = f"{location}.editable_gaps[{index}]"
        if not isinstance(gap, dict):
            errors.append(f"{gap_location} must be an object")
            continue
        _required_strings(gap, ("marker", "replacement", "instruction", "kind"), gap_location, errors)
        marker = gap.get("marker")
        replacement = gap.get("replacement")
        if not isinstance(marker, str) or not marker.strip():
            continue
        if marker in seen:
            errors.append(f"{gap_location}.marker is duplicated")
        seen.add(marker)
        lines = [line for line in content.splitlines() if marker in line]
        if not lines:
            errors.append(f"{gap_location}.marker is not present in starter content")
        elif isinstance(replacement, str) and replacement not in lines[0]:
            errors.append(f"{gap_location}.replacement must occur on the marker's source line")
    return len(gaps)


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
        "interaction_types": [],
        "starter_assets": 0,
        "todo_count": 0,
        "editable_gaps": 0,
        "teacher_references": 0,
        "context_preserved": False,
        "interaction_zones": 0,
        "interaction_type_count": 0,
        "dynamic_interactions": 0,
        "diagnose_interactions": 0,
        "continuous_interactions": 0,
        "guide_sections": 0,
        "foundation_microtopics": 0,
        "core_help_coverage": 0,
    }
    if not isinstance(content, dict):
        return {"status": "fail", "errors": ["practice content root must be an object"], "warnings": [], "metrics": metrics, "source_slide_refs": []}

    allowed = {
        "contract_version", "course_title", "practice_title", "audience", "duration_minutes", "course_context",
        "source_courseware", "knowledge_links", "tasks", "learning_center", "study_guide", "foundation_kit",
        "teacher_guide", "teacher_reference", "starter_assets",
    }
    errors.extend(f"content has unsupported field: {field}" for field in sorted(set(content) - allowed))
    if content.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version must be 1.0")
    _required_strings(content, ("course_title", "practice_title", "audience"), "content", errors)
    _validate_course_context(content.get("course_context"), "course_context", errors)
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
    upstream_context = courseware.get("course_context") if isinstance(courseware, dict) else None
    practice_context = content.get("course_context")
    if upstream_context is not None:
        if practice_context is None:
            errors.append("course_context is required when the upstream Courseware Contract declares it")
        elif isinstance(practice_context, dict):
            context_ok = True
            for field, expected in upstream_context.items():
                if practice_context.get(field) != expected:
                    errors.append(f"course_context.{field} must preserve the upstream Courseware value")
                    context_ok = False
            metrics["context_preserved"] = context_ok

    knowledge = _list(content.get("knowledge_links"))
    if not knowledge:
        errors.append("knowledge_links must contain at least one item")
    knowledge_ids: set[str] = set()
    knowledge_by_id: dict[str, dict[str, Any]] = {}
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
            knowledge_by_id[item_id] = item
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
    if len(tasks) < MIN_TASKS:
        errors.append(f"tasks must contain at least {MIN_TASKS} small activities")
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
        task_source_refs = {
            source_ref
            for item in knowledge
            if isinstance(item, dict) and item.get("id") in refs
            for source_ref in item.get("source_slide_ids", [])
            if isinstance(source_ref, str)
        }
        direct_source_refs = task.get("source_slide_ids")
        if not isinstance(direct_source_refs, list) or not direct_source_refs:
            errors.append(f"{location}.source_slide_ids must be a non-empty list")
            direct_source_refs = []
        direct_source_set: set[str] = set()
        for source_ref in direct_source_refs:
            if not isinstance(source_ref, str) or not source_ref.strip():
                errors.append(f"{location}.source_slide_ids contains an empty reference")
                continue
            direct_source_set.add(source_ref)
            if taught_ids and source_ref not in taught_ids:
                errors.append(f"{location}.source_slide_ids references an untaught slide: {source_ref}")
            if actual_slide_ids and source_ref not in actual_slide_ids:
                errors.append(f"{location}.source_slide_ids references missing slide.id: {source_ref}")
        if direct_source_set != task_source_refs:
            errors.append(f"{location}.source_slide_ids must match the task's knowledge source refs")
        if level == "core" and source.get("mode") == "courseware" and not direct_source_set:
            errors.append(f"{location} core task has no source_slide_ids")
        steps = task.get("steps")
        if not isinstance(steps, list) or len(steps) < MIN_TASK_STEPS:
            errors.append(f"{location}.steps must contain at least {MIN_TASK_STEPS} concrete items")
        else:
            for step_index, step in enumerate(steps):
                _required_strings(step, ("title", "instruction"), f"{location}.steps[{step_index}]", errors)
        for field in ("acceptance", "help_refs"):
            if not isinstance(task.get(field), list) or not task[field]:
                errors.append(f"{location}.{field} must be a non-empty list")
        minutes = task.get("estimated_minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 5:
            errors.append(f"{location}.estimated_minutes must be an integer of at least 5")
        elif level == "core":
            metrics["core_minutes"] += minutes
        if isinstance(minutes, int) and not isinstance(minutes, bool):
            metrics["task_minutes"] += minutes
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
    if metrics["core_tasks"] < MIN_CORE_TASKS:
        errors.append(f"tasks must include at least {MIN_CORE_TASKS} core activities")
    if metrics["optional_tasks"] < MIN_OPTIONAL_TASKS:
        errors.append(f"tasks must include at least {MIN_OPTIONAL_TASKS} optional activity")
    if metrics["challenge_tasks"] < MIN_CHALLENGE_TASKS:
        errors.append(f"tasks must include at least {MIN_CHALLENGE_TASKS} challenge activity")

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
        if isinstance(path, str) and path.lower().endswith(".drawio"):
            try:
                ET.fromstring(_text(asset.get("content")))
            except ET.ParseError as exc:
                errors.append(f"{location}.content must be well-formed draw.io XML: {exc}")
        metrics["editable_gaps"] += _validate_editable_gaps(asset, location, errors)
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
            actual_gaps = sum(len(asset.get("editable_gaps", [])) for asset in assets if isinstance(asset, dict) and asset.get("id") in starter_refs and isinstance(asset.get("editable_gaps", []), list))
            if actual_gaps != task.get("todo_count"):
                errors.append(f"task {task.get('id')} todo_count does not match declared real starter gaps ({actual_gaps})")

    centers = _list(content.get("learning_center"))
    center_ids: set[str] = set()
    interaction_types: set[str] = set()
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
        interaction = _validate_interaction(center.get("interaction"), f"{location}.interaction", errors)
        if isinstance(interaction.get("type"), str):
            interaction_types.add(interaction["type"])
        metrics["interactions"] += 1
    metrics["interaction_types"] = sorted(interaction_types)
    metrics["interaction_zones"] = len(center_ids)
    metrics["interaction_type_count"] = len(interaction_types)
    metrics["dynamic_interactions"] = sum(1 for center in centers if isinstance(center, dict) and center.get("interaction", {}).get("type") in PROCESS_INTERACTIONS)
    metrics["diagnose_interactions"] = sum(1 for center in centers if isinstance(center, dict) and center.get("interaction", {}).get("type") == "diagnose")
    metrics["continuous_interactions"] = sum(1 for center in centers if isinstance(center, dict) and center.get("interaction", {}).get("type") in {"multi-question", "scenario-decision"})
    if len(centers) < MIN_CENTER_ZONES or len(centers) > MAX_CENTER_ZONES:
        errors.append(f"learning_center must contain {MIN_CENTER_ZONES} to {MAX_CENTER_ZONES} distinct experiment zones")
    if len(interaction_types) < MIN_INTERACTION_TYPES:
        errors.append(f"learning_center must use at least {MIN_INTERACTION_TYPES} interaction types")
    if metrics["dynamic_interactions"] < 1:
        errors.append("learning_center needs at least one dynamic process/state interaction")
    if metrics["diagnose_interactions"] < 1:
        errors.append("learning_center needs at least one diagnose/Debug interaction")
    if metrics["continuous_interactions"] < 1:
        errors.append("learning_center needs at least one continuous question or scenario challenge")
    core_task_ids = {task_id for task_id, task in task_by_id.items() if task.get("level") == "core"}
    covered_core_task_ids = {task_id for center in centers if isinstance(center, dict) for task_id in _list(center.get("task_ids"))}
    missing_core_centers = sorted(core_task_ids - covered_core_task_ids)
    if missing_core_centers:
        errors.append("learning_center must cover every core task: " + ", ".join(missing_core_centers))
    for knowledge_id in knowledge_ids:
        knowledge_types = {center.get("interaction", {}).get("type") for center in centers if isinstance(center, dict) and knowledge_id in _list(center.get("knowledge_link_ids"))}
        knowledge_types.discard(None)
        if len(knowledge_types) < 2:
            errors.append(f"knowledge link {knowledge_id} must be practiced in at least two interaction forms")

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
        _check_id_refs(guide.get("task_ids"), task_ids, f"{location}.task_ids", errors)
        _required_strings(guide, ("worked_example",), location, errors)
        for field in ("quick_reference", "common_errors", "checkpoints"):
            values = guide.get(field)
            if not isinstance(values, list) or not values or any(not _non_empty(item) for item in values):
                errors.append(f"{location}.{field} must be a non-empty string list")
        if not isinstance(guide.get("checkpoints"), list) or not guide["checkpoints"]:
            errors.append(f"{location}.checkpoints must be a non-empty list")
    metrics["guide_sections"] = len(guide_ids)
    if len(guides) < MIN_GUIDE_SECTIONS or len(guides) > MAX_GUIDE_SECTIONS:
        errors.append(f"study_guide must contain {MIN_GUIDE_SECTIONS} to {MAX_GUIDE_SECTIONS} task-linked sections")

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
        _check_id_refs(kit.get("task_ids"), task_ids, f"{location}.task_ids", errors)
        _required_strings(kit, ("when_to_use",), location, errors)
        if not isinstance(kit.get("steps"), list) or not kit["steps"]:
            errors.append(f"{location}.steps must be a non-empty list")
        if not isinstance(kit.get("self_check"), list) or not kit["self_check"] or any(not _non_empty(item) for item in kit.get("self_check", [])):
            errors.append(f"{location}.self_check must be a non-empty string list")
    metrics["foundation_microtopics"] = len(kit_ids)
    if len(kits) < MIN_KIT_TOPICS or len(kits) > MAX_KIT_TOPICS:
        errors.append(f"foundation_kit must contain {MIN_KIT_TOPICS} to {MAX_KIT_TOPICS} course-specific microtopics")

    _validate_teacher_guide(content.get("teacher_guide"), task_ids, "teacher_guide", errors)
    _validate_teacher_reference(content.get("teacher_reference"), task_by_id, knowledge_by_id, actual_slide_ids, "teacher_reference", errors)
    if isinstance(content.get("teacher_reference"), dict):
        references = content["teacher_reference"].get("task_references", [])
        metrics["teacher_references"] = len(references) if isinstance(references, list) else 0

    teacher_guide_value = content.get("teacher_guide")
    teacher_guidance = teacher_guide_value.get("task_guidance") if isinstance(teacher_guide_value, dict) else []
    guidance_ids = {item.get("task_id") for item in _list(teacher_guidance) if isinstance(item, dict)}
    metrics["core_help_coverage"] = len(core_task_ids & guidance_ids)
    missing_core_guidance = sorted(core_task_ids - guidance_ids)
    if missing_core_guidance:
        errors.append("teacher_guide.task_guidance must cover every core task: " + ", ".join(missing_core_guidance))

    all_help_refs = [ref for task in task_by_id.values() for ref in _list(task.get("help_refs"))]
    valid_help = guide_ids | kit_ids
    for ref in all_help_refs:
        if ref not in valid_help:
            warnings.append(f"help_refs item is not a study guide or foundation kit id: {ref}")
    if isinstance(duration, int) and metrics["task_minutes"] != duration:
        warnings.append(f"task minutes total {metrics['task_minutes']} differs from class duration {duration}")
    if source.get("mode") == "courseware" and not source_slide_refs:
        errors.append("courseware mode requires at least one source slide reference")

    raw_content = json.dumps(content, ensure_ascii=False)
    if re.search(r"统一提交|提交截图|收走|每组至少交出", raw_content):
        errors.append("default classroom content must not require uniform submission, screenshots, or collection of artifacts")

    # A modeling/tooling or non-C fixture must not accidentally inherit a
    # C/programming scaffold.  This stays generic: it is based on the
    # declared course language, not on a hard-coded course title.
    declared_language = practice_context.get("language") if isinstance(practice_context, dict) else None
    if task_by_id and declared_language != "C":
        raw = json.dumps(content, ensure_ascii=False)
        if re.search(r"C\s*语言|C/C\+\+|#include\s*<|代码模板|binary_search\.py", raw, re.IGNORECASE):
            errors.append("non-C practice content contains C/code-template pollution")

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
