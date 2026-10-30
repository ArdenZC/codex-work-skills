"""Build a lesson-plan patch template without changing protected DOCX structure."""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path

import yaml
from docx import Document
from lxml import etree

from path_safety import paths_overlap


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _text_containers(root: etree._Element) -> list[etree._Element]:
    """Return explicit Word paragraphs so replacements never cross boundaries."""

    return root.xpath(".//w:p", namespaces={"w": W_NS})


def _visible_text_nodes(container: etree._Element) -> list[etree._Element]:
    return container.xpath(".//w:t", namespaces={"w": W_NS})


def _replace_visible_once(root: etree._Element, old_text: str, new_text: str) -> None:
    matches: list[tuple[list[etree._Element], str]] = []
    for container in _text_containers(root):
        nodes = _visible_text_nodes(container)
        joined = "".join(node.text or "" for node in nodes)
        matches.extend((nodes, joined) for _ in range(joined.count(old_text)))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one visible occurrence of {old_text!r}, found {len(matches)}")
    nodes, joined = matches[0]
    start = joined.index(old_text)
    end = start + len(old_text)
    cursor = 0
    first: etree._Element | None = None
    for node in nodes:
        text = node.text or ""
        node_start, node_end = cursor, cursor + len(text)
        if node_end > start and node_start < end:
            if first is None:
                first = node
                local_start = max(start - node_start, 0)
                local_end = min(end - node_start, len(text))
                node.text = text[:local_start] + new_text + text[local_end:]
            else:
                local_start = max(start - node_start, 0)
                local_end = min(end - node_start, len(text))
                node.text = text[:local_start] + text[local_end:]
        cursor = node_end
    if first is not None and any((node.text or "") for node in nodes):
        first.set(f"{{{XML_NS}}}space", "preserve")


def _evaluation_table_element(root: etree._Element, structure: dict) -> etree._Element:
    spec = structure.get("evaluation_table", {})
    body = root.find(f"{{{W_NS}}}body")
    top_tables = body.findall(f"{{{W_NS}}}tbl") if body is not None else []
    table_index = int(spec.get("table", -1))
    if table_index < 0 or table_index >= len(top_tables):
        raise ValueError("evaluation_table.table points to a missing top-level table")
    rows = top_tables[table_index].findall(f"{{{W_NS}}}tr")
    row_index = int(spec.get("row", -1))
    if row_index < 0 or row_index >= len(rows):
        raise ValueError("evaluation_table.row points to a missing table row")
    cells = rows[row_index].findall(f"{{{W_NS}}}tc")
    cell_index = int(spec.get("cell", -1))
    if cell_index < 0 or cell_index >= len(cells):
        raise ValueError("evaluation_table.cell points to a missing table cell")
    nested = cells[cell_index].findall(f"{{{W_NS}}}tbl")
    if len(nested) != 1:
        raise ValueError(f"expected one nested evaluation table, found {len(nested)}")
    return nested[0]


def _patch_evaluation_column_widths(
    root: etree._Element,
    widths_twips: list[int],
    structure: dict,
) -> None:
    if len(widths_twips) != 4 or any(type(value) is not int or value <= 0 for value in widths_twips):
        raise ValueError("evaluation_table_column_widths_twips must contain four positive integer widths")
    nested = _evaluation_table_element(root, structure)
    table_properties = nested.find(f"{{{W_NS}}}tblPr")
    table_width = table_properties.find(f"{{{W_NS}}}tblW") if table_properties is not None else None
    if table_width is None or table_width.get(f"{{{W_NS}}}type") != "dxa":
        raise ValueError("evaluation table must declare its total width in dxa")
    total_width = int(table_width.get(f"{{{W_NS}}}w", "0"))
    if sum(widths_twips) != total_width:
        raise ValueError(
            "evaluation column widths must preserve the existing total table width "
            f"({total_width} twips); received {sum(widths_twips)}"
        )

    grid = nested.find(f"{{{W_NS}}}tblGrid")
    grid_columns = grid.findall(f"{{{W_NS}}}gridCol") if grid is not None else []
    if len(grid_columns) != 4:
        raise ValueError(f"expected four evaluation table grid columns, found {len(grid_columns)}")
    for column, width in zip(grid_columns, widths_twips):
        column.set(f"{{{W_NS}}}w", str(width))

    rows = nested.findall(f"{{{W_NS}}}tr")
    expected_rows = int(structure.get("evaluation_table", {}).get("rows", 14))
    if len(rows) != expected_rows:
        raise ValueError(f"expected {expected_rows} evaluation rows, found {len(rows)}")
    for row_index, row in enumerate(rows):
        cells = row.findall(f"{{{W_NS}}}tc")
        if len(cells) != 4:
            raise ValueError(f"evaluation row {row_index} must retain four physical cells")
        for cell_index, (cell, width) in enumerate(zip(cells, widths_twips)):
            properties = cell.find(f"{{{W_NS}}}tcPr")
            cell_width = properties.find(f"{{{W_NS}}}tcW") if properties is not None else None
            if cell_width is None:
                raise ValueError(f"evaluation cell {row_index},{cell_index} has no declared width")
            if cell_width.get(f"{{{W_NS}}}type") != "dxa":
                raise ValueError(f"evaluation cell {row_index},{cell_index} width is not in dxa")
            cell_width.set(f"{{{W_NS}}}w", str(width))


