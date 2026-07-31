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

from package_common import DEFAULT_MANIFEST, ensure_supported_major, load_manifest, manifest_template_path


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
    fixed_cells = [
        "A1", "A3", "B3", "C3", "D3", "M3", "O3", "Q3", "D4", "L4", "M4", "N4", "O4", "P4", "Q4",
    ]
    return {
        "sheetnames": list(workbook.sheetnames),
        "dimension": [ws.max_row, ws.max_column],
        "merged": sorted(str(item).upper() for item in ws.merged_cells.ranges),
        "fixed_cells": {cell: ws[cell].value for cell in fixed_cells},
        "number_formats": {cell: ws[cell].number_format for cell in ["B5", "L5", "Q5"]},
        "orientation": ws.page_setup.orientation,
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

    expected_hash = str(manifest.get("fingerprint", {}).get("sha256", "")).upper()
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
            expected_last_row = int(structure["template_last_data_row"])
            if ws.max_row != expected_last_row:
                errors.append(f"Template row count mismatch: expected {expected_last_row}, got {ws.max_row}")
            expected_total_col = structure["columns"]["total_score"]
            if ws.max_column != 17:
                errors.append(f"Template column count mismatch: expected 17, got {ws.max_column}")
            merged = set(str(item).upper() for item in ws.merged_cells.ranges)
            required_merged = set(str(item).upper() for item in structure.get("required_merged_ranges", []))
            if not required_merged.issubset(merged):
                errors.append(f"Missing protected merged ranges: {sorted(required_merged - merged)}")
            required_headers = manifest["validation"]["required_headers"]
            header_values = [ws["A3"].value, ws["B3"].value, ws["C3"].value, ws["D3"].value, ws["M3"].value, ws["Q3"].value]
            for expected, actual in zip(required_headers, header_values):
                if str(expected) not in str(actual):
                    errors.append(f"Missing required header fragment {expected!r}; got {actual!r}")
            for cell in ["L5", "N5", "P5", "Q5"]:
                if not isinstance(ws[cell].value, str) or not ws[cell].value.startswith("="):
                    errors.append(f"Expected formula in template cell {cell}")
            if ws["B5"].number_format != "@":
                errors.append(f"Student ID cell B5 must be text formatted, got {ws['B5'].number_format!r}")
            if ws.page_setup.orientation != "landscape":
                errors.append(f"Template page orientation changed: {ws.page_setup.orientation}")
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
