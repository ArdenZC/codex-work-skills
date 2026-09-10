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
from external_research import detect_gaps


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
    return [
        page
        for session in session_plans.get("sessions", [])
        if isinstance(session, dict)
        for page in session.get("pages", [])
        if isinstance(page, dict)
    ]


def _sequence(session: dict[str, Any], key: str) -> tuple[Any, ...]:
    return tuple(
        page.get(key) if key != "block_signature" else tuple(page.get(key, []))
        for page in session.get("pages", [])
        if isinstance(page, dict)
    )


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
    pages = [page for page in session.get("pages", []) if isinstance(page, dict)]
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
    fingerprints: list[dict[str, Any]] = []
    for session in sessions:
        tasks = session.get("tasks", []) if isinstance(session, dict) else []
        fingerprints.append({
            "task_count": len(tasks),
            "capability_pattern": tuple(str(task.get("capability") or "") for task in tasks),
            "task_shapes": tuple(str(task.get("task_shape") or ("artifact" if task.get("artifact_type") else "response")) for task in tasks),
            "step_patterns": tuple(tuple(str(step.get("kind") or step.get("type") or "action") if isinstance(step, dict) else "action" for step in task.get("steps", [])) for task in tasks),
            "artifact_families": tuple(str(task.get("artifact_type") or "none") for task in tasks),
            "starter_gap_families": tuple(tuple(sorted(str(item.get("type")) if isinstance(item, dict) else str(item) for item in task.get("editable_gaps", task.get("starter", {}).get("editable_gaps", [])))) for task in tasks),
            "time_pattern_buckets": tuple(int(round(float(task.get("estimated_minutes", 0) or 0) / 5.0)) for task in tasks),
            "interaction_types": tuple(str(task.get("interaction_type") or task.get("modality") or task.get("capability") or "") for task in tasks),
            "levels": tuple(str(task.get("level") or "core") for task in tasks),
        })
    def fingerprint_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
        keys = tuple(left.keys())
        return round(sum(_feature_similarity(left[key], right[key]) for key in keys) / len(keys), 4) if keys else 1.0
    matrix = [[fingerprint_similarity(left, right) for right in fingerprints] for left in fingerprints]
    normalized_threshold = 0.86
    normalized_clusters = _clusters(matrix, normalized_threshold)
    return {
        "task_counts": [len(session.get("tasks", [])) for session in sessions],
        "structural_task_signatures": structural,
        "semantic_task_signatures": semantic,
        "task_signatures": structural,
        "task_capabilities": [tuple(task.get("capability") for task in session.get("tasks", [])) for session in sessions],
        "time_patterns": [tuple(round(float(task.get("estimated_minutes", 0) or 0), 2) for task in session.get("tasks", [])) for session in sessions],
        "starter_signatures": [tuple((task.get("starter", {}).get("artifact_type"), tuple(task.get("starter", {}).get("components", []))) for task in session.get("tasks", [])) for session in sessions],
        "normalized_fingerprints": fingerprints,
        "normalized_similarity_matrix": matrix,
        "normalized_similarity_threshold": normalized_threshold,
        "normalized_similarity_clusters": normalized_clusters,
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


def _integrity_finding(code: str, message: str, *, severity: str = "P0", **details: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message, **details}


def _input_integrity_findings(
    session_plans: Any,
    practice_plans: Any,
    graph: Any,
    inventory: Any,
    visual_plans: Any = None,
) -> list[dict[str, Any]]:
    """Validate cross-artifact shape before metrics are allowed to imply QA."""

    findings: list[dict[str, Any]] = []
    if not isinstance(session_plans, dict):
        findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "session_plans must be an object"))
        return findings
    if not isinstance(practice_plans, dict):
        findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "practice_plans must be an object"))
    if not isinstance(graph, dict):
        findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "knowledge graph must be an object"))
    if not isinstance(inventory, dict):
        findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "teaching asset inventory must be an object"))
    sessions = session_plans.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "session_plans.sessions must be a non-empty list"))
        sessions = []
    session_ids = [str(item.get("id") or "") if isinstance(item, dict) else "" for item in sessions]
    if any(not item for item in session_ids) or len(session_ids) != len(set(session_ids)):
        findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "session plan IDs must be non-empty and unique"))
    page_ids: set[str] = set()
    for session in sessions:
        if not isinstance(session, dict):
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "every planned session must be an object"))
            continue
        pages = session.get("pages")
        if not isinstance(pages, list) or not pages:
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"{session.get('id')}: pages must be a non-empty list"))
            continue
        for page in pages:
            page_id = str(page.get("id") or "") if isinstance(page, dict) else ""
            if not page_id or page_id in page_ids:
                findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"duplicate or missing page id: {page_id or '<missing>'}"))
            page_ids.add(page_id)
            if isinstance(page, dict) and not str(page.get("teaching_question_id") or "").strip():
                findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"{page_id}: teaching_question_id is required"))
    if isinstance(practice_plans, dict):
        practice_sessions = practice_plans.get("sessions")
        if not isinstance(practice_sessions, list):
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "practice_plans.sessions must be a list"))
            practice_sessions = []
        practice_ids = [str(item.get("id") or "") if isinstance(item, dict) else "" for item in practice_sessions]
        if len(practice_ids) != len(set(practice_ids)) or any(not item for item in practice_ids):
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "practice session IDs must be non-empty and unique"))
        missing_practice = sorted(set(session_ids) - set(practice_ids))
        orphan_practice = sorted(set(practice_ids) - set(session_ids))
        if missing_practice or orphan_practice:
            findings.append(_integrity_finding("CROSS_ARTIFACT_COVERAGE_ERROR", "practice sessions do not close over planned sessions", missing_sessions=missing_practice, orphan_sessions=orphan_practice))
        task_ids: set[str] = set()
        for session in practice_sessions:
            if not isinstance(session, dict):
                findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "every practice session must be an object"))
                continue
            tasks = session.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"{session.get('id')}: tasks must be a non-empty list"))
                continue
            for task in tasks:
                task_id = str(task.get("id") or "") if isinstance(task, dict) else ""
                if not task_id or task_id in task_ids:
                    findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"duplicate or missing task id: {task_id or '<missing>'}"))
                task_ids.add(task_id)
    if isinstance(graph, dict):
        graph_sessions = graph.get("sessions")
        if not isinstance(graph_sessions, list):
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "knowledge graph sessions must be a list"))
            graph_sessions = []
        graph_ids = [str(item.get("id") or "") if isinstance(item, dict) else "" for item in graph_sessions]
        if set(session_ids) - set(graph_ids) or set(graph_ids) - set(session_ids):
            findings.append(_integrity_finding("CROSS_ARTIFACT_COVERAGE_ERROR", "knowledge graph/session IDs are not aligned", missing_graph_sessions=sorted(set(session_ids) - set(graph_ids)), orphan_graph_sessions=sorted(set(graph_ids) - set(session_ids))))
    if isinstance(inventory, dict) and not isinstance(inventory.get("assets"), list):
        findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "inventory.assets must be a list"))
    if isinstance(visual_plans, dict):
        visuals = visual_plans.get("visual_plans")
        if not isinstance(visuals, list):
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "visual_plans.visual_plans must be a list"))
        else:
            visual_ids = [str(item.get("page_id") or "") if isinstance(item, dict) else "" for item in visuals]
            if len(visual_ids) != len(set(visual_ids)):
                findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", "visual plan page IDs must be unique"))
            orphans = sorted(set(visual_ids) - page_ids)
            if orphans:
                findings.append(_integrity_finding("CROSS_ARTIFACT_COVERAGE_ERROR", "visual plans contain orphan pages", orphan_visual_pages=orphans))
    for label, value, expected_version, expected_type in (
        ("session_plans", session_plans, {"1.0", "1.1"}, "content_native_session_plans"),
        ("practice_plans", practice_plans, {"1.0", "1.1"}, "whole_course_practice_plans"),
        ("graph", graph, {"1.0", "1.1"}, "course_knowledge_graph"),
        ("inventory", inventory, {"1.0", "1.1"}, "teaching_asset_inventory"),
    ):
        if isinstance(value, dict) and value.get("schema_version") not in {None, *expected_version}:
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"{label}: unsupported schema_version {value.get('schema_version')}"))
        if isinstance(value, dict) and value.get("plan_type") not in {None, expected_type} and label in {"session_plans", "practice_plans"}:
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"{label}: unexpected plan_type {value.get('plan_type')}"))
        if isinstance(value, dict) and value.get("graph_type") not in {None, expected_type} and label == "graph":
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"{label}: unexpected graph_type {value.get('graph_type')}"))
        if isinstance(value, dict) and value.get("inventory_type") not in {None, expected_type} and label == "inventory":
            findings.append(_integrity_finding("INPUT_INTEGRITY_ERROR", f"{label}: unexpected inventory_type {value.get('inventory_type')}"))
    return findings


