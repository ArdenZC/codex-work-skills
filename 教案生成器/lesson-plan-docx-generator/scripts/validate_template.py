from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from docx import Document
from docx.oxml.ns import qn
from docx.table import _Cell
from lxml import etree

from package_common import DEFAULT_MANIFEST, ensure_supported_major, field_spec, load_manifest, manifest_template_path


class TemplateValidationError(RuntimeError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        message = "; ".join(report.get("errors", [])) or "Template validation failed"
        super().__init__(message)


def actual_cells(row) -> list[_Cell]:
    return [_Cell(tc, row._parent) for tc in row._tr.tc_lst]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _xml_without_text(element) -> str:
    cloned = copy.deepcopy(element)
    for node in cloned.iter():
        if node.tag in {qn("w:t"), qn("w:instrText"), qn("w:delText")}:
            node.text = ""
    return etree.tostring(cloned, encoding="unicode")


def _clear_text_nodes(element) -> None:
    for node in element.iter():
        if node.tag in {qn("w:t"), qn("w:instrText"), qn("w:delText")}:
            node.text = ""


def _cell_signature(cell, writable: bool = False, evaluation: bool = False) -> str:
    cloned = copy.deepcopy(cell._tc)
    if writable:
        _clear_text_nodes(cloned)
    elif evaluation:
        for nested_table in cloned.iter(qn("w:tbl")):
            rows = [child for child in nested_table if child.tag == qn("w:tr")]
            for row_index, row in enumerate(rows):
                if row_index == 0:
                    continue
                nested_cells = [child for child in row if child.tag == qn("w:tc")]
                for cell_index in (2, 3):
                    if cell_index < len(nested_cells):
                        _clear_text_nodes(nested_cells[cell_index])
    return etree.tostring(cloned, encoding="unicode")


def _writable_main_table_cells(manifest: dict[str, Any]) -> tuple[set[tuple[int, int]], tuple[int, int] | None]:
    writable: set[tuple[int, int]] = set()
    evaluation: tuple[int, int] | None = None
    for spec in manifest.get("fields", {}).values():
        if spec.get("mode") == "row_cells":
            writable.update(
                (int(row), int(cell))
                for row in spec.get("rows", [])
                for cell in spec.get("cells", [])
            )
            continue
        if spec.get("mode") == "nested_table":
            if int(spec.get("table", -1)) == 0:
                evaluation = (int(spec["row"]), int(spec["cell"]))
            continue
        if int(spec.get("table", -1)) == 0 and "row" in spec and "cell" in spec:
            writable.add((int(spec["row"]), int(spec["cell"])))
    return writable, evaluation


def _styles_signature(document) -> str:
    return etree.tostring(copy.deepcopy(document.styles._element), encoding="unicode")


def _main_table_signature(document, manifest: dict[str, Any]) -> dict[str, Any]:
    table = document.tables[int(manifest["structure"]["main_table"]["index"])]
    writable_cells, evaluation_cell = _writable_main_table_cells(manifest)
    rows = []
    for row_index, row in enumerate(table.rows):
        cells = []
        for cell_index, cell in enumerate(actual_cells(row)):
            cells.append(
                _cell_signature(
                    cell,
                    writable=(row_index, cell_index) in writable_cells,
                    evaluation=evaluation_cell == (row_index, cell_index),
                )
            )
        rows.append({"tr": _xml_without_text(row._tr), "cells": cells})
    return {
        "table": _xml_without_text(table._tbl),
        "rows": rows,
        "row_count": len(table.rows),
        "column_count": len(table.columns),
        "styles": _styles_signature(document),
    }


def _section_signature(document) -> list[dict[str, Any]]:
    result = []
    for section in document.sections:
        result.append(
            {
                "page_width": section.page_width.twips,
                "page_height": section.page_height.twips,
                "top_margin": section.top_margin.twips,
                "bottom_margin": section.bottom_margin.twips,
                "left_margin": section.left_margin.twips,
                "right_margin": section.right_margin.twips,
                "header": [p.text for p in section.header.paragraphs],
                "footer": [p.text for p in section.footer.paragraphs],
            }
        )
    return result


def _all_text(document) -> str:
    values = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in actual_cells(row):
                values.append(cell.text)
                for nested in cell.tables:
                    for nested_row in nested.rows:
                        values.extend(c.text for c in nested_row.cells)
    return "\n".join(values)


def _check_field_coordinates(document, manifest: dict[str, Any], errors: list[str]) -> None:
    table_count = len(document.tables)
    for name, spec in manifest.get("fields", {}).items():
        if spec.get("target") == "document_paragraph" or "paragraph" in spec:
            paragraph_index = int(spec.get("paragraph", -1))
            if paragraph_index < 0 or paragraph_index >= len(document.paragraphs):
                errors.append(f"Field {name} points to missing document paragraph {paragraph_index}")
            continue
        if spec.get("mode") == "row_cells":
            rows = spec.get("rows", [])
            cells = spec.get("cells", [])
            for row_index in rows:
                for cell_index in cells:
                    if (
                        row_index < 0
                        or cell_index < 0
                        or row_index >= manifest["structure"]["main_table"]["rows"]
                        or cell_index >= manifest["structure"]["main_table"]["columns"]
                    ):
                        errors.append(f"Field {name} points outside the declared main table: row={row_index}, cell={cell_index}")
            continue
        if "table" not in spec or "row" not in spec or "cell" not in spec:
            continue
        table_index = int(spec["table"])
        row_index = int(spec["row"])
        cell_index = int(spec["cell"])
        if table_index < 0 or table_index >= table_count:
            errors.append(f"Field {name} points to missing table {table_index}")
            continue
        table = document.tables[table_index]
        if row_index < 0 or row_index >= len(table.rows):
            errors.append(f"Field {name} points to missing row {row_index}")
            continue
        if cell_index < 0 or cell_index >= len(actual_cells(table.rows[row_index])):
            errors.append(f"Field {name} points to missing cell {cell_index} in row {row_index}")


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
        document = Document(str(template))
        report["checks"]["docx_open"] = True
    except Exception as exc:  # pragma: no cover - library-specific parse errors
        errors.append(f"DOCX could not be opened: {exc}")
        raise TemplateValidationError(report)

    structure = manifest.get("structure", {})
    main_spec = structure.get("main_table", {})
    table_index = int(main_spec.get("index", 0))
    expected_top_level_tables = int(structure.get("top_level_tables", 1))
    if len(document.tables) != expected_top_level_tables:
        errors.append(f"Top-level table count mismatch: expected {expected_top_level_tables}, got {len(document.tables)}")
    if len(document.tables) <= table_index:
        errors.append(f"Missing main table at index {table_index}")
    else:
        table = document.tables[table_index]
        if len(table.rows) != int(main_spec.get("rows", 0)):
            errors.append(f"Main table row count mismatch: expected {main_spec.get('rows')}, got {len(table.rows)}")
        if len(table.columns) != int(main_spec.get("columns", 0)):
            errors.append(f"Main table column count mismatch: expected {main_spec.get('columns')}, got {len(table.columns)}")
        report["checks"]["main_table"] = {"rows": len(table.rows), "columns": len(table.columns)}

    evaluation = structure.get("evaluation_table", {})
    try:
        eval_cell = actual_cells(document.tables[int(evaluation["table"])].rows[int(evaluation["row"])])[int(evaluation["cell"])]
        nested = eval_cell.tables[0]
        if len(nested.rows) != int(evaluation["rows"]) or len(nested.columns) != int(evaluation["columns"]):
            errors.append(
                f"Evaluation table size mismatch: expected {evaluation.get('rows')}x{evaluation.get('columns')}, "
                f"got {len(nested.rows)}x{len(nested.columns)}"
            )
        report["checks"]["evaluation_table"] = {"rows": len(nested.rows), "columns": len(nested.columns)}
    except (IndexError, KeyError, TypeError) as exc:
        errors.append(f"Evaluation table coordinate is invalid: {exc}")

    labels = manifest.get("validation", {}).get("required_labels", [])
    document_text = _all_text(document)
    missing_labels = [label for label in labels if label not in document_text]
    if missing_labels:
        errors.append(f"Missing fixed labels: {', '.join(missing_labels)}")
    _check_field_coordinates(document, manifest, errors)
    report["checks"]["required_labels"] = {"count": len(labels), "missing": missing_labels}
    report["checks"]["sections"] = _section_signature(document)

    if canonical.exists() and not is_canonical:
        canonical_doc = Document(str(canonical))
        if _main_table_signature(canonical_doc, manifest) != _main_table_signature(document, manifest):
            errors.append("Custom template changed protected main-table structure or formatting.")
        if _section_signature(canonical_doc) != _section_signature(document):
            errors.append("Custom template changed protected page, header, footer, or section settings.")

    if errors:
        raise TemplateValidationError(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the versioned DOCX lesson-plan template package.")
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
        for warning in report.get("warnings", []):
            print(f"WARNING: {warning}")
        print(f"validated template={template} version={report['template_version']} sha256={report['checks']['sha256']['actual']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
