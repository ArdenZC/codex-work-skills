from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import _Cell

from bookmark_utils import bookmark_parent_cell, bookmark_parent_paragraph, find_bookmark
from package_common import DEFAULT_MANIFEST, DEFAULT_SCHEMA, evaluation_cell_values, ensure_supported_major, field_bookmark, field_spec, generated_lesson_fields, implementation_bookmarks, implementation_cell_values, is_semantic_manifest, load_manifest, manifest_template_path, reflection_bookmarks, reflection_cell_values, resolve_template_package, validate_composed_fields, validate_input
from validate_output import validate_output_dir, write_skipped_report
from validate_template import validate_template


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.1" / "template.docx"

MAX_FILENAME_BYTES = 255


def actual_cells(row):
    return [_Cell(tc, row._parent) for tc in row._tr.tc_lst]


def clear_paragraph(paragraph):
    for child in list(paragraph._p):
        if child.tag not in {qn("w:pPr"), qn("w:bookmarkStart"), qn("w:bookmarkEnd")}:
            paragraph._p.remove(child)


def copy_run_format(src, dst):
    source_rpr = src._element.rPr
    target_rpr = dst._element.rPr
    if source_rpr is None:
        if target_rpr is not None:
            dst._element.remove(target_rpr)
        return
    if target_rpr is None:
        target_rpr = dst._element.get_or_add_rPr()
    for child in list(target_rpr):
        target_rpr.remove(child)
    for child in source_rpr:
        target_rpr.append(copy.deepcopy(child))


def copy_paragraph_format(src, dst):
    source_ppr = src._p.pPr
    target_ppr = dst._p.pPr
    if source_ppr is None:
        if target_ppr is not None:
            dst._p.remove(target_ppr)
        return
    if target_ppr is None:
        target_ppr = dst._p.get_or_add_pPr()
    for child in list(target_ppr):
        target_ppr.remove(child)
    for child in source_ppr:
        target_ppr.append(copy.deepcopy(child))


def set_paragraph_text(paragraph, text, align=None, source_run=None, bookmark_end=None):
    src = source_run or (paragraph.runs[0] if paragraph.runs else None)
    clear_paragraph(paragraph)
    run = paragraph.add_run(str(text))
    if src is not None:
        copy_run_format(src, run)
    if bookmark_end is not None and bookmark_end.getparent() is paragraph._p:
        paragraph._p.remove(run._r)
        paragraph._p.insert(list(paragraph._p).index(bookmark_end), run._r)
    if align is not None:
        paragraph.alignment = align

def set_cell_text(cell, text, align=None, preserve_cell_layout=False, bookmark_end=None):
    paragraph = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    set_paragraph_text(paragraph, text, align, bookmark_end=bookmark_end)
    for extra in list(cell.paragraphs)[1:]:
        extra._element.getparent().remove(extra._element)
    if not preserve_cell_layout:
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_cell_multiline(cell, text, align=None, bookmark_end=None):
    lines = str(text).splitlines() or [""]
    paragraphs = list(cell.paragraphs) if cell.paragraphs else [cell.add_paragraph()]
    source_paragraph = paragraphs[0]
    source_run = source_paragraph.runs[0] if source_paragraph.runs else None
    while len(paragraphs) < len(lines):
        paragraph = cell.add_paragraph()
        if source_paragraph.style is not None:
            paragraph.style = source_paragraph.style
        paragraphs.append(paragraph)
    for paragraph, line in zip(paragraphs, lines):
        if paragraph is not source_paragraph:
            copy_paragraph_format(source_paragraph, paragraph)
        set_paragraph_text(
            paragraph,
            line,
            align,
            source_run,
            bookmark_end=bookmark_end if paragraph is source_paragraph else None,
        )
    for extra in paragraphs[len(lines):]:
        extra._element.getparent().remove(extra._element)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_row(table, row_idx, values_by_idx):
    cells = actual_cells(table.rows[row_idx])
    for idx, value in values_by_idx.items():
        if idx < len(cells):
            writer = set_cell_multiline if "\n" in str(value) else set_cell_text
            writer(cells[idx], value)


