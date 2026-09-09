"""Validation helpers for Practice Class Content Contract 1.1.

This validator intentionally stays focused on teaching relationships: upstream
slide references, task levels, modality-appropriate scaffolds, content-linked
interactions, and the split student/teacher reference contract.  It does not
import the former practice-workorder hardening stack.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "1.1"
LEGACY_CONTRACT_VERSION = "1.0"
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
TASK_KINDS = {"observation", "analysis", "implementation", "debugging", "modeling", "tooling", "experiment", "scenario", "mixed"}
CAPABILITIES = {
    "code_editing",
    "file_editing",
    "model_editing",
    "execution",
    "query_execution",
    "diagnosis",
    "state_tracking",
    "visualization",
    "explanation",
    "comparison",
    "scenario_reasoning",
    "tool_operation",
    "experiment",
}
ARTIFACT_KINDS = {"source-code", "query", "model", "document", "workbook", "diagram", "scenario", "result", "mixed", "project"}
VISUALIZATION_KINDS = {
    "sequence-range",
    "timeline",
    "table-state",
    "state-machine",
    "queue",
    "graph-path",
    "comparison",
    "table",
}
REFERENCE_VISUAL_KINDS = {
    "uml-class",
    "uml-sequence",
    "graph",
    "table",
    "timeline",
    "state-machine",
    "comparison",
    "result-preview",
}
# These are legal-contract minima, not Gold content targets.  Quality targets
# are emitted as recommendations below so short workshops and unusual course
# modalities are not rejected merely for having a different shape.
MIN_TASKS = 1
# A Learning Center is an optional modality.  A practice route can be fully
# teachable with core starter assets plus the study guide; interaction zones
# are selected by affordance, not by a quota.
MIN_CENTER_ZONES = 0
MIN_GUIDE_SECTIONS = 1
MIN_KIT_TOPICS = 0
MIN_TASK_STEPS = 1
PROCESS_INTERACTIONS = {"stepper", "trace", "state-simulator"}
RENDERER_FAMILIES = {
    "choice": "choice-family",
    "match": "choice-family",
    "diagnose": "choice-family",
    "predict-next": "choice-family",
    "build-relation": "choice-family",
    "compare-strategies": "choice-family",
    "scenario-decision": "choice-family",
    "stepper": "step-family",
    "trace": "step-family",
    "classify": "classify-family",
    "reorder": "reorder-family",
    "state-simulator": "state-simulator-family",
    "multi-question": "multi-question-family",
}
CONTEXT_STRING_FIELDS = {
    "course_name",
    "audience",
    "language",
    "platform",
    "software",
    "database_dialect",
    "framework",
    "delivery_environment",
}
CONTEXT_LIST_FIELDS = {"tools", "other_constraints"}
CONTEXT_FIELDS = CONTEXT_STRING_FIELDS | CONTEXT_LIST_FIELDS

TOOLCHAIN_FAMILY_PATTERNS = {
    "c-cpp": re.compile(r"(?i)(?:#\s*include\s*[<\"]|\bgcc\b|\bg\+\+\b|\bclang\b|\bdev-c\+\+\b|\bcode::blocks\b|\bcmake\b|\.(?:c|cpp|h|hpp)\b)"),
    "java": re.compile(r"(?i)(?:\bjava\b|\bjavac\b|\bintellij\b|\bmaven\b|\bgradle\b|\.(?:java|jar)\b)"),
    "python": re.compile(r"(?i)(?:\bpython(?:3)?\b|\bpip\b|\bpytest\b|\bflask\b|\bdjango\b|\.(?:py|ipynb)\b)"),
    "sql": re.compile(r"(?i)(?:\bsql\b|\bmysql\b|\bpostgres(?:ql)?\b|\bsqlite\b|\bselect\b.+\bfrom\b)"),
    "uml": re.compile(r"(?i)(?:\bdraw\.io\b|\bstaruml\b|\bplantuml\b|\bmermaid\b|\buml\b|\.drawio\b)"),
}


_COURSEWARE_SCRIPTS = Path(__file__).resolve().parents[3] / "HTML课件生成器" / "courseware-html-generator" / "scripts"
if str(_COURSEWARE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_COURSEWARE_SCRIPTS))
from content_contract import normalize_content as normalize_courseware_content  # noqa: E402


def _legacy_capabilities(task: dict[str, Any]) -> tuple[str, str, list[str], str]:
    modality = str(task.get("modality", "")).casefold()
    if modality in {"coding", "programming"}:
        return "implementation", "source-code", ["code_editing", "execution", "explanation"], "C"
    if modality.startswith("sql"):
        return "implementation", "query", ["file_editing", "query_execution", "explanation"], "B"
    if "debug" in modality or task.get("id", "").casefold().find("debug") >= 0:
        return "debugging", "mixed", ["diagnosis", "explanation"], "B"
    if "model" in modality or "uml" in modality:
        return "modeling", "model", ["model_editing", "visualization", "explanation"], "B"
    if "tool" in modality:
        return "tooling", "document", ["file_editing", "explanation"], "B"
    return "mixed", "mixed", ["explanation"], "B"


def _legacy_task_semantics(task: dict[str, Any], kind: str, artifact: str, capabilities: list[str]) -> None:
    """Populate the new task-kind fields only when migrating a 1.0 contract.

    These values are derived from the legacy task itself; they are not a course
    template and are never used to author a new 1.1 task.
    """

    overview = _text(task.get("overview")) or _text(task.get("title"))
    scaffold = _text(task.get("scaffold")) or overview
    steps = [item.get("instruction") for item in _list(task.get("steps")) if isinstance(item, dict) and _non_empty(item.get("instruction"))]
    acceptance = [str(item) for item in _list(task.get("acceptance")) if _non_empty(item)]
    if kind == "implementation" or "code_editing" in capabilities:
        task.setdefault("edit_targets", [f"按任务要求修改 starter 中的关键空位：{overview}"])
    if kind == "debugging" or "diagnosis" in capabilities:
        task.setdefault("symptom", f"观察现象：{overview}")
        task.setdefault("faulty_artifact", _text(task.get("starter_asset_ids")) or "任务提供的可观察起点")
        task.setdefault("expected_behavior", acceptance[0] if acceptance else "结果应与已讲理论规则一致。")
        task.setdefault("diagnosis_target", "把可观察现象对应到一个可检查的理论或操作原因。")
        task.setdefault("repair_target", "修改造成该现象的关键位置，并用验收条件复核。")
    if kind == "modeling" or "model_editing" in capabilities:
        task.setdefault("editable_model", scaffold)
        task.setdefault("required_edit", overview)
        task.setdefault("modeling_constraints", acceptance or ["只修改本任务明确的对象、关系或属性。"])
    if kind == "tooling" or "tool_operation" in capabilities:
        task.setdefault("tool", "课程声明的工具环境")
        task.setdefault("starting_state", scaffold)
        task.setdefault("operations", steps or ["按任务步骤完成一次可观察操作。"])
        task.setdefault("expected_observable_result", acceptance[0] if acceptance else "记录一个可复核的操作结果。")
    if kind == "experiment" or "experiment" in capabilities:
        task.setdefault("variable", "任务要求观察的变量或条件")
        task.setdefault("control", "保持其他条件不变")
        task.setdefault("operation", steps or ["改变一个条件并执行观察。"])
        task.setdefault("observation", acceptance or ["记录改变条件前后的可见差异。"])
        task.setdefault("expected_reasoning", overview)


def _courseware_semantics(courseware: dict[str, Any] | None) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, Any]]]:
    slide_units: dict[str, set[str]] = {}
    fact_by_id: dict[str, set[str]] = {}
    units_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(courseware, dict):
        return slide_units, fact_by_id, units_by_id
    for unit in courseware.get("learning_units", []):
        if isinstance(unit, dict) and _non_empty(unit.get("id")):
            units_by_id[str(unit["id"])] = unit
    for slide in courseware.get("slides", []):
        if isinstance(slide, dict) and _non_empty(slide.get("id")):
            slide_units[str(slide["id"])] = set(str(ref) for ref in slide.get("learning_unit_ids", []) if isinstance(ref, str))
    for fact in courseware.get("canonical_facts", []):
        if isinstance(fact, dict) and _non_empty(fact.get("id")):
            fact_by_id[str(fact["id"])] = set(str(ref) for ref in fact.get("source_slide_ids", []) if isinstance(ref, str))
    return slide_units, fact_by_id, units_by_id


def _refs_for_slides(slide_refs: Any, slide_units: dict[str, set[str]], fact_by_id: dict[str, set[str]], courseware: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    refs = [str(ref) for ref in slide_refs if isinstance(ref, str)] if isinstance(slide_refs, list) else []
    units = sorted({unit for ref in refs for unit in slide_units.get(ref, set())})
    fact_ids: list[str] = []
    for fact_id, fact_refs in fact_by_id.items():
        if set(refs) & fact_refs:
            fact_ids.append(fact_id)
    return units, sorted(fact_ids)


def _normalize_item_links(item: dict[str, Any], slide_units: dict[str, set[str]], fact_by_id: dict[str, set[str]]) -> None:
    units, facts = _refs_for_slides(item.get("source_slide_ids", []), slide_units, fact_by_id, None)
    item.setdefault("learning_unit_ids", units)
    item.setdefault("canonical_fact_ids", facts)


def normalize_content(content: Any, courseware: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize legacy 1.0 practice JSON to the 1.1 semantic shape."""

    if not isinstance(content, dict):
        return content, {"migrated": False, "from": None, "to": CONTRACT_VERSION}
    normalized = copy.deepcopy(content)
    version = normalized.get("contract_version")
    migration = {"migrated": False, "from": version, "to": CONTRACT_VERSION}
    slide_units, fact_by_id, _ = _courseware_semantics(courseware)
    if version == LEGACY_CONTRACT_VERSION:
        normalized["contract_version"] = CONTRACT_VERSION
        source = normalized.get("source_courseware")
        if isinstance(source, dict):
            source["contract_version"] = CONTRACT_VERSION
        for item in normalized.get("knowledge_links", []):
            if isinstance(item, dict):
                _normalize_item_links(item, slide_units, fact_by_id)
        for task in normalized.get("tasks", []):
            if not isinstance(task, dict):
                continue
            kind, artifact, capabilities, scaffold_level = _legacy_capabilities(task)
            task.setdefault("task_kind", kind)
            task.setdefault("artifact_kind", artifact)
            task.setdefault("capabilities", capabilities)
            task.setdefault("scaffold_level", scaffold_level)
            _legacy_task_semantics(task, kind, artifact, capabilities)
            _normalize_item_links(task, slide_units, fact_by_id)
        for collection_name in ("learning_center", "study_guide", "foundation_kit"):
            for item in normalized.get(collection_name, []):
                if isinstance(item, dict):
                    if "source_slide_ids" in item:
                        _normalize_item_links(item, slide_units, fact_by_id)
                    else:
                        task_ids = set(item.get("task_ids", []))
                        task_by_id = {str(task.get("id")): task for task in normalized.get("tasks", []) if isinstance(task, dict)}
                        slide_refs = [ref for task_id in task_ids for ref in task_by_id.get(task_id, {}).get("source_slide_ids", [])]
                        item.setdefault("learning_unit_ids", sorted({unit for ref in slide_refs for unit in slide_units.get(ref, set())}))
                        item.setdefault("canonical_fact_ids", sorted({fact for fact, refs in fact_by_id.items() if set(slide_refs) & refs}))
                    interaction = item.get("interaction")
                    if isinstance(interaction, dict) and isinstance(interaction.get("state_visual"), dict):
                        visual = copy.deepcopy(interaction["state_visual"])
                        visual.setdefault("kind", "sequence-range")
                        interaction.setdefault("visualization", visual)
        for asset in normalized.get("starter_assets", []):
            if isinstance(asset, dict) and "student_instruction" not in asset and "instruction" in asset:
                asset["student_instruction"] = asset["instruction"]
        references = normalized.get("teacher_reference", {}).get("task_references", []) if isinstance(normalized.get("teacher_reference"), dict) else []
        task_by_id = {str(task.get("id")): task for task in normalized.get("tasks", []) if isinstance(task, dict)}
        for reference in references:
            if not isinstance(reference, dict):
                continue
            task = task_by_id.get(str(reference.get("task_id")), {})
            ref_obj = reference.get("model_visual")
            if isinstance(ref_obj, dict):
                converted = copy.deepcopy(ref_obj)
                converted["kind"] = "uml-sequence" if converted.get("messages") else "uml-class"
                reference.setdefault("reference_visual", converted)
            reference.setdefault("learning_unit_ids", task.get("learning_unit_ids", []))
            reference.setdefault("canonical_fact_ids", task.get("canonical_fact_ids", []))
        migration["migrated"] = True
    return normalized, migration


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


