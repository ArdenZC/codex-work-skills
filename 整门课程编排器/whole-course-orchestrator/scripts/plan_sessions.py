"""Create content-native session plans from teaching questions and graph state."""

from __future__ import annotations

import argparse
from typing import Any

from orchestrator_core import OrchestrationError, canonical_hash, dump_json, load_json, slug


JOB_LAYOUTS = {
    "introduce": "hero",
    "define": "focus",
    "explain": "focus",
    "visualize": "semantic-diagram",
    "compare": "comparison",
    "worked_example": "worked-example",
    "step_through": "step-build",
    "diagnose": "diagnose",
    "check": "check",
    "summarize": "summary",
    "bridge": "bridge",
    "demonstrate": "demonstration",
}


def _derive_job(question: dict[str, Any]) -> str:
    explicit = str(question.get("primary_job") or question.get("job") or "").strip()
    if explicit:
        if explicit not in JOB_LAYOUTS:
            raise OrchestrationError(f"unsupported slide job: {explicit}")
        return explicit
    if question.get("artifact_type") or question.get("visual_intent") or question.get("visual_asset_ids"):
        return "visualize"
    if question.get("comparison") or question.get("contrast_dimension"):
        return "compare"
    if question.get("worked_example") or question.get("case"):
        return "worked_example"
    if question.get("procedure") or question.get("steps"):
        return "step_through"
    if question.get("check") or question.get("quiz"):
        return "check"
    if question.get("bridge"):
        return "bridge"
    if question.get("intro"):
        return "introduce"
    return "explain"


def _allocate_minutes(questions: list[dict[str, Any]], session_minutes: int | float | None) -> list[float]:
    explicit = [float(item.get("minutes", 0) or 0) for item in questions]
    if all(value > 0 for value in explicit):
        return explicit
    target = float(session_minutes or 0)
    known = sum(value for value in explicit if value > 0)
    missing = sum(1 for value in explicit if value <= 0)
    share = max((target - known) / missing, 1.0) if missing else 0.0
    result = [value if value > 0 else share for value in explicit]
    if not target:
        return result
    correction = target - sum(result)
    if result:
        result[-1] = max(result[-1] + correction, 0.5)
    return result


