from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import copy
from decimal import Decimal
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
        bad["weights"] = {"regular": 0.5, "theory": 0.5, "skill": 0.5}
        with self.assertRaises(ValueError):
            validate_input(bad)
        with self.assertRaises(ValueError):
            validate_input({"course_name": "软件测试", "lessons": [{"unit": "", "task": "", "hours": "2"}]})
        with self.assertRaises(ValueError):
            validate_input({"course_name": "课" * 33, "lessons": [{"unit": "项目一", "task": "完成任务", "hours": "2"}]})

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
    ) -> Path:
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
