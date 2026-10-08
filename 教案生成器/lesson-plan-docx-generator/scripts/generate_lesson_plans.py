from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.table import _Cell

from bookmark_utils import bookmark_parent_cell, bookmark_parent_paragraph, find_bookmark
from content_contract import (
    format_evaluation_values,
    format_implementation,
    format_reflection,
    lesson_content_field_values,
    lesson_filename,
    lesson_header_values,
    format_title,
    reference_canonical_identity,
    reference_source_binding_errors,
)
from content_quality import ContentQualityError, validate_content_quality
from package_common import (
    DEFAULT_MANIFEST,
    DEFAULT_SCHEMA,
    apply_reviewed_lesson_content,
    canonical_json_sha256,
    content_digest_rollup,
    ensure_supported_major,
    field_bookmark,
    field_spec,
    implementation_bookmarks,
    is_semantic_manifest,
    lesson_agent_content,
    load_manifest,
    manifest_template_path,
    reflection_bookmarks,
    resolve_template_package,
    score_breakdown,
    validate_content_v2_input,
    validate_test_fixture_content_v2_input,
)
from path_safety import assert_external_qa_path_safe, assert_output_path_safe, lesson_protected_paths, paths_equal
from render_qa import pdf_page_count
from validate_output import validate_output_dir, write_skipped_report
from validate_template import validate_template


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "template.docx"
UNSAFE_VALIDATION_SKIP_ENV = "LESSON_ALLOW_UNSAFE_VALIDATION_SKIP"
TEST_FIXTURE_AUTHORING_ENV = "LESSON_ALLOW_TEST_FIXTURE_AUTHORING"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{5,95}$")



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


def add_eval_table(cell, target: float, lesson: dict[str, Any], manifest: dict[str, Any]):
    table = cell.tables[0] if cell.tables else cell.add_table(rows=14, cols=4)
    for r_idx, values in enumerate(
        format_evaluation_values(lesson, score_breakdown(target)),
        start=1,
    ):
        set_cell_text(table.cell(r_idx, 2), values[2], preserve_cell_layout=True)
        set_cell_text(table.cell(r_idx, 3), values[3], preserve_cell_layout=True)


def build_lesson(template: Path, out_dir: Path, meta: dict[str, Any], item: dict[str, Any], seq: int, manifest: dict[str, Any]) -> Path:
    header_values = lesson_header_values(meta, item)
    course = header_values["course_name"]
    major = header_values["major"]
    audience = header_values["audience"]
    hours = header_values["hours"]
    lesson_content = lesson_content_field_values(item, meta)
    score = float(item["evaluation"]["score"])

    doc = Document(str(template))
    title_text = format_title(seq, meta, item)
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
    for name, value in {**header_values, **lesson_content}.items():
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
    add_eval_table(evaluation_cell, score, item, manifest)

    if is_semantic_manifest(manifest):
        for bookmark_group, values in zip(implementation_bookmarks(manifest), format_implementation(item["implementation"])):
            for bookmark_name, value in zip(bookmark_group, [values[index] for index in range(5)]):
                set_anchored_cell(doc, manifest, bookmark_name, value, multiline="\n" in str(value))
        for bookmark_name, value in zip(reflection_bookmarks(manifest), format_reflection(item["reflection"])):
            set_anchored_cell(doc, manifest, bookmark_name, value, multiline="\n" in str(value))
    else:
        implementation_rows = [int(row) for row in manifest["fields"]["implementation"]["rows"]]
        for row_index, values in zip(implementation_rows, format_implementation(item["implementation"])):
            set_row(table, row_index, values)
        reflection_rows = [int(row) for row in manifest["fields"]["reflection"]["rows"]]
        for row_index, value in zip(reflection_rows, format_reflection(item["reflection"])):
            set_row(table, row_index, {2: value})

    out = out_dir / lesson_filename(seq, header_values["unit"], header_values["task"])
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
    render: bool,
    render_pdf_dir: Path | None = None,
    allow_test_fixture_authoring: bool = False,
    source_truth_path: Path | None = None,
    content_path: Path | None = None,
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
        render=render,
        render_pdf_dir=render_pdf_dir,
        allow_test_fixture_authoring=allow_test_fixture_authoring,
        source_truth_path=source_truth_path,
        content_path=content_path,
        require_local_outline=source_truth_path is not None,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _stable_render_artifacts(
    report: dict[str, Any],
    candidate: Path,
    expected_docx_names: list[str],
) -> list[dict[str, Any]]:
    render = report.get("render") if isinstance(report.get("render"), dict) else {}
    if render.get("status") != "passed":
        if render.get("status") != "not_executed":
            raise RuntimeError("render evidence is not eligible for artifact stabilization")
        render["pdf_artifacts"] = []
        render.pop("pdf_files", None)
        report["render"] = render
        return []

    expected_names = list(expected_docx_names)
    if (
        any(not isinstance(name, str) or not name or Path(name).name != name for name in expected_names)
        or len(set(expected_names)) != len(expected_names)
    ):
        raise RuntimeError("expected DOCX names for render artifacts are invalid")
    raw_pdf_files = render.get("pdf_files")
    if not isinstance(raw_pdf_files, dict):
        raw_pdf_files = {} if not expected_names else None
    page_counts = render.get("page_counts")
    if not isinstance(raw_pdf_files, dict) or set(raw_pdf_files) != set(expected_names):
        raise RuntimeError("render must retain exactly one current PDF for every Lesson DOCX")
    if not isinstance(page_counts, dict) or set(page_counts) != set(expected_names):
        raise RuntimeError("render page counts must map exactly to every Lesson DOCX")
    if (
        type(render.get("files_checked")) is not int
        or render.get("files_checked") != len(expected_names)
        or any(type(page_counts[name]) is not int or page_counts[name] <= 0 for name in expected_names)
        or type(render.get("page_count")) is not int
        or render.get("page_count") != sum(page_counts.values())
    ):
        raise RuntimeError("render page-count evidence is incomplete or inconsistent")

    pdf_dir = candidate.resolve() / "render" / "pdf"
    if not expected_names:
        if render.get("files_checked") != 0 or render.get("page_count") != 0:
            raise RuntimeError("a render with no theory Lessons must have zero files and pages")
        render["pdf_artifacts"] = []
        render.pop("pdf_files", None)
        report["render"] = render
        return []
    if (candidate / "render").is_symlink() or pdf_dir.is_symlink() or not pdf_dir.is_dir():
        raise RuntimeError("retained PDF directory is missing or is a symbolic link")
    actual_pdfs = [path for path in pdf_dir.iterdir() if path.suffix.lower() == ".pdf"]
    expected_pdf_names = {Path(name).stem + ".pdf" for name in expected_names}
    if (
        len(actual_pdfs) != len(expected_names)
        or {path.name for path in actual_pdfs} != expected_pdf_names
        or any(path.is_symlink() or not path.is_file() for path in actual_pdfs)
    ):
        raise RuntimeError("retained PDF inventory must match the Lesson DOCX inventory exactly")

    artifacts: list[dict[str, Any]] = []
    final_page_counts: dict[str, int] = {}
    resolved_pdf_dir = pdf_dir.resolve(strict=True)
    for docx_name in expected_names:
        raw_pdf = raw_pdf_files.get(docx_name)
        if not isinstance(raw_pdf, str) or not raw_pdf.strip():
            raise RuntimeError(f"{docx_name}: render did not declare its retained PDF")
        declared_path = Path(raw_pdf).expanduser()
        if not declared_path.is_absolute() or declared_path.is_symlink():
            raise RuntimeError(f"{docx_name}: retained PDF path is not a regular absolute path")
        try:
            pdf_path = declared_path.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(f"{docx_name}: retained PDF is missing") from exc
        if pdf_path.parent != resolved_pdf_dir or pdf_path.name != Path(docx_name).stem + ".pdf":
            raise RuntimeError(f"{docx_name}: retained PDF does not match the expected artifact path")
        if not pdf_path.is_file() or pdf_path.stat().st_size <= 0:
            raise RuntimeError(f"{docx_name}: retained PDF is unreadable or empty")
        actual_page_count = pdf_page_count(pdf_path)
        if actual_page_count <= 0 or actual_page_count != page_counts[docx_name]:
            raise RuntimeError(f"{docx_name}: retained PDF page count does not match render QA")
        final_page_counts[docx_name] = actual_page_count
        artifacts.append(
            {
                "docx_path": docx_name,
                "final_pdf_path": _relative_posix(pdf_path, candidate),
                "actual_pdf_page_count": actual_page_count,
            }
        )
    render["page_counts"] = final_page_counts
    render["page_count"] = sum(final_page_counts.values())
    render["pdf_artifacts"] = artifacts
    render.pop("pdf_files", None)
    report["render"] = render
    return artifacts


