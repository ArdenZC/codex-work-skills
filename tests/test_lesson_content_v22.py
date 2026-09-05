from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from docx import Document

from tests.synthetic_lesson_content_v2_acceptance import _lesson as synthetic_lesson
from tests.test_lesson_content_v2 import (
    LESSON,
    ROOT,
    V112_MANIFEST,
    assess_content_quality,
    bookmark_text,
    field_bookmark,
    lesson_generator,
    load_manifest,
    run_script,
)
from tests.test_lesson_skill_hardening import lesson_acceptance


DB_SPECS = (
    ("项目一 数据结构认知", "梳理线性结构使用场景", "线性结构", "结构选择说明", "顺序表实现"),
    ("项目一 数据结构认知", "比较顺序表与链表特点", "顺序表实现", "结构比较表", "链表操作"),
    ("项目一 数据结构认知", "分析链表结点与链接关系", "链表操作", "链表关系图", "栈队列应用"),
    ("项目二 线性结构实现", "设计栈和队列操作接口", "栈队列应用", "接口设计记录", "树形结构表示"),
    ("项目二 线性结构实现", "实现栈队列的典型算法", "树形结构表示", "算法实现记录", "树的遍历"),
    ("项目二 线性结构实现", "验证边界条件与异常处理", "树的遍历", "边界测试记录", "图结构建模"),
    ("项目三 非线性结构建模", "建立树结构的结点模型", "图结构建模", "树模型说明", "遍历策略"),
    ("项目三 非线性结构建模", "编排树的遍历与搜索", "遍历策略", "遍历过程记录", "图的存储"),
    ("项目三 非线性结构建模", "比较图的邻接表示方法", "图的存储", "图存储比较表", "最短路径"),
    ("项目四 算法分析应用", "分析最短路径求解条件", "最短路径", "路径分析记录", "排序算法"),
    ("项目四 算法分析应用", "选择排序策略并说明依据", "排序算法", "排序选择说明", "查找算法"),
    ("项目四 算法分析应用", "比较查找算法的适用边界", "查找算法", "查找比较记录", "综合结构设计"),
    ("项目五 综合结构设计", "拆解综合任务的结构需求", "综合结构设计", "需求拆解清单", "性能验证"),
    ("项目五 综合结构设计", "组合线性与非线性结构", "性能验证", "结构组合方案", "复杂度评估"),
    ("项目五 综合结构设计", "评估操作复杂度与性能", "复杂度评估", "复杂度分析表", "项目交付"),
    ("项目六 项目成果交付", "整理数据结构项目成果", "项目交付", "项目成果包", "成果答辩"),
    ("项目六 项目成果交付", "复核算法证据与运行结果", "成果答辩", "复核问题清单", "课程复盘"),
    ("项目六 项目成果交付", "展示方案并完成课程复盘", "课程复盘", "课程复盘报告", "后续能力迁移"),
)

SOFTWARE_SPECS = tuple(
    (
        f"项目{index // 3 + 1} 软件建模实施",
        task,
        focus,
        artifact,
        next_focus,
    )
    for index, (task, focus, artifact, next_focus) in enumerate(
        (
            ("梳理业务目标与建模边界", "业务边界", "建模范围清单", "用例分析"),
            ("识别参与者与系统用例", "用例分析", "用例关系图", "领域对象"),
            ("提取领域对象与职责", "领域对象", "领域对象表", "类关系"),
            ("建立类之间的关联关系", "类关系", "类关系草图", "属性方法"),
            ("补充类的属性与方法", "属性方法", "类说明表", "交互场景"),
            ("描述对象协作与消息顺序", "交互场景", "交互顺序图", "状态变化"),
            ("刻画对象状态与转移条件", "状态变化", "状态图说明", "活动流程"),
            ("编排业务活动与决策分支", "活动流程", "活动流程图", "组件边界"),
            ("划分组件职责与依赖边界", "组件边界", "组件依赖图", "部署节点"),
            ("规划部署节点与运行环境", "部署节点", "部署结构图", "架构取舍"),
            ("比较架构方案与质量属性", "架构取舍", "架构比较表", "模型验证"),
            ("依据约束检查模型一致性", "模型验证", "模型检查记录", "迭代修订"),
            ("根据评审意见修订模型", "迭代修订", "模型修订记录", "文档封装"),
            ("整理模型元素与设计文档", "文档封装", "设计文档包", "成果评审"),
            ("组织建模成果评审与答辩", "成果评审", "评审问题清单", "综合交付"),
            ("完成软件建模方案综合交付", "综合交付", "建模综合成果包", "后续项目迁移"),
        )
    )
)

