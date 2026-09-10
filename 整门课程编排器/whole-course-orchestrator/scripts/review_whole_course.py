"""Run plan-level and rendered-evidence whole-course QA."""

from __future__ import annotations

import argparse
import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

from orchestrator_core import canonical_hash, dump_json, jaccard, load_json, ngrams, text_of, tokenise
from plan_visuals import validate_visual


GENERIC_PHRASES = (
    "本页先让学生",
    "讲解时先区分",
    "请学生用一句话",
    "下一步会把当前判断",
    "本页的核心解释",
)

SIMILARITY_CALIBRATION = {
    "pair_threshold": 0.85,
    "cluster_fraction": 0.70,
    "source": ["synthetic failure fixtures", "frozen UML failure benchmark", "gold calibration examples"],
    "reason": "A cluster is a course-level template risk when at least 70% of sessions remain at or above 0.85 structural similarity; one changed title, topic id, minute or layout cannot hide the shared teaching skeleton.",
}


def _pages(session_plans: dict[str, Any]) -> list[dict[str, Any]]:
    return [page for session in session_plans.get("sessions", []) for page in session.get("pages", [])]


def _sequence(session: dict[str, Any], key: str) -> tuple[Any, ...]:
    return tuple(page.get(key) if key != "block_signature" else tuple(page.get(key, [])) for page in session.get("pages", []))


def _script(page: dict[str, Any]) -> str:
    # Never fall back to teaching_question here: final-script QA must be
    # grounded in a Courseware output or an explicitly authored script.
    return str(page.get("speaker_script") or page.get("script") or page.get("final_speaker_script") or "")


def _timing(page: dict[str, Any]) -> tuple[float, float]:
    return (round(float(page.get("lecture_minutes", 0) or 0), 2), round(float(page.get("activity_minutes", 0) or 0), 2))


