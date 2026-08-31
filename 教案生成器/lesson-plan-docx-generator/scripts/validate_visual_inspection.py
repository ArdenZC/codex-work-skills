"""Validate Agent visual evidence against the current QA output tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from path_safety import paths_equal
from record_visual_inspection import CHECK_NAMES, output_fingerprint


def validate_visual_inspection(
    output_dir: Path | str,
    qa_report: Path | str,
    evidence_path: Path | str,
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve()
    report_path = Path(qa_report).expanduser().resolve()
    evidence_file = Path(evidence_path).expanduser().resolve()
    if not report_path.is_file() or not evidence_file.is_file():
        raise ValueError("visual evidence and qa-report.json must both exist")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("visual evidence or qa-report.json is not valid JSON") from exc
    if not isinstance(report, dict) or not isinstance(evidence, dict):
        raise ValueError("visual evidence and qa-report.json must contain objects")
    if report.get("status") != "passed":
        raise ValueError("visual evidence requires a passed QA report")
    if "output_dir" in report and not paths_equal(report["output_dir"], directory):
        raise ValueError("qa-report output_dir does not match output_dir")
    if evidence.get("status") != "passed" or evidence.get("qa_status") != "passed":
        raise ValueError("visual evidence status is not passed")
    required = {
        "status",
        "inspected_files",
        "inspected_pages",
        "checks",
        "notes",
        "related_qa_report",
        "output_fingerprint",
        "timestamp",
        "page_bounds_verified",
    }
    missing_keys = sorted(required - set(evidence))
    if missing_keys:
        raise ValueError(f"visual evidence schema is missing keys: {', '.join(missing_keys)}")
    if not isinstance(evidence["timestamp"], str) or not isinstance(evidence["notes"], str):
        raise ValueError("visual evidence timestamp/notes have invalid types")
    if evidence.get("related_qa_report") and not paths_equal(evidence["related_qa_report"], report_path):
        raise ValueError("visual evidence references a different QA report")
    current_fingerprint = output_fingerprint(directory, report_path)
    if evidence.get("output_fingerprint") != current_fingerprint:
        raise ValueError("visual evidence is stale: output fingerprint does not match")

    inspected_files = evidence.get("inspected_files")
    inspected_pages = evidence.get("inspected_pages")
    checks = evidence.get("checks")
    if not isinstance(inspected_files, list) or not isinstance(inspected_pages, dict):
        raise ValueError("visual evidence inspected_files/inspected_pages are malformed")
    if set(checks or {}) != set(CHECK_NAMES) or any(checks[name] != "passed" for name in CHECK_NAMES):
        raise ValueError("visual evidence must record all eleven checks as passed")
    available = {path.name for path in directory.glob("*.docx") if path.is_file() and not path.is_symlink()}
    if set(inspected_files) != set(inspected_pages) or not set(inspected_files) <= available:
        raise ValueError("visual evidence references missing or unexpected DOCX files")
    if not inspected_files or not inspected_pages:
        raise ValueError("visual evidence must include at least one inspected DOCX and page")
    if any(
        not isinstance(pages, list)
        or not pages
        or any(not isinstance(page, int) or page <= 0 for page in pages)
        for pages in inspected_pages.values()
    ):
        raise ValueError("visual evidence must include positive inspected page numbers")

    page_counts = report.get("render", {}).get("page_counts")
    if not evidence.get("page_bounds_verified"):
        if page_counts:
            raise ValueError("render.page_counts are present but page_bounds_verified is false")
    else:
        if not isinstance(page_counts, dict):
            raise ValueError("page_bounds_verified requires render.page_counts")
        for name, pages in inspected_pages.items():
            maximum = page_counts.get(name)
            if not isinstance(pages, list) or not isinstance(maximum, int) or maximum <= 0:
                raise ValueError(f"page bounds are malformed for {name}")
            if any(not isinstance(page, int) or page <= 0 or page > maximum for page in pages):
                raise ValueError(f"inspected pages exceed render.page_counts for {name}")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--qa-report", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_visual_inspection(args.output_dir, args.qa_report, args.evidence), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