NURSING_SPECS = (
    ("项目一 基础护理准备", "完成护理评估与操作准备", "护理评估", "护理评估记录", "安全核对"),
    ("项目一 基础护理准备", "完成操作前风险与安全核对", "安全核对", "安全核对清单", "生命体征观察"),
    ("项目二 生命体征照护", "完成生命体征测量记录", "生命体征观察", "生命体征测量记录", "异常沟通"),
    ("项目二 生命体征照护", "开展异常情况沟通处置", "异常沟通", "异常沟通记录单", "护理复盘"),
    ("项目三 综合照护交付", "展示综合照护成果并复盘", "护理复盘", "综合照护记录单", "岗位迁移"),
)

# Keep the fixture inside the existing 85-96 / 0.5 score vocabulary without
# accidentally exercising the stable mechanical-score hard-fail rules.
SYNTHETIC_SCORES = (
    88.5,
    91.0,
    89.5,
    92.5,
    90.0,
    93.5,
    87.5,
    94.0,
    86.5,
    95.0,
    87.0,
    92.0,
    89.0,
    96.0,
    90.5,
    94.5,
    85.5,
    93.0,
)


def _pool(*, include_foreign: bool = False, generic: bool = False) -> list[dict[str, object]]:
    items: list[dict[str, object]] = [
        {
            "reference_id": "REF-DOMESTIC",
            "reference_type": "book",
            "title": "数据结构（C语言版）",
            "authors": ["严蔚敏", "吴伟民"],
            "edition": "第2版",
            "publisher": "清华大学出版社",
            "source_kind": "provided",
            "source_region": "domestic",
            "evidence": "用户提供：数据结构教材.pdf",
        },
        {
            "reference_id": "REF-STANDARD",
            "reference_type": "formal_course_document",
            "title": "数据结构课程标准",
            "publisher": "某职业院校",
            "source_kind": "verified_public",
            "source_region": "domestic",
            "evidence": "https://example.edu.cn/curriculum/data-structure-standard",
        },
    ]
    if generic:
        items[1] = {
            "reference_id": "REF-STANDARD",
            "reference_type": "formal_course_document",
            "title": "数据结构课程标准相关章节",
            "source_kind": "generic",
            "source_region": "domestic",
        }
    if include_foreign:
        items.append(
            {
                "reference_id": "REF-FOREIGN",
                "reference_type": "official_manual",
                "title": "Python Documentation: Data Structures",
                "publisher": "Python Software Foundation",
                "source_kind": "verified_public",
                "source_region": "foreign",
                "evidence": "https://docs.python.org/3/tutorial/datastructures.html",
            }
        )
    return items


def _task(task_id: str, hours: int, course: str, lesson_ids: list[str]) -> dict[str, object]:
    return {
        "task_id": task_id,
        "project_id": f"P-{task_id.split('-')[-1]}",
        "title": f"{task_id} {course}实践任务",
        "lesson_ids": lesson_ids,
        "practice_hours": hours,
        "scenario": f"围绕{course}的真实业务情境完成可复核实践。",
        "objectives": ["按任务边界完成实践操作", "形成可追溯的实践成果"],
        "required_inputs": ["课程任务说明", "样例数据"],
        "tools_or_materials": ["实训环境", "实践记录表"],
        "steps": ["核对任务条件", "实施操作并记录证据", "整理成果并复核"],
        "deliverables": ["实践成果包", "过程记录表"],
        "acceptance_criteria": ["成果内容完整且可复核", "记录与成果能够相互对应"],
        "safety_or_compliance": ["遵守实训环境和数据使用规范"],
    }