def _reviewed_content_digest(meta: dict[str, Any]) -> str:
    return content_digest_rollup(
        [canonical_json_sha256(lesson_agent_content(lesson)) for lesson in meta.get("lessons", [])]
    )


def _reference_evidence_payload(meta: dict[str, Any], source_path: Path, run_id: str) -> dict[str, Any]:
    research = meta.get("reference_research") if isinstance(meta.get("reference_research"), dict) else {}
    sources = research.get("sources", []) if isinstance(research, dict) else []
    source_by_id = {
        str(source.get("reference_id")): source
        for source in sources
        if isinstance(source, dict) and source.get("reference_id")
    }
    references: list[dict[str, Any]] = []
    for reference in meta.get("reference_pool", []):
        if not isinstance(reference, dict):
            continue
        reference_id = str(reference.get("reference_id"))
        source = source_by_id.get(reference_id)
        binding_errors = (
            []
            if reference.get("source_kind") != "verified_public"
            else (
                ["research source is missing"]
                if source is None
                else reference_source_binding_errors(reference, source, f"reference_research.sources[{reference_id}]")
            )
        )
        references.append(
            {
                "reference_id": reference_id,
                "source_kind": reference.get("source_kind"),
                "canonical_identity": reference_canonical_identity(reference),
                "research_evidence": (
                    {
                        key: source.get(key)
                        for key in (
                            "reference_id",
                            "source_url",
                            "source_title",
                            "source_author_or_organization",
                            "source_year",
                            "source_identifier",
                            "authoritative_source",
                        )
                    }
                    if isinstance(source, dict)
                    else None
                ),
                "binding_status": "not_applicable" if reference.get("source_kind") != "verified_public" else ("passed" if not binding_errors else "failed"),
                "binding_errors": binding_errors,
            }
        )
    return {
        "evidence_version": "1.0",
        "run_id": run_id,
        "course_name": meta.get("course_name"),
        "major": meta.get("major"),
        "source_json_path": str(source_path.resolve()),
        "references": references,
    }


def _build_artifact_manifest(
    candidate: Path,
    meta: dict[str, Any],
    report: dict[str, Any],
    generated_filenames: list[str],
    run_id: str,
    source_path: Path,
    created_at: str,
    *,
    benchmark_authorization: dict[str, Any] | None = None,
    benchmark_authorization_sha256: str | None = None,
) -> dict[str, Any]:
    render_artifacts = {
        item["docx_path"]: item
        for item in (report.get("render", {}).get("pdf_artifacts", []) if isinstance(report.get("render"), dict) else [])
        if isinstance(item, dict) and item.get("docx_path")
    }
    records: list[dict[str, Any]] = []
    for lesson, filename in zip(meta.get("lessons", []), generated_filenames):
        docx_path = candidate / filename
        render_item = render_artifacts.get(filename, {})
        pdf_path = candidate / str(render_item["final_pdf_path"]) if render_item.get("final_pdf_path") else None
        records.append(
            {
                "lesson_id": lesson.get("lesson_id"),
                "lesson_hours": lesson.get("hours"),
                "final_docx_path": _relative_posix(docx_path, candidate),
                "final_docx_sha256": _file_sha256(docx_path),
                "final_pdf_path": render_item.get("final_pdf_path"),
                "final_pdf_sha256": _file_sha256(pdf_path) if pdf_path is not None and pdf_path.is_file() else None,
                "actual_pdf_page_count": render_item.get("actual_pdf_page_count"),
            }
        )
    page_counts = [
        record["actual_pdf_page_count"]
        for record in records
        if isinstance(record.get("actual_pdf_page_count"), int)
    ]
    lesson_hours = sum(
        (float(lesson.get("hours", 0)) for lesson in meta.get("lessons", [])),
        0.0,
    )
    if lesson_hours.is_integer():
        lesson_hours = int(lesson_hours)
    is_current_contract = meta.get("content_contract_version") in {"2.2", "2.3"}
    source_final_content_sha256 = str((meta.get("authoring_provenance") or {}).get("final_content_sha256", "")).upper()
    packaged_content_sha256 = _reviewed_content_digest(meta) if is_current_contract else None
    reference_evidence_path = candidate / "reference-evidence.json"
    manifest = {
        "manifest_version": "2.0",
        "skill_version": "2.3.1",
        "content_contract_version": meta.get("content_contract_version"),
        "run_id": run_id,
        "course_name": meta.get("course_name"),
        "major": meta.get("major"),
        "lesson_hours": lesson_hours,
        "source_json_path": str(source_path.resolve()),
        "source_json_sha256": _file_sha256(source_path),
        "source_json_path_privacy": "local_diagnostic",
        "source_label": source_path.name,
        "source_sha256": _file_sha256(source_path),
        "final_docx_path": records[0]["final_docx_path"] if len(records) == 1 else None,
        "final_docx_sha256": records[0]["final_docx_sha256"] if len(records) == 1 else None,
        "final_pdf_path": records[0]["final_pdf_path"] if len(records) == 1 else None,
        "final_pdf_sha256": records[0]["final_pdf_sha256"] if len(records) == 1 else None,
        "actual_pdf_page_count": sum(page_counts),
        "qa_status": report.get("status"),
        "render_status": (report.get("render") or {}).get("status") if isinstance(report.get("render"), dict) else None,
        "qa_report_path": "qa-report.json",
        "reference_evidence_path": "reference-evidence.json",
        "reference_evidence_sha256": _file_sha256(reference_evidence_path) if reference_evidence_path.is_file() else None,
        "confirmed_course_info": meta.get("confirmed_course_info"),
        "course_profile": report.get("course_profile"),
        "reviewed_content_digest": (
            {
                "source_final_content_sha256": source_final_content_sha256,
                "packaged_final_content_sha256": packaged_content_sha256,
                "match": bool(source_final_content_sha256) and source_final_content_sha256 == packaged_content_sha256,
            }
            if is_current_contract
            else {"status": "not_applicable"}
        ),
        "created_at": created_at,
        "artifacts": records,
    }
    if benchmark_authorization is None:
        manifest["lesson_skill_capability"] = (
            "2.3-compatible" if meta.get("content_contract_version") == "2.3" else "2.2-compatible"
        )
        manifest["teaching_exemplar_benchmark"] = {"status": "not_provided"}
    else:
        if not isinstance(benchmark_authorization_sha256, str):
            raise RuntimeError("Benchmark Authorization bytes are required to build artifact provenance")
        from benchmark_authorization import authorization_manifest_block

        manifest["lesson_skill_capability"] = "2.3-benchmark-linked"
        manifest["benchmark_authorization_path"] = "benchmark-authorization.json"
        manifest["teaching_exemplar_benchmark"] = authorization_manifest_block(
            benchmark_authorization, benchmark_authorization_sha256
        )
    if is_current_contract:
        manifest["production_status"] = report.get("production_status")
    return manifest


