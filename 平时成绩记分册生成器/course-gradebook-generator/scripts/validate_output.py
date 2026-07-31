from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from package_common import DEFAULT_MANIFEST, DEFAULT_SCHEMA, column_number, load_manifest, validate_input
from validate_template import convert_to_xlsx, find_soffice


def _number(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric: {value!r}") from exc


def _cell(ws, column: str, row: int):
    return ws[f"{column}{row}"]


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
    files = sorted(out_dir.glob("*.xls"))
    errors: list[str] = []
    warnings: list[str] = []
    report: dict[str, Any] = {
        "status": "failed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "template_id": manifest.get("template", {}).get("id"),
        "template_version": manifest.get("template", {}).get("version"),
        "output_dir": str(out_dir),
        "errors": errors,
        "warnings": warnings,
        "checks": {},
    }
    if len(files) != 1:
        errors.append(f"Expected one generated XLS file, got {len(files)}")
    if files:
        path = files[0]
        structure = manifest["structure"]
        columns = structure["columns"]
        start_row = int(structure["data_start_row"])
        skill_enabled = data["weights"]["skill"] > 0.000001
        total_column = columns["total_score"] if skill_enabled else structure["no_skill_total_column"]
        formula_columns = manifest["fields"]["formula_columns_with_skill"]["columns"] if skill_enabled else manifest["fields"]["formula_columns_without_skill"]["columns"]
        try:
            with tempfile.TemporaryDirectory(prefix="gradebook-output-") as temp_name:
                xlsx = convert_to_xlsx(path, Path(temp_name), find_soffice())
                formulas = load_workbook(xlsx, data_only=False)
                values = load_workbook(xlsx, data_only=True)
                sheet_name = structure["worksheet"]
                if sheet_name not in formulas.sheetnames:
                    errors.append(f"Missing worksheet: {sheet_name}")
                else:
                    ws_formula = formulas[sheet_name]
                    ws_values = values[sheet_name]
                    expected_meta = {
                        "term": data["term"],
                        "course": data["course"],
                        "teacher": data["teacher"],
                        "class_name": data["class_name"],
                    }
                    for name, expected in expected_meta.items():
                        cell = structure["metadata"][name]
                        actual = ws_values[cell].value
                        if str(actual).strip() != str(expected).strip():
                            errors.append(f"{name} mismatch: expected {expected!r}, got {actual!r}")
                    student_checks = []
                    for index, student in enumerate(data["students"]):
                        row = start_row + index
                        row_errors: list[str] = []
                        actual_id = _cell(ws_values, columns["student_id"], row).value
                        if str(actual_id).strip() != student["id"]:
                            row_errors.append(f"student ID mismatch: expected {student['id']}, got {actual_id}")
                        if _cell(ws_formula, columns["student_id"], row).number_format != "@":
                            row_errors.append("student ID is not text-formatted")
                        actual_name = _cell(ws_values, columns["student_name"], row).value
                        if str(actual_name).strip() != student["name"]:
                            row_errors.append(f"student name mismatch: expected {student['name']}, got {actual_name}")
                        regular_start = column_number(columns["regular_items_start"])
                        regular_end = column_number(columns["regular_items_end"])
                        regular_values = [_number(ws_values.cell(row, col).value, f"regular score {row}") for col in range(regular_start, regular_end + 1)]
                        if len(regular_values) != int(manifest["validation"]["regular_item_count"]):
                            row_errors.append("regular score count changed")
                        average = sum(regular_values) / len(regular_values)
                        if not math.isclose(average, float(student["regular"]), abs_tol=0.001):
                            row_errors.append(f"regular score average mismatch: expected {student['regular']}, got {average}")
                        for col in formula_columns:
                            formula = _cell(ws_formula, col, row).value
                            if not isinstance(formula, str) or not formula.startswith("=") or "#REF!" in formula or "#VALUE!" in formula:
                                row_errors.append(f"formula missing or broken in {col}{row}")
                        total_value = _cell(ws_values, total_column, row).value
                        if total_value is not None:
                            try:
                                if not math.isclose(_number(total_value, f"total {row}"), float(student["total"]), abs_tol=1.0):
                                    row_errors.append(f"total differs from source: expected {student['total']}, got {total_value}")
                            except ValueError as exc:
                                row_errors.append(str(exc))
                        if not skill_enabled:
                            for header_cell in ["O3", "P3", "O4", "P4"]:
                                if "技能成绩" in str(ws_values[header_cell].value or ""):
                                    row_errors.append("skill columns were not removed for zero skill weight")
                        else:
                            skill_value = _cell(ws_values, columns["skill_score"], row).value
                            if not math.isclose(_number(skill_value, f"skill score {row}"), float(student["skill"]), abs_tol=0.001):
                                row_errors.append(f"skill score mismatch: expected {student['skill']}, got {skill_value}")
                        if row_errors:
                            errors.extend(f"{path.name} row {row}: {message}" for message in row_errors)
                        student_checks.append({"row": row, "id": student["id"], "errors": row_errors, "regular_average": average})
                    report["checks"]["students"] = student_checks
                    report["checks"]["skill_enabled"] = skill_enabled
                    report["checks"]["formula_columns"] = formula_columns
        except Exception as exc:
            errors.append(f"Generated XLS could not be opened or inspected: {exc}")
    report["checks"]["file_count"] = {"expected": 1, "actual": len(files)}
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
    parser = argparse.ArgumentParser(description="Validate a generated XLS gradebook and write a QA report.")
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
    print(f"validated files={report['checks']['file_count']['actual']} students={len(report['checks'].get('students', []))} qa={report['qa_report']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
