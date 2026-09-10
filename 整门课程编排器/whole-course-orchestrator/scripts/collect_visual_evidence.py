"""Collect marker and structural visual evidence from final Courseware HTML.

Planner requirements are never copied into ``observed`` fields.  This module
keeps two evidence layers separate:

* marker evidence proves that semantic metadata survived the renderer;
* structure evidence proves that a typed visual has real nodes, edges and
  endpoint relationships rather than labels painted onto arbitrary rectangles.

Neither layer is a visual-aesthetics or teacher-acceptance judgment.
"""

from __future__ import annotations

import argparse
import html as html_module
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from orchestrator_core import dump_json, load_json
from semantic_artifacts import artifact_spec, structure_defaults


KNOWN_ROLES = {
    "actor", "system_boundary", "use_case", "association", "include", "extend", "generalization",
    "class", "class_compartment", "attribute", "operation", "relationship", "multiplicity", "inheritance", "aggregation", "composition",
    "lifeline", "activation", "message", "return", "fragment", "state", "event", "transition", "guard", "initial", "final",
    "node", "artifact", "deployment", "communication_link", "action", "control_flow", "decision", "fork_or_join", "initial_or_final",
}

TYPED_ARTIFACTS = {
    "class_model",
    "sequence_model",
    "state_model",
    "deployment_model",
    "use_case_model",
    "activity_model",
    "tree_graph_structure",
    "relational_table_model",
    "network_topology",
    "worksheet_dataflow",
}


def _empty_page(page_id: str) -> dict[str, Any]:
    return {
        "page_id": page_id,
        "artifact_types": set(),
        "roles": set(),
        "evidence": [],
        "asset_ids": set(),
        "text": [],
        "visual_nodes": [],
        "nodes": [],
        "edges": [],
        "labels": [],
    }


def _tokens(value: Any) -> Iterable[str]:
    text = str(value or "").replace("-", "_").replace("/", "_")
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]+", text):
        lowered = token.lower()
        if lowered in KNOWN_ROLES:
            yield lowered


