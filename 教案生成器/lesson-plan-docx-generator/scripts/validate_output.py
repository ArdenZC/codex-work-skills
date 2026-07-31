from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import _Cell
from lxml import etree

from package_common import DEFAULT_MANIFEST, DEFAULT_SCHEMA, field_spec, load_manifest, manifest_template_path, validate_input


def actual_cells(row) -> list[_Cell]:
    return [_Cell(tc, row._parent) for tc in row._tr.tc_lst]


def cell_text(table, row_index: int, cell_index: int) -> str:
    return actual_cells(table.rows[row_index])[cell_index].text.strip()


def parse_number(value: Any, label: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric: {value!r}") from exc


def _xml(element) -> str:
    return etree.tostring(copy.deepcopy(element), encoding="unicode")


def protected_layout_signature(document) -> dict[str, Any]:
    table = document.tables[0]
    rows = []
    for row in table.rows:
        rows.append(
            {
                "trPr": _xml(row._tr.trPr) if row._tr.trPr is not None else "",
                "cells": [_xml(cell._tc.tcPr) if cell._tc.tcPr is not None else "" for cell in actual_cells(row)],
            }
        )
    return {
        "tablePr": _xml(table._tbl.tblPr) if table._tbl.tblPr is not None else "",
        "tblGrid": _xml(table._tbl.tblGrid) if table._tbl.tblGrid is not None else "",
        "rows": rows,
        "sections": [
            {
                "page_width": section.page_width.twips,
                "page_height": section.page_height.twips,
                "top_margin": section.top_margin.twips,
                "bottom_margin": section.bottom_margin.twips,
                "left_margin": section.left_margin.twips,
                "right_margin": section.right_margin.twips,
                "header_footer_refs": [
                    _xml(child)
                    for child in section._sectPr
                    if child.tag.endswith("headerReference") or child.tag.endswith("footerReference")
                ],
            }
            for section in document.sections
        ],
    }


def _validate_text_length(name: str, value: str, spec: dict[str, Any], errors: list[str]) -> None:
    max_chars = spec.get("max_chars")
    if max_chars is not None and len(value) > int(max_chars):
        errors.append(f"{name} exceeds manifest max_chars={max_chars}: {len(value)}")


def _field_targets(document, table, spec: dict[str, Any]):
    if spec.get("target") == "document_paragraph" or "paragraph" in spec:
        index = int(spec.get("paragraph", -1))
        if 0 <= index < len(document.paragraphs):
            return [(document.paragraphs[index].text, 1)]
        return []
    if spec.get("mode") == "row_cells":
        values = []
        for row_index in spec.get("rows", []):
            if row_index >= len(table.rows):
                continue
            cells = actual_cells(table.rows[int(row_index)])
            for cell_index in spec.get("cells", []):
                if cell_index < len(cells):
                    values.append((cells[int(cell_index)].text, len(cells[int(cell_index)].paragraphs)))
        return values
    if "table" in spec and "row" in spec and "cell" in spec:
        table_index = int(spec["table"])
        if table_index == 0 and int(spec["row"]) < len(table.rows):
            cells = actual_cells(table.rows[int(spec["row"])])
            cell_index = int(spec["cell"])
            if cell_index < len(cells):
                cell = cells[cell_index]
                return [(cell.text, len(cell.paragraphs))]
    return []


def _document_text(document, table) -> str:
    values = [paragraph.text for paragraph in document.paragraphs]
    for row in table.rows:
        for cell in actual_cells(row):
            values.append(cell.text)
            for nested in cell.tables:
                for nested_row in nested.rows:
                    values.extend(nested_cell.text for nested_cell in nested_row.cells)
    for section in document.sections:
        values.extend(paragraph.text for paragraph in section.header.paragraphs)
        values.extend(paragraph.text for paragraph in section.footer.paragraphs)
    return "\n".join(values)


def validate_output_dir(
    output_dir: Path | str,
    data: dict[str, Any],
    manifest: dict[str, Any] | None = None,
    qa_report_path: Path | str | None = None,
    schema_path: Path | str = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    out_dir = Path(output_dir).expanduser().resolve()
    manifest = manifest or load_manifest()
    validate_input(data, schema_path)
    lessons = data["lessons"]
    files = sorted(out_dir.glob("*.docx"))
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    report: dict[str, Any] = {
        "status": "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "template_id": manifest.get("template", {}).get("id"),
        "template_version": manifest.get("template", {}).get("version"),
        "output_dir": str(out_dir),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "files_checked": 0,
    }

    if not files:
        errors.append(f"No DOCX files generated in {out_dir}")
    if len(files) != len(lessons):
        errors.append(f"Output count mismatch: expected {len(lessons)}, got {len(files)}")

    main_spec = manifest["structure"]["main_table"]
    course_expected = str(data["course_name"])
    total_hours = 0.0
    lesson_checks = []
    for index, (path, item) in enumerate(zip(files, lessons), start=1):
        item_errors: list[str] = []
        if not path.is_file() or path.stat().st_size == 0:
            item_errors.append("file is missing or empty")
            errors.extend(f"{path.name}: {message}" for message in item_errors)
            lesson_checks.append({"file": path.name, "errors": item_errors})
            continue
        try:
            document = Document(str(path))
        except Exception as exc:  # pragma: no cover - library-specific parse errors
            item_errors.append(f"DOCX could not be opened: {exc}")
            lesson_checks.append({"file": path.name, "errors": item_errors})
            errors.extend(f"{path.name}: {message}" for message in item_errors)
            continue
        if len(document.tables) <= int(main_spec["index"]):
            item_errors.append("main table is missing")
            lesson_checks.append({"file": path.name, "errors": item_errors})
            errors.extend(f"{path.name}: {message}" for message in item_errors)
            continue
        table = document.tables[int(main_spec["index"])]
        canonical_template = manifest_template_path(manifest)
        if canonical_template.exists():
            canonical_document = Document(str(canonical_template))
            if protected_layout_signature(document) != protected_layout_signature(canonical_document):
                item_errors.append("protected DOCX layout changed")
        if len(table.rows) != int(main_spec["rows"]):
            item_errors.append(f"main table rows expected {main_spec['rows']}, got {len(table.rows)}")
        if len(table.columns) != int(main_spec["columns"]):
            item_errors.append(f"main table columns expected {main_spec['columns']}, got {len(table.columns)}")

        field_values = {
            "course_name": cell_text(table, 0, int(field_spec(manifest, "course_name")["cell"])),
            "unit": cell_text(table, 1, int(field_spec(manifest, "unit")["cell"])),
            "task": cell_text(table, 1, int(field_spec(manifest, "task")["cell"])),
            "hours": cell_text(table, 1, int(field_spec(manifest, "hours")["cell"])),
        }
        if field_values["course_name"] != course_expected:
            item_errors.append(f"course mismatch: expected {course_expected!r}, got {field_values['course_name']!r}")
        if field_values["unit"] != str(item["unit"]):
            item_errors.append(f"unit mismatch: expected {item['unit']!r}, got {field_values['unit']!r}")
        if field_values["task"] != str(item["task"]):
            item_errors.append(f"task mismatch: expected {item['task']!r}, got {field_values['task']!r}")
        try:
            hours = parse_number(field_values["hours"], "hours")
            expected_hours = parse_number(item["hours"], "input hours")
            total_hours += hours
            if not math.isclose(hours, expected_hours, abs_tol=0.01):
                item_errors.append(f"hours mismatch: expected {expected_hours}, got {hours}")
        except ValueError as exc:
            item_errors.append(str(exc))
        if not field_values["unit"].startswith("项目"):
            item_errors.append(f"unit is not projectized: {field_values['unit']}")

        title_spec = field_spec(manifest, "title")
        title_index = int(title_spec.get("paragraph", manifest["structure"]["title"]["paragraph"]))
        expected_title = f"{index} 《{course_expected}》教学单元设计：{item['task']}"
        actual_title = document.paragraphs[title_index].text if 0 <= title_index < len(document.paragraphs) else ""
        if actual_title != expected_title:
            item_errors.append(f"title mismatch: expected {expected_title!r}, got {actual_title!r}")

        for name, spec in manifest.get("fields", {}).items():
            if name in {"evaluation"}:
                continue
            for value, paragraph_count in _field_targets(document, table, spec):
                _validate_text_length(name, value, spec, item_errors)
                max_paragraphs = spec.get("max_paragraphs")
                if max_paragraphs is not None and paragraph_count > int(max_paragraphs):
                    item_errors.append(f"{name} exceeds manifest max_paragraphs={max_paragraphs}: {paragraph_count}")

        nested_spec = manifest["structure"]["evaluation_table"]
        try:
            eval_cell = actual_cells(table.rows[int(nested_spec["row"])])[int(nested_spec["cell"])]
            nested = eval_cell.tables[0]
            if len(nested.rows) != int(nested_spec["rows"]) or len(nested.columns) != int(nested_spec["columns"]):
                item_errors.append("evaluation table structure changed")
            score_values = [parse_number(nested.cell(row, 2).text, f"evaluation score row {row}") for row in range(1, 14)]
            target = float(item.get("score", 89 + ((index - 1) % 6) * 0.5))
            score_sum = round(sum(score_values), 1)
            if not math.isclose(score_sum, target, abs_tol=float(manifest["validation"].get("score_tolerance", 0.1))):
                item_errors.append(f"evaluation total mismatch: expected {target}, got {score_sum}")
        except (IndexError, ValueError) as exc:
            item_errors.append(f"evaluation table validation failed: {exc}")

        all_text = _document_text(document, table)
        for forbidden in manifest.get("validation", {}).get("forbidden_template_text", []):
            if forbidden in {course_expected, str(item["unit"]), str(item["task"])}:
                continue
            if forbidden in all_text:
                item_errors.append(f"forbidden template text remains: {forbidden}")
        if course_expected != "Linux操作系统应用" and "Linux操作系统应用" in all_text:
            item_errors.append("template course-name placeholder Linux操作系统应用 remains")
        if item_errors:
            errors.extend(f"{path.name}: {message}" for message in item_errors)
        lesson_checks.append({"file": path.name, "errors": item_errors, "fields": field_values})

    expected_total = data.get("total_hours")
    if expected_total is not None:
        try:
            if not math.isclose(total_hours, parse_number(expected_total, "total_hours"), abs_tol=0.01):
                errors.append(f"Total hours mismatch: expected {expected_total}, got {total_hours:g}")
        except ValueError as exc:
            errors.append(str(exc))
    checks["file_count"] = {"expected": len(lessons), "actual": len(files)}
    checks["total_hours"] = {"expected": expected_total, "actual": total_hours}
    checks["lessons"] = lesson_checks
    report["files_checked"] = len(files)
    if not warnings:
        warnings = report["warnings"]
    if not errors:
        report["status"] = "passed"

    report_path = Path(qa_report_path).expanduser().resolve() if qa_report_path else out_dir / "qa-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report["qa_report"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError("Output validation failed: " + "; ".join(errors[:8]))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated lesson-plan DOCX files and write a QA report.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--qa-report", default="")
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.input_json).read_text(encoding="utf-8-sig"))
        report = validate_output_dir(args.output_dir, data, load_manifest(args.manifest), args.qa_report or None, args.schema)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for warning in report.get("warnings", []):
        print(f"WARNING: {warning}")
    print(f"validated files={report['checks']['file_count']['actual']} qa={report['qa_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
