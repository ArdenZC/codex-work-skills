"""Plan typed, knowledge-bounded practice tasks with observed-evidence slots."""

from __future__ import annotations

import argparse
from typing import Any

from build_knowledge_graph import validate_knowledge_boundary
from orchestrator_core import OrchestrationError, canonical_hash, dump_json, load_json
from semantic_artifacts import starter_spec


TYPED_STARTERS: dict[str, dict[str, Any]] = {
    "use_case_model": {"components": ["actor", "system_boundary", "partial_use_cases"], "gaps": ["missing_actor", "missing_relation"]},
    "class_model": {"components": ["partial_classes", "missing_relationship", "missing_multiplicity"], "gaps": ["missing_relation", "wrong_multiplicity"]},
    "sequence_model": {"components": ["lifelines", "missing_messages", "wrong_order"], "gaps": ["missing_message", "wrong_message_order"]},
    "state_model": {"components": ["states", "missing_transition_event"], "gaps": ["missing_transition"]},
    "deployment_model": {"components": ["nodes", "artifact_placement"], "gaps": ["wrong_node_mapping"]},
    "activity_model": {"components": ["actions", "decision_node", "partial_control_flow"], "gaps": ["missing_transition", "wrong_guard"]},
    "tree_graph_structure": {"components": ["nodes", "root", "partial_edges"], "gaps": ["missing_edge", "wrong_parent"]},
    "relational_table_model": {"components": ["table", "field", "missing_key"], "gaps": ["missing_key", "wrong_relationship"]},
    "network_topology": {"components": ["device", "link", "partial_path"], "gaps": ["missing_link", "wrong_direction"]},
    "worksheet_dataflow": {"components": ["cell_range", "formula", "partial_dependency"], "gaps": ["missing_formula", "wrong_dependency"]},
}


