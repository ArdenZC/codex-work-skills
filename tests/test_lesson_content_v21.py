from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from docx import Document

from tests.test_lesson_content_v2 import (
    LESSON,
    ROOT,
    SCRIPTS,
    assess_content_quality,
    bookmark_text,
    document_text,
    field_bookmark,
    lesson_content_contract,
    lesson_content_quality,
    lesson_generator,
    lesson_output,
    lesson_package_common,
    load_fixture,
    load_manifest,
    run_script,
    write_payload,
)
from tests.test_lesson_skill_hardening import lesson_acceptance


def _reference_pool(*, generic: bool = False) -> list[dict[str, object]]:
    standard: dict[str, object] = {
        "reference_id": "REF-B",
        "reference_type": "standard",
        "title": "软件测试课程标准相关章节" if generic else "软件测试课程标准",
        "source_kind": "generic" if generic else "verified_public",
    }
    if not generic:
        standard["evidence"] = "https://example.edu/software-testing-standard"
    return [
        {
            "reference_id": "REF-A",
            "reference_type": "book",
            "title": "软件测试基础",
            "authors": ["测试教材编写组"],
            "edition": "第1版",
            "publisher": "教育出版社",
            "source_kind": "provided",
            "evidence": "用户上传：软件测试基础.pdf",
        },
        standard,
    ]


def make_v21_fixture(*, generic: bool = False, practice: bool = False) -> dict:
    data = copy.deepcopy(load_fixture("lesson-plan-content-v2-it.json"))
    data["content_contract_version"] = "2.1"
    data["default_hours"] = 2
    data["lessons"] = data["lessons"][:4] if practice else data["lessons"][:6]
    data["total_hours"] = 8 if practice else 12
    data["course_materials"] = {
        "textbook": {
            "title": "软件测试基础教材",
            "authors": ["课程教材编写组"],
            "edition": "第2版",
            "publisher": "教育出版社",
            "source_kind": "provided",
            "evidence": "用户上传：软件测试基础教材.pdf",
        }
    }
    data["reference_pool"] = _reference_pool(generic=generic)
    data["artifact_plan"] = {"lesson_plans": True, "practice_work_orders": False}
    if practice:
        data["delivery_plan"] = {
            "mode": "split_lessons",
            "total_hours": 8,
            "theory_hours": 4,
            "practice_hours": 4,
        }
    else:
        data["delivery_plan"] = {
            "mode": "theory_only",
            "total_hours": 12,
            "theory_hours": 12,
            "practice_hours": 0,
        }
    for index, lesson in enumerate(data["lessons"]):
        lesson["lesson_type"] = "practice" if practice and index >= 2 else "theory"
        lesson["theory_hours"] = 0 if lesson["lesson_type"] == "practice" else lesson["hours"]
        lesson["practice_hours"] = lesson["hours"] if lesson["lesson_type"] == "practice" else 0
        lesson["reference_ids"] = ["REF-A", "REF-B"]
        lesson["practice_task_ids"] = ["PT-01"] if lesson["lesson_type"] == "practice" else []
        lesson.pop("references", None)
    if practice:
        data["practice_task_contract"] = {
            "contract_version": "1.0",
            "course_name": data["course_name"],
            "practice_hours": 4,
            "granularity": "per_task",
            "tasks": [
                {
                    "task_id": "PT-01",
                    "project_id": "P-01",
                    "title": "完成测试用例执行与缺陷复盘",
                    "lesson_ids": ["L03", "L04"],
                    "practice_hours": 4,
                    "scenario": "依据已形成的测试计划完成一次可追溯的功能验证。",
                    "objectives": ["执行测试用例并记录结果", "根据证据定位并复盘缺陷"],
                    "required_inputs": ["测试计划初稿", "功能需求片段"],
                    "tools_or_materials": ["测试环境", "样例数据", "缺陷记录表"],
                    "steps": ["准备环境和数据", "执行用例并记录证据", "复盘缺陷并整理成果"],
                    "deliverables": ["测试执行记录", "缺陷复盘表"],
                    "acceptance_criteria": ["每条结果均有对应证据", "缺陷复盘能说明影响和处理建议"],
                    "safety_or_compliance": ["遵守测试环境数据使用规范"],
                }
            ],
        }
    data["outline"] = [
        {
            "lesson_id": lesson["lesson_id"],
            "unit": lesson["unit"],
            "task": lesson["task"],
            "lesson_type": lesson["lesson_type"],
            "hours": lesson["hours"],
            "theory_hours": lesson["theory_hours"],
            "practice_hours": lesson["practice_hours"],
            "prior_learning": lesson["progression"]["prior_learning"],
            "capability_stage": lesson["progression"]["capability_stage"],
            "deliverable": lesson["progression"]["deliverable"],
            "next_bridge": lesson["progression"]["next_bridge"],
            "practice_task_ids": lesson["practice_task_ids"],
        }
        for lesson in data["lessons"]
    ]
    return data


