from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from docx import Document
from lxml import etree

from bookmark_utils import (
    find_bookmark,
    xml_location,
    validate_bookmark_inventory,
)
from package_common import load_manifest
from semantic_bookmarks import (
    FIXED_BOOKMARKS,
    IMPLEMENTATION_COLUMNS,
    IMPLEMENTATION_STAGES,
    REFLECTION_BOOKMARKS,
    managed_bookmark_names,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx"
DEFAULT_SOURCE_MANIFEST = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "manifest.yaml"
DEFAULT_OUTPUT = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "template.docx"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

def _qn(local_name: str) -> str:
    return f"{{{W_NS}}}{local_name}"


def _unique_ids(root: etree._Element) -> int:
    values = []
    for node in root.xpath(".//w:bookmarkStart", namespaces=NS):
        try:
            values.append(int(node.get(_qn("id"), "0")))
        except ValueError:
            continue
    for node in root.xpath(".//w:bookmarkEnd", namespaces=NS):
        try:
            values.append(int(node.get(_qn("id"), "0")))
        except ValueError:
            continue
    return max(values, default=0) + 1


def _named_bookmarks(root: etree._Element) -> list[str]:
    return [str(node.get(_qn("name"), "")) for node in root.xpath(".//w:bookmarkStart", namespaces=NS)]


def _body(root: etree._Element) -> etree._Element:
    body = root.find(f"{{{W_NS}}}body")
    if body is None:
        raise ValueError("word/document.xml is missing w:body")
    return body


def _body_paragraph(body: etree._Element, paragraph_index: int) -> etree._Element:
    paragraphs = [node for node in body if node.tag == _qn("p")]
    if paragraph_index < 0 or paragraph_index >= len(paragraphs):
        raise ValueError(f"field 'title' points to missing document paragraph {paragraph_index}")
    return paragraphs[paragraph_index]


def _top_level_tables(body: etree._Element) -> list[etree._Element]:
    return [node for node in body if node.tag == _qn("tbl")]


def _table_cell(body: etree._Element, table_index: int, row_index: int, cell_index: int, field: str) -> etree._Element:
    tables = _top_level_tables(body)
    if table_index < 0 or table_index >= len(tables):
        raise ValueError(f"field '{field}' points to missing table {table_index}")
    rows = [node for node in tables[table_index] if node.tag == _qn("tr")]
    if row_index < 0 or row_index >= len(rows):
        raise ValueError(f"field '{field}' points to missing row {row_index}")
    cells = [node for node in rows[row_index] if node.tag == _qn("tc")]
    if cell_index < 0 or cell_index >= len(cells):
        raise ValueError(f"field '{field}' points to missing cell {cell_index} in row {row_index}")
    return cells[cell_index]


def _first_paragraph(cell: etree._Element, field: str) -> etree._Element:
    for child in cell:
        if child.tag == _qn("p"):
            return child
    raise ValueError(f"field '{field}' target cell has no writable paragraph")


def _add_bookmark(paragraph: etree._Element, name: str, bookmark_id: int, field: str) -> None:
    start = etree.Element(_qn("bookmarkStart"))
    start.set(_qn("id"), str(bookmark_id))
    start.set(_qn("name"), name)
    end = etree.Element(_qn("bookmarkEnd"))
    end.set(_qn("id"), str(bookmark_id))
    ppr = paragraph.find(_qn("pPr"))
    insert_index = list(paragraph).index(ppr) + 1 if ppr is not None else 0
    paragraph.insert(insert_index, start)
    paragraph.append(end)


def _definitions(source_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    fields = source_manifest.get("fields", {})
    definitions: list[dict[str, Any]] = []
    for field, bookmark in FIXED_BOOKMARKS:
        spec = fields.get(field)
        if not isinstance(spec, dict):
            raise ValueError(f"field '{field}' is missing from v1.0 source manifest")
        if spec.get("target") == "document_paragraph" or "paragraph" in spec:
            definitions.append({"field": field, "name": bookmark, "container": "document_paragraph", "paragraph": int(spec["paragraph"])})
        else:
            definitions.append(
                {
                    "field": field,
                    "name": bookmark,
                    "container": "cell",
                    "table": int(spec["table"]),
                    "row": int(spec["row"]),
                    "cell": int(spec["cell"]),
                }
            )
    for stage, stage_code, row in IMPLEMENTATION_STAGES:
        for column, column_code, cell in IMPLEMENTATION_COLUMNS:
            definitions.append(
                {
                    "field": f"implementation.{stage}.{column}",
                    "name": f"lp_impl_{stage_code}_{column_code}",
                    "container": "cell",
                    "table": 0,
                    "row": row,
                    "cell": cell,
                }
            )
    for field, name, row in REFLECTION_BOOKMARKS:
        definitions.append(
            {
                "field": f"reflection.{field}",
                "name": name,
                "container": "cell",
                "table": 0,
                "row": row,
                "cell": 2,
            }
        )
    return definitions


def _target_paragraph(body: etree._Element, definition: dict[str, Any]) -> etree._Element:
    target = _target_container(body, definition)
    if definition["container"] == "document_paragraph":
        return target
    return _first_paragraph(target, str(definition["field"]))


def _target_container(body: etree._Element, definition: dict[str, Any]) -> etree._Element:
    if definition["container"] == "document_paragraph":
        return _body_paragraph(body, int(definition["paragraph"]))
    return _table_cell(
        body,
        int(definition["table"]),
        int(definition["row"]),
        int(definition["cell"]),
        str(definition["field"]),
    )


def _validate_semantic_positions(
    root: etree._Element,
    body: etree._Element,
    definitions: list[dict[str, Any]],
    document: Document | None = None,
) -> None:
    expected_containers = {item["name"]: item["container"] for item in definitions}
    inventory = validate_bookmark_inventory(
        document if document is not None else root,
        expected_containers,
        expected_containers,
    )
    if not inventory["valid"]:
        raise ValueError("Semantic bookmark inventory is invalid: " + "; ".join(inventory["errors"]))

    seen_locations: dict[tuple[str, tuple[tuple[str, int], ...]], str] = {}
    for definition in definitions:
        name = str(definition["name"])
        record = find_bookmark(root, name)
        if record is None:
            raise ValueError(f"Bookmark {name} is missing while checking semantic position")
        expected_container = str(definition["container"])
        target = _target_container(body, definition)
        expected_location = xml_location(body, target)
        if expected_location is None:
            raise ValueError(f"Unable to locate expected physical container for bookmark {name}")
        location_key = (expected_container, expected_location)
        previous = seen_locations.get(location_key)
        if previous is not None:
            raise ValueError(
                f"Bookmarks {previous} and {name} resolve to the same physical {expected_container}"
            )
        seen_locations[location_key] = name
        if expected_container == "cell":
            actual_start = xml_location(body, record.start_parent_cell)
            actual_end = xml_location(body, record.end_parent_cell)
            if actual_start != expected_location or actual_end != expected_location:
                raise ValueError(
                    f"Bookmark {name} is in the wrong physical table cell: "
                    f"expected {expected_location}, got start={actual_start}, end={actual_end}"
                )
        else:
            actual_start = xml_location(body, record.start_parent_paragraph)
            actual_end = xml_location(body, record.end_parent_paragraph)
            if actual_start != expected_location or actual_end != expected_location:
                raise ValueError(
                    f"Bookmark {name} is in the wrong document paragraph: "
                    f"expected {expected_location}, got start={actual_start}, end={actual_end}"
                )


def _write_package(source: Path, output: Path, document_xml: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source, "r") as source_zip, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as target_zip:
        for info in source_zip.infolist():
            data = document_xml if info.filename == "word/document.xml" else source_zip.read(info.filename)
            target_zip.writestr(info, data)


def validate_built_template(
    output: Path,
    definitions: list[dict[str, Any]],
    required_names: list[str],
) -> None:
    """Validate the final DOCX package, including every Word story."""
    try:
        document = Document(str(output))
    except Exception as exc:
        raise ValueError(f"Built DOCX package could not be opened: {exc}") from exc
    expected_containers = {item["name"]: item["container"] for item in definitions}
    inventory = validate_bookmark_inventory(document, required_names, expected_containers)
    if not inventory["valid"]:
        raise ValueError(
            "Built DOCX package bookmark inventory is invalid: " + "; ".join(inventory["errors"])
        )
    root = document.element
    _validate_semantic_positions(root, _body(root), definitions, document=document)


def build(source: Path, output: Path, source_manifest: Path) -> list[str]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    source_manifest = source_manifest.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source template not found: {source}")
    if source == output:
        raise ValueError("Source and output template paths must be different")
    # python-docx confirms that the source is a readable Word document before the
    # Open XML pass locates stable table/cell targets.
    Document(str(source))
    legacy_manifest = load_manifest(source_manifest)
    definitions = _definitions(legacy_manifest)
    required_names = [item["name"] for item in definitions]
    if required_names != managed_bookmark_names():
        raise ValueError("Semantic definition order does not match the managed bookmark definition")

    with zipfile.ZipFile(source, "r") as source_zip:
        try:
            xml_bytes = source_zip.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("Source DOCX is missing word/document.xml") from exc
    root = etree.fromstring(xml_bytes)
    existing_names = _named_bookmarks(root)
    counts: dict[str, int] = {}
    for name in existing_names:
        counts[name] = counts.get(name, 0) + 1
    expected_existing = {name for name in required_names if counts.get(name) == 1}
    if expected_existing:
        missing = sorted(set(required_names) - expected_existing)
        if missing:
            raise ValueError("Source has a partial semantic bookmark set; missing: " + ", ".join(missing))
        output_xml = None
    else:
        duplicates = sorted(name for name, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError("Source contains duplicate bookmark names: " + ", ".join(duplicates))

        body = _body(root)
        next_id = _unique_ids(root)
        created: list[str] = []
        for definition in definitions:
            name = str(definition["name"])
            try:
                paragraph = _target_paragraph(body, definition)
                _add_bookmark(paragraph, name, next_id, str(definition["field"]))
            except (IndexError, TypeError, ValueError) as exc:
                raise ValueError(f"Unable to add bookmark {name} for {definition['field']}: {exc}") from exc
            next_id += 1
            created.append(name)

        output_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="lesson-plan-semantic-build-", dir=str(output.parent)) as temp_name:
        temporary_output = Path(temp_name) / output.name
        if output_xml is None:
            shutil.copy2(source, temporary_output)
        else:
            _write_package(source, temporary_output, output_xml)
        validate_built_template(temporary_output, definitions, required_names)
        temporary_output.replace(output)
    return required_names


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the versioned lesson-plan semantic-bookmark template.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--source-manifest", default=str(DEFAULT_SOURCE_MANIFEST))
    parser.add_argument("--output", required=True, help="Explicit output DOCX path")
    args = parser.parse_args()
    try:
        names = build(Path(args.source), Path(args.output), Path(args.source_manifest))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"built={Path(args.output).expanduser().resolve()}")
    print(f"bookmark_count={len(names)}")
    print("bookmarks=" + ",".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
