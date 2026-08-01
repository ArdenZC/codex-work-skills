from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

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


_FONT_NAME_ALIASES = {
    "simsun": "simsun",
    "mssimsun": "simsun",
    "宋体": "simsun",
    "nsimsun": "nsimsun",
    "新宋体": "nsimsun",
    "simhei": "simhei",
    "黑体": "simhei",
    "microsoftyahei": "microsoftyahei",
    "microsoftyaheiui": "microsoftyahei",
    "微软雅黑": "microsoftyahei",
    "kaiti": "kaiti",
    "楷体": "kaiti",
    "fangsong": "fangsong",
    "仿宋": "fangsong",
    "dengxian": "dengxian",
    "等线": "dengxian",
}

_KNOWN_LIBREOFFICE_FALLBACK_NAMES = {
    "dejavusans",
    "dejavuserif",
    "liberationsans",
    "liberationserif",
}
_KNOWN_LIBREOFFICE_CJK_SOURCE_METADATA = (134, 0.0, None)
_KNOWN_LIBREOFFICE_FALLBACK_METADATA = {
    (None, 2.0, None),
    (None, 2, None),
}


def _font_name_signature(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    compact = re.sub(r"[\s_-]+", "", normalized)
    return _FONT_NAME_ALIASES.get(compact, compact)


def _font_metadata_signature(font) -> tuple[Any, ...]:
    return font.charset, font.family, font.scheme


def _font_signatures_match(left: tuple[Any, ...], right: tuple[Any, ...]) -> bool:
    """Compare the complete font identity, including the declared family name."""
    return len(left) == len(right) and left == right


def _cell_format_signatures_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if set(left) != set(right):
        return False
    for key in left:
        if key == "font":
            if not _font_signatures_match(left[key], right[key]):
                return False
        elif left[key] != right[key]:
            return False
    return True


def _cell_format_signature(cell) -> dict[str, Any]:
    def color_signature(color) -> tuple[Any, ...]:
        if color is None:
            return ()
        return (
            color.type,
            color.rgb,
            color.indexed,
            color.auto,
            color.theme,
            color.tint,
        )

    def side_signature(side) -> tuple[Any, ...]:
        if side is None:
            return ()
        return side.style, color_signature(side.color)

    font = cell.font
    fill = cell.fill
    border = cell.border
    alignment = cell.alignment
    protection = cell.protection
    font_name = _font_name_signature(font.name)
    font_charset, font_family, font_scheme = _font_metadata_signature(font)
    return {
        "number_format": cell.number_format,
        # Keep font identity while normalizing common locale-specific aliases from XLS round trips.
        "font": (
            font_name,
            font_charset,
            font_family,
            font_scheme,
            font.sz,
            bool(font.b),
            bool(font.i),
            font.u,
            bool(font.strike),
            bool(font.outline),
            bool(font.shadow),
            font.vertAlign,
            color_signature(font.color),
        ),
        "fill": (
            fill.patternType,
            color_signature(fill.fgColor),
            color_signature(fill.bgColor),
        ),
        "border": (
            border.outline,
            border.diagonalUp,
            border.diagonalDown,
            side_signature(border.left),
            side_signature(border.right),
            side_signature(border.top),
            side_signature(border.bottom),
            side_signature(border.diagonal),
            side_signature(border.start),
            side_signature(border.end),
        ),
        "alignment": (
            alignment.horizontal,
            alignment.vertical,
            alignment.textRotation,
            bool(alignment.wrapText),
            bool(alignment.shrinkToFit),
            alignment.indent or 0,
            alignment.relativeIndent or 0,
            alignment.justifyLastLine,
            alignment.readingOrder or 0,
        ),
        "protection": (bool(protection.locked), bool(protection.hidden)),
    }


def _dimension_signature(value: Any) -> float | None:
    if value is None:
        return None
    # LibreOffice can shift XLS column widths by hundredths during a round trip.
    return round(float(value), 1)


def _page_setup_value(value: Any) -> Any:
    if isinstance(value, float):
        # LibreOffice can introduce a few-millionths drift in inch-based margins.
        return round(value, 4)
    return value


def _protection_signature(protection) -> dict[str, Any]:
    signature: dict[str, Any] = {}
    for name in getattr(protection, "__attrs__", ()):
        value = getattr(protection, name, None)
        if any(token in name.lower() for token in ("password", "hash", "salt")):
            present = value not in (None, "")
            signature[name] = {
                "present": present,
                "digest": hashlib.sha256(str(value).encode("utf-8")).hexdigest() if present else "",
            }
        else:
            signature[name] = value
    return signature


def _header_footer_item_signature(item) -> dict[str, dict[str, Any]]:
    return {
        side: {
            name: getattr(getattr(item, side, None), name, None)
            for name in ("text", "size", "font", "color")
        }
        for side in ("left", "center", "right")
    }


def _header_footer_signature(sheet) -> dict[str, Any]:
    header_footer = sheet.HeaderFooter
    return {
        "flags": {
            name: getattr(header_footer, name, None)
            for name in ("differentOddEven", "differentFirst", "scaleWithDoc", "alignWithMargins")
        },
        "odd_header": _header_footer_item_signature(header_footer.oddHeader),
        "odd_footer": _header_footer_item_signature(header_footer.oddFooter),
        "even_header": _header_footer_item_signature(header_footer.evenHeader),
        "even_footer": _header_footer_item_signature(header_footer.evenFooter),
        "first_header": _header_footer_item_signature(header_footer.firstHeader),
        "first_footer": _header_footer_item_signature(header_footer.firstFooter),
    }


def _page_setup_signature(sheet) -> dict[str, Any]:
    page_setup = sheet.page_setup
    margins = sheet.page_margins
    print_options = sheet.print_options
    page_setup_properties = sheet.sheet_properties.pageSetUpPr
    return {
        "page_setup": {
            name: _page_setup_value(getattr(page_setup, name, None))
            for name in (
                "orientation",
                "paperSize",
                "scale",
                "fitToHeight",
                "fitToWidth",
                "firstPageNumber",
                "useFirstPageNumber",
                "paperHeight",
                "paperWidth",
                "pageOrder",
                "usePrinterDefaults",
                "blackAndWhite",
                "draft",
                "cellComments",
                "errors",
                "horizontalDpi",
                "verticalDpi",
                "copies",
                "autoPageBreaks",
                "fitToPage",
            )
        },
        "margins": {
            name: _page_setup_value(getattr(margins, name, None))
            for name in ("left", "right", "top", "bottom", "header", "footer")
        },
        "print_options": {
            name: getattr(print_options, name, None)
            for name in ("horizontalCentered", "verticalCentered", "headings", "gridLines", "gridLinesSet")
        },
        "page_setup_properties": {
            "fitToPage": getattr(page_setup_properties, "fitToPage", None) if page_setup_properties else None,
            "autoPageBreaks": getattr(page_setup_properties, "autoPageBreaks", None) if page_setup_properties else None,
        },
        "print_title_rows": str(sheet.print_title_rows or ""),
        "print_title_cols": str(sheet.print_title_cols or ""),
        "header_footer": _header_footer_signature(sheet),
    }


def _non_target_dimension_signature(value: Any) -> float | None:
    if value is None:
        return None
    # LibreOffice can shift compatibility-sheet dimensions by fractional units during an XLS round trip.
    return round(float(value))


def _non_target_sheet_signature(sheet) -> dict[str, Any]:
    max_row = sheet.max_row
    max_column = sheet.max_column
    cells = []
    for row in sheet.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_column):
        cells.append(
            [
                {
                    "value": cell.value,
                    "data_type": cell.data_type,
                    "format": _cell_format_signature(cell),
                }
                for cell in row
            ]
        )
    return {
        "dimension": [max_row, max_column],
        "cells": cells,
        "merged": sorted(str(item).upper() for item in sheet.merged_cells.ranges),
        "column_widths": {
            key: {
                "width": _non_target_dimension_signature(value.width),
                "hidden": bool(value.hidden),
                "outline_level": value.outlineLevel,
                "collapsed": bool(value.collapsed),
            }
            for key, value in sheet.column_dimensions.items()
        },
        "row_heights": {
            str(key): {
                "height": _non_target_dimension_signature(value.height),
                "hidden": bool(value.hidden),
                "outline_level": value.outlineLevel,
                "collapsed": bool(value.collapsed),
            }
            for key, value in sheet.row_dimensions.items()
            if value.height is not None or value.hidden or value.outlineLevel or value.collapsed
        },
        "orientation": sheet.page_setup.orientation,
        "print_area": str(sheet.print_area or ""),
        "freeze_panes": str(sheet.freeze_panes or ""),
        "page_setup": _page_setup_signature(sheet),
        "protection": _protection_signature(sheet.protection),
    }


