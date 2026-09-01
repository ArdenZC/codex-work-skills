from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from content_contract import (  # noqa: E402
    WorkOrderContractError,
    load_practice_task_contract,
    load_work_order_content,
    practice_tasks_to_content,
)
from content_quality import validate_collection, validate_content  # noqa: E402
from generate_work_orders import DEFAULT_TEMPLATE, generate  # noqa: E402
from validate_output import validate_document  # noqa: E402
from validate_template import validate as validate_template  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class PracticeTaskWorkOrderPackageTests(unittest.TestCase):
    def load_examples(self, name: str) -> list[dict]:
        return load_work_order_content(ROOT / "examples" / name)

    def test_canonical_template_and_manifest(self) -> None:
        template = ROOT / "assets" / "templates" / "practice-work-order" / "v1.0.0" / "template.docx"
        manifest = ROOT / "assets" / "templates" / "practice-work-order" / "v1.0.0" / "manifest.yaml"
        report = validate_template(template, manifest)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["metrics"]["sha256"], digest(template))

    def test_software_and_nursing_samples_generate_three_each(self) -> None:
        software = self.load_examples("software.example.json")
        nursing = self.load_examples("nursing.example.json")
        self.assertEqual(validate_collection(software)["status"], "pass")
        self.assertEqual(validate_collection(nursing)["status"], "pass")
        with tempfile.TemporaryDirectory(prefix="work-order-package-") as temp:
            root = Path(temp)
            first = generate(software, output_dir=root / "software", template=DEFAULT_TEMPLATE)
            second = generate(nursing, output_dir=root / "nursing", template=DEFAULT_TEMPLATE)
            self.assertEqual(first["status"], "pass")
            self.assertEqual(second["status"], "pass")
            self.assertEqual(len(list((root / "software").glob("*.docx"))), 3)
            self.assertEqual(len(list((root / "nursing").glob("*.docx"))), 3)
            for content, report in zip(software + nursing, first["outputs"] + second["outputs"]):
                self.assertEqual(report["output_qa"]["status"], "pass")
                self.assertEqual(validate_document(Path(report["path"]), content)["status"], "pass")
                self.assertEqual(report["output_qa"]["metrics"]["student_result_cells_blank"], 3)

    def test_generic_schema_accepts_accounting_tasks(self) -> None:
        content = self.load_examples("software.example.json")[0]
        content["course_name"] = "会计信息化"
        content["major"] = "大数据与会计"
        content["project_name"] = "整理月度凭证核对记录"
        content["practice_task_id"] = "AC-WO-01"
        content["task_items"][0]["title"] = "核对凭证信息"
        content["task_items"][0]["description"] = "根据凭证资料核对日期、摘要和金额，记录需要复核的项目。"
        content["task_items"][0]["tools_or_materials"] = ["凭证资料", "核对表"]
        content["task_items"][0]["steps"] = ["核对凭证字段", "记录复核项目"]
        content["task_items"][0]["deliverables"] = ["凭证核对表"]
        content["task_items"][0]["acceptance_criteria"] = ["字段核对完整", "复核项目可定位"]
        report = validate_content(content)
        self.assertEqual(report["status"], "pass", report)

    def test_lesson_practice_task_handoff_is_consumed_without_duplicate_schema(self) -> None:
        handoff = {
            "contract_version": "1.0",
            "course_name": "数据库技术",
            "practice_hours": 2,
            "granularity": "per_task",
            "tasks": [
                {
                    "task_id": "PT-01",
                    "project_id": "P-01",
                    "title": "整理数据模型需求",
                    "lesson_ids": ["L03", "L04"],
                    "practice_hours": 2,
                    "scenario": "根据业务资料整理数据模型需求。",
                    "objectives": ["识别业务对象"],
                    "required_inputs": ["业务资料"],
                    "tools_or_materials": ["需求记录表"],
                    "steps": ["分析业务对象", "记录对象关系", "核对需求记录"],
                    "deliverables": ["需求分析表"],
                    "acceptance_criteria": ["对象关系与业务资料一致"],
                    "safety_or_compliance": ["遵守资料保密要求"],
                }
            ],
        }
        with tempfile.TemporaryDirectory(prefix="work-order-handoff-") as temp:
            path = Path(temp) / "practice-task-contract.json"
            path.write_text(json.dumps(handoff, ensure_ascii=False), encoding="utf-8")
            loaded = load_practice_task_contract(path)
            contents = practice_tasks_to_content(loaded, major="软件技术", class_or_audience="一年级")
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["lesson_ids"], ["L03", "L04"])
        self.assertEqual(sum(item["score"] for item in contents[0]["task_items"]), 90)
        self.assertEqual(validate_content(contents[0])["status"], "pass")

    def test_fixed_score_and_answer_leakage_are_hard_failures(self) -> None:
        content = self.load_examples("software.example.json")[0]
        wrong_score = copy.deepcopy(content)
        wrong_score["task_items"][0]["score"] = 31
        self.assertIn("scores must total 90", " ".join(validate_content(wrong_score)["errors"]))
        answer = copy.deepcopy(content)
        answer["task_items"][0]["description"] += "；附完整 SQL 标准答案"
        self.assertIn("answer/key leakage", " ".join(validate_content(answer)["errors"]))

    def test_invalid_contract_does_not_write_output(self) -> None:
        content = self.load_examples("software.example.json")[0]
        content["task_items"][0]["deliverables"] = []
        with tempfile.TemporaryDirectory(prefix="work-order-invalid-") as temp:
            source = Path(temp) / "invalid.json"
            source.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(WorkOrderContractError):
                load_work_order_content(source)
            self.assertEqual(list(Path(temp).glob("*.docx")), [])

    def test_canonical_template_is_not_modified_by_generation(self) -> None:
        before = digest(DEFAULT_TEMPLATE)
        content = self.load_examples("software.example.json")[0]
        with tempfile.TemporaryDirectory(prefix="work-order-atomic-") as temp:
            report = generate([content], output_dir=Path(temp), template=DEFAULT_TEMPLATE)
            self.assertEqual(report["status"], "pass")
        self.assertEqual(digest(DEFAULT_TEMPLATE), before)

    def test_instruction_contract_mentions_phase_one_boundaries(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        prompt = (ROOT / "通用提示词.md").read_text(encoding="utf-8")
        for text in (skill, prompt):
            for token in ("Practice Task Contract V1", "Content V1", "10", "90", "100", "结果", "答案"):
                self.assertIn(token, text)
        self.assertIn("Phase 2", skill)


if __name__ == "__main__":
    unittest.main()
