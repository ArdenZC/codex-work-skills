from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from copy import copy
from decimal import Decimal
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import _Cell
from openpyxl import Workbook, load_workbook


ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "教案生成器" / "lesson-plan-docx-generator"
GRADE = ROOT / "平时成绩记分册生成器" / "course-gradebook-generator"
PYTHON = Path(sys.executable)


def soffice_path() -> str | None:
    candidates = [
        shutil.which("soffice"),
        shutil.which("soffice.com"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
    ]
    return next((item for item in candidates if item and Path(item).exists()), None)


def run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(PYTHON), str(script), *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


class LessonTemplatePackageTests(unittest.TestCase):
    def test_canonical_template_and_compatibility_entry(self) -> None:
        result = run_script(LESSON / "scripts" / "validate_template.py", "--json")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["checks"]["main_table"], {"rows": 30, "columns": 10})
        self.assertEqual(report["checks"]["evaluation_table"], {"rows": 14, "columns": 4})

    def test_invalid_input_is_rejected(self) -> None:
        sys.path.insert(0, str(LESSON / "scripts"))
        from package_common import validate_input

        bad = {"course_name": "软件测试", "lessons": [{"unit": "项目一"}]}
        with self.assertRaises(ValueError):
            validate_input(bad)
        bad["weights"] = {"regular": 0.5, "theory": 0.5, "skill": 0.5}
        with self.assertRaises(ValueError):
            validate_input(bad)
        with self.assertRaises(ValueError):
            validate_input({"course_name": "软件测试", "lessons": [{"unit": "", "task": "", "hours": "2"}]})
        with self.assertRaises(ValueError):
            validate_input({"course_name": "课" * 33, "lessons": [{"unit": "项目一", "task": "完成任务", "hours": "2"}]})

    def test_non_projectized_unit_rejects_before_docx_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-unit-guard-") as temp_name:
            folder = Path(temp_name)
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            payload["lessons"][0]["unit"] = "第一章 基础测试"
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("projectized teaching", result.stderr)
            self.assertFalse(output.exists())

    def test_score_precision_accepts_half_points_and_defaults(self) -> None:
        sys.modules.pop("package_common", None)
        sys.path.insert(0, str(LESSON / "scripts"))
        from package_common import validate_input

        base = {"course_name": "软件测试实训", "lessons": [{"unit": "项目一", "task": "完成任务", "hours": "2"}]}
        for score in (89, 89.0, 89.5):
            payload = json.loads(json.dumps(base, ensure_ascii=False))
            payload["lessons"][0]["score"] = score
            validate_input(payload)
        validate_input(base)

    def test_nonpositive_hours_rejects_numeric_values_and_strings(self) -> None:
        sys.modules.pop("package_common", None)
        sys.path.insert(0, str(LESSON / "scripts"))
        from package_common import validate_input

        base = {"course_name": "软件测试实训", "lessons": [{"unit": "项目一", "task": "完成任务", "hours": "2"}]}
        for invalid_hours in (-2, "-2", 0, "0"):
            payload = json.loads(json.dumps(base, ensure_ascii=False))
            payload["lessons"][0]["hours"] = invalid_hours
            with self.subTest(invalid_hours=invalid_hours), self.assertRaisesRegex(ValueError, "positive number"):
                validate_input(payload)

    def test_nonpositive_hours_reject_before_docx_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-hours-") as temp_name:
            folder = Path(temp_name)
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            payload["lessons"][0]["hours"] = "-2"
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lessons[0].hours must be a positive number; received -2.", result.stderr)
            self.assertFalse(output.exists())

    def test_long_lesson_hours_reject_before_docx_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-hours-length-") as temp_name:
            folder = Path(temp_name)
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            payload["lessons"][0]["hours"] = "1234567890123"
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Input schema validation failed", result.stderr)
            self.assertFalse(output.exists())

    def test_numeric_lesson_hours_length_rejects_before_docx_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-numeric-hours-length-") as temp_name:
            folder = Path(temp_name)
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            payload["lessons"][0]["hours"] = 1234567890123
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hours exceeds manifest max_chars=12", result.stderr)
            self.assertFalse(output.exists())

    def test_invalid_total_hours_reject_before_docx_generation(self) -> None:
        for invalid_total in ("abc", "-2", 0, "0"):
            with self.subTest(invalid_total=invalid_total), tempfile.TemporaryDirectory(prefix="lesson-package-total-hours-") as temp_name:
                folder = Path(temp_name)
                payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
                payload["total_hours"] = invalid_total
                source = folder / "tasks.json"
                output = folder / "output"
                source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                result = run_script(
                    LESSON / "scripts" / "generate_lesson_plans.py",
                    "--tasks-json",
                    str(source),
                    "--output-dir",
                    str(output),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("total_hours must be a positive number", result.stderr)
                self.assertFalse(output.exists())

    def test_teaching_content_capacity_rejects_before_docx_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-content-capacity-") as temp_name:
            folder = Path(temp_name)
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            payload["lessons"][0]["flows"] = [f"流程{i}" for i in range(6)]
            payload["lessons"][0]["knowledge"] = [f"知识点{i}" for i in range(3)]
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("flows and knowledge combined must contain at most 8 items", result.stderr)
            self.assertFalse(output.exists())

    def test_composed_lesson_fields_reject_before_docx_generation(self) -> None:
        cases = {
            "teaching_content": {
                "flows": ["流" * 200 for _ in range(8)],
                "knowledge": [],
                "message": "teaching_content exceeds manifest max_chars=1200",
            },
            "knowledge_goal": {
                "flows": [],
                "knowledge": ["知识点" for _ in range(6)],
                "message": "knowledge_goal exceeds manifest max_paragraphs=5",
            },
            "resources": {
                "tools": "\n".join("工具" for _ in range(7)),
                "message": "resources exceeds manifest max_paragraphs=8",
            },
            "implementation": {
                "flows": ["流" * 200 for _ in range(3)],
                "knowledge": [],
                "message": "implementation row 3 cell 1 exceeds manifest max_chars=600",
            },
            "title": {
                "course_name": "课" * 32,
                "task": "任务" * 40,
                "message": "title exceeds manifest max_chars=120",
            },
        }
        for name, case in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="lesson-package-composed-") as temp_name:
                folder = Path(temp_name)
                payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
                payload["lessons"] = [payload["lessons"][0]]
                payload["total_hours"] = 2
                lesson = payload["lessons"][0]
                lesson.update({key: value for key, value in case.items() if key != "message"})
                source = folder / "tasks.json"
                output = folder / "output"
                source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                result = run_script(
                    LESSON / "scripts" / "generate_lesson_plans.py",
                    "--tasks-json",
                    str(source),
                    "--output-dir",
                    str(output),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(case["message"], result.stderr)
                self.assertFalse(output.exists())

    def test_score_precision_rejects_before_docx_generation(self) -> None:
        for invalid_score in (89.2, 89.25):
            with self.subTest(invalid_score=invalid_score), tempfile.TemporaryDirectory(prefix="lesson-package-score-") as temp_name:
                folder = Path(temp_name)
                payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
                payload["lessons"][0]["score"] = invalid_score
                source = folder / "tasks.json"
                output = folder / "output"
                source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                result = run_script(
                    LESSON / "scripts" / "generate_lesson_plans.py",
                    "--tasks-json",
                    str(source),
                    "--output-dir",
                    str(output),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"lessons[0].score must use 0.5-point increments; received {invalid_score}.",
                    result.stderr,
                )
                self.assertFalse(output.exists())

    def test_default_score_generates_exact_evaluation_total(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-default-score-") as temp_name:
            folder = Path(temp_name)
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            payload["lessons"][0].pop("score")
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            generated = sorted(output.glob("*.docx"))[0]
            nested = Document(generated).tables[0].cell(12, 1).tables[0]
            score_sum = sum(
                (Decimal(nested.cell(row, 2).text.strip()) for row in range(1, 14)),
                Decimal("0"),
            )
            self.assertEqual(score_sum, Decimal("89"))

    def test_lesson_course_override_is_validated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-course-override-") as temp_name:
            folder = Path(temp_name)
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            payload["lessons"] = [payload["lessons"][0]]
            payload["total_hours"] = 2
            payload["lessons"][0]["course_name"] = "接口测试实训"
            payload["lessons"][0]["major"] = "数据科学与大数据技术"
            payload["lessons"][0]["audience"] = "高职三年级"
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            generated = next(output.glob("*.docx"))
            document = Document(generated)
            self.assertEqual(document.tables[0].cell(0, 1).text.strip(), "接口测试实训")
            self.assertEqual(document.tables[0].cell(0, 5).text.strip(), "数据科学与大数据技术")
            self.assertEqual(document.tables[0].cell(0, 9).text.strip(), "高职三年级")
            self.assertIn("《接口测试实训》", document.paragraphs[0].text)

            document.tables[0].cell(0, 5).text = "错误专业"
            document.save(generated)
            validation = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(validation.returncode, 0)
            self.assertIn("major field mismatch", validation.stderr)

    def test_lesson_filename_is_bounded_by_utf8_bytes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-long-filename-") as temp_name:
            folder = Path(temp_name)
            payload = {
                "course_name": "软件测试",
                "total_hours": 2,
                "lessons": [
                    {
                        "unit": "项目一" + "单元" * 28,
                        "task": "完成" + "测试任务" * 19,
                        "hours": "2",
                        "flows": [],
                        "knowledge": [],
                    }
                ],
            }
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            generated = next(output.glob("*.docx"))
            self.assertLessEqual(len(generated.name.encode("utf-8")), 255)
            self.assertIn("~", generated.stem)

    def test_long_teaching_content_is_generated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-long-") as temp_name:
            folder = Path(temp_name)
            payload = {
                "course_name": "软件测试实训" + "课程" * 13,
                "total_hours": 2,
                "lessons": [
                    {
                        "unit": "项目一 测试项目准备",
                        "task": "编制测试计划并完成环境检查",
                        "hours": "2",
                        "flows": [f"流程{i + 1}" + "：" + "检查测试环境、记录问题并提交阶段成果" * 3 for i in range(5)],
                        "knowledge": ["测试计划结构", "环境检查要点"],
                        "score": 90,
                    }
                ],
            }
            source = folder / "tasks.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(folder / "output"),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_manifest_coordinate_and_major_failures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-manifest-") as temp_name:
            folder = Path(temp_name)
            template = folder / "template.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", template)
            manifest_text = (LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "manifest.yaml").read_text(encoding="utf-8")
            bad_coordinate = folder / "bad-coordinate.yaml"
            bad_coordinate.write_text(manifest_text.replace("paragraph: 0, mode: replace_text_preserve_style", "paragraph: 999, mode: replace_text_preserve_style", 1), encoding="utf-8")
            result = run_script(LESSON / "scripts" / "validate_template.py", "--template", str(template), "--manifest", str(bad_coordinate), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing document paragraph", result.stdout)

            incompatible = folder / "incompatible.yaml"
            incompatible.write_text(manifest_text.replace("version: 1.0.0", "version: 2.0.0", 1), encoding="utf-8")
            result = run_script(LESSON / "scripts" / "validate_template.py", "--template", str(template), "--manifest", str(incompatible), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsupported template major version", result.stdout)

    def test_custom_lesson_template_rejects_fixed_label_relocation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-fixed-label-") as temp_name:
            custom = Path(temp_name) / "custom.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            document = Document(custom)
            table = document.tables[0]
            table.cell(0, 0).text = "授课专业"
            table.cell(0, 3).text = "课程名称"
            document.save(custom)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected main-table structure or formatting", result.stdout)

    def test_custom_lesson_template_rejects_style_definition_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-style-guard-") as temp_name:
            custom = Path(temp_name) / "custom.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            document = Document(custom)
            document.styles["Normal"].font.size = Pt(13)
            document.save(custom)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected main-table structure or formatting", result.stdout)

    def test_custom_lesson_template_rejects_title_formatting_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-title-format-guard-") as temp_name:
            custom = Path(temp_name) / "custom.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            document = Document(custom)
            document.paragraphs[0].runs[0].font.size = Pt(19)
            document.save(custom)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected main-table structure or formatting", result.stdout)

    def test_custom_lesson_template_rejects_header_footer_formatting_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-header-format-guard-") as temp_name:
            custom = Path(temp_name) / "custom.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            document = Document(custom)
            document.sections[0].header.paragraphs[0].paragraph_format.space_before = Pt(1)
            document.save(custom)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected page, header, footer, or section settings", result.stdout)

    def test_custom_lesson_template_rejects_section_property_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-section-property-guard-") as temp_name:
            folder = Path(temp_name)
            custom = folder / "custom.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            document = Document(custom)
            columns = OxmlElement("w:cols")
            columns.set(qn("w:num"), "2")
            document.sections[0]._sectPr.append(columns)
            document.save(custom)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected page, header, footer, or section settings", result.stdout)

    def test_custom_lesson_template_rejects_document_settings_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-settings-guard-") as temp_name:
            folder = Path(temp_name)
            custom = folder / "custom.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            document = Document(custom)
            default_tab_stop = OxmlElement("w:defaultTabStop")
            default_tab_stop.set(qn("w:val"), "240")
            document.settings._element.append(default_tab_stop)
            document.save(custom)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected page, header, footer, or section settings", result.stdout)

    def test_custom_lesson_template_rejects_theme_definition_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-theme-guard-") as temp_name:
            folder = Path(temp_name)
            custom = folder / "custom.docx"
            tampered = folder / "tampered.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            with zipfile.ZipFile(custom, "r") as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == "word/theme/theme1.xml":
                        data = data.replace(b"Office Theme", b"Tampered Theme")
                    target.writestr(info, data)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(tampered),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected main-table structure or formatting", result.stdout)

    def test_custom_lesson_template_rejects_protected_body_paragraph_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-body-guard-") as temp_name:
            custom = Path(temp_name) / "custom.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", custom)
            document = Document(custom)
            document.paragraphs[1].add_run("未声明正文")
            document.save(custom)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected main-table structure or formatting", result.stdout)

    def test_generation_writes_qa_report_and_preserves_structure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-test-") as temp_name:
            output = Path(temp_name) / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(ROOT / "tests" / "fixtures" / "lesson-plan-input.json"),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertTrue((output / "qa-report.json").exists())
            self.assertEqual(len(list(output.glob("*.docx"))), 2)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["template_id"], "lesson-plan")
            self.assertEqual(report["template_version"], "1.0.0")
            self.assertEqual(report["generator_version"], "1.0.0")
            self.assertEqual(report["engine"], "python-docx")
            self.assertFalse(report["custom_template"])
            self.assertEqual(report["validation_skipped"], [])
            self.assertEqual(report["status"], "passed")
            payload = json.loads((ROOT / "tests" / "fixtures" / "lesson-plan-input.json").read_text(encoding="utf-8"))
            for path, item in zip(sorted(output.glob("*.docx")), payload["lessons"]):
                self.assertEqual(len(Document(path).tables[0].rows), 30)
                nested = Document(path).tables[0].cell(12, 1).tables[0]
                score_sum = sum(
                    (Decimal(nested.cell(row, 2).text.strip()) for row in range(1, 14)),
                    Decimal("0"),
                )
                self.assertEqual(score_sum, Decimal(str(item["score"])))

    def test_generation_copies_direct_formatting_to_added_multiline_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-multiline-format-") as temp_name:
            output = Path(temp_name) / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            template_cell = Document(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx").tables[0].cell(4, 1)
            output_cell = Document(sorted(output.glob("*.docx"))[0]).tables[0].cell(4, 1)
            self.assertGreater(len(output_cell.paragraphs), 1)
            source_ppr = template_cell.paragraphs[0]._p.pPr.xml
            source_rpr = template_cell.paragraphs[0].runs[0]._r.rPr.xml
            for paragraph in output_cell.paragraphs[1:]:
                self.assertEqual(paragraph._p.pPr.xml, source_ppr)
                self.assertEqual(paragraph.runs[0]._r.rPr.xml, source_rpr)

    def test_output_validation_orders_three_digit_lesson_files_numerically(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-three-digit-") as temp_name:
            folder = Path(temp_name)
            payload = {
                "course_name": "软件测试实训",
                "total_hours": 200,
                "lessons": [
                    {
                        "unit": f"项目{i + 1} 测试任务",
                        "task": f"完成测试任务{i + 1}",
                        "hours": "2",
                        "flows": [],
                        "knowledge": [],
                        "score": 89.5,
                    }
                    for i in range(100)
                ],
            }
            source = folder / "tasks.json"
            output = folder / "output"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_compatibility_template_and_skipped_validation_leave_qa_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-compat-qa-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--template",
                str(LESSON / "assets" / "lesson-plan-template.docx"),
                "--tasks-json",
                str(ROOT / "tests" / "fixtures" / "lesson-plan-input.json"),
                "--output-dir",
                str(output),
                "--skip-output-validation",
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "skipped")
            self.assertTrue(report["custom_template"])
            self.assertEqual(report["validation_skipped"], ["output"])
            self.assertIn("output", report["checks"]["validation"]["skipped"])
            self.assertIn("Custom template selected", " ".join(report["warnings"]))

    def test_manifest_loading_failures_are_clear(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-manifest-errors-") as temp_name:
            folder = Path(temp_name)
            template = folder / "template.docx"
            shutil.copy2(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx", template)
            missing = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(template),
                "--manifest",
                str(folder / "missing.yaml"),
                "--json",
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("No such file", missing.stdout)

            malformed = folder / "malformed.yaml"
            malformed.write_text("template: [", encoding="utf-8")
            result = run_script(LESSON / "scripts" / "validate_template.py", "--manifest", str(malformed), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("errors", result.stdout)

            manifest_text = (LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "manifest.yaml").read_text(encoding="utf-8")
            missing_version = folder / "missing-version.yaml"
            missing_version.write_text(manifest_text.replace("  version: 1.0.0\n", "", 1), encoding="utf-8")
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(template),
                "--manifest",
                str(missing_version),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("semantic template version", result.stdout)

            missing_template = folder / "missing-template.yaml"
            missing_template.write_text(manifest_text.replace("file: template.docx", "file: missing.docx", 1), encoding="utf-8")
            result = run_script(LESSON / "scripts" / "validate_template.py", "--manifest", str(missing_template), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Template not found", result.stdout)

    def test_structure_breaking_docx_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-broken-") as temp_name:
            broken = Path(temp_name) / "broken.docx"
            document = Document(LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx")
            document.add_table(rows=1, cols=1)
            document.save(broken)
            result = run_script(
                LESSON / "scripts" / "validate_template.py",
                "--template",
                str(broken),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Top-level table count mismatch", result.stdout)

    def test_output_residual_template_text_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-residual-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(ROOT / "tests" / "fixtures" / "lesson-plan-input.json"),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = next(output.glob("*.docx"))
            document = Document(path)
            document.tables[0].cell(3, 1).paragraphs[0].text = "Linux操作系统应用残留"
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(ROOT / "tests" / "fixtures" / "lesson-plan-input.json"),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("forbidden template text", result.stderr)

    def test_output_validation_rejects_evaluation_score_above_rubric_maximum(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-score-cap-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            nested = document.tables[0].cell(12, 1).tables[0]
            original_row_10 = Decimal(nested.cell(10, 2).text.strip())
            nested.cell(1, 2).text = "3.5"
            nested.cell(10, 2).text = str(original_row_10 - Decimal("0.5"))
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("evaluation score row 1 exceeds rubric maximum 3", result.stderr)

    def test_output_validation_rejects_header_footer_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-header-footer-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            document.sections[0].header.paragraphs[0].text = "被篡改页眉"
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected DOCX layout changed", result.stderr)

    def test_output_validation_rejects_fixed_label_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-fixed-label-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            nested = document.tables[0].cell(12, 1).tables[0]
            nested.cell(1, 1).text = "被篡改的评价要素"
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected DOCX layout changed", result.stderr)

    def test_output_validation_rejects_writable_direct_formatting_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-direct-format-guard-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            paragraph = document.tables[0].cell(4, 1).paragraphs[0]
            paragraph.paragraph_format.space_before = Pt(1)
            run = paragraph.runs[0]
            run.bold = True
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected DOCX layout changed", result.stderr)

    def test_output_validation_rejects_title_formatting_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-title-output-guard-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            document.paragraphs[0].runs[0].font.size = Pt(19)
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected DOCX layout changed", result.stderr)

    def test_output_validation_rejects_document_settings_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-settings-output-guard-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            character_spacing = OxmlElement("w:characterSpacingControl")
            character_spacing.set(qn("w:val"), "doNotCompress")
            document.settings._element.append(character_spacing)
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected DOCX layout changed", result.stderr)

    def test_output_validation_rejects_removed_writable_direct_formatting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-direct-format-removal-guard-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            cell = document.tables[0].cell(4, 1)
            for paragraph in cell.paragraphs:
                if paragraph._p.pPr is not None:
                    paragraph._p.remove(paragraph._p.pPr)
                for run in paragraph.runs:
                    if run._r.rPr is not None:
                        run._r.remove(run._r.rPr)
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("protected DOCX layout changed", result.stderr)

    def test_output_validation_rejects_composed_content_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-composed-output-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            document.tables[0].cell(4, 1).text = "被替换的教学内容"
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("teaching_content content mismatch", result.stderr)

    def test_output_validation_rejects_implementation_content_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-implementation-output-guard-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            document.tables[0].cell(16, 1).text = "被替换的实施内容"
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("implementation cell mismatch", result.stderr)

    def test_output_validation_rejects_deterministic_field_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-deterministic-output-guard-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            ability_cell = _Cell(document.tables[0].rows[6]._tr.tc_lst[3], document.tables[0].rows[6]._parent)
            ability_cell.text = "被替换的能力目标"
            document.tables[0].cell(29, 2).text = "被替换的教学反思"
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ability_goal content mismatch", result.stderr)
            self.assertIn("reflection cell mismatch", result.stderr)

    def test_output_validation_rejects_evaluation_cell_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-package-evaluation-output-guard-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            path = sorted(output.glob("*.docx"))[0]
            document = Document(path)
            document.tables[0].cell(12, 1).tables[0].cell(1, 3).text = "被篡改评价备注"
            document.save(path)
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("evaluation cell mismatch", result.stderr)


class GradebookTotalRuleTests(unittest.TestCase):
    def test_total_rule_matches_exactly_with_zero_and_nonzero_skill_weights(self) -> None:
        sys.modules.pop("package_common", None)
        sys.path.insert(0, str(GRADE / "scripts"))
        from package_common import calculate_expected_total, source_total_matches, validate_source_totals

        no_skill_weights = {"regular": 0.6, "theory": 0.4, "skill": 0.0}
        no_skill = {"regular": 86.5, "theory": 88.0, "skill": 0.0, "total": 87.0}
        no_skill_expected = calculate_expected_total(no_skill, no_skill_weights)
        self.assertEqual(no_skill_expected, 87)
        self.assertTrue(source_total_matches(87.0000000001, no_skill_expected))
        self.assertFalse(source_total_matches(87.4, no_skill_expected))
        validate_source_totals([no_skill], no_skill_weights)

        skill_weights = {"regular": 0.5, "theory": 0.3, "skill": 0.2}
        skill = {"regular": 91.0, "theory": 90.0, "skill": 90.0, "total": 91.0}
        skill_expected = calculate_expected_total(skill, skill_weights)
        self.assertEqual(skill_expected, 91)
        validate_source_totals([skill], skill_weights)

        self.assertFalse(source_total_matches(88, no_skill_expected))
        self.assertFalse(source_total_matches(86, no_skill_expected))
        with self.assertRaisesRegex(ValueError, "Source total mismatch"):
            validate_source_totals([{**no_skill, "total": 88}], no_skill_weights)
        with self.assertRaisesRegex(ValueError, "Source total mismatch"):
            validate_source_totals([{**no_skill, "total": 86}], no_skill_weights)
        with self.assertRaisesRegex(ValueError, "Source total mismatch"):
            validate_source_totals([{**no_skill, "total": 87.4}], no_skill_weights)


class GradebookPowerShellContractTests(unittest.TestCase):
    def test_com_path_uses_same_rounding_preflight_and_exact_output_contract(self) -> None:
        script = (GRADE / "scripts" / "generate_gradebook.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Excel-Round", script)
        self.assertIn("function Format-Percentage-Label", script)
        self.assertIn("[System.MidpointRounding]::AwayFromZero", script)
        self.assertIn("function Assert-ManifestCompatibility", script)
        self.assertIn("Assert-ManifestCompatibility $ManifestData", script)
        self.assertIn("function Source-Total-Matches", script)
        self.assertIn("function Assert-HalfPointRegularScores", script)
        self.assertIn("function Assert-NormalizedInput", script)
        self.assertIn("validate_input.py", script)
        self.assertIn("Assert-NormalizedInput $normalizedInput", script)
        self.assertIn("function Assert-SourceTotals", script)
        self.assertIn("Assert-HalfPointRegularScores $students", script)
        self.assertIn("Assert-SourceTotals $students $meta", script)
        self.assertIn("'--output-file'", script)
        self.assertNotIn("abs_tol=1.0", script)


class WorkflowContractTests(unittest.TestCase):
    def test_template_package_ci_runs_on_main_push(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "template-package-ci.yml").read_text(encoding="utf-8")
        self.assertIn("      - main\n      - master", workflow)


@unittest.skipUnless(soffice_path(), "LibreOffice is required for XLS package tests")
class GradebookTemplatePackageTests(unittest.TestCase):
    def make_source(
        self,
        folder: Path,
        skill: bool = False,
        count: int = 2,
        leading_zero: bool = False,
        total_delta: float = 0.0,
        regular_override: float | None = None,
        regular_pct: float | None = None,
        theory_pct: float | None = None,
        skill_pct: float | None = None,
    ) -> Path:
        xlsx = folder / "课程成绩单.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "成绩单"
        regular_pct = (0.5 if skill else 0.6) if regular_pct is None else regular_pct
        theory_pct = (0.3 if skill else 0.4) if theory_pct is None else theory_pct
        skill_pct = (0.2 if skill else 0.0) if skill_pct is None else skill_pct
        sheet["A2"] = f"课程名称:软件测试实训 教师:张老师 上课班级:软件技术2401班 成绩项目比例:技能成绩{skill_pct * 100:g}% 理论成绩{theory_pct * 100:g}% 平时成绩{regular_pct * 100:g}%"
        sheet["A3"] = "开课学期:2025-2026-2"
        headers = ["学号", "姓名", "平时成绩", "理论成绩"] + (["技能成绩"] if skill else []) + ["总成绩"]
        for col, value in enumerate(headers, start=1):
            sheet.cell(4, col).value = value
        rows = []
        for index in range(count):
            regular = regular_override if regular_override is not None and index == 0 else [86.5, 91.0, 100.0, 0.0][index % 4]
            theory = [88.0, 90.0, 100.0, 0.0][index % 4]
            skill_score = [92.0, 90.0, 100.0, 0.0][index % 4]
            total = math.floor(regular * regular_pct + theory * theory_pct + skill_score * skill_pct + 0.5)
            if index == 0:
                total += total_delta
            student_id = "0012345678" if leading_zero and index == 0 else f"240101{index + 1:03d}"
            values = [student_id, f"学生{index + 1}", regular, theory] + ([skill_score] if skill else []) + [total]
            rows.append(values)
        for row, values in enumerate(rows, start=5):
            for col, value in enumerate(values, start=1):
                sheet.cell(row, col).value = value
            sheet.cell(row, 1).number_format = "@"
        workbook.save(xlsx)
        subprocess.run(
            [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(folder), str(xlsx)],
            check=True,
            capture_output=True,
        )
        return folder / "课程成绩单.xls"

    def test_canonical_template_and_compatibility_entry(self) -> None:
        result = run_script(GRADE / "scripts" / "validate_template.py", "--json")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["checks"]["structure"]["rows"], 52)
        self.assertEqual(report["checks"]["structure"]["columns"], 17)

    def test_invalid_input_is_rejected(self) -> None:
        sys.modules.pop("package_common", None)
        sys.path.insert(0, str(GRADE / "scripts"))
        from package_common import validate_input

        bad = {"term": "2025", "course": "软件测试", "teacher": "张老师", "class_name": "一班", "weights": {"regular": 1, "theory": 0, "skill": 0}, "students": [{"id": "bad"}]}
        with self.assertRaises(ValueError):
            validate_input(bad)

    def test_python_generator_zero_skill_and_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-test-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertTrue((output / "qa-report.json").exists())
            self.assertEqual(len(list(output.glob("*.xls"))), 1)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["template_id"], "course-gradebook")
            self.assertEqual(report["template_version"], "1.0.0")
            self.assertEqual(report["generator_version"], "1.0.0")
            self.assertEqual(report["engine"], "libreoffice-openpyxl")
            self.assertFalse(report["custom_template"])
            self.assertEqual(report["validation_skipped"], [])
            self.assertEqual(report["status"], "passed")
            generated = next(output.glob("*.xls"))
            self.assertEqual(report["output_file"], generated.name)
            self.assertEqual(report["files_checked"], 1)

    def test_python_generator_preserves_fractional_weight_headers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-fractional-weights-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder, skill=True, regular_pct=0.333, theory_pct=0.333, skill_pct=0.334)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            xlsx_dir = folder / "xlsx-output"
            xlsx_dir.mkdir()
            generated = next(output.glob("*.xls"))
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(generated)],
                check=True,
                capture_output=True,
            )
            workbook = load_workbook(next(xlsx_dir.glob("*.xlsx")), data_only=False)
            sheet = workbook["平时成绩"]
            self.assertEqual(sheet["D3"].value, "平时成绩(33.3%)")
            self.assertEqual(sheet["M3"].value, "理论成绩(33.3%)")
            self.assertEqual(sheet["O3"].value, "技能成绩（33.4%）")

    def test_output_validation_rejects_theory_score_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-theory-mismatch-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
                "--skip-output-validation",
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            generated = next(output.glob("*.xls"))

            xlsx_dir = folder / "tamper-xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(generated)],
                check=True,
                capture_output=True,
            )
            tampered_xlsx = xlsx_dir / f"{generated.stem}.xlsx"
            workbook = load_workbook(tampered_xlsx)
            workbook["平时成绩"]["M5"] = 87.0
            workbook.save(tampered_xlsx)
            tampered_dir = folder / "tampered"
            tampered_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(tampered_dir), str(tampered_xlsx)],
                check=True,
                capture_output=True,
            )
            tampered = output / "tampered.xls"
            shutil.copy2(tampered_dir / f"{generated.stem}.xls", tampered)

            normalized = folder / "normalized.json"
            normalized.write_text(
                json.dumps(
                    {
                        "term": "2025-2026-2",
                        "course": "软件测试实训",
                        "teacher": "张老师",
                        "class_name": "软件技术2401班",
                        "weights": {"regular": 0.6, "theory": 0.4, "skill": 0.0},
                        "students": [
                            {"id": "240101001", "name": "学生1", "regular": 86.5, "theory": 88.0, "skill": 0.0, "total": 87.0},
                            {"id": "240101002", "name": "学生2", "regular": 91.0, "theory": 90.0, "skill": 0.0, "total": 91.0},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = run_script(
                GRADE / "scripts" / "validate_output.py",
                "--input-json",
                str(normalized),
                "--output-dir",
                str(output),
                "--output-file",
                str(tampered),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("theory score mismatch", result.stderr)

    def test_output_validation_rejects_non_target_sheet_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-non-target-mismatch-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
                "--skip-output-validation",
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            generated = next(output.glob("*.xls"))

            xlsx_dir = folder / "tamper-xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(generated)],
                check=True,
                capture_output=True,
            )
            tampered_xlsx = xlsx_dir / f"{generated.stem}.xlsx"
            workbook = load_workbook(tampered_xlsx)
            workbook["Sheet1"]["B1"] = "被篡改的受保护工作表内容"
            workbook.save(tampered_xlsx)
            tampered_dir = folder / "tampered"
            tampered_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(tampered_dir), str(tampered_xlsx)],
                check=True,
                capture_output=True,
            )
            tampered = output / "tampered.xls"
            shutil.copy2(tampered_dir / f"{generated.stem}.xls", tampered)

            normalized = folder / "normalized.json"
            normalized.write_text(
                json.dumps(
                    {
                        "term": "2025-2026-2",
                        "course": "软件测试实训",
                        "teacher": "张老师",
                        "class_name": "软件技术2401班",
                        "weights": {"regular": 0.6, "theory": 0.4, "skill": 0.0},
                        "students": [
                            {"id": "240101001", "name": "学生1", "regular": 86.5, "theory": 88.0, "skill": 0.0, "total": 87.0},
                            {"id": "240101002", "name": "学生2", "regular": 91.0, "theory": 90.0, "skill": 0.0, "total": 91.0},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = run_script(
                GRADE / "scripts" / "validate_output.py",
                "--input-json",
                str(normalized),
                "--output-dir",
                str(output),
                "--output-file",
                str(tampered),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Protected worksheet changed: Sheet1", result.stderr)

    def test_python_generator_skill_and_leading_zero_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-skill-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder, skill=True, leading_zero=True)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["checks"]["skill_enabled"])
            self.assertEqual(report["checks"]["structure"]["columns"], 17)
            self.assertEqual(report["checks"]["students"][0]["status"], "passed")
            generated = next(output.glob("*.xls"))
            self.assertEqual(report["output_file"], generated.name)
            self.assertEqual(report["files_checked"], 1)
            self.assertNotIn("0012345678", json.dumps(report, ensure_ascii=False))

    def test_python_generator_ignores_unrelated_xls_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-unrelated-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            output.mkdir()
            template = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            shutil.copy2(template, output / "unrelated-a.xls")
            shutil.copy2(template, output / "unrelated-b.xls")
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            generated = [path for path in output.glob("*.xls") if path.name.startswith(folder.name)]
            self.assertEqual(len(generated), 1)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["output_file"], generated[0].name)
            self.assertEqual(report["files_checked"], 1)
            self.assertEqual(report["checks"]["file_count"]["actual"], 1)

    def test_rejects_source_total_mismatch_positive_one(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-total-plus-one-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder, total_delta=1.0)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Source total mismatch", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_source_total_mismatch_negative_one(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-total-minus-one-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder, total_delta=-1.0)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Source total mismatch", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_fractional_source_total_before_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-total-fraction-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder, total_delta=0.4)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Source total mismatch", result.stderr)
            self.assertIn("received 87.4", result.stderr)
            self.assertFalse(output.exists())

    def test_rejects_fractional_regular_score_before_generation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-regular-fraction-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder, regular_override=89.2)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("students[0].regular must use 0.5-point increments; received 89.2.", result.stderr)
            self.assertFalse(output.exists())

    def test_custom_template_allows_writable_values_but_preserves_formatting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-custom-values-") as temp_name:
            folder = Path(temp_name)
            canonical = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            xlsx_dir = folder / "xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(canonical)],
                check=True,
                capture_output=True,
            )
            xlsx = xlsx_dir / "template.xlsx"
            workbook = load_workbook(xlsx)
            sheet = workbook["平时成绩"]
            for cell, value in {
                "C2": "自定义学期",
                "G2": "自定义课程",
                "L2": "自定义教师",
                "O2": "自定义班级",
                "D3": "平时成绩(99%)",
                "M3": "理论成绩(1%)",
                "O3": "技能成绩（0%）",
            }.items():
                sheet[cell] = value
            workbook.save(xlsx)
            custom_dir = folder / "custom"
            custom_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(custom_dir), str(xlsx)],
                check=True,
                capture_output=True,
            )
            custom = custom_dir / "template.xls"
            result = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

            formatted_xlsx = folder / "formatted-template.xlsx"
            formatted_workbook = load_workbook(xlsx)
            formatted_sheet = formatted_workbook["平时成绩"]
            formatted_font = copy(formatted_sheet["C2"].font)
            formatted_font.sz = (formatted_font.sz or 11) + 1
            formatted_sheet["C2"].font = formatted_font
            formatted_workbook.save(formatted_xlsx)
            formatted_dir = folder / "formatted"
            formatted_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(formatted_dir), str(formatted_xlsx)],
                check=True,
                capture_output=True,
            )
            formatted = formatted_dir / "formatted-template.xls"
            formatted_result = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(formatted),
                "--json",
            )
            self.assertNotEqual(formatted_result.returncode, 0)
            self.assertIn("Custom template changed protected workbook structure or formatting", formatted_result.stdout)

    def test_custom_template_rejects_protected_target_cell_formatting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-custom-target-format-guard-") as temp_name:
            folder = Path(temp_name)
            canonical = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            xlsx_dir = folder / "xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(canonical)],
                check=True,
                capture_output=True,
            )
            xlsx = xlsx_dir / "template.xlsx"
            workbook = load_workbook(xlsx)
            sheet = workbook["平时成绩"]
            changed_font = copy(sheet["A1"].font)
            changed_font.sz = (changed_font.sz or 11) + 1
            sheet["A1"].font = changed_font
            workbook.save(xlsx)
            custom_dir = folder / "custom"
            custom_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(custom_dir), str(xlsx)],
                check=True,
                capture_output=True,
            )
            result = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(custom_dir / "template.xls"),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected workbook structure or formatting", result.stdout)

    def test_custom_template_rejects_print_header_footer_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-custom-print-header-guard-") as temp_name:
            folder = Path(temp_name)
            canonical = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            xlsx_dir = folder / "xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(canonical)],
                check=True,
                capture_output=True,
            )
            xlsx = xlsx_dir / "template.xlsx"
            workbook = load_workbook(xlsx)
            workbook["平时成绩"].oddHeader.center.text = "自定义打印页眉"
            workbook.save(xlsx)
            custom_dir = folder / "custom"
            custom_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(custom_dir), str(xlsx)],
                check=True,
                capture_output=True,
            )
            result = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(custom_dir / "template.xls"),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected workbook structure or formatting", result.stdout)

    def test_custom_template_rejects_non_target_sheet_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-custom-non-target-") as temp_name:
            folder = Path(temp_name)
            canonical = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            xlsx_dir = folder / "xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(canonical)],
                check=True,
                capture_output=True,
            )
            xlsx = xlsx_dir / "template.xlsx"
            workbook = load_workbook(xlsx)
            workbook["Sheet1"]["B1"] = "被修改的非目标工作表内容"
            workbook["Sheet3"]["A1"] = "=1+1"
            workbook.save(xlsx)
            custom_dir = folder / "custom"
            custom_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(custom_dir), str(xlsx)],
                check=True,
                capture_output=True,
            )
            custom = custom_dir / "template.xls"
            result = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(custom),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected workbook structure or formatting", result.stdout)

    def test_custom_template_rejects_regular_item_header_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-custom-header-") as temp_name:
            folder = Path(temp_name)
            canonical = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            xlsx_dir = folder / "xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(canonical)],
                check=True,
                capture_output=True,
            )
            xlsx = xlsx_dir / "template.xlsx"
            workbook = load_workbook(xlsx)
            workbook["平时成绩"]["E4"] = "被修改的常规项目"
            workbook.save(xlsx)
            custom_dir = folder / "custom"
            custom_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(custom_dir), str(xlsx)],
                check=True,
                capture_output=True,
            )
            result = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(custom_dir / "template.xls"),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Custom template changed protected workbook structure or formatting", result.stdout)

    def test_output_validation_rejects_target_sheet_formatting_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-format-mismatch-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
                "--skip-output-validation",
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            generated = next(output.glob("*.xls"))

            xlsx_dir = folder / "tamper-xlsx"
            xlsx_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(generated)],
                check=True,
                capture_output=True,
            )
            tampered_xlsx = xlsx_dir / f"{generated.stem}.xlsx"
            workbook = load_workbook(tampered_xlsx)
            tampered_font = copy(workbook["平时成绩"]["C5"].font)
            tampered_font.sz = (tampered_font.sz or 10) + 1
            workbook["平时成绩"]["C5"].font = tampered_font
            workbook["平时成绩"]["E4"] = "被篡改的常规项目"
            workbook["平时成绩"].page_margins.left = (workbook["平时成绩"].page_margins.left or 0) + 1
            workbook["平时成绩"].oddHeader.center.text = "被篡改的打印页眉"
            workbook.save(tampered_xlsx)
            tampered_dir = folder / "tampered"
            tampered_dir.mkdir()
            subprocess.run(
                [soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(tampered_dir), str(tampered_xlsx)],
                check=True,
                capture_output=True,
            )
            tampered = output / "tampered.xls"
            shutil.copy2(tampered_dir / f"{generated.stem}.xls", tampered)

            normalized = folder / "normalized.json"
            normalized.write_text(
                json.dumps(
                    {
                        "term": "2025-2026-2",
                        "course": "软件测试实训",
                        "teacher": "张老师",
                        "class_name": "软件技术2401班",
                        "weights": {"regular": 0.6, "theory": 0.4, "skill": 0.0},
                        "students": [
                            {"id": "240101001", "name": "学生1", "regular": 86.5, "theory": 88.0, "skill": 0.0, "total": 87.0},
                            {"id": "240101002", "name": "学生2", "regular": 91.0, "theory": 90.0, "skill": 0.0, "total": 91.0},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = run_script(
                GRADE / "scripts" / "validate_output.py",
                "--input-json",
                str(normalized),
                "--output-dir",
                str(output),
                "--output-file",
                str(tampered),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("target sheet formatting mismatch", result.stderr)
            self.assertIn("target sheet protected value mismatch at E4", result.stderr)
            self.assertIn("target sheet print settings mismatch", result.stderr)

    def test_legacy_output_dir_with_multiple_candidates_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-multiple-candidates-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            output.mkdir()
            template = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            shutil.copy2(template, output / "candidate-a.xls")
            shutil.copy2(template, output / "candidate-b.xls")
            result = run_script(
                GRADE / "scripts" / "validate_output.py",
                "--input-json",
                str(ROOT / "tests" / "fixtures" / "gradebook-input.json"),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Expected one generated XLS file, got 2", result.stderr)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["output_file"], "")
            self.assertEqual(report["files_checked"], 0)
            self.assertEqual(report["checks"]["file_count"]["actual"], 2)

    def test_python_compatibility_template_and_skipped_validation_leave_qa_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-compat-qa-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--template",
                str(GRADE / "assets" / "平时成绩记分册模板.xls"),
                "--output-dir",
                str(output),
                "--skip-output-validation",
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "skipped")
            self.assertTrue(report["custom_template"])
            self.assertEqual(report["engine"], "libreoffice-openpyxl")
            self.assertEqual(report["validation_skipped"], ["output"])
            self.assertIn("Custom template selected", " ".join(report["warnings"]))

    def test_python_generator_expands_beyond_template_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-many-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder, count=50)
            output = folder / "output"
            result = run_script(
                GRADE / "scripts" / "generate_gradebook.py",
                "--source",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(report["checks"]["students"]), 50)

    def test_regular_score_boundaries_are_exact(self) -> None:
        sys.modules.pop("generate_gradebook", None)
        sys.path.insert(0, str(GRADE / "scripts"))
        from generate_gradebook import generate_regular_scores

        for target in (0.0, 86.5, 100.0):
            scores = generate_regular_scores(target, f"boundary-{target}")
            self.assertEqual(len(scores), 8)
            self.assertAlmostEqual(sum(scores) / len(scores), target, places=7)
            self.assertTrue(all(0 <= score <= 100 for score in scores))
            self.assertTrue(all(abs(score * 2 - round(score * 2)) < 1e-7 for score in scores))
        self.assertEqual(len(generate_regular_scores(86.5, "four-items", item_count=4)), 4)

    def test_structure_breaking_xls_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-broken-") as temp_name:
            folder = Path(temp_name)
            source = GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls"
            xlsx_dir = folder / "xlsx"
            xlsx_dir.mkdir()
            subprocess.run([soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(source)], check=True, capture_output=True)
            xlsx = xlsx_dir / "template.xlsx"
            workbook = load_workbook(xlsx)
            workbook["平时成绩"]["A3"] = "坏标签"
            workbook.save(xlsx)
            broken_dir = folder / "broken"
            broken_dir.mkdir()
            subprocess.run([soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(broken_dir), str(xlsx)], check=True, capture_output=True)
            broken = broken_dir / "template.xls"
            result = run_script(GRADE / "scripts" / "validate_template.py", "--template", str(broken), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("required header", result.stdout)

    def test_incompatible_manifest_major_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-manifest-") as temp_name:
            folder = Path(temp_name)
            template = folder / "template.xls"
            shutil.copy2(GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls", template)
            manifest = folder / "manifest.yaml"
            manifest_text = (GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "manifest.yaml").read_text(encoding="utf-8")
            manifest.write_text(manifest_text.replace("version: 1.0.0", "version: 2.0.0", 1), encoding="utf-8")
            result = run_script(GRADE / "scripts" / "validate_template.py", "--template", str(template), "--manifest", str(manifest), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Unsupported template major version", result.stdout)

    def test_manifest_loading_failures_are_clear(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-manifest-errors-") as temp_name:
            folder = Path(temp_name)
            template = folder / "template.xls"
            shutil.copy2(GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "template.xls", template)
            missing = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(template),
                "--manifest",
                str(folder / "missing.yaml"),
                "--json",
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("No such file", missing.stdout)

            malformed = folder / "malformed.yaml"
            malformed.write_text("template: [", encoding="utf-8")
            result = run_script(GRADE / "scripts" / "validate_template.py", "--manifest", str(malformed), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("errors", result.stdout)

            manifest_text = (GRADE / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "manifest.yaml").read_text(encoding="utf-8")
            missing_version = folder / "missing-version.yaml"
            missing_version.write_text(manifest_text.replace("  version: 1.0.0\n", "", 1), encoding="utf-8")
            result = run_script(
                GRADE / "scripts" / "validate_template.py",
                "--template",
                str(template),
                "--manifest",
                str(missing_version),
                "--json",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("semantic template version", result.stdout)

            missing_template = folder / "missing-template.yaml"
            missing_template.write_text(manifest_text.replace("file: template.xls", "file: missing.xls", 1), encoding="utf-8")
            result = run_script(GRADE / "scripts" / "validate_template.py", "--manifest", str(missing_template), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Template not found", result.stdout)

    def test_formula_error_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-formula-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            result = run_script(GRADE / "scripts" / "generate_gradebook.py", "--source", str(source), "--output-dir", str(output))
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            output_file = next(output.glob("*.xls"))
            xlsx_dir = folder / "broken-xlsx"
            xlsx_dir.mkdir()
            subprocess.run([soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(output_file)], check=True, capture_output=True)
            xlsx = xlsx_dir / f"{output_file.stem}.xlsx"
            workbook = load_workbook(xlsx)
            workbook["平时成绩"]["L5"] = "=#REF!"
            workbook.save(xlsx)
            broken_dir = folder / "broken-xls"
            broken_dir.mkdir()
            subprocess.run([soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(broken_dir), str(xlsx)], check=True, capture_output=True)
            broken = broken_dir / f"{output_file.stem}.xls"
            output_file.unlink()
            broken.replace(output_file)
            input_json = folder / "input.json"
            input_json.write_text(json.dumps({
                "term": "2025-2026-2",
                "course": "软件测试实训",
                "teacher": "张老师",
                "class_name": "软件技术2401班",
                "weights": {"regular": 0.6, "theory": 0.4, "skill": 0.0},
                "students": [
                    {"id": "240101001", "name": "学生1", "regular": 86.5, "theory": 88.0, "skill": 0.0, "total": 87.0},
                    {"id": "240101002", "name": "学生2", "regular": 91.0, "theory": 90.0, "skill": 0.0, "total": 91.0},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            result = run_script(GRADE / "scripts" / "validate_output.py", "--input-json", str(input_json), "--output-dir", str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("formula error", result.stderr)

    def test_student_count_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="grade-package-count-") as temp_name:
            folder = Path(temp_name)
            source = self.make_source(folder)
            output = folder / "output"
            result = run_script(GRADE / "scripts" / "generate_gradebook.py", "--source", str(source), "--output-dir", str(output))
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            output_file = next(output.glob("*.xls"))
            xlsx_dir = folder / "broken-xlsx"
            xlsx_dir.mkdir()
            subprocess.run([soffice_path(), "--headless", "--convert-to", "xlsx", "--outdir", str(xlsx_dir), str(output_file)], check=True, capture_output=True)
            xlsx = xlsx_dir / f"{output_file.stem}.xlsx"
            workbook = load_workbook(xlsx)
            workbook["平时成绩"].delete_rows(6, 1)
            workbook.save(xlsx)
            broken_dir = folder / "broken-xls"
            broken_dir.mkdir()
            subprocess.run([soffice_path(), "--headless", "--convert-to", "xls", "--outdir", str(broken_dir), str(xlsx)], check=True, capture_output=True)
            broken = broken_dir / f"{output_file.stem}.xls"
            output_file.unlink()
            broken.replace(output_file)
            input_json = folder / "input.json"
            input_json.write_text(json.dumps({
                "term": "2025-2026-2",
                "course": "软件测试实训",
                "teacher": "张老师",
                "class_name": "软件技术2401班",
                "weights": {"regular": 0.6, "theory": 0.4, "skill": 0.0},
                "students": [
                    {"id": "240101001", "name": "学生1", "regular": 86.5, "theory": 88.0, "skill": 0.0, "total": 87.0},
                    {"id": "240101002", "name": "学生2", "regular": 91.0, "theory": 90.0, "skill": 0.0, "total": 91.0},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            result = run_script(GRADE / "scripts" / "validate_output.py", "--input-json", str(input_json), "--output-dir", str(output))
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