def _target_cell_format_signature(sheet) -> dict[str, dict[str, Any]]:
    return {
        cell.coordinate: _cell_format_signature(cell)
        for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column)
        for cell in row
    }


def _protected_target_values(sheet, manifest: dict[str, Any]) -> dict[str, Any]:
    structure = manifest["structure"]
    writable_cells = {
        str(cell).upper()
        for cell in [*structure.get("metadata", {}).values(), *structure.get("headers", {}).values()]
        if cell
    }
    data_start_row = int(structure["data_start_row"])
    total_column = column_number(structure["columns"]["total_score"])
    return {
        f"{get_column_letter(column)}{row}": sheet.cell(row, column).value
        for row in range(1, data_start_row)
        for column in range(1, total_column + 1)
        if f"{get_column_letter(column)}{row}" not in writable_cells
    }


def _signature_differences(
    left: Any,
    right: Any,
    path: str = "",
    font_matcher=None,
) -> list[dict[str, Any]]:
    differences: list[dict[str, Any]] = []
    if path.endswith(".font") and isinstance(left, tuple) and isinstance(right, tuple):
        if not _font_signatures_match(left, right) and not (
            font_matcher is not None and font_matcher(left, right, path)
        ):
            differences.append({"path": path, "expected": left, "actual": right})
    elif isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right), key=str):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left:
                differences.append({"path": child_path, "expected": "<missing>", "actual": right[key]})
            elif key not in right:
                differences.append({"path": child_path, "expected": left[key], "actual": "<missing>"})
            else:
                differences.extend(_signature_differences(left[key], right[key], child_path, font_matcher))
    elif isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            differences.append({"path": path, "expected": left, "actual": right})
        else:
            for index, (expected, actual) in enumerate(zip(left, right)):
                differences.extend(
                    _signature_differences(expected, actual, f"{path}[{index}]", font_matcher)
                )
    elif left != right:
        differences.append({"path": path, "expected": left, "actual": right})
    return differences


