from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
COURSEWARE_SCRIPTS = REPO / "HTML课件生成器" / "courseware-html-generator" / "scripts"
sys.path.insert(0, str(COURSEWARE_SCRIPTS))
sys.path.insert(0, str(ROOT / "scripts"))

from content_contract import normalize_content as normalize_courseware  # noqa: E402
from content_contract import validate_content as validate_courseware  # noqa: E402
from pedagogical_review import review_content as review_courseware  # noqa: E402
from render_courseware import generate as render_courseware  # noqa: E402
from repair_courseware import repair_content as repair_courseware_content  # noqa: E402
from practice_contract import load_courseware, load_json, normalize_content, validate_content  # noqa: E402
from practice_pedagogical_review import review_content as review_practice  # noqa: E402


class G1AdaptivePlanningTests(unittest.TestCase):
    def courseware(self) -> dict:
        return load_json(COURSEWARE_SCRIPTS.parent / "examples" / "data-structures.example.json")

    def practice(self) -> dict:
        return load_json(ROOT / "examples" / "data-structures.practice.json")

    def courseware_path(self) -> Path:
        return COURSEWARE_SCRIPTS.parent / "examples" / "data-structures.example.json"

    def test_courseware_missing_learning_unit_fails_then_repair_fills_from_facts(self) -> None:
        content, _ = normalize_courseware(self.courseware())
        content["slides"][0]["learning_unit_ids"] = []
        self.assertEqual(validate_courseware(content)["status"], "fail")
        repaired = repair_courseware_content(content)
        self.assertEqual(repaired["status"], "pass", repaired)
        self.assertTrue(repaired["actions"])

    def test_courseware_short_script_is_pedagogical_failure_not_schema_failure(self) -> None:
        content, _ = normalize_courseware(self.courseware())
        content["slides"][0]["lecture_minutes"] = 8
        content["slides"][0]["suggested_minutes"] = max(8, content["slides"][0]["suggested_minutes"])
        content["slides"][0]["activity_minutes"] = content["slides"][0]["suggested_minutes"] - 8
        planned = sum(slide["suggested_minutes"] for slide in content["slides"])
        content.update(session_minutes=planned, prepared_minutes=planned, core_minutes=planned, extension_minutes=0)
        content["slides"][0]["speaker_script"] = "太短"
        self.assertEqual(validate_courseware(content)["status"], "pass")
        report = review_courseware(content)
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(report["metrics"]["speaker_script_planning"]["errors"])

    def test_courseware_repeated_sentence_warns_but_repeated_script_fails(self) -> None:
        content, _ = normalize_courseware(self.courseware())
        sentence = "这一句用于说明当前概念与例子的关系，教师可以结合页面继续解释。"
        content["slides"][0]["speaker_script"] = " ".join([sentence] * 3)
        report = review_courseware(content)
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("repeats" in item for item in report["metrics"]["speaker_script_repetition"]["warnings"]))
        paragraph = "这是一段需要被发现的完整重复讲稿，包含当前图示、例子、误解、提问、边界和教师应补充的因果解释。"
        repeated_script = "\n\n".join([paragraph] * 4)
        for slide in content["slides"]:
            slide["speaker_script"] = repeated_script
        repeated = review_courseware(content)
        self.assertEqual(repeated["status"], "FAIL", repeated)
        self.assertTrue(repeated["metrics"]["speaker_script_repetition"]["errors"])

    def test_courseware_prepared_extension_requires_explicit_teacher_path(self) -> None:
        content, _ = normalize_courseware(self.courseware())
        content["session_minutes"] = 90
        content["prepared_minutes"] = 120
        content["core_minutes"] = 90
        content["extension_minutes"] = 30
        planned = [20, 20, 20, 30, 30]
        for slide, minutes in zip(content["slides"], planned):
            slide["lecture_minutes"] = minutes
            slide["activity_minutes"] = 0
            slide["suggested_minutes"] = minutes
            slide.pop("delivery_track", None)
        self.assertEqual(validate_courseware(content)["status"], "pass")
        report = review_courseware(content)
        self.assertTrue(any("extension" in item for item in report["errors"]), report)
        content["slides"][-1]["delivery_track"] = "extension"
        self.assertEqual(review_courseware(content)["metrics"]["delivery_paths"]["metrics"]["track_minutes"]["extension"], 30)

    def test_valid_mixed_layouts_remain_renderable(self) -> None:
        content, _ = normalize_courseware(self.courseware())
        self.assertEqual(validate_courseware(content)["status"], "pass")
        self.assertGreaterEqual(len({slide["layout"] for slide in content["slides"]}), 3)
        with tempfile.TemporaryDirectory(prefix="courseware-g1-smoke-") as temp:
            report = render_courseware(self.courseware_path(), Path(temp) / "courseware")
            self.assertEqual(report["status"], "pass", report)
            self.assertEqual(report["qa"]["status"], "pass", report)

    def _trim_task(self, content: dict, task_id: str) -> None:
        content["tasks"] = [task for task in content["tasks"] if task.get("id") != task_id]
        for collection in ("learning_center", "study_guide", "foundation_kit"):
            for item in content.get(collection, []):
                if isinstance(item, dict):
                    item["task_ids"] = [value for value in item.get("task_ids", []) if value != task_id]
        guide = content.get("teacher_guide", {})
        if isinstance(guide, dict):
            guide["task_guidance"] = [item for item in guide.get("task_guidance", []) if item.get("task_id") != task_id]
        reference = content.get("teacher_reference", {})
        if isinstance(reference, dict):
            reference["task_references"] = [item for item in reference.get("task_references", []) if item.get("task_id") != task_id]

    def test_practice_debugging_requires_symptom_and_complete_task_passes(self) -> None:
        content, _ = normalize_content(self.practice(), load_courseware(self.courseware_path()))
        task = content["tasks"][0]
        task["task_kind"] = "debugging"
        task["capabilities"] = ["diagnosis", "explanation"]
        for field in ("symptom", "faulty_artifact", "expected_behavior", "diagnosis_target", "repair_target"):
            task.pop(field, None)
        report = validate_content(content, load_courseware(self.courseware_path()))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("symptom" in item for item in report["errors"]))
        task.update({
            "symptom": "结果为空",
            "faulty_artifact": "starter output",
            "expected_behavior": "返回目标位置",
            "diagnosis_target": "检查边界更新",
            "repair_target": "修复边界更新",
        })
        self.assertEqual(validate_content(content, load_courseware(self.courseware_path()))["status"], "pass")

    def test_required_canonical_fact_is_checked_when_task_claims_theory_source(self) -> None:
        content, _ = normalize_content(self.practice(), load_courseware(self.courseware_path()))
        task = next(item for item in content["tasks"] if item["level"] == "core")
        task["canonical_fact_ids"] = []
        report = validate_content(content, load_courseware(self.courseware_path()))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("canonical_fact_ids" in item for item in report["errors"]))

    def test_levels_and_learning_center_are_affordance_driven(self) -> None:
        courseware = load_courseware(self.courseware_path())
        content, _ = normalize_content(self.practice(), courseware)
        self._trim_task(content, content["tasks"][-1]["id"])
        for index, task in enumerate(content["tasks"]):
            task["level"] = "core" if index < 5 else "optional"
        report = validate_content(content, courseware)
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["metrics"]["core_tasks"], 5)
        self.assertEqual(report["metrics"]["optional_tasks"], 2)
        self.assertEqual(report["metrics"]["challenge_tasks"], 0)

        three_centers = copy.deepcopy(content["learning_center"][:3])
        content["learning_center"] = three_centers
        self.assertEqual(validate_content(content, courseware)["status"], "pass")

    def test_core_starter_and_study_guide_can_pass_without_learning_center(self) -> None:
        courseware = load_courseware(self.courseware_path())
        content, _ = normalize_content(self.practice(), courseware)
        content["learning_center"] = []
        contract = validate_content(content, courseware)
        self.assertEqual(contract["status"], "pass")
        self.assertIn(review_practice(content, contract)["status"], {"DEGRADED", "PASS"})

    def test_student_starter_replacement_leakage_fails_and_clean_teacher_reference_passes(self) -> None:
        courseware = load_courseware(self.courseware_path())
        content, _ = normalize_content(self.practice(), courseware)
        asset = next(item for item in content["starter_assets"] if item.get("editable_gaps"))
        gap = asset["editable_gaps"][0]
        original = asset["content"]
        asset["content"] = original.replace(gap["marker"], f"{gap['marker']} {gap['replacement']}")
        report = validate_content(content, courseware)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("leaks" in item for item in report["errors"]))
        content, _ = normalize_content(self.practice(), courseware)
        self.assertEqual(validate_content(content, courseware)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