def plan_session(session: dict[str, Any], graph_session: dict[str, Any] | None, assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    session_id = str(session.get("id") or "").strip()
    if not session_id:
        raise OrchestrationError("session is missing id")
    questions = session.get("teaching_questions")
    if not isinstance(questions, list) or not questions:
        raise OrchestrationError(f"{session_id}: teaching_questions must be a non-empty list")
    errors: list[str] = []
    pages: list[dict[str, Any]] = []
    minutes = _allocate_minutes(questions, session.get("minutes"))
    for index, raw in enumerate(questions, start=1):
        if not isinstance(raw, dict):
            errors.append(f"{session_id}: teaching_questions[{index - 1}] is not an object")
            continue
        question_id = str(raw.get("id") or f"{session_id}-q{index:02d}")
        prompt = str(raw.get("prompt") or raw.get("question") or "").strip()
        outcome = str(raw.get("learning_outcome") or raw.get("understanding_result") or "").strip()
        if len(prompt) < 4:
            errors.append(f"{session_id}/{question_id}: question is too broad or empty")
        if not outcome:
            errors.append(f"{session_id}/{question_id}: learning_outcome is required")
        job = _derive_job(raw)
        asset_ids = [str(item) for item in raw.get("visual_asset_ids", raw.get("asset_ids", []))]
        missing_assets = [asset_id for asset_id in asset_ids if asset_id not in assets]
        if missing_assets:
            errors.append(f"{session_id}/{question_id}: unknown teaching assets {missing_assets}")
        artifact_type = raw.get("artifact_type")
        if artifact_type and job != "visualize" and not raw.get("visual_intent"):
            errors.append(f"{session_id}/{question_id}: typed visual artifact needs a visual teaching job")
        page = {
            "id": f"{session_id}-{slug(question_id, fallback=f'q{index:02d}')}",
            "session_id": session_id,
            "title": str(raw.get("title") or prompt),
            "teaching_question_id": question_id,
            "teaching_question": prompt,
            "learning_outcome": outcome,
            "primary_job": job,
            "layout": JOB_LAYOUTS[job],
            "knowledge_node_ids": [str(item) for item in raw.get("knowledge_node_ids", raw.get("knowledge_ids", []))],
            "source_asset_ids": asset_ids,
            "artifact_type": artifact_type,
            "visual_intent": raw.get("visual_intent"),
            "contrast_dimension": raw.get("contrast_dimension"),
            "lecture_minutes": round(float(minutes[index - 1]) * float(raw.get("lecture_ratio", 0.65)), 2),
            "activity_minutes": round(float(minutes[index - 1]) * (1 - float(raw.get("lecture_ratio", 0.65))), 2),
            "content_evidence": {
                "worked_example": raw.get("worked_example"),
                "case": raw.get("case"),
                "procedure": raw.get("procedure"),
                "check": raw.get("check"),
                "steps": raw.get("steps", []),
            },
            "script_anchor_ids": [question_id, *asset_ids],
            "block_signature": _block_signature(raw, job),
        }
        page["suggested_minutes"] = round(page["lecture_minutes"] + page["activity_minutes"], 2)
        page["content_signature"] = canonical_hash({key: page[key] for key in ("primary_job", "knowledge_node_ids", "source_asset_ids", "artifact_type", "content_evidence")})
        pages.append(page)
    if errors:
        raise OrchestrationError("session planning failed:\n- " + "\n- ".join(errors))

    result = {
        "id": session_id,
        "title": str(session.get("title") or session_id),
        "minutes": session.get("minutes"),
        "planned_minutes": round(sum(float(page["suggested_minutes"]) for page in pages), 2),
        "teaching_questions": [
            {"id": page["teaching_question_id"], "prompt": page["teaching_question"], "learning_outcome": page["learning_outcome"]}
            for page in pages
        ],
        "pages": pages,
        "knowledge_state_before": (graph_session or {}).get("knowledge_state_before", []),
        "new_knowledge": (graph_session or {}).get("new_knowledge", []),
        "review_knowledge": (graph_session or {}).get("review_knowledge", []),
        "knowledge_state_after": (graph_session or {}).get("knowledge_state_after", []),
        "future_knowledge": (graph_session or {}).get("future_knowledge", []),
        "structure_policy": "teaching_questions -> primary_job -> content evidence -> layout",
    }
    return result


def _block_signature(question: dict[str, Any], job: str) -> list[str]:
    signature = ["question"]
    if question.get("definition") or job in {"define", "explain"}:
        signature.append("explanation")
    if question.get("visual_asset_ids") or question.get("artifact_type"):
        signature.append("semantic_visual")
    if question.get("worked_example") or question.get("case"):
        signature.append("worked_example")
    if question.get("comparison") or question.get("contrast_dimension"):
        signature.append("comparison")
    if question.get("check") or question.get("quiz"):
        signature.append("diagnostic_check")
    if question.get("steps") or question.get("procedure"):
        signature.append("procedure")
    return signature


def build_plans(course: dict[str, Any], graph: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    assets = {str(item["id"]): item for item in inventory.get("assets", []) if isinstance(item, dict) and item.get("id")}
    graph_sessions = {str(item["id"]): item for item in graph.get("sessions", [])}
    planned = []
    for session in course.get("sessions", []):
        session_id = str(session.get("id") or "")
        planned.append(plan_session(session, graph_sessions.get(session_id), assets))
    return {
        "schema_version": "1.0",
        "plan_type": "content_native_session_plans",
        "course_id": graph.get("course_id"),
        "sessions": planned,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--course-json", required=True)
    parser.add_argument("--knowledge-graph", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_plans(load_json(args.course_json), load_json(args.knowledge_graph), load_json(args.assets))
    dump_json(result, args.output_json)
    if args.json:
        print({"sessions": len(result["sessions"]), "slides": sum(len(item["pages"]) for item in result["sessions"])})


if __name__ == "__main__":
    main()