def _artifact_relative_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw_path = Path(value)
    if any(part == ".." for part in raw_path.parts):
        return None
    root_resolved = root.resolve()
    lexical_path = raw_path if raw_path.is_absolute() else root_resolved / raw_path
    try:
        relative = lexical_path.relative_to(root_resolved)
    except ValueError:
        return None
    cursor = root_resolved
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    candidate = lexical_path.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def verify_artifact_manifest(root: Path, manifest: dict[str, Any], source_path: Path) -> str | None:
    """Verify manifest provenance and return the artifact-level production state."""

    if "canonical_lifecycle" in manifest:
        block = manifest["canonical_lifecycle"]
        if not isinstance(block, dict) or set(block) != {"orchestrator_version", "production_authorization_sha256", "semantic_scope"} or block["orchestrator_version"] != "2.0":
            raise RuntimeError("invalid O2 artifact provenance block")
        from lifecycle_digest import read_json_object, sha256_bytes
        from production_authorization import validate_production_authorization_payload
        authorization, raw = read_json_object(root / "production-authorization.json", "artifact PA")
        if validate_production_authorization_payload(authorization) or authorization["contract_version"] != "2.0":
            raise RuntimeError("artifact provenance requires structurally valid PA 2.0")
        if block["production_authorization_sha256"] != sha256_bytes(raw) or block["semantic_scope"] != authorization["semantic_scope"] or authorization["pipeline_run_id"] != manifest.get("run_id") or authorization["content_sha256"] != sha256_bytes(source_path.read_bytes()):
            raise RuntimeError("STALE O2 artifact/PA byte bindings")
        # This verifies stored provenance bytes only. Current external process
        # authority is independently required by the canonical run validator.

    required = {
        "run_id",
        "course_name",
        "major",
        "lesson_hours",
        "source_json_path",
        "source_json_sha256",
        "final_docx_path",
        "final_docx_sha256",
        "final_pdf_path",
        "final_pdf_sha256",
        "actual_pdf_page_count",
        "qa_status",
        "render_status",
        "created_at",
    }
    missing = sorted(field for field in required if field not in manifest)
    if missing:
        raise RuntimeError("artifact manifest is missing required fields: " + ", ".join(missing))
    if Path(str(manifest["source_json_path"])).resolve() != source_path.resolve():
        raise RuntimeError("artifact manifest source_json_path does not match the source JSON")
    if str(manifest["source_json_sha256"]).upper() != _file_sha256(source_path):
        raise RuntimeError("artifact manifest source_json_sha256 does not match the source JSON")
    try:
        source_data = json.loads(source_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"source JSON could not be read for artifact verification: {exc}") from exc
    source_contract_version = source_data.get("content_contract_version")
    if "content_contract_version" in manifest and manifest.get("content_contract_version") != source_contract_version:
        raise RuntimeError("artifact manifest content_contract_version does not match the source JSON")
    if manifest.get("manifest_version") != "2.0":
        raise RuntimeError("artifact manifest manifest_version must be 2.0")
    if "skill_version" in manifest:
        if manifest.get("skill_version") != "2.3.1":
            raise RuntimeError("artifact manifest skill_version must be 2.3.1")
        if manifest.get("source_json_path_privacy") != "local_diagnostic":
            raise RuntimeError("artifact manifest source_json_path must be marked local_diagnostic")
        if manifest.get("source_label") != source_path.name:
            raise RuntimeError("artifact manifest source_label does not match the source JSON filename")
        if str(manifest.get("source_sha256", "")).upper() != _file_sha256(source_path):
            raise RuntimeError("artifact manifest source_sha256 does not match the source JSON")
        benchmark = manifest.get("teaching_exemplar_benchmark")
        if not isinstance(benchmark, dict):
            raise RuntimeError("artifact manifest teaching_exemplar_benchmark must be an object")
        if benchmark.get("status") == "not_provided":
            expected_capability = "2.3-compatible" if source_contract_version == "2.3" else "2.2-compatible"
            if benchmark != {"status": "not_provided"} or manifest.get("lesson_skill_capability") != expected_capability:
                raise RuntimeError("missing Benchmark Authorization must use the source contract compatibility block")
            if manifest.get("benchmark_authorization_path") is not None or (root / "benchmark-authorization.json").exists():
                raise RuntimeError("artifact contains Benchmark Authorization data but declares not_provided")
        else:
            if manifest.get("lesson_skill_capability") != "2.3-benchmark-linked":
                raise RuntimeError("Benchmark Authorization requires lesson_skill_capability=2.3-benchmark-linked")
            authorization_path = _artifact_relative_path(root, manifest.get("benchmark_authorization_path"))
            if (
                authorization_path is None
                or authorization_path != (root / "benchmark-authorization.json").resolve()
                or authorization_path.is_symlink()
                or not authorization_path.is_file()
            ):
                raise RuntimeError("benchmark-authorization.json is missing or outside the final artifact directory")
            authorization_sha256 = _file_sha256(authorization_path)
            if str(benchmark.get("benchmark_authorization_sha256", "")).upper() != authorization_sha256:
                raise RuntimeError("artifact manifest Benchmark Authorization SHA-256 mismatch")
            try:
                authorization = json.loads(authorization_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Benchmark Authorization could not be read: {exc}") from exc
            from benchmark_authorization import validate_authorization_payload

            source_final_digest = str((source_data.get("authoring_provenance") or {}).get("final_content_sha256", ""))
            authorization_errors = validate_authorization_payload(
                authorization,
                source_lesson_content_sha256=_file_sha256(source_path),
                source_final_content_sha256=source_final_digest,
            )
            if authorization_errors:
                raise RuntimeError("Benchmark Authorization validation failed: " + "; ".join(authorization_errors))
            from benchmark_authorization import validate_manifest_benchmark_binding

            binding_errors = validate_manifest_benchmark_binding(manifest, authorization, authorization_sha256)
            if binding_errors:
                raise RuntimeError("; ".join(binding_errors))
    is_current_contract = source_contract_version in {"2.2", "2.3"}
    if manifest.get("course_name") != source_data.get("course_name") or manifest.get("major") != source_data.get("major"):
        raise RuntimeError("artifact manifest course identity does not match the source JSON")
    source_lessons = source_data.get("lessons") if isinstance(source_data.get("lessons"), list) else []
    source_lesson_hours = sum(
        (float(lesson.get("hours", 0)) for lesson in source_lessons if isinstance(lesson, dict)),
        0.0,
    )
    try:
        manifest_lesson_hours = float(manifest.get("lesson_hours"))
    except (TypeError, ValueError):
        manifest_lesson_hours = -1.0
    if manifest_lesson_hours != source_lesson_hours:
        raise RuntimeError("artifact manifest lesson_hours do not match the source JSON")
    reference_evidence = _artifact_relative_path(root, manifest.get("reference_evidence_path"))
    if reference_evidence is None or reference_evidence.is_symlink() or not reference_evidence.is_file():
        raise RuntimeError("reference-evidence.json is missing from the final artifact directory")
    if is_current_contract and not isinstance(manifest.get("reference_evidence_sha256"), str):
        raise RuntimeError("artifact manifest reference_evidence_sha256 is required")
    if is_current_contract and not re.fullmatch(r"[0-9a-fA-F]{64}", manifest["reference_evidence_sha256"]):
        raise RuntimeError("artifact manifest reference_evidence_sha256 must be 64 hex characters")
    if manifest.get("reference_evidence_sha256") and str(manifest["reference_evidence_sha256"]).upper() != _file_sha256(reference_evidence):
        raise RuntimeError("artifact manifest reference-evidence SHA-256 mismatch")
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        raise RuntimeError("artifact manifest artifacts must be a list")
    if len(records) != len(source_lessons):
        raise RuntimeError("artifact manifest must contain exactly one record for every source Lesson")
    qa_path = _artifact_relative_path(root, manifest.get("qa_report_path"))
    if qa_path is None or not qa_path.is_file():
        raise RuntimeError("qa-report.json is missing from the final artifact directory")
    try:
        qa_report = json.loads(qa_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"qa-report.json could not be read for artifact verification: {exc}") from exc
    if not isinstance(qa_report, dict):
        raise RuntimeError("qa-report.json must contain an object")
    if manifest.get("qa_status") != qa_report.get("status"):
        raise RuntimeError("artifact manifest qa_status does not match the QA report")
    if is_current_contract and qa_report.get("status") != "passed":
        raise RuntimeError("Content Contract 2.2/2.3 artifact publication requires qa status=passed")
    render = qa_report.get("render") if isinstance(qa_report.get("render"), dict) else {}
    render_status = render.get("status")
    if manifest.get("render_status") != render_status or (is_current_contract and render_status not in {"passed", "not_executed"}):
        raise RuntimeError("artifact manifest render_status does not match eligible QA render evidence")
    if qa_report.get("artifact_manifest") not in (None, "artifact-manifest.json"):
        raise RuntimeError("QA report artifact_manifest must point to artifact-manifest.json")
    is_final_qa_report = qa_report.get("artifact_manifest") == "artifact-manifest.json"

    require_retained_pdf = render_status == "passed"
    expected_docx_names = [
        lesson_filename(index, str(lesson.get("unit", "")), str(lesson.get("task", "")))
        for index, lesson in enumerate(source_lessons, start=1)
        if isinstance(lesson, dict)
    ]
    if len(expected_docx_names) != len(source_lessons):
        raise RuntimeError("source Lesson entries must be objects")
    actual_docx_paths = list(root.glob("*.docx"))
    if (
        len(actual_docx_paths) != len(expected_docx_names)
        or {path.name for path in actual_docx_paths} != set(expected_docx_names)
        or any(path.is_symlink() or not path.is_file() for path in actual_docx_paths)
    ):
        raise RuntimeError("final DOCX inventory does not match source Lesson count")
    qa_page_counts = render.get("page_counts") if isinstance(render.get("page_counts"), dict) else {}
    qa_page_total = render.get("page_count")
    if require_retained_pdf:
        if render.get("files_checked") != len(expected_docx_names) or set(qa_page_counts) != set(expected_docx_names):
            raise RuntimeError("QA render must account for exactly one page count per Lesson DOCX")
        if any(type(qa_page_counts[name]) is not int or qa_page_counts[name] <= 0 for name in expected_docx_names):
            raise RuntimeError("QA render page counts must be positive integers")
        if type(qa_page_total) is not int or qa_page_total != sum(qa_page_counts.values()):
            raise RuntimeError("QA render total page count is inconsistent")
    else:
        if render.get("requested") is True:
            raise RuntimeError("a requested render that was not executed is not eligible for publication")
        if qa_page_counts or qa_page_total not in (None, 0):
            raise RuntimeError("unrendered QA must not claim rendered page counts")

    page_total = 0
    seen_docx_paths: set[str] = set()
    seen_pdf_paths: set[str] = set()
    expected_pdf_names = {f"{Path(name).stem}.pdf" for name in expected_docx_names}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise RuntimeError(f"artifact manifest artifacts[{index}] is not an object")
        docx_path = _artifact_relative_path(root, record.get("final_docx_path"))
        pdf_path = _artifact_relative_path(root, record.get("final_pdf_path"))
        expected_docx_name = expected_docx_names[index]
        if record.get("lesson_id") != source_lessons[index].get("lesson_id"):
            raise RuntimeError(f"artifact manifest artifacts[{index}] lesson_id does not match source Lesson")
        if (
            docx_path is None
            or docx_path.is_symlink()
            or not docx_path.is_file()
            or docx_path.parent != root.resolve()
            or docx_path.name != expected_docx_name
        ):
            raise RuntimeError(f"artifact manifest artifacts[{index}] final DOCX is missing")
        try:
            record_hours = float(record.get("lesson_hours"))
            source_hours = float(source_lessons[index].get("hours"))
        except (TypeError, ValueError):
            raise RuntimeError(f"artifact manifest artifacts[{index}] lesson_hours are invalid") from None
        if record_hours != source_hours:
            raise RuntimeError(f"artifact manifest artifacts[{index}] lesson_hours do not match the source Lesson")
        docx_rel = _relative_posix(docx_path, root)
        if docx_rel in seen_docx_paths:
            raise RuntimeError("artifact manifest maps more than one Lesson to the same DOCX")
        seen_docx_paths.add(docx_rel)
        if _file_sha256(docx_path) != str(record.get("final_docx_sha256", "")).upper():
            raise RuntimeError(f"artifact manifest artifacts[{index}] final DOCX SHA-256 mismatch")
        if not require_retained_pdf:
            if record.get("final_pdf_path") is not None or record.get("final_pdf_sha256") is not None or record.get("actual_pdf_page_count") is not None:
                raise RuntimeError("unrendered artifact records must not claim retained PDF evidence")
            continue
        if pdf_path is None or pdf_path.is_symlink() or not pdf_path.is_file():
            raise RuntimeError(f"artifact manifest artifacts[{index}] final PDF is missing")
        if pdf_path.parent != (root / "render" / "pdf").resolve():
            raise RuntimeError(f"artifact manifest artifacts[{index}] PDF is outside render/pdf")
        if pdf_path.name != f"{Path(expected_docx_name).stem}.pdf":
            raise RuntimeError(f"artifact manifest artifacts[{index}] PDF name does not match its DOCX")
        pdf_rel = _relative_posix(pdf_path, root)
        if pdf_rel in seen_pdf_paths:
            raise RuntimeError("artifact manifest maps more than one Lesson to the same PDF")
        seen_pdf_paths.add(pdf_rel)
        if _file_sha256(pdf_path) != str(record.get("final_pdf_sha256", "")).upper():
            raise RuntimeError(f"artifact manifest artifacts[{index}] final PDF SHA-256 mismatch")
        actual_pages = pdf_page_count(pdf_path)
        declared_pages = record.get("actual_pdf_page_count")
        if type(declared_pages) is not int or declared_pages <= 0 or actual_pages != declared_pages:
            raise RuntimeError(
                f"artifact manifest artifacts[{index}] PDF page count mismatch: declared={declared_pages}, actual={actual_pages}"
            )
        if qa_page_counts.get(expected_docx_name) != actual_pages:
            raise RuntimeError(f"artifact manifest artifacts[{index}] page count does not match QA render evidence")
        page_total += actual_pages
    if require_retained_pdf and expected_docx_names:
        pdf_dir = root / "render" / "pdf"
        if pdf_dir.is_symlink() or not pdf_dir.is_dir():
            raise RuntimeError("retained render/pdf directory is missing or is a symbolic link")
        actual_pdf_paths = [path for path in pdf_dir.iterdir() if path.suffix.lower() == ".pdf"]
        if (
            len(actual_pdf_paths) != len(expected_pdf_names)
            or {path.name for path in actual_pdf_paths} != expected_pdf_names
            or any(path.is_symlink() or not path.is_file() for path in actual_pdf_paths)
        ):
            raise RuntimeError("retained PDF inventory does not match source Lesson count")
    elif manifest.get("actual_pdf_page_count") != 0:
        raise RuntimeError("unrendered artifact manifest must have zero retained PDF pages")
    if type(manifest.get("actual_pdf_page_count")) is not int or manifest.get("actual_pdf_page_count") != page_total:
        raise RuntimeError("artifact manifest actual_pdf_page_count does not equal retained PDF page-count sum")
    if len(records) == 1:
        record = records[0]
        for path_field, sha_field in (
            ("final_docx_path", "final_docx_sha256"),
            ("final_pdf_path", "final_pdf_sha256"),
        ):
            if manifest.get(path_field) != record.get(path_field) or manifest.get(sha_field) != record.get(sha_field):
                raise RuntimeError(f"artifact manifest top-level {path_field}/{sha_field} does not match its record")
    elif any(
        manifest.get(field) is not None
        for field in ("final_docx_path", "final_docx_sha256", "final_pdf_path", "final_pdf_sha256")
    ):
        raise RuntimeError("multi-Lesson artifact manifests must not claim a singular top-level artifact")
    if is_current_contract and is_final_qa_report:
        if "pdf_files" in render:
            raise RuntimeError("final QA report must not retain transient absolute pdf_files paths")
        qa_artifacts = render.get("pdf_artifacts")
        expected_qa_artifact_count = len(records) if require_retained_pdf else 0
        if not isinstance(qa_artifacts, list) or len(qa_artifacts) != expected_qa_artifact_count:
            raise RuntimeError("final QA report pdf_artifacts count does not match retained render evidence")
        for index, (qa_artifact, record) in enumerate(zip(qa_artifacts, records)):
            if not isinstance(qa_artifact, dict):
                raise RuntimeError(f"final QA report pdf_artifacts[{index}] is not an object")
            if qa_artifact.get("docx_path") != record.get("final_docx_path"):
                raise RuntimeError(f"final QA report pdf_artifacts[{index}] DOCX path does not match the manifest")
            if qa_artifact.get("final_pdf_path") != record.get("final_pdf_path"):
                raise RuntimeError(f"final QA report pdf_artifacts[{index}] PDF path does not match the manifest")
            if qa_artifact.get("actual_pdf_page_count") != record.get("actual_pdf_page_count"):
                raise RuntimeError(f"final QA report pdf_artifacts[{index}] page count does not match the manifest")
    digest = manifest.get("reviewed_content_digest")
    if is_current_contract:
        if not isinstance(digest, dict):
            raise RuntimeError("artifact manifest reviewed_content_digest is required")
        for field in ("source_final_content_sha256", "packaged_final_content_sha256"):
            if not isinstance(digest.get(field), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest[field]):
                raise RuntimeError(f"reviewed_content_digest.{field} must be 64 hex characters")
        if digest.get("match") is not True or digest["source_final_content_sha256"].upper() != digest["packaged_final_content_sha256"].upper():
            raise RuntimeError("reviewed_content_digest must match source and packaged final content")
    if isinstance(digest, dict) and "match" in digest and not digest.get("match"):
        raise RuntimeError("packaged final content digest does not match authoring provenance")
    production_status = None
    if is_current_contract:
        production_status = "production_pass" if require_retained_pdf and expected_docx_names else "structural_pass"
        if manifest.get("production_status") not in (None, production_status):
            raise RuntimeError(
                "artifact manifest production_status is inconsistent with verified artifact evidence: "
                f"declared={manifest.get('production_status')!r}, expected={production_status!r}"
            )
        qa_production_status = qa_report.get("production_status")
        if qa_production_status not in (None, "structural_pass", production_status):
            raise RuntimeError("QA report production_status is invalid or inconsistent with verified artifact evidence")
        if qa_report.get("artifact_manifest") == "artifact-manifest.json" and qa_production_status not in (None, production_status):
            raise RuntimeError("final QA report production_status does not match verified artifact evidence")
    return production_status


def _verify_artifact_manifest(root: Path, manifest: dict[str, Any], source_path: Path) -> str | None:
    """Backward-compatible private entrypoint for the shared read-only verifier."""
    return verify_artifact_manifest(root, manifest, source_path)


def _unique_backup_path(out_dir: Path) -> Path:
    for _ in range(100):
        candidate = out_dir.parent / f"_{out_dir.name}_backup_{uuid.uuid4().hex[:12]}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Unable to allocate a backup path beside {out_dir}")


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _cleanup_path(path: Path, label: str) -> str | None:
    """Attempt cleanup without hiding a primary generation or commit error."""

    try:
        if path.exists() or path.is_symlink():
            _remove_path(path)
    except Exception as exc:  # pragma: no cover - filesystem failures vary by platform
        return f"cleanup failed for {label}: {exc}; residual path: {path}"
    return None


