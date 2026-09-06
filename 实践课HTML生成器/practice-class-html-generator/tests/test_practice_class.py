from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REPO = ROOT.parents[1]
sys.path.insert(0, str(SCRIPTS))

from install import install as install_skill  # noqa: E402
from install_adapters import install as install_adapters  # noqa: E402
from practice_contract import load_courseware, load_json, validate_content  # noqa: E402
from render_practice import generate  # noqa: E402
from validate_practice import validate  # noqa: E402


class PracticeClassPackageTests(unittest.TestCase):
    def fixture(self, name: str) -> dict:
        return load_json(ROOT / "examples" / name)

    def courseware_for(self, name: str) -> Path:
        if name == "database.practice.json":
            return ROOT / "examples" / "database-courseware.example.json"
        if name == "uml.practice.json":
            return REPO / "HTML课件生成器" / "courseware-html-generator" / "examples" / "uml.example.json"
        return REPO / "HTML课件生成器" / "courseware-html-generator" / "examples" / "data-structures.example.json"

    def test_all_fixtures_consume_real_courseware_slide_ids_and_context(self) -> None:
        for name in ("data-structures.practice.json", "uml.practice.json", "database.practice.json"):
            content = self.fixture(name)
            courseware = load_courseware(self.courseware_for(name))
            report = validate_content(content, courseware)
            self.assertEqual(report["status"], "pass", report)
            slide_ids = {slide["id"] for slide in courseware["slides"]}
            refs = {ref for item in content["knowledge_links"] for ref in item["source_slide_ids"]}
            self.assertTrue(refs <= slide_ids)
            self.assertTrue(report["metrics"]["context_preserved"])
            self.assertEqual(content["course_context"], courseware["course_context"])
            self.assertTrue(all(task["knowledge_link_ids"] for task in content["tasks"] if task["level"] == "core"))
            self.assertTrue(all(task["source_slide_ids"] for task in content["tasks"]))
            self.assertTrue(all(set(task["source_slide_ids"]) <= slide_ids for task in content["tasks"]))
            self.assertGreaterEqual(report["metrics"]["tasks"], 7)
            self.assertGreaterEqual(report["metrics"]["core_tasks"], 5)
            self.assertGreaterEqual(report["metrics"]["interaction_zones"], 5)
            self.assertGreaterEqual(report["metrics"]["interaction_type_count"], 4)
            self.assertGreaterEqual(report["metrics"]["guide_sections"], 6)
            self.assertGreaterEqual(report["metrics"]["foundation_microtopics"], 5)
            self.assertEqual(report["metrics"]["core_help_coverage"], report["metrics"]["core_tasks"])

    def test_fixtures_have_distinct_learning_modalities_and_rich_interactions(self) -> None:
        data = self.fixture("data-structures.practice.json")
        uml = self.fixture("uml.practice.json")
        database = self.fixture("database.practice.json")
        self.assertIn("coding", {task["modality"] for task in data["tasks"]})
        self.assertIn("modeling", {task["modality"] for task in uml["tasks"]})
        self.assertIn("sql", {task["modality"] for task in database["tasks"]})
        self.assertEqual(data["course_context"]["language"], "C")
        self.assertEqual(data["course_context"]["tools"], ["Dev-C++", "Code::Blocks"])
        self.assertEqual(data["learning_center"][1]["interaction"]["type"], "state-simulator")
        self.assertIn("classify", {center["interaction"]["type"] for center in uml["learning_center"]})
        self.assertIn("stepper", {center["interaction"]["type"] for center in database["learning_center"]})
        self.assertNotEqual(data["course_title"], uml["course_title"])
        self.assertNotEqual(uml["course_title"], database["course_title"])

    def test_uml_fixture_has_editable_drawio_and_no_programming_pollution(self) -> None:
        content = self.fixture("uml.practice.json")
        raw = json.dumps(content, ensure_ascii=False)
        self.assertIsNone(re.search(r"C语言|C 语言|C/C\+\+|代码模板|#include|\bTODO\s+\d+\b|binary_search\.py", raw, re.IGNORECASE))
        drawio = next(asset for asset in content["starter_assets"] if asset["path"].endswith(".drawio"))
        self.assertIn("<mxfile", drawio["content"])
        self.assertIn("Student", drawio["content"])
        self.assertIn("Reservation", drawio["content"])
        self.assertIn("shape=umlClass", drawio["content"])
        self.assertNotIn("umlActor", drawio["content"])

    def test_non_c_fixtures_have_no_c_or_dev_cpp_pollution(self) -> None:
        for name in ("uml.practice.json", "database.practice.json"):
            raw = json.dumps(self.fixture(name), ensure_ascii=False)
            self.assertIsNone(re.search(r"C语言|C 语言|C/C\+\+|Dev-C\+\+|Code::Blocks|#include\s*<|binary_search", raw, re.IGNORECASE), name)

    def test_sql_starter_is_executable_shaped_and_keeps_mysql_context(self) -> None:
        content = self.fixture("database.practice.json")
        sql = next(asset["content"] for asset in content["starter_assets"] if asset["path"].endswith(".sql"))
        self.assertNotRegex(sql, r"=\s*NULL")
        self.assertIn("'pending'", sql)
        reference = next(item for item in content["teacher_reference"]["task_references"] if item["task_id"] == "db-sql-core")
        self.assertIn("'completed'", reference["reference_answer"])
        self.assertEqual(content["course_context"]["database_dialect"], "MySQL")

    def test_invalid_source_slide_and_teacher_reference_fail(self) -> None:
        content = self.fixture("uml.practice.json")
        content["knowledge_links"][0]["source_slide_ids"] = ["uml-missing"]
        report = validate_content(content, load_courseware(self.courseware_for("uml.practice.json")))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("missing slide.id" in error for error in report["errors"]))
        content = self.fixture("database.practice.json")
        content["teacher_reference"]["task_references"] = content["teacher_reference"]["task_references"][:-1]
        report = validate_content(content, load_courseware(self.courseware_for("database.practice.json")))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("missing tasks" in error for error in report["errors"]))
        content = self.fixture("data-structures.practice.json")
        content["tasks"][0]["source_slide_ids"] = ["search-missing"]
        report = validate_content(content, load_courseware(self.courseware_for("data-structures.practice.json")))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("tasks[0].source_slide_ids" in error for error in report["errors"]))

    def test_independent_mode_accepts_explicit_local_slide_refs(self) -> None:
        content = self.fixture("uml.practice.json")
        content["source_courseware"]["mode"] = "independent"
        report = validate_content(content)
        self.assertEqual(report["status"], "pass", report)

    def test_generation_emits_physically_split_outputs_and_output_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="practice-class-package-") as temp:
            output = Path(temp) / "data-structures"
            practice = ROOT / "examples" / "data-structures.practice.json"
            report = generate(practice, output, self.courseware_for("data-structures.practice.json"))
            self.assertEqual(report["status"], "pass", report)
            self.assertEqual({path.name for path in output.iterdir()}, {"student", "teacher", "practice-content.json", "qa-report.json"})
            self.assertEqual({path.name for path in (output / "student").iterdir() if path.is_file()}, {"student-task.html", "learning-center.html", "study-guide.html", "foundation-kit.html"})
            self.assertEqual({path.name for path in (output / "teacher").iterdir()}, {"teacher-guide.html", "teacher-reference.html"})
            qa = validate(practice, output, self.courseware_for("data-structures.practice.json"))
            self.assertEqual(qa["status"], "pass", qa)
            student = (output / "student" / "student-task.html").read_text(encoding="utf-8")
            self.assertIn('data-task-id="ds-fill-core"', student)
            self.assertIn("search-02", student)
            self.assertIn("核心必做", student)
            self.assertNotIn("teacher-guide", student)
            self.assertNotIn("教师参考", student)
            self.assertIn("教师参考", (output / "teacher" / "teacher-reference.html").read_text(encoding="utf-8"))
            self.assertTrue((output / "student" / "starter" / "binary-search.c").is_file())
            self.assertIn("TODO 1", (output / "student" / "starter" / "binary-search.c").read_text(encoding="utf-8"))

    def test_installer_and_namespaced_adapter_are_minimal_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="practice-class-install-") as temp:
            root = Path(temp)
            skills_dir = root / "skills"
            target = install_skill(ROOT, skills_dir)
            self.assertTrue((target / "manifest.yaml").is_file())
            with self.assertRaises(FileExistsError):
                install_skill(ROOT, skills_dir)
            install_skill(ROOT, skills_dir, replace=True)
            project = root / "project"
            project.mkdir()
            (project / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            result = install_adapters(ROOT, project, adapters=["agents", "cursor"], copy_engine=True)
            self.assertEqual(result["status"], "pass")
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("practice-class-html-generator:start", agents)
            self.assertTrue((project / ".cursor" / "rules" / "practice-class-html-generator.mdc").is_file())
            install_adapters(ROOT, project, adapters=["agents", "cursor"], copy_engine=True, replace=True)
            self.assertEqual(agents, (project / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
