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
        with self.assertRaises(ValueError):
            validate_input({"course_name": "软件测试", "lessons": [{"unit": "", "task": "", "hours": "2"}]})
        with self.assertRaises(ValueError):
            validate_input({"course_name": "课" * 33, "lessons": [{"unit": "项目一", "task": "完成任务", "hours": "2"}]})

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


@unittest.skipUnless(soffice_path(), "LibreOffice is required for XLS package tests")
class GradebookTemplatePackageTests(unittest.TestCase):
    def make_source(self, folder: Path, skill: bool = False, count: int = 2, leading_zero: bool = False) -> Path:
        xlsx = folder / "课程成绩单.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "成绩单"
        regular_pct = 0.5 if skill else 0.6
        theory_pct = 0.3 if skill else 0.4
        skill_pct = 0.2 if skill else 0.0
        sheet["A2"] = f"课程名称:软件测试实训 教师:张老师 上课班级:软件技术2401班 成绩项目比例:技能成绩{int(skill_pct * 100)}% 理论成绩{int(theory_pct * 100)}% 平时成绩{int(regular_pct * 100)}%"
        sheet["A3"] = "开课学期:2025-2026-2"
        headers = ["学号", "姓名", "平时成绩", "理论成绩"] + (["技能成绩"] if skill else []) + ["总成绩"]
        for col, value in enumerate(headers, start=1):
            sheet.cell(4, col).value = value
        rows = []
        for index in range(count):
            regular = [86.5, 91.0, 100.0, 0.0][index % 4]
            theory = [88.0, 90.0, 100.0, 0.0][index % 4]
            skill_score = [92.0, 90.0, 100.0, 0.0][index % 4]
            total = round(regular * regular_pct + theory * theory_pct + skill_score * skill_pct)
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
            self.assertEqual(report["checks"]["students"][0]["id"], "0012345678")

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
