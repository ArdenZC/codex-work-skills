from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_lesson_content_v21 import make_v21_fixture
from tests.test_lesson_content_v2 import lesson_generator
from tests.test_lesson_content_v22 import LESSON, assess_content_quality, make_v22_payload, run_script
from tests.test_lesson_skill_hardening import lesson_acceptance


class Lesson22ContractHardeningTests(unittest.TestCase):
    def assert_rejected(self, payload: dict[str, object], pattern: str | None = None) -> None:
        with self.assertRaises(ValueError) as raised:
            lesson_generator.validate_content_v2_input(payload)
        if pattern:
            self.assertRegex(str(raised.exception), pattern)

    def test_v22_canonical_stage_invariants_have_explicit_hard_negatives(self) -> None:
        valid = make_v22_payload(theory_hours=2, practice_hours=0, lesson_count=1)
        lesson_generator.validate_content_v2_input(valid)

        bad_order = copy.deepcopy(valid)
        stages = bad_order["lessons"][0]["implementation"]
        stages[3], stages[4] = stages[4], stages[3]
        self.assert_rejected(bad_order, "canonical order")

        duplicate = copy.deepcopy(valid)
        duplicate["lessons"][0]["implementation"][4]["id"] = "task_implementation"
        self.assert_rejected(duplicate, "stage IDs must be unique")

        missing = copy.deepcopy(valid)
        missing["lessons"][0]["implementation"].pop()
        self.assert_rejected(missing, "Input schema validation failed")

        extra = copy.deepcopy(valid)
        extra["lessons"][0]["implementation"].append(copy.deepcopy(extra["lessons"][0]["implementation"][-1]))
        self.assert_rejected(extra, "Input schema validation failed")

        bad_minutes = copy.deepcopy(valid)
        bad_minutes["lessons"][0]["implementation"][3]["minutes"] += 2
        self.assert_rejected(bad_minutes, r"hours\*45")

        out_of_class = copy.deepcopy(valid)
        out_of_class["lessons"][0]["implementation"][0]["minutes"] = 91
        self.assert_rejected(out_of_class, "out-of-class minutes")

    def test_v21_uses_the_same_stage_invariant_helper(self) -> None:
        valid = make_v21_fixture()
        lesson_generator.validate_content_v2_input(valid)

        bad_order = copy.deepcopy(valid)
        stages = bad_order["lessons"][0]["implementation"]
        stages[3], stages[4] = stages[4], stages[3]
        self.assert_rejected(bad_order, "canonical order")

    def test_practice_task_lesson_id_compatibility_is_version_aware(self) -> None:
        v21 = make_v21_fixture(practice=True)
        lesson_generator.validate_content_v2_input(v21)
        v21_empty = copy.deepcopy(v21)
        v21_empty["practice_task_contract"]["tasks"][0]["lesson_ids"] = []
        self.assert_rejected(v21_empty, "Content Contract 2.1")

        v22_pure = make_v22_payload(
            theory_hours=0,
            practice_hours=8,
            lesson_count=0,
            task_hours=[2, 2, 2, 2],
            practice_work_orders=True,
        )
        lesson_generator.validate_content_v2_input(v22_pure)
        self.assertEqual(v22_pure["practice_task_contract"]["tasks"][0]["lesson_ids"], [])

        v22_linked = make_v22_payload(
            theory_hours=2,
            practice_hours=8,
            lesson_count=1,
            task_hours=[2, 2, 2, 2],
            practice_work_orders=True,
        )
        lesson_generator.validate_content_v2_input(v22_linked)
        v22_empty = copy.deepcopy(v22_linked)
        v22_empty["practice_task_contract"]["tasks"][0]["lesson_ids"] = []
        self.assert_rejected(v22_empty, "related theory Lessons")

    def test_pure_practice_acceptance_marks_lesson_docx_gates_not_applicable(self) -> None:
        payload = make_v22_payload(
            course="护理技能实训",
            major="护理专业",
            theory_hours=0,
            practice_hours=8,
            lesson_count=0,
            practice_work_orders=True,
        )
        with tempfile.TemporaryDirectory(prefix="lesson-22-hardening-pure-practice-") as temp_name:
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
            report = lesson_acceptance.build_acceptance_report(
                source,
                output,
                output / "qa-report.json",
                source_type="synthetic_fixture",
                report_dir=root / "acceptance",
            )
            gates = {item["name"]: item for item in report["structural_hard_gates"]["gates"]}
            self.assertEqual(report["structural_hard_gates"]["status"], "PASS")
            self.assertFalse(report["structural_hard_gates"]["lesson_docx_applicable"])
            for name in (
                "docx_inventory",
                "qa_files_checked",
                "template_names_and_fidelity",
                "semantic_bookmarks",
                "render_smoke",
            ):
                self.assertEqual(gates[name]["status"], "NOT_APPLICABLE", name)
            self.assertEqual(gates["total_hours"]["status"], "PASS")
            self.assertEqual(gates["delivery_consistency"]["status"], "PASS")
            self.assertEqual(gates["practice_handoff"]["status"], "PASS")
            self.assertNotEqual(report["final_status"], "FAILED")

            handoff = json.loads((output / "practice-task-contract.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["practice_hours"], 8)
            self.assertEqual(len(handoff["tasks"]), 4)
            self.assertEqual(sum(task["practice_hours"] for task in handoff["tasks"]), 8)

    def test_eight_hour_split_smoke_generates_lesson_and_practice_artifacts(self) -> None:
        payload = make_v22_payload(
            course="数据结构高级",
            major="软件工程专业",
            theory_hours=4,
            practice_hours=4,
            lesson_count=2,
            lesson_hours=[2, 2],
            task_hours=[2, 2],
            practice_work_orders=True,
        )
        self.assertTrue(all(lesson["reference_ids"] for lesson in payload["lessons"]))
        with tempfile.TemporaryDirectory(prefix="lesson-22-hardening-split-smoke-") as temp_name:
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
            self.assertEqual(len(list(output.glob("*.docx"))), 2)
            handoff = json.loads((output / "practice-task-contract.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["practice_hours"], 4)
            self.assertEqual(sum(task["practice_hours"] for task in handoff["tasks"]), 4)
            self.assertEqual(handoff["tasks"][0]["lesson_ids"], ["L01", "L02"])
            self.assertEqual(len(handoff["tasks"]), 2)

            report = lesson_acceptance.build_acceptance_report(
                source,
                output,
                output / "qa-report.json",
                source_type="synthetic_fixture",
                report_dir=root / "acceptance",
            )
            gates = {item["name"]: item for item in report["structural_hard_gates"]["gates"]}
            self.assertTrue(report["structural_hard_gates"]["lesson_docx_applicable"])
            for name in (
                "docx_inventory",
                "qa_files_checked",
                "total_hours",
                "delivery_consistency",
                "reference_hard_gates",
                "practice_handoff",
                "template_identity",
                "template_names_and_fidelity",
                "semantic_bookmarks",
                "content_quality",
            ):
                self.assertEqual(gates[name]["status"], "PASS", name)
            # LibreOffice availability and PDF conversion behavior are runner
            # concerns; this regression targets the split/handoff contracts.
            self.assertIn(gates["render_smoke"]["status"], {"PASS", "FAIL"})

    def test_pure_theory_keeps_lesson_anchor_gate_applicable(self) -> None:
        payload = make_v22_payload(theory_hours=2, practice_hours=0, lesson_count=1)
        with tempfile.TemporaryDirectory(prefix="lesson-22-hardening-pure-theory-") as temp_name:
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
            report = lesson_acceptance.build_acceptance_report(
                source,
                output,
                output / "qa-report.json",
                source_type="synthetic_fixture",
                report_dir=root / "acceptance",
            )
            gates = {item["name"]: item for item in report["structural_hard_gates"]["gates"]}
            self.assertTrue(report["structural_hard_gates"]["lesson_docx_applicable"])
            self.assertEqual(gates["semantic_bookmarks"]["status"], "PASS")
            self.assertIn(gates["render_smoke"]["status"], {"PASS", "FAIL"})

    def test_practice_hours_without_workorders_require_no_contract(self) -> None:
        payload = make_v22_payload(
            theory_hours=4,
            practice_hours=20,
            lesson_count=2,
            practice_work_orders=False,
        )
        lesson_generator.validate_content_v2_input(payload)
        report = lesson_acceptance.delivery_metrics(payload)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["actual"]["practice_hours"], 20)
        self.assertEqual(report["actual"]["practice_task_count"], 0)
        self.assertEqual(assess_content_quality(payload)["practice_handoff"]["status"], "not_applicable")
        self.assertNotIn("practice_task_contract", payload)

    def test_workorders_true_uses_exact_two_hour_task_units(self) -> None:
        payload = make_v22_payload(
            theory_hours=4,
            practice_hours=20,
            lesson_count=2,
            practice_work_orders=True,
        )
        lesson_generator.validate_content_v2_input(payload)
        tasks = payload["practice_task_contract"]["tasks"]
        self.assertEqual(len(tasks), 10)
        self.assertTrue(all(task["practice_hours"] == 2 for task in tasks))
        self.assertEqual(
            len({task["task_id"] for task in tasks}),
            len(tasks),
        )
        self.assertEqual(assess_content_quality(payload)["practice_handoff"]["task_count"], 10)

    def test_odd_practice_hours_fail_closed_when_workorders_are_enabled(self) -> None:
        payload = make_v22_payload(
            theory_hours=2,
            practice_hours=14,
            lesson_count=1,
            practice_work_orders=True,
        )
        payload["total_hours"] = 17
        payload["delivery_plan"]["total_hours"] = 17
        payload["delivery_plan"]["practice_hours"] = 15
        payload["practice_task_contract"]["practice_hours"] = 15
        self.assert_rejected(payload, r"divisible by 2")

    def test_workorder_preference_can_be_enabled_without_changing_confirmed_hours(self) -> None:
        pending_choice = make_v22_payload(
            theory_hours=4,
            practice_hours=4,
            lesson_count=2,
            practice_work_orders=False,
        )
        enabled = copy.deepcopy(pending_choice)
        enabled["artifact_plan"]["practice_work_orders"] = True
        source_with_handoff = make_v22_payload(
            theory_hours=4,
            practice_hours=4,
            lesson_count=2,
            practice_work_orders=True,
        )
        enabled["practice_task_contract"] = source_with_handoff["practice_task_contract"]
        enabled["lessons"][0]["practice_task_ids"] = [
            task["task_id"] for task in enabled["practice_task_contract"]["tasks"]
        ]
        enabled["outline"][0]["practice_task_ids"] = list(enabled["lessons"][0]["practice_task_ids"])
        lesson_generator.validate_content_v2_input(enabled)
        self.assertEqual(
            {
                key: enabled["delivery_plan"][key]
                for key in ("total_hours", "theory_hours", "practice_hours", "mode")
            },
            {
                key: pending_choice["delivery_plan"][key]
                for key in ("total_hours", "theory_hours", "practice_hours", "mode")
            },
        )


if __name__ == "__main__":
    unittest.main()