def _theory_knowledge_errors(session_plans: dict[str, Any], graph: dict[str, Any]) -> list[dict[str, Any]]:
    graph_by_id = {str(item.get("id")): item for item in graph.get("sessions", []) if isinstance(item, dict) and item.get("id")}
    errors: list[dict[str, Any]] = []
    for session in session_plans.get("sessions", []):
        session_id = str(session.get("id"))
        graph_session = graph_by_id.get(session_id, {})
        available = set(str(item) for item in graph_session.get("knowledge_state_before", []))
        new_knowledge = [str(item) for item in graph_session.get("new_knowledge", [])]
        future = set(str(item) for item in graph_session.get("future_knowledge", []))
        for page_index, page in enumerate(session.get("pages", []), start=1):
            if not isinstance(page, dict):
                continue
            page_before = set(str(item) for item in page.get("page_knowledge_state_before", available))
            current_new = set(str(item) for item in page.get("current_new_knowledge_ids", []))
            allowed = page_before | current_new
            refs = [str(item) for item in page.get("knowledge_node_ids", [])]
            illegal = sorted(set(refs) - allowed)
            illegal_future = sorted(set(refs) & future - allowed)
            for node_id in sorted(set(illegal) | set(illegal_future)):
                errors.append({"session_id": session_id, "page_id": page.get("id"), "page_index": page_index, "knowledge_node_id": node_id, "code": "THEORY_KNOWLEDGE_BOUNDARY_ERROR", "allowed_before": sorted(page_before), "current_new": sorted(current_new), "future_knowledge": sorted(future)})
            page_after = set(str(item) for item in page.get("page_knowledge_state_after", allowed))
            available = page_after or (available | current_new)
        # If pages omit explicit state, a graph-level future reference is still
        # invalid; no planner field is allowed to self-certify it.
        if not new_knowledge and future and not session.get("pages"):
            errors.append({"session_id": session_id, "code": "THEORY_KNOWLEDGE_BOUNDARY_ERROR", "message": "session has no pages to establish a knowledge boundary"})
    return errors


