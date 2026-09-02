"""Generate Practice Work Order Content V1 DOCX files transactionally."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from docx import Document

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from content_contract import (  # noqa: E402
    WorkOrderContractError,
    load_practice_task_contract,
    load_work_order_content,
    practice_tasks_to_content,
    safe_filename,
)
from content_quality import validate_collection, validate_content  # noqa: E402
from cross_artifact_quality import validate_cross_artifact  # noqa: E402
from validate_output import validate_document  # noqa: E402


DEFAULT_TEMPLATE = PACKAGE_ROOT / "assets" / "templates" / "practice-work-order" / "v1.0.0" / "template.docx"


def _replace_paragraph_text(paragraph: Any, text: str) -> None:
    runs = paragraph.runs
    if not runs:
        paragraph.add_run(text)
        return
    runs[0].text = text
    for run in runs[1:]:
        run.text = ""


def _replace_cell_text(cell: Any, text: str) -> None:
    paragraphs = cell.paragraphs
    if not paragraphs:
        cell.add_paragraph(text)
        return
    first = paragraphs[0]
    for child in list(first._p):
        if child.tag.endswith("}pPr"):
            continue
        first._p.remove(child)
    first.add_run(text)
    for paragraph in paragraphs[1:]:
        cell._tc.remove(paragraph._p)


def _replace_in_paragraph(paragraph: Any, old: str, new: str) -> None:
    if old not in paragraph.text:
        return
    for run in paragraph.runs:
        run.text = run.text.replace(old, new)
    if old in paragraph.text:
        _replace_paragraph_text(paragraph, paragraph.text.replace(old, new))


def _replace_in_table(table: Any, old: str, new: str) -> None:
    seen: set[int] = set()
    for row in table.rows:
        for cell in row.cells:
            identity = id(cell._tc)
            if identity in seen:
                continue
            seen.add(identity)
            for paragraph in cell.paragraphs:
                _replace_in_paragraph(paragraph, old, new)


def _format_content_description(item: dict[str, Any]) -> str:
    def joined(values: Iterable[str]) -> str:
        return "；".join(str(value).strip() for value in values if str(value).strip())

    return (
        f"{item['description'].strip()}\n"
        f"工具/材料：{joined(item['tools_or_materials'])}\n"
        f"步骤：{joined(item['steps'])}\n"
        f"交付物：{joined(item['deliverables'])}\n"
        f"验收：{joined(item['acceptance_criteria'])}"
    )


def _source_project_name(document: Any) -> str:
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    match = re.search(r"《([^》]+)》", text)
    if match:
        return match.group(1)
    for table in document.tables:
        match = re.search(r"项目实训[^\n：:]+", "\n".join(cell.text for row in table.rows for cell in row.cells))
        if match:
            return match.group(0).strip()
    return "项目实训2 设计数据库"


def _set_title_paragraphs(document: Any, old_project: str, project_name: str) -> None:
    for paragraph in document.paragraphs:
        if "学习工单" in paragraph.text:
            _replace_paragraph_text(paragraph, f"《{project_name}》学习工单")
        elif "课堂评价表-学生" in paragraph.text:
            _replace_paragraph_text(paragraph, f"《{project_name}》课堂评价表-学生")
        elif "课堂评价表-教师" in paragraph.text:
            _replace_paragraph_text(paragraph, f"《{project_name}》课堂评价表-教师")
        elif old_project in paragraph.text:
            _replace_in_paragraph(paragraph, old_project, project_name)


def _clone_task_rows(table: Any, items: list[dict[str, Any]]) -> None:
    prototype = deepcopy(table.rows[2]._tr)
    for row in list(table.rows[2:]):
        table._tbl.remove(row._tr)
    for item in items:
        table._tbl.append(deepcopy(prototype))
        row = table.rows[-1]
        _replace_cell_text(row.cells[1], item["title"])
        _replace_cell_text(row.cells[2], _format_content_description(item))
        _replace_cell_text(row.cells[3], "")
        _replace_cell_text(row.cells[4], str(item["score"]))


def _write_document(template: Path, output: Path, content: dict[str, Any]) -> None:
    document = Document(str(template))
    if len(document.tables) != 3:
        raise WorkOrderContractError("canonical template must contain exactly three top-level tables")
    old_project = _source_project_name(document)
    project_name = content["project_name"].strip()
    _set_title_paragraphs(document, old_project, project_name)
    work_table, student_table, teacher_table = document.tables
    _clone_task_rows(work_table, content["task_items"])
    metadata_parts = [
        content["course_name"],
        f"专业：{content['major']}",
        f"对象：{content['class_or_audience']}",
        f"实践任务ID：{content['practice_task_id']}",
        f"任务标题：{content.get('task_title', content['project_name'])}",
    ]
    if content.get("project_id"):
        metadata_parts.append(f"项目ID：{content['project_id']}")
    metadata_parts.extend(
        [
            f"实践学时：{content['practice_hours']}",
            content["group"]["name"],
            content["group"]["leader_placeholder"],
            content["group"]["member_placeholder"],
        ]
    )
    metadata = "\n".join(metadata_parts)
    if content.get("safety_or_compliance"):
        metadata += "\n安全/合规：" + "；".join(content["safety_or_compliance"])
    _replace_cell_text(work_table.rows[1].cells[0], metadata)
    _replace_in_table(student_table, old_project, project_name)
    _replace_in_table(teacher_table, old_project, project_name)
    document.core_properties.title = f"《{project_name}》学习工单"
    document.core_properties.subject = (
        f"Practice Task {content['practice_task_id']} / "
        f"{content.get('task_title', project_name)}"
    )
    document.core_properties.keywords = " ".join(
        value
        for value in (
            content["course_name"],
            content["practice_task_id"],
            content.get("project_id", ""),
        )
        if value
    )
    document.save(str(output))


def _render_optional(path: Path, output_dir: Path) -> dict[str, Any]:
    from render_qa import render_file

    return render_file(path, output_dir)


def generate(
    contents: list[dict[str, Any]],
    *,
    output_dir: Path,
    template: Path,
    replace: bool = False,
    render: bool = False,
) -> dict[str, Any]:
    if not template.is_file():
        raise FileNotFoundError(f"template not found: {template}")
    collection_report = validate_collection(contents)
    if collection_report["status"] != "pass":
        raise WorkOrderContractError("Content QA failed: " + "; ".join(collection_report["errors"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for content in contents:
        final = output_dir / f"{safe_filename(content['practice_task_id'])}_{safe_filename(content['project_name'])}.docx"
        if final.exists() and not replace:
            raise FileExistsError(f"output exists; use --replace to overwrite: {final}")
        fd, temporary_name = tempfile.mkstemp(prefix=f".{final.stem}-", suffix=".docx", dir=str(output_dir))
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            _write_document(template, temporary, content)
            output_report = validate_document(temporary, content)
            if output_report["status"] != "pass":
                raise WorkOrderContractError(
                    f"Output QA failed for {content['practice_task_id']}: "
                    + "; ".join(output_report["errors"])
                )
            os.replace(str(temporary), str(final))
            result: dict[str, Any] = {
                "practice_task_id": content["practice_task_id"],
                "path": str(final),
                "content_qa": validate_content(content),
                "output_qa": output_report,
            }
            if render:
                result["render"] = _render_optional(final, output_dir / "render" / final.stem)
            results.append(result)
        finally:
            if temporary.exists():
                temporary.unlink()
    return {"status": "pass", "content_qa": collection_report, "outputs": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--content-json", type=Path)
    source.add_argument("--practice-task-json", type=Path)
    parser.add_argument("--major", help="required when consuming a Lesson Practice Task Contract")
    parser.add_argument("--class-or-audience", help="required when consuming a Lesson Practice Task Contract")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        cross_reports: list[dict[str, Any]] = []
        if args.content_json:
            contents = load_work_order_content(args.content_json)
        else:
            if not args.major or not args.class_or_audience:
                raise WorkOrderContractError("--major and --class-or-audience are required for handoff input")
            handoff = load_practice_task_contract(args.practice_task_json)
            contents = practice_tasks_to_content(
                handoff,
                major=args.major,
                class_or_audience=args.class_or_audience,
            )
            for content in contents:
                cross_report = validate_cross_artifact(handoff, content)
                cross_reports.append(cross_report)
                if cross_report["status"] != "pass":
                    raise WorkOrderContractError(
                        f"Cross-Artifact QA failed for {content['practice_task_id']}: "
                        + "; ".join(cross_report["errors"])
                    )
        report = generate(
            contents,
            output_dir=args.output_dir,
            template=args.template,
            replace=args.replace,
            render=args.render,
        )
        if cross_reports:
            report["cross_artifact_qa"] = cross_reports
    except Exception as exc:
        report = {"status": "fail", "errors": [str(exc)]}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if report["status"] == "pass":
            for item in report["outputs"]:
                print(item["path"])
        else:
            for error in report["errors"]:
                print(f"ERROR: {error}", file=sys.stderr)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
