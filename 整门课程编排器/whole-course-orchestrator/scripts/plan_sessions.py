"""Create content-native session plans with explicit timing/layout evidence."""

from __future__ import annotations

import argparse
from typing import Any

from orchestrator_core import OrchestrationError, canonical_hash, dump_json, load_json, slug


JOB_LAYOUT_FAMILIES: dict[str, tuple[str, ...]] = {
    "introduce": ("hero", "split", "large-visual"),
    "define": ("focus", "split", "annotated-object"),
    "explain": ("focus", "split", "large-visual"),
    "visualize": ("semantic-diagram", "large-visual", "split", "annotated-object"),
    "compare": ("comparison", "split", "annotated-object"),
    "worked_example": ("step-build", "split", "large-visual", "timeline"),
    "step_through": ("step-build", "timeline", "split", "large-visual"),
    "diagnose": ("diagnose", "split", "focus"),
    "check": ("check", "split", "focus"),
    "summarize": ("summary", "focus", "split"),
    "bridge": ("bridge", "split", "focus"),
    "demonstrate": ("demonstration", "large-visual", "step-build", "split"),
}

# Backward-compatible first-choice view. New planning uses the full family and
# records why the selected member was chosen.
JOB_LAYOUTS = {job: families[0] for job, families in JOB_LAYOUT_FAMILIES.items()}

JOB_ACTIVITY_RANGES: dict[str, tuple[float, float]] = {
    "introduce": (0.55, 0.80),
    "define": (0.45, 0.70),
    "explain": (0.40, 0.65),
    "visualize": (0.25, 0.55),
    "compare": (0.30, 0.60),
    "worked_example": (0.30, 0.60),
    "step_through": (0.25, 0.65),
    "diagnose": (0.20, 0.55),
    "check": (0.15, 0.45),
    "summarize": (0.35, 0.60),
    "bridge": (0.35, 0.65),
    "demonstrate": (0.25, 0.60),
}


def _derive_job(question: dict[str, Any]) -> str:
    explicit = str(question.get("primary_job") or question.get("job") or "").strip()
    if explicit:
        if explicit not in JOB_LAYOUT_FAMILIES:
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


def _effort_estimate(question: dict[str, Any], job: str) -> float:
    model = question.get("effort_model")
    if not isinstance(model, dict):
        return 0.0
    complexity = float(model.get("complexity", 0) or 0)
    visual_load = float(model.get("visual_load", 0) or 0)
    worked_steps = float(model.get("worked_example_steps", 0) or 0)
    reasoning = float(model.get("student_reasoning_load", 0) or 0)
    # The coefficients are a generic effort model, not a course-specific
    # timing template. A supplied explicit minute value always wins.
    return max(1.0, round(1.5 * complexity + 1.5 * visual_load + 1.0 * worked_steps + 2.0 * reasoning, 2))


def _allocate_minutes(questions: list[dict[str, Any]], session_minutes: int | float | None, planning_mode: str = "draft") -> tuple[list[float], str, list[str]]:
    explicit: list[float] = []
    sources: list[str] = []
    for question in questions:
        value = float(question.get("minutes", question.get("estimated_minutes", 0)) or 0)
        if value > 0:
            explicit.append(value)
            sources.append("explicit_minutes")
            continue
        estimate = _effort_estimate(question, _derive_job(question))
        if estimate > 0:
            explicit.append(estimate)
            sources.append("effort_model")
        else:
            explicit.append(0.0)
            sources.append("missing")
    missing = [index for index, value in enumerate(explicit) if value <= 0]
    if planning_mode == "release" and missing:
        labels = [str(questions[index].get("id") or index + 1) for index in missing]
        raise OrchestrationError(f"release timing requires minutes or effort_model for teaching questions: {labels}")
    if not missing:
        return explicit, "EVIDENCE_BACKED", sources
    target = float(session_minutes or 0)
    known = sum(value for value in explicit if value > 0)
    remaining = target - known if target > known else 0.0
    fallback = round(max(remaining / len(missing), 1.0), 2) if remaining else 5.0
    for index in missing:
        explicit[index] = fallback
        sources[index] = "draft_estimate_fallback"
    return explicit, "DEGRADED_ESTIMATE", sources