def _required_string_list(item: Any, field: str, location: str, errors: list[str]) -> None:
    values = item.get(field) if isinstance(item, dict) else None
    if not isinstance(values, list) or not values or any(not _non_empty(value) for value in values):
        errors.append(f"{location}.{field} must be a non-empty string list")


def _validate_time_breakdown(value: Any, location: str, errors: list[str]) -> None:
    """Validate optional, human-authored time evidence without requiring it."""

    if value is None:
        return
    if not isinstance(value, list) or not value:
        errors.append(f"{location} must be a non-empty list when present")
        return
    for index, item in enumerate(value):
        item_location = f"{location}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_location} must be an object")
            continue
        if not _non_empty(item.get("step")):
            errors.append(f"{item_location}.step must be a non-empty string")
        minutes = item.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            errors.append(f"{item_location}.minutes must be a positive integer")


def _required_task_semantics(task: dict[str, Any], location: str, task_kind: Any, capabilities: list[str], errors: list[str]) -> None:
    """Apply modality-specific completeness rules to new 1.1 tasks."""

    code_task = task_kind == "implementation" or "code_editing" in capabilities
    debug_task = task_kind == "debugging" or "diagnosis" in capabilities
    model_task = task_kind == "modeling" or "model_editing" in capabilities
    tool_task = task_kind == "tooling" or "tool_operation" in capabilities
    experiment_task = task_kind == "experiment" or "experiment" in capabilities
    if code_task:
        values = task.get("starter_asset_ids")
        if not isinstance(values, list) or not values:
            errors.append(f"{location}.starter_asset_ids is required for implementation/code_editing tasks")
        _required_string_list(task, "edit_targets", location, errors)
    if debug_task:
        _required_strings(task, ("symptom", "faulty_artifact", "expected_behavior", "diagnosis_target", "repair_target"), location, errors)
    if model_task:
        _required_strings(task, ("editable_model", "required_edit"), location, errors)
        _required_string_list(task, "modeling_constraints", location, errors)
    if tool_task:
        _required_strings(task, ("tool", "starting_state", "expected_observable_result"), location, errors)
        _required_string_list(task, "operations", location, errors)
    if experiment_task:
        _required_strings(task, ("variable", "control", "expected_reasoning"), location, errors)
        _required_string_list(task, "operation", location, errors)
        _required_string_list(task, "observation", location, errors)


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