def _patch_evaluation_pagination(
    root: etree._Element,
    pagination: dict | None,
    structure: dict,
) -> None:
    if pagination is None:
        return
    if not isinstance(pagination, dict):
        raise ValueError("evaluation_table_pagination must be a mapping")
    keep_rows_together = pagination.get("keep_rows_together")
    if set(pagination) != {"keep_rows_together"} or type(keep_rows_together) is not bool:
        raise ValueError("evaluation_table_pagination must declare boolean keep_rows_together")
    nested = _evaluation_table_element(root, structure)
    rows = nested.findall(f"{{{W_NS}}}tr")
    expected_rows = int(structure.get("evaluation_table", {}).get("rows", 14))
    if len(rows) != expected_rows or not rows:
        raise ValueError(f"expected {expected_rows} evaluation rows before pagination patch, found {len(rows)}")
    for row in rows:
        tr_properties = row.find(f"{{{W_NS}}}trPr")
        if tr_properties is None:
            tr_properties = etree.Element(f"{{{W_NS}}}trPr")
            row.insert(0, tr_properties)
        cant_split = tr_properties.find(f"{{{W_NS}}}cantSplit")
        should_keep = keep_rows_together
        if should_keep and cant_split is None:
            tr_properties.append(etree.Element(f"{{{W_NS}}}cantSplit"))
        elif not should_keep and cant_split is not None:
            tr_properties.remove(cant_split)


def _implementation_table_element(root: etree._Element, structure: dict) -> etree._Element:
    spec = structure.get("implementation_table", {})
    body = root.find(f"{{{W_NS}}}body")
    top_tables = body.findall(f"{{{W_NS}}}tbl") if body is not None else []
    table_index = int(spec.get("index", -1))
    if table_index < 0 or table_index >= len(top_tables):
        raise ValueError("implementation_table.index points to a missing top-level table")
    return top_tables[table_index]