class LessonContentV21Tests(unittest.TestCase):
    def assert_rejected(self, payload: dict, pattern: str | None = None) -> None:
        with self.assertRaises(ValueError) as raised:
            lesson_generator.validate_content_v2_input(payload)
        if pattern:
            self.assertRegex(str(raised.exception), pattern)

    def test_v21_schema_and_legacy_v20_compatibility(self) -> None:
        payload = make_v21_fixture()
        lesson_generator.validate_content_v2_input(payload)
        lesson_generator.validate_content_v2_input(load_fixture("lesson-plan-input.json"))
        report = lesson_content_contract.lesson_content_field_values(payload["lessons"][0], payload)
        self.assertIn("《软件测试基础》", report["references"])
        self.assertIn("《软件测试课程标准》", report["references"])
        self.assertNotIn("用户上传：软件测试基础.pdf", report["references"])

    def test_same_provided_verified_and_generic_document_references_reuse_across_six_lessons(self) -> None:
        for generic in (False, True):
            with self.subTest(generic=generic):
                payload = make_v21_fixture(generic=generic)
                lesson_generator.validate_content_v2_input(payload)
                report = assess_content_quality(payload)
                self.assertEqual(report["status"], "passed", report)
                self.assertEqual(report["reference_provenance"]["cross_lesson_reuse"], "allowed")
                self.assertEqual(report["reference_provenance"]["same_lesson_duplicates"], [])
                self.assertEqual(report["coverage"]["reference_metrics"]["unresolved_id_count"], 0)
                self.assertEqual(report["coverage"]["reference_metrics"]["reuse_frequency"]["REF-A"], 6)

    def test_reference_reuse_scales_without_course_duplicate_failures(self) -> None:
        payload = make_v21_fixture()
        report = assess_content_quality(payload)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["reuse_policy"]["classes"]["references"], "reference_reusable")
        self.assertEqual(report["reference_provenance"]["reuse_frequency"]["REF-A"], 6)
        self.assertNotIn("reference_ids", " ".join(report["errors"]))

        cross_lesson_duplicate_detectors = (
            "exact_duplicates",
            "adjacent_exact_duplicates",
            "item_duplicates",
            "adjacent_item_duplicates",
            "frequency_item_duplicates",
            "repeated_sentences",
            "adjacent_similarity_pairs",
            "field_similarity_pairs",
            "adjacent_field_similarity_pairs",
            "structural_similarity_pairs",
            "whole_lesson_similarity_pairs",
            "high_similarity_pairs",
        )
        for detector in cross_lesson_duplicate_detectors:
            with self.subTest(detector=detector):
                for item in report[detector]:
                    if "reference" in json.dumps(item, ensure_ascii=False).lower():
                        self.assertTrue(item.get("allowed"), item)
                        self.assertEqual(item.get("reuse_policy"), "reference_reusable")

    def test_reference_exemption_does_not_exempt_teaching_content(self) -> None:
        payload = make_v21_fixture()
        payload["lessons"][1]["teaching_content"] = copy.deepcopy(payload["lessons"][0]["teaching_content"])
        report = assess_content_quality(payload)
        self.assertEqual(report["status"], "failed", report)
        duplicate_records = []
        for detector in (
            "exact_duplicates",
            "adjacent_exact_duplicates",
            "item_duplicates",
            "adjacent_item_duplicates",
            "frequency_item_duplicates",
            "field_similarity_pairs",
            "whole_lesson_similarity_pairs",
        ):
            duplicate_records.extend(report[detector])
        self.assertTrue(
            any("teaching_content" in json.dumps(item, ensure_ascii=False) for item in duplicate_records),
            duplicate_records,
        )

    def test_reference_gate_accepts_twenty_and_thirty_two_lesson_reuse(self) -> None:
        pool = [
            {
                "reference_id": "REF-A",
                "reference_type": "book",
                "title": "核心教材 A",
                "source_kind": "provided",
                "evidence": "用户上传：核心教材A.pdf",
            },
            {
                "reference_id": "REF-B",
                "reference_type": "standard",
                "title": "课程标准 B 相关章节",
                "source_kind": "generic",
            },
        ]
        for lesson_count in (20, 32):
            with self.subTest(lesson_count=lesson_count):
                lessons = [
                    {"lesson_id": f"L{index:02d}", "reference_ids": ["REF-A", "REF-B"]}
                    for index in range(1, lesson_count + 1)
                ]
                data = {
                    "content_contract_version": "2.1",
                    "course_materials": {"textbook": None},
                    "reference_pool": pool,
                    "lessons": lessons,
                }
                provenance = lesson_content_quality._reference_provenance_report(
                    lessons,
                    [lesson["lesson_id"] for lesson in lessons],
                    data,
                )
                reference_report = lesson_acceptance.reference_metrics(
                    data,
                    {"content_quality": {"reference_provenance": provenance}},
                )
                self.assertEqual(reference_report["status"], "PASS")
                self.assertEqual(reference_report["reuse_frequency"], {"REF-A": lesson_count, "REF-B": lesson_count})
                self.assertEqual(provenance["cross_lesson_reuse"], "allowed")
                self.assertEqual(provenance["same_lesson_duplicates"], [])
                self.assertEqual(provenance["unresolved_ids"], [])

    def test_reference_boundary_negative_controls_and_valid_sources(self) -> None:
        cases: list[tuple[str, callable, str]] = []
        cases.append(("duplicate-id", lambda item: item["lessons"][0]["reference_ids"].append("REF-A"), "duplicate IDs"))
        cases.append(("missing-id", lambda item: item["lessons"][0]["reference_ids"].__setitem__(0, "REF-MISSING"), "unresolved IDs"))
        cases.append(("resource", lambda item: item["reference_pool"][0].update({"title": "投影仪"}), "resource-only"))
        cases.append(("placeholder", lambda item: item["reference_pool"][0].update({"title": "统一建模语言相关公开文档"}), "placeholder"))
        cases.append(("invented-generic", lambda item: item["reference_pool"][0].update({"source_kind": "generic", "title": "《虚构教材》 作者甲 ISBN 978-7-0000-0000-0"}), "bibliographic"))
        cases.append(("textbook-overlap", lambda item: item["reference_pool"][0].update({"title": item["course_materials"]["textbook"]["title"]}), "textbook"))
        cases.append(
            (
                "same-lesson-same-document-different-ids",
                lambda item: (
                    item["reference_pool"].append(
                        {
                            "reference_id": "REF-C",
                            "reference_type": "book",
                            "title": item["reference_pool"][0]["title"],
                            "authors": item["reference_pool"][0]["authors"],
                            "edition": item["reference_pool"][0]["edition"],
                            "publisher": item["reference_pool"][0]["publisher"],
                            "source_kind": "provided",
                            "evidence": "用户上传：软件测试基础.pdf",
                        }
                    ),
                    item["lessons"][0]["reference_ids"].append("REF-C"),
                )[-1],
                "duplicate reference content",
            )
        )
        for label, mutate, pattern in cases:
            with self.subTest(case=label):
                payload = make_v21_fixture()
                mutate(payload)
                self.assert_rejected(payload, pattern)

        valid_public = make_v21_fixture()
        valid_public["reference_pool"][0] = {
            "reference_id": "REF-A",
            "reference_type": "official_manual",
            "title": "MySQL 8.0 Reference Manual",
            "source_kind": "verified_public",
            "evidence": "https://dev.mysql.com/doc/refman/8.0/en/",
        }
        lesson_generator.validate_content_v2_input(valid_public)

    def test_empty_reference_ids_render_as_blank(self) -> None:
        payload = make_v21_fixture()
        payload["lessons"] = payload["lessons"][:1]
        payload["lessons"][0]["reference_ids"] = []
        payload["total_hours"] = 2
        payload["delivery_plan"] = {"mode": "theory_only", "total_hours": 2, "theory_hours": 2, "practice_hours": 0}
        payload["outline"] = [copy.deepcopy(payload["outline"][0])]
        lesson_generator.validate_content_v2_input(payload)
        self.assertEqual(lesson_content_contract.lesson_content_field_values(payload["lessons"][0], payload)["references"], "")
        with tempfile.TemporaryDirectory(prefix="lesson-v21-empty-references-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            result = run_script(LESSON / "scripts" / "generate_lesson_plans.py", "--tasks-json", str(source), "--output-dir", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            document = Document(next(output.glob("*.docx")))
            manifest = load_manifest(LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "manifest.yaml")
            self.assertEqual(bookmark_text(document, field_bookmark(manifest, "references")), "")

    def test_practice_generation_writes_only_handoff_and_formal_citations(self) -> None:
        payload = make_v21_fixture(practice=True)
        with tempfile.TemporaryDirectory(prefix="lesson-v21-practice-output-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            result = run_script(LESSON / "scripts" / "generate_lesson_plans.py", "--tasks-json", str(source), "--output-dir", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(output.glob("*.docx"))), 4)
            self.assertTrue((output / "practice-task-contract.json").is_file())
            text = document_text(Document(sorted(output.glob("*.docx"))[0]))
            self.assertIn("软件测试基础", text)
            self.assertIn("软件测试课程标准", text)
            self.assertNotIn("用户上传：软件测试基础.pdf", text)
            self.assertNotIn("https://example.edu/software-testing-standard", text)
            self.assertNotIn("REF-A", text)

    def test_practice_task_contract_reconciles_and_rejects_wrong_links(self) -> None:
        payload = make_v21_fixture(practice=True)
        lesson_generator.validate_content_v2_input(payload)
        report = assess_content_quality(payload)
        self.assertEqual(report["status"], "passed", report)
        self.assertEqual(report["practice_handoff"]["status"], "passed")
        self.assertEqual(report["practice_handoff"]["task_count"], 1)
        self.assertEqual(report["practice_handoff"]["expected_practice_hours"], 4)
        bad_link = copy.deepcopy(payload)
        bad_link["practice_task_contract"]["tasks"][0]["lesson_ids"] = ["L01", "L03"]
        self.assert_rejected(bad_link, "theory")
        bad_hours = copy.deepcopy(payload)
        bad_hours["practice_task_contract"]["tasks"][0]["practice_hours"] = 3
        self.assert_rejected(bad_hours, "practice task hours")
        bad_type = copy.deepcopy(payload)
        bad_type["lessons"][2]["lesson_type"] = "theory"
        bad_type["outline"][2]["lesson_type"] = "theory"
        self.assert_rejected(bad_type, "theory")
        fractional = copy.deepcopy(payload)
        fractional["lessons"][0]["hours"] = 0.5
        fractional["lessons"][0]["theory_hours"] = 0.5
        fractional["outline"][0]["hours"] = 0.5
        fractional["outline"][0]["theory_hours"] = 0.5
        self.assert_rejected(fractional, "not valid")

    def test_acceptance_v21_metrics_and_static_instruction_contract(self) -> None:
        payload = make_v21_fixture(practice=True)
        quality = assess_content_quality(payload)
        delivery = lesson_acceptance.delivery_metrics(payload)
        references = lesson_acceptance.reference_metrics(payload, {"content_quality": quality})
        practice = lesson_acceptance.practice_handoff_metrics(payload, {"content_quality": quality})
        self.assertEqual(delivery["status"], "PASS")
        self.assertEqual(references["status"], "PASS")
        self.assertEqual(references["reuse_frequency"]["REF-A"], 4)
        self.assertEqual(practice["status"], "passed")
        canonical = "\n".join(
            (LESSON / name).read_text(encoding="utf-8")
            for name in ("SKILL.md", "通用提示词.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "CONVENTIONS.md", "agents/openai.yaml")
        )
        for token in ("course_name", "major", "audience", "total_hours", "theory_hours", "practice_hours", "default_hours=2", "textbook", "auxiliary_references", "practice_work_orders", "course_reference_pool"):
            self.assertIn(token, canonical)
        self.assertRegex(canonical, re.compile(r"一次集中|一次性|one[- ]time", re.IGNORECASE))
        self.assertRegex(canonical, re.compile(r"不得再问.*(?:模板|输出目录|DOCX)|不再询问.*(?:模板|输出目录|DOCX)", re.IGNORECASE | re.DOTALL))
        self.assertIn("references", canonical)
        self.assertIn("resources", canonical)


if __name__ == "__main__":
    unittest.main()
