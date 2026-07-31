from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import _Cell

from package_common import DEFAULT_MANIFEST, DEFAULT_SCHEMA, ensure_supported_major, field_spec, load_manifest, manifest_template_path, validate_input
from validate_output import validate_output_dir, write_skipped_report
from validate_template import validate_template


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx"

MAX_POINTS = [3, 3, 4, 5, 5, 5, 5, 10, 10, 10, 25, 10, 5]
REMARKS = [
    ["出勤正常", "注意力较稳", "参与较积极", "规范意识较好", "质量意识较强", "安全意识较好", "习惯较好", "预习较完整", "答题较准确", "作业较认真", "实操较熟练", "展示较清楚"],
    ["基本到课", "个别环节需提醒", "能主动配合", "流程执行较规范", "能联系项目实际", "职业责任意识较好", "工具使用较规范", "线上学习较及时", "讨论质量尚可", "提交较规范", "任务完成度较高", "汇报条理较清楚"],
    ["考勤良好", "专注度尚可", "参与较自然", "记录较规范", "质量观念较到位", "能注意风险控制", "实训习惯较好", "资料阅读较完整", "关键问题掌握较好", "成果较完整", "能完成主要步骤", "演示基本清楚"],
]


def actual_cells(row):
    return [_Cell(tc, row._parent) for tc in row._tr.tc_lst]


def clear_paragraph(paragraph):
    for child in list(paragraph._p):
        if child.tag == qn("w:r"):
            paragraph._p.remove(child)


def copy_run_format(src, dst):
    dst.bold = src.bold
    dst.italic = src.italic
    dst.underline = src.underline
    dst.font.name = src.font.name
    dst.font.size = src.font.size
    if src._element.rPr is not None and src._element.rPr.rFonts is not None and dst._element.rPr is not None:
        for key in ("w:eastAsia", "w:ascii", "w:hAnsi"):
            value = src._element.rPr.rFonts.get(qn(key))
            if value:
                dst._element.rPr.rFonts.set(qn(key), value)


def set_paragraph_text(paragraph, text, align=None):
    src = paragraph.runs[0] if paragraph.runs else None
    clear_paragraph(paragraph)
    run = paragraph.add_run(str(text))
    if src is not None:
        copy_run_format(src, run)
    if align is not None:
        paragraph.alignment = align


def set_cell_text(cell, text, align=WD_ALIGN_PARAGRAPH.LEFT):
    paragraph = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    set_paragraph_text(paragraph, text, align)
    for extra in list(cell.paragraphs)[1:]:
        extra._element.getparent().remove(extra._element)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_cell_multiline(cell, text, align=WD_ALIGN_PARAGRAPH.LEFT):
    lines = str(text).splitlines() or [""]
    paragraphs = list(cell.paragraphs) if cell.paragraphs else [cell.add_paragraph()]
    while len(paragraphs) < len(lines):
        paragraph = cell.add_paragraph()
        if paragraphs[0].style is not None:
            paragraph.style = paragraphs[0].style
        paragraphs.append(paragraph)
    for paragraph, line in zip(paragraphs, lines):
        set_paragraph_text(paragraph, line, align)
    for extra in paragraphs[len(lines):]:
        extra._element.getparent().remove(extra._element)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def set_row(table, row_idx, values_by_idx):
    cells = actual_cells(table.rows[row_idx])
    for idx, value in values_by_idx.items():
        if idx < len(cells):
            writer = set_cell_multiline if "\n" in str(value) else set_cell_text
            writer(cells[idx], value)


def set_manifest_field(table, manifest: dict[str, Any], name: str, value: Any, align=WD_ALIGN_PARAGRAPH.LEFT):
    spec = field_spec(manifest, name)
    if "table" not in spec or "row" not in spec or "cell" not in spec:
        raise ValueError(f"Field {name} is not a single table-cell field")
    target_table = table if int(spec["table"]) == 0 else table._parent.tables[int(spec["table"])]
    cell = actual_cells(target_table.rows[int(spec["row"])])[int(spec["cell"])]
    writer = set_cell_multiline if spec.get("mode") in {"replace_paragraphs", "replace_multiline"} else set_cell_text
    writer(cell, value, align)