def typed_starter(artifact_type: str, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
    adapter = TYPED_STARTERS.get(artifact_type)
    if adapter is None:
        registry_adapter = starter_spec(artifact_type)
        if registry_adapter:
            adapter = {"components": registry_adapter["components"], "gaps": registry_adapter["gaps"]}
    if not adapter:
        return {"artifact_type": artifact_type, "components": [], "editable_gaps": [], "starter_kind": "none", "starter_observed": [], "evidence_status": "PLANNED_NOT_OBSERVED"}
    supplied = supplied or {}
    gaps = supplied.get("editable_gaps")
    if not isinstance(gaps, list) or not gaps:
        gaps = [{"type": gap, "semantic_target": gap} for gap in adapter["gaps"]]
    return {
        "artifact_type": artifact_type,
        "components": list(supplied.get("components") or adapter["components"]),
        "editable_gaps": gaps,
        "starter_kind": "typed",
        "starter_observed": list(supplied.get("starter_observed") or []),
        "evidence": list(supplied.get("evidence") or []),
        "evidence_status": str(supplied.get("evidence_status") or "PLANNED_NOT_OBSERVED"),
    }


def _validate_starter(task: dict[str, Any], starter: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    artifact_type = str(task.get("artifact_type") or "")
    if artifact_type in TYPED_STARTERS:
        expected = TYPED_STARTERS[artifact_type]
        components = set(starter.get("components", []))
        gaps = {str(item.get("type")) if isinstance(item, dict) else str(item) for item in starter.get("editable_gaps", [])}
        if starter.get("starter_kind") != "typed":
            errors.append(f"{task.get('id')}: typed artifact has no typed starter")
        if not set(expected["components"]) & components:
            errors.append(f"{task.get('id')}: starter has no artifact-specific components")
        if not gaps & set(expected["gaps"]):
            errors.append(f"{task.get('id')}: starter has no semantic editable gap")
        if any(token in str(starter).lower() for token in ("todo_1", "todo_2", "generic rectangle")):
            errors.append(f"{task.get('id')}: generic TODO/rectangle starter is not allowed for {artifact_type}")
    return errors


def _gap_types(starter: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in starter.get("editable_gaps", []):
        value = item.get("type") if isinstance(item, dict) else item
        if value:
            values.append(str(value))
    return list(dict.fromkeys(values))


def _step_pattern(raw: dict[str, Any]) -> list[str]:
    steps = raw.get("steps", [])
    if not isinstance(steps, list):
        steps = []
    result: list[str] = []
    for step in steps:
        if isinstance(step, dict):
            result.append(str(step.get("kind") or step.get("type") or ("check" if step.get("check") else "action")))
        else:
            result.append("action")
    return result or ["action"]


def _structural_signature(raw: dict[str, Any], task: dict[str, Any], starter: dict[str, Any]) -> str:
    minutes = float(task.get("estimated_minutes", 0) or 0)
    breakdown = []
    for item in task.get("time_breakdown", []) if isinstance(task.get("time_breakdown"), list) else []:
        if isinstance(item, dict):
            breakdown.append((str(item.get("label") or item.get("kind") or "segment"), round(float(item.get("minutes", 0) or 0), 1)))
    payload = {
        "capability": str(task.get("capability") or ""),
        "task_shape": str(raw.get("task_shape") or raw.get("shape") or ("artifact" if task.get("artifact_type") else "response")),
        "step_pattern": _step_pattern(raw),
        "artifact_family": str(task.get("artifact_type") or raw.get("artifact_family") or "none"),
        "starter_gap_family": sorted(_gap_types(starter)),
        "time_structure": {"minutes": round(minutes), "breakdown": breakdown},
        "interaction_type": str(raw.get("interaction_type") or raw.get("modality") or task.get("capability") or "unknown"),
    }
    return canonical_hash(payload)


def plan_practice_session(session: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    session_id = str(session.get("id") or "")
    specs = session.get("practice_tasks", session.get("tasks", []))
    if not isinstance(specs, list) or not specs:
        raise OrchestrationError(f"{session_id}: practice_tasks must be a non-empty list")
    errors: list[str] = []
    tasks: list[dict[str, Any]] = []
    for index, raw in enumerate(specs, start=1):
        if not isinstance(raw, dict):
            errors.append(f"{session_id}: task {index} is not an object")
            continue
        task_id = str(raw.get("id") or f"{session_id}-task-{index:02d}")
        knowledge_ids = [str(item) for item in raw.get("knowledge_node_ids", raw.get("knowledge_ids", []))]
        errors.extend(validate_knowledge_boundary(graph, session_id, knowledge_ids))
        artifact_type = str(raw.get("artifact_type") or raw.get("artifact_kind") or "")
        starter = typed_starter(artifact_type, raw.get("starter") if isinstance(raw.get("starter"), dict) else None)
        errors.extend(_validate_starter({"id": task_id, "artifact_type": artifact_type}, starter))
        capability = str(raw.get("capability") or raw.get("modality") or "explain")
        estimated = float(raw.get("estimated_minutes", 0) or 0)
        if estimated <= 0:
            errors.append(f"{task_id}: estimated_minutes must be positive")
        task = {
            "id": task_id,
            "session_id": session_id,
            "title": str(raw.get("title") or task_id),
            "level": str(raw.get("level") or "core"),
            "capability": capability,
            "artifact_type": artifact_type or None,
            "knowledge_node_ids": knowledge_ids,
            "estimated_minutes": estimated,
            "time_breakdown": raw.get("time_breakdown", []),
            "starter": starter,
            "starter_requirements": list(raw.get("starter_requirements") or starter.get("components", [])) + [f"editable_gap:{gap}" for gap in _gap_types(starter)],
            "starter_plan": dict(starter),
            "starter_observed": [],
            "editable_gaps": starter.get("editable_gaps", []),
            "observable_output": raw.get("observable_output"),
            "acceptance": raw.get("acceptance", []),
            "scaffold": raw.get("scaffold", []),
            "task_shape": str(raw.get("task_shape") or raw.get("shape") or ("artifact" if artifact_type else "response")),
            "interaction_type": str(raw.get("interaction_type") or raw.get("modality") or capability),
        }
        task["structural_task_signature"] = _structural_signature(raw, task, starter)
        task["semantic_task_signature"] = canonical_hash({"title": task["title"], "knowledge_node_ids": knowledge_ids, "capability": capability, "artifact_type": artifact_type, "editable_gaps": task["editable_gaps"]})
        # Phase 1 compatibility: ``signature`` remains the semantic signature;
        # template QA now uses structural_task_signature instead.
        task["signature"] = task["semantic_task_signature"]
        tasks.append(task)
    if errors:
        raise OrchestrationError("practice planning failed:\n- " + "\n- ".join(errors))
    graph_session = next((item for item in graph.get("sessions", []) if item.get("id") == session_id), None)
    practice_config = session.get("practice") if isinstance(session.get("practice"), dict) else {}
    declared_minutes = session.get("practice_minutes") or session.get("practice_duration_minutes") or practice_config.get("minutes")
    duration_status = "NOT_DECLARED"
    duration_reasons: list[str] = []
    planned_minutes = round(sum(float(task["estimated_minutes"]) for task in tasks), 2)
    if declared_minutes not in (None, ""):
        try:
            declared_value = float(declared_minutes)
        except (TypeError, ValueError):
            raise OrchestrationError(f"{session_id}: practice minutes must be numeric")
        if abs(declared_value - planned_minutes) > 1:
            duration_status = "MISMATCH_DEGRADED" if str(session.get("planning_mode") or "draft") == "draft" else "MISMATCH"
            duration_reasons.append(f"declared practice minutes {declared_value:g} differs from task sum {planned_minutes:g}")
            if str(session.get("planning_mode") or "draft") == "release":
                raise OrchestrationError(f"PRACTICE_DURATION_MISMATCH: {session_id}: declared {declared_value:g}, planned {planned_minutes:g}")
        else:
            duration_status = "MATCH"
    return {
        "id": session_id,
        "title": str(session.get("title") or session_id),
        "knowledge_state_after": (graph_session or {}).get("knowledge_state_after", []),
        "tasks": tasks,
        "task_count": len(tasks),
        "planned_minutes": planned_minutes,
        "practice_minutes": declared_minutes,
        "duration_status": duration_status,
        "duration_reasons": duration_reasons,
    }


def build_practice_plans(course: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "plan_type": "whole_course_practice_plans",
        "course_id": graph.get("course_id"),
        "sessions": [plan_practice_session(session, graph) for session in course.get("sessions", [])],
        "evidence_state_model": {"required": "artifact-specific starter requirements", "planned": "starter plan", "observed": "real starter files and closure evidence"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-json", required=True)
    parser.add_argument("--knowledge-graph", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_practice_plans(load_json(args.course_json), load_json(args.knowledge_graph))
    dump_json(result, args.output_json)
    if args.json:
        print({"sessions": len(result["sessions"]), "tasks": sum(item["task_count"] for item in result["sessions"])})


if __name__ == "__main__":
    main()