def _semantic_target(document, manifest: dict[str, Any], name: str):
    bookmark_name = field_bookmark(manifest, name)
    record = find_bookmark(document, bookmark_name)
    if record is None:
        raise ValueError(f"Semantic bookmark {bookmark_name} for field {name} is missing")
    spec = field_spec(manifest, name)
    target = spec["target"]
    if target == "document_paragraph":
        paragraph_element = bookmark_parent_paragraph(document, record)
        if paragraph_element is None:
            raise ValueError(f"Semantic bookmark {bookmark_name} for field {name} is not in a document paragraph")
        return Paragraph(paragraph_element, document), record.end
    if target == "table_cell":
        cell_element = bookmark_parent_cell(document, record)
        if cell_element is None:
            raise ValueError(f"Semantic bookmark {bookmark_name} for field {name} is not in a table cell")
        return _Cell(cell_element, document), record.end
    if target == "nested_table":
        raise ValueError(f"Semantic field {name} target nested_table requires the evaluation writer")
    raise ValueError(f"Unsupported semantic field target for fields.{name}: {target}")


def set_manifest_field(document, table, manifest: dict[str, Any], name: str, value: Any, align=None):
    spec = field_spec(manifest, name)
    if is_semantic_manifest(manifest):
        target, bookmark_end = _semantic_target(document, manifest, name)
        mode = spec["mode"]
        if isinstance(target, Paragraph):
            if mode != "replace_text_preserve_style":
                raise ValueError(f"Unsupported semantic field mode for fields.{name}: {mode}")
            set_paragraph_text(target, value, align, bookmark_end=bookmark_end)
            return
        if mode == "replace_single_paragraph":
            set_cell_text(target, value, align, bookmark_end=bookmark_end)
            return
        if mode == "replace_paragraphs":
            set_cell_multiline(target, value, align, bookmark_end=bookmark_end)
            return
        raise ValueError(f"Unsupported semantic field mode for fields.{name}: {mode}")
    if "table" not in spec or "row" not in spec or "cell" not in spec:
        raise ValueError(f"Field {name} is not a single table-cell field")
    target_table = table if int(spec["table"]) == 0 else table._parent.tables[int(spec["table"])]
    cell = actual_cells(target_table.rows[int(spec["row"])])[int(spec["cell"])]
    writer = set_cell_multiline if spec.get("mode") in {"replace_paragraphs", "replace_multiline"} else set_cell_text
    writer(cell, value, align)


def set_anchored_cell(document, manifest: dict[str, Any], bookmark_name: str, value: Any, multiline: bool = False):
    record = find_bookmark(document, bookmark_name)
    if record is None:
        raise ValueError(f"Semantic bookmark {bookmark_name} is missing")
    cell_element = bookmark_parent_cell(document, record)
    if cell_element is None:
        raise ValueError(f"Semantic bookmark {bookmark_name} is not in a table cell")
    cell = _Cell(cell_element, document)
    writer = set_cell_multiline if multiline else set_cell_text
    writer(cell, value, bookmark_end=record.end)


def numbered(items: list[str], limit: int | None = None) -> str:
    values = [str(x).strip() for x in items if str(x).strip()]
    if limit and len(values) > limit:
        values = values[:limit] + ["结合任务材料完成其余流程训练"]
    return "\n".join(f"{idx}. {item}" for idx, item in enumerate(values, 1))


def safe_name(text: str) -> str:
    text = re.sub(r"\s+", "", str(text))
    return re.sub(r'[\\/:*?"<>|]+', "", text)


