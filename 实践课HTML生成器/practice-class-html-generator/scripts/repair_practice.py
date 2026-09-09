"""Perform safe, deterministic Practice Contract repair rounds.

The repairer only completes relationships or semantic scaffolding that can be
derived from the Agent's own tasks and the supplied Courseware Contract.  It
does not invent a task, alter a student starter's answer, or add an interaction
just to satisfy a quantity target.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from practice_contract import load_courseware, normalize_content, validate_content


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _courseware_maps(courseware: dict[str, Any] | None) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    slide_units: dict[str, set[str]] = {}
    slide_facts: dict[str, set[str]] = {}
    if not isinstance(courseware, dict):
        return slide_units, slide_facts
    for slide in _list(courseware.get("slides")):
        if isinstance(slide, dict) and _non_empty(slide.get("id")):
            slide_units[str(slide["id"])] = {str(item) for item in _list(slide.get("learning_unit_ids")) if _non_empty(item)}
    for fact in _list(courseware.get("canonical_facts")):
        if not isinstance(fact, dict):
            continue
        fact_id = fact.get("id")
        if not _non_empty(fact_id):
            continue
        for slide_id in _list(fact.get("source_slide_ids")):
            if _non_empty(slide_id):
                slide_facts.setdefault(str(slide_id), set()).add(str(fact_id))
    return slide_units, slide_facts


def _semantic_ids(slide_refs: list[str], slide_units: dict[str, set[str]], slide_facts: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    units = sorted({unit for slide_id in slide_refs for unit in slide_units.get(slide_id, set())})
    facts = sorted({fact for slide_id in slide_refs for fact in slide_facts.get(slide_id, set())})
    return units, facts


def _task_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in _list(content.get("tasks")) if isinstance(item, dict) and _non_empty(item.get("id"))}


def _knowledge_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in _list(content.get("knowledge_links")) if isinstance(item, dict) and _non_empty(item.get("id"))}


def _source_refs(item: dict[str, Any], tasks: dict[str, dict[str, Any]], knowledge: dict[str, dict[str, Any]]) -> list[str]:
    refs = [str(value) for value in _list(item.get("source_slide_ids")) if _non_empty(value)]
    if refs:
        return sorted(set(refs))
    linked: set[str] = set()
    for task_id in _list(item.get("task_ids")):
        linked.update(str(value) for value in _list(tasks.get(str(task_id), {}).get("source_slide_ids")) if _non_empty(value))
    for knowledge_id in _list(item.get("knowledge_link_ids")):
        linked.update(str(value) for value in _list(knowledge.get(str(knowledge_id), {}).get("source_slide_ids")) if _non_empty(value))
    return sorted(linked)


def _fill_semantic_links(item: dict[str, Any], refs: list[str], slide_units: dict[str, set[str]], slide_facts: dict[str, set[str]], actions: list[dict[str, Any]], location: str, round_number: int) -> bool:
    units, facts = _semantic_ids(refs, slide_units, slide_facts)
    changed = False
    for field, derived in (("learning_unit_ids", units), ("canonical_fact_ids", facts)):
        current = item.get(field)
        if (not isinstance(current, list) or not current) and derived:
            item[field] = derived
            actions.append({"round": round_number, "field": f"{location}.{field}", "method": "Courseware slide/fact map", "value": derived})
            changed = True
    return changed


def _fill_task_semantics(
    task: dict[str, Any],
    assets: list[dict[str, Any]],
    support_items: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    location: str,
    round_number: int,
) -> bool:
    changed = False
    kind = task.get("task_kind")
    capabilities = set(task.get("capabilities", [])) if isinstance(task.get("capabilities"), list) else set()
    starter_ids = [str(asset.get("id")) for asset in assets if str(asset.get("task_id")) == str(task.get("id")) and _non_empty(asset.get("id"))]
    if (kind == "implementation" or "code_editing" in capabilities) and not task.get("starter_asset_ids") and starter_ids:
        task["starter_asset_ids"] = starter_ids
        actions.append({"round": round_number, "field": f"{location}.starter_asset_ids", "method": "starter_assets.task_id", "value": starter_ids})
        changed = True
    referenced_assets = [asset for asset in assets if str(asset.get("id")) in {str(item) for item in _list(task.get("starter_asset_ids"))}]
    if kind == "implementation" or "code_editing" in capabilities:
        if not task.get("edit_targets"):
            gaps = [str(gap.get("marker")) for asset in referenced_assets for gap in _list(asset.get("editable_gaps")) if isinstance(gap, dict) and _non_empty(gap.get("marker"))]
            if gaps:
                task["edit_targets"] = gaps
                actions.append({"round": round_number, "field": f"{location}.edit_targets", "method": "starter editable_gaps.marker", "value": gaps})
                changed = True
        if task.get("todo_count") is None:
            todo_count = sum(_text(asset.get("content")).count("TODO ") for asset in referenced_assets)
            gap_count = sum(len(_list(asset.get("editable_gaps"))) for asset in referenced_assets)
            derived = max(todo_count, gap_count)
            if derived:
                task["todo_count"] = derived
                actions.append({"round": round_number, "field": f"{location}.todo_count", "method": "starter TODO/editable gap count", "value": derived})
                changed = True
    task_id = str(task.get("id"))
    overview = _text(task.get("overview")) or _text(task.get("title"))
    if not _non_empty(task.get("scaffold")) and overview:
        task["scaffold"] = f"先从这一步开始：{overview}"
        actions.append({"round": round_number, "field": f"{location}.scaffold", "method": "task overview/title", "value": task["scaffold"]})
        changed = True
    steps = [str(step.get("instruction")) for step in _list(task.get("steps")) if isinstance(step, dict) and _non_empty(step.get("instruction"))]
    checks = [str(step.get("check")) for step in _list(task.get("steps")) if isinstance(step, dict) and _non_empty(step.get("check"))]
    acceptance = [str(value) for value in _list(task.get("acceptance")) if _non_empty(value)]
    if not acceptance and checks:
        task["acceptance"] = checks
        acceptance = checks
        actions.append({"round": round_number, "field": f"{location}.acceptance", "method": "step.check", "value": checks})
        changed = True
    elif not acceptance and overview:
        derived_acceptance = [f"完成后能够说明或核对：{overview}"]
        task["acceptance"] = derived_acceptance
        acceptance = derived_acceptance
        actions.append({"round": round_number, "field": f"{location}.acceptance", "method": "task overview/title", "value": derived_acceptance})
        changed = True
    if not isinstance(task.get("help_refs"), list):
        related = [
            str(item.get("id"))
            for item in support_items
            if task_id in {str(ref) for ref in _list(item.get("task_ids"))} and _non_empty(item.get("id"))
        ]
        task["help_refs"] = sorted(set(related))
        actions.append({"round": round_number, "field": f"{location}.help_refs", "method": "matching guide/kit task_ids", "value": task["help_refs"]})
        changed = True
    scaffold = _text(task.get("scaffold")) or overview
    if kind == "debugging" or "diagnosis" in capabilities:
        values = {
            "symptom": f"观察现象：{overview}",
            "faulty_artifact": ", ".join(str(asset.get("path")) for asset in referenced_assets) or "任务提供的可观察起点",
            "expected_behavior": acceptance[0] if acceptance else "结果应与已讲理论规则一致。",
            "diagnosis_target": "把可观察现象对应到一个可检查的理论或操作原因。",
            "repair_target": "修改造成该现象的关键位置，并用验收条件复核。",
        }
        for field, value in values.items():
            if not _non_empty(task.get(field)):
                task[field] = value
                actions.append({"round": round_number, "field": f"{location}.{field}", "method": "task overview/scaffold/acceptance", "value": value})
                changed = True
    if kind == "modeling" or "model_editing" in capabilities:
        values = {"editable_model": scaffold, "required_edit": overview, "modeling_constraints": acceptance or ["只修改本任务明确的对象、关系或属性。"]}
        for field, value in values.items():
            if not task.get(field):
                task[field] = value
                actions.append({"round": round_number, "field": f"{location}.{field}", "method": "task scaffold/overview/acceptance", "value": value})
                changed = True
    if kind == "tooling" or "tool_operation" in capabilities:
        values = {"tool": _text(task.get("modality")) or "课程声明的工具环境", "starting_state": scaffold, "operations": steps or ["按任务步骤完成一次可观察操作。"], "expected_observable_result": acceptance[0] if acceptance else "记录一个可复核的操作结果。"}
        for field, value in values.items():
            if not task.get(field):
                task[field] = value
                actions.append({"round": round_number, "field": f"{location}.{field}", "method": "task steps/scaffold/acceptance", "value": value})
                changed = True
    if kind == "experiment" or "experiment" in capabilities:
        values = {"variable": "任务要求观察的变量或条件", "control": "保持其他条件不变", "operation": steps or ["改变一个条件并执行观察。"], "observation": acceptance or ["记录改变条件前后的可见差异。"], "expected_reasoning": overview}
        for field, value in values.items():
            if not task.get(field):
                task[field] = value
                actions.append({"round": round_number, "field": f"{location}.{field}", "method": "task steps/acceptance", "value": value})
                changed = True
    return changed


def _repair_round(content: dict[str, Any], courseware: dict[str, Any] | None, actions: list[dict[str, Any]], round_number: int) -> bool:
    slide_units, slide_facts = _courseware_maps(courseware)
    tasks = _task_map(content)
    knowledge = _knowledge_map(content)
    assets = [asset for asset in _list(content.get("starter_assets")) if isinstance(asset, dict)]
    support_items = [
        item
        for collection in ("study_guide", "foundation_kit")
        for item in _list(content.get(collection))
        if isinstance(item, dict)
    ]
    changed = False
    for index, item in enumerate(_list(content.get("knowledge_links"))):
        if isinstance(item, dict):
            changed |= _fill_semantic_links(item, _source_refs(item, tasks, knowledge), slide_units, slide_facts, actions, f"knowledge_links[{index}]", round_number)
    for index, task in enumerate(_list(content.get("tasks"))):
        if not isinstance(task, dict):
            continue
        location = f"tasks[{index}]"
        refs = _source_refs(task, tasks, knowledge)
        if not task.get("source_slide_ids") and refs:
            task["source_slide_ids"] = refs
            actions.append({"round": round_number, "field": f"{location}.source_slide_ids", "method": "linked knowledge source slides", "value": refs})
            changed = True
        changed |= _fill_semantic_links(task, refs, slide_units, slide_facts, actions, location, round_number)
        changed |= _fill_task_semantics(task, assets, support_items, actions, location, round_number)
    for collection in ("learning_center", "study_guide", "foundation_kit"):
        for index, item in enumerate(_list(content.get(collection))):
            if isinstance(item, dict):
                changed |= _fill_semantic_links(item, _source_refs(item, tasks, knowledge), slide_units, slide_facts, actions, f"{collection}[{index}]", round_number)
    references = _list(content.get("teacher_reference", {}).get("task_references")) if isinstance(content.get("teacher_reference"), dict) else []
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            continue
        task = tasks.get(str(reference.get("task_id")), {})
        for field in ("source_slide_ids", "learning_unit_ids", "canonical_fact_ids"):
            if not reference.get(field) and task.get(field):
                reference[field] = copy.deepcopy(task[field])
                actions.append({"round": round_number, "field": f"teacher_reference.task_references[{index}].{field}", "method": "matching task semantic links", "value": reference[field]})
                changed = True
    return changed


def repair_content(content: Any, courseware: dict[str, Any] | None = None, *, max_rounds: int = 2) -> dict[str, Any]:
    normalized, migration = normalize_content(content, courseware)
    if not isinstance(normalized, dict):
        return {"status": "fail", "errors": ["practice content root must be an object"], "warnings": [], "actions": [], "rounds": 0, "migration": migration, "content": normalized}
    repaired = copy.deepcopy(normalized)
    actions: list[dict[str, Any]] = []
    report = validate_content(repaired, courseware)
    rounds_used = 0
    round_limit = min(max(0, max_rounds), 2)
    for round_number in range(1, round_limit + 1):
        if report["status"] == "pass":
            break
        rounds_used = round_number
        if not _repair_round(repaired, courseware, actions, round_number):
            break
        report = validate_content(repaired, courseware)
    return {
        "status": "pass" if report["status"] == "pass" else "fail",
        "errors": report.get("errors", []),
        "warnings": report.get("warnings", []),
        "actions": actions,
        "rounds": rounds_used,
        "round_limit": round_limit,
        "migration": migration,
        "content": repaired,
        "validation": report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-json", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--courseware-json", type=Path)
    parser.add_argument("--max-rounds", type=int, default=2)
    args = parser.parse_args(argv)
    source = args.practice_json.expanduser().resolve()
    target = args.output_json.expanduser().resolve()
    try:
        if source == target:
            raise ValueError("repair output must not overwrite the Agent input contract")
        raw = json.loads(source.read_text(encoding="utf-8"))
        courseware = load_courseware(args.courseware_json.expanduser().resolve()) if args.courseware_json else None
        result = repair_content(raw, courseware, max_rounds=args.max_rounds)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result["content"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        public = {key: value for key, value in result.items() if key not in {"content"}}
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "pass" else 1
    except Exception as exc:  # noqa: BLE001 - CLI keeps repair evidence machine-readable
        print(json.dumps({"status": "fail", "errors": [str(exc)], "actions": [], "rounds": 0}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
