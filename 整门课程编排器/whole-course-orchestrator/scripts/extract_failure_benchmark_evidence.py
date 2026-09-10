"""Extract a normalized snapshot from the real frozen failure output.

This command reads the already-frozen external benchmark and its existing
courseware/practice artifacts.  It never regenerates the old UML course and it
never rewrites the source or build roots.  The resulting snapshot is small
enough for CI replay while retaining the evidence needed by course-level QA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from orchestrator_core import canonical_hash, dump_json, load_json


EXTRACTOR_VERSION = "1.1.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _load_record(record: dict[str, Any]) -> Any:
    path = Path(str(record["path"]))
    return load_json(path)


def _record_for(records: list[dict[str, Any]], pattern: str) -> dict[str, Any]:
    matches = [record for record in records if re.fullmatch(pattern, str(record.get("relative_path", "")).replace("\\", "/"))]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frozen record for {pattern}, found {len(matches)}")
    return matches[0]


def _find_file(root: Path, *parts: str) -> Path | None:
    candidate = root.joinpath(*parts)
    return candidate if candidate.is_file() else None


def _svg_summary(svg: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(svg)
        elements = list(root.iter())
    except ET.ParseError:
        return {"parse_status": "FAIL", "element_count": 0, "node_count": 0, "edge_count": 0, "labels": []}
    node_ids = [element.get("data-node-id") for element in elements if element.get("data-node-id")]
    edge_ids = [element.get("data-edge-id") for element in elements if element.get("data-edge-id")]
    labels = [element.get("data-label") or "" for element in elements if element.get("data-label-kind")]
    return {
        "parse_status": "PASS",
        "element_count": len(elements),
        "node_count": len(node_ids),
        "edge_count": len(edge_ids),
        "node_ids": node_ids,
        "edge_ids": edge_ids,
        "labels": labels,
        "legacy_shape_count": sum(1 for element in elements if _local(element.tag) in {"rect", "line", "ellipse", "polygon", "circle"}),
        "typed_structure_marker_count": len(node_ids) + len(edge_ids),
    }


def _drawio_signature(path: Path) -> dict[str, Any]:
    try:
        root = ET.fromstring(path.read_bytes())
        cells = [element for element in root.iter() if _local(element.tag) == "mxCell"]
    except (OSError, ET.ParseError):
        return {"status": "FAIL", "sha256": _sha256(path), "vertex_count": 0, "edge_count": 0, "value_tokens": []}
    return {
        "status": "PASS",
        "sha256": _sha256(path),
        "vertex_count": sum(1 for cell in cells if cell.get("vertex") == "1"),
        "edge_count": sum(1 for cell in cells if cell.get("edge") == "1"),
        "value_tokens": sorted(str(cell.get("value") or "") for cell in cells if cell.get("value")),
    }


def _source_hash_records(benchmark: dict[str, Any]) -> dict[str, Any]:
    artifact_sets = benchmark.get("artifact_sets", {})
    return {
        "source_files": list(benchmark.get("source_files", [])),
        "converted_source_evidence": list(benchmark.get("converted_source_evidence", [])),
        "artifact_sets": {name: list(records) for name, records in artifact_sets.items()},
    }


def _verify_frozen_records(records: dict[str, Any]) -> dict[str, Any]:
    checked = 0
    missing: list[str] = []
    mismatches: list[dict[str, Any]] = []
    def visit(value: Any) -> None:
        nonlocal checked
        if isinstance(value, dict):
            if value.get("path") and value.get("sha256"):
                path = Path(str(value["path"]))
                checked += 1
                if not path.is_file():
                    missing.append(str(path))
                else:
                    actual = _sha256(path)
                    if actual != value["sha256"]:
                        mismatches.append({"path": str(path), "expected": value["sha256"], "actual": actual})
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(records)
    return {"status": "PASS" if not missing and not mismatches else "FAIL", "checked_files": checked, "missing": missing, "mismatches": mismatches}


def _theory_session(
    session_number: int,
    contract: dict[str, Any],
    build_root: Path,
) -> dict[str, Any]:
    session_id = f"session-{session_number:02d}"
    rendered_html = _find_file(build_root, "rendered", "courseware", session_id, "student.html")
    rendered_html_text = rendered_html.read_text(encoding="utf-8", errors="ignore") if rendered_html else ""
    pages: list[dict[str, Any]] = []
    for slide in contract.get("slides", []):
        blocks = slide.get("blocks", []) if isinstance(slide.get("blocks"), list) else []
        block_signature = [str(block.get("type")) for block in blocks if isinstance(block, dict)]
        visual_evidence: list[dict[str, Any]] = []
        content_evidence: dict[str, Any] = {}
        source_asset_ids: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            source_asset_ids.extend(str(item) for item in (block.get("source_asset_ids") or []) if item)
            if block.get("type") == "svg":
                visual_evidence.append({"type": "svg", "caption": block.get("caption"), "summary": _svg_summary(str(block.get("svg") or ""))})
            elif block.get("type") == "image":
                visual_evidence.append({"type": "image", "caption": block.get("caption")})
            elif block.get("type") == "comparison":
                content_evidence["comparison"] = dict(block)
            elif block.get("type") == "quiz":
                content_evidence["quiz"] = dict(block)
        pages.append({
            "id": slide.get("id"),
            "title": slide.get("title"),
            "layout": slide.get("layout"),
            "layout_family": [slide.get("layout")],
            "primary_job": slide.get("primary_job") or slide.get("delivery_track") or "lesson",
            "lecture_minutes": slide.get("lecture_minutes", 0),
            "activity_minutes": slide.get("activity_minutes", 0),
            "suggested_minutes": slide.get("suggested_minutes", 0),
            "block_signature": block_signature,
            "speaker_script": slide.get("speaker_script", ""),
            "source_asset_ids": sorted(set(source_asset_ids)),
            "contract_referenced_asset_ids": sorted(set(source_asset_ids)),
            "content_evidence": content_evidence,
            "visual_evidence_summary": visual_evidence,
            "rendered_visual_count": rendered_html_text.count("<svg") + rendered_html_text.count("<img"),
        })
    return {
        "id": session_id,
        "session_number": session_number,
        "title": contract.get("chapter_title"),
        "real_page_count": len(pages),
        "real_layout_sequence": [page.get("layout") for page in pages],
        "real_primary_jobs": [page.get("primary_job") for page in pages],
        "real_lecture_activity_minutes": [[page.get("lecture_minutes"), page.get("activity_minutes")] for page in pages],
        "real_block_signatures": [page.get("block_signature") for page in pages],
        "real_speaker_scripts": [page.get("speaker_script") for page in pages],
        "real_visual_evidence_summary": [page.get("visual_evidence_summary") for page in pages],
        "real_comparison_evidence": [page.get("content_evidence", {}).get("comparison") for page in pages if page.get("content_evidence", {}).get("comparison")],
        "real_quiz_evidence": [page.get("content_evidence", {}).get("quiz") for page in pages if page.get("content_evidence", {}).get("quiz")],
        "pages": pages,
    }


def _practice_session(session_number: int, contract: dict[str, Any], build_root: Path) -> dict[str, Any]:
    session_id = f"session-{session_number:02d}"
    starter_root = build_root / "rendered" / "practice" / session_id / "student" / "starter"
    tasks: list[dict[str, Any]] = []
    for task in contract.get("tasks", []):
        if not isinstance(task, dict):
            continue
        starter_ids = [str(item) for item in task.get("starter_asset_ids", []) if item]
        starter_files = [path for path in starter_root.rglob("*") if path.is_file() and any(asset_id in path.stem for asset_id in starter_ids)] if starter_root.is_dir() else []
        if not starter_files and starter_root.is_dir():
            # The frozen contract's logical starter id and the real output
            # filename are not required to be identical; retain the actual
            # file rather than silently reporting an empty starter signature.
            starter_files = [path for path in starter_root.rglob("*") if path.is_file()]
        starter_signatures = [{"path": str(path.relative_to(starter_root).as_posix()), **_drawio_signature(path)} for path in starter_files]
        structural_payload = {
            "level": task.get("level"),
            "capabilities": sorted(str(item) for item in task.get("capabilities", []) or []),
            "artifact_kind": task.get("artifact_kind"),
            "step_count": len(task.get("steps", []) if isinstance(task.get("steps"), list) else []),
            "step_titles": [step.get("title") for step in task.get("steps", []) if isinstance(step, dict)],
            "estimated_minutes": task.get("estimated_minutes"),
            "starter_shape": [(item.get("vertex_count"), item.get("edge_count")) for item in starter_signatures],
        }
        tasks.append({
            "id": task.get("id"),
            "title": task.get("title"),
            "level": task.get("level"),
            "capability": task.get("modality") or task.get("task_kind"),
            "capabilities": task.get("capabilities", []),
            "estimated_minutes": task.get("estimated_minutes"),
            "artifact_type": task.get("artifact_kind"),
            "artifact_kind": task.get("artifact_kind"),
            "source_slide_ids": task.get("source_slide_ids", []),
            "steps": task.get("steps", []),
            "step_structure": [{"title": step.get("title"), "instruction": step.get("instruction"), "check": step.get("check")} for step in task.get("steps", []) if isinstance(step, dict)],
            "starter_asset_ids": starter_ids,
            "starter_signatures": starter_signatures,
            "starter": {"artifact_type": task.get("artifact_kind"), "components": sorted({str(item.get("vertex_count")) for item in starter_signatures})},
            "structural_task_signature": canonical_hash(structural_payload),
            "semantic_task_signature": canonical_hash({"title": task.get("title"), "source_slide_ids": task.get("source_slide_ids", []), "capabilities": task.get("capabilities", [])}),
        })
    return {
        "id": session_id,
        "session_number": session_number,
        "title": contract.get("practice_title"),
        "real_task_count": len(tasks),
        "real_capabilities": [task.get("capabilities", []) for task in tasks],
        "real_minutes": [task.get("estimated_minutes") for task in tasks],
        "real_step_structures": [task.get("step_structure") for task in tasks],
        "real_artifact_types": [task.get("artifact_type") for task in tasks],
        "real_starter_signatures": [task.get("starter_signatures") for task in tasks],
        "tasks": tasks,
    }


def extract(benchmark_path: Path, output_path: Path) -> dict[str, Any]:
    benchmark_path = benchmark_path.expanduser().resolve()
    benchmark = load_json(benchmark_path)
    build_root = Path(str(benchmark["build_root"])).expanduser().resolve()
    source_root = Path(str(benchmark["source_root"])).expanduser().resolve()
    if not build_root.is_dir() or not source_root.is_dir():
        raise FileNotFoundError(f"frozen source/build roots are unavailable: {source_root}, {build_root}")
    source_hashes = _source_hash_records(benchmark)
    integrity = _verify_frozen_records(source_hashes)
    if integrity["status"] != "PASS":
        raise ValueError("frozen benchmark evidence changed or is unavailable: " + json.dumps(integrity, ensure_ascii=False))
    package_candidates = sorted(source_root.parent.glob("*.zip"))
    package = package_candidates[0] if len(package_candidates) == 1 else None
    courseware_records = benchmark["artifact_sets"]["courseware_contracts"]
    practice_records = benchmark["artifact_sets"]["practice_contracts"]
    theory_sessions = [_theory_session(index, _load_record(_record_for(courseware_records, rf"contracts/session-{index:02d}/courseware\.json")), build_root) for index in range(1, int(benchmark["course_shape"]["theory_session_count"]) + 1)]
    practice_sessions = [_practice_session(index, _load_record(_record_for(practice_records, rf"contracts/session-{index:02d}/practice\.json")), build_root) for index in range(1, int(benchmark["course_shape"]["practice_session_count"]) + 1)]
    payload: dict[str, Any] = {
        "snapshot_type": "REAL_FROZEN_FAILURE_EVIDENCE",
        "snapshot_schema_version": "1.0",
        "source_benchmark_id": benchmark.get("benchmark_id"),
        "source_benchmark_sha256": _sha256(benchmark_path),
        "original_package": {"path": str(package), "sha256": _sha256(package)} if package else {"status": "NOT_FOUND"},
        "relevant_original_file_hashes": source_hashes,
        "integrity_at_extraction": integrity,
        "extractor_version": EXTRACTOR_VERSION,
        "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
        "extracted_from_real_output": True,
        "source_root": str(source_root),
        "build_root": str(build_root),
        "course_shape": benchmark.get("course_shape", {}),
        "generator_evidence": benchmark.get("generator_evidence", {}),
        "expected_findings": sorted(set(benchmark.get("failure_findings", {}).get("theory", {}).get("finding_codes", []) + benchmark.get("failure_findings", {}).get("practice", {}).get("finding_codes", []))),
        "theory_sessions": theory_sessions,
        "practice_sessions": practice_sessions,
        "inventory_assets": [],
    }
    payload["snapshot_sha256"] = canonical_hash({key: value for key, value in payload.items() if key not in {"snapshot_sha256", "extraction_timestamp"}})
    dump_json(payload, output_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-json", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    args = parser.parse_args()
    result = extract(args.benchmark_json, args.output_json)
    print({"snapshot_type": result["snapshot_type"], "snapshot_sha256": result["snapshot_sha256"], "theory_sessions": len(result["theory_sessions"]), "practice_sessions": len(result["practice_sessions"])})


if __name__ == "__main__":
    main()
