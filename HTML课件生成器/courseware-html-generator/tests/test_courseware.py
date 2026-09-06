from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from content_contract import CoursewareContractError, load_content, validate_content  # noqa: E402
from install_adapters import install as install_adapters  # noqa: E402
from install import install as install_skill  # noqa: E402
from render_courseware import generate  # noqa: E402
from validate_courseware import validate_files, validate_html_outputs  # noqa: E402


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
        self.assertEqual(report["metrics"]["student_pages"], 2)
        self.assertEqual(report["metrics"]["teacher_pages"], 2)

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