def _utf8_prefix(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def lesson_filename(seq: int, unit: str, task: str) -> str:
    prefix = f"教案{seq:02d}_"
    suffix = ".docx"
    stem = f"{safe_name(unit)}_{safe_name(task)}"
    filename = f"{prefix}{stem}{suffix}"
    if len(filename.encode("utf-8")) <= MAX_FILENAME_BYTES:
        return filename
    digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:10]
    marker = f"~{digest}"
    stem_budget = MAX_FILENAME_BYTES - len((prefix + marker + suffix).encode("utf-8"))
    return f"{prefix}{_utf8_prefix(stem, stem_budget)}{marker}{suffix}"


def add_eval_table(cell, target: float, seq: int, manifest: dict[str, Any]):
    table = cell.tables[0] if cell.tables else cell.add_table(rows=14, cols=4)
    for r_idx, values in enumerate(evaluation_cell_values(target, seq), start=1):
        set_cell_text(table.cell(r_idx, 2), values[2], preserve_cell_layout=True)
        set_cell_text(table.cell(r_idx, 3), values[3], preserve_cell_layout=True)


def build_lesson(template: Path, out_dir: Path, meta: dict[str, Any], item: dict[str, Any], seq: int, manifest: dict[str, Any]) -> Path:
    course = item.get("course_name") or meta["course_name"]
    major = item.get("major") or meta.get("major", "软件技术")
    audience = item.get("audience") or meta.get("audience", "高职二年级")
    hours = str(item.get("hours") or meta.get("default_hours", "2"))
    unit = str(item["unit"])
    task = str(item["task"])
    flows = [str(x) for x in item.get("flows", [])]
    knowledge = [str(x) for x in item.get("knowledge", [])]
    tools = str(item.get("tools", "课程PPT、微课视频、任务单、评分表和成果模板"))
    score = float(item.get("score", 89 + ((seq - 1) % 6) * 0.5))

    doc = Document(str(template))
    title_text = f"{seq} 《{course}》教学单元设计：{task}"
    if is_semantic_manifest(manifest):
        target, bookmark_end = _semantic_target(doc, manifest, "title")
        set_paragraph_text(target, title_text, WD_ALIGN_PARAGRAPH.CENTER, bookmark_end=bookmark_end)
    else:
        title_spec = field_spec(manifest, "title")
        title_index = int(title_spec.get("paragraph", manifest["structure"]["title"]["paragraph"]))
        if title_index >= len(doc.paragraphs):
            raise ValueError(f"Title paragraph coordinate is invalid: {title_index}")
        set_paragraph_text(doc.paragraphs[title_index], title_text, WD_ALIGN_PARAGRAPH.CENTER)

    table = doc.tables[0]
    set_manifest_field(doc, table, manifest, "course_name", course)
    set_manifest_field(doc, table, manifest, "major", major)
    set_manifest_field(doc, table, manifest, "audience", audience)
    set_manifest_field(doc, table, manifest, "unit", unit)
    set_manifest_field(doc, table, manifest, "task", task)
    set_manifest_field(doc, table, manifest, "hours", hours)
    for name, value in generated_lesson_fields(unit, task, flows, knowledge, tools).items():
        set_manifest_field(doc, table, manifest, name, value)
    if is_semantic_manifest(manifest):
        evaluation_name = field_bookmark(manifest, "evaluation")
        evaluation_record = find_bookmark(doc, evaluation_name)
        if evaluation_record is None:
            raise ValueError(f"Semantic bookmark {evaluation_name} for field evaluation is missing")
        evaluation_element = bookmark_parent_cell(doc, evaluation_record)
        if evaluation_element is None:
            raise ValueError(f"Semantic bookmark {evaluation_name} for field evaluation is not in a table cell")
        evaluation_cell = _Cell(evaluation_element, doc)
    else:
        evaluation_spec = manifest["structure"]["evaluation_table"]
        evaluation_cell = actual_cells(table.rows[int(evaluation_spec["row"])])[int(evaluation_spec["cell"])]
    add_eval_table(evaluation_cell, score, seq, manifest)

    if is_semantic_manifest(manifest):
        for bookmark_group, values in zip(implementation_bookmarks(manifest), implementation_cell_values(task, flows, hours)):
            for bookmark_name, value in zip(bookmark_group, [values[index] for index in range(5)]):
                set_anchored_cell(doc, manifest, bookmark_name, value, multiline="\n" in str(value))
        for bookmark_name, value in zip(reflection_bookmarks(manifest), reflection_cell_values(task)):
            set_anchored_cell(doc, manifest, bookmark_name, value, multiline="\n" in str(value))
    else:
        implementation_rows = [int(row) for row in manifest["fields"]["implementation"]["rows"]]
        for row_index, values in zip(implementation_rows, implementation_cell_values(task, flows, hours)):
            set_row(table, row_index, values)
        reflection_rows = [int(row) for row in manifest["fields"]["reflection"]["rows"]]
        for row_index, value in zip(reflection_rows, reflection_cell_values(task)):
            set_row(table, row_index, {2: value})

    out = out_dir / lesson_filename(seq, unit, task)
    doc.save(out)
    return out