def _conversion_font_fallback_is_proven(
    expected: tuple[Any, ...],
    actual: tuple[Any, ...],
) -> bool:
    """Recognize only the observed SimSun to LibreOffice fallback conversion."""
    if _font_name_signature(expected[0]) != "simsun":
        return False
    if _font_name_signature(actual[0]) not in _KNOWN_LIBREOFFICE_FALLBACK_NAMES:
        return False
    if tuple(expected[1:4]) != _KNOWN_LIBREOFFICE_CJK_SOURCE_METADATA:
        return False
    if tuple(actual[1:4]) not in _KNOWN_LIBREOFFICE_FALLBACK_METADATA:
        return False
    return len(expected) == len(actual) and expected[4:] == actual[4:]


def _custom_font_fallback_is_proven(
    expected: tuple[Any, ...],
    actual: tuple[Any, ...],
    path: str,
    manifest: dict[str, Any],
    source_suffix: str,
) -> bool:
    """Allow conversion drift only for editable metadata in a real XLS round trip."""
    if source_suffix.lower() != ".xls" or not _conversion_font_fallback_is_proven(expected, actual):
        return False
    match = re.search(r"\.([A-Z]+\d+)\.font$", path, flags=re.IGNORECASE)
    if match is None:
        return False
    writable_cells = {
        str(cell).upper()
        for cell in manifest.get("structure", {}).get("metadata", {}).values()
        if cell
    }
    return match.group(1).upper() in writable_cells


