"""Synthetic acceptance harness for Lesson Content V2 course briefs.

This file deliberately builds a deterministic temporary V2 payload from a short
brief instead of reading one of the committed JSON fixtures. It is synthetic
acceptance evidence, not a true Agent-authored E2E, and is not part of the
regular core test shard because it renders 30 DOCX files with LibreOffice.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from docx import Document

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixture_lesson_plans import apply_authored_fixture_plan


LESSON = ROOT / "教案生成器" / "lesson-plan-docx-generator"
GENERATOR = LESSON / "scripts" / "generate_lesson_plans.py"
NON_IT_FORBIDDEN = ("工程伦理", "平凡又不平凡的价值观", "软件技术", "标准机房", "脚本", "截图工具", "代码编辑器", "数据安全")

def _brief_metadata(brief: str) -> tuple[str, str, int, int]:
    course = re.search(r"课程：([^\n]+)", brief).group(1).strip()
    major = re.search(r"专业：([^\n]+)", brief).group(1).strip()
    total_hours = int(re.search(r"总课时：([0-9]+)", brief).group(1))
    lesson_hours = int(re.search(r"每次：([0-9]+)学时", brief).group(1))
    return course, major, total_hours, lesson_hours


def _lesson(
    *, course: str, major: str, audience: str, index: int, unit: str,
    task: str, focus: str, artifact: str, next_focus: str, next_task: str,
    previous_artifact: str | None, score: float,
) -> dict:
    """Build test scaffolding from a supplied task/output allocation.

    Index controls identity and the historical capability-stage snapshot only.
    Teaching intent never comes from an ordinal topic table. ``focus`` remains
    in the frozen planning snapshot for compatibility; current prose comes from
    the authored task/output plan. This helper cannot author production content.
    """
    from tests.fixture_scope_plans import PRESERVED_DELIVERABLE_NODES, scope_plan_for

    plan = scope_plan_for(task, artifact)
    prior_learning = (
        f"课程开始前完成需求情境梳理，明确本课将围绕{focus}建立工作入口"
        if previous_artifact is None
        else f"已将{previous_artifact}带入本课的{focus}，据此补充新的判断条件"
    )
    stages = (
        ('before_class_preparation', '课前准备', 10,
         f'预读{task}的任务说明，准备{artifact}所需的已有材料。',
         f'检查{task}的已知要求，指出本课需要形成的{artifact}。',
         f'列出{task}的给定条件与尚不清楚的要求，准备{artifact}材料。',
         f'明确{task}的输入和本课产出范围。'),
        ('task_introduction', '任务导入', 10, plan.introduction,
         f'围绕{task}追问对象和要求，说明{artifact}为何是本课产出。',
         f'解释{task}的对象与要求，指出{artifact}应回应的内容。', plan.key),
        ('operation_demonstration', '方法示范', 20,
         f'示范{task}的处理过程，展示{artifact}如何保留处理依据。',
         f'结合{task}说明各步依据，把对应结果呈现在{artifact}中。',
         f'记录{task}的示范步骤及其在{artifact}中的位置。', plan.key),
        ('task_implementation', '任务实施', 25, plan.practice,
         f'检查{task}的完成过程，引导学生说明{artifact}中的具体依据。',
         f'完成{task}并提交{artifact}草稿，指出尚需说明的内容。', plan.difficulty),
        ('task_extension', '任务拓展', 10,
         f'复查{artifact}是否完整回应{task}，保持本课任务范围。',
         f'对照{task}发现{artifact}的缺项，不扩展下一课的新任务。',
         f'补充{task}的遗漏说明，在{artifact}中标明补充位置。', plan.difficulty),
        ('project_practice', '项目实训', 10,
         f'按{task}的既定范围整理{artifact}，使结果与依据对应。',
         f'核对{artifact}是否覆盖{task}的已分配要求。',
         f'提交{artifact}及{task}的对应说明，保留尚未完成的事项。', plan.practice),
        ('peer_review', '组间互评', 5,
         f'交换{artifact}，对照{task}要求独立核对。',
         f'要求评阅者指明{artifact}中与{task}不对应的位置。',
         f'为{artifact}写出一项与{task}相关的核对意见及位置。', plan.key),
        ('lesson_summary', '课堂小结', 10,
         f'归纳{task}的处理依据与{artifact}的形成过程。',
         f'区分{task}中已完成的内容与仍未解决的问题。',
         f'说明{artifact}如何回应{task}，报告本课完成范围。', plan.introduction),
        ('after_class_improvement', '课后完善', 15,
         f'依据核对意见完善{artifact}，保持{task}的原有范围。',
         f'反馈{artifact}是否回应{task}的遗漏要求。',
         f'上传{artifact}修订稿及对应{task}的修改说明。', plan.practice),
    )
    implementation = [
        dict(id=stage_id, label=label, minutes=minutes,
             modality='线上+线下' if stage_id in {'before_class_preparation', 'after_class_improvement'} else '小组实训',
             content=[content], teacher_actions=[teacher], student_actions=[student], objective=objective)
        for stage_id, label, minutes, content, teacher, student, objective in stages
    ]
    # Evaluate an observable criterion/output; do not repeat instructional prose.
    remarks = {
        key: suffix
        for key, suffix in {
            'attendance': '到课并备齐当前任务材料',
            'attention': f'关注{artifact}中的处理依据',
            'participation': f'说明{artifact}的一项形成依据',
            'compliance': '按本课要求保留对应记录',
            'values': f'说明{artifact}的职业用途',
            'ethics': f'如实报告{artifact}的完成情况',
            'habits': '整理本课材料及其对应位置',
            'online_learning': f'预读{artifact}对应的任务要求',
            'discussion': f'围绕{artifact}解释处理决定',
            'homework': f'提交{artifact}及修订说明',
            'practice': f'按本课任务形成{artifact}',
            'presentation': f'说明{artifact}的形成依据',
            'improvement': f'补齐{artifact}中的当前任务缺项',
        }.items()
    }
    lesson = {
        'lesson_id': f'L{index:02d}', 'unit': unit, 'task': task,
        'hours': lesson_hours_for_course(course),
        'progression': {
            'prior_lesson_id': None if previous_artifact is None else f'L{index - 1:02d}',
            'prior_learning': prior_learning,
            'capability_stage': ('认知', '理解', '模仿', '独立', '迁移')[min(index - 1, 4)],
            'deliverable': artifact,
            'next_bridge': f'下一课以{artifact}为输入，{next_task}，重点衔接{next_focus}',
        },
        'student_analysis': {
            'base': [f'本测试假定能够阅读{task}的任务说明。', f'本测试假定接触过{artifact}所需的基础材料。'],
            'problems': [f'{task}需要重点解释：{plan.key}', f'{task}的处理难点：{plan.difficulty}'],
            'strategies': [plan.introduction, plan.practice],
        },
        'teaching_content': [plan.introduction,
            PRESERVED_DELIVERABLE_NODES.get(task, f'示范形成{artifact}的关键步骤，说明产物如何回应“{task}”的要求。'),
            plan.practice],
        'goals': {'knowledge': [plan.introduction, plan.key],
                  'ability': [plan.practice, plan.difficulty],
                  'quality': [f'如实说明{task}的完成范围，保留{artifact}中的依据。',
                              f'以{artifact}核对{task}，对尚未完成的要求作明确标记。']},
        'key_point': {'content': [plan.key], 'strategy': [plan.introduction]},
        'difficult_point': {'content': [plan.difficulty], 'strategy': [plan.practice]},
        'teaching_methods': [f'{task}任务驱动法', f'{artifact}示范练习法', f'{artifact}成果互评法'],
        'resources': [f'{task}任务说明', f'{artifact}成果模板', '当前任务已有材料'],
        'references': [{'text': '本课程项目任务资料', 'source_kind': 'generic'}],
        'implementation': implementation,
        'evaluation': {'score': score, 'remarks': remarks},
        'reflection': {
            'summary': f'本 synthetic fixture 以当前任务分配为界：{plan.introduction}',
            'innovation': f'教学组织围绕当前产物{artifact}展开：{plan.practice}',
            'improvement': f'后续应复查当前教学难点的表达：{plan.difficulty}',
        },
    }
    # Preserve ad76ae0's two fully authored lessons without rewriting their plan.
    apply_authored_fixture_plan(lesson, task=task, focus=focus, artifact=artifact)
    return lesson


_CURRENT_LESSON_HOURS = 2


def lesson_hours_for_course(_course: str) -> int:
    return _CURRENT_LESSON_HOURS


def synthetic_plan_from_brief(brief: str) -> dict:
    global _CURRENT_LESSON_HOURS
    course, major, total_hours, lesson_hours = _brief_metadata(brief)
    _CURRENT_LESSON_HOURS = lesson_hours
    audience = "高职二年级"
    if "数据库" in course:
        specs = (
            ("项目一 数据库项目准备", "梳理业务需求与数据边界", "需求边界", "需求范围清单", "数据对象建模"),
            ("项目一 数据库项目准备", "建立业务实体关系草图", "数据对象建模", "实体关系草图", "项目初始化"),
            ("项目一 数据库项目准备", "完成数据库项目初始化", "项目初始化", "数据库初始化记录", "字段与类型规划"),
            ("项目二 数据库结构设计", "规划字段与数据类型", "字段与类型规划", "数据库字段字典", "约束规则配置"),
            ("项目二 数据库结构设计", "配置主键外键与约束", "约束规则配置", "数据库约束检查表", "样例数据校验"),
            ("项目二 数据库结构设计", "录入样例数据并校验", "样例数据校验", "数据校验记录", "多表业务关联"),
            ("项目三 业务查询实现", "实现多表业务关联查询", "多表业务关联", "关联查询脚本", "分组统计查询"),
            ("项目三 业务查询实现", "完成分组统计与汇总", "分组统计查询", "业务统计结果表", "嵌套查询设计"),
            ("项目三 业务查询实现", "设计嵌套查询解决方案", "嵌套查询设计", "嵌套查询记录", "视图封装"),
            ("项目四 数据库运行维护", "创建视图封装业务结果", "视图封装", "业务视图说明", "索引优化"),
            ("项目四 数据库运行维护", "依据查询特征调整索引", "索引优化", "索引调整记录", "事务控制"),
            ("项目四 数据库运行维护", "处理事务提交与回滚", "事务控制", "事务验证记录", "访问权限管理"),
            ("项目五 安全与性能管理", "配置角色与访问权限", "访问权限管理", "权限配置清单", "备份策略制定"),
            ("项目五 安全与性能管理", "制定数据库备份策略", "备份策略制定", "数据库备份计划表", "性能指标诊断"),
            ("项目五 安全与性能管理", "诊断查询性能指标", "性能指标诊断", "性能诊断报告", "综合过程编排"),
            ("项目六 综合项目交付", "编排存储过程完成业务处理", "综合过程编排", "过程调用记录", "综合报表设计"),
            ("项目六 综合项目交付", "完成综合业务报表设计", "综合报表设计", "综合报表成果", "项目验收答辩"),
            ("项目六 综合项目交付", "展示数据库项目并完成答辩", "项目验收答辩", "数据库项目验收包", "课程成果复盘"),
        )
    elif "会计" in course:
        specs = (
            ("项目一 凭证业务准备", "识别原始凭证要素与业务边界", "凭证要素识别", "凭证要素清单", "会计科目判断"),
            ("项目一 凭证业务准备", "依据业务变化判断会计科目", "会计科目判断", "科目判断分析表", "记账凭证编制"),
            ("项目二 记账凭证处理", "编制收付转记账凭证", "记账凭证编制", "记账凭证与附件编号表", "凭证审核"),
            ("项目二 记账凭证处理", "审核凭证并追溯差错", "凭证审核", "凭证审核结果与差错清单", "账簿登记"),
            ("项目三 账簿登记核算", "登记日记账与明细账", "账簿登记", "日记账明细账登记记录", "账簿核对"),
            ("项目三 账簿登记核算", "完成账簿核对与成果汇报", "账簿核对", "会计核算成果交付包", "岗位复盘"),
        )
    else:
        specs = (
            ("项目一 基础护理准备", "完成护理评估与操作准备", "护理评估", "护理评估记录", "基础操作核对"),
            ("项目一 基础护理准备", "完成无菌操作前核对", "基础操作核对", "操作核对清单", "生命体征观察"),
            ("项目二 生命体征照护", "完成生命体征测量记录", "生命体征观察", "生命体征测量记录", "异常情况沟通"),
            ("项目二 生命体征照护", "开展异常情况沟通处置", "异常情况沟通", "异常沟通记录单", "基础护理操作"),
            ("项目三 基础护理实施", "完成基础护理操作练习", "基础护理操作", "基础操作评价表", "综合照护交付"),
            ("项目三 基础护理实施", "展示综合照护成果并复盘", "综合照护交付", "综合照护记录单", "岗位规范复盘"),
        )
    scores = (88.5, 90, 89.5, 91, 90.5, 92, 91.5, 93, 92.5, 94, 93.5, 90.5, 94.5, 91.5, 95, 92, 95.5, 93)
    lessons = []
    previous_artifact = None
    for index, (unit, task, focus, artifact, next_focus) in enumerate(specs, 1):
        lessons.append(
            _lesson(
                course=course,
                major=major,
                audience=audience,
                index=index,
                unit=unit,
                task=task,
                focus=focus,
                artifact=artifact,
                next_focus=next_focus,
                next_task=(specs[index][1] if index < len(specs) else f"复盘{course}课程成果"),
                previous_artifact=previous_artifact,
                score=scores[(index - 1) % len(scores)],
            )
        )
        previous_artifact = artifact
    assert total_hours == len(lessons) * lesson_hours
    return {
        "content_contract_version": "2.0",
        "course_name": course,
        "major": major,
        "audience": audience,
        "default_hours": lesson_hours,
        "total_hours": total_hours,
        "lessons": lessons,
    }


def _document_text(path: Path) -> str:
    document = Document(path)
    values = [paragraph.text for paragraph in document.paragraphs]

    def visit_table(table) -> None:
        for row in table.rows:
            for cell in row.cells:
                values.append(cell.text)
                for nested in cell.tables:
                    visit_table(nested)

    for table in document.tables:
        visit_table(table)
    return "\n".join(values)


@contextmanager
def _case_directory(label: str):
    evidence_root = os.environ.get("LESSON_V2_SYNTHETIC_EVIDENCE_DIR", "").strip()
    if evidence_root:
        folder = Path(evidence_root).expanduser().resolve() / label
        if folder.exists():
            raise RuntimeError(f"synthetic evidence directory already exists: {folder}")
        folder.mkdir(parents=True)
        yield folder
        return
    with tempfile.TemporaryDirectory(prefix="lesson-v2-synthetic-") as temp_name:
        yield Path(temp_name)


def _export_visual_evidence(output: Path, representative: list[Path], evidence_root: Path | None) -> dict[str, object]:
    if evidence_root is None:
        return {"status": "not_exported", "scope": "synthetic_acceptance", "representative_files": [path.name for path in representative]}
    docx_dir = evidence_root / "docx"
    pdf_dir = evidence_root / "pdf"
    docx_dir.mkdir()
    pdf_dir.mkdir()
    for path in representative:
        shutil.copy2(path, docx_dir / path.name)
    renderer_candidates = (
        shutil.which("soffice"),
        shutil.which("soffice.com"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    )
    renderer = next((item for item in renderer_candidates if item and Path(item).exists()), None)
    if renderer is None:
        return {
            "status": "not_executed",
            "scope": "synthetic_acceptance",
            "representative_files": [path.name for path in representative],
            "pdf_files": [],
            "reason": "LibreOffice was not found for representative visual evidence",
        }
    profile = evidence_root / "profile"
    profile.mkdir()
    pdf_files: list[str] = []
    for path in sorted(docx_dir.glob("*.docx")):
        result = subprocess.run(
            [renderer, "--headless", f"-env:UserInstallation={profile.as_uri()}", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
        )
        pdf = pdf_dir / f"{path.stem}.pdf"
        if result.returncode != 0 or not pdf.is_file() or pdf.stat().st_size == 0:
            raise RuntimeError(f"representative PDF conversion failed for {path.name}: {result.stderr or result.stdout}")
        pdf_files.append(pdf.name)
    return {
        "status": "rendered_for_external_inspection",
        "scope": "synthetic_acceptance",
        "representative_files": [path.name for path in representative],
        "pdf_files": pdf_files,
        "evidence_directory": str(evidence_root),
    }


def run_case(brief: str, expected_lessons: int) -> dict:
    if "数据库" in brief:
        label = "database"
    elif "护理" in brief:
        label = "nursing"
    else:
        label = "accounting"
    with _case_directory(label) as folder:
        evidence_root = folder if os.environ.get("LESSON_V2_SYNTHETIC_EVIDENCE_DIR", "").strip() else None
        source = folder / "brief-derived-input.json"
        source.write_text(json.dumps(synthetic_plan_from_brief(brief), ensure_ascii=False, indent=2), encoding="utf-8")
        output = folder / "output"
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--tasks-json", str(source), "--output-dir", str(output), "--render"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)
        report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
        lessons = sorted(output.glob("*.docx"))
        if len(lessons) != expected_lessons or report["files_checked"] != expected_lessons:
            raise AssertionError((len(lessons), report["files_checked"], expected_lessons))
        if report["status"] != "passed" or report["content_quality"]["status"] != "passed":
            raise AssertionError(report)
        if report["content_quality"]["progression"]["status"] != "passed":
            raise AssertionError(report["content_quality"]["progression"])
        score_pattern = report["content_quality"]["coverage"]["score_pattern"]
        if not score_pattern["range_valid"] or score_pattern["all_same"] or score_pattern["simple_cycle"] or score_pattern["arithmetic_progression"]:
            raise AssertionError(score_pattern)
        for key in ("exact_duplicates", "adjacent_exact_duplicates", "adjacent_similarity_pairs", "whole_lesson_similarity_pairs", "implementation_similarity_pairs", "repeated_sentences"):
            if report["content_quality"].get(key):
                raise AssertionError({key: report["content_quality"][key]})
        all_text = "\n".join(_document_text(path) for path in lessons)
        representative = [lessons[0], lessons[len(lessons) // 2], lessons[-1]]
        representative_text = [_document_text(path) for path in representative]
        if len(set(representative_text)) != len(representative_text):
            raise AssertionError("representative lessons are not distinct")
        visual_inspection = _export_visual_evidence(output, representative, evidence_root)
        result_data = {
            "lessons": expected_lessons,
            "hours": report["checks"]["total_hours"]["actual"],
            "max_similarity": max(
                [item["score"] for item in report["content_quality"].get("whole_lesson_similarity_pairs", [])],
                default=0,
            ),
            "duplicates": 0,
            "progression": report["content_quality"]["progression"]["status"],
            "scores": "valid-natural-pattern",
            "render": report["render"],
            "visual_inspection": visual_inspection,
        }
        if "护理" in brief:
            for term in NON_IT_FORBIDDEN:
                if term in all_text:
                    raise AssertionError(f"non-IT contamination: {term}")
            if "职业伦理" not in all_text or "职业价值观" not in all_text:
                raise AssertionError("generalized evaluation labels are missing")
        print(json.dumps(result_data, ensure_ascii=False, indent=2))
        return result_data


def main() -> int:
    run_case(
        "课程：《数据库技术》\n专业：软件技术\n总课时：36\n每次：2学时\n没有其他资料\n允许合理设计",
        18,
    )
    run_case(
        "课程：《基础护理技术》\n专业：护理\n总课时：12\n每次：2学时\n没有教材\n允许合理设计",
        6,
    )
    run_case(
        "课程：《会计凭证与账簿实训》\n专业：大数据与会计\n总课时：12\n每次：2学时\n没有教材\n允许合理设计",
        6,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