def _validate_semantic_links(
    item: dict[str, Any],
    location: str,
    task_by_id: dict[str, dict[str, Any]],
    unit_ids: set[str],
    fact_ids: set[str],
    errors: list[str],
    *,
    task_field: str = "task_ids",
) -> tuple[set[str], set[str]]:
    """Check that a teaching surface carries the same semantic trail as its tasks."""

    linked_units = _check_id_refs(item.get("learning_unit_ids"), unit_ids, f"{location}.learning_unit_ids", errors)
    linked_facts = _check_id_refs(item.get("canonical_fact_ids", []), fact_ids, f"{location}.canonical_fact_ids", errors, allow_empty=True)
    expected_units: set[str] = set()
    expected_facts: set[str] = set()
    for task_id in _list(item.get(task_field)):
        task = task_by_id.get(str(task_id))
        if isinstance(task, dict):
            expected_units.update(ref for ref in task.get("learning_unit_ids", []) if isinstance(ref, str))
            expected_facts.update(ref for ref in task.get("canonical_fact_ids", []) if isinstance(ref, str))
    missing_units = expected_units - linked_units
    missing_facts = expected_facts - linked_facts
    if missing_units:
        errors.append(f"{location}.learning_unit_ids must cover linked tasks: {', '.join(sorted(missing_units))}")
    if missing_facts:
        errors.append(f"{location}.canonical_fact_ids must cover linked tasks: {', '.join(sorted(missing_facts))}")
    return linked_units, linked_facts


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


def _declared_toolchain_families(context: dict[str, Any] | None) -> set[str]:
    if not isinstance(context, dict):
        return set()
    raw = json.dumps(context, ensure_ascii=False).casefold()
    declared: set[str] = set()
    language = str(context.get("language", "")).casefold()
    if "java" in language:
        declared.add("java")
    if "python" in language:
        declared.add("python")
    if "sql" in language or "mysql" in raw or "postgres" in raw or "sqlite" in raw:
        declared.add("sql")
    if "uml" in language or "model" in language or any(token in raw for token in ("draw.io", "staruml", "plantuml", "mermaid")):
        declared.add("uml")
    if re.search(r"c\+\+|c/c\+\+|cpp|g\+\+", raw):
        declared.add("c-cpp")
    elif re.search(r"(?i)\blanguage\"\s*:\s*\"c\"|\bdev-c\+\+\b|\bgcc\b|\bclang\b", raw):
        declared.add("c-cpp")
    return declared


def _toolchain_compatibility_errors(content: dict[str, Any], context: dict[str, Any] | None) -> list[str]:
    """Detect incompatible toolchain fragments without a course-specific ban list."""

    if not isinstance(context, dict):
        return []
    raw = json.dumps(content, ensure_ascii=False)
    declared = _declared_toolchain_families(context)
    if not declared:
        return []
    errors: list[str] = []
    context_raw = json.dumps(context, ensure_ascii=False)
    language = str(context.get("language", "")).casefold()
    if "java" in language and re.search(r"(?i)(?:gcc|g\+\+|clang|dev-c\+\+|code::blocks)", context_raw):
        errors.append("Java course context cannot declare a GCC/Dev-C++/C++ toolchain")
    for family, pattern in TOOLCHAIN_FAMILY_PATTERNS.items():
        if pattern.search(raw) and family not in declared:
            errors.append(f"practice content contains {family} toolchain material incompatible with declared course context")
    return errors