def numbered(items: list[str], limit: int | None = None) -> str:
    values = [str(x).strip() for x in items if str(x).strip()]
    if limit and len(values) > limit:
        values = values[:limit] + ["结合任务材料完成其余流程训练"]
    return "\n".join(f"{idx}. {item}" for idx, item in enumerate(values, 1))


def safe_name(text: str) -> str:
    text = re.sub(r"\s+", "", str(text))
    return re.sub(r'[\\/:*?"<>|]+', "", text)


def half_round(value: float) -> float:
    return float((Decimal(str(value)) * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)


def score_breakdown(target: float) -> list[float]:
    target_decimal = Decimal(str(target))
    target_units_decimal = target_decimal * 2
    if target_units_decimal != target_units_decimal.to_integral_value():
        raise ValueError(f"Evaluation score must use 0.5-point increments: {target}")
    target_units = int(target_units_decimal)
    scores_units = [
        int((Decimal(point) * target_decimal * 2 / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        for point in MAX_POINTS
    ]
    diff_units = target_units - sum(scores_units)
    step = 1 if diff_units > 0 else -1
    order = [10, 8, 9, 12, 2, 7, 11, 3, 4, 5, 6, 1, 0]
    while diff_units:
        changed = False
        for pos in order:
            candidate = scores_units[pos] + step
            if 0 <= candidate <= MAX_POINTS[pos] * 2:
                scores_units[pos] = candidate
                diff_units = target_units - sum(scores_units)
                changed = True
                break
        if not changed:
            break
    return [units / 2 for units in scores_units]


def add_eval_table(cell, target: float, seq: int, manifest: dict[str, Any]):
    table = cell.tables[0] if cell.tables else cell.add_table(rows=14, cols=4)
    table.style = "Table Grid"
    headers = ["评价维度", "评价要素", "得分", "备注"]
    rows = [
        ("课堂表现度\n（10）", "考勤（3）"),
        ("课堂表现度\n（10）", "专注度（3）"),
        ("课堂表现度\n（10）", "参与度（4）"),
        ("素质形成度\n（20）", "遵守规范、守法意识（5）"),
        ("素质形成度\n（20）", "质量意识与职业责任（5）"),
        ("素质形成度\n（20）", "工程伦理与数据安全（5）"),
        ("素质形成度\n（20）", "行为习惯、环境维护（5）"),
        ("知识掌握度\n（30）", "线上学习情况统计（10）"),
        ("知识掌握度\n（30）", "课中讨论、答题等（10）"),
        ("知识掌握度\n（30）", "课后作业（10）"),
        ("能力达成度\n（40）", "实操实训情况（25）"),
        ("能力达成度\n（40）", "成果展示（10）"),
        ("能力达成度\n（40）", "后续改进拓展（5）"),
    ]
    for idx, header in enumerate(headers):
        set_cell_text(table.cell(0, idx), header, WD_ALIGN_PARAGRAPH.CENTER)
    scores = score_breakdown(target)
    remarks = REMARKS[(seq - 1) % len(REMARKS)]
    for r_idx, row in enumerate(rows, 1):
        set_cell_multiline(table.cell(r_idx, 0), row[0], WD_ALIGN_PARAGRAPH.CENTER)
        set_cell_multiline(table.cell(r_idx, 1), row[1], WD_ALIGN_PARAGRAPH.CENTER)
        value = scores[r_idx - 1]
        display = str(int(value)) if abs(value - int(value)) < 0.01 else f"{value:.1f}"
        set_cell_text(table.cell(r_idx, 2), display, WD_ALIGN_PARAGRAPH.CENTER)
        note = remarks[r_idx - 1] if r_idx <= 12 else f"综合{target:.1f}分，后续加强完整项目迁移"
        set_cell_text(table.cell(r_idx, 3), note, WD_ALIGN_PARAGRAPH.CENTER)
    for row in table.rows:
        for c in row.cells:
            for p in c.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(8)


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
    title_spec = field_spec(manifest, "title")
    title_index = int(title_spec.get("paragraph", manifest["structure"]["title"]["paragraph"]))
    if title_index >= len(doc.paragraphs):
        raise ValueError(f"Title paragraph coordinate is invalid: {title_index}")
    set_paragraph_text(doc.paragraphs[title_index], f"{seq} 《{course}》教学单元设计：{task}", WD_ALIGN_PARAGRAPH.CENTER)

    table = doc.tables[0]
    set_manifest_field(table, manifest, "course_name", course)
    set_manifest_field(table, manifest, "major", major)
    set_manifest_field(table, manifest, "audience", audience)
    set_manifest_field(table, manifest, "unit", unit)
    set_manifest_field(table, manifest, "task", task)
    set_manifest_field(table, manifest, "hours", hours)
    set_manifest_field(table, manifest, "student_base", "1. 已具备相关课程基础，能理解任务涉及的基本概念\n2. 能按照教师演示完成基本工具操作\n3. 对项目案例、实操训练和线上资源接受度较高")
    set_manifest_field(table, manifest, "student_problems", "1. 理论知识向任务迁移时容易停留在照步骤操作\n2. 操作记录、结果分析和成果表达不够规范\n3. 小组分工、工具使用和成果整理能力存在差异")
    set_manifest_field(table, manifest, "student_strategy", "1. 以项目任务驱动教学，明确每次课成果\n2. 提供任务单、模板和检查表降低入门难度\n3. 通过过程性评分和小组互评及时反馈改进")
    set_manifest_field(table, manifest, "teaching_content", f"围绕“{unit}”开展“{task}”，完成以下任务：\n{numbered(flows)}\n核心知识点：\n{numbered(knowledge)}")
    set_manifest_field(table, manifest, "quality_goal", "1. 培养规范操作、职业责任和质量意识\n2. 树立严谨记录、客观评价和持续改进的工程态度\n3. 强化团队协作、诚信意识和数据安全意识")
    set_manifest_field(table, manifest, "knowledge_goal", numbered(knowledge) or f"1. 理解{task}的核心概念\n2. 掌握相关流程和成果要求")
    set_manifest_field(table, manifest, "ability_goal", f"1. 能根据任务要求完成{task}相关操作\n2. 能按模板提交规范成果\n3. 能对任务结果进行说明、分析和改进")
    set_manifest_field(table, manifest, "key_content", f"{task}的操作流程、成果规范和结果分析")
    set_manifest_field(table, manifest, "key_strategy", "任务驱动、教师示范、分组实训、过程评价")
    set_manifest_field(table, manifest, "difficult_content", f"在真实项目情境下完成{task}并形成规范成果")
    set_manifest_field(table, manifest, "difficult_strategy", "提供模板清单、分步演示、同伴互评和教师点评")
    set_manifest_field(table, manifest, "teaching_methods", "项目教学法、任务驱动法、演示法、分组实训法、成果评价法")
    set_manifest_field(table, manifest, "resources", f"1. 教学环境：标准机房、多媒体设备、网络环境及课程实训平台\n2. 实训工具：{tools}\n3. 数字资源：课程PPT、微课视频、任务单、评分表和成果模板")
    set_manifest_field(table, manifest, "references", "1. 课程配套教学资源\n2. 相关课程标准、项目任务书及主流工具官方文档\n3. 行业案例资料和实训成果模板")
    evaluation_spec = manifest["structure"]["evaluation_table"]
    evaluation_cell = actual_cells(table.rows[int(evaluation_spec["row"])])[int(evaluation_spec["cell"])]
    add_eval_table(evaluation_cell, score, seq, manifest)

    implementation_rows = [int(row) for row in manifest["fields"]["implementation"]["rows"]]
    preparation_row, introduction_row, demonstration_row, task_row, extension_row, practice_row, peer_row, summary_row, after_row = implementation_rows

    set_row(table, preparation_row, {0: "课前准备\n10min\n线上+线下", 1: f"阅读任务单，了解{task}的成果要求和评价标准", 2: "1. 发布任务单和模板\n2. 推送操作提示\n3. 收集预习问题", 3: "1. 阅读任务材料\n2. 检查工具环境\n3. 标记疑问", 4: "保证任务开始前目标明确、环境可用"})
    set_row(table, introduction_row, {0: "任务导入5min\n线下", 1: f"以项目情境导入“{task}”，说明本次任务产出物", 2: "1. 展示项目背景\n2. 明确任务边界\n3. 说明评分要点", 3: "1. 了解项目情境\n2. 明确小组分工\n3. 确认成果要求", 4: "用真实任务激活学习动机，形成任务驱动"})
    set_row(table, demonstration_row, {0: "操作示范\n15min\n线下", 1: f"示范本次任务关键步骤：\n{numbered(flows[:3])}", 2: "1. 演示关键流程\n2. 提醒易错点\n3. 展示合格成果样例", 3: "1. 观察记录\n2. 对照模板理解要求\n3. 提问确认", 4: "降低实操门槛，让学生掌握基本路径"})
    set_row(table, task_row, {0: "任务实施\n25min\n线下", 1: f"小组完成{task}，形成课堂阶段性成果", 2: "1. 巡视指导\n2. 解答工具和流程问题\n3. 记录共性问题", 3: "1. 按分工完成任务\n2. 记录操作过程\n3. 整理成果文件", 4: "通过做中学完成知识、技能和规范的转化"})
    set_row(table, extension_row, {0: "任务拓展\n10min\n线下", 1: "根据教师反馈修正记录、脚本、用例或文档中的问题", 2: "1. 点评典型问题\n2. 指导小组修正\n3. 强调质量标准", 3: "1. 对照反馈修改\n2. 复查成果完整性\n3. 完成自评", 4: "强化规范意识和质量闭环"})
    set_row(table, practice_row, {0: "项目实训\n15min\n线下", 1: f"提交{task}相关成果包，包括记录、截图、脚本或文档", 2: "1. 检查提交材料\n2. 抽查关键成果\n3. 给出即时建议", 3: "1. 提交成果包\n2. 补充说明\n3. 记录改进点", 4: "形成可评价、可追溯的学习成果"})
    set_row(table, peer_row, {0: "组间互评8min\n线下", 1: "小组交换成果，从正确性、完整性、规范性和可复现性四方面互评", 2: "1. 下发互评标准\n2. 组织互评\n3. 抽取典型成果点评", 3: "1. 根据标准互评\n2. 记录建议\n3. 完善本组成果", 4: "让评价标准显性化，促进互学互改"})
    set_row(table, summary_row, {0: "课堂小结7min\n线下", 1: "归纳本次任务的关键流程、常见问题和成果规范", 2: "1. 总结重难点\n2. 发布课后完善要求\n3. 提醒下次课准备", 3: "1. 回顾任务过程\n2. 完成自评\n3. 明确课后任务", 4: "帮助学生沉淀经验，形成持续改进意识"})
    set_row(table, after_row, {0: "课后完善\n15min\n线上+线下", 1: "根据课堂反馈完善成果包，并在线提交最终版本", 2: "1. 在线答疑\n2. 检查最终提交\n3. 记录过程性成绩", 3: "1. 修改成果\n2. 上传最终版本\n3. 完成学习反思", 4: "延伸课堂任务，保证成果质量"})
    reflection_rows = [int(row) for row in manifest["fields"]["reflection"]["rows"]]
    set_row(table, reflection_rows[0], {2: f"多数学生能按要求完成{task}，对任务流程和成果规范有较清晰认识；少数学生在记录完整性和结果分析上仍需加强。"})
    set_row(table, reflection_rows[1], {2: "以项目任务贯穿教学，突出实操产出和过程评价，学生参与度较高，互评环节能促进成果完善。"})
    set_row(table, reflection_rows[2], {2: "后续增加优秀成果样例和常见错误清单，对基础薄弱学生提供分步检查表，对能力较强学生增加扩展场景。"})

    out = out_dir / f"教案{seq:02d}_{safe_name(unit)}_{safe_name(task)}.docx"
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
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--skip-template-validation", action="store_true")
    parser.add_argument("--skip-output-validation", action="store_true")
    parser.add_argument("--qa-report", default="")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    ensure_supported_major(manifest)
    template = Path(args.template).expanduser().resolve() if args.template else manifest_template_path(manifest)
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")
    out_dir = Path(args.output_dir)
    with open(args.tasks_json, "r", encoding="utf-8") as f:
        meta = json.load(f)
    validate_input(meta, args.schema)
    lessons = meta["lessons"]

    template_warnings: list[str] = []
    if not args.skip_template_validation:
        template_report = validate_template(template, args.manifest)
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
