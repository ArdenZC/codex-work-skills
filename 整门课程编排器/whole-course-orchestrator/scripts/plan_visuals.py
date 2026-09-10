"""Plan semantic visuals without manufacturing rendered evidence."""

from __future__ import annotations

import argparse
from typing import Any

from orchestrator_core import OrchestrationError, dump_json, load_json, text_of
from semantic_artifacts import registry_summary, structure_defaults


# ``capabilities`` describes what an artifact adapter can observe. It is not
# a claim that every visual of that type must contain every capability.
# Compatibility-shaped view for older callers and reports.  The source of
# truth is the domain-neutral registry in semantic_artifacts.py.
SEMANTIC_ADAPTERS: dict[str, dict[str, Any]] = registry_summary()


KEYWORD_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "multiplicity": ("multiplicity",),
    "多重性": ("multiplicity",),
    "基数": ("multiplicity",),
    "attribute": ("attribute", "class_compartment"),
    "属性": ("attribute", "class_compartment"),
    "operation": ("operation", "class_compartment"),
    "方法": ("operation", "class_compartment"),
    "inheritance": ("inheritance",),
    "继承": ("inheritance",),
    "aggregation": ("aggregation",),
    "聚合": ("aggregation",),
    "composition": ("composition",),
    "组合": ("composition",),
    "actor": ("actor",),
    "参与者": ("actor",),
    "lifeline": ("lifeline",),
    "生命线": ("lifeline",),
    "message": ("message",),
    "消息": ("message",),
    "transition": ("transition",),
    "状态转移": ("transition",),
    "guard": ("guard",),
    "条件": ("guard",),
    "decision": ("decision",),
    "判断": ("decision",),
    "node": ("node",),
    "节点": ("node",),
    "edge": ("edge",),
    "边": ("edge",),
    "root": ("root",),
    "根节点": ("root",),
    "parent": ("parent_child",),
    "父子": ("parent_child",),
    "traversal": ("traversal",),
    "遍历": ("traversal",),
    "table": ("table",),
    "表": ("table",),
    "field": ("field",),
    "字段": ("field",),
    "key": ("key",),
    "主键": ("key",),
    "row": ("row",),
    "行": ("row",),
    "column": ("column",),
    "列": ("column",),
    "device": ("device",),
    "设备": ("device",),
    "link": ("link",),
    "链路": ("link",),
    "direction": ("direction",),
    "方向": ("direction",),
    "path": ("path",),
    "路径": ("path",),
    "cell": ("cell",),
    "单元格": ("cell",),
    "range": ("range",),
    "区域": ("range",),
    "formula": ("formula",),
    "公式": ("formula",),
    "dependency": ("dependency",),
    "依赖": ("dependency",),
    "input": ("input",),
    "输入": ("input",),
    "output": ("output",),
    "输出": ("output",),
}


def adapter_for(artifact_type: str | None) -> dict[str, Any] | None:
    return SEMANTIC_ADAPTERS.get(str(artifact_type or ""))


def _relevant_requirements(page: dict[str, Any], artifact_type: str, adapter: dict[str, Any]) -> list[str]:
    explicit = page.get("required_semantic_elements")
    capabilities = set(adapter.get("capabilities", []))
    if isinstance(explicit, list) and explicit:
        values = [str(item) for item in explicit if str(item) in capabilities]
        if values:
            return list(dict.fromkeys(values))
    haystack = text_of({
        "teaching_question": page.get("teaching_question") or page.get("question"),
        "learning_outcome": page.get("learning_outcome"),
        "visual_intent": page.get("visual_intent"),
        "title": page.get("title"),
    }).lower()
    result: list[str] = []
    for keyword, values in KEYWORD_REQUIREMENTS.items():
        if keyword.lower() in haystack:
            result.extend(value for value in values if value in capabilities)
    if page.get("visual_intent") == "relationship":
        result.extend(value for value in ("association", "relationship", "multiplicity") if value in capabilities)
    if page.get("visual_intent") in {"sequence", "interaction"}:
        result.extend(value for value in ("lifeline", "message") if value in capabilities)
    if page.get("visual_intent") in {"state_transition", "process"}:
        result.extend(value for value in ("state", "transition") if value in capabilities)
    if not result:
        result.extend(adapter.get("default_requirements", [])[:3])
    return list(dict.fromkeys(result))


def _planned_elements(page: dict[str, Any], required: list[str], adapter: dict[str, Any] | None) -> list[str]:
    supplied = page.get("planned_semantic_elements", page.get("semantic_elements", []))
    if isinstance(supplied, list) and supplied:
        values = [str(item) for item in supplied]
    else:
        # Planning may propose the selected requirements. This is explicitly
        # kept in PLANNED; it is never copied into OBSERVED.
        values = list(required)
    capabilities = set((adapter or {}).get("capabilities", []))
    return list(dict.fromkeys(item for item in values if not capabilities or item in capabilities))