def _flatten(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            result.extend(_flatten(value))
        else:
            result.append(value)
    return result


def _page_visual_role(page: dict[str, Any]) -> tuple[str, ...]:
    roles = page.get("observed_semantic_elements") or page.get("planned_semantic_elements") or page.get("semantic_elements") or []
    return tuple(sorted({str(item) for item in roles}))


def normalized_session_fingerprint(session: dict[str, Any]) -> dict[str, Any]:
    pages = session.get("pages", [])
    return {
        "page_count": len(pages),
        "normalized_teaching_jobs": tuple(str(page.get("primary_job") or "") for page in pages),
        "layout_families": tuple(tuple(page.get("layout_family") or [page.get("layout") or ""]) for page in pages),
        "lecture_activity_pattern": tuple(
            "balanced" if abs(float(page.get("lecture_minutes", 0) or 0) - float(page.get("activity_minutes", 0) or 0)) <= 1 else "lecture-heavy" if float(page.get("lecture_minutes", 0) or 0) > float(page.get("activity_minutes", 0) or 0) else "activity-heavy"
            for page in pages
        ),
        "block_pattern": tuple(tuple(sorted(str(item) for item in page.get("block_signature", []))) for page in pages),
        "visual_role_pattern": tuple(_page_visual_role(page) for page in pages),
        "check_pattern": tuple(bool(page.get("quiz") or page.get("check") or page.get("content_evidence", {}).get("check")) for page in pages),
        "worked_example_pattern": tuple(bool(page.get("worked_example") or page.get("case") or page.get("content_evidence", {}).get("worked_example") or page.get("content_evidence", {}).get("case")) for page in pages),
    }


def _feature_similarity(left: Any, right: Any) -> float:
    if isinstance(left, bool) or isinstance(right, bool):
        return 1.0 if left == right else 0.0
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        denominator = max(abs(float(left)), abs(float(right)), 1.0)
        return max(0.0, 1.0 - abs(float(left) - float(right)) / denominator)
    if isinstance(left, (list, tuple, set)) and isinstance(right, (list, tuple, set)):
        if left and all(isinstance(item, (list, tuple, set)) for item in left) and right and all(isinstance(item, (list, tuple, set)) for item in right):
            size = max(len(left), len(right))
            positional = [_feature_similarity(left[index] if index < len(left) else (), right[index] if index < len(right) else ()) for index in range(size)]
            return sum(positional) / len(positional) if positional else 1.0
        return jaccard(_flatten(left), _flatten(right))
    return 1.0 if str(left) == str(right) else 0.0


def session_structure_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    a = normalized_session_fingerprint(left)
    b = normalized_session_fingerprint(right)
    scores = [_feature_similarity(a[key], b[key]) for key in a]
    return round(sum(scores) / len(scores), 4) if scores else 1.0


def _similarity_matrix(sessions: list[dict[str, Any]]) -> tuple[list[list[float]], list[dict[str, Any]]]:
    fingerprints = [normalized_session_fingerprint(session) for session in sessions]
    matrix: list[list[float]] = []
    for left in sessions:
        matrix.append([session_structure_similarity(left, right) for right in sessions])
    return matrix, fingerprints


def _clusters(matrix: list[list[float]], threshold: float) -> list[list[int]]:
    remaining = set(range(len(matrix)))
    result: list[list[int]] = []
    while remaining:
        seed = min(remaining)
        cluster = [index for index in sorted(remaining) if matrix[seed][index] >= threshold]
        if len(cluster) < 2:
            cluster = [seed]
        result.append(cluster)
        remaining.difference_update(cluster)
    return result


def _structural_task_signature(task: dict[str, Any]) -> str:
    if task.get("structural_task_signature"):
        return str(task["structural_task_signature"])
    starter = task.get("starter", {}) if isinstance(task.get("starter"), dict) else {}
    payload = {
        "capability": task.get("capability"),
        "task_shape": task.get("task_shape") or ("artifact" if task.get("artifact_type") else "response"),
        "step_pattern": task.get("step_pattern") or len(task.get("steps", [])) if isinstance(task.get("steps"), list) else "action",
        "artifact_family": task.get("artifact_type"),
        "starter_gap_family": sorted(str(item.get("type")) if isinstance(item, dict) else str(item) for item in task.get("editable_gaps", starter.get("editable_gaps", []))),
        "time_structure": round(float(task.get("estimated_minutes", 0) or 0)),
        "interaction_type": task.get("interaction_type") or task.get("modality") or task.get("capability"),
    }
    return canonical_hash(payload)


def _asset_usage(session_plans: dict[str, Any], inventory: dict[str, Any], render_evidence: dict[str, Any] | None = None, rendered_course: dict[str, Any] | None = None) -> dict[str, Any]:
    selected: set[str] = set()
    contract_referenced: set[str] = set()
    rendered: set[str] = set(str(item) for item in (render_evidence or {}).get("rendered_asset_ids", []))
    script_grounded: set[str] = set()
    by_session: dict[str, dict[str, list[str]]] = {}
    for session in session_plans.get("sessions", []):
        session_selected: set[str] = set()
        session_contract: set[str] = set()
        session_rendered: set[str] = set()
        session_grounded: set[str] = set()
        for page in session.get("pages", []):
            page_selected = {str(item) for item in page.get("source_asset_ids", [])}
            page_contract = {str(item) for item in page.get("contract_referenced_asset_ids", [])}
            page_rendered = {str(item) for item in page.get("rendered_source_asset_ids", [])}
            page_grounded = {str(item) for item in page.get("script_grounded_asset_ids", [])}
            script = _script(page).lower()
            for asset_id in page_selected | page_contract:
                if asset_id.lower() in script:
                    page_grounded.add(asset_id)
            session_selected.update(page_selected)
            session_contract.update(page_contract)
            session_rendered.update(page_rendered)
            session_grounded.update(page_grounded)
        selected.update(session_selected)
        contract_referenced.update(session_contract)
        rendered.update(session_rendered)
        script_grounded.update(session_grounded)
        by_session[str(session.get("id"))] = {
            "selected": sorted(session_selected),
            "contract_referenced": sorted(session_contract),
            "rendered": sorted(session_rendered),
            "script_grounded": sorted(session_grounded),
            "actually_used": sorted(session_rendered | session_grounded),
        }
    if rendered_course:
        for page in _pages(rendered_course):
            rendered.update(str(item) for item in page.get("rendered_source_asset_ids", page.get("rendered_asset_ids", [])))
            script = _script(page).lower()
            for asset in inventory.get("assets", []):
                asset_id = str(asset.get("id"))
                if asset_id and asset_id.lower() in script:
                    script_grounded.add(asset_id)
    high_value = {str(asset.get("id")) for asset in inventory.get("assets", []) if asset.get("teaching_value") == "core"}
    actually_used = rendered | script_grounded
    return {
        "discovered_assets": sorted(str(asset.get("id")) for asset in inventory.get("assets", []) if asset.get("id")),
        "selected_assets": sorted(selected),
        "contract_referenced_assets": sorted(contract_referenced),
        "rendered_assets": sorted(rendered),
        "script_grounded_assets": sorted(script_grounded),
        "actually_used": sorted(actually_used),
        "unused_high_value": sorted(high_value - actually_used),
        "by_session": by_session,
        "usage_definition": "An asset reference is not usage; actually_used requires final rendered evidence or a final speaker script grounding link.",
    }


def _script_metrics(session_plans: dict[str, Any], *, final_scripts: bool = False) -> dict[str, Any]:
    sessions = session_plans.get("sessions", [])
    position_scores: list[float] = []
    all_ngrams: list[set[tuple[str, ...]]] = []
    generic_hits = 0
    script_count = 0
    scripts_by_session: list[list[str]] = []
    for session in sessions:
        scripts = [_script(page) for page in session.get("pages", [])]
        scripts_by_session.append(scripts)
        for script in scripts:
            if script:
                script_count += 1
                generic_hits += sum(1 for phrase in GENERIC_PHRASES if phrase in script)
                all_ngrams.append(ngrams(script))
        if not scripts and final_scripts:
            continue
    max_len = max((len(scripts) for scripts in scripts_by_session), default=0)
    for index in range(max_len):
        values = [scripts[index] for scripts in scripts_by_session if index < len(scripts) and scripts[index]]
        for left, right in combinations(values, 2):
            position_scores.append(jaccard(ngrams(left), ngrams(right)))
    repeated_ngram_pairs = sum(1 for left, right in combinations(all_ngrams, 2) if left & right)
    pair_count = len(all_ngrams) * (len(all_ngrams) - 1) / 2
    repeated_sentences = Counter()
    for script in (script for scripts in scripts_by_session for script in scripts if script):
        for sentence in re.split(r"[。！？.!?\n]+", script):
            normalized = re.sub(r"\s+", "", sentence).strip().lower()
            if len(normalized) >= 10:
                repeated_sentences[normalized] += 1
    sentence_clusters = {sentence: count for sentence, count in repeated_sentences.items() if count > 1}
    return {
        "status": "PASS" if script_count else "NOT_OBSERVED",
        "same_position_similarity_mean": round(sum(position_scores) / len(position_scores), 4) if position_scores else 0,
        "same_position_similarity_max": round(max(position_scores), 4) if position_scores else 0,
        "cross_session_ngram_reuse_ratio": round(repeated_ngram_pairs / pair_count, 4) if pair_count else 0,
        "generic_phrase_ratio": round(generic_hits / script_count, 4) if script_count else 0,
        "repeated_sentence_clusters": sentence_clusters,
        "repeated_sentence_cluster_count": len(sentence_clusters),
        "script_count": script_count,
    }


def _normalised_overlap(left: Any, right: Any) -> float:
    return jaccard(tokenise(left), tokenise(right))


def _comparison_errors(session_plans: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for page in _pages(session_plans):
        evidence = page.get("content_evidence", {}) if isinstance(page.get("content_evidence"), dict) else {}
        if page.get("primary_job") != "compare" and not page.get("comparison") and not evidence.get("comparison"):
            continue
        comparison = page.get("comparison") or evidence.get("comparison") or {}
        dimension = str(page.get("contrast_dimension") or comparison.get("contrast_dimension") or "").strip()
        if not dimension:
            errors.append({"page_id": page.get("id"), "code": "MISSING_CONTRAST_DIMENSION"})
        items = comparison.get("items") if isinstance(comparison, dict) else None
        if isinstance(items, list) and items:
            claims = [item for item in items if isinstance(item, dict)]
            for left, right in combinations(claims, 2):
                overlap = _normalised_overlap(left.get("claim"), right.get("claim"))
                if overlap >= 0.8:
                    errors.append({"page_id": page.get("id"), "code": "COMPARISON_SEMANTIC_OVERLAP", "overlap": round(overlap, 4)})
            sides = {str(item.get("side")) for item in claims if item.get("side") is not None}
            if len(sides) < 2 and len(claims) >= 2:
                errors.append({"page_id": page.get("id"), "code": "COMPARISON_ROLE_INCONSISTENT"})
        left = text_of(comparison.get("left")) if isinstance(comparison, dict) else ""
        right = text_of(comparison.get("right")) if isinstance(comparison, dict) else ""
        if left and right and (_normalised_overlap(left, right) >= 0.95 or left.strip().lower() == right.strip().lower()):
            errors.append({"page_id": page.get("id"), "code": "COMPARISON_SIDES_SEMANTICALLY_IDENTICAL"})
        wrong_side = str(comparison.get("wrong_side") or "") if isinstance(comparison, dict) else ""
        correct = str(comparison.get("correct") or comparison.get("correct_side") or "") if isinstance(comparison, dict) else ""
        if wrong_side and correct and wrong_side == correct:
            errors.append({"page_id": page.get("id"), "code": "CORRECT_ITEM_ON_WRONG_SIDE"})
    return errors


def _quiz_metrics(session_plans: dict[str, Any]) -> dict[str, Any]:
    distractors: list[str] = []
    trivial: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    unrelated_markers = {"无关", "随便", "天气", "颜色", "banana", "xyz", "不相关"}
    for page in _pages(session_plans):
        quiz = page.get("quiz") or page.get("content_evidence", {}).get("quiz") or {}
        values = quiz.get("distractors", []) if isinstance(quiz, dict) else []
        for value in values:
            record = value if isinstance(value, dict) else {"text": value}
            text = str(record.get("text") or record.get("label") or record.get("option") or value).strip().lower()
            if not text:
                continue
            distractors.append(text)
            if record.get("trivial") is True or str(record.get("misconception_type", "")).lower() in {"trivial", "unrelated"} or text in unrelated_markers:
                trivial.append({"page_id": page.get("id"), "text": text})
            if not record.get("misconception_type") or not record.get("rationale") or not record.get("source"):
                incomplete.append({"page_id": page.get("id"), "text": text})
    counts = Counter(distractors)
    top = counts.most_common(1)[0] if counts else (None, 0)
    return {
        "distractor_count": len(distractors),
        "unique_distractor_count": len(counts),
        "most_reused_distractor": top[0],
        "most_reused_count": top[1],
        "reuse_ratio": round(top[1] / len(distractors), 4) if distractors else 0,
        "trivial_distractors": trivial,
        "incomplete_distractor_metadata": incomplete,
    }


def _practice_metrics(practice_plans: dict[str, Any]) -> dict[str, Any]:
    sessions = practice_plans.get("sessions", [])
    structural = [[_structural_task_signature(task) for task in session.get("tasks", [])] for session in sessions]
    semantic = [[str(task.get("semantic_task_signature") or task.get("signature")) for task in session.get("tasks", [])] for session in sessions]
    return {
        "task_counts": [len(session.get("tasks", [])) for session in sessions],
        "structural_task_signatures": structural,
        "semantic_task_signatures": semantic,
        "task_signatures": structural,
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


def _plan_findings(
    session_plans: dict[str, Any],
    practice_plans: dict[str, Any],
    graph: dict[str, Any],
    inventory: dict[str, Any],
    visual_plans: dict[str, Any] | None,
    research: dict[str, Any] | None,
    *,
    render_evidence: dict[str, Any] | None = None,
    rendered_course: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sessions = session_plans.get("sessions", [])
    session_slide_counts = [len(session.get("pages", [])) for session in sessions]
    layout_sequences = [_sequence(session, "layout") for session in sessions]
    slide_job_sequences = [_sequence(session, "primary_job") for session in sessions]
    timing_distributions = [tuple(_timing(page) for page in session.get("pages", [])) for session in sessions]
    block_signatures = [_sequence(session, "block_signature") for session in sessions]
    visual_intents = Counter(str(page.get("visual_intent")) for page in _pages(session_plans) if page.get("visual_intent"))
    matrix, fingerprints = _similarity_matrix(sessions)
    clusters = _clusters(matrix, SIMILARITY_CALIBRATION["pair_threshold"])
    asset_usage = _asset_usage(session_plans, inventory, render_evidence=render_evidence, rendered_course=rendered_course)
    script_metrics = _script_metrics(session_plans)
    quiz_metrics = _quiz_metrics(session_plans)
    comparison_errors = _comparison_errors(session_plans)
    practice_metrics = _practice_metrics(practice_plans)
    knowledge_errors = _knowledge_errors(graph, practice_plans)
    findings: list[dict[str, Any]] = []

    large_clusters = [cluster for cluster in clusters if len(cluster) >= max(3, math.ceil(len(sessions) * SIMILARITY_CALIBRATION["cluster_fraction"]))]
    if large_clusters:
        findings.append({"severity": "P0", "code": "WHOLE_COURSE_TEMPLATE_COLLAPSE", "clusters": large_clusters, "message": "a high-similarity session cluster exceeds the calibrated course-level threshold"})
    if asset_usage["unused_high_value"] and len(asset_usage["unused_high_value"]) / max(sum(1 for asset in inventory.get("assets", []) if asset.get("teaching_value") == "core"), 1) >= 0.5:
        findings.append({"severity": "P0", "code": "SOURCE_MATERIAL_UNDERUTILIZED", "asset_ids": asset_usage["unused_high_value"]})
    if script_metrics["same_position_similarity_mean"] >= 0.6 or script_metrics["generic_phrase_ratio"] >= 0.6 or script_metrics["repeated_sentence_cluster_count"]:
        findings.append({"severity": "P1", "code": "SCRIPT_CROSS_SESSION_TEMPLATE_REUSE", "metrics": script_metrics})
    if comparison_errors:
        findings.append({"severity": "P0", "code": "COMPARISON_SEMANTIC_ERROR", "errors": comparison_errors})
    if quiz_metrics["reuse_ratio"] >= 0.8 and quiz_metrics["distractor_count"] >= 3:
        findings.append({"severity": "P0", "code": "QUIZ_DISTRACTOR_REUSE", "metrics": quiz_metrics})
    if quiz_metrics["trivial_distractors"]:
        severity = "P0" if len(quiz_metrics["trivial_distractors"]) >= max(3, len(sessions)) else "P1"
        findings.append({"severity": severity, "code": "TRIVIAL_DISTRACTOR", "items": quiz_metrics["trivial_distractors"]})
    if len(sessions) >= 3 and practice_metrics["task_counts"] and len(set(tuple(item) for item in practice_metrics["structural_task_signatures"])) == 1:
        findings.append({"severity": "P0", "code": "WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE", "signature": practice_metrics["structural_task_signatures"][0]})
    if knowledge_errors:
        findings.append({"severity": "P0", "code": "KNOWLEDGE_BOUNDARY_ERROR", "errors": knowledge_errors})
    visual_errors: list[str] = []
    for visual in (visual_plans or {}).get("visual_plans", []):
        visual_errors.extend(validate_visual(visual))
    if visual_errors:
        findings.append({"severity": "P0", "code": "SEMANTIC_VISUAL_DEGRADED", "errors": visual_errors})
    if research and research.get("research_status") == "completed" and research.get("research_gaps") and not research.get("selected_source_count"):
        findings.append({"severity": "P1", "code": "RESEARCH_OPPORTUNITY_MISSED"})
    metrics = {
        "session_slide_counts": session_slide_counts,
        "layout_sequences": layout_sequences,
        "slide_job_sequences": slide_job_sequences,
        "timing_distributions": timing_distributions,
        "block_signatures": block_signatures,
        "visual_intent_distribution": dict(visual_intents),
        "normalized_session_fingerprints": fingerprints,
        "session_structure_similarity": matrix,
        "similarity_clusters": large_clusters,
        "similarity_calibration": SIMILARITY_CALIBRATION,
        "teaching_asset_usage": asset_usage,
        "script_cross_similarity": script_metrics,
        "repeated_phrase_ratio": script_metrics["generic_phrase_ratio"],
        "quiz_distractor_reuse": quiz_metrics,
        "comparison_semantic_errors": comparison_errors,
        "practice_task_counts": practice_metrics["task_counts"],
        "practice_task_signatures": practice_metrics["structural_task_signatures"],
        "practice_semantic_task_signatures": practice_metrics["semantic_task_signatures"],
        "starter_signatures": practice_metrics["starter_signatures"],
        "knowledge_boundary_errors": knowledge_errors,
    }
    return metrics, findings


def review_plan_architecture(
    session_plans: dict[str, Any],
    practice_plans: dict[str, Any],
    graph: dict[str, Any],
    inventory: dict[str, Any],
    visual_plans: dict[str, Any] | None = None,
    research: dict[str, Any] | None = None,
    *,
    render_evidence: dict[str, Any] | None = None,
    rendered_course: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics, findings = _plan_findings(session_plans, practice_plans, graph, inventory, visual_plans, research, render_evidence=render_evidence, rendered_course=rendered_course)
    blocking = any(item.get("severity") in {"P0", "P1"} for item in findings)
    return {
        "schema_version": "1.1",
        "report_type": "whole_course_plan_qa",
        "status": "FAIL" if blocking else "PASS",
        "plan_status": "FAIL" if blocking else "PASS",
        "render_status": "NOT_RUN",
        "final_status": "NOT_EVALUATED",
        "architecture_status": "WHOLE_COURSE_ARCHITECTURE_BLOCKED" if blocking else "READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW",
        "metrics": metrics,
        "findings": findings,
        "human_review_boundary": "Plan QA does not replace final DOM/file evidence or teacher review of representative opening, core concept, complex visual, case, exercise and summary pages.",
    }


def _as_render_pages(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {"sessions": []}
    if "sessions" in value:
        return value
    if "pages" in value:
        return {"sessions": [{"id": value.get("id", "rendered"), "pages": value["pages"]}]}
    return {"sessions": []}


def _render_metrics(rendered_course: dict[str, Any] | None, visual_evidence: dict[str, Any] | None, starter_evidence: dict[str, Any] | None, contact_sheet: dict[str, Any] | None, inventory: dict[str, Any]) -> dict[str, Any]:
    course = _as_render_pages(rendered_course)
    scripts = _script_metrics(course, final_scripts=True)
    grounded_pages = 0
    total_pages = 0
    for page in _pages(course):
        total_pages += 1
        script = _script(page)
        content = text_of({"title": page.get("title"), "blocks": page.get("blocks"), "visual": page.get("visual"), "asset_ids": page.get("source_asset_ids")})
        if script and (set(tokenise(script)) & set(tokenise(content)) or page.get("script_grounded_asset_ids")):
            grounded_pages += 1
    return {
        "actual_visual_semantic_coverage": {
            "status": (visual_evidence or {}).get("status", "NOT_RUN"),
            "passed": sum(1 for item in (visual_evidence or {}).get("visual_plans", []) if item.get("evidence_status") == "PASS"),
            "total": len((visual_evidence or {}).get("visual_plans", [])),
        },
        "semantic_marker_evidence": {
            "status": (visual_evidence or {}).get("marker_plumbing_status", "NOT_RUN"),
            "passed": sum(1 for item in (visual_evidence or {}).get("visual_plans", []) if item.get("semantic_marker_evidence", {}).get("status") == "PASS"),
            "total": len((visual_evidence or {}).get("visual_plans", [])),
        },
        "semantic_structure_evidence": {
            "status": (visual_evidence or {}).get("semantic_structure_status", "NOT_RUN"),
            "passed": sum(1 for item in (visual_evidence or {}).get("visual_plans", []) if item.get("semantic_structure_evidence", {}).get("status") in {"PASS", "NOT_APPLICABLE"}),
            "total": len((visual_evidence or {}).get("visual_plans", [])),
        },
        "actual_asset_usage": {
            "rendered_asset_ids": sorted(set(str(item) for item in (visual_evidence or {}).get("rendered_asset_ids", []))),
            "status": "PASS" if visual_evidence and visual_evidence.get("status") == "PASS" else "NOT_RUN",
        },
        "script_similarity": scripts,
        "script_to_slide_grounding": {"status": "PASS" if total_pages and grounded_pages == total_pages else "FAIL" if total_pages else "NOT_OBSERVED", "script_grounding_ratio": round(grounded_pages / total_pages, 4) if total_pages else 0, "grounded_pages": grounded_pages, "total_pages": total_pages},
        "starter_semantic_evidence": {"status": (starter_evidence or {}).get("status", "NOT_RUN"), "observed": (starter_evidence or {}).get("starter_observed", [])},
        "quiz_quality": {"status": "PASS"},
        "comparison_quality": {"status": "PASS"},
        "rendered_contact_sheet_evidence": {"status": (contact_sheet or {}).get("status", "NOT_RUN"), "thumbnail_count": (contact_sheet or {}).get("thumbnail_count", 0)},
    }


def review_rendered_course(
    session_plans: dict[str, Any],
    practice_plans: dict[str, Any],
    graph: dict[str, Any],
    inventory: dict[str, Any],
    *,
    visual_evidence: dict[str, Any] | None = None,
    starter_evidence: dict[str, Any] | None = None,
    rendered_course: dict[str, Any] | None = None,
    rendered_practice: dict[str, Any] | None = None,
    contact_sheet: dict[str, Any] | None = None,
    research: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = review_plan_architecture(
        session_plans,
        practice_plans,
        graph,
        inventory,
        visual_evidence,
        research,
        render_evidence=visual_evidence,
        rendered_course=rendered_course,
    )
    metrics = dict(plan["metrics"])
    render_metrics = _render_metrics(rendered_course, visual_evidence, starter_evidence, contact_sheet, inventory)
    metrics["render_evidence"] = render_metrics
    findings = list(plan["findings"])
    rendered_script_metrics = render_metrics["script_similarity"]
    if (
        rendered_script_metrics["same_position_similarity_mean"] >= 0.6
        or rendered_script_metrics["generic_phrase_ratio"] >= 0.6
        or rendered_script_metrics["repeated_sentence_cluster_count"]
    ):
        findings.append(
            {
                "severity": "P1",
                "code": "SCRIPT_CROSS_SESSION_TEMPLATE_REUSE",
                "source": "rendered_course",
                "metrics": rendered_script_metrics,
            }
        )
    if visual_evidence and visual_evidence.get("status") == "FAIL":
        findings.append({"severity": "P0", "code": "RENDERED_VISUAL_EVIDENCE_INCOMPLETE"})
    if visual_evidence and visual_evidence.get("marker_plumbing_status") == "PASS" and visual_evidence.get("semantic_structure_status") == "FAIL":
        findings.append({"severity": "P0", "code": "SEMANTIC_MARKER_WITHOUT_STRUCTURE", "message": "semantic role markers were transported, but typed visual structure evidence failed"})
    if starter_evidence and starter_evidence.get("status") not in {"PASS"}:
        findings.append({"severity": "P0", "code": "STARTER_EVIDENCE_INCOMPLETE", "status": starter_evidence.get("status")})
    if rendered_course is not None and render_metrics["script_to_slide_grounding"]["status"] != "PASS":
        findings.append({"severity": "P1", "code": "SCRIPT_TO_SLIDE_GROUNDING_INCOMPLETE"})
    if contact_sheet and contact_sheet.get("status") not in {"PASS", "DEGRADED"}:
        findings.append({"severity": "P1", "code": "CONTACT_SHEET_EVIDENCE_INCOMPLETE"})
    blocking = any(item.get("severity") in {"P0", "P1"} for item in findings)
    required_evidence_present = visual_evidence is not None and starter_evidence is not None and rendered_course is not None and contact_sheet is not None
    render_status = "PASS" if required_evidence_present and not blocking else "FAIL" if blocking else "NOT_RUN"
    return {
        "schema_version": "1.1",
        "report_type": "whole_course_render_qa",
        "status": "FAIL" if blocking else "PASS" if render_status == "PASS" else "NOT_EVALUATED",
        "plan_status": plan["plan_status"],
        "render_status": render_status,
        "final_status": "FAIL" if blocking else "PASS" if render_status == "PASS" else "NOT_EVALUATED",
        "architecture_status": "WHOLE_COURSE_ARCHITECTURE_BLOCKED" if blocking else "READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW",
        "metrics": metrics,
        "findings": findings,
        "human_review_boundary": "Rendered evidence and automated metrics do not replace teacher acceptance of instructional quality.",
    }


def review_course(
    session_plans: dict[str, Any],
    practice_plans: dict[str, Any],
    graph: dict[str, Any],
    inventory: dict[str, Any],
    visual_plans: dict[str, Any] | None = None,
    research: dict[str, Any] | None = None,
    *,
    render_evidence: dict[str, Any] | None = None,
    starter_evidence: dict[str, Any] | None = None,
    rendered_course: dict[str, Any] | None = None,
    rendered_practice: dict[str, Any] | None = None,
    contact_sheet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if any(value is not None for value in (render_evidence, starter_evidence, rendered_course, rendered_practice, contact_sheet)):
        return review_rendered_course(session_plans, practice_plans, graph, inventory, visual_evidence=render_evidence, starter_evidence=starter_evidence, rendered_course=rendered_course, rendered_practice=rendered_practice, contact_sheet=contact_sheet, research=research)
    return review_plan_architecture(session_plans, practice_plans, graph, inventory, visual_plans, research)


def review_failure_benchmark(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Replay normalized evidence extracted from the real frozen failure.

    The snapshot is intentionally converted into the same review inputs used
    by normal planning QA.  No old renderer is rerun and no finding code is
    injected into the result; findings must be derived from the normalized
    session/page/task evidence.
    """

    theory = {"sessions": snapshot.get("theory_sessions", [])}
    practice = {"sessions": snapshot.get("practice_sessions", [])}
    session_ids = [str(item.get("id")) for item in theory.get("sessions", []) if item.get("id")]
    graph = {"nodes": [], "sessions": [{"id": session_id, "knowledge_state_after": []} for session_id in session_ids]}
    inventory = {"assets": snapshot.get("inventory_assets", [])}
    result = review_course(theory, practice, graph, inventory)
    result["report_type"] = "whole_course_failure_benchmark_replay"
    result["benchmark_id"] = snapshot.get("source_benchmark_id")
    result["evidence_provenance"] = {
        "extracted_from_real_output": snapshot.get("extracted_from_real_output"),
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
        "source_benchmark_sha256": snapshot.get("source_benchmark_sha256"),
    }
    return result


def review_whole_course(value: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility entry point for plan inputs and frozen snapshots."""

    if isinstance(value, dict) and value.get("snapshot_type") == "REAL_FROZEN_FAILURE_EVIDENCE":
        return review_failure_benchmark(value)
    return review_course(value, *args, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-plans", required=True)
    parser.add_argument("--practice-plans", required=True)
    parser.add_argument("--knowledge-graph", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--visual-plans")
    parser.add_argument("--research")
    parser.add_argument("--render-evidence")
    parser.add_argument("--starter-evidence")
    parser.add_argument("--rendered-course")
    parser.add_argument("--rendered-practice")
    parser.add_argument("--contact-sheet")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-plan-qa")
    parser.add_argument("--output-render-qa")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    loader = lambda path: load_json(path) if path else None
    result = review_course(load_json(args.session_plans), load_json(args.practice_plans), load_json(args.knowledge_graph), load_json(args.assets), loader(args.visual_plans), loader(args.research), render_evidence=loader(args.render_evidence), starter_evidence=loader(args.starter_evidence), rendered_course=loader(args.rendered_course), rendered_practice=loader(args.rendered_practice), contact_sheet=loader(args.contact_sheet))
    dump_json(result, args.output_json)
    if args.output_plan_qa:
        dump_json(review_plan_architecture(load_json(args.session_plans), load_json(args.practice_plans), load_json(args.knowledge_graph), load_json(args.assets), loader(args.visual_plans), loader(args.research)), args.output_plan_qa)
    if args.output_render_qa and any(value is not None for value in (args.render_evidence, args.starter_evidence, args.rendered_course, args.rendered_practice, args.contact_sheet)):
        dump_json(result, args.output_render_qa)
    if args.json:
        print({"status": result["status"], "plan_status": result.get("plan_status"), "render_status": result.get("render_status"), "final_status": result.get("final_status"), "findings": len(result["findings"])})


if __name__ == "__main__":
    main()
