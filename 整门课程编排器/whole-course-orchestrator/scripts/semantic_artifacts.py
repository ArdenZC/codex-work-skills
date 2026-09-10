"""Domain-neutral semantic artifact registry.

The whole-course layer needs to know what a visual or editable starter can
prove, but it must not assume that every course is a UML course.  This module
keeps the registry deliberately declarative.  Page-specific requirements are
computed by the visual planner from the teaching question; an artifact family
only advertises capabilities and safe defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArtifactSpec:
    artifact_type: str
    family: str
    visual_intent: str
    capabilities: tuple[str, ...]
    default_requirements: tuple[str, ...]
    starter_components: tuple[str, ...] = ()
    starter_gaps: tuple[str, ...] = ()


_SPECS = (
    ArtifactSpec(
        "use_case_model", "uml", "relationship",
        ("actor", "system_boundary", "use_case", "association", "include", "extend", "generalization"),
        ("actor", "use_case"),
        ("actor", "system_boundary", "partial_use_cases"),
        ("missing_actor", "missing_relation"),
    ),
    ArtifactSpec(
        "class_model", "uml", "hierarchy",
        ("class", "class_compartment", "attribute", "operation", "association", "relationship", "multiplicity", "inheritance", "aggregation", "composition"),
        ("class", "class_compartment"),
        ("partial_classes", "missing_relationship", "missing_multiplicity"),
        ("missing_relation", "wrong_multiplicity"),
    ),
    ArtifactSpec(
        "sequence_model", "uml", "sequence",
        ("lifeline", "activation", "message", "return", "fragment"),
        ("lifeline",),
        ("lifelines", "missing_messages", "wrong_order"),
        ("missing_message", "wrong_message_order"),
    ),
    ArtifactSpec(
        "state_model", "uml", "state_transition",
        ("state", "event", "transition", "guard", "initial", "final"),
        ("state",),
        ("states", "missing_transition_event"),
        ("missing_transition",),
    ),
    ArtifactSpec(
        "deployment_model", "uml", "topology",
        ("node", "artifact", "deployment", "communication_link"),
        ("node",),
        ("nodes", "artifact_placement"),
        ("wrong_node_mapping",),
    ),
    ArtifactSpec(
        "activity_model", "uml", "process",
        ("action", "control_flow", "decision", "guard", "fork_or_join", "initial_or_final"),
        ("action",),
        ("actions", "decision_node", "partial_control_flow"),
        ("missing_transition", "wrong_guard"),
    ),
    ArtifactSpec(
        "tree_graph_structure", "graph", "structure",
        ("node", "edge", "root", "parent_child", "traversal", "direction"),
        ("node",),
        ("nodes", "root", "partial_edges"),
        ("missing_edge", "wrong_parent"),
    ),
    ArtifactSpec(
        "relational_table_model", "relational", "data_model",
        ("table", "field", "key", "relationship", "row", "column"),
        ("table",),
        ("table", "field", "missing_key"),
        ("missing_key", "wrong_relationship"),
    ),
    ArtifactSpec(
        "network_topology", "topology", "network",
        ("device", "node", "link", "direction", "path", "layer", "role"),
        ("device",),
        ("device", "link", "partial_path"),
        ("missing_link", "wrong_direction"),
    ),
    ArtifactSpec(
        "worksheet_dataflow", "dataflow", "transformation",
        ("cell", "range", "formula", "dependency", "input", "output", "transformation"),
        ("cell",),
        ("cell_range", "formula", "partial_dependency"),
        ("missing_formula", "wrong_dependency"),
    ),
)

ARTIFACT_REGISTRY: dict[str, ArtifactSpec] = {item.artifact_type: item for item in _SPECS}


def artifact_spec(artifact_type: Any) -> ArtifactSpec | None:
    return ARTIFACT_REGISTRY.get(str(artifact_type or ""))


def artifact_capabilities(artifact_type: Any) -> set[str]:
    spec = artifact_spec(artifact_type)
    return set(spec.capabilities if spec else ())


def starter_spec(artifact_type: Any) -> dict[str, Any] | None:
    spec = artifact_spec(artifact_type)
    if spec is None or not spec.starter_components:
        return None
    return {
        "artifact_type": spec.artifact_type,
        "components": list(spec.starter_components),
        "gaps": list(spec.starter_gaps),
        "family": spec.family,
    }


def structure_defaults(
    artifact_type: Any,
    required_roles: list[str] | tuple[str, ...] | set[str],
    *,
    visual_intent: str | None = None,
) -> dict[str, Any]:
    """Return conservative, page-scoped structural requirements.

    These defaults intentionally do not turn an artifact family into a full
    model template.  A page that only teaches one class or one table remains a
    valid visual; relationship-specific pages opt into endpoints explicitly.
    """

    spec = artifact_spec(artifact_type)
    roles = {str(item).lower() for item in required_roles}
    intent = str(visual_intent or "").lower()
    if spec is None:
        return {}
    result: dict[str, Any] = {"required_roles": sorted(roles)}
    if spec.artifact_type == "class_model":
        relation_required = bool(roles & {"relationship", "association", "inheritance", "aggregation", "composition", "multiplicity"}) or intent in {"relationship", "multiplicity", "hierarchy"} and bool(roles & {"relationship", "multiplicity"})
        result.update({"min_nodes": 2 if relation_required else 1, "relationship_required": relation_required})
        if "multiplicity" in roles:
            result["multiplicity_labels"] = 2
        result["relation_kinds"] = sorted(roles & {"association", "relationship", "inheritance", "aggregation", "composition"})
    elif spec.artifact_type == "sequence_model":
        result["min_lifelines"] = 2 if roles & {"message", "return", "fragment"} else 1
    elif spec.artifact_type == "state_model":
        result["min_states"] = 2 if "transition" in roles else 1
    elif spec.artifact_type in {"deployment_model", "use_case_model", "activity_model"}:
        result["question_scoped"] = True
    elif spec.artifact_type == "tree_graph_structure":
        result.update({"min_nodes": 2 if roles & {"edge", "parent_child", "traversal"} else 1, "edge_required": bool(roles & {"edge", "parent_child", "traversal"})})
    elif spec.artifact_type == "relational_table_model":
        result.update({"min_tables": 1, "relationship_required": bool(roles & {"relationship"}), "key_required": bool(roles & {"key"})})
    elif spec.artifact_type == "network_topology":
        result.update({"min_devices": 2 if roles & {"link", "direction", "path"} else 1, "link_required": bool(roles & {"link", "direction", "path"})})
    elif spec.artifact_type == "worksheet_dataflow":
        result.update({"min_cells": 1, "dependency_required": bool(roles & {"dependency", "transformation"}), "formula_required": bool(roles & {"formula"})})
    return result


def registry_summary() -> dict[str, Any]:
    return {
        key: {
            "family": spec.family,
            "visual_intent": spec.visual_intent,
            "capabilities": list(spec.capabilities),
            "default_requirements": list(spec.default_requirements),
            "starter_components": list(spec.starter_components),
            "starter_gaps": list(spec.starter_gaps),
        }
        for key, spec in ARTIFACT_REGISTRY.items()
    }
