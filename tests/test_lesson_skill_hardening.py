from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "教案生成器" / "lesson-plan-docx-generator"
SCRIPTS = LESSON / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_template_patch  # noqa: E402
import content_quality  # noqa: E402
import install as lesson_install  # noqa: E402
import install_adapters  # noqa: E402
import render_qa  # noqa: E402
from record_visual_inspection import CHECK_NAMES, write_visual_inspection_evidence  # noqa: E402
from validate_visual_inspection import validate_visual_inspection  # noqa: E402


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LessonSkillHardeningTests(unittest.TestCase):
    def test_intra_lesson_calibration_covers_domain_positives_and_negatives(self) -> None:
        cases = content_quality.intra_lesson_coherence_calibration()
        self.assertGreaterEqual(len(cases), 8)
        self.assertTrue(all(item["expected"] == item["actual"] for item in cases), cases)

    def test_installer_dry_run_and_replace_are_transactional(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-installer-hardening-") as temp_name:
            root = Path(temp_name) / "skills"
            lesson_install.install(LESSON, root, dry_run=True)
            self.assertFalse(root.exists())
            lesson_install.install(LESSON, root)
            target = root / lesson_install.SKILL_NAME
            (target / "user-marker.txt").write_text("old", encoding="utf-8")
            lesson_install.install(LESSON, root, replace=True)
            backups = list(root.glob("lesson-plan-docx-generator_backup_*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "user-marker.txt").read_text(encoding="utf-8"), "old")

    def test_installer_commit_failure_restores_previous_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-installer-rollback-") as temp_name:
            root = Path(temp_name) / "skills"
            lesson_install.install(LESSON, root)
            target = root / lesson_install.SKILL_NAME
            marker = target / "rollback-marker.txt"
            marker.write_text("keep", encoding="utf-8")
            real_replace = lesson_install.os.replace
            calls = 0

            def fail_commit(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected commit failure")
                return real_replace(source, destination)

            with patch.object(lesson_install.os, "replace", side_effect=fail_commit):
                with self.assertRaisesRegex(RuntimeError, "previous installation restored"):
                    lesson_install.install(LESSON, root, replace=True)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_adapter_namespace_markers_and_aider_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-adapter-hardening-") as temp_name:
            target = Path(temp_name) / "project"
            install_adapters.install(LESSON, target, adapters=["all"])
            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(agents.count(install_adapters.MARKER_START), 1)
            self.assertIn(".lesson-plan-docx-generator/SKILL.md", agents)
            self.assertNotIn(".lesson-plan-docx-generator/scripts/generate_lesson_plans.py", agents)
            self.assertIn("--copy-engine", agents)
            self.assertTrue((target / ".lesson-plan-docx-generator" / "SKILL.md").is_file())
            self.assertTrue((target / ".lesson-plan-docx-generator" / "CONVENTIONS.md").is_file())
            for minimal_name in ("SKILL.md", "通用提示词.md", "AGENTS.md", "CONVENTIONS.md"):
                minimal_text = (target / ".lesson-plan-docx-generator" / minimal_name).read_text(encoding="utf-8")
                self.assertNotIn("scripts/generate_lesson_plans.py", minimal_text)
                self.assertNotIn("docs/content-contract-v2.md", minimal_text)
                self.assertNotIn("examples/tasks.example.json", minimal_text)
                self.assertNotRegex(minimal_text, r"(?:scripts|docs|examples|schemas|assets)/")
            full_target = Path(temp_name) / "full-project"
            install_adapters.install(LESSON, full_target, adapters=["all"], copy_engine=True)
            full_agents = (full_target / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn(".lesson-plan-docx-generator/scripts/generate_lesson_plans.py", full_agents)
            stale = full_target / ".lesson-plan-docx-generator" / "obsolete-helper.py"
            stale.write_text("stale", encoding="utf-8")
            install_adapters.install(LESSON, full_target, adapters=["all"], copy_engine=True, replace=True)
            self.assertFalse(stale.exists())
            self.assertTrue(any(path.name.startswith(".lesson-plan-docx-generator.backup_") for path in full_target.iterdir()))
            install_adapters.install(LESSON, target, adapters=["agents"])
            self.assertEqual((target / "AGENTS.md").read_text(encoding="utf-8").count(install_adapters.MARKER_START), 1)
            aider = target / ".aider.conf.yml"
            before = aider.read_bytes()
            aider.write_text("read: {unsafe: true}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "complex"):
                install_adapters.install(LESSON, target, adapters=["aider"])
            self.assertEqual(aider.read_text(encoding="utf-8"), "read: {unsafe: true}\n")
            self.assertNotEqual(before, aider.read_bytes())

    def test_gradebook_shared_marker_and_aider_coexistence(self) -> None:
        gradebook = load_module(
            ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "scripts" / "install_adapters.py",
            "gradebook_install_adapters_hardening",
        )
        with tempfile.TemporaryDirectory(prefix="lesson-gradebook-coexist-") as temp_name:
            target = Path(temp_name) / "project"
            install_adapters.install(LESSON, target, adapters=["agents", "aider"])
            gradebook_root = ROOT / "平时成绩记分册生成器" / "course-gradebook-generator"
            gradebook.copy_file(gradebook_root, target, "AGENTS.md", False, False)
            gradebook.copy_file(gradebook_root, target, ".aider.conf.yml", False, False)
            agents = (target / "AGENTS.md").read_text(encoding="utf-8")
            aider = (target / ".aider.conf.yml").read_text(encoding="utf-8")
            self.assertIn("lesson-plan-docx-generator:start", agents)
            self.assertIn("course-gradebook-generator:start", agents)
            self.assertIn(".lesson-plan-docx-generator/SKILL.md", aider)
            self.assertIn(".course-gradebook-generator/SKILL.md", aider)

    def test_visual_evidence_validator_rejects_stale_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-visual-hardening-") as temp_name:
            output = Path(temp_name) / "output"
            output.mkdir()
            lesson = output / "教案01_示例.docx"
            lesson.write_bytes(b"docx-bytes")
            qa_report = output / "qa-report.json"
            qa_report.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "output_dir": str(output.resolve()),
                        "validation": {"output": True},
                        "render": {"page_counts": {lesson.name: 2}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            checks = {name: "passed" for name in CHECK_NAMES}
            evidence_path = output / "visual-inspection.json"
            write_visual_inspection_evidence(
                output_dir=output,
                qa_report=qa_report,
                destination=evidence_path,
                status="passed",
                inspected_pages={lesson.name: [1, 2]},
                checks=checks,
                notes="Agent inspected representative pages.",
            )
            validate_visual_inspection(output, qa_report, evidence_path)
            valid_evidence = evidence_path.read_bytes()
            empty_evidence = json.loads(valid_evidence.decode("utf-8"))
            empty_evidence["inspected_files"] = []
            empty_evidence["inspected_pages"] = {}
            evidence_path.write_text(json.dumps(empty_evidence, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "at least one inspected"):
                validate_visual_inspection(output, qa_report, evidence_path)
            evidence_path.write_bytes(valid_evidence)
            lesson.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "stale"):
                validate_visual_inspection(output, qa_report, evidence_path)

    def test_xml_template_patch_escapes_visible_text_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-template-patch-hardening-") as temp_name:
            folder = Path(temp_name)
            source = folder / "source.docx"
            target = folder / "patched.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "template.docx", source)
            build_template_patch.build_patch(source, target, [("职业价值观", "A&B <测试>")])
            self.assertTrue(target.is_file())
            from docx import Document

            document = Document(target)
            visible = [paragraph.text for paragraph in document.paragraphs]
            def cell_text(cell):
                return [cell.text, *[value for table in cell.tables for row in table.rows for nested in row.cells for value in cell_text(nested)]]

            visible.extend(value for table in document.tables for row in table.rows for cell in row.cells for value in cell_text(cell))
            self.assertIn("A&B <测试>", "\n".join(visible))

    def test_xml_template_patch_does_not_cross_paragraph_boundaries(self) -> None:
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>跨</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>段</w:t></w:r></w:p></w:body></w:document>'
        ).encode("utf-8")
        with self.assertRaisesRegex(ValueError, "found 0"):
            build_template_patch._replace_document_text(xml, [("跨段", "不应替换")])

    def test_render_timeout_is_reported_as_failed_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-render-timeout-") as temp_name:
            output = Path(temp_name)
            (output / "教案01_示例.docx").write_bytes(b"docx")
            timeout = subprocess.TimeoutExpired(["soffice"], 1)
            with patch.object(render_qa, "find_renderer", return_value="soffice"):
                with patch.object(render_qa.subprocess, "run", side_effect=timeout):
                    report = render_qa.render_docx_directory(output, timeout=1)
            self.assertEqual(report["status"], "failed")
            self.assertIn("timed out after 1s", report["errors"][0])


if __name__ == "__main__":
    unittest.main()