def _cleanup_empty_directory(path: Path, label: str) -> str | None:
    try:
        if path.exists():
            path.rmdir()
    except Exception as exc:  # pragma: no cover - filesystem failures vary by platform
        return f"cleanup failed for {label}: {exc}; residual path: {path}"
    return None


def atomic_commit_candidate(
    candidate: Path, out_dir: Path, backup_existing: bool,
    post_commit_validate: Callable[[Path], None] | None = None,
) -> Path | None:
    """Publish through the shared transaction, including final validation."""
    return _commit_candidate_transaction(candidate, out_dir, backup_existing, post_commit_validate)


def _unique_file_backup_path(path: Path) -> Path:
    for _ in range(100):
        candidate = path.parent / f"_{path.name}_backup_{uuid.uuid4().hex[:12]}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise FileExistsError(f"Unable to allocate a backup path beside {path}")


def _best_effort_post_commit_cleanup(path: Path | None, label: str) -> str | None:
    """Clean an old backup after publication without changing its outcome."""

    if path is None:
        return None
    try:
        _remove_path(path)
    except Exception as exc:  # pragma: no cover - filesystem failures vary by platform
        return f"cleanup failed for {label}: {exc}; residual backup path: {path}"
    return None


def atomic_commit_candidate_with_external_qa(
    candidate: Path,
    out_dir: Path,
    external_candidate: Path,
    external_qa: Path,
    backup_existing: bool,
    post_commit_validate: Callable[[Path], None] | None = None,
) -> Path | None:
    """Commit output and an external QA report, restoring both on any failure."""
    return _commit_candidate_transaction(
        candidate, out_dir, backup_existing, post_commit_validate, external_candidate, external_qa,
    )


