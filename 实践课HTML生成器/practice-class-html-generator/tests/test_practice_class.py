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
            report = validate_content(content, load_courseware(self.courseware_for(name)))
            self.assertEqual(report["status"], "pass", report)
            slide_ids = {slide["id"] for slide in load_courseware(self.courseware_for(name))["slides"]}
            refs = {ref for item in content["knowledge_links"] for ref in item["source_slide_ids"]}
            self.assertTrue(refs <= slide_ids)
            self.assertTrue(report["metrics"]["context_preserved"])
            self.assertEqual(content["course_context"], load_courseware(self.courseware_for(name))["course_context"])
            self.assertEqual(report["metrics"]["interaction_estimated_minutes"], sum(item["interaction"]["estimated_minutes"] for item in content["learning_center"]))
            self.assertTrue(all(task["source_slide_ids"] for task in content["tasks"]))
            self.assertEqual(report["metrics"]["core_help_coverage"], report["metrics"]["core_tasks"])

    def test_quantity_is_a_quality_recommendation_not_a_fixed_contract(self) -> None:
        content = self.fixture("uml.practice.json")
        content["foundation_kit"] = []
        report = validate_content(content, load_courseware(self.courseware_for("uml.practice.json")))
        self.assertEqual(report["status"], "pass", report)
        self.assertTrue(report["warnings"])
        self.assertTrue(report["metrics"]["quality_recommendations"])

    def test_fixtures_have_distinct_learning_modalities_and_renderer_families(self) -> None:
        data = self.fixture("data-structures.practice.json")
        uml = self.fixture("uml.practice.json")
        database = self.fixture("database.practice.json")
        self.assertIn("coding", {task["modality"] for task in data["tasks"]})
        self.assertIn("modeling", {task["modality"] for task in uml["tasks"]})
        self.assertIn("sql", {task["modality"] for task in database["tasks"]})
        self.assertEqual(data["course_context"]["language"], "C")
        self.assertIn("state-simulator-family", validate_content(data, load_courseware(self.courseware_for("data-structures.practice.json")))["metrics"]["renderer_families"])
        self.assertIn("classify-family", validate_content(uml, load_courseware(self.courseware_for("uml.practice.json")))["metrics"]["renderer_families"])
        self.assertIn("reorder-family", validate_content(database, load_courseware(self.courseware_for("database.practice.json")))["metrics"]["renderer_families"])
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

    def test_state_reorder_and_classification_contracts_are_teaching_safe(self) -> None:
        data = self.fixture("data-structures.practice.json")
        interval = next(item for item in data["learning_center"] if item["id"] == "ds-interval-lab")["interaction"]
        self.assertEqual(interval["state_fields"][0]["id"], "left")
        self.assertEqual(interval["rounds"][0]["given"], {"left": 0, "right": 7})
        self.assertEqual(interval["rounds"][0]["expected"], {"mid": 3})
        self.assertEqual(interval["rounds"][0]["next_expected"], {"left": 4, "right": 7})
        self.assertEqual(interval["rounds"][-1]["status"], "found")
        self.assertNotIn("next_expected", interval["rounds"][-1])
        for name in ("uml.practice.json", "database.practice.json"):
            content = self.fixture(name)
            for center in content["learning_center"]:
                if center["interaction"]["type"] == "reorder":
                    interaction = center["interaction"]
                    self.assertNotEqual([item["id"] for item in interaction["items"]], interaction["correct_order"])
                    self.assertEqual(set(item["id"] for item in interaction["items"]), set(interaction["correct_order"]))

    def test_renderer_source_is_course_neutral(self) -> None:
        source = (SCRIPTS / "render_practice.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\bBoundary\b|\bControl\b|\bActor\b|消息接收者|SQL JOIN|\bpivot\b", source, re.IGNORECASE))
        self.assertNotRegex(source, r"data-state-[abc]|next_left|next_right|state-mid")

    def test_generation_emits_six_module_pages_and_output_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="practice-class-package-") as temp:
            output = Path(temp) / "data-structures"
            practice = ROOT / "examples" / "data-structures.practice.json"
            report = generate(practice, output, self.courseware_for("data-structures.practice.json"))
            self.assertEqual(report["status"], "pass", report)
            self.assertEqual({path.name for path in output.iterdir()}, {"student", "teacher", "practice-content.json", "qa-report.json"})
            self.assertEqual({path.name for path in (output / "student").iterdir() if path.is_file()}, {"student-task.html", "learning-center.html", "study-guide.html", "foundation-kit.html"})
            self.assertEqual({path.name for path in (output / "teacher").iterdir() if path.is_file()}, {"teacher-guide.html", "teacher-reference.html"})
            self.assertEqual(len(list(output.rglob("*.html"))), 6)
            self.assertFalse((output / "student" / "tasks").exists())
            self.assertFalse((output / "teacher" / "references").exists())
            qa = validate(practice, output, self.courseware_for("data-structures.practice.json"))
            self.assertEqual(qa["status"], "pass", qa)
            task_page = (output / "student" / "student-task.html").read_text(encoding="utf-8")
            visible_task = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", task_page, flags=re.S)
            self.assertNotIn("ds-fill-core", visible_task)
            self.assertNotIn("search-02", visible_task)
            self.assertIn("核心必做", visible_task)
            self.assertIn('data-task-id="ds-fill-core"', task_page)
            self.assertIn('data-source-slide-ids="search-02 search-05"', task_page)
            self.assertIn("learning-center.html#lab-", task_page)
            self.assertIn("study-guide.html#guide-", task_page)
            self.assertIn("foundation-kit.html#kit-", task_page)
            learning = (output / "student" / "learning-center.html").read_text(encoding="utf-8")
            self.assertIn('data-renderer-family="state-simulator-family"', learning)
            self.assertIn('data-estimated-minutes="8"', learning)
            self.assertIn("data-state-fields", learning)
            teacher = (output / "teacher" / "teacher-reference.html").read_text(encoding="utf-8")
            self.assertIn("参考答案", teacher)
            self.assertIn("reference-answer", teacher)
            self.assertNotIn("search-01", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", teacher, flags=re.S))
            self.assertTrue((output / "student" / "starter" / "binary-search.c").is_file())

    def test_starters_and_teacher_references_are_directly_usable(self) -> None:
        for name in ("data-structures.practice.json", "uml.practice.json", "database.practice.json"):
            with self.subTest(fixture=name), tempfile.TemporaryDirectory(prefix="practice-class-r6-") as temp:
                output = Path(temp) / "fixture"
                practice = ROOT / "examples" / name
                report = generate(practice, output, self.courseware_for(name))
                self.assertEqual(report["status"], "pass", report)
                student = (output / "student" / "student-task.html").read_text(encoding="utf-8")
                teacher = (output / "teacher" / "teacher-reference.html").read_text(encoding="utf-8")
                visible_student = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", student, flags=re.S)
                visible_teacher = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", teacher, flags=re.S)
                self.assertNotRegex(visible_teacher, r"source_slide_ids|task_id|slide_id|renderer_family|interaction_type")
                for asset in self.fixture(name)["starter_assets"]:
                    path = asset["path"].replace("\\", "/")
                    self.assertIn(f'data-starter-path="{path}"', student)
                    self.assertIn(f'href="starter/{path}"', student)
                    if path.casefold().endswith(".drawio"):
                        self.assertNotIn(f'data-starter-preview-path="{path}"', student)
                        self.assertNotIn("mxGraphModel", visible_student)
                    else:
                        self.assertIn(f'data-starter-preview-path="{path}"', student)
                if name == "data-structures.practice.json":
                    self.assertIn("int binary_search", teacher)
                    self.assertIn("TODO 1", teacher)
                    self.assertIn("本次环境：C · Dev-C++ / Code::Blocks", visible_student)
                elif name == "uml.practice.json":
                    self.assertGreaterEqual(teacher.count('data-reference-visual='), 2)
                    self.assertIn("本次工具：draw.io / StarUML", visible_student)
                else:
                    self.assertIn("SELECT c.customer_name", teacher)
                    self.assertIn("客户 A | 2", teacher)
                    self.assertIn("本次环境：MySQL 8.0 · MySQL Workbench · draw.io", visible_student)

    def test_database_setup_and_query_semantics_are_non_trivial(self) -> None:
        content = self.fixture("database.practice.json")
        setup = next(asset["content"] for asset in content["starter_assets"] if asset["path"].endswith("setup.sql"))
        self.assertIn("'pending'", setup)
        self.assertIn("2025-02-28", setup)
        query = next(asset["content"] for asset in content["starter_assets"] if asset["path"].endswith("query.sql"))
        self.assertEqual(len(re.findall(r"TODO [1-4]", query)), 4)
        self.assertIn("COUNT(DISTINCT o.customer_id)", query)
        reference = next(item for item in content["teacher_reference"]["task_references"] if item["task_id"] == "db-sql-core")
        self.assertIn("A=2", reference["reference_result"])
        self.assertIn("B=1", reference["reference_result"])

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

    def test_independent_mode_accepts_explicit_local_slide_refs(self) -> None:
        content = self.fixture("uml.practice.json")
        content["source_courseware"]["mode"] = "independent"
        self.assertEqual(validate_content(content)["status"], "pass")

    def test_installer_and_namespaced_adapter_are_minimal_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="practice-class-install-") as temp:
            root = Path(temp); skills_dir = root / "skills"; target = install_skill(ROOT, skills_dir)
            self.assertTrue((target / "manifest.yaml").is_file())
            with self.assertRaises(FileExistsError): install_skill(ROOT, skills_dir)
            install_skill(ROOT, skills_dir, replace=True)
            project = root / "project"; project.mkdir(); (project / "AGENTS.md").write_text("# Existing\n", encoding="utf-8")
            result = install_adapters(ROOT, project, adapters=["agents", "cursor"], copy_engine=True)
            self.assertEqual(result["status"], "pass")
            agents = (project / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("practice-class-html-generator:start", agents)
            self.assertTrue((project / ".cursor" / "rules" / "practice-class-html-generator.mdc").is_file())
            install_adapters(ROOT, project, adapters=["agents", "cursor"], copy_engine=True, replace=True)
            self.assertEqual(agents, (project / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
