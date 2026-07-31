from __future__ import annotations

import argparse
import json
import math
import re
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


def _formula_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".") or "0"


def _normalize_formula(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper().replace("$", "")


def _contains_formula_error(value: Any) -> bool:
    return isinstance(value, str) and any(
        token in value.upper() for token in ("#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A")
    )


def _excel_round(value: float) -> int:
    return math.floor(value + 0.5)


def _expected_formulas(
    row: int,
    weights: dict[str, Any],
    columns: dict[str, str],
    skill_enabled: bool,
    total_column: str,
) -> dict[str, str]:
    regular = _formula_number(float(weights["regular"]))
    theory = _formula_number(float(weights["theory"]))
    skill = _formula_number(float(weights["skill"]))
    average = f"AVERAGE({columns['regular_items_start']}{row}:{columns['regular_items_end']}{row})"
    expected = {
        columns["regular_weighted"]: f"={average}*{regular}",
        columns["theory_weighted"]: f"={columns['theory_score']}{row}*{theory}",
    }
    total = f"=ROUND({average}*{regular}+{columns['theory_score']}{row}*{theory}"
    if skill_enabled:
        expected[columns["skill_weighted"]] = f"={columns['skill_score']}{row}*{skill}"
        total += f"+{columns['skill_score']}{row}*{skill}"
    expected[total_column] = total + ",0)"
    return expected


def _row_has_content(ws, row: int, max_col: int) -> bool:
    return any(ws.cell(row, col).value not in (None, "") for col in range(1, max_col + 1))


def _check_workbook_protection(
    ws,
    workbook,
    manifest: dict[str, Any],
    skill_enabled: bool,
    errors: list[str],
) -> dict[str, Any]:
    structure = manifest["structure"]
    validation = manifest["validation"]
    expected_sheets = list(structure.get("required_sheets", []))
    if expected_sheets and workbook.sheetnames != expected_sheets:
        errors.append(f"Worksheet names changed: expected {expected_sheets}, got {workbook.sheetnames}")
    expected_states = {str(key): str(value) for key, value in structure.get("required_sheet_states", {}).items()}
    actual_states = {sheet.title: sheet.sheet_state for sheet in workbook.worksheets}
    if expected_states and actual_states != expected_states:
        errors.append(f"Worksheet visibility changed: expected {expected_states}, got {actual_states}")
    expected_merged_key = "required_merged_ranges" if skill_enabled else "required_merged_ranges_without_skill"
    expected_merged = sorted(str(item).upper() for item in structure.get(expected_merged_key, []))
    actual_merged = sorted(str(item).upper() for item in ws.merged_cells.ranges)
    if expected_merged != actual_merged:
        errors.append(f"Output merged ranges changed: expected {expected_merged}, got {actual_merged}")
    expected_columns = column_number(
        structure["columns"]["total_score"] if skill_enabled else structure["no_skill_total_column"]
    )
    if ws.max_column != expected_columns:
        errors.append(f"Output column count changed: expected {expected_columns}, got {ws.max_column}")
    if ws.page_setup.orientation != validation.get("page_orientation", "landscape"):
        errors.append(f"Output page orientation changed: {ws.page_setup.orientation}")
    expected_print_area = str(validation.get("expected_print_area") or "")
    if "expected_print_area" in validation and str(ws.print_area or "") != expected_print_area:
        errors.append(f"Output print area changed: expected {expected_print_area!r}, got {str(ws.print_area or '')!r}")
    expected_freeze = str(validation.get("expected_freeze_panes") or "")
    if "expected_freeze_panes" in validation and str(ws.freeze_panes or "") != expected_freeze:
        errors.append(f"Output freeze panes changed: expected {expected_freeze!r}, got {str(ws.freeze_panes or '')!r}")
    expected_named_ranges = sorted(str(item) for item in validation.get("required_named_ranges", []))
    actual_named_ranges = sorted(str(name) for name in workbook.defined_names)
    if actual_named_ranges != expected_named_ranges:
        errors.append(f"Output named ranges changed: expected {expected_named_ranges}, got {actual_named_ranges}")
    expected_dv = int(validation.get("required_data_validations", 0))
    actual_dv = len(ws.data_validations.dataValidation)
    if actual_dv != expected_dv:
        errors.append(f"Output data validations changed: expected {expected_dv}, got {actual_dv}")
    expected_cf = int(validation.get("required_conditional_formats", 0))
    actual_cf = len(ws.conditional_formatting)
    if actual_cf != expected_cf:
        errors.append(f"Output conditional formats changed: expected {expected_cf}, got {actual_cf}")
    return {
        "sheets": workbook.sheetnames,
        "sheet_states": actual_states,
        "rows": ws.max_row,
        "columns": ws.max_column,
        "merged_ranges": actual_merged,
        "orientation": ws.page_setup.orientation,
        "print_area": str(ws.print_area or ""),
        "freeze_panes": str(ws.freeze_panes or ""),
        "named_ranges": actual_named_ranges,
        "data_validations": actual_dv,
        "conditional_formats": actual_cf,
    }


def _scan_formula_errors(formula_workbook, value_workbook) -> list[str]:
    errors: list[str] = []
    for sheet in formula_workbook.worksheets:
        value_sheet = value_workbook[sheet.title] if sheet.title in value_workbook.sheetnames else None
        for row in sheet.iter_rows():
            for cell in row:
                if _contains_formula_error(cell.value):
                    errors.append(f"{sheet.title}!{cell.coordinate} contains a formula error: {cell.value}")
                if value_sheet is not None and _contains_formula_error(value_sheet[cell.coordinate].value):
                    errors.append(f"{sheet.title}!{cell.coordinate} has a cached formula error: {value_sheet[cell.coordinate].value}")
    return errors


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
        "template_sha256": manifest.get("fingerprint", {}).get("sha256") or manifest.get("fingerprint", {}).get("value"),
        "output_dir": str(out_dir),
        "errors": errors,
        "warnings": warnings,
        "checks": {},
        "files_checked": 0,
    }
    if len(files) != 1:
        errors.append(f"Expected one generated XLS file, got {len(files)}")
    if files:
        path = files[0]
        structure = manifest["structure"]
        columns = structure["columns"]
        start_row = int(structure["data_start_row"])
        skill_enabled = float(data["weights"]["skill"]) > 0.000001
        total_column = columns["total_score"] if skill_enabled else structure["no_skill_total_column"]
        formula_columns = (
            manifest["fields"]["formula_columns_with_skill"]["columns"]
            if skill_enabled
            else manifest["fields"]["formula_columns_without_skill"]["columns"]
        )
        try:
            if path.stat().st_size == 0:
                raise RuntimeError("Generated XLS file is empty")
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
                    report["checks"]["structure"] = _check_workbook_protection(
                        ws_formula, formulas, manifest, skill_enabled, errors
                    )
                    errors.extend(_scan_formula_errors(formulas, values))

                    expected_headers = {
                        "regular": f"平时成绩({round(float(data['weights']['regular']) * 100)}%)",
                        "theory": f"理论成绩({round(float(data['weights']['theory']) * 100)}%)",
                        "total": "总评\n成绩",
                    }
                    header_cells = structure["headers"]
                    for name in ("regular", "theory"):
                        actual = str(ws_values[header_cells[name]].value or "").replace("\r\n", "\n")
                        if actual != expected_headers[name]:
                            errors.append(f"{name} header mismatch: expected {expected_headers[name]!r}, got {actual!r}")
                    total_header = columns["total_score"] if skill_enabled else structure["no_skill_total_column"]
                    actual_total_header = str(ws_values[f"{total_header}3"].value or "").replace("\r\n", "\n")
                    if actual_total_header != expected_headers["total"]:
                        errors.append(f"total header mismatch: expected {expected_headers['total']!r}, got {actual_total_header!r}")
                    if skill_enabled:
                        skill_header = str(ws_values[header_cells["skill"]].value or "").replace("\r\n", "\n")
                        expected_skill_header = f"技能成绩（{round(float(data['weights']['skill']) * 100)}%）"
                        if skill_header != expected_skill_header:
                            errors.append(f"skill header mismatch: expected {expected_skill_header!r}, got {skill_header!r}")
                    else:
                        for cell in ("O3", "P3", "Q3", "O4", "P4", "Q4"):
                            if "技能成绩" in str(ws_values[cell].value or ""):
                                errors.append(f"skill header remains after zero-skill column removal: {cell}")

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

                    expected_last_row = start_row + len(data["students"]) - 1
                    if ws_values.max_row < expected_last_row:
                        errors.append(f"Output student rows are short: expected through row {expected_last_row}, got {ws_values.max_row}")
                    output_max_col = column_number(total_column)
                    for extra_row in range(expected_last_row + 1, max(ws_values.max_row, expected_last_row) + 1):
                        if _row_has_content(ws_values, extra_row, output_max_col):
                            errors.append(f"Unexpected non-empty student row after expected data: {extra_row}")

                    student_checks = []
                    regular_start = column_number(columns["regular_items_start"])
                    regular_end = column_number(columns["regular_items_end"])
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

                        regular_values = [
                            _number(ws_values.cell(row, col).value, f"regular score {row}")
                            for col in range(regular_start, regular_end + 1)
                        ]
                        if len(regular_values) != int(manifest["validation"]["regular_item_count"]):
                            row_errors.append("regular score count changed")
                        for score in regular_values:
                            if not 0 <= score <= 100 or not math.isclose(score * 2, round(score * 2), abs_tol=0.000001):
                                row_errors.append(f"regular score is outside 0..100 or not a half-point: {score}")
                        average = sum(regular_values) / len(regular_values)
                        if not math.isclose(average, float(student["regular"]), abs_tol=0.001):
                            row_errors.append(f"regular score average mismatch: expected {student['regular']}, got {average}")

                        theory_value = _number(_cell(ws_values, columns["theory_score"], row).value, f"theory score {row}")
                        if not 0 <= theory_value <= 100:
                            row_errors.append(f"theory score outside 0..100: {theory_value}")
                        expected_formulas = _expected_formulas(row, data["weights"], columns, skill_enabled, total_column)
                        for col in formula_columns:
                            formula = _cell(ws_formula, col, row).value
                            expected_formula = expected_formulas.get(col)
                            if not isinstance(formula, str) or not formula.startswith("=") or _contains_formula_error(formula):
                                row_errors.append(f"formula missing or broken in {col}{row}")
                            elif expected_formula and _normalize_formula(formula) != _normalize_formula(expected_formula):
                                row_errors.append(f"formula mismatch in {col}{row}: expected {expected_formula}, got {formula}")
                            cached_formula_value = _cell(ws_values, col, row).value
                            if cached_formula_value is None or _contains_formula_error(cached_formula_value):
                                row_errors.append(f"formula result missing or broken in {col}{row}")

                        try:
                            total_number = _number(_cell(ws_values, total_column, row).value, f"total {row}")
                            expected_calculated_total = float(student["regular"]) * float(data["weights"]["regular"])
                            expected_calculated_total += theory_value * float(data["weights"]["theory"])
                            skill_value = 0.0
                            if skill_enabled:
                                skill_value = _number(_cell(ws_values, columns["skill_score"], row).value, f"skill score {row}")
                                if not 0 <= skill_value <= 100:
                                    row_errors.append(f"skill score outside 0..100: {skill_value}")
                                if not math.isclose(skill_value, float(student["skill"]), abs_tol=0.001):
                                    row_errors.append(f"skill score mismatch: expected {student['skill']}, got {skill_value}")
                                expected_calculated_total += skill_value * float(data["weights"]["skill"])
                            if total_number != _excel_round(expected_calculated_total):
                                row_errors.append(f"total formula result mismatch: expected {_excel_round(expected_calculated_total)}, got {total_number}")
                            if not math.isclose(total_number, float(student["total"]), abs_tol=1.0):
                                row_errors.append(f"total differs from source: expected {student['total']}, got {total_number}")
                        except ValueError as exc:
                            row_errors.append(str(exc))

                        if row_errors:
                            errors.extend(f"{path.name} row {row}: {message}" for message in row_errors)
                        student_checks.append({"row": row, "id": student["id"], "errors": row_errors, "regular_average": average})
                    report["checks"]["students"] = student_checks
                    report["checks"]["skill_enabled"] = skill_enabled
                    report["checks"]["formula_columns"] = formula_columns
        except Exception as exc:
            errors.append(f"Generated XLS could not be opened or inspected: {exc}")
    report["checks"]["file_count"] = {"expected": 1, "actual": len(files)}
    report["files_checked"] = len(files)
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
