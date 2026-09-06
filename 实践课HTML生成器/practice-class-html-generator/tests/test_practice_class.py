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

    def test_all_fixtures_consume_real_courseware_slide_ids(self) -> None:
        for name in ("data-structures.practice.json", "uml.practice.json", "database.practice.json"):
            content = self.fixture(name)
            courseware = load_courseware(self.courseware_for(name))
            report = validate_content(content, courseware)
            self.assertEqual(report["status"], "pass", report)
            slide_ids = {slide["id"] for slide in courseware["slides"]}
            refs = {ref for item in content["knowledge_links"] for ref in item["source_slide_ids"]}
            self.assertTrue(refs)
            self.assertTrue(refs <= slide_ids)
            self.assertTrue(all(task["knowledge_link_ids"] for task in content["tasks"] if task["level"] == "core"))

    def test_fixtures_have_distinct_learning_modalities(self) -> None:
        data = self.fixture("data-structures.practice.json")
        uml = self.fixture("uml.practice.json")
        database = self.fixture("database.practice.json")
        self.assertIn("coding", {task["modality"] for task in data["tasks"]})
        self.assertIn("modeling", {task["modality"] for task in uml["tasks"]})
        self.assertIn("sql", {task["modality"] for task in database["tasks"]})
        data_core = next(task for task in data["tasks"] if task["id"] == "binary-search-core")
        self.assertEqual(data_core["todo_count"], 5)
        self.assertEqual(sum(1 for item in data["starter_assets"][0]["content"].splitlines() if "TODO " in item), 5)

    def test_uml_fixture_has_no_programming_template_pollution(self) -> None:
        raw = json.dumps(self.fixture("uml.practice.json"), ensure_ascii=False)
        self.assertIsNone(re.search(r"C语言|C 语言|C/C\+\+|代码模板|\bTODO\b|\bdef\s", raw, re.IGNORECASE))

    def test_invalid_source_slide_fails(self) -> None:
        content = self.fixture("uml.practice.json")
        content["knowledge_links"][0]["source_slide_ids"] = ["uml-missing"]
        report = validate_content(content, load_courseware(self.courseware_for("uml.practice.json")))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("missing slide.id" in error for error in report["errors"]))

    def test_generation_emits_required_files_and_output_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="practice-class-package-") as temp:
            output = Path(temp) / "data-structures"
            report = generate(ROOT / "examples" / "data-structures.practice.json", output, self.courseware_for("data-structures.practice.json"))
            self.assertEqual(report["status"], "pass", report)
            self.assertEqual(set(path.name for path in output.iterdir()), {"student-task.html", "learning-center.html", "study-guide.html", "foundation-kit.html", "teacher-guide.html", "practice-content.json", "qa-report.json", "starter"})
            qa = validate(ROOT / "examples" / "data-structures.practice.json", output, self.courseware_for("data-structures.practice.json"))
            self.assertEqual(qa["status"], "pass", qa)
            self.assertIn('data-task-id="binary-search-core"', (output / "student-task.html").read_text(encoding="utf-8"))
            self.assertIn("search-02", (output / "student-task.html").read_text(encoding="utf-8"))
            self.assertIn("data-choice", (output / "learning-center.html").read_text(encoding="utf-8"))

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