def make_v22_payload(
    *,
    course: str = "数据结构高级",
    major: str = "软件工程专业",
    audience: str = "高职三年级",
    theory_hours: int = 12,
    practice_hours: int = 0,
    lesson_count: int | None = None,
    lesson_hours: list[int] | None = None,
    task_hours: list[int] | None = None,
    references: list[dict[str, object]] | None = None,
    textbook: dict[str, object] | None = None,
    allow_textbook: bool = False,
    practice_work_orders: bool = False,
    specs: tuple[tuple[str, str, str, str, str], ...] = DB_SPECS,
) -> dict[str, object]:
    default_hours = 2
    if lesson_hours is None:
        expected_count = (theory_hours + default_hours - 1) // default_hours
        lesson_hours = [default_hours] * expected_count
        if theory_hours % default_hours:
            lesson_hours[-1] = theory_hours % default_hours
    if lesson_count is None:
        lesson_count = len(lesson_hours)
    lesson_hours = list(lesson_hours[:lesson_count])
    if sum(lesson_hours) != theory_hours:
        raise AssertionError("fixture lesson hours must equal theory_hours")
    if len(specs) < lesson_count:
        raise AssertionError("fixture specs are shorter than lesson_count")

    lessons: list[dict[str, object]] = []
    previous_artifact: str | None = None
    for index, (unit, task, focus, artifact, next_focus) in enumerate(specs[:lesson_count], 1):
        lesson = synthetic_lesson(
            course=course,
            major=major,
            audience=audience,
            index=index,
            unit=unit,
            task=task,
            focus=focus,
            artifact=artifact,
            next_focus=next_focus,
            next_task=(specs[index][1] if index < len(specs) else f"复盘{course}"),
            previous_artifact=previous_artifact,
            score=SYNTHETIC_SCORES[index - 1],
        )
        lesson["lesson_id"] = f"L{index:02d}"
        lesson["lesson_type"] = "theory"
        lesson["hours"] = lesson_hours[index - 1]
        lesson["theory_hours"] = lesson_hours[index - 1]
        lesson["practice_hours"] = 0
        lesson["reference_ids"] = [str(item["reference_id"]) for item in (references or _pool())[:2]]
        lesson["practice_task_ids"] = []
        lesson["progression"]["prior_lesson_id"] = None if index == 1 else f"L{index - 1:02d}"
        for progression_field in ("prior_learning", "deliverable", "next_bridge"):
            value = str(lesson["progression"][progression_field])
            if len(value) < 6:
                lesson["progression"][progression_field] = value + "成果"
        lesson.pop("references", None)
        if lesson_hours[index - 1] == 1:
            for stage, minutes in zip(
                lesson["implementation"],
                (5, 5, 10, 12, 5, 5, 3, 5, 5),
            ):
                stage["minutes"] = minutes
        lessons.append(lesson)
        previous_artifact = artifact

    total_hours = theory_hours + practice_hours
    tasks: list[dict[str, object]] = []
    if practice_hours:
        task_hours = list(task_hours or [practice_hours])
        if sum(task_hours) != practice_hours:
            raise AssertionError("fixture task hours must equal practice_hours")
        related_lessons = [lesson["lesson_id"] for lesson in lessons[: min(2, len(lessons))]]
        for index, hours in enumerate(task_hours, 1):
            tasks.append(_task(f"PT-{index:02d}", hours, course, related_lessons if theory_hours else []))
        if lessons:
            lessons[0]["practice_task_ids"] = [task["task_id"] for task in tasks]

    pool = copy.deepcopy(references or _pool())
    lesson_ids = [lesson["lesson_id"] for lesson in lessons]
    outline = [
        {
            "lesson_id": lesson["lesson_id"],
            "unit": lesson["unit"],
            "task": lesson["task"],
            "lesson_type": "theory",
            "hours": lesson["hours"],
            "theory_hours": lesson["theory_hours"],
            "practice_hours": 0,
            "prior_learning": lesson["progression"]["prior_learning"],
            "capability_stage": lesson["progression"]["capability_stage"],
            "deliverable": lesson["progression"]["deliverable"],
            "next_bridge": lesson["progression"]["next_bridge"],
            "practice_task_ids": lesson["practice_task_ids"],
        }
        for lesson in lessons
    ]
    payload: dict[str, object] = {
        "content_contract_version": "2.2",
        "course_name": course,
        "major": major,
        "audience": audience,
        "default_hours": default_hours,
        "total_hours": total_hours,
        "delivery_plan": {
            "mode": "theory_only" if practice_hours == 0 else "practice_only" if theory_hours == 0 else "hybrid",
            "total_hours": total_hours,
            "theory_hours": theory_hours,
            "practice_hours": practice_hours,
        },
        "course_materials": {"textbook": copy.deepcopy(textbook)},
        "reference_pool": pool,
        "allow_textbook_as_reference": allow_textbook,
        "artifact_plan": {
            "lesson_plans": theory_hours > 0,
            "practice_work_orders": practice_work_orders,
        },
        "outline": outline,
        "lessons": lessons,
    }
    if practice_hours:
        payload["practice_task_contract"] = {
            "contract_version": "1.0",
            "course_name": course,
            "practice_hours": practice_hours,
            "granularity": "per_task",
            "tasks": tasks,
        }
    return payload