def _commit_candidate_transaction(
    candidate: Path, out_dir: Path, backup_existing: bool,
    post_commit_validate: Callable[[Path], None] | None,
    external_candidate: Path | None = None, external_qa: Path | None = None,
) -> Path | None:
    """Keep displaced paths recoverable until post-publication validation succeeds."""

    displaced_output: Path | None = None
    displaced_qa: Path | None = None
    output_swapped = False
    qa_swapped = False
    try:
        if out_dir.exists():
            if not out_dir.is_dir():
                raise FileExistsError(f"Output path is not a directory: {out_dir}")
            if any(out_dir.iterdir()) and not backup_existing:
                raise FileExistsError(f"Output directory is not empty: {out_dir}")
            displaced_output = _unique_backup_path(out_dir)
            os.replace(str(out_dir), str(displaced_output))
        os.replace(str(candidate), str(out_dir))
        output_swapped = True

        if external_qa is not None and (external_qa.exists() or external_qa.is_symlink()):
            if external_qa.is_dir():
                raise FileExistsError(f"External QA report path must be a file, not a directory: {external_qa}")
            displaced_qa = _unique_file_backup_path(external_qa)
            os.replace(str(external_qa), str(displaced_qa))
        if external_qa is not None:
            os.replace(str(external_candidate), str(external_qa))
            qa_swapped = True

        if post_commit_validate is not None:
            post_commit_validate(out_dir)

    except BaseException as commit_error:
        rollback_errors: list[str] = []

        def rollback(action: str, callback) -> None:
            try:
                callback()
            except Exception as exc:  # pragma: no cover - injected filesystem failures vary by platform
                rollback_errors.append(f"{action}: {exc}")

        if qa_swapped and (external_qa.exists() or external_qa.is_symlink()):
            rollback("remove new external QA", lambda: _remove_path(external_qa))
        if displaced_qa is not None and displaced_qa.exists() and not external_qa.exists():
            rollback("restore external QA", lambda: os.replace(str(displaced_qa), str(external_qa)))
        if output_swapped and (out_dir.exists() or out_dir.is_symlink()):
            rollback("remove new output", lambda: _remove_path(out_dir))
        if displaced_output is not None and displaced_output.exists() and not out_dir.exists():
            rollback("restore output", lambda: os.replace(str(displaced_output), str(out_dir)))

        if rollback_errors:
            raise RuntimeError(
                "External QA commit failed and rollback failed: "
                + "; ".join(rollback_errors)
                + f"; original error: {commit_error}"
            ) from commit_error
        raise


    # Publication is complete only after final validation succeeds. Cleanup
    # is intentionally outside rollback: a filesystem failure while
    # deleting an old backup must leave the new output and QA available.
    cleanup_diagnostics = []
    if displaced_output is not None and not backup_existing:
        cleanup_error = _best_effort_post_commit_cleanup(displaced_output, "old output backup")
        if cleanup_error:
            cleanup_diagnostics.append(cleanup_error)
        else:
            displaced_output = None
    if displaced_qa is not None:
        cleanup_error = _best_effort_post_commit_cleanup(displaced_qa, "old external QA backup")
        if cleanup_error:
            cleanup_diagnostics.append(cleanup_error)
        else:
            displaced_qa = None
    for diagnostic in cleanup_diagnostics:
        print(f"WARNING: {diagnostic}", file=sys.stderr)
    return displaced_output