def _workbook_signature(workbook, manifest: dict[str, Any]) -> dict[str, Any]:
    structure = manifest["structure"]
    sheet_name = structure["worksheet"]
    ws = workbook[sheet_name]
    label_cells = structure.get("header_label_cells", {})
    writable_cells = {
        str(cell)
        for cell in [
            *structure.get("metadata", {}).values(),
            *structure.get("headers", {}).values(),
        ]
        if cell
    }
    fixed_cells = [structure.get("title_cell"), *label_cells.values()]
    fixed_cells = [cell for cell in fixed_cells if cell and str(cell) not in writable_cells]
    header_row = int(structure.get("header_row", 4))
    fixed_columns = {str(column).upper() for column in structure.get("columns", {}).values() if column}
    for field_name in ("formula_columns_with_skill", "formula_columns_without_skill"):
        fixed_columns.update(
            str(column).upper()
            for column in manifest.get("fields", {}).get(field_name, {}).get("columns", [])
        )
    fixed_cells.extend(f"{column}{header_row}" for column in sorted(fixed_columns))
    regular_start = column_number(structure["columns"]["regular_items_start"])
    regular_end = column_number(structure["columns"]["regular_items_end"])
    fixed_cells.extend(
        f"{get_column_letter(column)}{header_row}"
        for column in range(regular_start, regular_end + 1)
    )
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
        "non_target_sheets": {
            sheet.title: _non_target_sheet_signature(sheet)
            for sheet in workbook.worksheets
            if sheet.title != sheet_name
        },
        "dimension": [ws.max_row, ws.max_column],
        "merged": sorted(str(item).upper() for item in ws.merged_cells.ranges),
        "page_setup": _page_setup_signature(ws),
        "worksheet_protection": _protection_signature(ws.protection),
        "workbook_protection": _protection_signature(workbook.security),
        "fixed_cells": {cell: ws[cell].value for cell in fixed_cells},
        "protected_values": _protected_target_values(ws, manifest),
        "target_cell_formats": _target_cell_format_signature(ws),
        "writable_cell_formats": {
            cell: _cell_format_signature(ws[cell]) for cell in sorted(writable_cells)
        },
        "number_formats": {f"{column}{style_row}": ws[f"{column}{style_row}"].number_format for column in format_columns},
        "orientation": ws.page_setup.orientation,
        "print_area": str(ws.print_area or ""),
        "freeze_panes": str(ws.freeze_panes or ""),
        "named_ranges": sorted(str(name) for name in workbook.defined_names),
        "data_validations": len(ws.data_validations.dataValidation),
        "conditional_formats": len(ws.conditional_formatting),
        "column_widths": {key: _dimension_signature(value.width) for key, value in ws.column_dimensions.items()},
        "row_heights": {
            str(key): _dimension_signature(value.height)
            for key, value in ws.row_dimensions.items()
            if value.height is not None
        },
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
    if not is_canonical and not canonical.exists():
        errors.append(f"Canonical template not found: {canonical}")
    report["checks"]["sha256"] = {"expected": expected_hash, "actual": actual_hash}
    if is_canonical and actual_hash != expected_hash:
        errors.append(f"Canonical template SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
    elif not is_canonical and actual_hash != expected_hash:
        warnings.append(
            f"Custom template fingerprint differs from the {manifest.get('template', {}).get('version')} canonical template."
        )

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
                expected_text = str(expected)
                if not is_canonical and "(" in expected_text and expected_text.endswith(")"):
                    expected_text = expected_text.split("(", 1)[0]
                if expected_text not in str(actual):
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
                    canonical_signature = _workbook_signature(canonical_workbook, manifest)
                    custom_signature = _workbook_signature(workbook, manifest)
                    differences = _signature_differences(
                        canonical_signature,
                        custom_signature,
                        font_matcher=lambda expected, actual, path: _custom_font_fallback_is_proven(
                            expected,
                            actual,
                            path,
                            manifest,
                            template.suffix,
                        ),
                    )
                    if differences:
                        report["checks"]["protected_signature_differences"] = differences[:20]
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
    try:
        manifest = load_manifest(args.manifest)
        template = Path(args.template).expanduser().resolve() if args.template else manifest_template_path(manifest)
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
    except Exception as exc:
        report = {
            "template": str(Path(args.template).expanduser().resolve()) if args.template else "",
            "manifest": str(Path(args.manifest).expanduser().resolve()),
            "template_version": None,
            "errors": [str(exc)],
            "warnings": [],
            "checks": {},
        }
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"validated template={template} version={report['template_version']} sha256={report['checks']['sha256']['actual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