def _duration_findings(session_plans: dict[str, Any], practice_plans: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for session in session_plans.get("sessions", []):
        if not isinstance(session, dict):
            continue
        declared = session.get("minutes")
        if declared in (None, ""):
            continue
        try:
            declared_value = float(declared)
        except (TypeError, ValueError):
            findings.append({"severity": "P0", "code": "THEORY_DURATION_MISMATCH", "session_id": session.get("id"), "declared_minutes": declared, "planned_page_minutes": None, "message": "declared session duration is not numeric"})
            continue
        planned = sum(float(page.get("suggested_minutes", 0) or 0) for page in session.get("pages", []) if isinstance(page, dict))
        if abs(declared_value - planned) > 1:
            severity = "P0" if str(session.get("planning_mode") or session_plans.get("planning_mode") or "draft") == "release" else "P1"
            findings.append({"severity": severity, "code": "THEORY_DURATION_MISMATCH", "session_id": session.get("id"), "declared_minutes": declared_value, "planned_page_minutes": planned, "tolerance_minutes": 1})
    practice_by_id = {str(item.get("id")): item for item in practice_plans.get("sessions", []) if isinstance(item, dict)}
    for session in session_plans.get("sessions", []):
        if not isinstance(session, dict):
            continue
        config = session.get("practice") if isinstance(session.get("practice"), dict) else {}
        planned_session = practice_by_id.get(str(session.get("id")), {})
        declared = (
            session.get("practice_minutes")
            or session.get("practice_duration_minutes")
            or config.get("minutes")
            or (planned_session.get("practice_minutes") if isinstance(planned_session, dict) else None)
            or (planned_session.get("duration_minutes") if isinstance(planned_session, dict) else None)
            or (planned_session.get("minutes") if isinstance(planned_session, dict) else None)
        )
        if declared in (None, ""):
            continue
        tasks = planned_session.get("tasks", []) if isinstance(planned_session, dict) else []
        planned = sum(float(task.get("estimated_minutes", 0) or 0) for task in tasks if isinstance(task, dict))
        try:
            declared_value = float(declared)
        except (TypeError, ValueError):
            findings.append({"severity": "P0", "code": "PRACTICE_DURATION_MISMATCH", "session_id": session.get("id"), "declared_minutes": declared, "planned_task_minutes": None, "message": "declared practice duration is not numeric"})
            continue
        if abs(declared_value - planned) > 1:
            severity = "P0" if str(session.get("planning_mode") or session_plans.get("planning_mode") or "draft") == "release" else "P1"
            findings.append({"severity": severity, "code": "PRACTICE_DURATION_MISMATCH", "session_id": session.get("id"), "declared_minutes": declared_value, "planned_task_minutes": planned, "tolerance_minutes": 1})
    return findings


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
    sessions = [item for item in session_plans.get("sessions", []) if isinstance(item, dict)]
    practice_sessions = [item for item in practice_plans.get("sessions", []) if isinstance(item, dict)]
    session_plans = {**session_plans, "sessions": sessions}
    practice_plans = {**practice_plans, "sessions": practice_sessions}
    graph = graph if isinstance(graph, dict) else {}
    inventory = inventory if isinstance(inventory, dict) else {}
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
    theory_knowledge_errors = _theory_knowledge_errors(session_plans, graph)
    duration_errors = _duration_findings(session_plans, practice_plans)
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
    normalized_pairs = [
        {"left_session": practice_sessions[left].get("id"), "right_session": practice_sessions[right].get("id"), "similarity": practice_metrics["normalized_similarity_matrix"][left][right]}
        for left in range(len(practice_sessions))
        for right in range(left + 1, len(practice_sessions))
        if practice_metrics["normalized_similarity_matrix"][left][right] >= practice_metrics["normalized_similarity_threshold"]
    ]
    normalized_large_clusters = [
        cluster for cluster in practice_metrics["normalized_similarity_clusters"]
        if len(cluster) >= 2 and (len(cluster) >= 3 or len(practice_sessions) <= 2)
    ]
    if normalized_large_clusters or (len(practice_sessions) <= 2 and normalized_pairs):
        findings.append({
            "severity": "P1",
            "code": "WHOLE_COURSE_PRACTICE_SIMILARITY_COLLAPSE",
            "clusters": normalized_large_clusters,
            "high_similarity_pairs": normalized_pairs,
            "threshold": practice_metrics["normalized_similarity_threshold"],
        })
    if knowledge_errors:
        findings.append({"severity": "P0", "code": "KNOWLEDGE_BOUNDARY_ERROR", "errors": knowledge_errors})
    if theory_knowledge_errors:
        findings.append({"severity": "P0", "code": "THEORY_KNOWLEDGE_BOUNDARY_ERROR", "errors": theory_knowledge_errors})
    findings.extend(duration_errors)
    visual_errors: list[str] = []
    for visual in (visual_plans or {}).get("visual_plans", []):
        visual_errors.extend(validate_visual(visual))
    if visual_errors:
        findings.append({"severity": "P0", "code": "SEMANTIC_VISUAL_DEGRADED", "errors": visual_errors})
    if research and str(research.get("research_status") or "") in {"completed", "COMPLETED"} and research.get("research_gaps") and not research.get("selected_source_count") and not research.get("search_performed", True):
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
        "theory_knowledge_boundary_errors": theory_knowledge_errors,
        "duration_errors": duration_errors,
        "practice_normalized_similarity_pairs": normalized_pairs,
        "practice_normalized_similarity_clusters": normalized_large_clusters,
        "research_state": (research or {}).get("research_status", "MISSING") if isinstance(research, dict) else "MISSING",
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
    integrity_findings = _input_integrity_findings(session_plans, practice_plans, graph, inventory, visual_plans)
    safe_session_plans = session_plans if isinstance(session_plans, dict) else {"sessions": []}
    safe_practice_plans = practice_plans if isinstance(practice_plans, dict) else {"sessions": []}
    safe_graph = graph if isinstance(graph, dict) else {"sessions": [], "nodes": []}
    safe_inventory = inventory if isinstance(inventory, dict) else {"assets": []}
    metrics, findings = _plan_findings(safe_session_plans, safe_practice_plans, safe_graph, safe_inventory, visual_plans if isinstance(visual_plans, dict) else None, research, render_evidence=render_evidence, rendered_course=rendered_course)
    if research is None:
        gaps = detect_gaps(safe_graph, safe_inventory, safe_graph.get("asset_knowledge_links") if isinstance(safe_graph.get("asset_knowledge_links"), dict) else None)
        if gaps:
            integrity_findings.append(_integrity_finding("RESEARCH_STATE_MISSING", "research is required when source/teaching gaps are present", severity="P1", gap_types=sorted({str(item.get("type")) for item in gaps})))
    elif not isinstance(research, dict) or str(research.get("research_status") or "") not in {"USER_SOURCE_SUFFICIENT", "COMPLETED", "completed", "EXTERNAL_RESEARCH_DISABLED_BY_USER", "EXTERNAL_RESEARCH_UNAVAILABLE"}:
        integrity_findings.append(_integrity_finding("RESEARCH_STATE_MISSING", "research status is absent or unsupported", severity="P1"))
    findings = integrity_findings + findings
    has_integrity_block = any(item.get("code") in {"INPUT_INTEGRITY_ERROR", "CROSS_ARTIFACT_COVERAGE_ERROR"} for item in findings)
    blocking = has_integrity_block or any(item.get("severity") in {"P0", "P1"} for item in findings)
    return {
        "schema_version": "1.1",
        "report_type": "whole_course_plan_qa",
        "status": "BLOCKED" if has_integrity_block else "FAIL" if blocking else "PASS",
        "plan_status": "BLOCKED" if has_integrity_block else "FAIL" if blocking else "PASS",
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


def _phrase_units(value: Any) -> set[str]:
    text = re.sub(r"\s+", "", text_of(value)).lower()
    units: set[str] = set(re.findall(r"[a-z][a-z0-9_]{2,}|\d+[a-z]+", text))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) >= 2:
            units.add(run)
            units.update(run[index : index + 2] for index in range(len(run) - 1))
            if len(run) >= 3:
                units.update(run[index : index + 3] for index in range(len(run) - 2))
    return {item for item in units if item not in {"学生", "教师", "页面", "本页", "内容", "说明", "当前", "一个", "可以", "进行", "以及", "然后", "需要"}}


def _rendered_blocks(rendered_course: dict[str, Any] | None, block_type: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in _pages(_as_render_pages(rendered_course)):
        for block in page.get("blocks", []) if isinstance(page.get("blocks"), list) else []:
            if isinstance(block, dict) and block.get("type") == block_type:
                result.append({"page": page, "block": block})
        direct = page.get(block_type)
        if isinstance(direct, dict):
            result.append({"page": page, "block": {"type": block_type, **direct}})
    return result


def _quiz_quality(rendered_course: dict[str, Any] | None) -> dict[str, Any]:
    records = _rendered_blocks(rendered_course, "quiz")
    if not records:
        return {"status": "NOT_APPLICABLE", "quiz_count": 0, "errors": [], "items": []}
    errors: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    distractors: list[tuple[str, str]] = []
    trivial_markers = ("忽略", "随便", "猜测", "天气", "颜色", "banana", "xyz", "无关", "都一样", "全部相同", "不相关")
    for record in records:
        page = record["page"]
        block = record["block"]
        page_id = page.get("id")
        options = block.get("options", [])
        options = [item.get("text", "") if isinstance(item, dict) else str(item) for item in options] if isinstance(options, list) else []
        question = str(block.get("question") or block.get("stem") or "").strip()
        correct_index = block.get("correct_index", block.get("answer_index"))
        correct_option = str(block.get("correct_option") or "").strip()
        if not question:
            errors.append({"page_id": page_id, "code": "QUIZ_MISSING_STEM"})
        if not options or not isinstance(correct_index, int) or not 0 <= correct_index < len(options):
            if correct_option and correct_option in options:
                correct_index = options.index(correct_option)
            else:
                errors.append({"page_id": page_id, "code": "QUIZ_CORRECT_OPTION_UNCLEAR"})
        if len(options) < 3:
            errors.append({"page_id": page_id, "code": "QUIZ_INSUFFICIENT_OPTIONS", "option_count": len(options)})
        context_units = _phrase_units({"title": page.get("title"), "question": question, "script": page.get("speaker_script")})
        metadata_by_text = {}
        for metadata in block.get("distractor_metadata", []) if isinstance(block.get("distractor_metadata"), list) else []:
            if isinstance(metadata, dict) and metadata.get("text") is not None:
                metadata_by_text[str(metadata.get("text")).strip().lower()] = metadata
        page_distractors: list[str] = []
        if isinstance(correct_index, int) and 0 <= correct_index < len(options):
            correct_option = options[correct_index]
            answer_text = str(block.get("answer_text") or "")
            explanation = str(block.get("explanation") or "").strip()
            if not answer_text or correct_option not in answer_text:
                errors.append({"page_id": page_id, "code": "QUIZ_CORRECT_OPTION_NOT_RENDERED"})
            if not explanation:
                errors.append({"page_id": page_id, "code": "QUIZ_EXPLANATION_MISSING"})
            elif correct_option and correct_option not in answer_text and not (_phrase_units(explanation) & _phrase_units(correct_option)):
                errors.append({"page_id": page_id, "code": "QUIZ_EXPLANATION_INCONSISTENT"})
            for index, option in enumerate(options):
                if index == correct_index:
                    continue
                normalized = option.strip().lower()
                page_distractors.append(option)
                distractors.append((str(page_id), normalized))
                if not normalized or any(marker in normalized for marker in trivial_markers):
                    errors.append({"page_id": page_id, "code": "QUIZ_TRIVIAL_DISTRACTOR", "text": option})
                metadata = metadata_by_text.get(normalized, {})
                misconception_type = str(metadata.get("misconception_type") or "").lower()
                metadata_plausible = misconception_type not in {"", "trivial", "unrelated", "random"} and bool(metadata.get("rationale") or metadata.get("source") or metadata.get("misconception"))
                if context_units and not (_phrase_units(option) & context_units) and not metadata_plausible:
                    errors.append({"page_id": page_id, "code": "QUIZ_IMPLAUSIBLE_DISTRACTOR", "text": option})
            for left, right in combinations(page_distractors, 2):
                if _normalised_overlap(left, right) >= 0.8 or left.strip().lower() == right.strip().lower():
                    errors.append({"page_id": page_id, "code": "QUIZ_SEMANTICALLY_DUPLICATE_OPTIONS", "left": left, "right": right})
        items.append({"page_id": page_id, "question": question, "options": options, "correct_index": correct_index, "correct_option": correct_option, "distractor_count": len(page_distractors), "answer_text": block.get("answer_text", ""), "explanation": block.get("explanation", "")})
    counts = Counter(value for _page_id, value in distractors)
    repeated = [{"text": text, "count": count, "page_ids": [page_id for page_id, value in distractors if value == text]} for text, count in counts.items() if count > 1]
    if repeated:
        errors.append({"code": "QUIZ_CROSS_PAGE_DISTRACTOR_REUSE", "items": repeated})
    return {"status": "PASS" if not errors else "FAIL", "quiz_count": len(records), "errors": errors, "items": items, "repeated_distractors": repeated}


def _comparison_quality(rendered_course: dict[str, Any] | None, session_plans: dict[str, Any]) -> dict[str, Any]:
    records = _rendered_blocks(rendered_course, "comparison")
    if not records:
        return {"status": "NOT_APPLICABLE", "comparison_count": 0, "errors": [], "items": []}
    plan_pages = {str(page.get("id")): page for page in _pages(session_plans)}
    errors: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for record in records:
        page = record["page"]
        block = record["block"]
        page_id = str(page.get("id"))
        dimension = str(block.get("contrast_dimension") or block.get("dimension") or "").strip()
        left_title = str(block.get("left_title") or "").strip()
        right_title = str(block.get("right_title") or "").strip()
        left_values = block.get("left", []) if isinstance(block.get("left"), list) else [block.get("left", "")]
        right_values = block.get("right", []) if isinstance(block.get("right"), list) else [block.get("right", "")]
        left_text = text_of(left_values)
        right_text = text_of(right_values)
        if not dimension:
            errors.append({"page_id": page_id, "code": "COMPARISON_RENDER_MISSING_DIMENSION"})
        if not left_title or not right_title or not left_text.strip() or not right_text.strip():
            errors.append({"page_id": page_id, "code": "COMPARISON_RENDER_INCOMPLETE_SIDES"})
        if left_text and right_text and (_normalised_overlap(left_text, right_text) >= 0.8 or left_text.strip().lower() == right_text.strip().lower()):
            errors.append({"page_id": page_id, "code": "COMPARISON_RENDER_SIDES_DUPLICATE"})
        correct = str(block.get("correct_side") or "")
        wrong = str(block.get("wrong_side") or "")
        if correct and wrong and correct == wrong:
            errors.append({"page_id": page_id, "code": "COMPARISON_RENDER_SIDE_CONFLICT"})
        planned = plan_pages.get(page_id, {})
        planned_evidence = planned.get("content_evidence") if isinstance(planned.get("content_evidence"), dict) else {}
        planned_comparison = planned.get("comparison") or planned_evidence.get("comparison") or {}
        planned_dimension = str(planned.get("contrast_dimension") or planned_comparison.get("contrast_dimension") or planned_comparison.get("dimension") or "").strip() if isinstance(planned_comparison, dict) else str(planned.get("contrast_dimension") or "").strip()
        if planned_dimension and planned_dimension not in dimension and not (_phrase_units(planned_dimension) & _phrase_units(dimension)):
            errors.append({"page_id": page_id, "code": "COMPARISON_RENDER_INTENT_MISMATCH", "planned_dimension": planned_dimension, "rendered_dimension": dimension})
        for field, rendered_value, planned_key in (("left_title", left_title, "left_title"), ("right_title", right_title, "right_title")):
            expected = planned_comparison.get(planned_key) if isinstance(planned_comparison, dict) else None
            if expected and str(expected) != rendered_value:
                errors.append({"page_id": page_id, "code": "COMPARISON_RENDER_SIDE_SEMANTICS_MISMATCH", "side": field, "planned": expected, "rendered": rendered_value})
        items.append({"page_id": page_id, "contrast_dimension": dimension, "left_title": left_title, "right_title": right_title, "left": left_values, "right": right_values, "correct_side": correct, "wrong_side": wrong})
    return {"status": "PASS" if not errors else "FAIL", "comparison_count": len(records), "errors": errors, "items": items}


def _grounding_evidence(page: dict[str, Any], plan_page: dict[str, Any] | None, graph: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    script = _script(page)
    plan = plan_page or {}
    question_terms = sorted(_phrase_units({"question": plan.get("teaching_question"), "title": plan.get("title") or page.get("title"), "outcome": plan.get("learning_outcome")}))
    knowledge_ids = [str(item) for item in plan.get("knowledge_node_ids", [])]
    nodes = {str(item.get("id")): item for item in graph.get("nodes", []) if isinstance(item, dict) and item.get("id")}
    knowledge_terms = sorted(_phrase_units([nodes[item].get("title") for item in knowledge_ids if item in nodes]))
    asset_ids = [str(item) for item in plan.get("source_asset_ids", [])]
    assets = {str(item.get("id")): item for item in inventory.get("assets", []) if isinstance(item, dict) and item.get("id")}
    asset_terms = sorted(_phrase_units([assets[item].get("title") or assets[item].get("content_summary") for item in asset_ids if item in assets]))
    roles = [str(item) for item in plan.get("required_semantic_elements", plan.get("planned_semantic_elements", []))]
    role_aliases = {"class": ("class", "类"), "relationship": ("relationship", "关系"), "multiplicity": ("multiplicity", "多重性", "基数"), "node": ("node", "节点"), "edge": ("edge", "边"), "table": ("table", "表"), "field": ("field", "字段"), "device": ("device", "设备"), "link": ("link", "链路"), "formula": ("formula", "公式"), "dependency": ("dependency", "依赖")}
    visual_terms = sorted({alias for role in roles for alias in role_aliases.get(role, (role,)) if len(alias) >= 2})
    example_value = plan.get("content_evidence", {}).get("worked_example") or plan.get("content_evidence", {}).get("case")
    example_terms = sorted(_phrase_units(example_value)) if example_value else []
    script_units = _phrase_units(script)
    matched_question = sorted(set(question_terms) & script_units)
    matched_knowledge = sorted(set(knowledge_terms) & script_units)
    matched_assets = sorted({asset_id for asset_id in asset_ids if asset_id.lower() in script.lower()} | {term for term in asset_terms if term in script_units})
    matched_roles = sorted(term for term in visual_terms if term in script_units or term in re.sub(r"\s+", "", script).lower())
    matched_examples = sorted(set(example_terms) & script_units)
    denominator = max(1, len(question_terms) + len(knowledge_terms) + len(asset_terms) + len(visual_terms) + len(example_terms))
    weighted = 2 * len(matched_question) + 2 * len(matched_knowledge) + 2 * len(matched_assets) + len(matched_roles) + len(matched_examples)
    score = round(min(1.0, weighted / denominator), 4)
    status = "PASS" if script and (matched_question or matched_knowledge or matched_assets or matched_roles or matched_examples) and score >= 0.08 else "FAIL" if script else "NOT_OBSERVED"
    return {"matched_question_terms": matched_question, "matched_knowledge_nodes": matched_knowledge, "matched_assets": matched_assets, "matched_visual_roles": matched_roles, "matched_example_entities": matched_examples, "score": score, "status": status, "anchor_terms": {"question": question_terms, "knowledge": knowledge_terms, "assets": asset_terms, "visual_roles": visual_terms, "examples": example_terms}}


def _rendered_course_coverage(rendered_course: dict[str, Any] | None, session_plans: dict[str, Any]) -> dict[str, Any]:
    planned_sessions = {str(item.get("id")): item for item in session_plans.get("sessions", []) if isinstance(item, dict) and item.get("id")}
    rendered_sessions = {str(item.get("id")): item for item in _as_render_pages(rendered_course).get("sessions", []) if isinstance(item, dict) and item.get("id")}
    missing_sessions = sorted(set(planned_sessions) - set(rendered_sessions))
    orphan_sessions = sorted(set(rendered_sessions) - set(planned_sessions))
    missing_pages: list[str] = []
    orphan_pages: list[str] = []
    for session_id, planned in planned_sessions.items():
        rendered = rendered_sessions.get(session_id, {})
        planned_ids = {str(item.get("id")) for item in planned.get("pages", []) if isinstance(item, dict) and item.get("id")}
        rendered_ids = {str(item.get("id")) for item in rendered.get("pages", []) if isinstance(item, dict) and item.get("id")}
        missing_pages.extend(f"{session_id}/{page_id}" for page_id in sorted(planned_ids - rendered_ids))
        orphan_pages.extend(f"{session_id}/{page_id}" for page_id in sorted(rendered_ids - planned_ids))
    errors = []
    if missing_sessions or orphan_sessions or missing_pages or orphan_pages:
        errors.append({"code": "CROSS_ARTIFACT_COVERAGE_ERROR", "missing_sessions": missing_sessions, "orphan_sessions": orphan_sessions, "missing_pages": missing_pages, "orphan_pages": orphan_pages})
    return {"status": "PASS" if not errors else "FAIL", "planned_session_ids": sorted(planned_sessions), "rendered_session_ids": sorted(rendered_sessions), "missing_sessions": missing_sessions, "orphan_sessions": orphan_sessions, "missing_pages": missing_pages, "orphan_pages": orphan_pages, "errors": errors}


def _rendered_practice_evidence(rendered_practice: dict[str, Any] | None, practice_plans: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(rendered_practice, dict):
        return {"status": "MISSING", "sessions": [], "errors": [{"code": "RENDERED_PRACTICE_EVIDENCE_MISSING"}]}
    raw_sessions = rendered_practice.get("sessions")
    if not isinstance(raw_sessions, list):
        return {"status": "FAIL", "sessions": [], "errors": [{"code": "INPUT_INTEGRITY_ERROR", "message": "rendered_practice.sessions must be a list"}]}
    planned_by_id = {str(item.get("id")): item for item in practice_plans.get("sessions", []) if isinstance(item, dict) and item.get("id")}
    rendered_by_id: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    session_records: list[dict[str, Any]] = []
    for raw in raw_sessions:
        if not isinstance(raw, dict) or not raw.get("id"):
            errors.append({"code": "INPUT_INTEGRITY_ERROR", "message": "rendered practice session is missing id"})
            continue
        session_id = str(raw["id"])
        if session_id in rendered_by_id:
            errors.append({"code": "INPUT_INTEGRITY_ERROR", "message": f"duplicate rendered practice session: {session_id}"})
        rendered_by_id[session_id] = raw
    missing_sessions = sorted(set(planned_by_id) - set(rendered_by_id))
    orphan_sessions = sorted(set(rendered_by_id) - set(planned_by_id))
    for session_id in missing_sessions:
        errors.append({"code": "CROSS_ARTIFACT_COVERAGE_ERROR", "session_id": session_id, "message": "planned practice session has no rendered output"})
    for session_id in orphan_sessions:
        errors.append({"code": "CROSS_ARTIFACT_COVERAGE_ERROR", "session_id": session_id, "message": "rendered practice session is not in the plan"})
    for session_id, planned in planned_by_id.items():
        rendered = rendered_by_id.get(session_id)
        if rendered is None:
            continue
        planned_tasks = [task for task in planned.get("tasks", []) if isinstance(task, dict)]
        planned_ids = [str(task.get("id")) for task in planned_tasks if task.get("id")]
        raw_task_evidence = rendered.get("task_evidence", [])
        task_evidence = [item for item in raw_task_evidence if isinstance(item, dict)] if isinstance(raw_task_evidence, list) else []
        observed_ids = [str(item.get("task_id")) for item in task_evidence if item.get("task_id")]
        if not observed_ids and isinstance(rendered.get("rendered_task_ids"), list):
            observed_ids = [str(item) for item in rendered.get("rendered_task_ids", [])]
        if len(observed_ids) != len(set(observed_ids)):
            errors.append({"code": "INPUT_INTEGRITY_ERROR", "session_id": session_id, "message": "duplicate rendered task IDs"})
        missing_tasks = sorted(set(planned_ids) - set(observed_ids))
        orphan_tasks = sorted(set(observed_ids) - set(planned_ids))
        if missing_tasks or orphan_tasks:
            errors.append({"code": "CROSS_ARTIFACT_COVERAGE_ERROR", "session_id": session_id, "missing_tasks": missing_tasks, "orphan_tasks": orphan_tasks})
        by_task_id = {str(item.get("task_id")): item for item in task_evidence if item.get("task_id")}
        task_records: list[dict[str, Any]] = []
        for task in planned_tasks:
            task_id = str(task.get("id"))
            evidence = by_task_id.get(task_id)
            task_errors: list[str] = []
            if evidence is None:
                task_errors.append("rendered_task_evidence_missing")
            else:
                if str(evidence.get("status")) != "PASS":
                    task_errors.append("task_evidence_not_pass")
                required = evidence.get("required", [])
                missing = evidence.get("missing", [])
                if required and missing:
                    task_errors.append("required_task_evidence_missing")
                observed = set(str(item) for item in evidence.get("observed", [])) if isinstance(evidence.get("observed"), list) else set()
                if not any(item.startswith("starter:") for item in observed) and not evidence.get("starter_observed"):
                    task_errors.append("starter_missing")
                if evidence.get("student_artifact_present") is False or ("student_artifact_present" not in evidence and evidence and "student_artifact" not in observed):
                    task_errors.append("student_artifact_missing")
                if evidence.get("teacher_reference_artifact_present") is False:
                    task_errors.append("teacher_reference_artifact_missing")
                if task.get("artifact_type") and "editable_artifact" not in observed:
                    task_errors.append("editable_artifact_missing")
                if not evidence.get("student_manifest_present", True):
                    task_errors.append("student_manifest_missing_or_leaking_teacher_answers")
                if evidence.get("teacher_reference_present") is False:
                    task_errors.append("teacher_reference_missing")
            task_records.append({"task_id": task_id, "required": task.get("level", "core") == "core", "status": "PASS" if not task_errors else "FAIL", "errors": task_errors, "evidence": evidence})
            if task_errors and task.get("level", "core") == "core":
                errors.append({"code": "PRACTICE_TASK_EVIDENCE_INCOMPLETE", "session_id": session_id, "task_id": task_id, "errors": task_errors})
        planned_minutes = sum(float(task.get("estimated_minutes", 0) or 0) for task in planned_tasks)
        rendered_minutes = rendered.get("duration_minutes")
        if rendered_minutes not in (None, ""):
            try:
                if abs(float(rendered_minutes) - planned_minutes) > 1:
                    errors.append({"code": "PRACTICE_DURATION_MISMATCH", "session_id": session_id, "planned_task_minutes": planned_minutes, "rendered_minutes": float(rendered_minutes), "tolerance_minutes": 1})
            except (TypeError, ValueError):
                errors.append({"code": "PRACTICE_DURATION_MISMATCH", "session_id": session_id, "rendered_minutes": rendered_minutes, "message": "rendered duration is not numeric"})
        if not Path(str(rendered.get("student_dir"))).is_dir() if rendered.get("student_dir") else True:
            errors.append({"code": "PRACTICE_STUDENT_OUTPUT_MISSING", "session_id": session_id})
        if not Path(str(rendered.get("teacher_dir"))).is_dir() if rendered.get("teacher_dir") else True:
            errors.append({"code": "PRACTICE_TEACHER_OUTPUT_MISSING", "session_id": session_id})
        session_records.append({"session_id": session_id, "planned_task_ids": planned_ids, "rendered_task_ids": observed_ids, "task_count_match": len(planned_ids) == len(observed_ids) and set(planned_ids) == set(observed_ids), "tasks": task_records, "planned_minutes": planned_minutes, "rendered_minutes": rendered_minutes})
    return {"status": "PASS" if not errors else "FAIL", "sessions": session_records, "missing_sessions": missing_sessions, "orphan_sessions": orphan_sessions, "errors": errors, "policy": "Whole-Course QA observes every planned practice session and task independently; renderer status is not a substitute for per-task evidence."}


def _render_metrics(rendered_course: dict[str, Any] | None, rendered_practice: dict[str, Any] | None, visual_evidence: dict[str, Any] | None, starter_evidence: dict[str, Any] | None, contact_sheet: dict[str, Any] | None, inventory: dict[str, Any], session_plans: dict[str, Any], practice_plans: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    course = _as_render_pages(rendered_course)
    scripts = _script_metrics(course, final_scripts=True)
    plan_pages = {str(page.get("id")): page for page in _pages(session_plans) if page.get("id")}
    grounding: list[dict[str, Any]] = []
    for page in _pages(course):
        grounding.append({"page_id": page.get("id"), **_grounding_evidence(page, plan_pages.get(str(page.get("id"))), graph, inventory)})
    grounded_pages = sum(1 for item in grounding if item.get("status") == "PASS")
    total_pages = len(grounding)
    quiz_quality = _quiz_quality(rendered_course)
    comparison_quality = _comparison_quality(rendered_course, session_plans)
    rendered_practice_quality = _rendered_practice_evidence(rendered_practice, practice_plans)
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
        "script_to_slide_grounding": {"status": "PASS" if total_pages and grounded_pages == total_pages else "FAIL" if total_pages else "NOT_OBSERVED", "script_grounding_ratio": round(grounded_pages / total_pages, 4) if total_pages else 0, "grounded_pages": grounded_pages, "total_pages": total_pages, "pages": grounding, "policy": "Page-specific phrase/anchor evidence is required; single-character Chinese overlap is excluded."},
        "starter_semantic_evidence": {"status": (starter_evidence or {}).get("status", "NOT_RUN"), "observed": (starter_evidence or {}).get("starter_observed", [])},
        "quiz_quality": quiz_quality,
        "comparison_quality": comparison_quality,
        "rendered_practice": rendered_practice_quality,
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
        None,
        research,
        render_evidence=visual_evidence,
        rendered_course=rendered_course,
    )
    metrics = dict(plan["metrics"])
    render_metrics = _render_metrics(rendered_course, rendered_practice, visual_evidence, starter_evidence, contact_sheet, inventory, session_plans if isinstance(session_plans, dict) else {"sessions": []}, practice_plans if isinstance(practice_plans, dict) else {"sessions": []}, graph if isinstance(graph, dict) else {})
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
    if render_metrics["quiz_quality"].get("status") == "FAIL":
        findings.append({"severity": "P0", "code": "RENDERED_QUIZ_QUALITY_FAILURE", "errors": render_metrics["quiz_quality"].get("errors", [])})
    if render_metrics["comparison_quality"].get("status") == "FAIL":
        findings.append({"severity": "P0", "code": "RENDERED_COMPARISON_QUALITY_FAILURE", "errors": render_metrics["comparison_quality"].get("errors", [])})
    rendered_coverage = _rendered_course_coverage(rendered_course, session_plans if isinstance(session_plans, dict) else {"sessions": []})
    metrics["render_evidence"]["rendered_course_coverage"] = rendered_coverage
    if rendered_coverage.get("status") == "FAIL":
        findings.extend({"severity": "P0", **item} for item in rendered_coverage.get("errors", []))
    if render_metrics["rendered_practice"].get("status") != "PASS":
        findings.append({"severity": "P0", "code": "RENDERED_PRACTICE_EVIDENCE_INCOMPLETE", "details": render_metrics["rendered_practice"]})
    if contact_sheet and contact_sheet.get("status") not in {"PASS", "DEGRADED"}:
        findings.append({"severity": "P1", "code": "CONTACT_SHEET_EVIDENCE_INCOMPLETE"})
    blocking = any(item.get("severity") in {"P0", "P1"} for item in findings)
    missing_required = [name for name, value in (("rendered_course", rendered_course), ("rendered_practice", rendered_practice), ("visual_evidence", visual_evidence), ("starter_evidence", starter_evidence), ("contact_sheet", contact_sheet)) if value is None]
    if missing_required:
        findings.append({"severity": "P0", "code": "REQUIRED_RENDER_EVIDENCE_MISSING", "missing": missing_required})
    required_evidence_present = not missing_required
    render_status = "PASS" if required_evidence_present and not blocking else "FAIL" if blocking or not required_evidence_present else "NOT_RUN"
    return {
        "schema_version": "1.1",
        "report_type": "whole_course_render_qa",
        "status": "FAIL" if blocking or not required_evidence_present else "PASS" if render_status == "PASS" else "NOT_EVALUATED",
        "plan_status": plan["plan_status"],
        "render_status": render_status,
        "final_status": "FAIL" if blocking or not required_evidence_present else "PASS" if render_status == "PASS" else "NOT_EVALUATED",
        "architecture_status": "WHOLE_COURSE_ARCHITECTURE_BLOCKED" if blocking or not required_evidence_present else "READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW",
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

    theory_sessions = []
    for raw_session in snapshot.get("theory_sessions", []):
        session = dict(raw_session) if isinstance(raw_session, dict) else raw_session
        if isinstance(session, dict):
            pages = []
            for raw_page in session.get("pages", []):
                page = dict(raw_page) if isinstance(raw_page, dict) else raw_page
                if isinstance(page, dict) and not page.get("teaching_question_id"):
                    # The frozen benchmark predates the page-level question
                    # field.  Normalize that immutable evidence into the
                    # current review shape without changing its failure facts.
                    page["teaching_question_id"] = f"legacy-{page.get('id') or 'page'}"
                pages.append(page)
            session["pages"] = pages
        theory_sessions.append(session)
    theory = {"sessions": theory_sessions}
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