class _VisualDOMParser(HTMLParser):
    def __init__(self, source_name: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_name = source_name
        self.pages: dict[str, dict[str, Any]] = {}
        self.current_page: str | None = None
        # Keep the opening tag with the previous page.  A page contains many
        # nested divs; popping on every div end would otherwise close the page
        # at the first inner container and make later evidence look like it
        # belongs to the document root.
        self.page_stack: list[tuple[str, str | None]] = []
        self.element_stack: list[dict[str, Any]] = []

    def _page(self) -> dict[str, Any]:
        page_id = self.current_page or "__document__"
        return self.pages.setdefault(page_id, _empty_page(page_id))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("data-page-id"):
            self.page_stack.append((tag, self.current_page))
            self.current_page = values["data-page-id"]
        page = self._page()
        selector = tag
        if values.get("id"):
            selector += f"#{values['id']}"
        if values.get("class"):
            selector += "." + ".".join(values["class"].split())
        artifact_type = values.get("data-artifact-type") or values.get("data-visual-artifact")
        if artifact_type:
            page["artifact_types"].add(artifact_type)
            page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "artifact-type-marker", "value": artifact_type, "selector": selector})
        for raw_role in (values.get("data-semantic-role", ""), values.get("data-semantic-roles", "")):
            for role in re.split(r"[\s,;|]+", raw_role):
                role = role.strip().lower()
                if not role:
                    continue
                page["roles"].add(role)
                page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "semantic-role-marker", "value": role, "selector": selector})
        for key in ("class", "id", "aria-label", "data-label", "data-role"):
            for role in _tokens(values.get(key)):
                page["roles"].add(role)
                page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "accessible-semantic-label", "value": role, "selector": selector, "attribute": key})
        for key in ("data-source-asset-id", "data-derived-from-asset-id", "data-derived-from-asset-ids"):
            raw_ids = values.get(key, "")
            if raw_ids:
                ids = [item for item in re.split(r"[\s,;|]+", raw_ids) if item]
                page["asset_ids"].update(ids)
                page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "asset-render-marker", "value": ids, "selector": selector, "attribute": key})
        if tag in {"svg", "img", "canvas"} or values.get("data-visual-container") == "true":
            visual = {"kind": tag, "selector": selector, "source": self.source_name, "page_id": page["page_id"]}
            page["visual_nodes"].append(visual)
            page["evidence"].append({**visual, "kind": "rendered-visual-container"})
        if tag == "img" and values.get("src"):
            page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "rendered-image", "value": values["src"][:120], "selector": selector})

        node_id = values.get("data-node-id") or values.get("data-node-key")
        edge_id = values.get("data-edge-id") or values.get("data-edge-key")
        label_for = values.get("data-label-for") or values.get("data-label-for-key") or values.get("data-related-edge-id") or values.get("data-related-edge-key")
        if node_id:
            node = {
                "id": str(node_id),
                "roles": sorted(set(_role_values(values))),
                "selector": selector,
            }
            page["nodes"].append(node)
            page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "semantic-structure-node", **node})
        if edge_id:
            edge = {
                "id": str(edge_id),
                "roles": sorted(set(_role_values(values))),
                "source_id": values.get("data-source-id") or values.get("data-source-node-id") or values.get("data-source-key"),
                "target_id": values.get("data-target-id") or values.get("data-target-node-id") or values.get("data-target-key"),
                "relation_kind": values.get("data-relation-kind") or values.get("data-edge-kind"),
                "order": _int_or_none(values.get("data-order") or values.get("data-message-order")),
                "selector": selector,
            }
            page["edges"].append(edge)
            page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "semantic-structure-edge", **edge})
        if label_for or values.get("data-label-kind"):
            label = {
                "id": values.get("data-label-id") or selector,
                "for_edge": label_for,
                "kind": values.get("data-label-kind") or values.get("data-semantic-role"),
                "endpoint": values.get("data-label-endpoint"),
                "value": values.get("data-label") or "",
                "selector": selector,
            }
            page["labels"].append(label)
        self.element_stack.append({"tag": tag, "label": page["labels"][-1] if (label_for or values.get("data-label-kind")) else None})

    def handle_endtag(self, tag: str) -> None:
        if self.element_stack:
            # HTMLParser is intentionally tolerant of the SVG/HTML mix used by
            # Courseware.  Pop the nearest matching element without allowing a
            # nested div to close the page or a structure label early.
            for index in range(len(self.element_stack) - 1, -1, -1):
                if self.element_stack[index]["tag"] == tag:
                    del self.element_stack[index:]
                    break
        if self.page_stack and self.page_stack[-1][0] == tag:
            _, self.current_page = self.page_stack.pop()

    def handle_data(self, data: str) -> None:
        if data.strip():
            value = data.strip()
            self._page()["text"].append(value)
            for item in reversed(self.element_stack):
                label = item.get("label")
                if label is not None:
                    label["value"] = (str(label.get("value") or "") + " " + value).strip()
                    break


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _role_values(values: dict[str, str]) -> list[str]:
    roles: list[str] = []
    for key in ("data-semantic-role", "data-semantic-roles", "data-role"):
        roles.extend(item.strip().lower() for item in re.split(r"[\s,;|]+", values.get(key, "")) if item.strip())
    return roles


