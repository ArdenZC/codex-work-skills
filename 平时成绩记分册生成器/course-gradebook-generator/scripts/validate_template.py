from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from package_common import DEFAULT_MANIFEST, column_number, ensure_supported_major, load_manifest, manifest_template_path


class TemplateValidationError(RuntimeError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("; ".join(report.get("errors", [])) or "Template validation failed")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def find_soffice() -> str:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        shutil.which("soffice.com"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/libreoffice",
        "/usr/local/bin/libreoffice",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise RuntimeError("LibreOffice/soffice was not found; install LibreOffice or use Windows Excel COM for generation.")


def convert_to_xlsx(source: Path, out_dir: Path, soffice: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [soffice, "--headless", "--convert-to", "xlsx", "--outdir", str(out_dir), str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {proc.stdout}\n{proc.stderr}")
    target = out_dir / f"{source.stem}.xlsx"
    if target.exists():
        return target
    matches = sorted(out_dir.glob(f"{source.stem}.*"))
    if matches:
        return matches[0]
    raise RuntimeError(f"LibreOffice did not create an XLSX file for {source}")


def _workbook_signature(workbook, manifest: dict[str, Any]) -> dict[str, Any]:
    structure = manifest["structure"]
    sheet_name = structure["worksheet"]
    ws = workbook[sheet_name]
    label_cells = structure.get("header_label_cells", {})
    fixed_cells = ["A1", *structure.get("metadata", {}).values(), *label_cells.values()]
    header_row = int(structure.get("header_row", 4))
    fixed_cells.extend(f"{column}{header_row}" for column in ("A", "B", "C", "D", "L", "M", "N", "O", "P", "Q"))
    fixed_cells = list(dict.fromkeys(str(cell) for cell in fixed_cells))
    style_row = int(structure["style_source_row"])
    format_columns = [
        structure["columns"]["student_id"],
        structure["columns"]["regular_weighted"],
        structure["columns"]["theory_weighted"],
        structure["columns"]["skill_weighted"],
        structure["columns"]["total_score"],
    ]
    return {
        "sheetnames": list(workbook.sheetnames),
        "sheet_states": {sheet.title: sheet.sheet_state for sheet in workbook.worksheets},
        "dimension": [ws.max_row, ws.max_column],
        "merged": sorted(str(item).upper() for item in ws.merged_cells.ranges),
        "fixed_cells": {cell: ws[cell].value for cell in fixed_cells},
        "number_formats": {f"{column}{style_row}": ws[f"{column}{style_row}"].number_format for column in format_columns},
        "orientation": ws.page_setup.orientation,
        "print_area": str(ws.print_area or ""),
        "freeze_panes": str(ws.freeze_panes or ""),
        "named_ranges": sorted(str(name) for name in workbook.defined_names),
        "data_validations": len(ws.data_validations.dataValidation),
        "conditional_formats": len(ws.conditional_formatting),
        "column_widths": {key: value.width for key, value in ws.column_dimensions.items()},
        "row_heights": {str(key): value.height for key, value in ws.row_dimensions.items() if value.height is not None},
    }


def validate_template(
    template_path: Path | str,
    manifest_path: Path | str = DEFAULT_MANIFEST,
    compatibility_template: Path | str | None = None,
) -> dict[str, Any]:
    template = Path(template_path).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    errors: list[str] = []
    warnings: list[str] = []
    report: dict[str, Any] = {
        "template": str(template),
        "manifest": str(Path(manifest_path).expanduser().resolve()),
        "template_version": manifest.get("template", {}).get("version"),
        "errors": errors,
        "warnings": warnings,
        "checks": {},
    }
    try:
        ensure_supported_major(manifest)
    except ValueError as exc:
        errors.append(str(exc))
    if not template.exists():
        errors.append(f"Template not found: {template}")
        raise TemplateValidationError(report)

    expected_hash = str(manifest.get("fingerprint", {}).get("sha256") or manifest.get("fingerprint", {}).get("value", "")).upper()
    actual_hash = sha256(template)
    canonical = manifest_template_path(manifest)
    is_canonical = template == canonical
    report["checks"]["sha256"] = {"expected": expected_hash, "actual": actual_hash}
    if is_canonical and actual_hash != expected_hash:
        errors.append(f"Canonical template SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
    elif not is_canonical and actual_hash != expected_hash:
        warnings.append("Custom template fingerprint differs from the v1.0.0 canonical template.")

    if compatibility_template is None:
        entries = manifest.get("template", {}).get("compatibility_entries", [])
        if entries:
            compatibility_template = Path(manifest["_path"]).parent / entries[0]
    if compatibility_template:
        compat = Path(compatibility_template).expanduser().resolve()
        if compat.exists():
            compat_hash = sha256(compat)
            report["checks"]["compatibility_sha256"] = {"path": str(compat), "actual": compat_hash}
            if compat_hash != expected_hash:
                errors.append(f"Compatibility template diverges from canonical template: {compat}")
        else:
            warnings.append(f"Compatibility template entry is missing: {compat}")

    try:
        with tempfile.TemporaryDirectory(prefix="gradebook-template-") as temp_name:
            xlsx = template if template.suffix.lower() == ".xlsx" else convert_to_xlsx(template, Path(temp_name), find_soffice())
            workbook = load_workbook(xlsx, data_only=False)
            report["checks"]["workbook_open"] = True
            structure = manifest["structure"]
            sheet_name = structure["worksheet"]
            if sheet_name not in workbook.sheetnames:
                errors.append(f"Missing worksheet: {sheet_name}")
                raise TemplateValidationError(report)
            ws = workbook[sheet_name]
            expected_sheets = list(structure.get("required_sheets", []))
            if expected_sheets and workbook.sheetnames != expected_sheets:
                errors.append(f"Worksheet names changed: expected {expected_sheets}, got {workbook.sheetnames}")
            expected_states = {str(key): str(value) for key, value in structure.get("required_sheet_states", {}).items()}
            actual_states = {sheet.title: sheet.sheet_state for sheet in workbook.worksheets}
            if expected_states and actual_states != expected_states:
                errors.append(f"Worksheet visibility changed: expected {expected_states}, got {actual_states}")
            expected_last_row = int(structure["template_last_data_row"])
            if ws.max_row != expected_last_row:
                errors.append(f"Template row count mismatch: expected {expected_last_row}, got {ws.max_row}")
            expected_total_col = structure["columns"]["total_score"]
            expected_columns = column_number(structure["columns"]["total_score"])
            if ws.max_column != expected_columns:
                errors.append(f"Template column count mismatch: expected {expected_columns}, got {ws.max_column}")
            merged = set(str(item).upper() for item in ws.merged_cells.ranges)
            required_merged = set(str(item).upper() for item in structure.get("required_merged_ranges", []))
            if merged != required_merged:
                errors.append(f"Protected merged ranges changed: expected {sorted(required_merged)}, got {sorted(merged)}")
            required_headers = manifest["validation"]["required_headers"]
            label_cells = structure.get("header_label_cells", {"serial": "A3", "student_id": "B3", "student_name": "C3", "regular": "D3", "theory": "M3", "total": "Q3"})
            header_values = [ws[label_cells[key]].value for key in ("serial", "student_id", "student_name", "regular", "theory", "total")]
            for expected, actual in zip(required_headers, header_values):
                if str(expected) not in str(actual):
                    errors.append(f"Missing required header fragment {expected!r}; got {actual!r}")
            formula_columns = manifest["fields"].get("formula_columns_with_skill", {}).get("columns", ["L", "N", "P", "Q"])
            formula_row = int(structure["style_source_row"])
            for column in formula_columns:
                cell = f"{column}{formula_row}"
                if not isinstance(ws[cell].value, str) or not ws[cell].value.startswith("="):
                    errors.append(f"Expected formula in template cell {cell}")
            student_id_column = structure["columns"]["student_id"]
            student_id_cell = f"{student_id_column}{formula_row}"
            if ws[student_id_cell].number_format != "@":
                errors.append(f"Student ID cell {student_id_cell} must be text formatted, got {ws[student_id_cell].number_format!r}")
            expected_orientation = manifest["validation"].get("page_orientation", "landscape")
            if ws.page_setup.orientation != expected_orientation:
                errors.append(f"Template page orientation changed: {ws.page_setup.orientation}")
            expected_print_area = str(manifest["validation"].get("expected_print_area") or "")
            if str(ws.print_area or "") != expected_print_area:
                errors.append(f"Template print area changed: expected {expected_print_area!r}, got {str(ws.print_area or '')!r}")
            expected_freeze = str(manifest["validation"].get("expected_freeze_panes") or "")
            if str(ws.freeze_panes or "") != expected_freeze:
                errors.append(f"Template freeze panes changed: expected {expected_freeze!r}, got {str(ws.freeze_panes or '')!r}")
            expected_named_ranges = sorted(str(item) for item in manifest["validation"].get("required_named_ranges", []))
            actual_named_ranges = sorted(str(name) for name in workbook.defined_names)
            if actual_named_ranges != expected_named_ranges:
                errors.append(f"Named ranges changed: expected {expected_named_ranges}, got {actual_named_ranges}")
            expected_dv = int(manifest["validation"].get("required_data_validations", 0))
            actual_dv = len(ws.data_validations.dataValidation)
            if actual_dv != expected_dv:
                errors.append(f"Data validations changed: expected {expected_dv}, got {actual_dv}")
            expected_cf = int(manifest["validation"].get("required_conditional_formats", 0))
            actual_cf = len(ws.conditional_formatting)
            if actual_cf != expected_cf:
                errors.append(f"Conditional formats changed: expected {expected_cf}, got {actual_cf}")
            report["checks"]["structure"] = {
                "sheets": workbook.sheetnames,
                "rows": ws.max_row,
                "columns": ws.max_column,
                "merged_count": len(merged),
                "expected_total_column": expected_total_col,
            }
            if canonical.exists() and not is_canonical:
                canonical_xlsx = canonical
                with tempfile.TemporaryDirectory(prefix="gradebook-canonical-") as canonical_temp:
                    canonical_xlsx = convert_to_xlsx(canonical, Path(canonical_temp), find_soffice())
                    canonical_workbook = load_workbook(canonical_xlsx, data_only=False)
                    if _workbook_signature(canonical_workbook, manifest) != _workbook_signature(workbook, manifest):
                        errors.append("Custom template changed protected workbook structure or formatting.")
    except TemplateValidationError:
        raise
    except Exception as exc:
        errors.append(f"XLS template could not be opened or inspected: {exc}")

    if errors:
        raise TemplateValidationError(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the versioned XLS course-gradebook template package.")
    parser.add_argument("--template", default="")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--compatibility-template", default="")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    template = Path(args.template).expanduser().resolve() if args.template else manifest_template_path(manifest)
    try:
        report = validate_template(template, args.manifest, args.compatibility_template or None)
    except TemplateValidationError as exc:
        report = exc.report
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            for error in report.get("errors", []):
                print(f"ERROR: {error}", file=sys.stderr)
            for warning in report.get("warnings", []):
                print(f"WARNING: {warning}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"validated template={template} version={report['template_version']} sha256={report['checks']['sha256']['actual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