class LessonContentV22Tests(unittest.TestCase):
    def assert_rejected(self, payload: dict[str, object], pattern: str) -> None:
        with self.assertRaisesRegex(ValueError, pattern):
            lesson_generator.validate_content_v2_input(payload)

    def assert_valid_and_qa(self, payload: dict[str, object]) -> dict[str, object]:
        lesson_generator.validate_content_v2_input(payload)
        report = assess_content_quality(payload)
        self.assertEqual(report["status"], "passed", report)
        return report

    def test_40h_and_64h_artifact_hours_are_decoupled_from_workorder_count(self) -> None:
        cases = (
            (40, 20, 20, 10, [4, 6, 10], DB_SPECS),
            (64, 32, 32, 16, [6, 10, 16], SOFTWARE_SPECS),
        )
        for total, theory, practice, count, task_hours, specs in cases:
            with self.subTest(total=total):
                payload = make_v22_payload(
                    course="软件建模与设计" if total == 64 else "数据结构高级",
                    theory_hours=theory,
                    practice_hours=practice,
                    lesson_count=count,
                    task_hours=task_hours,
                    specs=specs,
                )
                report = self.assert_valid_and_qa(payload)
                self.assertEqual(len(payload["lessons"]), count)
                self.assertEqual(sum(lesson["hours"] for lesson in payload["lessons"]), theory)
                self.assertEqual(sum(task["practice_hours"] for task in payload["practice_task_contract"]["tasks"]), practice)
                self.assertEqual(lesson_acceptance.delivery_metrics(payload)["status"], "PASS")
                self.assertEqual(report["reference_provenance"]["reuse_policy"], "reference_reusable")
                self.assertNotIn("project_count=8", json.dumps(payload, ensure_ascii=False))
                self.assertNotEqual(len(payload["practice_task_contract"]["tasks"]), practice // 2)

    def test_theory_remainder_uses_ceil_and_one_hour_lesson(self) -> None:
        payload = make_v22_payload(theory_hours=21, lesson_hours=[2] * 10 + [1], specs=DB_SPECS)
        lesson_generator.validate_content_v2_input(payload)
        self.assertEqual(len(payload["lessons"]), 11)
        self.assertEqual(payload["lessons"][-1]["hours"], 1)
        self.assertEqual(sum(lesson["hours"] for lesson in payload["lessons"]), 21)

        rounded = copy.deepcopy(payload)
        rounded["lessons"] = rounded["lessons"][:-1]
        rounded["outline"] = rounded["outline"][:-1]
        self.assert_rejected(rounded, r"ceil\(theory_hours / default_hours\)")

    def test_pure_theory_and_pure_practice_do_not_invent_opposite_artifact(self) -> None:
        theory = make_v22_payload(theory_hours=32, practice_hours=0, lesson_count=16, specs=SOFTWARE_SPECS)
        lesson_generator.validate_content_v2_input(theory)
        self.assertEqual(len(theory["lessons"]), 16)
        self.assertNotIn("practice_task_contract", theory)

        practice = make_v22_payload(
            course="护理技能实训",
            major="护理专业",
            theory_hours=0,
            practice_hours=32,
            lesson_count=0,
            task_hours=[8, 10, 14],
            practice_work_orders=True,
            specs=NURSING_SPECS,
        )
        report = self.assert_valid_and_qa(practice)
        lesson_generator.validate_content_v2_input(practice)
        self.assertEqual(practice["lessons"], [])
        self.assertEqual(sum(task["practice_hours"] for task in practice["practice_task_contract"]["tasks"]), 32)
        self.assertTrue(all(task["lesson_ids"] == [] for task in practice["practice_task_contract"]["tasks"]))
        self.assertEqual(report["practice_handoff"]["status"], "passed")

    def test_pure_practice_output_keeps_handoff_without_lesson_docx(self) -> None:
        payload = make_v22_payload(
            course="护理技能实训",
            major="护理专业",
            theory_hours=0,
            practice_hours=32,
            lesson_count=0,
            task_hours=[8, 10, 14],
            practice_work_orders=False,
            specs=NURSING_SPECS,
        )
        with tempfile.TemporaryDirectory(prefix="lesson-v22-pure-practice-") as temp_name:
            root = Path(temp_name)
            source = root / "content.json"
            output = root / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(qa["status"], "passed", qa)
            self.assertEqual(qa["checks"]["file_count"], {"expected": 0, "actual": 0})
            self.assertEqual(qa["checks"]["total_hours"]["actual"], 0)
            self.assertEqual(qa["checks"]["course_hours"]["actual"], 32)
            handoff = json.loads((output / "practice-task-contract.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["practice_hours"], 32)
            self.assertEqual(list(output.glob("*.docx")), [])

    def test_same_reference_reuse_across_six_lessons_passes_for_all_source_kinds(self) -> None:
        for label, refs in (
            ("provided", _pool()),
            ("verified_public", [
                {**_pool()[0], "source_kind": "verified_public", "evidence": "https://example.edu.cn/book"},
                _pool()[1],
            ]),
            ("generic", _pool(generic=True)),
        ):
            with self.subTest(source_kind=label):
                payload = make_v22_payload(theory_hours=12, lesson_count=6, references=refs, specs=DB_SPECS)
                report = self.assert_valid_and_qa(payload)
                self.assertEqual(report["reference_provenance"]["cross_lesson_reuse"], "allowed")
                self.assertEqual(report["reference_provenance"]["same_lesson_duplicates"], [])
                self.assertEqual(report["coverage"]["reference_metrics"]["reuse_frequency"]["REF-DOMESTIC"], 6)
                for detector in (
                    "exact_duplicates",
                    "adjacent_exact_duplicates",
                    "item_duplicates",
                    "adjacent_item_duplicates",
                    "frequency_item_duplicates",
                    "repeated_sentences",
                    "field_similarity_pairs",
                    "adjacent_field_similarity_pairs",
                    "whole_lesson_similarity_pairs",
                    "structural_similarity_pairs",
                ):
                    for finding in report.get(detector, []):
                        if finding.get("field") == "references":
                            self.assertTrue(
                                finding.get("allowed"),
                                {"detector": detector, "finding": finding},
                            )

    def test_reference_boundary_and_textbook_exclusion_are_fail_closed(self) -> None:
        for title in ("投影仪", "血压计", "MySQL Workbench"):
            with self.subTest(title=title):
                refs = _pool()
                refs[0]["title"] = title
                self.assert_rejected(make_v22_payload(references=refs), "resource-only")

        invented = _pool(generic=True)
        invented[0].update({"title": "《虚构教材》 作者甲 ISBN 978-7-0000-0000-0", "source_kind": "generic"})
        self.assert_rejected(make_v22_payload(references=invented), "cannot claim a specific bibliographic identity")

        textbook = {
            "title": "数据结构（C语言版）",
            "authors": ["严蔚敏", "吴伟民"],
            "edition": "第2版",
            "publisher": "清华大学出版社",
            "source_kind": "provided",
            "evidence": "用户提供：数据结构教材.pdf",
        }
        overlap = _pool()
        overlap[0] = {**overlap[0], **textbook}
        self.assert_rejected(make_v22_payload(references=overlap, textbook=textbook), "course textbook")
        only_textbook = {
            **textbook,
            "reference_id": "REF-TEXTBOOK",
            "reference_type": "book",
            "source_region": "domestic",
        }
        self.assert_rejected(
            make_v22_payload(references=[only_textbook], textbook=textbook),
            "course textbook",
        )
        allowed = make_v22_payload(
            references=overlap,
            textbook=textbook,
            allow_textbook=True,
        )
        allowed_report = self.assert_valid_and_qa(allowed)
        self.assertTrue(allowed_report["reference_provenance"]["textbook_overlap_allowed"])
        acceptance_references = lesson_acceptance.reference_metrics(allowed, {"content_quality": allowed_report})
        self.assertEqual(acceptance_references["status"], "PASS")
        self.assertEqual(acceptance_references["textbook_overlap_count"], 6)

        duplicate = make_v22_payload(references=_pool())
        duplicate["lessons"][0]["reference_ids"] = ["REF-DOMESTIC", "REF-DOMESTIC"]
        self.assert_rejected(duplicate, "duplicate IDs")

        empty = make_v22_payload(references=_pool())
        empty["lessons"][0]["reference_ids"] = []
        self.assert_rejected(empty, r"(?:at least one citable reference|should be non-empty)")

    def test_real_manual_and_domestic_majority_are_quality_passes(self) -> None:
        manual = [
            {
                "reference_id": "REF-MANUAL",
                "reference_type": "official_manual",
                "title": "MySQL 8.0 Reference Manual",
                "source_kind": "verified_public",
                "source_region": "foreign",
                "evidence": "https://dev.mysql.com/doc/refman/8.0/en/",
            }
        ]
        self.assert_valid_and_qa(make_v22_payload(references=manual))

        refs = _pool(include_foreign=True)
        report = self.assert_valid_and_qa(make_v22_payload(references=refs))
        self.assertEqual(report["coverage"]["reference_metrics"]["domestic_source_count"], 2)
        self.assertEqual(report["coverage"]["reference_metrics"]["foreign_source_count"], 1)
        self.assertEqual(report["coverage"]["reference_metrics"]["domestic_share"], 2 / 3)
        self.assertTrue(any("below 70%" in warning for warning in report["warnings"]))

    def test_reference_reuse_does_not_exempt_same_lesson_or_narrative_duplicates(self) -> None:
        payload = make_v22_payload(theory_hours=12, lesson_count=6, specs=DB_SPECS)
        payload["lessons"][0]["teaching_content"][0] = payload["lessons"][1]["teaching_content"][0]
        payload["lessons"][0]["teacher_actions"] = payload["lessons"][1].get("teacher_actions", [])
        report = assess_content_quality(payload)
        self.assertNotEqual(report["status"], "passed")
        self.assertTrue(report["item_duplicates"] or report["exact_duplicates"] or report["field_similarity_pairs"])

    def test_generated_docx_references_are_visible_in_first_middle_last_lessons(self) -> None:
        payload = make_v22_payload(theory_hours=6, practice_hours=2, lesson_count=3, task_hours=[2], specs=DB_SPECS)
        with tempfile.TemporaryDirectory(prefix="lesson-v22-output-") as temp_name:
            root = Path(temp_name)
            source = root / "content.json"
            output = root / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--render",
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            qa = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(qa["status"], "passed", qa)
            self.assertEqual(qa["checks"]["total_hours"]["actual"], 6)
            self.assertEqual(qa["checks"]["course_hours"]["actual"], 8)
            manifest = load_manifest(V112_MANIFEST)
            files = sorted(output.glob("*.docx"))
            self.assertEqual(len(files), 3)
            for path in (files[0], files[1], files[-1]):
                document = Document(path)
                references = bookmark_text(document, field_bookmark(manifest, "references"))
                self.assertIn("数据结构（C语言版）", references)
                self.assertIn("数据结构课程标准", references)
                self.assertNotIn("投影仪", references)


if __name__ == "__main__":
    unittest.main()
