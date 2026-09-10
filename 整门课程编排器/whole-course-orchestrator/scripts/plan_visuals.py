"""Plan semantic visuals and validate typed visual evidence."""

from __future__ import annotations

import argparse
from typing import Any

from orchestrator_core import OrchestrationError, dump_json, load_json


SEMANTIC_ADAPTERS: dict[str, dict[str, Any]] = {
    "use_case_model": {
        "visual_intent": "relationship",
        "required_elements": ["actor", "system_boundary", "use_case", "association", "include", "extend", "generalization"],
    },
    "class_model": {
        "visual_intent": "hierarchy",
        "required_elements": ["class_compartment", "attribute", "operation", "relationship", "multiplicity", "inheritance", "aggregation", "composition"],
    },
    "sequence_model": {
        "visual_intent": "sequence",
        "required_elements": ["lifeline", "activation", "message", "return", "fragment"],
    },
    "state_model": {
        "visual_intent": "state_transition",
        "required_elements": ["state", "event", "transition", "guard", "initial", "final"],
    },
    "deployment_model": {
        "visual_intent": "topology",
        "required_elements": ["node", "artifact", "deployment", "communication_link"],
    },
    "activity_model": {
        "visual_intent": "process",
        "required_elements": ["action", "control_flow", "decision", "guard", "fork_or_join", "initial_or_final"],
    },
}


def adapter_for(artifact_type: str | None) -> dict[str, Any] | None:
    return SEMANTIC_ADAPTERS.get(str(artifact_type or ""))


def plan_visual(page: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    artifact_type = page.get("artifact_type")
    asset_ids = [str(item) for item in page.get("source_asset_ids", [])]
    referenced_assets = [assets[item] for item in asset_ids if item in assets]
    is_visual = bool(artifact_type or page.get("visual_intent") or asset_ids or page.get("primary_job") == "visualize")
    if not is_visual:
        return None
    adapter = adapter_for(str(artifact_type)) if artifact_type else None
    supplied_elements = [str(item) for item in page.get("semantic_elements", [])]
    required_elements = list(adapter.get("required_elements", [])) if adapter else []
    semantic_elements = supplied_elements or required_elements[:]
    selected_source_assets = [asset["id"] for asset in referenced_assets if asset.get("teaching_value") in {"core", "supporting"}]
    source_image = next((asset.get("image_ref") for asset in referenced_assets if asset.get("image_ref")), None)
    strategy = str(page.get("render_strategy") or "")
    if not strategy:
        strategy = "reuse" if source_image and page.get("reuse_source_asset") else "semantic_redraw" if adapter else "generated"
    return {
        "page_id": page.get("id"),
        "artifact_type": artifact_type,
        "visual_intent": page.get("visual_intent") or (adapter or {}).get("visual_intent"),
        "semantic_elements": semantic_elements,
        "required_semantic_elements": required_elements,
        "source_asset_ids": asset_ids,
        "selected_source_asset_ids": selected_source_assets,
        "source_image_ref": source_image,
        "render_strategy": strategy,
        "source_reference_policy": "reuse user asset when clear; otherwise semantic redraw; external images are reference-only unless reuse is licensed",
    }


def validate_visual(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    artifact_type = plan.get("artifact_type")
    required = set(plan.get("required_semantic_elements", []))
    actual = set(plan.get("semantic_elements", []))
    if artifact_type and required - actual:
        errors.append(f"{plan.get('page_id')}: typed visual is missing semantic elements {sorted(required - actual)}")
    strategy = plan.get("render_strategy")
    if artifact_type and strategy in {"generic_rectangle", "placeholder", "todo"}:
        errors.append(f"{plan.get('page_id')}: typed visual cannot use {strategy}")
    if artifact_type and not plan.get("visual_intent"):
        errors.append(f"{plan.get('page_id')}: artifact_type requires visual_intent")
    return errors


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
        "schema_version": "1.0",
        "plan_type": "semantic_visual_plans",
        "visual_plans": plans,
        "adapters": sorted(SEMANTIC_ADAPTERS),
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
