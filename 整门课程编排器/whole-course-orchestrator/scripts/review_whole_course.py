"""Run whole-course batch QA across theory plans, practice plans, sources and graph state."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from itertools import combinations
from typing import Any, Iterable

from orchestrator_core import dump_json, jaccard, load_json, ngrams, text_of
from plan_visuals import validate_visual


GENERIC_PHRASES = (
    "本页先让学生",
    "讲解时先区分",
    "请学生用一句话",
    "下一步会把当前判断",
    "本页的核心解释",
)


def _pages(session_plans: dict[str, Any]) -> list[dict[str, Any]]:
    return [page for session in session_plans.get("sessions", []) for page in session.get("pages", [])]


def _sequence(session: dict[str, Any], key: str) -> tuple[Any, ...]:
    return tuple(page.get(key) if key != "block_signature" else tuple(page.get(key, [])) for page in session.get("pages", []))


def _script(page: dict[str, Any]) -> str:
    return str(page.get("speaker_script") or page.get("script") or page.get("content_evidence", {}).get("speaker_script") or page.get("teaching_question") or "")


def _timing(page: dict[str, Any]) -> tuple[float, float]:
    return (round(float(page.get("lecture_minutes", 0) or 0), 2), round(float(page.get("activity_minutes", 0) or 0), 2))


def _asset_usage(session_plans: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    selected: set[str] = set()
    used: set[str] = set()
    by_session: dict[str, dict[str, list[str]]] = {}
    for session in session_plans.get("sessions", []):
        session_selected: set[str] = set()
        session_used: set[str] = set()
        for page in session.get("pages", []):
            session_selected.update(str(item) for item in page.get("source_asset_ids", []))
            session_used.update(str(item) for item in page.get("used_source_asset_ids", page.get("source_asset_ids", [])))
        selected.update(session_selected)
        used.update(session_used)
        by_session[str(session.get("id"))] = {"selected": sorted(session_selected), "used": sorted(session_used)}
    high_value = {str(asset.get("id")) for asset in inventory.get("assets", []) if asset.get("teaching_value") == "core"}
    return {
        "selected": sorted(selected),
        "actually_used": sorted(used),
        "unused_high_value": sorted(high_value - used),
        "by_session": by_session,
    }


def _script_metrics(session_plans: dict[str, Any]) -> dict[str, Any]:
    sessions = session_plans.get("sessions", [])
    position_scores: list[float] = []
    all_ngrams: list[set[tuple[str, ...]]] = []
    generic_hits = 0
    script_count = 0
    for session in sessions:
        scripts = [_script(page) for page in session.get("pages", [])]
        for script in scripts:
            if script:
                script_count += 1
                generic_hits += sum(1 for phrase in GENERIC_PHRASES if phrase in script)
                all_ngrams.append(ngrams(script))
        if not sessions:
            continue
    max_len = max((len(session.get("pages", [])) for session in sessions), default=0)
    for index in range(max_len):
        values = [_script(session["pages"][index]) for session in sessions if index < len(session.get("pages", []))]
        for left, right in combinations(values, 2):
            position_scores.append(jaccard(ngrams(left), ngrams(right)))
    repeated_ngram_count = sum(1 for pair in combinations(range(len(all_ngrams)), 2) if all_ngrams[pair[0]] & all_ngrams[pair[1]])
    pair_count = len(all_ngrams) * (len(all_ngrams) - 1) / 2
    return {
        "same_position_similarity_mean": round(sum(position_scores) / len(position_scores), 4) if position_scores else 0,
        "same_position_similarity_max": round(max(position_scores), 4) if position_scores else 0,
        "cross_session_ngram_reuse_ratio": round(repeated_ngram_count / pair_count, 4) if pair_count else 0,
        "generic_phrase_ratio": round(generic_hits / script_count, 4) if script_count else 0,
        "script_count": script_count,
    }


def _comparison_errors(session_plans: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for page in _pages(session_plans):
        if page.get("primary_job") != "compare" and not page.get("comparison") and not page.get("content_evidence", {}).get("comparison"):
            continue
        comparison = page.get("comparison") or page.get("content_evidence", {}).get("comparison") or {}
        left = text_of(comparison.get("left"))
        right = text_of(comparison.get("right"))
        dimension = str(page.get("contrast_dimension") or comparison.get("contrast_dimension") or "").strip()
        if not dimension:
            errors.append({"page_id": page.get("id"), "code": "MISSING_CONTRAST_DIMENSION"})
        if left and right and left.strip().lower() == right.strip().lower():
            errors.append({"page_id": page.get("id"), "code": "COMPARISON_SIDES_SEMANTICALLY_IDENTICAL"})
        wrong_side = str(comparison.get("wrong_side") or "")
        correct = str(comparison.get("correct") or comparison.get("correct_side") or "")
        if wrong_side and correct and wrong_side == correct:
            errors.append({"page_id": page.get("id"), "code": "CORRECT_ITEM_ON_WRONG_SIDE"})
    return errors


def _quiz_metrics(session_plans: dict[str, Any]) -> dict[str, Any]:
    distractors: list[str] = []
    for page in _pages(session_plans):
        quiz = page.get("quiz") or page.get("content_evidence", {}).get("quiz") or {}
        values = quiz.get("distractors", []) if isinstance(quiz, dict) else []
        distractors.extend(str(item).strip().lower() for item in values if str(item).strip())
    counts = Counter(distractors)
    top = counts.most_common(1)[0] if counts else (None, 0)
    return {
        "distractor_count": len(distractors),
        "unique_distractor_count": len(counts),
        "most_reused_distractor": top[0],
        "most_reused_count": top[1],
        "reuse_ratio": round(top[1] / len(distractors), 4) if distractors else 0,
    }


def _practice_metrics(practice_plans: dict[str, Any]) -> dict[str, Any]:
    sessions = practice_plans.get("sessions", [])
    return {
        "task_counts": [len(session.get("tasks", [])) for session in sessions],
        "task_signatures": [tuple(task.get("signature") for task in session.get("tasks", [])) for session in sessions],
        "task_capabilities": [tuple(task.get("capability") for task in session.get("tasks", [])) for session in sessions],
        "time_patterns": [tuple(round(float(task.get("estimated_minutes", 0) or 0), 2) for task in session.get("tasks", [])) for session in sessions],
        "starter_signatures": [tuple((task.get("starter", {}).get("artifact_type"), tuple(task.get("starter", {}).get("components", []))) for task in session.get("tasks", [])) for session in sessions],
    }


def _knowledge_errors(graph: dict[str, Any], practice_plans: dict[str, Any]) -> list[str]:
    state = {str(session.get("id")): set(session.get("knowledge_state_after", [])) for session in graph.get("sessions", [])}
    errors: list[str] = []
    for session in practice_plans.get("sessions", []):
        allowed = state.get(str(session.get("id")), set())
        for task in session.get("tasks", []):
            for node_id in task.get("knowledge_node_ids", []):
                if node_id not in allowed:
                    errors.append(f"{session.get('id')}/{task.get('id')}: knowledge used before taught: {node_id}")
    return errors


def review_course(
    session_plans: dict[str, Any],
    practice_plans: dict[str, Any],
    graph: dict[str, Any],
    inventory: dict[str, Any],
    visual_plans: dict[str, Any] | None = None,
    research: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sessions = session_plans.get("sessions", [])
    session_slide_counts = [len(session.get("pages", [])) for session in sessions]
    layout_sequences = [_sequence(session, "layout") for session in sessions]
    slide_job_sequences = [_sequence(session, "primary_job") for session in sessions]
    timing_distributions = [tuple(_timing(page) for page in session.get("pages", [])) for session in sessions]
    block_signatures = [_sequence(session, "block_signature") for session in sessions]
    visual_intents = Counter(str(page.get("visual_intent")) for page in _pages(session_plans) if page.get("visual_intent"))
    asset_usage = _asset_usage(session_plans, inventory)
    script_metrics = _script_metrics(session_plans)
    quiz_metrics = _quiz_metrics(session_plans)
    comparison_errors = _comparison_errors(session_plans)
    practice_metrics = _practice_metrics(practice_plans)
    knowledge_errors = _knowledge_errors(graph, practice_plans)
    findings: list[dict[str, Any]] = []

    if len(sessions) >= 3 and session_slide_counts and len(set(session_slide_counts)) == 1 and len(set(layout_sequences)) == 1 and len(set(slide_job_sequences)) == 1 and len(set(timing_distributions)) == 1 and len(set(block_signatures)) == 1:
        findings.append({"severity": "P0", "code": "WHOLE_COURSE_TEMPLATE_COLLAPSE", "message": "all sessions share page count, layout/jobs, timing and block signatures"})
    if asset_usage["unused_high_value"] and len(asset_usage["unused_high_value"]) / max(sum(1 for asset in inventory.get("assets", []) if asset.get("teaching_value") == "core"), 1) >= 0.5:
        findings.append({"severity": "P0", "code": "SOURCE_MATERIAL_UNDERUTILIZED", "asset_ids": asset_usage["unused_high_value"]})
    if script_metrics["same_position_similarity_mean"] >= 0.6 or script_metrics["generic_phrase_ratio"] >= 0.6:
        findings.append({"severity": "P1", "code": "SCRIPT_CROSS_SESSION_TEMPLATE_REUSE", "metrics": script_metrics})
    if comparison_errors:
        findings.append({"severity": "P0", "code": "COMPARISON_SEMANTIC_ERROR", "errors": comparison_errors})
    if quiz_metrics["reuse_ratio"] >= 0.8 and quiz_metrics["distractor_count"] >= 3:
        findings.append({"severity": "P0", "code": "QUIZ_DISTRACTOR_REUSE", "metrics": quiz_metrics})
    if len(sessions) >= 3 and practice_metrics["task_counts"] and len(set(practice_metrics["task_counts"])) == 1 and len(set(practice_metrics["task_signatures"])) == 1 and len(set(practice_metrics["time_patterns"])) == 1 and len(set(practice_metrics["starter_signatures"])) == 1:
        findings.append({"severity": "P0", "code": "WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE"})
    if knowledge_errors:
        findings.append({"severity": "P0", "code": "KNOWLEDGE_BOUNDARY_ERROR", "errors": knowledge_errors})
    visual_errors = []
    for visual in (visual_plans or {}).get("visual_plans", []):
        visual_errors.extend(validate_visual(visual))
    if visual_errors:
        findings.append({"severity": "P0", "code": "SEMANTIC_VISUAL_DEGRADED", "errors": visual_errors})
    if research and research.get("research_status") == "completed" and research.get("research_gaps") and not research.get("selected_source_count"):
        findings.append({"severity": "P1", "code": "RESEARCH_OPPORTUNITY_MISSED"})

    p0 = any(item.get("severity") == "P0" for item in findings)
    return {
        "schema_version": "1.0",
        "report_type": "whole_course_batch_qa",
        "status": "FAIL" if p0 else "PASS",
        "architecture_status": "WHOLE_COURSE_ARCHITECTURE_BLOCKED" if p0 else "READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW",
        "metrics": {
            "session_slide_counts": session_slide_counts,
            "layout_sequences": layout_sequences,
            "slide_job_sequences": slide_job_sequences,
            "timing_distributions": timing_distributions,
            "block_signatures": block_signatures,
            "visual_intent_distribution": dict(visual_intents),
            "teaching_asset_usage": asset_usage,
            "script_cross_similarity": script_metrics,
            "repeated_phrase_ratio": script_metrics["generic_phrase_ratio"],
            "quiz_distractor_reuse": quiz_metrics,
            "comparison_semantic_errors": comparison_errors,
            "practice_task_counts": practice_metrics["task_counts"],
            "practice_task_signatures": practice_metrics["task_signatures"],
            "starter_signatures": practice_metrics["starter_signatures"],
            "knowledge_boundary_errors": knowledge_errors,
        },
        "findings": findings,
        "human_review_boundary": "Automated batch QA does not replace teacher review of representative opening, core concept, complex visual, case, exercise and summary pages.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-plans", required=True)
    parser.add_argument("--practice-plans", required=True)
    parser.add_argument("--knowledge-graph", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--visual-plans")
    parser.add_argument("--research")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = review_course(
        load_json(args.session_plans),
        load_json(args.practice_plans),
        load_json(args.knowledge_graph),
        load_json(args.assets),
        load_json(args.visual_plans) if args.visual_plans else None,
        load_json(args.research) if args.research else None,
    )
    dump_json(result, args.output_json)
    if args.json:
        print({"status": result["status"], "architecture_status": result["architecture_status"], "findings": len(result["findings"])})


if __name__ == "__main__":
    main()
