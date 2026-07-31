from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document
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
            for path in output.glob("*.docx"):
                self.assertEqual(len(Document(path).tables[0].rows), 30)

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


@unittest.skipUnless(soffice_path(), "LibreOffice is required for XLS package tests")
class GradebookTemplatePackageTests(unittest.TestCase):
    def make_source(self, folder: Path) -> Path:
        xlsx = folder / "课程成绩单.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "成绩单"
        sheet["A2"] = "课程名称:软件测试实训 教师:张老师 上课班级:软件技术2401班 成绩项目比例:技能成绩0% 理论成绩40% 平时成绩60%"
        sheet["A3"] = "开课学期:2025-2026-2"
        for col, value in enumerate(["学号", "姓名", "平时成绩", "理论成绩", "总成绩"], start=1):
            sheet.cell(4, col).value = value
        rows = [
            ["240101001", "张三", 86.5, 88.0, 87.0],
            ["240101002", "李四", 91.0, 90.0, 91.0],
        ]
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


if __name__ == "__main__":
    unittest.main()