def _delivery_mix(question: dict[str, Any], job: str, total: float) -> tuple[float, float, dict[str, Any]]:
    explicit_minutes = question.get("lecture_minutes"), question.get("activity_minutes")
    if all(isinstance(value, (int, float)) and float(value) >= 0 for value in explicit_minutes) and any(value is not None for value in explicit_minutes):
        lecture = max(0.0, float(explicit_minutes[0] or 0))
        activity = max(0.0, float(explicit_minutes[1] or 0))
        if lecture + activity > 0:
            scale = total / (lecture + activity)
            return round(lecture * scale, 2), round(activity * scale, 2), {"lecture": round(lecture * scale, 2), "activity": round(activity * scale, 2), "source": "explicit_minutes"}
    raw_mix = question.get("delivery_mix")
    if isinstance(raw_mix, dict) and raw_mix:
        values = {str(key): max(0.0, float(value or 0)) for key, value in raw_mix.items() if isinstance(value, (int, float))}
        if sum(values.values()) > 0:
            lecture = values.get("lecture", 0.0)
            activity = sum(value for key, value in values.items() if key != "lecture")
            scale = total / sum(values.values())
            return round(lecture * scale, 2), round(activity * scale, 2), {key: round(value * scale, 2) for key, value in values.items()} | {"source": "explicit_delivery_mix"}
    if isinstance(question.get("lecture_ratio"), (int, float)):
        ratio = min(max(float(question["lecture_ratio"]), 0.0), 1.0)
        return round(total * ratio, 2), round(total * (1 - ratio), 2), {"lecture": round(total * ratio, 2), "activity": round(total * (1 - ratio), 2), "source": "explicit_ratio"}
    activity_low, activity_high = JOB_ACTIVITY_RANGES.get(job, (0.30, 0.60))
    evidence_score = 0.0
    for key in ("steps", "procedure", "worked_example", "case", "check", "quiz", "comparison"):
        if question.get(key):
            evidence_score += 0.08
    activity_ratio = min(activity_high, max(activity_low, activity_low + evidence_score))
    activity = round(total * activity_ratio, 2)
    lecture = round(max(total - activity, 0.0), 2)
    return lecture, activity, {"lecture": lecture, "activity": activity, "activity_ratio": activity_ratio, "source": "job_range_and_question_evidence"}


def _layout_for(question: dict[str, Any], job: str) -> tuple[str, str]:
    families = JOB_LAYOUT_FAMILIES[job]
    explicit = str(question.get("layout") or "").strip()
    if explicit:
        if explicit not in families:
            raise OrchestrationError(f"{question.get('id') or job}: layout {explicit} is not in the {job} layout family")
        return explicit, "explicit layout selected by the teaching question"
    if job in {"define", "explain"}:
        if question.get("source_asset_ids") or question.get("visual_asset_ids") or question.get("worked_example"):
            return families[1], "supporting evidence needs a text-and-evidence composition"
        return families[0], "definition has a focused explanation with no additional evidence block"
    if job in {"worked_example", "step_through"}:
        steps = question.get("steps") or question.get("procedure") or []
        if isinstance(steps, list) and len(steps) >= 4:
            return families[1], "four or more procedure steps benefit from a temporal sequence"
        return families[0], "the worked evidence is best built step by step"
    if job == "compare":
        return (families[0], "two-sided contrast has an explicit comparison dimension") if question.get("contrast_dimension") or question.get("comparison") else (families[1], "comparison evidence is present but needs a supporting explanation")
    if job == "visualize":
        return (families[0], "typed visual evidence is the primary teaching object") if question.get("artifact_type") else (families[1], "visual evidence is supporting the teaching question")
    if question.get("check") or question.get("quiz"):
        return families[0], "the page must keep the diagnostic action visible"
    return families[0], "first compatible layout in the job family selected deterministically"