def _courseware_ids(courseware: dict[str, Any] | None, errors: list[str]) -> set[str]:
    if courseware is None:
        return set()
    if not isinstance(courseware, dict):
        errors.append("courseware content must be an object")
        return set()
    if courseware.get("contract_version") != "1.1":
        errors.append("courseware contract_version must be 1.1 after migration")
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

    raw = load_json(path)
    content, _ = normalize_courseware_content(raw)
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
    for field in ("success_feedback", "retry_feedback", "completion_feedback"):
        if field in interaction and not _non_empty(interaction.get(field)):
            errors.append(f"{location}.{field} must be a non-empty string when present")

    estimated = interaction.get("estimated_minutes")
    if estimated is not None and (not isinstance(estimated, int) or isinstance(estimated, bool) or estimated < 1):
        errors.append(f"{location}.estimated_minutes must be a positive integer when present")

    comparison = interaction.get("comparison")
    if comparison is not None:
        if not isinstance(comparison, dict):
            errors.append(f"{location}.comparison must be an object when present")
        else:
            parameters = comparison.get("parameters")
            series = comparison.get("series")
            if not isinstance(parameters, list) or len(parameters) < 2 or any(not isinstance(item, dict) or not _non_empty(item.get("id")) or not _non_empty(item.get("label")) or not _non_empty(item.get("explanation")) for item in parameters):
                errors.append(f"{location}.comparison.parameters must contain labelled explanations")
            if not isinstance(series, list) or len(series) < 2:
                errors.append(f"{location}.comparison.series must contain at least two series")
            else:
                expected_count = len(parameters) if isinstance(parameters, list) else 0
                for index, item in enumerate(series):
                    if not isinstance(item, dict) or not _non_empty(item.get("id")) or not _non_empty(item.get("label")) or not isinstance(item.get("counts"), list) or len(item["counts"]) != expected_count:
                        errors.append(f"{location}.comparison.series[{index}] needs one numeric count per parameter")
                    elif any(not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 for value in item["counts"]):
                        errors.append(f"{location}.comparison.series[{index}].counts must be non-negative numbers")

    if kind in OPTION_INTERACTIONS and not (kind == "diagnose" and "diagnostic_cases" in interaction):
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
        if not isinstance(order, list) or len(order) != len(item_ids) or set(order) != set(item_ids) or len(set(order)) != len(order):
            errors.append(f"{location}.correct_order must list every item id exactly once")
        elif order == item_ids:
            errors.append(f"{location}.items must start in an intentionally incorrect order")
    elif kind == "state-simulator":
        fields = interaction.get("state_fields")
        field_ids: list[str] = []
        if not isinstance(fields, list) or not fields:
            errors.append(f"{location}.state_fields must contain at least one field")
        else:
            for index, field in enumerate(fields):
                field_location = f"{location}.state_fields[{index}]"
                if not isinstance(field, dict) or not _non_empty(field.get("id")) or not _non_empty(field.get("label")):
                    errors.append(f"{field_location} needs id and label")
                    continue
                if field["id"] in field_ids:
                    errors.append(f"{field_location}.id is duplicated")
                field_ids.append(field["id"])
        state = interaction.get("state")
        if state is not None and not isinstance(state, dict):
            errors.append(f"{location}.state must be an object when present")
        rounds = interaction.get("rounds")
        if not isinstance(rounds, list) or not rounds:
            errors.append(f"{location}.rounds must contain at least one round")
        else:
            for index, item in enumerate(rounds):
                round_location = f"{location}.rounds[{index}]"
                if not isinstance(item, dict) or not isinstance(item.get("given"), dict) or not isinstance(item.get("expected"), dict) or not _non_empty(item.get("feedback")):
                    errors.append(f"{round_location} needs given, expected and feedback")
                    continue
                if item.get("status") not in {"continue", "found", "not-found"}:
                    errors.append(f"{round_location}.status must be continue, found or not-found")
                for field_name in ("given", "expected"):
                    value = item.get(field_name, {})
                    if not value:
                        errors.append(f"{round_location}.{field_name} must contain at least one field")
                    unknown = sorted(set(value) - set(field_ids))
                    if unknown:
                        errors.append(f"{round_location}.{field_name} references unknown state fields: {', '.join(unknown)}")
                if item.get("status") == "continue":
                    next_expected = item.get("next_expected")
                    if not isinstance(next_expected, dict) or not next_expected:
                        errors.append(f"{round_location} with status=continue needs next_expected")
                    elif set(next_expected) - set(field_ids):
                        errors.append(f"{round_location}.next_expected references unknown state fields")
                elif "next_expected" in item:
                    errors.append(f"{round_location} terminal state must not declare next_expected")
                if item.get("status") != "continue" and index != len(rounds) - 1:
                    errors.append(f"{round_location} is terminal but later rounds still exist")
                if index < len(rounds) - 1 and item.get("status") == "continue":
                    following = rounds[index + 1]
                    if isinstance(following, dict) and isinstance(item.get("next_expected"), dict):
                        if following.get("given") != item["next_expected"]:
                            errors.append(f"{round_location}.next_expected does not match the following round's given state")
            if isinstance(rounds[-1], dict) and rounds[-1].get("status") == "continue":
                errors.append(f"{location}.rounds must end with a terminal status")
        visual = interaction.get("visualization")
        if visual is None:
            visual = interaction.get("state_visual")
        if visual is not None:
            if not isinstance(visual, dict):
                errors.append(f"{location}.visualization must be an object when present")
            else:
                visual_kind = visual.get("kind", "table")
                if visual_kind not in VISUALIZATION_KINDS:
                    errors.append(f"{location}.visualization.kind must be one of {sorted(VISUALIZATION_KINDS)}")
                items = visual.get("items")
                if not isinstance(items, list) or not items:
                    errors.append(f"{location}.visualization.items must contain at least one item")
                else:
                    for index, item in enumerate(items):
                        if not isinstance(item, dict) or not _non_empty(item.get("label")) or "value" not in item:
                            errors.append(f"{location}.visualization.items[{index}] needs label and value")
                if visual_kind == "sequence-range":
                    for field_name in ("start_field", "end_field", "focus_field"):
                        if not _non_empty(visual.get(field_name)) or visual.get(field_name) not in field_ids:
                            errors.append(f"{location}.visualization.{field_name} must name a state field")
    elif kind == "diagnose":
        cases = interaction.get("diagnostic_cases")
        if cases is not None:
            if not isinstance(cases, list) or len(cases) < 2:
                errors.append(f"{location}.diagnostic_cases must contain at least two cases")
            else:
                for index, case in enumerate(cases):
                    case_location = f"{location}.diagnostic_cases[{index}]"
                    if not isinstance(case, dict) or not _non_empty(case.get("id")) or not _non_empty(case.get("title")):
                        errors.append(f"{case_location} needs id and title")
                        continue
                    for option_name in ("error_options", "fix_options"):
                        options = case.get(option_name)
                        if not isinstance(options, list) or len(options) < 2:
                            errors.append(f"{case_location}.{option_name} must contain at least two options")
                        else:
                            _validate_options({"options": options, "answer_index": case.get("error_answer_index" if option_name == "error_options" else "fix_answer_index")}, f"{case_location}.{option_name}", errors)
                    for answer_name in ("error_answer_index", "fix_answer_index"):
                        if not isinstance(case.get(answer_name), int):
                            errors.append(f"{case_location}.{answer_name} must be an integer")
        else:
            options = interaction.get("options")
            if not isinstance(options, list) or len(options) < 2:
                errors.append(f"{location}.options must contain at least two diagnostic options")
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
    courseware_unit_ids: set[str],
    courseware_fact_ids: set[str],
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
            expected_units = set(task_by_id[task_id].get("learning_unit_ids", []))
            expected_facts = set(task_by_id[task_id].get("canonical_fact_ids", []))
            if courseware_unit_ids:
                linked_units = _check_id_refs(item.get("learning_unit_ids"), courseware_unit_ids, f"{item_location}.learning_unit_ids", errors)
                if expected_units - linked_units:
                    errors.append(f"{item_location}.learning_unit_ids must cover the task's learning units: {', '.join(sorted(expected_units - linked_units))}")
            if courseware_fact_ids:
                linked_facts = _check_id_refs(item.get("canonical_fact_ids", []), courseware_fact_ids, f"{item_location}.canonical_fact_ids", errors, allow_empty=True)
                if expected_facts - linked_facts:
                    errors.append(f"{item_location}.canonical_fact_ids must cover the task's canonical facts: {', '.join(sorted(expected_facts - linked_facts))}")
        visual = item.get("reference_visual")
        if visual is None:
            visual = item.get("model_visual")
        if visual is not None:
            if not isinstance(visual, dict):
                errors.append(f"{item_location}.reference_visual must be an object when present")
            else:
                kind = visual.get("kind", "table")
                if kind not in REFERENCE_VISUAL_KINDS:
                    errors.append(f"{item_location}.reference_visual.kind must be one of {sorted(REFERENCE_VISUAL_KINDS)}")
                if not _non_empty(visual.get("title")):
                    errors.append(f"{item_location}.reference_visual.title is required")
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
    """Require a real student marker without leaking the teacher replacement."""

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
        patch_kind = gap.get("patch_kind", "replace-expression")
        required_gap_fields = ("replacement", "student_instruction", "kind") if patch_kind == "add-file" else ("marker", "replacement", "student_instruction", "kind")
        _required_strings(gap, required_gap_fields, gap_location, errors)
        marker = gap.get("marker")
        replacement = gap.get("replacement")
        if not isinstance(marker, str) or not marker.strip():
            continue
        if marker in seen:
            errors.append(f"{gap_location}.marker is duplicated")
        seen.add(marker)
        positions = [index for index, line in enumerate(content.splitlines()) if marker in line]
        if not positions and gap.get('patch_kind') != 'add-file':
            errors.append(f"{gap_location}.marker is not present in starter content")
            continue
        if not isinstance(replacement, str) or not replacement.strip():
            continue
        lines = content.splitlines()
        # The marker line is the actionable student surface, but a complete
        # replacement must not be present anywhere in the student starter.
        # Checking the full content closes the leak when an answer is copied to
        # a nearby comment or a second line instead of the marker line.
        if replacement.casefold() in content.casefold():
            errors.append(f"{gap_location}.replacement leaks into the student starter")
        target = gap.get("target")
        if target is not None and (not isinstance(target, str) or not target):
            errors.append(f"{gap_location}.target must be a non-empty string when present")
        if isinstance(target, str) and target not in content:
            errors.append(f"{gap_location}.target is not present in starter content")
        instruction = gap.get("student_instruction")
        if isinstance(instruction, str) and replacement.casefold() in instruction.casefold():
            errors.append(f"{gap_location}.student_instruction leaks the complete replacement")
    return len(gaps)