def _patch_implementation_layout(
    root: etree._Element,
    widths_twips: list[int] | None,
    body_font_size_pt: int | float | None,
    structure: dict,
) -> None:
    table = _implementation_table_element(root, structure)
    rows = table.findall(f"{{{W_NS}}}tr")
    expected_rows = int(structure.get("implementation_table", {}).get("rows", -1))
    if len(rows) != expected_rows or not rows:
        raise ValueError(f"expected {expected_rows} implementation rows, found {len(rows)}")

    if widths_twips is not None:
        if len(widths_twips) != 5 or any(type(value) is not int or value <= 0 for value in widths_twips):
            raise ValueError("implementation_table_column_widths_twips must contain five positive integers")
        table_properties = table.find(f"{{{W_NS}}}tblPr")
        table_width = table_properties.find(f"{{{W_NS}}}tblW") if table_properties is not None else None
        if table_width is None or table_width.get(f"{{{W_NS}}}type") != "dxa":
            raise ValueError("implementation table must declare its total width in dxa")
        total_width = int(table_width.get(f"{{{W_NS}}}w", "0"))
        if sum(widths_twips) != total_width:
            raise ValueError(
                "implementation column widths must preserve the existing total table width "
                f"({total_width} twips); received {sum(widths_twips)}"
            )

        grid = table.find(f"{{{W_NS}}}tblGrid")
        grid_columns = grid.findall(f"{{{W_NS}}}gridCol") if grid is not None else []
        header_cells = rows[0].findall(f"{{{W_NS}}}tc")
        if len(header_cells) != 5 or not grid_columns:
            raise ValueError("implementation table must retain five header cells and a table grid")

        old_grid = [int(column.get(f"{{{W_NS}}}w", "0")) for column in grid_columns]
        new_grid: list[int] = []
        grid_cursor = 0
        for cell, target_width in zip(header_cells, widths_twips):
            properties = cell.find(f"{{{W_NS}}}tcPr")
            span_element = properties.find(f"{{{W_NS}}}gridSpan") if properties is not None else None
            span = int(span_element.get(f"{{{W_NS}}}val", "1")) if span_element is not None else 1
            old_group = old_grid[grid_cursor : grid_cursor + span]
            if len(old_group) != span or sum(old_group) <= 0:
                raise ValueError("implementation header cell spans do not match the declared table grid")
            assigned = [round(target_width * value / sum(old_group)) for value in old_group[:-1]]
            assigned.append(target_width - sum(assigned))
            if any(value <= 0 for value in assigned):
                raise ValueError("implementation table widths produce an empty grid column")
            new_grid.extend(assigned)
            grid_cursor += span
        if grid_cursor != len(old_grid):
            raise ValueError("implementation header cells do not cover the table grid")

        for column, width in zip(grid_columns, new_grid):
            column.set(f"{{{W_NS}}}w", str(width))
        for row_index, row in enumerate(rows):
            cells = row.findall(f"{{{W_NS}}}tc")
            cursor = 0
            row_properties = row.find(f"{{{W_NS}}}trPr")
            before = row_properties.find(f"{{{W_NS}}}gridBefore") if row_properties is not None else None
            if before is not None:
                cursor = int(before.get(f"{{{W_NS}}}val", "0"))
            for cell in cells:
                properties = cell.find(f"{{{W_NS}}}tcPr")
                span_element = properties.find(f"{{{W_NS}}}gridSpan") if properties is not None else None
                span = int(span_element.get(f"{{{W_NS}}}val", "1")) if span_element is not None else 1
                width = sum(new_grid[cursor : cursor + span])
                if width <= 0 or cursor + span > len(new_grid):
                    raise ValueError(f"implementation row {row_index} has an invalid grid span")
                cell_width = properties.find(f"{{{W_NS}}}tcW") if properties is not None else None
                if cell_width is None:
                    raise ValueError(f"implementation cell in row {row_index} has no declared width")
                cell_width.set(f"{{{W_NS}}}w", str(width))
                cell_width.set(f"{{{W_NS}}}type", "dxa")
                cursor += span
            after = row_properties.find(f"{{{W_NS}}}gridAfter") if row_properties is not None else None
            after_span = int(after.get(f"{{{W_NS}}}val", "0")) if after is not None else 0
            if cursor + after_span != len(new_grid):
                raise ValueError(f"implementation row {row_index} does not cover the table grid")

    if body_font_size_pt is not None:
        if (
            isinstance(body_font_size_pt, bool)
            or not isinstance(body_font_size_pt, (int, float))
            or body_font_size_pt <= 0
            or int(body_font_size_pt * 2) != body_font_size_pt * 2
        ):
            raise ValueError("implementation_body_font_size_pt must be a positive half-point size")
        half_points = str(int(body_font_size_pt * 2))
        for row in rows[1:]:
            cells = row.findall(f"{{{W_NS}}}tc")
            for cell in cells[1:]:
                for run in cell.findall(f".//{{{W_NS}}}r"):
                    run_properties = run.find(f"{{{W_NS}}}rPr")
                    if run_properties is None:
                        run_properties = etree.Element(f"{{{W_NS}}}rPr")
                        run.insert(0, run_properties)
                    for name in ("sz", "szCs"):
                        size = run_properties.find(f"{{{W_NS}}}{name}")
                        if size is None:
                            size = etree.SubElement(run_properties, f"{{{W_NS}}}{name}")
                        size.set(f"{{{W_NS}}}val", half_points)


