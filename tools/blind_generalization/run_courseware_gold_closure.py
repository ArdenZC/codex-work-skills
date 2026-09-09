"""Run the Courseware-only G3.2 Gold closure pipeline.

The runner consumes three fresh Agent-authored Courseware contracts.  It never
authors or regenerates Practice content; frozen Practice contracts are used
only for compatibility regression after the Courseware gates have run.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


TOOLS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_ROOT.parents[1]
COURSEWARE_SCRIPTS = REPO_ROOT / "HTML课件生成器" / "courseware-html-generator" / "scripts"
PRACTICE_SCRIPTS = REPO_ROOT / "实践课HTML生成器" / "practice-class-html-generator" / "scripts"
# Courseware owns shared module names such as ``teaching_blueprint``.  Keep it
# first so the runner cannot accidentally import the Practice-only validator;
# practice_contract explicitly imports Courseware's content contract itself.
if str(PRACTICE_SCRIPTS) not in sys.path:
    sys.path.append(str(PRACTICE_SCRIPTS))
if str(COURSEWARE_SCRIPTS) in sys.path:
    sys.path.remove(str(COURSEWARE_SCRIPTS))
sys.path.insert(0, str(COURSEWARE_SCRIPTS))

from content_contract import load_content, validate_content  # noqa: E402
from pedagogical_review import review_content  # noqa: E402
from planning_integrity import gold_batch_review  # noqa: E402
from practice_contract import validate_content as validate_practice_content  # noqa: E402
from run_blind_holdout import _git_provenance, _run, _sha256, _verify_source_freeze, _write_json  # noqa: E402


HOLDOUTS = ("python-web", "spreadsheet", "networking")
COURSEWARE_DECISION_KEYS = {
    "course_blueprint",
    "learning_units",
    "courseware_structure_reasoning_summary",
    "session_delivery_mode",
    "gold_script_target_summary",
    "visual_explanation_plan",
    "theory_practice_boundary_summary",
}
FORBIDDEN_PRIVATE_MARKERS = ("chain_of_thought", "private_reasoning", "hidden_reasoning")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite output path: {target}")
    shutil.copytree(source, target)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _agent_decision_report(path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        value = _load_json(path)
    except Exception as exc:  # noqa: BLE001 - preserve agent boundary evidence
        return {"status": "FAIL", "errors": [f"generation decision is not valid JSON: {exc}"]}
    if not isinstance(value, dict):
        return {"status": "FAIL", "errors": ["generation decision must be a JSON object"]}
    required_keys = {"course_blueprint", "learning_units", "courseware_structure_reasoning_summary"}
    missing = sorted(required_keys - set(value))
    if missing:
        errors.append("generation decision is missing Courseware planning keys: " + ", ".join(missing))
    private_keys = sorted(key for key in value if any(marker in str(key).casefold() for marker in FORBIDDEN_PRIVATE_MARKERS))
    if private_keys:
        errors.append("generation decision contains private reasoning fields: " + ", ".join(private_keys))
    blueprint = value.get("course_blueprint")
    blueprint_errors: list[str] = []
    if not isinstance(blueprint, dict):
        blueprint_errors.append("course_blueprint must be an object")
    learning_units = value.get("learning_units")
    if not isinstance(learning_units, list) or not learning_units:
        errors.append("learning_units must be a non-empty list")
    elif any(not isinstance(unit, (str, dict)) for unit in learning_units):
        errors.append("learning_units entries must be strings or objects")
    summary = value.get("courseware_structure_reasoning_summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append("courseware_structure_reasoning_summary must be a non-empty string")
    errors.extend("course_blueprint: " + error for error in blueprint_errors)
    if "practice_blueprint" in value or any("practice" in str(key).casefold() for key in value if key not in COURSEWARE_DECISION_KEYS):
        errors.append("Courseware-only generation decision must not contain a Practice blueprint or task plan")
    blueprint_report = {"status": "PASS" if not blueprint_errors else "FAIL", "errors": blueprint_errors}
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "blueprint": blueprint_report}


def _contract_report(path: Path) -> dict[str, Any]:
    try:
        raw = _load_json(path)
        report = validate_content(raw, base_dir=path.parent)
        report["session_delivery_mode"] = raw.get("session_delivery_mode", "theory-led") if isinstance(raw, dict) else None
        return report
    except Exception as exc:  # noqa: BLE001 - machine-readable gate evidence
        return {"status": "fail", "errors": [str(exc)], "warnings": [], "metrics": {}}


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _fact_locations(fact: dict[str, Any]) -> set[str]:
    locations: set[str] = set()
    for evidence in fact.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        locator = evidence.get("locator")
        if isinstance(locator, dict):
            for key in ("line", "line_start", "line_end"):
                if locator.get(key) is not None:
                    locations.add(str(locator[key]))
        elif locator is not None:
            locations.add(str(locator))
    return locations


def _fact_quotes(fact: dict[str, Any]) -> list[str]:
    return [
        _normalized_text(evidence.get("quote"))
        for evidence in fact.get("evidence", [])
        if isinstance(evidence, dict) and evidence.get("quote")
    ]


def _fact_match_score(old_fact: dict[str, Any], new_fact: dict[str, Any]) -> float:
    if old_fact.get("id") == new_fact.get("id"):
        return 10.0
    old_statement = _normalized_text(old_fact.get("statement"))
    new_statement = _normalized_text(new_fact.get("statement"))
    statement_score = difflib.SequenceMatcher(None, old_statement, new_statement).ratio()
    old_quotes = _fact_quotes(old_fact)
    new_quotes = _fact_quotes(new_fact)
    quote_score = max(
        (difflib.SequenceMatcher(None, old_quote, new_quote).ratio() for old_quote in old_quotes for new_quote in new_quotes),
        default=0.0,
    )
    location_match = bool(_fact_locations(old_fact) & _fact_locations(new_fact))
    old_numbers = set(re.findall(r"\d+(?:\.\d+)?", old_statement + " ".join(old_quotes)))
    new_numbers = set(re.findall(r"\d+(?:\.\d+)?", new_statement + " ".join(new_quotes)))
    number_score = len(old_numbers & new_numbers) / max(len(old_numbers), 1)
    old_chars = set(old_statement)
    new_chars = set(new_statement)
    character_score = len(old_chars & new_chars) / max(len(old_chars | new_chars), 1)
    return (
        0.72 * statement_score
        + 0.18 * quote_score
        + 0.28 * float(location_match)
        + 0.18 * number_score
        + 0.10 * character_score
    )


def _best_id_map(
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    *,
    score_fn: Any,
    label: str,
) -> tuple[dict[str, list[str]], list[str], dict[str, list[dict[str, Any]]]]:
    new_by_id = {str(item.get("id")): item for item in new_items if isinstance(item, dict) and item.get("id")}
    mapping: dict[str, list[str]] = {}
    errors: list[str] = []
    evidence: dict[str, list[dict[str, Any]]] = {}
    for old_item in old_items:
        old_id = str(old_item.get("id", ""))
        if not old_id:
            continue
        if old_id in new_by_id:
            mapping[old_id] = [old_id]
            evidence[old_id] = [{"new_id": old_id, "score": 10.0, "method": "stable-id"}]
            continue
        candidates = sorted(
            ((float(score_fn(old_item, new_item)), str(new_item.get("id"))) for new_item in new_items if new_item.get("id")),
            reverse=True,
        )
        if not candidates:
            errors.append(f"{label} has no candidate for frozen id: {old_id}")
            continue
        top_score, top_id = candidates[0]
        next_score = candidates[1][0] if len(candidates) > 1 else 0.0
        evidence[old_id] = [
            {"new_id": candidate_id, "score": round(score, 4)}
            for score, candidate_id in candidates[:3]
        ]
        if top_score < 0.24:
            errors.append(f"{label} mapping is too weak for {old_id}: top={top_id} score={top_score:.3f}")
            continue
        if top_score < 0.36 and top_score - next_score < 0.08:
            errors.append(
                f"{label} mapping is ambiguous for {old_id}: "
                f"{top_id}={top_score:.3f}, {candidates[1][1]}={next_score:.3f}"
            )
            continue
        mapping[old_id] = [top_id]
    return mapping, errors, evidence


def _unit_match_score(old_unit: dict[str, Any], new_unit: dict[str, Any]) -> float:
    old_title = _normalized_text(old_unit.get("title"))
    new_title = _normalized_text(new_unit.get("title"))
    title_score = difflib.SequenceMatcher(None, old_title, new_title).ratio()
    old_know = _normalized_text(" ".join(str(item) for item in old_unit.get("students_should_know", [])))
    new_know = _normalized_text(" ".join(str(item) for item in new_unit.get("students_should_know", [])))
    knowledge_score = difflib.SequenceMatcher(None, old_know, new_know).ratio()
    old_not_yet = {_normalized_text(item) for item in old_unit.get("not_yet_taught", [])}
    new_not_yet = {_normalized_text(item) for item in new_unit.get("not_yet_taught", [])}
    not_yet_score = len(old_not_yet & new_not_yet) / max(len(old_not_yet), 1)
    return 0.55 * title_score + 0.30 * knowledge_score + 0.15 * not_yet_score


def _slide_match_score(old_slide: dict[str, Any], new_slide: dict[str, Any]) -> float:
    old_title = _normalized_text(old_slide.get("title"))
    new_title = _normalized_text(new_slide.get("title"))
    old_kicker = _normalized_text(old_slide.get("kicker"))
    new_kicker = _normalized_text(new_slide.get("kicker"))
    return 0.75 * difflib.SequenceMatcher(None, old_title, new_title).ratio() + 0.25 * difflib.SequenceMatcher(None, old_kicker, new_kicker).ratio()


def _map_practice_ids(
    practice: dict[str, Any],
    old_courseware: dict[str, Any],
    new_courseware: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    old_facts = [item for item in old_courseware.get("canonical_facts", []) if isinstance(item, dict)]
    new_facts = [item for item in new_courseware.get("canonical_facts", []) if isinstance(item, dict)]
    old_slide_titles = {
        str(slide.get("id")): _normalized_text(slide.get("title"))
        for slide in old_courseware.get("slides", [])
        if isinstance(slide, dict) and slide.get("id")
    }
    new_slide_titles = {
        str(slide.get("id")): _normalized_text(slide.get("title"))
        for slide in new_courseware.get("slides", [])
        if isinstance(slide, dict) and slide.get("id")
    }

    def fact_score(old_fact: dict[str, Any], new_fact: dict[str, Any]) -> float:
        score = _fact_match_score(old_fact, new_fact)
        old_topics = [old_slide_titles[slide_id] for slide_id in old_fact.get("source_slide_ids", []) if str(slide_id) in old_slide_titles]
        new_topics = [new_slide_titles[slide_id] for slide_id in new_fact.get("source_slide_ids", []) if str(slide_id) in new_slide_titles]
        topic_score = max(
            (difflib.SequenceMatcher(None, old_topic, new_topic).ratio() for old_topic in old_topics for new_topic in new_topics),
            default=0.0,
        )
        return score + 0.45 * topic_score

    fact_map, fact_errors, fact_evidence = _best_id_map(old_facts, new_facts, score_fn=fact_score, label="canonical fact")

    new_units_by_fact: dict[str, set[str]] = {}
    for unit in new_courseware.get("learning_units", []):
        if not isinstance(unit, dict) or not unit.get("id"):
            continue
        for fact_id in unit.get("canonical_fact_ids", []):
            new_units_by_fact.setdefault(str(fact_id), set()).add(str(unit["id"]))
    old_units = [item for item in old_courseware.get("learning_units", []) if isinstance(item, dict)]
    new_units = [item for item in new_courseware.get("learning_units", []) if isinstance(item, dict)]
    unit_map: dict[str, list[str]] = {}
    unit_errors: list[str] = []
    unit_evidence: dict[str, list[dict[str, Any]]] = {}
    for old_unit in old_units:
        old_id = str(old_unit.get("id", ""))
        related_new_facts = {
            new_fact_id
            for old_fact_id in old_unit.get("canonical_fact_ids", [])
            for new_fact_id in fact_map.get(str(old_fact_id), [])
        }
        related_new_units = sorted({unit_id for fact_id in related_new_facts for unit_id in new_units_by_fact.get(fact_id, set())})
        if related_new_units:
            unit_map[old_id] = related_new_units
            unit_evidence[old_id] = [{"new_id": unit_id, "method": "mapped-canonical-facts"} for unit_id in related_new_units]
            continue
        candidates = sorted(
            ((_unit_match_score(old_unit, new_unit), str(new_unit.get("id"))) for new_unit in new_units if new_unit.get("id")),
            reverse=True,
        )
        if not candidates or candidates[0][0] < 0.24:
            unit_errors.append(f"learning unit has no reliable mapping for frozen id: {old_id}")
            continue
        unit_map[old_id] = [candidates[0][1]]
        unit_evidence[old_id] = [{"new_id": candidate_id, "score": round(score, 4)} for score, candidate_id in candidates[:3]]

    old_facts_by_slide: dict[str, set[str]] = {}
    for fact in old_facts:
        for slide_id in fact.get("source_slide_ids", []):
            old_facts_by_slide.setdefault(str(slide_id), set()).add(str(fact.get("id")))
    new_fact_by_id = {str(fact.get("id")): fact for fact in new_facts if fact.get("id")}
    old_slides = [item for item in old_courseware.get("slides", []) if isinstance(item, dict)]
    new_slides = [item for item in new_courseware.get("slides", []) if isinstance(item, dict)]
    new_slides_by_unit: dict[str, set[str]] = {}
    new_units_by_slide: dict[str, set[str]] = {}
    for new_slide in new_slides:
        new_slide_id = str(new_slide.get("id"))
        new_units_by_slide[new_slide_id] = {str(unit_id) for unit_id in new_slide.get("learning_unit_ids", []) if isinstance(unit_id, str)}
        for unit_id in new_slide.get("learning_unit_ids", []):
            new_slides_by_unit.setdefault(str(unit_id), set()).add(new_slide_id)
    slide_map: dict[str, list[str]] = {}
    slide_errors: list[str] = []
    slide_evidence: dict[str, list[dict[str, Any]]] = {}
    for old_slide in old_slides:
        old_id = str(old_slide.get("id", ""))
        candidate_scores: dict[str, float] = {}
        for old_fact_id in old_facts_by_slide.get(old_id, set()):
            for new_fact_id in fact_map.get(old_fact_id, []):
                for new_slide_id in new_fact_by_id.get(new_fact_id, {}).get("source_slide_ids", []):
                    candidate_scores[str(new_slide_id)] = candidate_scores.get(str(new_slide_id), 0.0) + 1.0
        for old_unit_id in old_slide.get("learning_unit_ids", []):
            for new_unit_id in unit_map.get(str(old_unit_id), []):
                for new_slide_id in new_slides_by_unit.get(new_unit_id, set()):
                    candidate_scores[new_slide_id] = candidate_scores.get(new_slide_id, 0.0) + 0.45
        candidates = sorted(
            (
                score + 0.18 * _slide_match_score(old_slide, new_slide),
                str(new_slide.get("id")),
            )
            for new_slide in new_slides
            for score in [candidate_scores.get(str(new_slide.get("id")), 0.0)]
            if new_slide.get("id")
        )
        candidates.sort(reverse=True)
        if not candidate_scores:
            candidates = sorted(
                ((_slide_match_score(old_slide, new_slide), str(new_slide.get("id"))) for new_slide in new_slides if new_slide.get("id")),
                reverse=True,
            )
        if not candidates or candidates[0][0] < 0.24:
            slide_errors.append(f"slide has no reliable mapping for frozen id: {old_id}")
            continue
        slide_map[old_id] = [candidates[0][1]]
        slide_evidence[old_id] = [
            {"new_id": candidate_id, "score": round(score, 4), "method": "mapped-semantic-evidence" if candidate_scores else "title-similarity"}
            for score, candidate_id in candidates[:3]
        ]

    transformed = copy.deepcopy(practice)
    replacement_errors: list[str] = []

    def replace_list(value: Any, mapping: dict[str, list[str]], label: str) -> Any:
        if not isinstance(value, list):
            return value
        replaced: list[Any] = []
        for item in value:
            if not isinstance(item, str) or item not in mapping:
                if isinstance(item, str) and item:
                    replacement_errors.append(f"{label} has no ID mapping: {item}")
                replaced.append(item)
                continue
            for mapped in mapping[item]:
                if mapped not in replaced:
                    replaced.append(mapped)
        return replaced

    def walk(value: Any, location: str = "practice") -> None:
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key == "source_slide_ids":
                    value[key] = replace_list(item, slide_map, f"{location}.{key}")
                elif key == "taught_slide_ids":
                    value[key] = replace_list(item, slide_map, f"{location}.{key}")
                elif key == "learning_unit_ids":
                    value[key] = replace_list(item, unit_map, f"{location}.{key}")
                elif key == "canonical_fact_ids":
                    value[key] = replace_list(item, fact_map, f"{location}.{key}")
                else:
                    walk(item, f"{location}.{key}")
            mapped_slides = value.get("source_slide_ids")
            if isinstance(mapped_slides, list):
                mapped_slide_ids = {str(slide_id) for slide_id in mapped_slides if isinstance(slide_id, str)}
                expected_facts = {
                    fact_id
                    for fact_id, fact in new_fact_by_id.items()
                    if mapped_slide_ids & {str(slide_id) for slide_id in fact.get("source_slide_ids", [])}
                }
                if isinstance(value.get("canonical_fact_ids"), list):
                    value["canonical_fact_ids"] = list(dict.fromkeys([*value["canonical_fact_ids"], *sorted(expected_facts)]))
                expected_units = {
                    unit_id
                    for slide_id in mapped_slide_ids
                    for unit_id in new_units_by_slide.get(slide_id, set())
                }
                if isinstance(value.get("learning_unit_ids"), list):
                    value["learning_unit_ids"] = list(dict.fromkeys([*value["learning_unit_ids"], *sorted(expected_units)]))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{location}[{index}]")

    walk(transformed)

    task_by_id = {
        str(task.get("id")): task
        for task in transformed.get("tasks", [])
        if isinstance(task, dict) and task.get("id")
    }

    def propagate_task_links(value: Any) -> None:
        if isinstance(value, dict):
            task_ids = value.get("task_ids")
            if isinstance(task_ids, list):
                linked_tasks = [task_by_id.get(str(task_id), {}) for task_id in task_ids]
                if isinstance(value.get("learning_unit_ids"), list):
                    linked_units = [
                        unit_id
                        for task in linked_tasks
                        for unit_id in task.get("learning_unit_ids", [])
                        if isinstance(unit_id, str)
                    ]
                    value["learning_unit_ids"] = list(dict.fromkeys([*value["learning_unit_ids"], *linked_units]))
                if isinstance(value.get("canonical_fact_ids"), list):
                    linked_facts = [
                        fact_id
                        for task in linked_tasks
                        for fact_id in task.get("canonical_fact_ids", [])
                        if isinstance(fact_id, str)
                    ]
                    value["canonical_fact_ids"] = list(dict.fromkeys([*value["canonical_fact_ids"], *linked_facts]))
            for item in value.values():
                propagate_task_links(item)
        elif isinstance(value, list):
            for item in value:
                propagate_task_links(item)

    propagate_task_links(transformed)
    if isinstance(transformed.get("course_context"), dict) and isinstance(new_courseware.get("course_context"), dict):
        transformed["course_context"] = copy.deepcopy(new_courseware["course_context"])
    report = {
        "fact_mapping": fact_evidence,
        "learning_unit_mapping": unit_evidence,
        "slide_mapping": slide_evidence,
        "mapping_errors": fact_errors + unit_errors + slide_errors + replacement_errors,
        "changed": {
            "canonical_facts": sorted(old_id for old_id, mapped in fact_map.items() if mapped != [old_id]),
            "learning_units": sorted(old_id for old_id, mapped in unit_map.items() if mapped != [old_id]),
            "slides": sorted(old_id for old_id, mapped in slide_map.items() if mapped != [old_id]),
        },
    }
    return transformed, report


def _context_compatibility(old_context: Any, new_context: Any) -> dict[str, Any]:
    errors: list[str] = []
    changes: list[dict[str, Any]] = []
    if not isinstance(old_context, dict) or not isinstance(new_context, dict):
        return {"status": "FAIL", "errors": ["both frozen and Gold Courseware course_context must be objects"], "changes": []}
    old_text = _normalized_text(json.dumps(old_context, ensure_ascii=False))
    new_text = _normalized_text(json.dumps(new_context, ensure_ascii=False))
    for field in ("course_name", "audience"):
        if old_context.get(field) != new_context.get(field):
            errors.append(f"course_context.{field} changed incompatibly")
            changes.append({"field": field, "old": old_context.get(field), "new": new_context.get(field), "status": "FAIL"})
    for field in ("language", "software", "framework", "platform"):
        old_value = old_context.get(field)
        if old_value is None:
            continue
        old_norm = _normalized_text(old_value)
        if old_norm and old_norm not in new_text:
            if field == "language" and old_norm in {"中文", "chinese"} and re.search(r"[\u3400-\u9fff]", new_text):
                changes.append({"field": field, "old": old_value, "new": new_context.get(field), "status": "EXPLAINED_SEMANTIC_CHANGE"})
            else:
                errors.append(f"course_context.{field} is not preserved semantically")
                changes.append({"field": field, "old": old_value, "new": new_context.get(field), "status": "FAIL"})
        elif old_context.get(field) != new_context.get(field):
            changes.append({"field": field, "old": old_value, "new": new_context.get(field), "status": "EXPLAINED_SEMANTIC_CHANGE"})
    old_tools = old_context.get("tools", [])
    if isinstance(old_tools, list):
        for tool in old_tools:
            if _normalized_text(tool) not in new_text:
                errors.append(f"course_context.tools lost: {tool}")
        if old_tools != new_context.get("tools"):
            changes.append({"field": "tools", "old": old_tools, "new": new_context.get("tools"), "status": "EXPLAINED_SEMANTIC_CHANGE"})
    old_constraints = old_context.get("other_constraints", [])
    if isinstance(old_constraints, list):
        for constraint in old_constraints:
            if _normalized_text(constraint) not in new_text:
                new_values = [
                    str(value)
                    for value in new_context.values()
                    if isinstance(value, str)
                ]
                new_values.extend(
                    str(item)
                    for value in new_context.values()
                    if isinstance(value, list)
                    for item in value
                )
                similarity = max(
                    (difflib.SequenceMatcher(None, _normalized_text(constraint), _normalized_text(value)).ratio() for value in new_values),
                    default=0.0,
                )
                normalized_constraint = _normalized_text(constraint)
                practice_lab_preserved = "实践课" in normalized_constraint and "实践" in new_text and "机房" in new_text
                if similarity < 0.35 and not practice_lab_preserved:
                    errors.append("course_context.other_constraints lost a frozen constraint")
        if old_constraints != new_context.get("other_constraints"):
            changes.append({"field": "other_constraints", "old": old_constraints, "new": new_context.get("other_constraints"), "status": "EXPLAINED_SEMANTIC_CHANGE"})
    old_delivery = _normalized_text(old_context.get("delivery_environment"))
    if old_delivery and old_delivery not in new_text:
        delivery_tokens = [token for token in ("computer-lab", "机房", "windows", "classroom", "topology", "excel") if token in old_delivery]
        if old_delivery == "computer-lab":
            delivery_tokens.append("机房")
        if not any(token in new_text for token in delivery_tokens):
            errors.append("course_context.delivery_environment is not preserved semantically")
        else:
            changes.append({"field": "delivery_environment", "old": old_context.get("delivery_environment"), "new": new_context.get("delivery_environment"), "status": "EXPLAINED_SEMANTIC_CHANGE"})
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "changes": changes}


def _practice_compatibility(
    practice_path: Path,
    courseware: dict[str, Any],
    frozen_courseware_path: Path,
) -> dict[str, Any]:
    try:
        practice = _load_json(practice_path)
        frozen_courseware = _load_json(frozen_courseware_path)
        projected_practice, mapping = _map_practice_ids(practice, frozen_courseware, courseware)
        context = _context_compatibility(frozen_courseware.get("course_context"), courseware.get("course_context"))
        report = validate_practice_content(projected_practice, courseware, enforce_task_semantics=False)
        errors = list(mapping.get("mapping_errors", [])) + list(context.get("errors", [])) + list(report.get("errors", []))
        return {
            "status": "PASS" if report.get("status") == "pass" and not errors else "FAIL",
            "practice_contract": str(practice_path),
            "frozen_courseware_reference": str(frozen_courseware_path),
            "validation_mode": "frozen-practice-semantic-id-remap",
            "errors": errors,
            "warnings": report.get("warnings", []),
            "metrics": report.get("metrics", {}),
            "context": context,
            "id_changes": mapping.get("changed", {}),
            "id_mapping_evidence": mapping,
            "stable_slide_ids": sorted({slide.get("id") for slide in courseware.get("slides", []) if isinstance(slide, dict)}),
        }
    except Exception as exc:  # noqa: BLE001 - preserve compatibility failure
        return {"status": "FAIL", "practice_contract": str(practice_path), "errors": [str(exc)], "warnings": []}


def _courseware_gold_report(
    *,
    output: Path,
    gold: dict[str, Any],
    reports: dict[str, dict[str, Any]],
    compatibility: dict[str, dict[str, Any]],
    final_status: str,
) -> str:
    profiles = gold.get("profiles", [])
    profile_by_holdout = {
        holdout: profiles[index] if index < len(profiles) else {}
        for index, holdout in enumerate(HOLDOUTS)
    }
    thresholds = gold.get("thresholds", {})
    normal_target = thresholds.get("normal_target_chars_per_lecture_minute", [120, 160])
    hard_floor = thresholds.get("hard_floor_chars_per_lecture_minute", 80)
    lines = [
        "# Courseware Gold Closure Report",
        "",
        f"Status: `{final_status}`",
        "",
        "## A. 为什么 G3 Courseware 仍 DEGRADED",
        "",
        "G3 第四轮已能通过结构、来源和渲染类自动门，但 Courseware 的教师逐字稿在多门课上仍集中在有效下限附近，部分页面的解释密度不足；这使教师仍需大量现场补讲。Gold Closure 将硬下限与正常生成目标分开，并把图、代码、表格、公式解释和理论/实践边界纳入同一批量门。",
        "",
        "## B. Theory-led model 如何工作",
        "",
        "每个 Courseware 合同显式声明 `session_delivery_mode=theory-led`，活动按教师演示、全班引导推理、学生短检查、学生独立练习分类。存在独立 Practice 资产时，理论课可以保留真实的短互动，但独立工具操作不能成为主要时长来源；检查使用角色分钟结构，不使用固定比例机械判定。",
        "",
        "## C. Script normal target 如何成为 generation target",
        "",
        f"生成阶段以每个讲授分钟 {normal_target[0]}–{normal_target[1]} 个去空白字符作为正常目标，以 {hard_floor} 个去空白字符作为 fail-closed 硬下限。目标用于规划和 Agent 自检，不通过复制段落或无意义选择题填充；每页仍需先形成讲解意图、例子、易错点、提问与过渡，再生成教师可直接朗读的逐字稿。",
        "",
        "## D. 三门 Courseware speaker script",
        "",
        "| holdout | core pages | min chars/min | median chars/min | max chars/min | below-normal ratio | near-floor ratio |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for holdout in HOLDOUTS:
        profile = profile_by_holdout[holdout]
        lines.append(
            f"| {holdout} | {profile.get('core_slide_count', 0)} | {profile.get('min_chars_per_lecture_minute', 'n/a')} | {profile.get('median_chars_per_lecture_minute', 'n/a')} | {profile.get('max_chars_per_lecture_minute', 'n/a')} | {profile.get('below_normal_ratio', 'n/a')} | {profile.get('near_floor_ratio', 'n/a')} |"
        )
    lines.extend([
        "",
        f"Gold batch status: `{gold.get('status', 'FAIL')}`. Repetition and visual coverage are evaluated per Courseware contract; code/table/SVG/formula pages require script coverage excerpts or explicit visual explanation markers.",
        "",
        "## E. Theory/practice boundary 时间结构",
        "",
        "| holdout | teacher-led demonstration | guided whole-class reasoning | short student check | student independent practice | boundary status |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for holdout in HOLDOUTS:
        boundary = reports.get(holdout, {}).get("pedagogical", {}).get("metrics", {}).get("theory_practice_boundary", {})
        role_minutes = boundary.get("role_minutes", {})
        lines.append(
            f"| {holdout} | {role_minutes.get('teacher-led-demonstration', 0)} | {role_minutes.get('guided-whole-class-reasoning', 0)} | {role_minutes.get('short-student-check', 0)} | {role_minutes.get('student-independent-practice', 0)} | {boundary.get('status', 'FAIL')} |"
        )
    lines.extend([
        "",
        "## F. Practice compatibility",
        "",
        "Practice 未重新生成；只使用冻结的 Fourth-pass Practice Contract 做回归。兼容性核对覆盖 `learning_unit_ids`、`canonical_fact_ids`、source-slide relationships、`not_yet_taught` 与 `course_context`。",
        "",
        "| holdout | frozen Practice compatibility |",
        "|---|---|",
    ])
    for holdout in HOLDOUTS:
        lines.append(f"| {holdout} | {compatibility.get(holdout, {}).get('status', 'FAIL')} |")
    lines.extend([
        "",
        "Courseware-only Agent 可以为理论课扩写而重排页面；runner 对冻结 Practice 做内存中的 ID 语义映射，再用新 Courseware 验证所有链接，原 Practice JSON 不被写回。变化逐项记录在 `practice-compatibility/*/compatibility.json` 的 `id_changes` 与 `id_mapping_evidence` 中。",
        "",
        "| holdout | changed slide IDs | changed learning-unit IDs | changed canonical-fact IDs | context status |",
        "|---|---:|---:|---:|---|",
    ])
    for holdout in HOLDOUTS:
        item = compatibility.get(holdout, {})
        changes = item.get("id_changes", {})
        context = item.get("context", {})
        lines.append(
            f"| {holdout} | {len(changes.get('slides', []))} | {len(changes.get('learning_units', []))} | {len(changes.get('canonical_facts', []))} | {context.get('status', 'FAIL')} |"
        )
    lines.extend([
        "",
        "## G. Manual evidence UI 修复",
        "",
        "教师页将证据状态作为枚举展示：`MANUAL_EVIDENCE_DEFINED` → 待课堂人工核对；`AUTOMATED_UNAVAILABLE` → 自动化不可用 · 已定义人工验收标准；`MANUAL_PASS` → 课堂人工核对通过；`FAIL` → 未通过；`PASS` → 通过。Practice G3 T1–T4 覆盖这些映射，未把未自动化状态折叠为失败或自动通过。",
        "",
        "## 质量对比：G3 Fourth-pass vs Gold Closure Pass",
        "",
        "| 维度 | G3 Fourth-pass | Gold Closure Pass |",
        "|---|---|---|",
        "| 可直接朗读 | 多门 Courseware 逐字稿低于正常目标，教师需要补讲 | 以正常目标驱动生成，并报告三门 min/median/max；最终仍保留人工教学验收边界 |",
        "| 真实解释 | 页面存在稀疏讲稿和解释不足风险 | 教学意图、例子、易错点、追问、过渡与脚本覆盖进入 Gold 检查 |",
        "| 图/代码/表格说明 | 不是统一的 Gold 批量门 | 有视觉解释覆盖门，缺失时失败 |",
        "| 理论/实践职责 | 需要额外辨析 Practice-like 时长 | 用 activity role 和 companion Practice 边界复核，不强制固定比例 |",
        "| Practice 稳定性 | Fourth-pass 冻结基线 | 未重生成，仅做 H1/H2/H3 兼容性回归 |",
        "",
        "本报告不替代教师对三门 Teacher Courseware 的最终课堂验收。",
        "",
    ])
    return "\n".join(lines)


def _zip_output(output: Path, zip_path: Path) -> dict[str, Any]:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        raise FileExistsError(f"refusing to overwrite existing ZIP: {zip_path}")
    files: list[dict[str, Any]] = []
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(output).as_posix()
            archive.write(path, relative)
            files.append({"relative_path": relative, "sha256": _sha256(path)})
    return {"path": str(zip_path), "sha256": _sha256(zip_path), "file_count": len(files), "files": files}


def _holdout_paths(root: Path, holdout: str) -> tuple[Path, Path]:
    agent_dir = root / holdout
    return agent_dir / "courseware-content.json", agent_dir / "generation-decision.json"


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    source_root = args.source_root.expanduser().resolve()
    source_freeze = args.source_freeze.expanduser().resolve() if args.source_freeze else None
    agent_root = args.agent_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    courseware_skill = args.courseware_skill.expanduser().resolve()
    practice_reference_root = args.practice_reference_root.expanduser().resolve()
    generator_repo = args.generator_repo.expanduser().resolve()
    errors: list[str] = []
    if output.exists():
        errors.append(f"refusing to overwrite existing Courseware Gold output: {output}")
    if not source_root.is_dir():
        errors.append(f"source root does not exist: {source_root}")
    if not agent_root.is_dir():
        errors.append(f"agent root does not exist: {agent_root}")
    if not courseware_skill.is_dir():
        errors.append(f"Courseware Skill does not exist: {courseware_skill}")
    if not practice_reference_root.is_dir():
        errors.append(f"frozen Practice reference root does not exist: {practice_reference_root}")

    freeze = {"status": "FAIL", "errors": ["source freeze was not checked"]}
    if source_root.is_dir():
        freeze_reports: dict[str, Any] = {}
        freeze_errors: list[str] = []
        for holdout in HOLDOUTS:
            source_pack = source_root / holdout
            if not source_pack.is_dir():
                message = f"frozen source pack missing for {holdout}: {source_pack}"
                freeze_errors.append(message)
                continue
            try:
                report = _verify_source_freeze(source_pack, source_freeze)
            except Exception as exc:  # noqa: BLE001
                report = {"status": "fail", "errors": [str(exc)]}
            freeze_reports[holdout] = report
            freeze_errors.extend(f"{holdout}: {item}" for item in report.get("errors", []))
        freeze = {
            "status": "pass" if not freeze_errors else "fail",
            "manifest": str(source_freeze) if source_freeze else None,
            "errors": freeze_errors,
            "holdouts": freeze_reports,
        }
        errors.extend(freeze_errors)
    git = _git_provenance(generator_repo, args.generator_commit)
    errors.extend(git.get("errors", []))

    inputs: dict[str, dict[str, Path]] = {}
    decisions: dict[str, dict[str, Any]] = {}
    for holdout in HOLDOUTS:
        courseware_path, decision_path = _holdout_paths(agent_root, holdout)
        source_pack = source_root / holdout
        inputs[holdout] = {"courseware": courseware_path, "decision": decision_path, "source": source_pack}
        for label, path in (("Courseware contract", courseware_path), ("generation decision", decision_path)):
            if not path.is_file():
                errors.append(f"{label} missing for {holdout}: {path}")
        if not source_pack.is_dir():
            errors.append(f"frozen source pack missing for {holdout}: {source_pack}")
        if decision_path.is_file():
            decision = _agent_decision_report(decision_path)
            decisions[holdout] = decision
            errors.extend(f"{holdout}: {item}" for item in decision.get("errors", []))

    if errors:
        return 2, {
            "status": "COURSEWARE_GOLD_CLOSURE_FAILED",
            "errors": errors,
            "source_freeze": freeze,
            "provenance": git,
            "generation_method": "agent-skill",
        }

    output.mkdir(parents=True, exist_ok=False)
    (output / "evaluation").mkdir()
    (output / "provenance").mkdir()
    (output / "generation-decision").mkdir()
    (output / "practice-compatibility").mkdir()
    for holdout in HOLDOUTS:
        _copy_tree(inputs[holdout]["source"], output / "raw-source" / holdout)
        shutil.copy2(inputs[holdout]["decision"], output / "generation-decision" / f"{holdout}.json")

    _write_json(output / "provenance" / "source-freeze.json", freeze)
    _write_json(output / "provenance" / "generator.json", git)
    _write_json(output / "provenance" / "generation-run.json", {
        "generation_method": "agent-skill",
        "agent_skill_generation": True,
        "builder_generation": False,
        "pass_name": "courseware-gold-closure",
        "generator_commit": git.get("head"),
        "dirty": git.get("dirty_worktree"),
        "courseware_skill_version": "1.2.1",
        "courseware_contract_version": "1.1",
        "practice_generation": "not-run",
        "source_freeze_sha256": _sha256(Path(freeze["manifest"])) if freeze.get("manifest") else None,
        "started_at": _now(),
    })

    stage_root = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    commands: dict[str, Any] = {}
    reports: dict[str, Any] = {}
    coursewares: list[dict[str, Any]] = []
    compatibility: dict[str, Any] = {}
    try:
        for holdout in HOLDOUTS:
            paths = inputs[holdout]
            content_path = paths["courseware"]
            source_pack = paths["source"]
            eval_dir = output / "evaluation" / holdout
            eval_dir.mkdir(parents=True, exist_ok=True)
            courseware_stage = stage_root / holdout / "courseware"
            holdout_commands: dict[str, Any] = {}

            holdout_commands["courseware_contract"] = _run(
                [sys.executable, str(COURSEWARE_SCRIPTS / "content_contract.py"), str(content_path)],
                COURSEWARE_SCRIPTS,
            )
            holdout_commands["source_truth"] = _run(
                [sys.executable, str(COURSEWARE_SCRIPTS / "source_truth_validator.py"), "--courseware-json", str(content_path), "--source-root", str(source_pack), "--mode", "strict", "--output-json", str(eval_dir / "source-truth.json")],
                COURSEWARE_SCRIPTS,
            )
            holdout_commands["time_evidence"] = _run(
                [sys.executable, str(COURSEWARE_SCRIPTS / "activity_time_reviewer.py"), "--content-json", str(content_path), "--mode", "strict", "--output-json", str(eval_dir / "time-evidence.json")],
                COURSEWARE_SCRIPTS,
            )
            ready_to_render = all(holdout_commands[key].get("status") == "pass" for key in ("courseware_contract", "source_truth", "time_evidence"))
            if ready_to_render:
                holdout_commands["courseware_render"] = _run(
                    [sys.executable, str(COURSEWARE_SCRIPTS / "render_courseware.py"), "--content-json", str(content_path), "--output-dir", str(courseware_stage), "--replace", "--source-root", str(source_pack), "--evidence-mode", "strict", "--separate-practice-available", "--json"],
                    COURSEWARE_SCRIPTS,
                )
            else:
                holdout_commands["courseware_render"] = {"status": "not-run", "reason": "Courseware Contract, Source Truth, or Time Evidence gate failed"}
            if holdout_commands["courseware_render"].get("status") == "pass":
                (output / holdout).mkdir(parents=True, exist_ok=True)
                _copy_tree(courseware_stage, output / holdout / "courseware")
                shutil.copy2(content_path, output / holdout / "courseware" / "courseware-content.json")
                shutil.copy2(content_path, output / holdout / "courseware" / "agent-contract.json")
                shutil.copy2(content_path, output / holdout / "courseware" / "contract.json")
                holdout_commands["courseware_validate"] = _run(
                    [sys.executable, str(COURSEWARE_SCRIPTS / "validate_courseware.py"), "--content-json", str(content_path), "--student-html", str(output / holdout / "courseware" / "student.html"), "--teacher-html", str(output / holdout / "courseware" / "teacher.html"), "--json"],
                    COURSEWARE_SCRIPTS,
                )
                if args.browser_smoke:
                    holdout_commands["browser_smoke"] = _run(
                        ["node", str(courseware_skill / "tests" / "browser_smoke.mjs"), str(output / holdout / "courseware" / "student.html")],
                        courseware_skill,
                    )
                else:
                    holdout_commands["browser_smoke"] = {"status": "not-run", "reason": "browser smoke was not requested"}
            else:
                holdout_commands["courseware_validate"] = {"status": "not-run", "reason": "Courseware render failed"}
                holdout_commands["browser_smoke"] = {"status": "not-run", "reason": "Courseware render failed"}

            raw_content = _load_json(content_path)
            contract_report = _contract_report(content_path)
            pedagogical = review_content(raw_content, time_mode="strict", separate_practice_available=True)
            _write_json(eval_dir / "contract.json", contract_report)
            _write_json(eval_dir / "pedagogical-review.json", pedagogical)
            reports[holdout] = {"contract": contract_report, "pedagogical": pedagogical}
            commands[holdout] = holdout_commands
            coursewares.append(raw_content)

            practice_path = practice_reference_root / holdout / "practice" / "practice-content.json"
            if not practice_path.is_file():
                practice_path = practice_reference_root / holdout / "practice" / "agent-contract.json"
            frozen_courseware_path = practice_reference_root / "generation-decision" / holdout / "courseware-content.json"
            compatibility_report = _practice_compatibility(practice_path, raw_content, frozen_courseware_path)
            compatibility[holdout] = compatibility_report
            compat_dir = output / "practice-compatibility" / holdout
            compat_dir.mkdir(parents=True, exist_ok=True)
            if practice_path.is_file():
                shutil.copy2(practice_path, compat_dir / "frozen-practice-contract.json")
            _write_json(compat_dir / "compatibility.json", compatibility_report)

        gold = gold_batch_review(coursewares)
        _write_json(output / "evaluation" / "gold-batch.json", gold)

        gates: dict[str, str] = {}
        for holdout in HOLDOUTS:
            courseware_report = reports[holdout]["contract"]
            pedagogical = reports[holdout]["pedagogical"]
            boundary = pedagogical.get("metrics", {}).get("theory_practice_boundary", {})
            script_planning = pedagogical.get("metrics", {}).get("speaker_script_planning", {})
            repetition = pedagogical.get("metrics", {}).get("speaker_script_repetition", {})
            holdout_commands = commands[holdout]
            per_holdout = {
                "courseware_contract": "PASS" if courseware_report.get("status") == "pass" else "FAIL",
                "source_truth": "PASS" if holdout_commands["source_truth"].get("status") == "pass" else "FAIL",
                "time_evidence": "PASS" if holdout_commands["time_evidence"].get("status") == "pass" else "FAIL",
                "theory_practice_boundary": "PASS" if boundary.get("status") != "FAIL" else "FAIL",
                "script_hard_floor": "PASS" if script_planning.get("status") != "FAIL" else "FAIL",
                "repetition": "PASS" if repetition.get("status") == "PASS" else "FAIL",
                "browser": "PASS" if holdout_commands["browser_smoke"].get("status") == "pass" else "FAIL",
                "overflow": "PASS" if holdout_commands["browser_smoke"].get("status") == "pass" else "FAIL",
                "courseware_validate": "PASS" if holdout_commands["courseware_validate"].get("status") == "pass" else "FAIL",
                "practice_compatibility": compatibility[holdout]["status"],
            }
            _write_json(output / "evaluation" / holdout / "gates.json", per_holdout)
        aggregate_names = ("courseware_contract", "source_truth", "time_evidence", "theory_practice_boundary", "script_hard_floor", "repetition", "browser", "overflow", "practice_compatibility")
        for name in aggregate_names:
            values = [_load_json(output / "evaluation" / holdout / "gates.json")[name] for holdout in HOLDOUTS]
            gates[name] = "PASS" if all(value == "PASS" for value in values) else "FAIL"
        gates["gold_batch"] = "PASS" if gold.get("status") == "PASS" else "FAIL"
        gates["courseware_validate"] = "PASS" if all(commands[h]["courseware_validate"].get("status") == "pass" for h in HOLDOUTS) else "FAIL"
        final_status = "READY_FOR_FINAL_COURSEWARE_GOLD_REVIEW" if all(value == "PASS" for value in gates.values()) else "COURSEWARE_GOLD_CLOSURE_FAILED"
        run_report = {
            "status": final_status,
            "generation_method": "agent-skill",
            "holdouts": list(HOLDOUTS),
            "source_freeze": freeze,
            "provenance": git,
            "skill_version": "1.2.1",
            "courseware_contract_version": "1.1",
            "practice_generation": "not-run",
            "gates": gates,
            "per_holdout": reports,
            "commands": commands,
            "practice_compatibility": compatibility,
            "gold_batch": gold,
        }
        _write_text(
            output / "evaluation" / "COURSEWARE-GOLD-CLOSURE-REPORT.md",
            _courseware_gold_report(
                output=output,
                gold=gold,
                reports=reports,
                compatibility=compatibility,
                final_status=final_status,
            ),
        )
        _write_json(output / "evaluation" / "run-report.json", run_report)
        _write_json(output / "provenance" / "generation-run.json", {
            "generation_method": "agent-skill",
            "agent_skill_generation": True,
            "builder_generation": False,
            "pass_name": "courseware-gold-closure",
            "generator_commit": git.get("head"),
            "dirty": git.get("dirty_worktree"),
            "courseware_skill_version": "1.2.1",
            "courseware_contract_version": "1.1",
            "practice_generation": "not-run",
            "source_freeze_sha256": _sha256(Path(freeze["manifest"])) if freeze.get("manifest") else None,
            "finished_at": _now(),
            "status": final_status,
        })
        return (0 if final_status == "READY_FOR_FINAL_COURSEWARE_GOLD_REVIEW" else 1), run_report
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--source-freeze", type=Path)
    parser.add_argument("--agent-root", required=True, type=Path)
    parser.add_argument("--practice-reference-root", required=True, type=Path)
    parser.add_argument("--courseware-skill", required=True, type=Path)
    parser.add_argument("--generator-repo", required=True, type=Path)
    parser.add_argument("--generator-commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--browser-smoke", action="store_true")
    args = parser.parse_args(argv)
    try:
        code, report = run(args)
        if code == 0 and args.zip_path:
            zip_report = _zip_output(args.output.expanduser().resolve(), args.zip_path.expanduser().resolve())
            report["zip"] = zip_report
            _write_json(args.output.expanduser().resolve() / "evaluation" / "zip-report.json", zip_report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return code
    except Exception as exc:  # noqa: BLE001 - preserve closure failure evidence
        report = {"status": "COURSEWARE_GOLD_CLOSURE_FAILED", "errors": [f"{type(exc).__name__}: {exc}"]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
