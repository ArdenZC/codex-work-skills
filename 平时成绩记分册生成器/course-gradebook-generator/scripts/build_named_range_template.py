#!/usr/bin/env python3
"""Build the v1.1 .xls package from the protected v1.0 canonical template."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from openpyxl import load_workbook

from named_range_contracts import required_names
from named_range_utils import (
    compare_named_range_inventories,
    set_named_range,
    validate_named_range_inventory,
)
from package_common import V10_TEMPLATE, V11_PACKAGE_DIR, sha256_file
from validate_template import convert_to_format, find_soffice
from xls_named_range_utils import (
    compare_xls_and_xlsx_named_ranges,
    normalize_libreoffice_print_title_records,
    normalize_xls_summary_information,
    validate_xls_named_range_inventory,
)


def _workbook_layout_signature(workbook) -> dict[str, Any]:
    def cell_signature(cell) -> tuple[Any, ...]:
        return (cell.coordinate, cell.value, cell.data_type, cell.style_id, cell.number_format)

    return {
        "sheetnames": list(workbook.sheetnames),
        "states": {sheet.title: sheet.sheet_state for sheet in workbook.worksheets},
        "sheets": {
            sheet.title: {
                "cells": [
                    cell_signature(cell)
                    for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row, min_col=1, max_col=sheet.max_column)
                    for cell in row
                    if cell.value is not None or cell.has_style
                ],
                "merged": sorted(str(item).upper() for item in sheet.merged_cells.ranges),
                "column_dimensions": sorted(
                    (str(key), value.width, bool(value.hidden), int(value.outlineLevel), bool(value.collapsed))
                    for key, value in sheet.column_dimensions.items()
                ),
                "row_dimensions": sorted(
                    (str(key), value.height, bool(value.hidden), int(value.outlineLevel), bool(value.collapsed))
                    for key, value in sheet.row_dimensions.items()
                    if value.height is not None or value.hidden or value.outlineLevel or value.collapsed
                ),
                "page_setup": (
                    sheet.page_setup.orientation,
                    sheet.page_setup.paperSize,
                    sheet.page_setup.scale,
                    sheet.page_margins.left,
                    sheet.page_margins.right,
                    sheet.page_margins.top,
                    sheet.page_margins.bottom,
                    str(sheet.print_area or ""),
                    str(sheet.freeze_panes or ""),
                ),
                "protection": (
                    bool(sheet.protection.sheet),
                    bool(sheet.protection.formatCells),
                    bool(sheet.protection.formatColumns),
                    bool(sheet.protection.formatRows),
                    bool(sheet.protection.insertColumns),
                    bool(sheet.protection.insertRows),
                    bool(sheet.protection.deleteColumns),
                    bool(sheet.protection.deleteRows),
                ),
            }
            for sheet in workbook.worksheets
        },
    }


def _pdf_signature(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    if not payload:
        raise RuntimeError(f"LibreOffice created an empty PDF: {path}")
    return len(re.findall(rb"/Type\s*/Page(?:\s|/|>)", payload)), len(payload)


def _convert(soffice: str, source: Path, output_dir: Path, target: str) -> Path:
    return convert_to_format(source, output_dir, target, soffice)


def _build_named_workbook(source_xlsx: Path, target_xlsx: Path) -> None:
    workbook = load_workbook(source_xlsx, data_only=False)
    sheet_name = workbook.sheetnames[0]
    locations = {
        "gb_title": (1, 1, 1, 1),
        "gb_term": (2, 3, 2, 3),
        "gb_course": (2, 7, 2, 7),
        "gb_teacher": (2, 12, 2, 12),
        "gb_class_name": (2, 15, 2, 15),
        "gb_header_serial": (3, 1, 3, 1),
        "gb_header_student_id": (3, 2, 3, 2),
        "gb_header_student_name": (3, 3, 3, 3),
        "gb_header_regular": (3, 4, 3, 4),
        "gb_header_theory": (3, 13, 3, 13),
        "gb_header_skill": (3, 15, 3, 15),
        "gb_header_total": (3, 17, 3, 17),
        "gb_data_table": (5, 1, 52, 17),
        "gb_template_row": (5, 1, 5, 17),
        "gb_serial_col": (5, 1, 52, 1),
        "gb_student_id_col": (5, 2, 52, 2),
        "gb_student_name_col": (5, 3, 52, 3),
        "gb_regular_items": (5, 4, 52, 11),
        "gb_regular_weighted_col": (5, 12, 52, 12),
        "gb_theory_score_col": (5, 13, 52, 13),
        "gb_theory_weighted_col": (5, 14, 52, 14),
        "gb_skill_score_col": (5, 15, 52, 15),
        "gb_skill_weighted_col": (5, 16, 52, 16),
        "gb_total_score_col": (5, 17, 52, 17),
    }
    for name in required_names("with_skill"):
        min_row, min_col, max_row, max_col = locations[name]
        set_named_range(workbook, name, sheet_name, min_row, min_col, max_row, max_col)
    workbook.save(target_xlsx)


def _write_manifest(source_manifest: Path, target_manifest: Path, template_sha: str) -> None:
    manifest = yaml.safe_load(source_manifest.read_text(encoding="utf-8")) or {}
    manifest["fingerprint"]["sha256"] = template_sha
    manifest["fingerprint"]["value"] = template_sha
    target_manifest.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def build_template(source: Path, output_dir: Path, force: bool = False) -> dict[str, Any]:
    source = source.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source.exists():
        raise RuntimeError(f"Source template not found: {source}")
    if output_dir.exists() and not force:
        raise RuntimeError(f"Refusing to overwrite existing output package: {output_dir}; use --force explicitly")
    soffice = find_soffice()
    source_manifest = source.parent / "manifest.yaml"
    if not source_manifest.exists():
        source_manifest = source.parent.parent / "v1.1.0" / "manifest.yaml"
    with tempfile.TemporaryDirectory(prefix="gradebook-named-template-") as temp_name:
        temp = Path(temp_name)
        source_xlsx = _convert(soffice, source, temp / "source-xlsx", "xlsx")
        baseline_normalized = temp / "baseline-normalized.xlsx"
        load_workbook(source_xlsx, data_only=False).save(baseline_normalized)
        baseline_xls = _convert(soffice, baseline_normalized, temp / "baseline-xls", "xls")
        baseline_roundtrip_xlsx = _convert(soffice, baseline_xls, temp / "baseline-roundtrip-xlsx", "xlsx")

        named_xlsx = temp / "named-ranges.xlsx"
        _build_named_workbook(source_xlsx, named_xlsx)
        named_xls = _convert(soffice, named_xlsx, temp / "named-xls", "xls")
        normalize_libreoffice_print_title_records(named_xls)
        normalize_xls_summary_information(named_xls)
        named_roundtrip_xlsx = _convert(soffice, named_xls, temp / "named-roundtrip-xlsx", "xlsx")

        package_manifest = output_dir / "manifest.yaml"
        source_v11_manifest = V11_PACKAGE_DIR / "manifest.yaml"
        manifest_source = source_v11_manifest if source_v11_manifest.exists() else source_manifest
        manifest_data = yaml.safe_load(manifest_source.read_text(encoding="utf-8")) or {}
        xlsx_inventory = validate_named_range_inventory(
            load_workbook(named_roundtrip_xlsx, data_only=False),
            manifest_data["anchors"],
            "with_skill",
        )
        xls_inventory = validate_xls_named_range_inventory(named_xls, manifest_data["anchors"], "with_skill")
        if xlsx_inventory["errors"] or xls_inventory["errors"]:
            raise RuntimeError("Named range build failed: " + "; ".join(xlsx_inventory["errors"] + xls_inventory["errors"]))
        differences = compare_xls_and_xlsx_named_ranges(xls_inventory, xlsx_inventory, required_names("with_skill"))
        differences.extend(compare_named_range_inventories(xls_inventory, xlsx_inventory, required_names("with_skill")))
        if differences:
            raise RuntimeError("Raw XLS and round-trip XLSX named-range inventories differ: " + "; ".join(sorted(set(differences))))
        if _workbook_layout_signature(load_workbook(baseline_roundtrip_xlsx, data_only=False)) != _workbook_layout_signature(
            load_workbook(named_roundtrip_xlsx, data_only=False)
        ):
            raise RuntimeError("Named-range build changed protected workbook layout or formatting")

        baseline_pdf = _convert(soffice, baseline_xls, temp / "baseline-pdf", "pdf")
        named_pdf = _convert(soffice, named_xls, temp / "named-pdf", "pdf")
        if _pdf_signature(baseline_pdf) != _pdf_signature(named_pdf):
            raise RuntimeError(
                f"Named-range build changed PDF rendering: baseline={_pdf_signature(baseline_pdf)}, named={_pdf_signature(named_pdf)}"
            )

        stage = temp / "package"
        stage.mkdir()
        staged_template = stage / "template.xls"
        shutil.copy2(named_xls, staged_template)
        template_sha = sha256_file(staged_template)
        _write_manifest(manifest_source, stage / "manifest.yaml", template_sha)
        changelog = manifest_source.parent / "CHANGELOG.md"
        if changelog.exists():
            shutil.copy2(changelog, stage / "CHANGELOG.md")
        else:
            (stage / "CHANGELOG.md").write_text("# 1.1.0\n\n- Add workbook-level managed named ranges.\n", encoding="utf-8")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage), str(output_dir))
        return {
            "output": str(output_dir),
            "template_sha256": template_sha,
            "v10_template_sha256": sha256_file(source),
            "named_range_count": len(xls_inventory["locations"]),
            "pdf_signature": _pdf_signature(named_pdf),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the course-gradebook v1.1 named-range template package.")
    parser.add_argument("--source", default=str(V10_TEMPLATE))
    parser.add_argument("--output-dir", default=str(V11_PACKAGE_DIR))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = build_template(Path(args.source), Path(args.output_dir), args.force)
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