def validate_outputs(
    out_dir: Path,
    meta: dict[str, Any],
    manifest: dict[str, Any],
    schema_path: Path,
    qa_report: Path | None = None,
    *,
    template: Path,
    custom_template: bool,
    template_validation: bool,
    template_warnings: list[str],
) -> dict[str, Any]:
    return validate_output_dir(
        out_dir,
        meta,
        manifest,
        qa_report,
        schema_path,
        template_path=template,
        custom_template=custom_template,
        engine="python-docx",
        template_validation=template_validation,
        extra_warnings=template_warnings,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate template-matched Chinese lesson plan DOCX files.")
    parser.add_argument("--template", default="")
    parser.add_argument("--tasks-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--backup-existing", action="store_true")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--skip-template-validation", action="store_true")
    parser.add_argument("--skip-output-validation", action="store_true")
    parser.add_argument("--qa-report", default="")
    args = parser.parse_args()

    template, manifest_path, manifest = resolve_template_package(
        args.template or None,
        args.manifest or None,
    )
    ensure_supported_major(manifest)
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    out_dir = Path(args.output_dir)
    with open(args.tasks_json, "r", encoding="utf-8") as f:
        meta = json.load(f)
    validate_input(meta, args.schema)
    validate_composed_fields(meta, manifest)
    lessons = meta["lessons"]

    template_warnings: list[str] = []
    if not args.skip_template_validation:
        template_report = validate_template(template, manifest_path)
        template_warnings = template_report.get("warnings", [])
        for warning in template_warnings:
            print(f"WARNING: {warning}")

    if out_dir.exists() and any(out_dir.iterdir()):
        if args.backup_existing:
            backup = out_dir.parent / f"_{out_dir.name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.move(str(out_dir), str(backup))
            print(f"backup={backup}")
        else:
            raise FileExistsError(f"Output directory is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    for seq, item in enumerate(lessons, 1):
        print(build_lesson(template, out_dir, meta, item, seq, manifest))
    if not args.skip_output_validation:
        report = validate_outputs(
            out_dir,
            meta,
            manifest,
            Path(args.schema),
            Path(args.qa_report) if args.qa_report else None,
            template=template,
            custom_template=bool(args.template),
            template_validation=not args.skip_template_validation,
            template_warnings=template_warnings,
        )
        action = "skipped validation" if report["status"] == "skipped" else "validated"
        print(f"{action} files={report['checks']['file_count']['actual']} total_hours={report['checks']['total_hours']['actual']:g} qa={report['qa_report']}")
    else:
        report = write_skipped_report(
            out_dir,
            meta,
            manifest,
            Path(args.qa_report) if args.qa_report else None,
            args.schema,
            template_path=template,
            custom_template=bool(args.template),
            engine="python-docx",
            template_validation=not args.skip_template_validation,
            warnings=template_warnings,
        )
        print(f"WARNING: output validation skipped; qa={report['qa_report']}")


if __name__ == "__main__":
    main()