REFERENCE_TYPES = {
    "syntax",
    "command",
    "function-call",
    "web-request",
    "file-output",
    "query-result",
    "structured-data",
    "browser",
    "manual-evidence",
}
INTEGRITY_ROLES = {"student-edit", "student-input", "runtime-required", "generated-scaffold", "teacher-reference", "test-only"}
PUBLIC_ASSET_ROLES = {"student-edit", "student-input", "runtime-required", "generated-scaffold"}
INTEGRITY_CLASSIFICATIONS = {"source-only-reference", "teacher-only-material", "student-classroom-input", "generated-starter-seed"}


def _validate_formula_fact_shapes(facts: Any, location: str, errors: list[str]) -> None:
    if facts is None:
        return
    if not isinstance(facts, list):
        errors.append(f"{location} must be a list")
        return
    seen: set[str] = set()
    for index, fact in enumerate(facts):
        item_location = f"{location}[{index}]"
        if not isinstance(fact, dict):
            errors.append(f"{item_location} must be an object")
            continue
        _required_strings(fact, ("id", "formula"), item_location, errors)
        fact_id = fact.get("id")
        if isinstance(fact_id, str):
            if fact_id in seen:
                errors.append(f"{item_location}.id is duplicated")
            seen.add(fact_id)
        if fact.get("example_scope") not in {"abstract", "current-dataset"}:
            errors.append(f"{item_location}.example_scope must be abstract or current-dataset")
        if not _text(fact.get("formula")).strip().startswith("="):
            errors.append(f"{item_location}.formula must start with =")
        if fact.get("example_scope") == "current-dataset":
            _required_strings(fact, ("source_id", "semantic_intent", "operation_location"), item_location, errors)
            bindings = fact.get("bindings")
            if not isinstance(bindings, dict) or not (bindings.get("input_field") or bindings.get("input_fields")):
                errors.append(f"{item_location}.bindings must declare input_field or input_fields")


def _validate_reference_verification(task: dict[str, Any], location: str, errors: list[str], *, integrity: bool) -> None:
    capabilities = set(task.get("required_capabilities", task.get("capabilities", [])))
    kind = task.get("task_kind", task.get("type"))
    required = kind in {"implementation", "debugging", "code_editing", "execution"} or bool(capabilities & {"implementation", "debugging", "code_editing", "execution"})
    verification = task.get("reference_verification")
    if not integrity and not verification:
        return
    if required and not isinstance(verification, dict):
        errors.append(f"{location}.reference_verification is required for executable tasks")
        return
    if verification is None:
        return
    if verification.get("kind") not in {"behavioral", "manual"}:
        errors.append(f"{location}.reference_verification.kind must be behavioral or manual")
    checks = verification.get("checks")
    if not isinstance(checks, list) or not checks:
        errors.append(f"{location}.reference_verification.checks must be non-empty")
        return
    ids: set[str] = set()
    types: list[str] = []
    for index, check in enumerate(checks):
        check_location = f"{location}.reference_verification.checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{check_location} must be an object")
            continue
        _required_strings(check, ("id", "verification_type"), check_location, errors)
        check_id = check.get("id")
        if isinstance(check_id, str):
            if check_id in ids:
                errors.append(f"{check_location}.id is duplicated")
            ids.add(check_id)
        verification_type = check.get("verification_type")
        types.append(str(verification_type))
        if verification_type not in REFERENCE_TYPES:
            errors.append(f"{check_location}.verification_type is unsupported")
        if verification_type in {"browser", "manual-evidence"}:
            for field in ("procedure", "observation", "expected_result"):
                if not _non_empty(check.get(field)):
                    errors.append(f"{check_location}.{field} is required for manual evidence")
    if required and set(types) <= {"syntax"}:
        errors.append(f"{location}.reference_verification needs behavioral evidence, not syntax alone")
    if verification.get("required_scenarios") is not None:
        scenarios = verification.get("required_scenarios")
        if not isinstance(scenarios, list) or any(not _non_empty(item) for item in scenarios):
            errors.append(f"{location}.reference_verification.required_scenarios must be a string list")


def _validate_g3_assets(content: dict[str, Any], task_ids: set[str], errors: list[str]) -> None:
    assets = [item for item in content.get("starter_assets", []) if isinstance(item, dict)]
    assets_by_id = {str(item.get("id")): item for item in assets if item.get("id")}
    for index, bundle in enumerate(content.get("starter_bundles", [])):
        location = f"starter_bundles[{index}]"
        if not isinstance(bundle, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(bundle, ("id", "root", "entrypoint"), location, errors)
        if bundle.get("artifact_kind") != "project":
            errors.append(f"{location}.artifact_kind must be project")
        files = bundle.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"{location}.files must be non-empty")
            continue
        seen: set[str] = set()
        public = set()
        for file_index, item in enumerate(files):
            file_location = f"{location}.files[{file_index}]"
            if not isinstance(item, dict):
                errors.append(f"{file_location} must be an object")
                continue
            _required_strings(item, ("path", "role"), file_location, errors)
            role = item.get("role")
            if role not in INTEGRITY_ROLES:
                errors.append(f"{file_location}.role is unsupported")
            path = str(item.get("path", ""))
            if path.casefold() in seen:
                errors.append(f"{file_location}.path is duplicated")
            seen.add(path.casefold())
            if role in PUBLIC_ASSET_ROLES:
                public.add(path.casefold())
                if item.get("asset_id") and str(item.get("asset_id")) not in {str(asset.get("id")) for asset in assets}:
                    errors.append(f"{file_location}.asset_id references an unknown starter asset")
                candidates = {path.replace("\\", "/"), f"{str(bundle.get('root', '')).replace('starter/', '').strip('/')}/{path}".strip('/')}
                if not item.get("asset_id") and not any(str(asset.get("path", "")).replace("\\", "/").strip("/").casefold() in {candidate.casefold() for candidate in candidates} for asset in assets):
                    errors.append(f"{file_location} needs a starter_assets entry or asset_id")
        entrypoint = str(bundle.get("entrypoint", ""))
        if entrypoint and entrypoint.casefold() not in public:
            errors.append(f"{location}.entrypoint must refer to a student bundle file")
    for index, asset in enumerate(assets):
        role = asset.get("role", "student-edit")
        if role not in INTEGRITY_ROLES:
            errors.append(f"starter_assets[{index}].role is unsupported")
    for index, item in enumerate(content.get("classroom_assets", [])):
        location = f"classroom_assets[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(item, ("id", "title", "task_id", "source_path", "sha256", "classification"), location, errors)
        if item.get("task_id") not in task_ids:
            errors.append(f"{location}.task_id references an unknown task")
        if item.get("classification") not in INTEGRITY_CLASSIFICATIONS:
            errors.append(f"{location}.classification is unsupported")
        if item.get("classification") in {"student-classroom-input", "generated-starter-seed"} and not _non_empty(item.get("student_path")):
            errors.append(f"{location}.student_path is required for student classroom input")
    for index, dep in enumerate(content.get("runtime_dependencies", [])):
        if not isinstance(dep, dict) or not _non_empty(dep.get("path")):
            errors.append(f"runtime_dependencies[{index}].path is required")


