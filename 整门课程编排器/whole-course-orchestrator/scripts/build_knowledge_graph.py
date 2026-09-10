"""Build a cumulative, source-aware course knowledge graph."""

from __future__ import annotations

import argparse
from typing import Any, Iterable

from orchestrator_core import OrchestrationError, dump_json, load_json


NODE_TYPES = {
    "concept",
    "notation",
    "procedure",
    "tool_skill",
    "analysis_skill",
    "modeling_skill",
    "calculation",
    "implementation",
    "diagnosis",
}


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def build_graph(course: dict[str, Any]) -> dict[str, Any]:
    raw_nodes = course.get("knowledge_nodes") or course.get("nodes")
    raw_sessions = course.get("sessions")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise OrchestrationError("course map must contain non-empty knowledge_nodes")
    if not isinstance(raw_sessions, list) or not raw_sessions:
        raise OrchestrationError("course map must contain non-empty sessions")

    node_map: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for index, raw in enumerate(raw_nodes, start=1):
        if not isinstance(raw, dict):
            errors.append(f"knowledge_nodes[{index - 1}] is not an object")
            continue
        node_id = str(raw.get("id") or "").strip()
        if not node_id:
            errors.append(f"knowledge_nodes[{index - 1}] is missing id")
            continue
        if node_id in node_map:
            errors.append(f"duplicate knowledge node id: {node_id}")
            continue
        node_type = str(raw.get("type") or "concept")
        if node_type not in NODE_TYPES:
            errors.append(f"{node_id}: unsupported knowledge node type {node_type}")
        node_map[node_id] = {
            "id": node_id,
            "title": str(raw.get("title") or node_id),
            "type": node_type,
            "source_assets": _unique(str(item) for item in raw.get("source_assets", [])),
            "prerequisites": _unique(str(item) for item in raw.get("prerequisites", [])),
            "depends_on": _unique(str(item) for item in raw.get("depends_on", [])),
            "related_to": _unique(str(item) for item in raw.get("related_to", [])),
            "difficulty": raw.get("difficulty", "medium"),
            "importance": raw.get("importance", "supporting"),
            "first_taught_session": None,
            "revisited_sessions": [],
            "practice_dependencies": _unique(str(item) for item in raw.get("practice_dependencies", [])),
        }

    for node in node_map.values():
        for field in ("prerequisites", "depends_on", "related_to"):
            for reference in node[field]:
                if reference not in node_map:
                    errors.append(f"{node['id']}.{field} references unknown node {reference}")

    session_records: list[dict[str, Any]] = []
    seen_sessions: set[str] = set()
    taught: list[str] = []
    for index, raw in enumerate(raw_sessions, start=1):
        if not isinstance(raw, dict):
            errors.append(f"sessions[{index - 1}] is not an object")
            continue
        session_id = str(raw.get("id") or f"session-{index:02d}").strip()
        if session_id in seen_sessions:
            errors.append(f"duplicate session id: {session_id}")
            continue
        seen_sessions.add(session_id)
        new_ids = _unique(str(item) for item in raw.get("new_knowledge_ids", raw.get("new_knowledge", [])))
        review_ids = _unique(str(item) for item in raw.get("review_knowledge_ids", raw.get("review_knowledge", [])))
        before = list(taught)
        if set(new_ids) & set(review_ids):
            errors.append(f"{session_id}: a node cannot be new and review in the same session")
        for node_id in new_ids + review_ids:
            if node_id not in node_map:
                errors.append(f"{session_id} references unknown node {node_id}")
        for node_id in new_ids:
            node = node_map.get(node_id)
            if not node:
                continue
            if node["first_taught_session"] is not None:
                errors.append(f"{session_id}: {node_id} is taught again as new; use review")
            node["first_taught_session"] = session_id
            missing_prerequisites = [
                prerequisite
                for prerequisite in node["prerequisites"] + node["depends_on"]
                if prerequisite not in before and prerequisite not in new_ids[: new_ids.index(node_id)]
            ]
            if missing_prerequisites:
                errors.append(f"{session_id}: {node_id} is before its prerequisites {missing_prerequisites}")
            taught.append(node_id)
        for node_id in review_ids:
            if node_id not in before and node_id not in new_ids:
                errors.append(f"{session_id}: review node {node_id} has not been taught")
            if node_id in node_map and session_id not in node_map[node_id]["revisited_sessions"]:
                node_map[node_id]["revisited_sessions"].append(session_id)
        after = _unique(taught)
        future = [node_id for node_id in node_map if node_id not in after]
        session_records.append({
            "id": session_id,
            "title": str(raw.get("title") or session_id),
            "minutes": raw.get("minutes"),
            "new_knowledge": new_ids,
            "review_knowledge": review_ids,
            "knowledge_state_before": before,
            "knowledge_state_after": after,
            "future_knowledge": future,
            "practice_dependencies": _unique(str(item) for item in raw.get("practice_dependencies", [])),
            "source_asset_ids": _unique(str(item) for item in raw.get("source_asset_ids", [])),
        })

    for node in node_map.values():
        if node["first_taught_session"] is None:
            errors.append(f"knowledge node is never taught: {node['id']}")

    if errors:
        raise OrchestrationError("knowledge graph validation failed:\n- " + "\n- ".join(errors))

    return {
        "schema_version": "1.0",
        "graph_type": "course_knowledge_graph",
        "course_id": str(course.get("course_id") or course.get("course_name") or "course"),
        "course_name": str(course.get("course_name") or course.get("course_id") or ""),
        "student_level": course.get("student_level", "高职/大专"),
        "nodes": list(node_map.values()),
        "sessions": session_records,
        "state_policy": "knowledge_state_after is cumulative; core practice may only use it",
    }


def validate_knowledge_boundary(graph: dict[str, Any], session_id: str, knowledge_ids: Iterable[str]) -> list[str]:
    session = next((item for item in graph.get("sessions", []) if item.get("id") == session_id), None)
    if not session:
        return [f"unknown session: {session_id}"]
    allowed = set(session.get("knowledge_state_after", []))
    return [f"{session_id}: knowledge used before taught: {node_id}" for node_id in knowledge_ids if node_id not in allowed]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-json", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_graph(load_json(args.course_json))
    dump_json(result, args.output_json)
    if args.json:
        print({"course_id": result["course_id"], "nodes": len(result["nodes"]), "sessions": len(result["sessions"])})


if __name__ == "__main__":
    main()