def _patch_implementation_keep_with_next(
    root: etree._Element,
    keep_with_next_rows: list[int],
    structure: dict,
) -> None:
    table = _implementation_table_element(root, structure)
    rows = table.findall(f"{{{W_NS}}}tr")
    expected_rows = int(structure.get("implementation_table", {}).get("rows", -1))
    if len(rows) != expected_rows or not rows:
        raise ValueError(f"expected {expected_rows} implementation rows, found {len(rows)}")
    if (
        not isinstance(keep_with_next_rows, list)
        or any(type(index) is not int or not 0 <= index < len(rows) for index in keep_with_next_rows)
        or len(set(keep_with_next_rows)) != len(keep_with_next_rows)
    ):
        raise ValueError("implementation_table_pagination.keep_with_next_rows must contain unique valid row indexes")
    keep_rows = set(keep_with_next_rows)
    for row_index, row in enumerate(rows):
        for paragraph in row.findall(f".//{{{W_NS}}}p"):
            paragraph_properties = paragraph.find(f"{{{W_NS}}}pPr")
            keep_next = (
                paragraph_properties.find(f"{{{W_NS}}}keepNext")
                if paragraph_properties is not None
                else None
            )
            if row_index in keep_rows:
                if paragraph_properties is None:
                    paragraph_properties = etree.Element(f"{{{W_NS}}}pPr")
                    paragraph.insert(0, paragraph_properties)
                if keep_next is None:
                    paragraph_properties.append(etree.Element(f"{{{W_NS}}}keepNext"))
            elif keep_next is not None:
                paragraph_properties.remove(keep_next)


def _patch_title_east_asia_font(root: etree._Element, font_name: str) -> None:
    if not isinstance(font_name, str) or not font_name.strip():
        raise ValueError("title_east_asia_font must be a non-empty font name")
    paragraphs = root.xpath("./w:body/w:p", namespaces={"w": W_NS})
    if not paragraphs:
        raise ValueError("template must have a title paragraph as its first body paragraph")
    runs = paragraphs[0].xpath("./w:r[w:t]", namespaces={"w": W_NS})
    if not runs:
        raise ValueError("template title paragraph must contain a text run")
    run = runs[0]
    run_properties = run.find(f"{{{W_NS}}}rPr")
    if run_properties is None:
        run_properties = etree.Element(f"{{{W_NS}}}rPr")
        run.insert(0, run_properties)
    fonts = run_properties.find(f"{{{W_NS}}}rFonts")
    if fonts is None:
        fonts = etree.Element(f"{{{W_NS}}}rFonts")
        run_properties.insert(0, fonts)
    for theme_attribute in ("asciiTheme", "eastAsiaTheme", "hAnsiTheme", "cstheme"):
        fonts.attrib.pop(f"{{{W_NS}}}{theme_attribute}", None)
    for script_attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(f"{{{W_NS}}}{script_attribute}", font_name)


def _replace_document_text(
    document_xml: bytes,
    replacements: list[tuple[str, str]],
    evaluation_widths_twips: list[int] | None = None,
    evaluation_pagination: dict | None = None,
    implementation_widths_twips: list[int] | None = None,
    implementation_body_font_size_pt: int | float | None = None,
    implementation_keep_with_next_rows: list[int] | None = None,
    title_east_asia_font: str | None = None,
    structure: dict | None = None,
) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    try:
        root = etree.fromstring(document_xml, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"word/document.xml is not valid XML: {exc}") from exc
    for old_text, new_text in replacements:
        _replace_visible_once(root, old_text, new_text)
    if title_east_asia_font is not None:
        _patch_title_east_asia_font(root, title_east_asia_font)
    if evaluation_widths_twips is not None or evaluation_pagination is not None:
        if structure is None:
            raise ValueError("template structure is required for evaluation table layout changes")
        if evaluation_widths_twips is not None:
            _patch_evaluation_column_widths(root, evaluation_widths_twips, structure)
        _patch_evaluation_pagination(root, evaluation_pagination, structure)
    if (
        implementation_widths_twips is not None
        or implementation_body_font_size_pt is not None
        or implementation_keep_with_next_rows is not None
    ):
        if structure is None:
            raise ValueError("template structure is required for implementation table layout changes")
        _patch_implementation_layout(
            root,
            implementation_widths_twips,
            implementation_body_font_size_pt,
            structure,
        )
        if implementation_keep_with_next_rows is not None:
            _patch_implementation_keep_with_next(root, implementation_keep_with_next_rows, structure)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _canonical_paths() -> set[Path]:
    skill_dir = Path(__file__).resolve().parents[1]
    package_root = skill_dir / "assets" / "templates" / "lesson-plan"
    protected = {
        skill_dir / "assets" / "lesson-plan-template.docx",
    }
    for version in ("v1.0.0", "v1.1.0", "v1.1.1", "v1.1.2", "v1.1.3"):
        protected.add(package_root / version)
    return {path.resolve(strict=False) for path in protected}