def plan_session(session: dict[str, Any], graph_session: dict[str, Any] | None, assets: dict[str, dict[str, Any]], *, planning_mode: str | None = None) -> dict[str, Any]:
    session_id = str(session.get("id") or "").strip()
    if not session_id:
        raise OrchestrationError("session is missing id")
    questions = session.get("teaching_questions")
    if not isinstance(questions, list) or not questions:
        raise OrchestrationError(f"{session_id}: teaching_questions must be a non-empty list")
    mode = str(planning_mode or session.get("planning_mode") or "draft").lower()
    if mode not in {"draft", "release"}:
        raise OrchestrationError(f"{session_id}: planning_mode must be draft or release")
    errors: list[str] = []
    pages: list[dict[str, Any]] = []
    minutes, timing_status, timing_sources = _allocate_minutes(questions, session.get("minutes"), mode)
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
        layout, layout_rationale = _layout_for(raw, job)
        total = float(minutes[index - 1])
        lecture, activity, delivery_mix = _delivery_mix(raw, job, total)
        page = {
            "id": f"{session_id}-{slug(question_id, fallback=f'q{index:02d}')}",
            "session_id": session_id,
            "title": str(raw.get("title") or prompt),
            "teaching_question_id": question_id,
            "teaching_question": prompt,
            "learning_outcome": outcome,
            "primary_job": job,
            "layout": layout,
            "layout_family": list(JOB_LAYOUT_FAMILIES[job]),
            "layout_rationale": layout_rationale,
            "knowledge_node_ids": [str(item) for item in raw.get("knowledge_node_ids", raw.get("knowledge_ids", []))],
            "source_asset_ids": asset_ids,
            "contract_referenced_asset_ids": [str(item) for item in raw.get("contract_referenced_asset_ids", [])],
            "artifact_type": artifact_type,
            "visual_intent": raw.get("visual_intent"),
            "contrast_dimension": raw.get("contrast_dimension"),
            "lecture_minutes": lecture,
            "activity_minutes": activity,
            "delivery_mix": delivery_mix,
            "timing_evidence": {"source": timing_sources[index - 1], "planning_mode": mode, "question_id": question_id, "effort_model": raw.get("effort_model")},
            "timing_status": timing_status,
            "content_evidence": {
                "worked_example": raw.get("worked_example"),
                "case": raw.get("case"),
                "procedure": raw.get("procedure"),
                "check": raw.get("check"),
                "steps": raw.get("steps", []),
                "comparison": raw.get("comparison"),
                "quiz": raw.get("quiz"),
            },
            "script_anchor_ids": [question_id, *asset_ids],
            "block_signature": _block_signature(raw, job),
        }
        if raw.get("speaker_script"):
            page["planned_speaker_script"] = str(raw["speaker_script"])
        page["suggested_minutes"] = round(lecture + activity, 2)
        page["content_signature"] = canonical_hash({key: page[key] for key in ("primary_job", "knowledge_node_ids", "source_asset_ids", "artifact_type", "content_evidence")})
        pages.append(page)
    if errors:
        raise OrchestrationError("session planning failed:\n- " + "\n- ".join(errors))

    result = {
        "id": session_id,
        "title": str(session.get("title") or session_id),
        "minutes": session.get("minutes"),
        "planning_mode": mode,
        "timing_status": timing_status,
        "timing_reasons": ["one or more questions used a draft fallback because no minutes/effort_model was supplied"] if timing_status == "DEGRADED_ESTIMATE" else [],
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
        "structure_policy": "teaching_questions -> primary_job -> content evidence -> evidence-backed timing -> layout family",
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
    mode = str(course.get("planning_mode") or "draft").lower()
    planned = []
    for session in course.get("sessions", []):
        session_id = str(session.get("id") or "")
        planned.append(plan_session(session, graph_sessions.get(session_id), assets, planning_mode=str(session.get("planning_mode") or mode)))
    return {
        "schema_version": "1.1",
        "plan_type": "content_native_session_plans",
        "course_id": graph.get("course_id"),
        "planning_mode": mode,
        "sessions": planned,
        "evidence_state_model": {"required": "question/contract evidence", "planned": "course-level plan", "observed": "downstream renderer output only"},
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
        print({"sessions": len(result["sessions"]), "slides": sum(len(item["pages"]) for item in result["sessions"]), "planning_mode": result["planning_mode"]})


if __name__ == "__main__":
    main()
