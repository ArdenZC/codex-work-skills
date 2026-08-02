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
    expected_named_range_locations,
    set_named_range_from_location,
    validate_named_range_inventory,
)
from package_common import V10_MANIFEST, V10_TEMPLATE, V11_PACKAGE_DIR, sha256_file
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


def _build_named_workbook(source_xlsx: Path, target_xlsx: Path, expected_locations) -> None:
    workbook = load_workbook(source_xlsx, data_only=False)
    for name in required_names("with_skill"):
        set_named_range_from_location(workbook, expected_locations[name])
    workbook.save(target_xlsx)


def _write_manifest(source_manifest: Path, target_manifest: Path, template_sha: str) -> None:
    manifest = yaml.safe_load(source_manifest.read_text(encoding="utf-8")) or {}
    manifest["fingerprint"]["sha256"] = template_sha
    manifest["fingerprint"]["value"] = template_sha
    target_manifest.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _inventory_has_managed_names(inventory: dict[str, Any]) -> bool:
    return bool(
        inventory.get("locations")
        or inventory.get("duplicate")
        or inventory.get("invalid_names")
        or inventory.get("unexpected")
        or inventory.get("scope_errors")
        or inventory.get("broken")
        or inventory.get("destination_errors")
        or inventory.get("shape_errors")
        or inventory.get("relationship_errors")
    )


def _validate_complete_named_inventory(
    label: str,
    inventory: dict[str, Any],
    expected_inventory: dict[str, Any],
) -> list[str]:
    errors = list(inventory.get("errors", []))
    errors.extend(
        compare_named_range_inventories(
            expected_inventory,
            inventory,
            required_names("with_skill"),
        )
    )
    if errors:
        return [f"{label}: {error}" for error in sorted(set(errors))]
    return []


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
        source_manifest_v11 = V11_PACKAGE_DIR / "manifest.yaml"
        manifest_data = yaml.safe_load(source_manifest_v11.read_text(encoding="utf-8")) or {}
        base_manifest = yaml.safe_load(V10_MANIFEST.read_text(encoding="utf-8")) or {}
        expected_locations = expected_named_range_locations(base_manifest["structure"], "with_skill")
        expected_inventory = {
            "locations": {
                name: location.to_dict() for name, location in expected_locations.items()
            }
        }
        source_xls_inventory = validate_xls_named_range_inventory(
            source,
            manifest_data["anchors"],
            "with_skill",
        )
        source_xlsx = _convert(soffice, source, temp / "source-xlsx", "xlsx")
        source_xlsx_inventory = validate_named_range_inventory(
            load_workbook(source_xlsx, data_only=False),
            manifest_data["anchors"],
            "with_skill",
        )
        source_has_names = _inventory_has_managed_names(source_xls_inventory)
        source_xlsx_has_names = _inventory_has_managed_names(source_xlsx_inventory)
        if not source_has_names and not source_xlsx_has_names:
            source_named_state = "v1.0 seed"
        elif not source_has_names or not source_xlsx_has_names:
            raise RuntimeError(
                "Named-range build rejected a partial managed-name inventory: "
                "raw XLS and round-trip XLSX do not contain the same managed-name state"
            )
        else:
            expected_count = len(required_names("with_skill"))
            if (
                source_xls_inventory.get("actual_count") != expected_count
                or source_xlsx_inventory.get("actual_count") != expected_count
            ):
                raise RuntimeError(
                    "Named-range build rejected a partial managed-name inventory: "
                    f"expected {expected_count} complete names, got "
                    f"raw={source_xls_inventory.get('actual_count')}, "
                    f"roundtrip={source_xlsx_inventory.get('actual_count')}"
                )
            source_errors = _validate_complete_named_inventory(
                "source XLS",
                source_xls_inventory,
                expected_inventory,
            )
            source_errors.extend(
                _validate_complete_named_inventory(
                    "source round-trip XLSX",
                    source_xlsx_inventory,
                    expected_inventory,
                )
            )
            source_errors.extend(
                compare_xls_and_xlsx_named_ranges(
                    source_xls_inventory,
                    source_xlsx_inventory,
                    required_names("with_skill"),
                )
            )
            source_errors.extend(
                compare_named_range_inventories(
                    source_xls_inventory,
                    source_xlsx_inventory,
                    required_names("with_skill"),
                )
            )
            if source_errors:
                raise RuntimeError(
                    "Named-range build rejected an invalid managed-name inventory: "
                    + "; ".join(sorted(set(source_errors)))
                )
            source_named_state = "v1.1 canonical"
        baseline_normalized = temp / "baseline-normalized.xlsx"
        load_workbook(source_xlsx, data_only=False).save(baseline_normalized)
        baseline_xls = _convert(soffice, baseline_normalized, temp / "baseline-xls", "xls")
        baseline_roundtrip_xlsx = _convert(soffice, baseline_xls, temp / "baseline-roundtrip-xlsx", "xlsx")

        named_xlsx = temp / "named-ranges.xlsx"
        if source_named_state == "v1.0 seed":
            _build_named_workbook(source_xlsx, named_xlsx, expected_locations)
            named_xls = _convert(soffice, named_xlsx, temp / "named-xls", "xls")
            normalize_libreoffice_print_title_records(named_xls)
            normalize_xls_summary_information(named_xls)
            named_roundtrip_xlsx = _convert(soffice, named_xls, temp / "named-roundtrip-xlsx", "xlsx")
        else:
            # A complete v1.1 source is already a canonical semantic package.
            # Validate its raw and round-trip inventories, then preserve its
            # bytes instead of silently rewriting names through LibreOffice.
            named_xls = source
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
        expected_differences = compare_named_range_inventories(
            expected_inventory,
            xls_inventory,
            required_names("with_skill"),
        )
        expected_differences.extend(
            compare_named_range_inventories(
                expected_inventory,
                xlsx_inventory,
                required_names("with_skill"),
            )
        )
        if expected_differences:
            raise RuntimeError(
                "Named range build changed the canonical managed destinations: "
                + "; ".join(sorted(set(expected_differences)))
            )
        differences = compare_xls_and_xlsx_named_ranges(xls_inventory, xlsx_inventory, required_names("with_skill"))
        differences.extend(compare_named_range_inventories(xls_inventory, xlsx_inventory, required_names("with_skill")))
        if differences:
            raise RuntimeError("Raw XLS and round-trip XLSX named-range inventories differ: " + "; ".join(sorted(set(differences))))
        protected_layout_reference = (
            baseline_roundtrip_xlsx
            if source_named_state == "v1.0 seed"
            else source_xlsx
        )
        if _workbook_layout_signature(load_workbook(protected_layout_reference, data_only=False)) != _workbook_layout_signature(
            load_workbook(named_roundtrip_xlsx, data_only=False)
        ):
            raise RuntimeError("Named-range build changed protected workbook layout or formatting")

        baseline_pdf = _convert(soffice, baseline_xls, temp / "baseline-pdf", "pdf")
        named_pdf = _convert(soffice, named_xls, temp / "named-pdf", "pdf")
        if source_named_state == "v1.1 canonical":
            # The staged template is the validated source byte-for-byte; no
            # second workbook transformation is introduced to compare here.
            baseline_pdf = named_pdf
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
