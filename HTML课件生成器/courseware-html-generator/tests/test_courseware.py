from __future__ import annotations

import hashlib
import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from content_contract import CoursewareContractError, load_content, normalize_content, validate_content  # noqa: E402
from install_adapters import install as install_adapters  # noqa: E402
from install import install as install_skill  # noqa: E402
from render_courseware import generate  # noqa: E402
from validate_courseware import validate_files, validate_html_outputs  # noqa: E402
from pedagogical_review import review_content  # noqa: E402
from pedagogical_review import theory_practice_boundary_review  # noqa: E402
from planning_integrity import gold_batch_review  # noqa: E402


class CoursewarePackageTests(unittest.TestCase):
    def load_example(self, name: str) -> dict:
        return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))

    def test_data_structure_and_uml_contracts_are_valid(self) -> None:
        for name in ("data-structures.example.json", "uml.example.json"):
            report = validate_content(self.load_example(name))
            self.assertEqual(report["status"], "pass", report)
            self.assertGreaterEqual(report["metrics"]["slides"], 2)

    def test_course_context_is_valid_and_keeps_stable_slide_ids(self) -> None:
        data = self.load_example("data-structures.example.json")
        uml = self.load_example("uml.example.json")
        self.assertEqual(data["course_context"]["language"], "C")
        self.assertEqual(data["course_context"]["tools"], ["Dev-C++", "Code::Blocks"])
        self.assertEqual(uml["course_context"]["tools"], ["draw.io", "StarUML"])
        self.assertEqual([slide["id"] for slide in data["slides"]], ["search-01", "search-02", "search-03", "search-04", "search-05"])

    def test_render_produces_two_offline_single_files_and_qa(self) -> None:
        content_path = ROOT / "examples" / "data-structures.example.json"
        with tempfile.TemporaryDirectory(prefix="courseware-package-") as temp:
            output = Path(temp) / "courseware"
            report = generate(content_path, output)
            self.assertEqual(report["status"], "pass", report)
            self.assertEqual(report["qa"]["status"], "pass", report)
            self.assertEqual({item.name for item in output.iterdir()}, {"student.html", "teacher.html", "qa-report.json"})
            qa = validate_files(content_path, output / "student.html", output / "teacher.html")
            self.assertEqual(qa["status"], "pass", qa)
            student = (output / "student.html").read_text(encoding="utf-8")
            teacher = (output / "teacher.html").read_text(encoding="utf-8")
            self.assertNotIn("speaker_script", student)
            self.assertNotIn("content_reserve_minutes", student)
            self.assertNotIn("建议 3 分钟", student)
            self.assertIn("speaker-script", teacher)
            self.assertIn("data-courseware-runtime=\"1\"", student)
            self.assertIn("data-courseware-runtime=\"1\"", teacher)
            self.assertNotIn("border-left", student.lower())

    def test_teacher_left_pages_and_student_pages_are_one_to_one(self) -> None:
        content = self.load_example("uml.example.json")
        from render_courseware import render_student, render_teacher

        report = validate_html_outputs(content, render_student(content), render_teacher(content))
        self.assertEqual(report["status"], "pass", report)
        self.assertEqual(report["metrics"]["student_pages"], len(content["slides"]))
        self.assertEqual(report["metrics"]["teacher_pages"], len(content["slides"]))

    def test_invalid_student_phrase_fails_before_output(self) -> None:
        content = self.load_example("data-structures.example.json")
        content["slides"][0]["blocks"][0]["text"] += " 本页建议6分钟"
        self.assertEqual(validate_content(content)["status"], "fail")
        with tempfile.TemporaryDirectory(prefix="courseware-invalid-") as temp:
            source = Path(temp) / "invalid.json"
            source.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(CoursewareContractError):
                load_content(source)
            self.assertEqual(list(Path(temp).glob("*.html")), [])

    def test_explicit_1_1_time_budget_cannot_hide_a_120_to_18_mismatch(self) -> None:
        content, _ = normalize_content(self.load_example("data-structures.example.json"))
        content["session_minutes"] = 120
        content["prepared_minutes"] = 120
        content["core_minutes"] = 100
        content["extension_minutes"] = 20
        self.assertEqual(validate_content(content)["status"], "fail")
        self.assertTrue(any("prepared_minutes" in error or "planned minutes" in error for error in validate_content(content)["errors"]))

    def test_speaker_script_uses_lecture_time_and_teaching_intent(self) -> None:
        content, _ = normalize_content(self.load_example("data-structures.example.json"))
        content["slides"][0]["lecture_minutes"] = 4
        content["slides"][0]["suggested_minutes"] = 4
        content["slides"][0]["speaker_script"] = "太短"
        contract = validate_content(content)
        self.assertEqual(contract["status"], "pass", contract)
        report = review_content(content)
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("speaker_script" in error for error in report["errors"]))

    def test_speaker_script_repetition_is_a_pedagogical_failure(self) -> None:
        content = self.load_example("data-structures.example.json")
        repeated = "这一段完整讲解用于说明请求处理中的关键因果关系，教师可以结合当前页面继续解释。"
        content["slides"] = content["slides"][:1]
        content["slides"][0]["speaker_script"] = " ".join([repeated] * 3)
        report = review_content(content)
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("repeats" in warning for warning in report["warnings"]), report)
        self.assertTrue(any("repeated n-gram" in error for error in report["errors"]), report)
        self.assertGreaterEqual(report["metrics"]["speaker_script_repetition"]["metrics"]["repeated_ngram_ratio"], 0.3)

    def _gold_content(self, rates: list[int], *, blocks: list[dict] | None = None, scripts: list[str] | None = None) -> dict:
        slides = []
        for index, rate in enumerate(rates):
            if scripts:
                script = scripts[index]
            else:
                source = "".join(
                    f"页{index}证据{part}说明{index + part}个因果节点，结合线索{part}判断，再转入步骤{index + part}。"
                    for part in range(60)
                )
                script = source[:rate * 2]
            slides.append({
                "id": f"gold-{index}",
                "title": f"核心概念 {index}",
                "lecture_minutes": 2,
                "activity_minutes": 0,
                "suggested_minutes": 2,
                "speaker_script": script,
                "blocks": blocks or [{"type": "paragraph", "text": "课堂概念"}],
            })
        return {"course_title": "Gold 测试", "slides": slides}

    def test_T5_gold_hard_floor_is_fail_closed(self):
        report = gold_batch_review([self._gold_content([79, 120, 130])])
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("hard speaker-script floor" in error for error in report["errors"]), report)

    def test_T6_gold_normal_target_batch_passes(self):
        report = gold_batch_review([self._gold_content([120, 132, 150, 160])])
        self.assertEqual(report["status"], "PASS", report)
        profile = report["profiles"][0]
        self.assertEqual(profile["below_normal_ratio"], 0)
        self.assertEqual(profile["median_chars_per_lecture_minute"], 141)

    def test_T7_gold_below_normal_ratio_is_a_degraded_signal_before_fail(self):
        report = gold_batch_review([self._gold_content([100, 120, 130, 140])])
        self.assertEqual(report["status"], "DEGRADED", report)
        self.assertEqual(report["profiles"][0]["below_normal_ratio"], 0.25)

    def test_T8_gold_repeated_paragraphs_fail_even_when_length_is_long(self):
        repeated = "这一段用于说明当前页面的因果关系，教师要结合页面证据引导学生回答，并说明为什么这个判断会影响下一步教学。"
        script = "\n\n".join([repeated] * 10)
        report = gold_batch_review([self._gold_content([len(script)], scripts=[script])])
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("repeats" in error for error in report["errors"]), report)

    def test_T9_gold_visual_explanation_requires_page_specific_script_coverage(self):
        blocks = [{"type": "code", "language": "python", "code": "def route():\n    return 'ok'"}]
        no_coverage = "".join(chr(0x4E00 + index) for index in range(280))
        report = gold_batch_review([self._gold_content([140], blocks=blocks, scripts=[no_coverage])])
        self.assertEqual(report["status"], "FAIL", report)
        with_coverage = "关键代码行说明了请求如何进入函数。" + "".join(chr(0x5000 + index) for index in range(280))
        content = self._gold_content([140], blocks=blocks, scripts=[with_coverage])
        content["slides"][0]["script_coverage"] = {"code": "关键代码行说明了请求如何进入函数"}
        report = gold_batch_review([content])
        self.assertEqual(report["status"], "PASS", report)

    def _boundary_content(self, mode: str, roles: list[tuple[str, int]]) -> dict:
        slides = []
        for index, (role, minutes) in enumerate(roles):
            type_by_role = {
                "teacher-led-demonstration": "demonstration-observation",
                "guided-whole-class-reasoning": "question-discussion",
                "short-student-check": "mini-quiz",
                "student-independent-practice": "individual-exercise",
            }
            slides.append({
                "id": f"boundary-{index}",
                "activity_minutes": minutes,
                "activity_plan": {"type": type_by_role[role], "activity_role": role},
                "delivery_track": "core",
            })
        return {"session_delivery_mode": mode, "slides": slides}

    def test_T10_theory_led_teacher_guided_activity_passes_boundary_review(self):
        report = theory_practice_boundary_review(self._boundary_content("theory-led", [
            ("teacher-led-demonstration", 5), ("guided-whole-class-reasoning", 5),
        ]), separate_practice_available=True)
        self.assertEqual(report["status"], "PASS", report)

    def test_T11_theory_led_independent_dominance_is_degraded_with_separate_practice(self):
        report = theory_practice_boundary_review(self._boundary_content("theory-led", [
            ("teacher-led-demonstration", 2), ("student-independent-practice", 5),
        ]), separate_practice_available=True)
        self.assertEqual(report["status"], "DEGRADED", report)
        self.assertTrue(any("independent-practice exceeds" in warning for warning in report["warnings"]), report)

    def test_T12_practice_led_independent_activity_is_not_a_courseware_boundary_failure(self):
        report = theory_practice_boundary_review(self._boundary_content("practice-led", [
            ("student-independent-practice", 8),
        ]), separate_practice_available=True)
        self.assertEqual(report["status"], "PASS", report)

    def test_context_learning_unit_and_slide_references_are_checked(self) -> None:
        content, _ = normalize_content(self.load_example("data-structures.example.json"))
        content["course_context"]["course_name"] = "另一门课"
        self.assertEqual(validate_content(content)["status"], "fail")
        content, _ = normalize_content(self.load_example("data-structures.example.json"))
        content["slides"][0]["learning_unit_ids"] = ["missing-unit"]
        report = validate_content(content)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("unknown unit" in error for error in report["errors"]))

    def test_local_image_asset_is_validated_and_inlined(self) -> None:
        content = self.load_example("data-structures.example.json")
        content["assets"] = [{"id": "tiny-diagram", "kind": "image", "path": "tiny.png"}]
        content["slides"][0]["blocks"].append({"type": "image", "asset_id": "tiny-diagram", "caption": "局部示意"})
        with tempfile.TemporaryDirectory(prefix="courseware-image-") as temp:
            root = Path(temp)
            (root / "tiny.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
            source = root / "content.json"
            source.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(validate_content(content, base_dir=root)["status"], "pass")
            output = root / "out"
            report = generate(source, output)
            self.assertEqual(report["status"], "pass", report)
            student = (output / "student.html").read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", student)
            self.assertNotIn('src="tiny.png"', student)

    def test_failed_replacement_preserves_existing_output(self) -> None:
        content_path = ROOT / "examples" / "data-structures.example.json"
        with tempfile.TemporaryDirectory(prefix="courseware-atomic-") as temp:
            output = Path(temp) / "courseware"
            generate(content_path, output)
            before = hashlib.sha256((output / "student.html").read_bytes()).hexdigest()
            invalid = self.load_example("data-structures.example.json")
            invalid["slides"][0]["speaker_script"] = "太短"
            invalid_path = Path(temp) / "invalid.json"
            invalid_path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(CoursewareContractError):
                generate(invalid_path, output, replace=True)
            after = hashlib.sha256((output / "student.html").read_bytes()).hexdigest()
            self.assertEqual(before, after)

    def test_adapter_install_is_namespaced_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="courseware-adapter-") as temp:
            project = Path(temp) / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("# Existing rules\n", encoding="utf-8")
            result = install_adapters(ROOT, project, adapters=["agents", "cursor"], copy_engine=True)
            self.assertEqual(result["status"], "pass")
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("courseware-html-generator:start", agents)
            self.assertTrue((project / ".cursor" / "rules" / "courseware-html-generator.mdc").is_file())
            self.assertTrue((project / ".courseware-html-generator" / "scripts" / "render_courseware.py").is_file())
            install_adapters(ROOT, project, adapters=["agents", "cursor"], copy_engine=True, replace=True)
            agents_again = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(agents, agents_again)

    def test_skill_installer_stages_and_replaces_without_partial_copy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="courseware-install-") as temp:
            skills_dir = Path(temp) / "skills"
            target = install_skill(ROOT, skills_dir)
            self.assertTrue((target / "manifest.yaml").is_file())
            self.assertTrue((target / "scripts" / "render_courseware.py").is_file())
            with self.assertRaises(FileExistsError):
                install_skill(ROOT, skills_dir)
            replaced = install_skill(ROOT, skills_dir, replace=True)
            self.assertEqual(target, replaced)
            self.assertFalse(any(path.name.startswith("courseware-html-generator_backup_") for path in skills_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