def _assert_target_safe(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Source template not found: {source}")
    if paths_overlap(source, target):
        raise ValueError("Source and target templates must not overlap")
    if target.exists() or target.is_symlink():
        raise FileExistsError(
            f"Refusing to overwrite existing target; choose a new path: {target}"
        )
    for protected in _canonical_paths():
        if paths_overlap(target, protected):
            raise ValueError(f"Refusing to write protected canonical template path: {target}")


def build_patch(
    source: Path,
    target: Path,
    replacements: list[tuple[str, str]],
    evaluation_widths_twips: list[int] | None = None,
    evaluation_pagination: dict | None = None,
    implementation_widths_twips: list[int] | None = None,
    implementation_body_font_size_pt: int | float | None = None,
    implementation_keep_with_next_rows: list[int] | None = None,
    title_east_asia_font: str | None = None,
    structure: dict | None = None,
) -> None:
    if source.resolve() == target.resolve():
        raise ValueError("Source and target templates must be different files")
    _assert_target_safe(source, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(source, "r") as source_zip, zipfile.ZipFile(temporary, "w") as target_zip:
            for info in source_zip.infolist():
                payload = source_zip.read(info.filename)
                if info.filename == "word/document.xml":
                    payload = _replace_document_text(
                        payload,
                        replacements,
                        evaluation_widths_twips,
                        evaluation_pagination,
                        implementation_widths_twips,
                        implementation_body_font_size_pt,
                        implementation_keep_with_next_rows,
                        title_east_asia_font,
                        structure,
                    )
                target_zip.writestr(info, payload)
        with zipfile.ZipFile(temporary, "r") as check_zip:
            if check_zip.testzip() is not None:
                raise ValueError("patched DOCX contains a corrupt ZIP member")
            document_xml = check_zip.read("word/document.xml")
        etree.fromstring(document_xml)
        try:
            Document(str(temporary))
        except Exception as exc:  # pragma: no cover - python-docx parser details
            raise ValueError(f"patched DOCX could not be reopened: {exc}") from exc
        os.replace(str(temporary), str(target))
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--manifest", type=Path, help="Read template patches and structural coordinates from a UTF-8 YAML manifest")
    parser.add_argument("--replace", action="append", metavar="OLD=NEW")
    args = parser.parse_args()
    replacements: list[tuple[str, str]] = []
    values = list(args.replace or [])
    evaluation_widths_twips = None
    evaluation_pagination = None
    implementation_widths_twips = None
    implementation_body_font_size_pt = None
    implementation_keep_with_next_rows = None
    title_east_asia_font = None
    structure = None
    if args.manifest:
        manifest = yaml.safe_load(args.manifest.expanduser().resolve().read_text(encoding="utf-8")) or {}
        patches = manifest.get("template", {}).get("patches", {})
        for item in patches.get("visible_text_replacements", []):
            values.append(f"{item['from']}={item['to']}")
        evaluation_widths_twips = patches.get("evaluation_table_column_widths_twips")
        evaluation_pagination = patches.get("evaluation_table_pagination")
        implementation_widths_twips = patches.get("implementation_table_column_widths_twips")
        implementation_body_font_size_pt = patches.get("implementation_body_font_size_pt")
        title_east_asia_font = patches.get("title_east_asia_font")
        implementation_pagination = patches.get("implementation_table_pagination")
        if implementation_pagination is not None:
            if (
                not isinstance(implementation_pagination, dict)
                or set(implementation_pagination) != {"keep_with_next_rows"}
                or not isinstance(implementation_pagination.get("keep_with_next_rows"), list)
            ):
                raise ValueError("implementation_table_pagination must declare keep_with_next_rows")
            implementation_keep_with_next_rows = implementation_pagination["keep_with_next_rows"]
        structure = manifest.get("structure")
    if not values and all(
        value is None
        for value in (
            evaluation_widths_twips,
            evaluation_pagination,
            implementation_widths_twips,
            implementation_body_font_size_pt,
            implementation_keep_with_next_rows,
            title_east_asia_font,
        )
    ):
        parser.error("provide --manifest with supported patches or at least one --replace")
    for value in values:
        if "=" not in value:
            parser.error("--replace must use OLD=NEW")
        old_text, new_text = value.split("=", 1)
        if not old_text or not new_text or old_text == new_text:
            parser.error("--replace values must contain two different non-empty strings")
        replacements.append((old_text, new_text))
    build_patch(
        args.source.expanduser().resolve(),
        args.target.expanduser().resolve(),
        replacements,
        evaluation_widths_twips,
        evaluation_pagination,
        implementation_widths_twips,
        implementation_body_font_size_pt,
        implementation_keep_with_next_rows,
        title_east_asia_font,
        structure,
    )
    print(f"patched={args.target.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