def validate_content(
    content: Any,
    courseware: dict[str, Any] | None = None,
    *,
    enforce_task_semantics: bool = True,
) -> dict[str, Any]:
    """Return a JSON-serialisable structural and relationship QA report."""

    if isinstance(courseware, dict):
        courseware, _ = normalize_courseware_content(courseware)
    content, migration = normalize_content(content, courseware)

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
        "time_breakdown_tasks": 0,
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
        "renderer_families": [],
        "renderer_family_count": 0,
        "terminal_simulators": 0,
        "guide_sections": 0,
        "foundation_microtopics": 0,
        "core_help_coverage": 0,
        "interaction_estimated_minutes": 0,
        "quality_recommendations": [],
        "learning_units": 0,
        "canonical_facts": 0,
        "support_path_coverage": 0,
        "capability_errors": 0,
        "starter_leakage_errors": 0,
    }
    if not isinstance(content, dict):
        return {"status": "fail", "errors": ["practice content root must be an object"], "warnings": [], "metrics": metrics, "source_slide_refs": [], "migration": migration}

    allowed = {
        "contract_version", "course_title", "practice_title", "audience", "duration_minutes", "course_context",
        "source_courseware", "knowledge_links", "tasks", "learning_center", "study_guide", "foundation_kit",
        "teacher_guide", "teacher_reference", "starter_assets", "integrity_version", "formula_facts",
        "starter_bundles", "classroom_assets", "runtime_dependencies", "paper_work_authorization", "spreadsheet_workflow",
    }
    errors.extend(f"content has unsupported field: {field}" for field in sorted(set(content) - allowed))
    if content.get("contract_version") != CONTRACT_VERSION:
        errors.append(f"contract_version must be {CONTRACT_VERSION}")
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
    if source.get("contract_version") != "1.1":
        errors.append("source_courseware.contract_version must be 1.1 after migration")
    _required_strings(source, ("chapter_title",), "source_courseware", errors)
    taught_ids = _unique_strings(source.get("taught_slide_ids"), "source_courseware.taught_slide_ids", errors) if source.get("taught_slide_ids") else set()
    if source.get("mode") == "courseware" and not taught_ids:
        errors.append("courseware mode requires taught_slide_ids")
    actual_slide_ids = _courseware_ids(courseware, errors)
    slide_units, fact_by_slide, courseware_units = _courseware_semantics(courseware)
    courseware_unit_ids = set(courseware_units)
    courseware_fact_ids = set(fact_by_slide)
    metrics["learning_units"] = len(courseware_unit_ids)
    metrics["canonical_facts"] = len(courseware_fact_ids)
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
        linked_units = _check_id_refs(item.get("learning_unit_ids"), courseware_unit_ids, f"{location}.learning_unit_ids", errors) if source.get("mode") == "courseware" else set()
        linked_facts = _check_id_refs(item.get("canonical_fact_ids", []), courseware_fact_ids, f"{location}.canonical_fact_ids", errors, allow_empty=True) if courseware is not None else set()
        if source.get("mode") == "courseware":
            expected_units = {unit for ref in refs for unit in slide_units.get(ref, set())}
            if expected_units - linked_units:
                errors.append(f"{location}.learning_unit_ids must cover the units behind source_slide_ids: {', '.join(sorted(expected_units - linked_units))}")
            expected_facts = {fact_id for fact_id, fact_refs in fact_by_slide.items() if set(refs) & fact_refs}
            if expected_facts - linked_facts:
                errors.append(f"{location}.canonical_fact_ids must cover the facts behind source_slide_ids: {', '.join(sorted(expected_facts - linked_facts))}")
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
        task_units = _check_id_refs(task.get("learning_unit_ids"), courseware_unit_ids, f"{location}.learning_unit_ids", errors) if source.get("mode") == "courseware" else set()
        task_facts = _check_id_refs(task.get("canonical_fact_ids", []), courseware_fact_ids, f"{location}.canonical_fact_ids", errors, allow_empty=True) if courseware is not None else set()
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
        if source.get("mode") == "courseware":
            expected_units = {unit for ref in direct_source_set for unit in slide_units.get(ref, set())}
            if expected_units - task_units:
                errors.append(f"{location}.learning_unit_ids must cover the units behind source_slide_ids: {', '.join(sorted(expected_units - task_units))}")
            expected_facts = {fact_id for fact_id, fact_refs in fact_by_slide.items() if direct_source_set & fact_refs}
            if expected_facts - task_facts:
                errors.append(f"{location}.canonical_fact_ids must cover the facts behind source_slide_ids: {', '.join(sorted(expected_facts - task_facts))}")
            not_yet_taught = " ".join(str(courseware_units.get(unit, {}).get("not_yet_taught", [])) for unit in task_units)
            if level == "core" and not_yet_taught and any(term and term.casefold() in json.dumps(task, ensure_ascii=False).casefold() for unit in task_units for term in courseware_units.get(unit, {}).get("not_yet_taught", [])):
                errors.append(f"{location} core task uses a not_yet_taught boundary")
        steps = task.get("steps")
        if not isinstance(steps, list) or len(steps) < MIN_TASK_STEPS:
            errors.append(f"{location}.steps must contain at least {MIN_TASK_STEPS} concrete items")
        else:
            for step_index, step in enumerate(steps):
                _required_strings(step, ("title", "instruction"), f"{location}.steps[{step_index}]", errors)
        if not isinstance(task.get("acceptance"), list) or not task["acceptance"]:
            errors.append(f"{location}.acceptance must be a non-empty list")
        if not isinstance(task.get("help_refs"), list):
            errors.append(f"{location}.help_refs must be a list when present")
        _validate_time_breakdown(task.get("time_breakdown"), f"{location}.time_breakdown", errors)
        if task.get("time_breakdown") is not None:
            metrics["time_breakdown_tasks"] += 1
        minutes = task.get("estimated_minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 5:
            errors.append(f"{location}.estimated_minutes must be an integer of at least 5")
        elif level == "core":
            metrics["core_minutes"] += minutes
        if isinstance(minutes, int) and not isinstance(minutes, bool):
            metrics["task_minutes"] += minutes
        modality = task.get("modality")
        if modality is not None and not _non_empty(modality):
            errors.append(f"{location}.modality must be a non-empty string when present")
        task_kind = task.get("task_kind")
        artifact_kind = task.get("artifact_kind")
        capabilities = task.get("capabilities")
        if task_kind not in TASK_KINDS:
            errors.append(f"{location}.task_kind must be one of {sorted(TASK_KINDS)}")
        if artifact_kind not in ARTIFACT_KINDS:
            errors.append(f"{location}.artifact_kind must be one of {sorted(ARTIFACT_KINDS)}")
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(f"{location}.capabilities must be a non-empty list")
            capabilities = []
        else:
            unknown_capabilities = sorted(set(capabilities) - CAPABILITIES)
            errors.extend(f"{location}.capabilities contains unknown capability: {item}" for item in unknown_capabilities)
        if enforce_task_semantics:
            _required_task_semantics(task, location, task_kind, capabilities, errors)
        if level == "core" and "code_editing" in capabilities and not task.get("starter_asset_ids"):
            errors.append(f"{location} core code_editing task must provide a starter")
        if "model_editing" in capabilities and not task.get("starter_asset_ids"):
            errors.append(f"{location} model_editing task must provide an editable starter or scaffold")
        if "execution" in capabilities or "query_execution" in capabilities:
            if not _non_empty(task.get("verification", "")) and not task.get("acceptance"):
                errors.append(f"{location} execution capability needs verification guidance")
        if "diagnosis" in capabilities and not _non_empty(task.get("scaffold")):
            errors.append(f"{location} diagnosis capability needs a concrete symptom scaffold")
        _validate_reference_verification(task, location, errors, integrity=content.get("integrity_version") == "1.0")
        if level == "core" and source.get("mode") == "courseware" and not refs:
            errors.append(f"{location} core task must link to taught knowledge")
        if level == "core" and "code_editing" in capabilities:
            starter_values = task.get("starter_asset_ids")
            if not isinstance(starter_values, list) or not starter_values:
                errors.append(f"{location}.starter_asset_ids must be a non-empty list")
            todo_count = task.get("todo_count")
            if todo_count is not None and (not isinstance(todo_count, int) or isinstance(todo_count, bool) or todo_count < 0):
                errors.append(f"{location}.todo_count must be a non-negative integer when present")
        elif not _non_empty(task.get("scaffold")):
            errors.append(f"{location}.scaffold is required for a non-coding task")
    metrics["tasks"] = len(task_ids)
    metrics["core_tasks"] = sum(1 for task in task_by_id.values() if task.get("level") == "core")
    metrics["optional_tasks"] = sum(1 for task in task_by_id.values() if task.get("level") == "optional")
    metrics["challenge_tasks"] = sum(1 for task in task_by_id.values() if task.get("level") == "challenge")
    # The three levels remain part of the content vocabulary, but none is a
    # contract-count requirement.  A quality recommendation can point out a
    # thin route without making a short or specialised class invalid.

    assets = _list(content.get("starter_assets"))
    asset_ids: set[str] = set()
    for index, asset in enumerate(assets):
        location = f"starter_assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{location} must be an object")
            continue
        _required_strings(asset, ("id", "path", "language", "task_id"), location, errors)
        if not asset.get('source_path') and not any(g.get('patch_kind') == 'add-file' for g in asset.get('editable_gaps', [])):
            _required_strings(asset, ('content',), location, errors)
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
    integrity = content.get("integrity_version")
    if integrity is not None and integrity != "1.0":
        errors.append("integrity_version must be 1.0 when present")
    if integrity == "1.0":
        _validate_formula_fact_shapes(content.get("formula_facts", []), "formula_facts", errors)
        _validate_g3_assets(content, task_ids, errors)
    elif content.get("formula_facts") is not None:
        _validate_formula_fact_shapes(content.get("formula_facts"), "formula_facts", errors)
    for task in task_by_id.values():
        starter_refs = task.get("starter_asset_ids", [])
        if starter_refs:
            _check_id_refs(starter_refs, asset_ids, f"tasks[{task.get('id')}].starter_asset_ids", errors)
        bundle_refs = task.get("starter_bundle_ids", [])
        if bundle_refs:
            known_bundle_ids = {str(bundle.get("id")) for bundle in content.get("starter_bundles", []) if isinstance(bundle, dict) and bundle.get("id")}
            _check_id_refs(bundle_refs, known_bundle_ids, f"tasks[{task.get('id')}].starter_bundle_ids", errors)
        if task.get("level") == "core" and "code_editing" in task.get("capabilities", []):
            actual_todo = sum(len(re.findall(r"\bTODO\s+\d+\b", _text(asset.get("content")))) for asset in assets if isinstance(asset, dict) and asset.get("id") in starter_refs)
            if task.get("todo_count") is not None and actual_todo != task.get("todo_count"):
                errors.append(f"task {task.get('id')} todo_count does not match starter content ({actual_todo})")
            actual_gaps = sum(len(asset.get("editable_gaps", [])) for asset in assets if isinstance(asset, dict) and asset.get("id") in starter_refs and isinstance(asset.get("editable_gaps", []), list))
            if task.get("todo_count") is not None and actual_gaps != task.get("todo_count"):
                errors.append(f"task {task.get('id')} todo_count does not match declared real starter gaps ({actual_gaps})")

    centers = _list(content.get("learning_center"))
    if len(centers) < MIN_CENTER_ZONES:
        errors.append(f"learning_center must contain at least {MIN_CENTER_ZONES} item")
    center_ids: set[str] = set()
    interaction_types: set[str] = set()
    renderer_families: set[str] = set()
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
        if source.get("mode") == "courseware":
            _validate_semantic_links(center, location, task_by_id, courseware_unit_ids, courseware_fact_ids, errors)
        interaction = _validate_interaction(center.get("interaction"), f"{location}.interaction", errors)
        if isinstance(interaction.get("type"), str):
            interaction_types.add(interaction["type"])
            if interaction["type"] in RENDERER_FAMILIES:
                renderer_families.add(RENDERER_FAMILIES[interaction["type"]])
        estimated = interaction.get("estimated_minutes")
        if isinstance(estimated, int) and not isinstance(estimated, bool):
            metrics["interaction_estimated_minutes"] += estimated
        else:
            warnings.append(f"{location}.interaction.estimated_minutes is omitted; the renderer will not invent a duration")
        metrics["interactions"] += 1
    metrics["interaction_types"] = sorted(interaction_types)
    metrics["interaction_zones"] = len(center_ids)
    metrics["interaction_type_count"] = len(interaction_types)
    metrics["renderer_families"] = sorted(renderer_families)
    metrics["renderer_family_count"] = len(renderer_families)
    metrics["dynamic_interactions"] = sum(1 for center in centers if isinstance(center, dict) and center.get("interaction", {}).get("type") in PROCESS_INTERACTIONS)
    metrics["diagnose_interactions"] = sum(1 for center in centers if isinstance(center, dict) and center.get("interaction", {}).get("type") == "diagnose")
    metrics["continuous_interactions"] = sum(1 for center in centers if isinstance(center, dict) and center.get("interaction", {}).get("type") in {"multi-question", "scenario-decision"})
    metrics["terminal_simulators"] = sum(
        1
        for center in centers
        if isinstance(center, dict)
        and center.get("interaction", {}).get("type") == "state-simulator"
        and isinstance(center.get("interaction", {}).get("rounds"), list)
        and center["interaction"]["rounds"]
        and isinstance(center["interaction"]["rounds"][-1], dict)
        and center["interaction"]["rounds"][-1].get("status") in {"found", "not-found"}
    )
    if metrics["terminal_simulators"] < sum(1 for center in centers if isinstance(center, dict) and center.get("interaction", {}).get("type") == "state-simulator"):
        errors.append("state-simulator interactions must include a terminal round")
    core_task_ids = {task_id for task_id, task in task_by_id.items() if task.get("level") == "core"}
    covered_core_task_ids = {task_id for center in centers if isinstance(center, dict) for task_id in _list(center.get("task_ids"))}
    for knowledge_id in knowledge_ids:
        knowledge_forms = {RENDERER_FAMILIES.get(center.get("interaction", {}).get("type")) for center in centers if isinstance(center, dict) and knowledge_id in _list(center.get("knowledge_link_ids"))}
        knowledge_forms.discard(None)
        if len(knowledge_forms) < 2:
            warnings.append(f"knowledge link {knowledge_id} is practiced in only one renderer family")

    guides = _list(content.get("study_guide"))
    if len(guides) < MIN_GUIDE_SECTIONS:
        errors.append(f"study_guide must contain at least {MIN_GUIDE_SECTIONS} item")
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
        if source.get("mode") == "courseware":
            _validate_semantic_links(guide, location, task_by_id, courseware_unit_ids, courseware_fact_ids, errors)
        _required_strings(guide, ("worked_example",), location, errors)
        for field in ("quick_reference", "common_errors", "checkpoints"):
            values = guide.get(field)
            if not isinstance(values, list) or not values or any(not _non_empty(item) for item in values):
                errors.append(f"{location}.{field} must be a non-empty string list")
        if not isinstance(guide.get("checkpoints"), list) or not guide["checkpoints"]:
            errors.append(f"{location}.checkpoints must be a non-empty list")
    metrics["guide_sections"] = len(guide_ids)

    kits = _list(content.get("foundation_kit"))
    if len(kits) < MIN_KIT_TOPICS:
        errors.append(f"foundation_kit must be a list")
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
        if source.get("mode") == "courseware":
            _validate_semantic_links(kit, location, task_by_id, courseware_unit_ids, courseware_fact_ids, errors)
        _required_strings(kit, ("when_to_use",), location, errors)
        if not isinstance(kit.get("steps"), list) or not kit["steps"]:
            errors.append(f"{location}.steps must be a non-empty list")
        if not isinstance(kit.get("self_check"), list) or not kit["self_check"] or any(not _non_empty(item) for item in kit.get("self_check", [])):
            errors.append(f"{location}.self_check must be a non-empty string list")
    metrics["foundation_microtopics"] = len(kit_ids)

    _validate_teacher_guide(content.get("teacher_guide"), task_ids, "teacher_guide", errors)
    _validate_teacher_reference(
        content.get("teacher_reference"),
        task_by_id,
        knowledge_by_id,
        actual_slide_ids,
        courseware_unit_ids,
        courseware_fact_ids,
        "teacher_reference",
        errors,
    )
    if isinstance(content.get("teacher_reference"), dict):
        references = content["teacher_reference"].get("task_references", [])
        metrics["teacher_references"] = len(references) if isinstance(references, list) else 0

    teacher_guide_value = content.get("teacher_guide")
    teacher_guidance = teacher_guide_value.get("task_guidance") if isinstance(teacher_guide_value, dict) else []
    guidance_ids = {item.get("task_id") for item in _list(teacher_guidance) if isinstance(item, dict)}
    metrics["core_help_coverage"] = len(core_task_ids & guidance_ids)
    missing_core_guidance = sorted(core_task_ids - guidance_ids)
    if missing_core_guidance:
        warnings.append("teacher_guide.task_guidance does not cover every core task: " + ", ".join(missing_core_guidance))

    all_help_refs = [ref for task in task_by_id.values() for ref in _list(task.get("help_refs"))]
    valid_help = guide_ids | kit_ids
    for ref in all_help_refs:
        if ref not in valid_help:
            warnings.append(f"help_refs item is not a study guide or foundation kit id: {ref}")
    support_covered = 0
    for task_id in core_task_ids:
        task = task_by_id[task_id]
        refs = set(task.get("help_refs", []))
        has_support = bool(refs & valid_help) or bool(task.get("starter_asset_ids")) or _non_empty(task.get("scaffold"))
        if has_support:
            support_covered += 1
    metrics["support_path_coverage"] = support_covered
    metrics["core_help_coverage"] = support_covered
    missing_support = sorted(task_id for task_id in core_task_ids if not (
        set(task_by_id[task_id].get("help_refs", [])) & valid_help
        or task_by_id[task_id].get("starter_asset_ids")
        or _non_empty(task_by_id[task_id].get("scaffold"))
    ))
    if missing_support:
        errors.append("core tasks need at least one effective support path: " + ", ".join(missing_support))
    timing = content.get("teacher_guide", {}).get("timing", []) if isinstance(content.get("teacher_guide"), dict) else []
    timing_minutes = sum(item.get("minutes", 0) for item in timing if isinstance(item, dict) and isinstance(item.get("minutes"), int))
    metrics["teacher_timing_minutes"] = timing_minutes
    if isinstance(duration, int) and timing_minutes != duration:
        errors.append(f"teacher_guide.timing total {timing_minutes} must equal duration_minutes {duration}")
    if isinstance(duration, int) and metrics["task_minutes"] != duration:
        warnings.append(f"task minutes total {metrics['task_minutes']} differs from class duration {duration}")
    if source.get("mode") == "courseware" and not source_slide_refs:
        errors.append("courseware mode requires at least one source slide reference")

    # Counts and level distribution are descriptive metrics, never contract
    # gates or score multipliers.  Only surface a warning when a declared
    # affordance is absent and the author should confirm that the omission is
    # intentional; a small or specialised class remains legal.
    recommendations: list[str] = []
    if not metrics["foundation_microtopics"]:
        recommendations.append("foundation_kit is empty; confirm that no just-in-time prerequisite support is needed")
    if not metrics["interactions"]:
        recommendations.append("learning_center is empty; confirm that core starter and study-guide support are sufficient")
    if metrics["interaction_estimated_minutes"] == 0 and metrics["interactions"]:
        recommendations.append("provide interaction-level estimated_minutes when reliable timings are known")
    metrics["quality_recommendations"] = recommendations
    warnings.extend(f"quality recommendation: {item}" for item in recommendations)

    raw_content = json.dumps(content, ensure_ascii=False)
    if re.search(r"统一提交|提交截图|收走|每组至少交出", raw_content):
        errors.append("default classroom content must not require uniform submission, screenshots, or collection of artifacts")

    environment = str((practice_context or {}).get("delivery_environment", "")).casefold() if isinstance(practice_context, dict) else ""
    paper_authorized = _non_empty(content.get("paper_work_authorization"))
    if ("computer-lab" in environment or "机房" in environment) and not paper_authorized:
        paper_phrases = sorted(set(re.findall(r"在纸上写|纸上填写|手写提交|纸笔记录|纸上记录", raw_content, flags=re.IGNORECASE)))
        if paper_phrases:
            warnings.append("COMPUTER_LAB_MODALITY_WARNING: default computer-lab work uses paper wording: " + "、".join(paper_phrases))

    errors.extend(_toolchain_compatibility_errors(content, practice_context))

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "source_slide_refs": sorted(source_slide_refs),
        "migration": migration,
    }


def require_valid(
    content: dict[str, Any],
    courseware: dict[str, Any] | None = None,
    *,
    enforce_task_semantics: bool = True,
) -> dict[str, Any]:
    report = validate_content(content, courseware, enforce_task_semantics=enforce_task_semantics)
    if report["status"] != "pass":
        raise ValueError("invalid Practice Class Content Contract: " + "; ".join(report["errors"]))
    return report