def main(argv=None, *, o2_run=None) -> None:
    def revalidate_o2():
        if o2_run is not None:
            from run_lesson_pipeline import validate_run_authorized
            if o2_run.get("orchestrator_version") != "2.0" or o2_run.get("mode") != "PRODUCTION" or o2_run["state"]["current_state"] != "PRODUCTION_AUTHORIZED":
                raise ValueError("O2 generation requires current PRODUCTION_AUTHORIZED run")
            validate_run_authorized(o2_run)
    revalidate_o2()
    parser = argparse.ArgumentParser(description="Generate template-matched Chinese lesson plan DOCX files.")
    parser.add_argument("--template", default="")
    parser.add_argument("--tasks-json", required=True)
    parser.add_argument(
        "--source-truth",
        type=Path,
        help="Source Truth manifest binding the frozen course outline; required by canonical production orchestration",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--backup-existing", action="store_true")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--benchmark-authorization", type=Path)
    parser.add_argument("--benchmark-catalog", type=Path)
    parser.add_argument("--benchmark-split", type=Path)
    parser.add_argument("--benchmark-authoring-pack", type=Path)
    parser.add_argument("--benchmark-authoring-selection", type=Path)
    parser.add_argument("--benchmark-holdout-pack", type=Path)
    parser.add_argument("--benchmark-holdout-selection", type=Path)
    parser.add_argument("--benchmark-review", type=Path)
    parser.add_argument("--benchmark-lesson-reviews-dir", type=Path)
    parser.add_argument("--benchmark-previous-review", type=Path)
    parser.add_argument("--benchmark-previous-lesson-reviews-dir", type=Path)
    parser.add_argument("--benchmark-previous-content", type=Path)
    parser.add_argument(
        "--benchmark-mode",
        choices=("none", "optional", "required"),
        default="none",
        help="Require and record full-linkage Benchmark Authorization for 2.3 production provenance",
    )
    parser.add_argument("--skip-template-validation", action="store_true")
    parser.add_argument("--skip-output-validation", action="store_true")
    parser.add_argument("--render", action="store_true", help="Render validated DOCX files and retain verified PDFs for artifact publication / production verification")
    parser.add_argument(
        "--run-id",
        default="",
        help="Stable smoke/artifact run identifier; generated when omitted",
    )
    parser.add_argument(
        "--allow-test-fixture-authoring",
        action="store_true",
        help="Test-only escape hatch; requires LESSON_ALLOW_TEST_FIXTURE_AUTHORING=1",
    )
    parser.add_argument("--qa-report", default="")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Explicitly enable the non-production 2.0/2.1 compatibility path",
    )
    args = parser.parse_args(argv)
    if o2_run is not None:
        from run_lesson_pipeline import path_of
        from path_safety import paths_equal
        if not paths_equal(args.tasks_json, path_of(o2_run, "content")) or not args.source_truth or not paths_equal(args.source_truth, path_of(o2_run, "source_truth")):
            raise ValueError("O2 generator inputs differ from authorized candidate")
        if args.run_id != o2_run["state"]["pipeline_run_id"] or not args.render or args.legacy or args.skip_output_validation or args.skip_template_validation or args.allow_test_fixture_authoring:
            raise ValueError("O2 generation requires exact run, render and all existing gates")
        canonical_template = manifest_template_path(load_manifest(DEFAULT_MANIFEST))
        if (args.manifest and not paths_equal(args.manifest, DEFAULT_MANIFEST)) or (args.template and not paths_equal(args.template, canonical_template)) or not paths_equal(args.schema, DEFAULT_SCHEMA):
            raise ValueError("O2 generation requires the canonical template, manifest and schema")
        from lifecycle_digest import read_json_object
        disposition, _ = read_json_object(path_of(o2_run, "benchmark_disposition"), "O2 Benchmark disposition")
        if disposition["benchmark"]["disposition"] == "BENCHMARK_REVIEW_COMPLETE":
            if args.benchmark_mode != "required" or args.benchmark_authorization is None or not paths_equal(args.benchmark_authorization, path_of(o2_run, "benchmark_authorization")):
                raise ValueError("O2 generation must retain the authorized required Benchmark branch")
        elif args.benchmark_mode != "none":
            raise ValueError("O2 generation Benchmark mode differs from the authorized disposition")
    if (args.skip_template_validation or args.skip_output_validation) and os.environ.get(UNSAFE_VALIDATION_SKIP_ENV) != "1":
        raise RuntimeError("Unsafe validation bypass is disabled.")
    allow_test_fixture_authoring = args.allow_test_fixture_authoring
    if allow_test_fixture_authoring and os.environ.get(TEST_FIXTURE_AUTHORING_ENV) != "1":
        raise RuntimeError("Test-fixture authoring bypass is disabled for production generation.")

    template, manifest_path, manifest = resolve_template_package(
        args.template or None,
        args.manifest or None,
    )
    ensure_supported_major(manifest)
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    out_dir = Path(args.output_dir).expanduser().absolute()
    source_path = Path(args.tasks_json).expanduser().resolve()
    source_truth_path = Path(args.source_truth).expanduser().absolute() if args.source_truth is not None else None
    source_truth_local_paths: list[Path] = []
    schema_path = Path(args.schema).expanduser().resolve()
    benchmark_authorization_path = (
        Path(args.benchmark_authorization).expanduser().absolute()
        if args.benchmark_authorization is not None
        else None
    )
    benchmark_evidence_arguments = {
        "--benchmark-catalog": args.benchmark_catalog,
        "--benchmark-split": args.benchmark_split,
        "--benchmark-authoring-pack": args.benchmark_authoring_pack,
        "--benchmark-authoring-selection": args.benchmark_authoring_selection,
        "--benchmark-holdout-pack": args.benchmark_holdout_pack,
        "--benchmark-holdout-selection": args.benchmark_holdout_selection,
        "--benchmark-review": args.benchmark_review,
        "--benchmark-lesson-reviews-dir": args.benchmark_lesson_reviews_dir,
        "--benchmark-previous-review": args.benchmark_previous_review,
        "--benchmark-previous-lesson-reviews-dir": args.benchmark_previous_lesson_reviews_dir,
        "--benchmark-previous-content": args.benchmark_previous_content,
    }
    any_benchmark_evidence = any(value is not None for value in benchmark_evidence_arguments.values())
    if args.benchmark_mode == "required" and benchmark_authorization_path is None:
        raise ValueError("--benchmark-mode required needs --benchmark-authorization")
    if args.benchmark_mode == "none" and benchmark_authorization_path is not None:
        raise ValueError("--benchmark-authorization requires --benchmark-mode optional or required")
    if benchmark_authorization_path is None and any_benchmark_evidence:
        raise ValueError("Benchmark evidence paths require --benchmark-authorization")
    if benchmark_authorization_path is not None:
        required_evidence_arguments = {
            name: benchmark_evidence_arguments[name]
            for name in (
                "--benchmark-catalog", "--benchmark-split", "--benchmark-authoring-pack",
                "--benchmark-authoring-selection", "--benchmark-holdout-pack",
                "--benchmark-holdout-selection", "--benchmark-review",
                "--benchmark-lesson-reviews-dir",
            )
        }
        missing_evidence = [name for name, value in required_evidence_arguments.items() if value is None]
        if missing_evidence:
            raise ValueError("Benchmark Authorization requires full evidence: " + ", ".join(missing_evidence))
    if benchmark_authorization_path is not None:
        from exemplar_contract import assert_distinct_file_paths

        benchmark_distinct_paths: dict[str, Path] = {
            "Lesson Content": source_path,
            "schema": schema_path,
            "Benchmark Authorization": benchmark_authorization_path,
            "Output directory": out_dir,
        }
        benchmark_distinct_paths.update(
            {name: value.expanduser().resolve() for name, value in benchmark_evidence_arguments.items() if value is not None}
        )
        assert_distinct_file_paths(
            benchmark_distinct_paths,
            outputs={"Benchmark Authorization", "Output directory"},
        )
    with source_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)
    if meta.get("content_contract_version") not in {"2.2", "2.3"} and not args.legacy:
        raise ValueError(
            "Lesson Content Contract 2.2 or 2.3 is required for production generation; "
            "legacy 2.0/2.1 input requires the explicit --legacy flag."
        )
    validate_content_v2_input(
        meta,
        schema_path,
        allow_test_fixture=allow_test_fixture_authoring,
    )
    if meta.get("content_contract_version") in {"2.2", "2.3"}:
        meta = apply_reviewed_lesson_content(meta)
    scope_report: dict[str, Any] | None = None
    if source_truth_path is not None:
        from course_scope_grounding import (
            format_scope_failures,
            load_frozen_course_outline,
            validate_course_scope_grounding,
        )
        from source_truth import source_truth_local_file_paths

        scope_report = validate_course_scope_grounding(
            meta,
            source_truth_path,
            content_path=source_path,
            require_local_outline=True,
        )
        if scope_report.get("status") != "passed":
            details = "; ".join(format_scope_failures(scope_report)[:8])
            raise ValueError("course-scope grounding failed before candidate creation: " + details)
        frozen_outline = load_frozen_course_outline(
            source_truth_path,
            require_local_bytes=True,
            content_path=source_path,
        )
        source_truth_local_paths = list(
            source_truth_local_file_paths(frozen_outline.source_truth, source_truth_path).values()
        )
    benchmark_authorization: dict[str, Any] | None = None
    benchmark_authorization_bytes: bytes | None = None
    benchmark_authorization_sha256: str | None = None
    if benchmark_authorization_path is not None:
        if meta.get("content_contract_version") not in {"2.2", "2.3"}:
            raise ValueError("Benchmark Authorization is supported with Lesson Content Contract 2.2 or 2.3")
        try:
            benchmark_authorization_bytes = benchmark_authorization_path.read_bytes()
            benchmark_authorization = json.loads(benchmark_authorization_bytes.decode("utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Benchmark Authorization could not be read: {exc}") from exc
        if not isinstance(benchmark_authorization, dict):
            raise ValueError("Benchmark Authorization must be a JSON object")
        benchmark_authorization_sha256 = hashlib.sha256(benchmark_authorization_bytes).hexdigest()
        from benchmark_authorization import derive_benchmark_authorization_claims, validate_authorization_matches_claims

        derived_claims = derive_benchmark_authorization_claims(
            lesson_content_path=source_path,
            catalog_path=args.benchmark_catalog.expanduser().resolve(),
            split_path=args.benchmark_split.expanduser().resolve(),
            authoring_pack_path=args.benchmark_authoring_pack.expanduser().resolve(),
            authoring_selection_path=args.benchmark_authoring_selection.expanduser().resolve(),
            holdout_pack_path=args.benchmark_holdout_pack.expanduser().resolve(),
            holdout_selection_path=args.benchmark_holdout_selection.expanduser().resolve(),
            benchmark_review_path=args.benchmark_review.expanduser().resolve(),
            lesson_reviews_dir=args.benchmark_lesson_reviews_dir.expanduser().resolve(),
            schema_path=schema_path,
            previous_lesson_content_path=args.benchmark_previous_content.expanduser().resolve() if args.benchmark_previous_content else None,
            previous_review_path=args.benchmark_previous_review.expanduser().resolve() if args.benchmark_previous_review else None,
            previous_lesson_reviews_dir=args.benchmark_previous_lesson_reviews_dir.expanduser().resolve() if args.benchmark_previous_lesson_reviews_dir else None,
            allow_test_fixture=allow_test_fixture_authoring,
        )
        authorization_errors = validate_authorization_matches_claims(benchmark_authorization, derived_claims)
        if authorization_errors:
            raise ValueError("Benchmark Authorization validation failed: " + "; ".join(authorization_errors))
    lessons = meta["lessons"]
    run_id = str(
        args.run_id
        or f"lesson-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    ).strip()
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("--run-id must be 6-96 characters of letters, digits, dot, underscore, or hyphen")

    package_roots = [manifest_path.parent]
    base_manifest = manifest.get("template", {}).get("base_manifest")
    if base_manifest:
        package_roots.append((manifest_path.parent / str(base_manifest)).resolve().parent)
    protected_paths = lesson_protected_paths(
        skill_dir=SKILL_DIR,
        source=source_path,
        schema=schema_path,
        template=template,
        manifest=manifest_path,
        package_roots=package_roots,
    )
    if source_truth_path is not None:
        protected_paths.append(source_truth_path)
        protected_paths.extend(source_truth_local_paths)
    if benchmark_authorization_path is not None:
        protected_paths.append(benchmark_authorization_path)
    assert_output_path_safe(out_dir, protected_paths)
    requested_qa = Path(args.qa_report).expanduser().resolve() if args.qa_report else None
    internal_qa = out_dir / "qa-report.json"
    external_qa = None
    qa_parent_created = False
    if requested_qa is not None:
        same_as_internal = paths_equal(requested_qa, internal_qa)
        if not same_as_internal:
            external_qa = assert_external_qa_path_safe(requested_qa, out_dir, protected_paths)
    if out_dir.exists() and not out_dir.is_dir():
        raise FileExistsError(f"Output path is not a directory: {out_dir}")
    if out_dir.exists() and any(out_dir.iterdir()) and not args.backup_existing:
        raise FileExistsError(f"Output directory is not empty: {out_dir}")

    template_warnings: list[str] = []
    if not args.skip_template_validation:
        template_report = validate_template(template, manifest_path)
        template_warnings = template_report.get("warnings", [])
        for warning in template_warnings:
            print(f"WARNING: {warning}")

    revalidate_o2()
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.candidate-", dir=str(out_dir.parent)))
    assert_output_path_safe(candidate, protected_paths)
    external_candidate: Path | None = None
    operation_error: BaseException | None = None
    try:
        content_quality = validate_content_quality(
            meta,
            manifest,
            source_truth_path=str(source_truth_path) if source_truth_path is not None else None,
            content_path=str(source_path),
            require_local_outline=source_truth_path is not None,
        )
        practice_contract = meta.get("practice_task_contract")
        artifact_plan = meta.get("artifact_plan") or {}
        if meta.get("content_contract_version") in {"2.2", "2.3"}:
            writes_practice_handoff = bool(artifact_plan.get("practice_work_orders"))
        else:
            writes_practice_handoff = True
        if writes_practice_handoff and isinstance(practice_contract, dict):
            (candidate / "practice-task-contract.json").write_text(
                json.dumps(practice_contract, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        generated_filenames: list[str] = []
        for seq, item in enumerate(lessons, 1):
            generated_filenames.append(build_lesson(template, candidate, meta, item, seq, manifest).name)
        if benchmark_authorization_bytes is not None:
            (candidate / "benchmark-authorization.json").write_bytes(benchmark_authorization_bytes)
        candidate_qa = candidate / "qa-report.json"
        if not args.skip_output_validation:
            report = validate_outputs(
                candidate,
                meta,
                manifest,
                schema_path,
                candidate_qa,
                template=template,
                custom_template=bool(args.template),
                template_validation=not args.skip_template_validation,
                template_warnings=template_warnings,
                render=args.render,
                render_pdf_dir=(candidate / "render" / "pdf") if args.render else None,
                allow_test_fixture_authoring=allow_test_fixture_authoring,
                source_truth_path=source_truth_path,
                content_path=source_path,
            )
        else:
            report = write_skipped_report(
                candidate,
                meta,
                manifest,
                candidate_qa,
                schema_path,
                template_path=template,
                custom_template=bool(args.template),
                engine="python-docx",
                template_validation=not args.skip_template_validation,
                warnings=template_warnings,
                render=args.render,
                render_pdf_dir=(candidate / "render" / "pdf") if args.render else None,
                allow_test_fixture_authoring=allow_test_fixture_authoring,
                source_truth_path=source_truth_path,
                content_path=source_path,
            )
        if meta.get("content_contract_version") in {"2.2", "2.3"} and report.get("production_status") == "failed":
            raise RuntimeError("Content Contract 2.2/2.3 output did not pass production readiness checks")
        _stable_render_artifacts(report, candidate, generated_filenames)
        created_at = datetime.now(timezone.utc).isoformat()
        reference_evidence_path = candidate / "reference-evidence.json"
        reference_evidence_path.write_text(
            json.dumps(_reference_evidence_payload(meta, source_path, run_id), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_data = _build_artifact_manifest(
            candidate,
            meta,
            report,
            generated_filenames,
            run_id,
            source_path,
            created_at,
            benchmark_authorization=benchmark_authorization,
            benchmark_authorization_sha256=benchmark_authorization_sha256,
        )
        if o2_run is not None:
            from lifecycle_digest import read_json_object, sha256_bytes
            from run_lesson_pipeline import path_of
            authorization, raw = read_json_object(path_of(o2_run, "production_authorization"), "O2 PA")
            (candidate / "production-authorization.json").write_bytes(raw)
            manifest_data["canonical_lifecycle"] = dict(orchestrator_version="2.0", production_authorization_sha256=sha256_bytes(raw),
                semantic_scope=authorization["semantic_scope"])
        # Production readiness is derived only after this tentative manifest's
        # files, hashes, and final page counts have all been verified.
        manifest_data.pop("production_status", None)
        artifact_manifest_path = candidate / "artifact-manifest.json"
        artifact_manifest_path.write_text(
            json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        verified_production_status = _verify_artifact_manifest(candidate, manifest_data, source_path)
        if meta.get("content_contract_version") in {"2.2", "2.3"}:
            if verified_production_status not in {"production_pass", "structural_pass"}:
                raise RuntimeError("verified Content Contract 2.2/2.3 artifacts did not produce a valid production state")
            report["production_status"] = verified_production_status
            manifest_data["production_status"] = verified_production_status
        final_qa = requested_qa or internal_qa
        report["output_dir"] = str(out_dir)
        report["qa_report"] = str(final_qa)
        report["run_id"] = run_id
        report["artifact_manifest"] = "artifact-manifest.json"
        report["reference_evidence"] = "reference-evidence.json"
        report_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        candidate_qa.write_text(report_text, encoding="utf-8")
        artifact_manifest_path.write_text(
            json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _verify_artifact_manifest(candidate, manifest_data, source_path)

        def post_commit_validate(published: Path) -> None:
            revalidate_o2()
            committed_manifest = json.loads((published / "artifact-manifest.json").read_text(encoding="utf-8"))
            _verify_artifact_manifest(published, committed_manifest, source_path)
            if external_qa is not None and _file_sha256(external_qa) != _file_sha256(published / "qa-report.json"):
                raise RuntimeError("published external QA does not match the final output QA report")

        revalidate_o2()
        if external_qa is not None:
            if not external_qa.parent.exists():
                external_qa.parent.mkdir(parents=True, exist_ok=True)
                qa_parent_created = True
            fd, external_candidate_name = tempfile.mkstemp(
                prefix=f".{external_qa.name}.candidate-",
                suffix=".tmp",
                dir=str(external_qa.parent),
            )
            os.close(fd)
            external_candidate = Path(external_candidate_name)
            external_candidate.write_text(report_text, encoding="utf-8")
            backup = atomic_commit_candidate_with_external_qa(
                candidate,
                out_dir,
                external_candidate,
                external_qa,
                args.backup_existing,
                post_commit_validate=post_commit_validate,
            )
        else:
            backup = atomic_commit_candidate(candidate, out_dir, args.backup_existing, post_commit_validate=post_commit_validate)
        for filename in generated_filenames:
            print(out_dir / filename)
        if backup is not None:
            print(f"backup={backup}")
        if meta.get("content_contract_version") in {"2.2", "2.3"}:
            print(
                f"Content Contract {meta.get('content_contract_version')} "
                f"production_status={report['production_status']} "
                f"qa_status={report['status']} "
                f"render_status={report['render']['status']} "
                f"files={report['checks']['file_count']['actual']} "
                f"total_hours={report['checks']['total_hours']['actual']:g} "
                f"qa={report['qa_report']}"
            )
        else:
            action = "skipped validation" if report["status"] == "skipped" else "validated"
            print(f"{action} files={report['checks']['file_count']['actual']} total_hours={report['checks']['total_hours']['actual']:g} qa={report['qa_report']}")
    except BaseException as exc:
        operation_error = exc
        raise
    finally:
        cleanup_diagnostics: list[str] = []
        candidate_error = _cleanup_path(candidate, "candidate directory")
        if candidate_error:
            cleanup_diagnostics.append(candidate_error)
        if external_candidate is not None:
            external_candidate_error = _cleanup_path(external_candidate, "external QA candidate")
            if external_candidate_error:
                cleanup_diagnostics.append(external_candidate_error)
        # A successful commit intentionally leaves the newly created parent
        # containing the external report.  Only remove it after a failed
        # operation, when rollback has left no committed report behind.
        if operation_error is not None and qa_parent_created and external_qa is not None and external_qa.parent.exists():
            parent_error = _cleanup_empty_directory(external_qa.parent, "external QA parent directory")
            if parent_error:
                cleanup_diagnostics.append(parent_error)
        for diagnostic in cleanup_diagnostics:
            print(f"WARNING: {diagnostic}", file=sys.stderr)
            if operation_error is not None:
                operation_error.add_note(diagnostic)


if __name__ == "__main__":
    main()
