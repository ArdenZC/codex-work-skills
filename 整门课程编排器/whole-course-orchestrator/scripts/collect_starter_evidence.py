"""Collect observed evidence from final Practice starter artifacts."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from orchestrator_core import dump_json, load_json


def _read_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    path = Path(str(value))
    return load_json(path) if path.is_file() else None


def _find_paths(bundle: Any) -> list[Path]:
    if bundle is None:
        return []
    if isinstance(bundle, (list, tuple)):
        result: list[Path] = []
        for item in bundle:
            result.extend(_find_paths(item))
        return result
    path = Path(str(bundle)).expanduser().resolve()
    if path.is_file():
        return [path]
    if path.is_dir():
        return [item for item in path.rglob("*") if item.is_file()]
    return []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            values.append(str(key))
            values.extend(_strings(item))
        return values
    return []


def _requirements(value: Any) -> list[str]:
    if isinstance(value, dict) and "starter_requirements" in value:
        value = value["starter_requirements"]
    if isinstance(value, dict):
        value = value.get("requires", value.get("required", value.get("components", [])))
    result: list[str] = []
    for item in value or []:
        if isinstance(item, dict):
            if item.get("type"):
                result.append(str(item["type"]))
            elif item.get("name"):
                result.append(str(item["name"]))
        else:
            result.append(str(item))
    return list(dict.fromkeys(result))


def _artifact_type(plan: dict[str, Any] | None) -> str:
    if not isinstance(plan, dict):
        return ""
    return str(plan.get("artifact_type") or plan.get("artifact_kind") or "")


def _xml_text(root: ET.Element) -> str:
    values: list[str] = []
    for node in root.iter():
        values.extend(str(value) for key, value in node.attrib.items() if key in {"value", "style", "id", "label", "data-semantic-role", "data-editable-gap"})
        if node.text:
            values.append(node.text)
    return " ".join(values)


def _drawio_observation(path: Path, artifact_type: str) -> tuple[set[str], list[dict[str, Any]]]:
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as exc:
        return set(), [{"path": str(path), "error": f"DRAWIO_PARSE_FAILED: {exc}"}]
    cells = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "mxCell"]
    text = _xml_text(root).lower()
    values = {str(value).lower() for node in cells for key, value in node.attrib.items() if key in {"value", "style", "id", "data-semantic-role", "data-editable-gap"}}
    observed: set[str] = set()
    evidence: list[dict[str, Any]] = [{"path": str(path), "kind": "drawio-xml", "cell_count": len(cells)}]

    def has(*terms: str) -> bool:
        return any(term.lower() in text or any(term.lower() in value for value in values) for term in terms)

    if artifact_type == "class_model":
        if has("umlclass", "class", "class_compartment"):
            observed.update({"class", "class_compartment"})
            if has("partial_classes") or has("editable_gap", "missing_relationship", "missing_relation"):
                observed.add("partial_classes")
        if has("relation", "association", "edgeStyle", "connect"):
            observed.update({"relationship", "association"})
        if has("missing_relationship", "missing_relation"):
            observed.add("missing_relationship")
        if has("multiplicity", "0..", "1..", "many", "*", "基数", "多重"):
            observed.add("multiplicity")
        if has("missing_multiplicity", "wrong_multiplicity", "multiplicity", "基数", "多重"):
            observed.add("missing_multiplicity")
        if has("attribute", "field", "+id", "-id"):
            observed.add("attribute")
        if has("operation", "method", "()"): observed.add("operation")
    elif artifact_type == "sequence_model":
        if has("lifeline", "umlLifeline", "participant"):
            observed.update({"lifeline", "lifelines"})
        if has("message", "missing_message", "arrow", "message") and any(node.attrib.get("edge") == "1" for node in cells): observed.add("message")
        if has("missing_message", "missing_messages"):
            observed.add("missing_messages")
        if has("wrong_order", "wrong_message_order", "order"):
            observed.add("wrong_order")
        if has("activation"): observed.add("activation")
        if has("return"): observed.add("return")
    elif artifact_type == "state_model":
        if has("state", "umlstate", "state node"): observed.add("state")
        if has("transition", "edge", "event"): observed.add("transition")
        if has("guard", "["):
            observed.add("guard")
    elif artifact_type == "deployment_model":
        if has("node", "umlcomponent", "device"): observed.add("node")
        if has("artifact", "artifact placement"): observed.update({"artifact", "deployment"})
        if has("edge", "communication", "link"): observed.add("communication_link")
    else:
        for token in re.findall(r"[a-z_]+", text):
            if token in {"editable", "artifact", "node", "message", "transition", "relationship", "multiplicity"}:
                observed.add(token)
    for marker in re.findall(r"(?:gap|editable_gap)[:=_-]([a-z_]+)", text):
        observed.add(f"editable_gap:{marker}")
    for marker in re.findall(r"missing_[a-z_]+", text):
        observed.add(f"editable_gap:{marker}")
    evidence.append({"path": str(path), "kind": "artifact-semantic-observation", "artifact_type": artifact_type, "observed": sorted(observed)})
    return observed, evidence


def _non_xml_observation(paths: list[Path], artifact_type: str, behavior_verification: dict[str, Any] | None) -> tuple[set[str], list[dict[str, Any]]]:
    observed: set[str] = set()
    evidence: list[dict[str, Any]] = []
    suffixes = {path.suffix.lower() for path in paths}
    if paths:
        observed.add("artifact_exists")
    if suffixes & {".sql", ".py", ".js", ".ts", ".html", ".css"}:
        observed.update({"starter_file", "editable"})
    if suffixes & {".xlsx", ".xls", ".csv"}:
        observed.update({"worksheet", "editable"})
        if any("formula" in path.name.lower() for path in paths):
            observed.add("formula")
    if suffixes & {".html", ".css", ".js", ".ts"}:
        observed.add("project_bundle")
    if behavior_verification and str(behavior_verification.get("status", "")).upper() in {"PASS", "PASSED", "PASSING", "pass"}:
        observed.add("behavior_verified")
    evidence.append({"kind": "non-xml-starter-observation", "paths": [str(path) for path in paths], "observed": sorted(observed)})
    return observed, evidence


def _student_leaks(paths: list[Path]) -> list[str]:
    markers = ("reference_answer", "teacher_reference", "canonical_answers_included\": true", "teacher-only answer")
    leaks: list[str] = []
    for path in paths:
        if path.suffix.lower() not in {".json", ".html", ".txt", ".md", ".drawio", ".xml", ".py", ".sql", ".js", ".ts"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        for marker in markers:
            if marker.lower() in text:
                leaks.append(f"{path}: {marker}")
    return leaks


def collect_starter_evidence(
    starter_requirements: Any,
    starter_plan: dict[str, Any] | None = None,
    starter_bundle: str | Path | None = None,
    *,
    manifest: dict[str, Any] | str | Path | None = None,
    qa_report: dict[str, Any] | str | Path | None = None,
    behavior_verification: dict[str, Any] | str | Path | None = None,
    student_root: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    if isinstance(starter_requirements, dict) and starter_plan is None:
        source = starter_requirements
        starter_plan = source.get("starter_plan", source)
        starter_requirements = source.get("starter_requirements", source.get("requires", []))
    plan = starter_plan if isinstance(starter_plan, dict) else {}
    requirements = _requirements(starter_requirements)
    artifact_type = _artifact_type(plan)
    paths = _find_paths(starter_bundle)
    manifest_value = _read_json(manifest)
    qa_value = _read_json(qa_report)
    behavior_value = _read_json(behavior_verification)
    observed: set[str] = set()
    evidence: list[dict[str, Any]] = []
    for path in paths:
        if path.suffix.lower() in {".drawio", ".xml"}:
            found, records = _drawio_observation(path, artifact_type)
        else:
            found, records = _non_xml_observation([path], artifact_type, behavior_value)
        observed.update(found)
        evidence.extend(records)
    if not paths and isinstance(manifest_value, dict):
        manifest_paths = _strings(manifest_value.get("files") or manifest_value.get("starter_assets"))
        if manifest_paths:
            evidence.append({"kind": "manifest-only", "paths": manifest_paths})
    if not paths and behavior_value and str(behavior_value.get("status", "")).upper() in {"PASS", "PASSED", "pass"}:
        observed.add("behavior_verified")
    student_paths = _find_paths(student_root) if student_root else [path for path in paths if "student" in path.as_posix().lower()]
    leaks = _student_leaks(student_paths)
    artifact_exists = bool(paths)
    missing = sorted(set(requirements) - observed)
    if not paths:
        status = "NOT_OBSERVED"
    elif missing or not artifact_exists or leaks:
        status = "STARTER_EVIDENCE_INCOMPLETE"
    else:
        status = "PASS"
    result = {
        "schema_version": "1.1",
        "report_type": "whole_course_starter_evidence",
        "status": status,
        "artifact_type": artifact_type,
        "starter_requirements": requirements,
        "starter_plan": plan,
        "starter_observed": sorted(observed),
        "missing_requirements": missing,
        "student_artifact_exists": artifact_exists,
        "teacher_only_answer_leakage": bool(leaks),
        "leakage_details": leaks,
        "evidence": evidence,
        "manifest_observed": bool(manifest_value),
        "qa_report_observed": bool(qa_value),
        "collection_policy": "Artifact-specific validators read real files and declared behavior/closure evidence; starter_plan alone cannot produce observed evidence.",
    }
    if output_path:
        dump_json(result, output_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements-json", required=True)
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--starter-bundle", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--qa-report")
    parser.add_argument("--behavior-verification")
    parser.add_argument("--student-root")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = collect_starter_evidence(load_json(args.requirements_json), load_json(args.plan_json), args.starter_bundle, manifest=args.manifest, qa_report=args.qa_report, behavior_verification=args.behavior_verification, student_root=args.student_root, output_path=args.output_json)
    if args.json:
        print({"status": result["status"], "artifact_type": result["artifact_type"], "observed": result["starter_observed"]})


if __name__ == "__main__":
    main()
