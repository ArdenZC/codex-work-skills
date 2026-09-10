"""Plan typed, knowledge-bounded whole-course practice tasks."""

from __future__ import annotations

import argparse
from typing import Any

from build_knowledge_graph import validate_knowledge_boundary
from orchestrator_core import OrchestrationError, canonical_hash, dump_json, load_json


TYPED_STARTERS: dict[str, dict[str, Any]] = {
    "use_case_model": {"components": ["actor", "system_boundary", "partial_use_cases"], "gaps": ["missing_actor", "missing_relation"]},
    "class_model": {"components": ["partial_classes", "missing_relationship", "missing_multiplicity"], "gaps": ["missing_relation", "wrong_multiplicity"]},
    "sequence_model": {"components": ["lifelines", "missing_messages", "wrong_order"], "gaps": ["missing_message", "wrong_message_order"]},
    "state_model": {"components": ["states", "missing_transition_event"], "gaps": ["missing_transition"]},
    "deployment_model": {"components": ["nodes", "artifact_placement"], "gaps": ["wrong_node_mapping"]},
    "activity_model": {"components": ["actions", "decision_node", "partial_control_flow"], "gaps": ["missing_transition", "wrong_guard"]},
}


def typed_starter(artifact_type: str, supplied: dict[str, Any] | None = None) -> dict[str, Any]:
    adapter = TYPED_STARTERS.get(artifact_type)
    if not adapter:
        return {"artifact_type": artifact_type, "components": [], "editable_gaps": [], "starter_kind": "none"}
    supplied = supplied or {}
    return {
        "artifact_type": artifact_type,
        "components": list(supplied.get("components") or adapter["components"]),
        "editable_gaps": list(supplied.get("editable_gaps") or [{"type": gap, "semantic_target": gap} for gap in adapter["gaps"]]),
        "starter_kind": "typed",
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
            "editable_gaps": starter.get("editable_gaps", []),
            "observable_output": raw.get("observable_output"),
            "acceptance": raw.get("acceptance", []),
            "scaffold": raw.get("scaffold", []),
        }
        task["signature"] = canonical_hash({key: task[key] for key in ("capability", "artifact_type", "knowledge_node_ids", "editable_gaps")})
        tasks.append(task)
    if errors:
        raise OrchestrationError("practice planning failed:\n- " + "\n- ".join(errors))
    return {
        "id": session_id,
        "title": str(session.get("title") or session_id),
        "knowledge_state_after": next(item.get("knowledge_state_after", []) for item in graph.get("sessions", []) if item.get("id") == session_id),
        "tasks": tasks,
        "task_count": len(tasks),
        "planned_minutes": sum(float(task["estimated_minutes"]) for task in tasks),
    }


def build_practice_plans(course: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "plan_type": "whole_course_practice_plans",
        "course_id": graph.get("course_id"),
        "sessions": [plan_practice_session(session, graph) for session in course.get("sessions", [])],
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