def _read_html(value: str | Path | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        return value.read_text(encoding="utf-8")
    text = str(value)
    if "<" in text and ">" in text:
        return text
    path = Path(text)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _records_for_html(value: str | Path | None, source_name: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    source = _read_html(value)
    if not source:
        return records
    parser = _VisualDOMParser(source_name)
    parser.feed(source)
    for page_id, record in parser.pages.items():
        records[page_id] = record
    return records


def _normalise_page_records(student_html: str | Path | None, teacher_html: str | Path | None) -> dict[str, dict[str, Any]]:
    """Compatibility merged view; final evidence uses per-role records."""

    merged: dict[str, dict[str, Any]] = {}
    for name, value in (("student.html", student_html), ("teacher.html", teacher_html)):
        for page_id, record in _records_for_html(value, name).items():
            target = merged.setdefault(page_id, _empty_page(page_id))
            target["artifact_types"].update(record["artifact_types"])
            target["roles"].update(record["roles"])
            target["evidence"].extend(record["evidence"])
            target["asset_ids"].update(record["asset_ids"])
            target["text"].extend(record["text"])
            target["visual_nodes"].extend(record["visual_nodes"])
            target["nodes"].extend(record["nodes"])
            target["edges"].extend(record["edges"])
            target["labels"].extend(record["labels"])
    return merged


def _required_roles(plan: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(str(item).lower() for item in plan.get("required_semantic_elements", []) if str(item).strip()))


def _marker_evidence(plan: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    required = _required_roles(plan)
    observed = sorted(set(str(item) for item in record.get("roles", set())))
    missing = sorted(set(required) - set(observed))
    if required:
        status = "PASS" if not missing else "PLANNED_NOT_OBSERVED" if not observed else "FAIL"
    else:
        status = "PASS" if record.get("visual_nodes") else "PLANNED_NOT_OBSERVED"
    return {
        "status": status,
        "required_roles": required,
        "observed_roles": observed,
        "missing_roles": missing,
        "artifact_types": sorted(record.get("artifact_types", set())),
        "source_asset_ids": sorted(record.get("asset_ids", set())),
        "evidence": list(record.get("evidence", [])),
        "interpretation": "marker plumbing only; this does not establish typed semantic structure",
    }


def _edge_roles(edge: dict[str, Any]) -> set[str]:
    values = {str(item).lower() for item in edge.get("roles", [])}
    if edge.get("relation_kind"):
        values.add(str(edge["relation_kind"]).lower().replace("-", "_"))
    return values


def _has_role(item: dict[str, Any], role: str) -> bool:
    return str(role).lower() in {str(value).lower() for value in item.get("roles", [])}


def _structure_evidence(plan: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    artifact = str(plan.get("artifact_type") or "")
    if not artifact:
        return {
            "status": "NOT_APPLICABLE",
            "artifact_type": None,
            "nodes": list(record.get("nodes", [])),
            "edges": list(record.get("edges", [])),
            "labels": list(record.get("labels", [])),
            "errors": [],
            "interpretation": "supporting visual has no typed structural contract",
        }
    nodes = list(record.get("nodes", []))
    edges = list(record.get("edges", []))
    labels = list(record.get("labels", []))
    node_ids = {str(item.get("id")) for item in nodes if item.get("id")}
    requirements = plan.get("structure_requirements") if isinstance(plan.get("structure_requirements"), dict) else structure_defaults(
        artifact,
        _required_roles(plan),
        visual_intent=plan.get("visual_intent"),
    )
    errors: list[str] = []

    def role_nodes(role: str) -> list[dict[str, Any]]:
        return [item for item in nodes if _has_role(item, role)]

    def role_edges(*roles: str) -> list[dict[str, Any]]:
        wanted = {role.lower() for role in roles}
        return [item for item in edges if _edge_roles(item) & wanted]

    def endpoint_edges(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in values if item.get("source_id") in node_ids and item.get("target_id") in node_ids]

    if artifact == "class_model":
        class_nodes = role_nodes("class")
        if len(class_nodes) < int(requirements.get("min_nodes", 2)):
            errors.append("class_model requires at least two class nodes")
        relations = endpoint_edges(role_edges("relationship", "association", "inheritance", "aggregation", "composition"))
        if requirements.get("relationship_required") and not relations:
            errors.append("class_model requires a relationship edge with valid source/target endpoints")
        required_kinds = {str(item).lower() for item in requirements.get("relation_kinds", [])}
        if "inheritance" in _required_roles(plan):
            required_kinds.add("inheritance")
        if "aggregation" in _required_roles(plan):
            required_kinds.add("aggregation")
        if "composition" in _required_roles(plan):
            required_kinds.add("composition")
        for kind in required_kinds:
            if not any(kind in _edge_roles(edge) for edge in relations):
                errors.append(f"class_model is missing relation kind: {kind}")
        if "attribute" in _required_roles(plan) and not any(_has_role(node, "attribute") for node in class_nodes):
            errors.append("class_model requires an attribute-bearing class compartment")
        if "operation" in _required_roles(plan) and not any(_has_role(node, "operation") for node in class_nodes):
            errors.append("class_model requires an operation-bearing class compartment")
        if "multiplicity" in _required_roles(plan) or requirements.get("multiplicity_labels"):
            relation_ids = {str(edge.get("id")) for edge in relations}
            multiplicities = [label for label in labels if str(label.get("kind", "")).lower() == "multiplicity" and str(label.get("for_edge")) in relation_ids]
            if len(multiplicities) < int(requirements.get("multiplicity_labels", 2)):
                errors.append("class_model requires multiplicity labels associated with a relationship edge")
    elif artifact == "sequence_model":
        lifelines = role_nodes("lifeline")
        if len(lifelines) < int(requirements.get("min_lifelines", 2)):
            errors.append("sequence_model requires at least two lifeline nodes")
        messages = endpoint_edges(role_edges("message", "return"))
        if not messages:
            errors.append("sequence_model requires message edges with valid source/target lifelines")
        if "return" in _required_roles(plan) and not any(_has_role(edge, "return") for edge in messages):
            errors.append("sequence_model is missing a return message")
        if "fragment" in _required_roles(plan) and not role_nodes("fragment"):
            errors.append("sequence_model is missing a typed fragment container")
        orders = [edge.get("order") for edge in messages if edge.get("order") is not None]
        if orders and orders != sorted(orders):
            errors.append("sequence_model message order is not monotonic")
    elif artifact == "state_model":
        states = role_nodes("state")
        if len(states) < int(requirements.get("min_states", 2)):
            errors.append("state_model requires at least two state nodes")
        transitions = endpoint_edges(role_edges("transition"))
        if not transitions:
            errors.append("state_model requires transition edges with valid endpoints")
        if any(role in _required_roles(plan) for role in ("guard", "event")):
            if not any(_has_role(edge, "guard") or _has_role(edge, "event") for edge in transitions):
                errors.append("state_model guard/event must be associated with a transition")
    elif artifact == "deployment_model":
        if not role_nodes("node"):
            errors.append("deployment_model requires a node")
        if not role_nodes("artifact"):
            errors.append("deployment_model requires an artifact/component")
        relations = endpoint_edges(role_edges("deployment", "communication_link"))
        if not relations:
            errors.append("deployment_model requires a deployment or communication edge")
        if "communication_link" in _required_roles(plan) and not any(_has_role(edge, "communication_link") for edge in relations):
            errors.append("deployment_model is missing a communication link")
    elif artifact == "use_case_model":
        if not role_nodes("actor"):
            errors.append("use_case_model requires an actor node")
        if not role_nodes("use_case"):
            errors.append("use_case_model requires a use-case node")
        relations = endpoint_edges(role_edges("association", "include", "extend", "generalization"))
        if not relations:
            errors.append("use_case_model requires an association edge with valid endpoints")
        for kind in ("include", "extend"):
            if kind in _required_roles(plan) and not any(kind in _edge_roles(edge) for edge in relations):
                errors.append(f"use_case_model is missing typed {kind} relationship")
    elif artifact == "activity_model":
        if not role_nodes("action"):
            errors.append("activity_model requires an action node")
        flows = endpoint_edges(role_edges("control_flow"))
        if not flows:
            errors.append("activity_model requires control-flow edges with valid endpoints")
        if "decision" in _required_roles(plan):
            decisions = role_nodes("decision")
            outgoing = [edge for edge in flows if edge.get("source_id") in {str(item.get("id")) for item in decisions}]
            if not decisions or len(outgoing) < 2:
                errors.append("activity_model decision requires a decision node with outgoing paths")
        if "guard" in _required_roles(plan) and not any(_has_role(edge, "guard") for edge in flows):
            errors.append("activity_model guard must be associated with an outgoing flow")
    elif artifact == "tree_graph_structure":
        nodes_for_tree = role_nodes("node")
        if len(nodes_for_tree) < int(requirements.get("min_nodes", 1)):
            errors.append("tree_graph_structure does not contain the required node count")
        if "root" in _required_roles(plan) and not role_nodes("root"):
            errors.append("tree_graph_structure requires a root node")
        tree_edges = endpoint_edges(role_edges("edge", "parent_child", "traversal", "direction"))
        if requirements.get("edge_required") and not tree_edges:
            errors.append("tree_graph_structure requires a parent/child or traversal edge with endpoints")
    elif artifact == "relational_table_model":
        tables = role_nodes("table")
        if len(tables) < int(requirements.get("min_tables", 1)):
            errors.append("relational_table_model requires a table node")
        if "field" in _required_roles(plan) and not role_nodes("field"):
            errors.append("relational_table_model requires a field node")
        if requirements.get("key_required") and not role_nodes("key"):
            errors.append("relational_table_model requires a key node")
        relational_edges = endpoint_edges(role_edges("relationship"))
        if requirements.get("relationship_required") and not relational_edges:
            errors.append("relational_table_model requires a relationship edge with endpoints")
    elif artifact == "network_topology":
        devices = role_nodes("device") or role_nodes("node")
        if len(devices) < int(requirements.get("min_devices", 1)):
            errors.append("network_topology does not contain the required device count")
        links = endpoint_edges(role_edges("link", "direction", "path"))
        if requirements.get("link_required") and not links:
            errors.append("network_topology requires a link/path edge with endpoints")
        if "direction" in _required_roles(plan) and not any(_has_role(edge, "direction") for edge in links):
            errors.append("network_topology requires a directed link")
    elif artifact == "worksheet_dataflow":
        cells = role_nodes("cell") or role_nodes("range")
        if len(cells) < int(requirements.get("min_cells", 1)):
            errors.append("worksheet_dataflow requires a cell or range node")
        if requirements.get("formula_required") and not role_nodes("formula"):
            errors.append("worksheet_dataflow requires a formula node")
        dependencies = endpoint_edges(role_edges("dependency", "transformation"))
        if requirements.get("dependency_required") and not dependencies:
            errors.append("worksheet_dataflow requires a dependency edge with endpoints")
    else:
        errors.append(f"unsupported typed artifact: {artifact}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "artifact_type": artifact,
        "nodes": nodes,
        "edges": edges,
        "labels": labels,
        "errors": errors,
        "interpretation": "typed structural relationships are required; visible tokens alone are insufficient",
    }


def collect_visual_evidence(
    visual_plans: dict[str, Any] | list[dict[str, Any]],
    student_html: str | Path | None = None,
    teacher_html: str | Path | None = None,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    plans = visual_plans.get("visual_plans", []) if isinstance(visual_plans, dict) else visual_plans
    student_pages = _records_for_html(student_html, "student.html")
    teacher_pages = _records_for_html(teacher_html, "teacher.html")
    observed_plans: list[dict[str, Any]] = []
    student_assets: set[str] = set()
    teacher_assets: set[str] = set()
    incomplete = False
    for raw in plans or []:
        plan = dict(raw)
        page_id = str(plan.get("page_id") or "")
        student_record = student_pages.get(page_id, _empty_page(page_id))
        teacher_record = teacher_pages.get(page_id, _empty_page(page_id))
        required = list(dict.fromkeys(str(item) for item in plan.get("required_semantic_elements", [])))
        student_observed = sorted(set(str(item) for item in student_record["roles"]))
        teacher_observed = sorted(set(str(item) for item in teacher_record["roles"]))
        student_marker = _marker_evidence(plan, student_record)
        teacher_marker = _marker_evidence(plan, teacher_record)
        student_structure = _structure_evidence(plan, student_record)
        teacher_structure = _structure_evidence(plan, teacher_record)
        plan["observed_semantic_elements"] = student_observed
        plan["student_observed"] = student_observed
        plan["teacher_observed"] = teacher_observed
        plan["evidence"] = list(student_record["evidence"])
        plan["student_evidence"] = list(student_record["evidence"])
        plan["teacher_evidence"] = list(teacher_record["evidence"])
        plan["observed_artifact_types"] = sorted(student_record["artifact_types"])
        plan["student_observed_artifact_types"] = sorted(student_record["artifact_types"])
        plan["teacher_observed_artifact_types"] = sorted(teacher_record["artifact_types"])
        plan["observed_source_asset_ids"] = sorted(student_record["asset_ids"])
        plan["student_observed_source_asset_ids"] = sorted(student_record["asset_ids"])
        plan["teacher_observed_source_asset_ids"] = sorted(teacher_record["asset_ids"])
        plan["semantic_marker_evidence"] = student_marker
        plan["marker_evidence"] = student_marker
        plan["semantic_structure_evidence"] = student_structure
        plan["structure_evidence"] = student_structure
        plan["student_semantic_marker_evidence"] = student_marker
        plan["student_semantic_structure_evidence"] = student_structure
        plan["teacher_semantic_marker_evidence"] = teacher_marker
        plan["teacher_semantic_structure_evidence"] = teacher_structure
        plan["visual_container_observed"] = bool(student_record.get("visual_nodes"))
        plan["student_visual_container_observed"] = bool(student_record.get("visual_nodes"))
        plan["teacher_visual_container_observed"] = bool(teacher_record.get("visual_nodes"))
        if not student_record.get("visual_nodes"):
            plan["evidence_status"] = "PLANNED_NOT_OBSERVED"
        elif student_marker["status"] != "PASS":
            plan["evidence_status"] = "PLANNED_NOT_OBSERVED" if student_marker["status"] == "PLANNED_NOT_OBSERVED" else "FAIL"
        elif student_structure["status"] == "FAIL":
            plan["evidence_status"] = "FAIL"
        else:
            plan["evidence_status"] = "PASS"
        plan["semantic_status"] = "PASS" if plan["evidence_status"] == "PASS" else "NOT_OBSERVED" if plan["evidence_status"] == "PLANNED_NOT_OBSERVED" else "FAIL"
        if plan["evidence_status"] != "PASS":
            incomplete = True
        student_assets.update(student_record["asset_ids"])
        teacher_assets.update(teacher_record["asset_ids"])
        observed_plans.append(plan)
    # A session with no visual requirement is not a missing observation.  A
    # declared visual plan with no final DOM, however, is a failed observation
    # and must remain fail-closed.
    status = "PASS" if not plans else "FAIL" if incomplete else "PASS"
    result = {
        "schema_version": "1.1",
        "report_type": "whole_course_visual_evidence",
        "status": status,
        "visual_plans": observed_plans,
        "rendered_asset_ids": sorted(student_assets),
        "student_rendered_asset_ids": sorted(student_assets),
        "teacher_rendered_asset_ids": sorted(teacher_assets),
        "page_count_observed": len(student_pages),
        "student_page_count_observed": len(student_pages),
        "teacher_page_count_observed": len(teacher_pages),
        "marker_plumbing_status": "NOT_APPLICABLE" if not plans else "PASS" if all(item["student_semantic_marker_evidence"]["status"] == "PASS" for item in observed_plans) else "FAIL",
        "semantic_structure_status": "NOT_APPLICABLE" if not plans else "PASS" if all(item["student_semantic_structure_evidence"]["status"] in {"PASS", "NOT_APPLICABLE"} for item in observed_plans) else "FAIL",
        "student_marker_plumbing_status": "NOT_APPLICABLE" if not plans else "PASS" if all(item["student_semantic_marker_evidence"]["status"] == "PASS" for item in observed_plans) else "FAIL",
        "student_semantic_structure_status": "NOT_APPLICABLE" if not plans else "PASS" if all(item["student_semantic_structure_evidence"]["status"] in {"PASS", "NOT_APPLICABLE"} for item in observed_plans) else "FAIL",
        "teacher_marker_plumbing_status": "NOT_APPLICABLE" if not plans else "PASS" if all(item["teacher_semantic_marker_evidence"]["status"] in {"PASS", "PLANNED_NOT_OBSERVED"} for item in observed_plans) else "FAIL",
        "teacher_semantic_structure_status": "NOT_APPLICABLE" if not plans else "PASS" if all(item["teacher_semantic_structure_evidence"]["status"] in {"PASS", "NOT_APPLICABLE", "PLANNED_NOT_OBSERVED"} for item in observed_plans) else "FAIL",
        "overall_policy": "Every declared visual plan must have a real rendered visual container and pass its marker/structure contract; no plan is allowed to disappear into an overall PASS.",
        "collection_policy": "Student-facing visual status is computed from student.html only. Teacher evidence is retained separately and cannot fill a student-facing gap. Observed roles come only from final Courseware DOM markers, accessible labels, classes or IDs; planner requirements are never used as observations.",
    }
    if output_path:
        dump_json(result, output_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-plans", required=True)
    parser.add_argument("--student-html", required=True)
    parser.add_argument("--teacher-html")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = collect_visual_evidence(load_json(args.visual_plans), args.student_html, args.teacher_html, output_path=args.output_json)
    if args.json:
        print({"status": result["status"], "visuals": len(result["visual_plans"]), "rendered_assets": result["rendered_asset_ids"]})


if __name__ == "__main__":
    main()