def plan_visual(page: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    artifact_type = page.get("artifact_type")
    asset_ids = [str(item) for item in page.get("source_asset_ids", [])]
    referenced_assets = [assets[item] for item in asset_ids if item in assets]
    is_visual = bool(artifact_type or page.get("visual_intent") or asset_ids or page.get("primary_job") == "visualize")
    if not is_visual:
        return None
    adapter = adapter_for(str(artifact_type)) if artifact_type else None
    required_elements = _relevant_requirements(page, str(artifact_type), adapter) if artifact_type and adapter else []
    planned_elements = _planned_elements(page, required_elements, adapter)
    selected_source_assets = [asset["id"] for asset in referenced_assets if asset.get("teaching_value") in {"core", "supporting"}]
    source_image = next((asset.get("image_ref") for asset in referenced_assets if asset.get("image_ref")), None)
    strategy = str(page.get("render_strategy") or "")
    if not strategy:
        strategy = "reuse" if source_image and page.get("reuse_source_asset") else "semantic_redraw" if adapter else "generated"
    visual = {
        "page_id": page.get("id"),
        "artifact_type": artifact_type,
        "visual_intent": page.get("visual_intent") or (adapter or {}).get("visual_intent") or "supporting_visual",
        "required_semantic_elements": required_elements,
        "planned_semantic_elements": planned_elements,
        "observed_semantic_elements": [],
        "evidence": [],
        "evidence_status": "PLANNED_NOT_OBSERVED",
        "source_asset_ids": asset_ids,
        "selected_source_asset_ids": selected_source_assets,
        "source_image_ref": source_image,
        "render_strategy": strategy,
        "structure_requirements": structure_defaults(
            artifact_type,
            required_elements,
            visual_intent=str(page.get("visual_intent") or (adapter or {}).get("visual_intent") or ""),
        ),
        "source_reference_policy": "reuse user asset when clear; otherwise semantic redraw; external images are reference-only unless reuse is licensed",
    }
    # Compatibility alias for Phase 1 consumers. It means planned elements,
    # never observed elements.
    visual["semantic_elements"] = list(planned_elements)
    return visual


def validate_visual(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    artifact_type = plan.get("artifact_type")
    required = set(plan.get("required_semantic_elements", []))
    planned = set(plan.get("planned_semantic_elements", plan.get("semantic_elements", [])))
    observed = set(plan.get("observed_semantic_elements", []))
    if artifact_type and required - planned:
        errors.append(f"{plan.get('page_id')}: planned visual is missing semantic elements {sorted(required - planned)}")
    strategy = plan.get("render_strategy")
    if artifact_type and strategy in {"generic_rectangle", "placeholder", "todo"}:
        errors.append(f"{plan.get('page_id')}: typed visual cannot use {strategy}")
    if artifact_type and not plan.get("visual_intent"):
        errors.append(f"{plan.get('page_id')}: artifact_type requires visual_intent")
    if observed and required - observed:
        errors.append(f"{plan.get('page_id')}: observed visual is missing semantic elements {sorted(required - observed)}")
    return errors


def visual_observation_status(plan: dict[str, Any]) -> str:
    required = set(plan.get("required_semantic_elements", []))
    observed = set(plan.get("observed_semantic_elements", []))
    if not observed:
        return "PLANNED_NOT_OBSERVED"
    return "PASS" if required <= observed else "NOT_OBSERVED"


def build_visual_plans(session_plans: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    assets = {str(item["id"]): item for item in inventory.get("assets", []) if isinstance(item, dict) and item.get("id")}
    plans: list[dict[str, Any]] = []
    errors: list[str] = []
    for session in session_plans.get("sessions", []):
        for page in session.get("pages", []):
            visual = plan_visual(page, assets)
            if visual is None:
                continue
            errors.extend(validate_visual(visual))
            plans.append({"session_id": session.get("id"), **visual})
    if errors:
        raise OrchestrationError("semantic visual planning failed:\n- " + "\n- ".join(errors))
    return {
        "schema_version": "1.1",
        "plan_type": "semantic_visual_plans",
        "visual_plans": plans,
        "adapters": sorted(SEMANTIC_ADAPTERS),
        "adapter_capabilities": {key: value["capabilities"] for key, value in SEMANTIC_ADAPTERS.items()},
        "evidence_state_model": {"required": "question-specific subset", "planned": "planner proposal", "observed": "downstream DOM/source evidence only"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-plans", required=True)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_visual_plans(load_json(args.session_plans), load_json(args.assets))
    dump_json(result, args.output_json)
    if args.json:
        print({"visual_plans": len(result["visual_plans"]), "adapters": len(result["adapters"])})


if __name__ == "__main__":
    main()
