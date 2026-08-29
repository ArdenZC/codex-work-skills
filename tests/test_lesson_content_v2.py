from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.table import _Cell


ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "教案生成器" / "lesson-plan-docx-generator"
SCRIPTS = LESSON / "scripts"
V10_TEMPLATE = LESSON / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx"
V110_TEMPLATE = LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "template.docx"
V112_TEMPLATE = LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "template.docx"
V112_MANIFEST = LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "manifest.yaml"
V111_TEMPLATE = LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.1" / "template.docx"
V111_MANIFEST = LESSON / "assets" / "templates" / "lesson-plan" / "v1.1.1" / "manifest.yaml"

sys.path.insert(0, str(SCRIPTS))
from bookmark_utils import (  # noqa: E402
    bookmark_boundary_locations,
    bookmark_parent_cell,
    bookmark_parent_paragraph,
    find_bookmark,
)
from content_contract import (  # noqa: E402
    format_evaluation_values,
    format_implementation,
    format_reflection,
    lesson_content_field_values,
    lesson_header_values,
)
from content_quality import ContentQualityError, assess_content_quality, validate_content_quality  # noqa: E402
import generate_lesson_plans as lesson_generator  # noqa: E402
from generate_lesson_plans import atomic_commit_candidate, atomic_commit_candidate_with_external_qa  # noqa: E402
import validate_output as lesson_output  # noqa: E402
from package_common import (  # noqa: E402
    field_bookmark,
    implementation_bookmarks,
    load_manifest,
    reflection_bookmarks,
    required_bookmarks,
    score_breakdown,
)
from path_safety import assert_output_path_safe, paths_overlap  # noqa: E402
from validate_output import manifest_field_text  # noqa: E402

# Keep the lesson modules above, but do not leave their generic import names
# cached for the sibling gradebook package, which has its own implementations.
for _module_name in ("package_common", "validate_output", "validate_template"):
    sys.modules.pop(_module_name, None)


def run_script(script: Path, *args: str) -> "subprocess.CompletedProcess[str]":
    import subprocess

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def load_fixture(name: str) -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


def write_payload(folder: Path, payload: dict, name: str = "tasks.json") -> Path:
    source = folder / name
    source.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return source


def document_text(document: Document) -> str:
    values = [paragraph.text for paragraph in document.paragraphs]

    def visit_table(table) -> None:
        for row in table.rows:
            for cell in row.cells:
                values.append(cell.text)
                for nested in cell.tables:
                    visit_table(nested)

    for table in document.tables:
        visit_table(table)
    for section in document.sections:
        values.append(section.header._element.text or "")
        values.append(section.footer._element.text or "")
    return "\n".join(values)


def bookmark_text(document: Document, name: str) -> str:
    record = find_bookmark(document, name)
    if record is None:
        raise AssertionError(f"missing bookmark {name}")
    cell_element = bookmark_parent_cell(document, record)
    if cell_element is not None:
        return _Cell(cell_element, document).text.strip()
    paragraph_element = bookmark_parent_paragraph(document, record)
    if paragraph_element is not None:
        return paragraph_element.text.strip()
    raise AssertionError(f"bookmark {name} has no text container")


class LessonContentV2Mixin:
    def test_sparse_input_fails_closed_through_real_generator(self) -> None:
        sparse = {
            "course_name": "软件测试实训",
            "lessons": [{"unit": "项目一 测试准备", "task": "完成环境检查", "hours": 2}],
        }
        with tempfile.TemporaryDirectory(prefix="lesson-v2-sparse-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, sparse)
            output = folder / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Legacy sparse lesson content is no longer accepted for production generation.",
                result.stderr,
            )
            self.assertIn("Regenerate tasks JSON using the Lesson Content V2 Skill workflow.", result.stderr)
            self.assertFalse(output.exists())

    def test_schema_and_classroom_time_contracts_fail_through_real_generator(self) -> None:
        cases = (
            ("missing-progression", lambda payload: payload["lessons"][0].pop("progression"), "Input schema validation failed"),
            ("missing-stage", lambda payload: payload["lessons"][0]["implementation"].pop(), "Input schema validation failed"),
            (
                "wrong-minutes",
                lambda payload: payload["lessons"][0]["implementation"][1].__setitem__("minutes", 11),
                "in-class implementation minutes must equal hours*45",
            ),
            ("empty-teaching-content", lambda payload: payload["lessons"][0].__setitem__("teaching_content", []), "Input schema validation failed"),
            (
                "future-prior",
                lambda payload: payload["lessons"][1]["progression"].__setitem__("prior_lesson_id", "L03"),
                "prior_lesson_id must reference an earlier lesson",
            ),
            (
                "self-prior",
                lambda payload: payload["lessons"][1]["progression"].__setitem__("prior_lesson_id", "L02"),
                "prior_lesson_id must reference an earlier lesson",
            ),
            (
                "unknown-prior",
                lambda payload: payload["lessons"][1]["progression"].__setitem__("prior_lesson_id", "missing"),
                "prior_lesson_id must reference an earlier lesson",
            ),
        )
        for label, mutate, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory(prefix=f"lesson-v2-contract-{label}-") as temp_name:
                folder = Path(temp_name)
                payload = load_fixture("lesson-plan-input.json")
                mutate(payload)
                source = write_payload(folder, payload)
                output = folder / "output"
                result = run_script(
                    LESSON / "scripts" / "generate_lesson_plans.py",
                    "--tasks-json",
                    str(source),
                    "--output-dir",
                    str(output),
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

    def test_evaluation_score_boundaries_use_half_point_contract(self) -> None:
        cases = ((84.5, False), (85, True), (85.5, True), (96, True), (96.5, False))
        with tempfile.TemporaryDirectory(prefix="lesson-v2-score-boundaries-") as temp_name:
            folder = Path(temp_name)
            for score, should_pass in cases:
                with self.subTest(score=score):
                    payload = load_fixture("lesson-plan-input.json")
                    payload["lessons"][0]["evaluation"]["score"] = score
                    source = write_payload(folder, payload, f"score-{str(score).replace('.', '_')}.json")
                    output = folder / f"output-{str(score).replace('.', '_')}"
                    result = run_script(
                        LESSON / "scripts" / "generate_lesson_plans.py",
                        "--tasks-json",
                        str(source),
                        "--output-dir",
                        str(output),
                    )
                    if should_pass:
                        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                        self.assertTrue((output / "qa-report.json").exists())
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("between 85 and 96 in 0.5-point increments", result.stderr)
                        self.assertFalse(output.exists())

    def test_content_quality_detects_real_failure_categories(self) -> None:
        base = load_fixture("lesson-plan-content-v2-it.json")
        cases = (
            (
                "exact student analysis",
                lambda data: data["lessons"][1]["student_analysis"].__setitem__(
                    "base", copy.deepcopy(data["lessons"][0]["student_analysis"]["base"])
                ),
                lambda report: any(item["field"] == "student_analysis.base" for item in report["exact_duplicates"]),
            ),
            (
                "similar reflection",
                lambda data: data["lessons"][1]["reflection"].__setitem__(
                    "summary",
                    data["lessons"][0]["reflection"]["summary"][:-5] + "并补充接口证据分析。",
                ),
                lambda report: any(item["field"] == "reflection.summary" for item in report["field_similarity_pairs"]),
            ),
            (
                "implementation duplicate",
                lambda data: [
                    lesson["implementation"][1]["teacher_actions"].__setitem__(
                        slice(None), ["教师根据本课任务检查需求依据并追问关键证据"]
                    )
                    for lesson in data["lessons"][:3]
                ],
                lambda report: any("task_introduction.teacher_actions" in item["field"] for item in report["implementation_duplicates"]),
            ),
            (
                "repeated sentence",
                lambda data: [
                    lesson["teaching_content"].__setitem__(
                        0, "学生按照任务清单核对关键证据并记录判定依据"
                    )
                    for lesson in data["lessons"][:3]
                ],
                lambda report: bool(report["repeated_sentences"]),
            ),
            (
                "old boilerplate",
                lambda data: data["lessons"][0]["reflection"].__setitem__(
                    "summary", data["lessons"][0]["reflection"]["summary"] + "任务驱动、教师示范、分组实训、过程评价"
                ),
                lambda report: bool(report["boilerplate_hits"]),
            ),
            (
                "identical progression",
                lambda data: [lesson["progression"].__setitem__("capability_stage", "独立") for lesson in data["lessons"]],
                lambda report: not report["progression"]["valid_variety"],
            ),
            (
                "simple score pattern",
                lambda data: [lesson["evaluation"].__setitem__("score", 90) for lesson in data["lessons"]],
                lambda report: report["coverage"]["score_pattern"]["all_same"],
            ),
        )
        for label, mutate, assertion in cases:
            with self.subTest(case=label):
                payload = copy.deepcopy(base)
                mutate(payload)
                report = assess_content_quality(payload)
                self.assertEqual(report["status"], "failed")
                self.assertTrue(assertion(report), report)

    def test_content_quality_calibration_rejects_copy_rewrites_but_allows_real_difference(self) -> None:
        base = load_fixture("lesson-plan-content-v2-it.json")

        def recursive_replace(value, replacements):
            if isinstance(value, str):
                for old, new in replacements:
                    value = value.replace(old, new)
                return value
            if isinstance(value, list):
                return [recursive_replace(item, replacements) for item in value]
            if isinstance(value, dict):
                return {key: recursive_replace(item, replacements) for key, item in value.items()}
            return value

        def copied_pair() -> dict:
            data = copy.deepcopy(base)
            data["lessons"] = data["lessons"][:2]
            data["total_hours"] = 4
            data["lessons"][1] = copy.deepcopy(data["lessons"][0])
            data["lessons"][1]["lesson_id"] = "L02"
            data["lessons"][1]["unit"] = "项目二 数据边界分析"
            data["lessons"][1]["task"] = "设计字段边界用例"
            data["lessons"][1]["progression"]["prior_lesson_id"] = "L01"
            data["lessons"][1]["evaluation"]["score"] = 90
            return data

        cases = (
            ("copy+task rename", lambda data: None, "adjacent_similarity_pairs"),
            (
                "10 percent wording",
                lambda data: data["lessons"].__setitem__(
                    1,
                    recursive_replace(data["lessons"][1], [("测试", "检验")]),
                ),
                "field_similarity_pairs",
            ),
            (
                "20 percent wording",
                lambda data: data["lessons"].__setitem__(
                    1,
                    recursive_replace(
                        data["lessons"][1],
                        [("测试", "检验"), ("记录", "登记"), ("检查", "核验"), ("证据", "依据"), ("任务", "项目任务")],
                    ),
                ),
                "adjacent_similarity_pairs",
            ),
            (
                "synonym and word order",
                lambda data: data["lessons"].__setitem__(
                    1,
                    recursive_replace(
                        data["lessons"][1],
                        [
                            ("完成环境检查并留下可追溯证据", "留下可追溯证据并完成环境核验"),
                            ("依据需求边界安排测试任务", "按需求边界编排检验任务"),
                            ("核验工具版本、账号权限与测试数据", "复核工具版本、账户权限以及检验数据"),
                        ],
                    ),
                ),
                "adjacent_similarity_pairs",
            ),
            (
                "same flow with renamed nouns",
                lambda data: data["lessons"].__setitem__(
                    1,
                    recursive_replace(
                        data["lessons"][1],
                        [("环境", "接口"), ("配置", "请求"), ("风险", "异常"), ("测试", "验证")],
                    ),
                ),
                "adjacent_similarity_pairs",
            ),
        )
        for label, mutate, expected_category in cases:
            with self.subTest(case=label):
                payload = copied_pair()
                mutate(payload)
                report = assess_content_quality(payload)
                self.assertEqual(report["status"], "failed", report)
                self.assertTrue(report[expected_category], report)
                for record in report[expected_category]:
                    self.assertEqual(len(record["lessons"]), 2)
                    self.assertIn("score", record)
                    self.assertIn("top_fragments", record)

        distinct = copy.deepcopy(base)
        distinct["lessons"] = distinct["lessons"][:2]
        distinct["total_hours"] = 4
        distinct_report = assess_content_quality(distinct)
        self.assertEqual(distinct_report["status"], "passed", distinct_report)
        thresholds = distinct_report["coverage"]["similarity_thresholds"]
        self.assertLess(thresholds["adjacent_whole_lesson"], thresholds["whole_lesson"])
        self.assertLess(thresholds["adjacent_field"], thresholds["field"])

    def test_content_quality_checks_expanded_fields_and_adjacent_implementation(self) -> None:
        base = load_fixture("lesson-plan-content-v2-it.json")

        def pair() -> dict:
            data = copy.deepcopy(base)
            data["lessons"] = data["lessons"][:2]
            data["total_hours"] = 4
            return data

        field_paths = (
            ("teaching_content", ("teaching_content",)),
            ("goals.knowledge", ("goals", "knowledge")),
            ("goals.ability", ("goals", "ability")),
            ("goals.quality", ("goals", "quality")),
            ("teaching_methods", ("teaching_methods",)),
            ("progression.prior_learning", ("progression", "prior_learning")),
            ("progression.deliverable", ("progression", "deliverable")),
            ("progression.next_bridge", ("progression", "next_bridge")),
        )
        for field_name, path in field_paths:
            with self.subTest(field=field_name):
                data = pair()
                left = data["lessons"][0]
                right = data["lessons"][1]
                source = left
                target = right
                for part in path[:-1]:
                    source = source[part]
                    target = target[part]
                target[path[-1]] = copy.deepcopy(source[path[-1]])
                report = assess_content_quality(data)
                self.assertTrue(
                    any(item["field"] == field_name for item in report["exact_duplicates"]),
                    (field_name, report),
                )

        data = pair()
        data["lessons"][1]["implementation"] = copy.deepcopy(data["lessons"][0]["implementation"])
        report = assess_content_quality(data)
        self.assertEqual(report["status"], "failed", report)
        self.assertTrue(report["adjacent_implementation_exact_duplicates"], report)
        self.assertTrue(
            any(
                item["stage"] == "task_introduction"
                and item["lessons"] == ["L01", "L02"]
                for item in report["implementation_similarity_pairs"]
            ),
            report,
        )

    def test_progression_coherence_and_score_calibration_are_deterministic(self) -> None:
        base = load_fixture("lesson-plan-content-v2-it.json")
        connected = copy.deepcopy(base)
        connected["lessons"] = connected["lessons"][:2]
        connected["total_hours"] = 4
        connected_report = assess_content_quality(connected)
        self.assertEqual(connected_report["progression"]["status"], "passed", connected_report)
        self.assertTrue(all(link["status"] == "passed" for link in connected_report["progression"]["links"]))

        boundary = copy.deepcopy(connected)
        boundary["lessons"][1]["unit"] = "项目二 测试执行与交付"
        boundary_report = assess_content_quality(boundary)
        self.assertEqual(boundary_report["progression"]["status"], "passed", boundary_report)
        self.assertFalse(boundary_report["progression"]["links"][0]["same_unit"])
        self.assertGreater(boundary_report["progression"]["links"][0]["threshold"], 0)

        disconnected = copy.deepcopy(base)
        disconnected["lessons"][1]["progression"].update(
            {
                "prior_learning": "完全转入园艺种植的病虫害防治",
                "deliverable": "灌溉阈值记录",
                "next_bridge": "进入植物病害观察",
            }
        )
        disconnected["lessons"][1]["task"] = "完成温室灌溉控制"
        disconnected["lessons"][1]["teaching_content"] = [
            "识别土壤湿度传感器",
            "配置灌溉阈值",
            "形成园艺控制记录",
        ]
        disconnected_report = assess_content_quality(disconnected)
        self.assertEqual(disconnected_report["progression"]["links"][0]["status"], "failed", disconnected_report)
        self.assertGreater(disconnected_report["progression"]["links"][0]["threshold"], 0)

        arithmetic = copy.deepcopy(base)
        for lesson, score in zip(arithmetic["lessons"], (88, 88.5, 89, 89.5, 90, 90.5)):
            lesson["evaluation"]["score"] = score
        arithmetic_report = assess_content_quality(arithmetic)
        self.assertTrue(arithmetic_report["coverage"]["score_pattern"]["arithmetic_progression"])
        self.assertEqual(arithmetic_report["status"], "failed")

        natural = copy.deepcopy(base)
        for lesson, score in zip(natural["lessons"], (88.5, 90, 89.5, 91, 90.5, 92)):
            lesson["evaluation"]["score"] = score
        natural_report = assess_content_quality(natural)
        self.assertFalse(natural_report["coverage"]["score_pattern"]["arithmetic_progression"])
        self.assertEqual(natural_report["status"], "passed", natural_report)

    def test_content_quality_failure_is_reported_by_real_output_validator(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        with tempfile.TemporaryDirectory(prefix="lesson-v2-output-quality-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            broken = copy.deepcopy(payload)
            broken["lessons"][1]["student_analysis"]["base"] = copy.deepcopy(
                broken["lessons"][0]["student_analysis"]["base"]
            )
            broken_source = write_payload(folder, broken, "broken-tasks.json")
            result = run_script(
                LESSON / "scripts" / "validate_output.py",
                "--input-json",
                str(broken_source),
                "--output-dir",
                str(output),
            )
            self.assertNotEqual(result.returncode, 0)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["content_quality"]["status"], "failed")
            self.assertTrue(report["content_quality"]["exact_duplicates"])
            self.assertTrue(any("student_analysis.base" in error for error in report["content_quality"]["errors"]))

    def test_distinct_it_and_non_it_fixtures_generate_without_contamination(self) -> None:
        fixtures = (
            "lesson-plan-content-v2-it.json",
            "lesson-plan-content-v2-non-it.json",
        )
        with tempfile.TemporaryDirectory(prefix="lesson-v2-cross-domain-") as temp_name:
            folder = Path(temp_name)
            for fixture_name in fixtures:
                output = folder / Path(fixture_name).stem
                result = run_script(
                    LESSON / "scripts" / "generate_lesson_plans.py",
                    "--tasks-json",
                    str(ROOT / "tests" / "fixtures" / fixture_name),
                    "--output-dir",
                    str(output),
                )
                self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "passed")
                self.assertEqual(report["content_quality"]["status"], "passed")
                self.assertEqual(report["content_quality"]["coverage"]["non_it_contamination"], [])
                self.assertEqual(len(list(output.glob("*.docx"))), 6)
                if "non-it" in fixture_name:
                    text = "\n".join(document_text(Document(path)) for path in output.glob("*.docx"))
                    for term in ("软件技术", "标准机房", "脚本", "截图工具", "代码编辑器", "数据安全"):
                        self.assertNotIn(term, text)
                    for term in ("工程伦理", "平凡又不平凡的价值观"):
                        self.assertNotIn(term, text)
                    for term in ("职业伦理", "职业价值观"):
                        self.assertIn(term, text)

    def test_writer_uses_v2_values_and_keeps_internal_qa_out_of_docx(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        manifest = load_manifest(V111_MANIFEST)

        with tempfile.TemporaryDirectory(prefix="lesson-v2-writer-fidelity-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for path, lesson in zip(sorted(output.glob("*.docx")), payload["lessons"]):
                document = Document(path)
                table = document.tables[0]
                for name, expected in lesson_header_values(payload, lesson).items():
                    self.assertEqual(bookmark_text(document, field_bookmark(manifest, name)), expected)
                for name, expected in lesson_content_field_values(lesson).items():
                    self.assertEqual(bookmark_text(document, field_bookmark(manifest, name)), expected)
                for group, expected_values in zip(implementation_bookmarks(manifest), format_implementation(lesson["implementation"])):
                    for name, expected in zip(group, expected_values.values()):
                        self.assertEqual(bookmark_text(document, name), expected)
                for name, expected in zip(reflection_bookmarks(manifest), format_reflection(lesson["reflection"])):
                    self.assertEqual(bookmark_text(document, name), expected)
                nested = table.cell(12, 1).tables[0]
                for row_index, expected_values in enumerate(
                    format_evaluation_values(lesson, score_breakdown(lesson["evaluation"]["score"])),
                    start=1,
                ):
                    for cell_index, expected in expected_values.items():
                        self.assertEqual(nested.cell(row_index, cell_index).text.strip(), expected)
                text = document_text(document)
                for internal in ("Content V2", "similarity", "confidence", "source provenance", "资料不足", "根据现有资料推断"):
                    self.assertNotIn(internal, text)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["content_contract_version"], "2.0")
            self.assertEqual(report["content_quality"]["status"], "passed")
            self.assertEqual(report["content_quality"]["coverage"]["non_it_contamination"], [])

    def test_references_require_provenance_without_writing_metadata_to_docx(self) -> None:
        base = load_fixture("lesson-plan-input.json")
        cases = (
            ("generic", "课程配套教学资源", "generic", True),
            ("provided", "《软件测试基础》作者甲，某出版社，2024年第2版", "provided", True),
            ("generic-isbn", "《软件测试基础》ISBN 978-7-0000-0000-0", "generic", False),
            ("generic-standard", "GB/T 0000-2024 软件测试规范", "generic", False),
            ("generic-author", "作者甲 某出版社 软件测试教材", "generic", False),
        )
        for label, text, source_kind, should_pass in cases:
            with self.subTest(reference=label):
                payload = copy.deepcopy(base)
                payload["lessons"][0]["references"] = [{"text": text, "source_kind": source_kind}]
                try:
                    lesson_generator.validate_content_v2_input(payload)
                except ValueError:
                    self.assertFalse(should_pass)
                else:
                    self.assertTrue(should_pass)

        with tempfile.TemporaryDirectory(prefix="lesson-v2-reference-docx-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, base)
            output = folder / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = "\n".join(document_text(Document(path)) for path in output.glob("*.docx"))
            self.assertNotIn("source_kind", text)
            self.assertNotIn("generic", text)

    def test_external_qa_report_is_committed_with_output_and_preflight_is_fail_closed(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        with tempfile.TemporaryDirectory(prefix="lesson-v2-external-qa-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            external = folder / "reports" / "qa-report.json"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--qa-report",
                str(external),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(external.is_file())
            internal_report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            external_report = json.loads(external.read_text(encoding="utf-8"))
            self.assertEqual(internal_report["status"], "passed")
            self.assertEqual(external_report["status"], "passed")
            self.assertEqual(external_report["qa_report"], str(external.resolve()))

            for label in ("output-descendant", "source"):
                with self.subTest(path=label):
                    bad_output = folder / f"bad-{label}"
                    qa_path = bad_output / "nested" / "qa.json" if label == "output-descendant" else source
                    failed = run_script(
                        LESSON / "scripts" / "generate_lesson_plans.py",
                        "--tasks-json",
                        str(source),
                        "--output-dir",
                        str(bad_output),
                        "--qa-report",
                        str(qa_path),
                    )
                    self.assertNotEqual(failed.returncode, 0)
                    self.assertIn("external qa report", failed.stderr.lower())
                    self.assertFalse(bad_output.exists())

    def test_external_qa_transaction_rolls_back_output_and_report_on_each_exchange_failure(self) -> None:
        for label, fail_calls in (
            ("output-commit", {2}),
            ("external-commit", {4}),
            ("external-backup", {3}),
        ):
            with self.subTest(failure=label), tempfile.TemporaryDirectory(prefix=f"lesson-v2-atomic-{label}-") as temp_name:
                folder = Path(temp_name)
                output = folder / "output"
                output.mkdir()
                (output / "old.txt").write_bytes(b"old-output")
                external = folder / "qa-report.json"
                external.write_bytes(b"old-qa")
                candidate = folder / "candidate"
                candidate.mkdir()
                (candidate / "new.txt").write_bytes(b"new-output")
                external_candidate = folder / "qa-candidate.tmp"
                external_candidate.write_bytes(b"new-qa")
                real_replace = os.replace
                calls = {"count": 0}

                def fail_selected(source, target):
                    calls["count"] += 1
                    if calls["count"] in fail_calls:
                        raise OSError(f"injected {label} failure")
                    return real_replace(source, target)

                with patch.object(lesson_generator.os, "replace", side_effect=fail_selected):
                    with self.assertRaises(OSError):
                        atomic_commit_candidate_with_external_qa(
                            candidate,
                            output,
                            external_candidate,
                            external,
                            backup_existing=True,
                        )
                self.assertEqual((output / "old.txt").read_bytes(), b"old-output")
                self.assertEqual(external.read_bytes(), b"old-qa")
                self.assertFalse((output / "new.txt").exists())
                self.assertEqual(list(folder.glob("_output_backup_*")), [])
                self.assertEqual(list(folder.glob("_qa-report.json_backup_*")), [])
                shutil.rmtree(candidate, ignore_errors=True)
                external_candidate.unlink(missing_ok=True)

    def test_external_qa_transaction_reports_rollback_failure_and_main_cleans_temp_candidate(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        with tempfile.TemporaryDirectory(prefix="lesson-v2-external-rollback-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            external = folder / "reports" / "qa.json"
            first = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--qa-report",
                str(external),
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            before_output = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            before_qa = external.read_bytes()
            with patch.object(lesson_generator.tempfile, "mkstemp", side_effect=OSError("injected external temp write failure")):
                argv = [
                    "generate_lesson_plans.py",
                    "--tasks-json",
                    str(source),
                    "--output-dir",
                    str(output),
                    "--qa-report",
                    str(external),
                    "--backup-existing",
                ]
                with patch.object(sys, "argv", argv):
                    with self.assertRaisesRegex(OSError, "external temp write failure"):
                        lesson_generator.main()
            after_output = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(before_output, after_output)
            self.assertEqual(before_qa, external.read_bytes())
            self.assertEqual(list(folder.rglob("*.candidate-*")), [])
            self.assertEqual(list(folder.rglob("*_backup_*")), [])

            candidate = folder / "candidate"
            candidate.mkdir()
            (candidate / "new.txt").write_bytes(b"new")
            external_candidate = folder / "qa-candidate.tmp"
            external_candidate.write_bytes(b"new-qa")
            real_replace = os.replace
            calls = {"count": 0}

            def fail_commit_and_rollback(source_path, target_path):
                calls["count"] += 1
                if calls["count"] in {4, 5}:
                    raise OSError("injected rollback failure")
                return real_replace(source_path, target_path)

            with patch.object(lesson_generator.os, "replace", side_effect=fail_commit_and_rollback):
                with self.assertRaisesRegex(RuntimeError, "rollback failed"):
                    atomic_commit_candidate_with_external_qa(
                        candidate,
                        output,
                        external_candidate,
                        external,
                        backup_existing=True,
                    )
            self.assertEqual(
                {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()},
                before_output,
            )
            self.assertFalse(external.exists())
            shutil.rmtree(candidate, ignore_errors=True)
            external_candidate.unlink(missing_ok=True)
            for path in folder.glob("_*_backup_*"):
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)

    def test_content_failure_preserves_existing_output_and_cleans_candidate(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        with tempfile.TemporaryDirectory(prefix="lesson-v2-transaction-quality-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            first = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            before = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            broken = copy.deepcopy(payload)
            broken["lessons"][1]["student_analysis"]["base"] = copy.deepcopy(
                broken["lessons"][0]["student_analysis"]["base"]
            )
            broken_source = write_payload(folder, broken, "broken.json")
            failed = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(broken_source),
                "--output-dir",
                str(output),
                "--backup-existing",
            )
            self.assertNotEqual(failed.returncode, 0)
            after = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(list(folder.glob(".output.candidate-*")), [])
            self.assertEqual(list(folder.glob("_output_backup_*")), [])

    def test_atomic_commit_restores_existing_directory_on_exchange_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-v2-transaction-commit-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            output.mkdir()
            (output / "old.txt").write_bytes(b"old")
            candidate = folder / "candidate"
            candidate.mkdir()
            (candidate / "new.txt").write_bytes(b"new")
            real_replace = os.replace
            calls = {"count": 0}

            def fail_second_replace(source: str, target: str) -> None:
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("injected candidate exchange failure")
                real_replace(source, target)

            with patch("generate_lesson_plans.os.replace", side_effect=fail_second_replace):
                with self.assertRaises(OSError):
                    atomic_commit_candidate(candidate, output, backup_existing=True)
            self.assertEqual((output / "old.txt").read_bytes(), b"old")
            self.assertFalse((output / "new.txt").exists())
            shutil.rmtree(candidate)
            for path in folder.glob("_output_backup_*"):
                shutil.rmtree(path, ignore_errors=True)

    def test_atomic_commit_preserves_existing_directory_when_backup_move_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-v2-transaction-backup-") as temp_name:
            folder = Path(temp_name)
            output = folder / "output"
            output.mkdir()
            (output / "old.txt").write_bytes(b"old")
            candidate = folder / "candidate"
            candidate.mkdir()
            (candidate / "new.txt").write_bytes(b"new")

            def fail_replace(_source: str, _target: str) -> None:
                raise OSError("injected backup move failure")

            with patch("generate_lesson_plans.os.replace", side_effect=fail_replace):
                with self.assertRaises(OSError):
                    atomic_commit_candidate(candidate, output, backup_existing=True)
            self.assertEqual((output / "old.txt").read_bytes(), b"old")
            self.assertTrue((candidate / "new.txt").exists())
            shutil.rmtree(candidate)

    def test_generation_midway_failure_never_commits_candidate(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        with tempfile.TemporaryDirectory(prefix="lesson-v2-transaction-generation-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            output.mkdir()
            (output / "old.txt").write_bytes(b"old")
            before = (output / "old.txt").read_bytes()
            original_build = lesson_generator.build_lesson
            calls = {"count": 0}

            def fail_on_second(*args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise RuntimeError("injected generation failure")
                return original_build(*args, **kwargs)

            argv = [
                "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--backup-existing",
            ]
            with patch.object(lesson_generator, "build_lesson", side_effect=fail_on_second):
                with patch.object(sys, "argv", argv):
                    with self.assertRaises(RuntimeError):
                        lesson_generator.main()
            self.assertEqual((output / "old.txt").read_bytes(), before)
            self.assertEqual(list(folder.glob(".output.candidate-*")), [])
            self.assertEqual(list(folder.glob("_output_backup_*")), [])

    def test_output_qa_failure_never_commits_candidate(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        with tempfile.TemporaryDirectory(prefix="lesson-v2-transaction-output-qa-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            output.mkdir()
            (output / "old.txt").write_bytes(b"old")
            argv = [
                "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--backup-existing",
            ]
            with patch.object(lesson_generator, "validate_outputs", side_effect=RuntimeError("injected output QA failure")):
                with patch.object(sys, "argv", argv):
                    with self.assertRaisesRegex(RuntimeError, "output QA failure"):
                        lesson_generator.main()
            self.assertEqual((output / "old.txt").read_bytes(), b"old")
            self.assertEqual(list(folder.glob(".output.candidate-*")), [])
            self.assertEqual(list(folder.glob("_output_backup_*")), [])

    def test_render_failure_is_reported_without_being_hidden(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        manifest = load_manifest(V112_MANIFEST)
        with tempfile.TemporaryDirectory(prefix="lesson-v2-render-failure-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            output = folder / "output"
            generated = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            failed_render = {
                "status": "failed",
                "reason": "injected renderer failure",
                "renderer": "injected",
                "files_checked": 2,
                "errors": ["lesson document did not render"],
            }
            with patch.object(lesson_output, "render_docx_directory", return_value=failed_render):
                with self.assertRaisesRegex(RuntimeError, "render QA"):
                    lesson_output.validate_output_dir(
                        output,
                        payload,
                        manifest,
                        output / "qa-report.json",
                        LESSON / "schemas" / "lesson-plan-input.schema.json",
                        template_path=V112_TEMPLATE,
                        render=True,
                    )
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["render"]["status"], "failed")
            self.assertEqual(report["render"]["errors"], failed_render["errors"])

    def test_path_safety_rejects_protected_real_cli_paths_and_allows_sibling(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        with tempfile.TemporaryDirectory(prefix="lesson-v2-paths-") as temp_name:
            folder = Path(temp_name)
            source = write_payload(folder, payload)
            protected_result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(LESSON),
            )
            self.assertNotEqual(protected_result.returncode, 0)
            self.assertIn("protected path", protected_result.stderr.lower())

            collision_result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(source),
            )
            self.assertNotEqual(collision_result.returncode, 0)
            self.assertIn("protected path", collision_result.stderr.lower())

            sibling = folder / "safe-output"
            safe_result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(sibling),
            )
            self.assertEqual(safe_result.returncode, 0, safe_result.stderr)
            self.assertTrue((sibling / "qa-report.json").exists())

    def test_path_safety_detects_symlink_overlap_when_supported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-v2-symlink-") as temp_name:
            folder = Path(temp_name)
            alias = folder / "skill-alias"
            try:
                alias.symlink_to(LESSON, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable in this Windows environment")
            self.assertTrue(paths_overlap(alias / "output", LESSON))
            with self.assertRaises(ValueError):
                assert_output_path_safe(alias / "output", [LESSON])

    def test_render_report_is_real_or_explicitly_not_executed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lesson-v2-render-") as temp_name:
            folder = Path(temp_name)
            source = ROOT / "tests" / "fixtures" / "lesson-plan-input.json"
            output = folder / "output"
            result = run_script(
                LESSON / "scripts" / "generate_lesson_plans.py",
                "--tasks-json",
                str(source),
                "--output-dir",
                str(output),
                "--render",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output / "qa-report.json").read_text(encoding="utf-8"))
            self.assertIn(report["render"]["status"], {"passed", "not_executed"})
            self.assertEqual(report["render"]["scope"], "smoke")
            self.assertEqual(report["visual_inspection"]["status"], "not_executed")
            if report["render"]["status"] == "passed":
                self.assertEqual(report["render"]["files_checked"], 2)
                self.assertGreater(report["render"]["page_count"], 0)
                self.assertEqual(report["render"]["reason"], "LibreOffice render smoke passed")
            self.assertEqual(list(output.glob("*.pdf")), [])

    def test_template_binaries_keep_master_hashes(self) -> None:
        def digest(path: Path) -> str:
            value = hashlib.sha256()
            value.update(path.read_bytes())
            return value.hexdigest().upper()

        self.assertEqual(digest(V10_TEMPLATE), "11783108468204DD67C9F8EAA1543B67279361ECC842A8B37F8541BDD01D16D5")
        self.assertEqual(digest(V110_TEMPLATE), "5139D6C0D48E6BA23991D4415BD1D7ED594913010B19DACC37415E946A65DE8B")
        self.assertEqual(digest(V111_TEMPLATE), "569B076DE30CD64172EE86F2123C8AE5EA67828F46B51C4280FE32DAF6DE1AD0")
        self.assertEqual(digest(V112_TEMPLATE), "6FFAFA579D3AACBC535BA624D0A6A766644868B0AF1FCE6AC37B20BA8F3D8FC1")

    def test_v112_is_a_visible_text_patch_with_identical_semantic_anchors(self) -> None:
        old_document = Document(V111_TEMPLATE)
        new_document = Document(V112_TEMPLATE)
        old_text = document_text(old_document)
        new_text = document_text(new_document)
        self.assertIn("平凡又不平凡的价值观", old_text)
        self.assertIn("工程伦理", old_text)
        self.assertNotIn("平凡又不平凡的价值观", new_text)
        self.assertNotIn("工程伦理", new_text)
        self.assertIn("职业价值观", new_text)
        self.assertIn("职业伦理", new_text)

        old_manifest = load_manifest(V111_MANIFEST)
        new_manifest = load_manifest(V112_MANIFEST)
        old_names = required_bookmarks(old_manifest)
        self.assertEqual(old_names, required_bookmarks(new_manifest))
        for name in old_names:
            old_record = find_bookmark(old_document, name)
            new_record = find_bookmark(new_document, name)
            self.assertIsNotNone(old_record)
            self.assertIsNotNone(new_record)
            self.assertEqual(old_record.bookmark_id, new_record.bookmark_id)
            self.assertEqual(
                bookmark_boundary_locations(old_document, name),
                bookmark_boundary_locations(new_document, name),
            )

        result = run_script(
            LESSON / "scripts" / "validate_template.py",
            "--template",
            str(V112_TEMPLATE),
            "--manifest",
            str(V112_MANIFEST),
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["template_version"], "1.1.2")
        self.assertEqual(report["checks"]["visible_text_replacements"][0]["from"], "平凡又不平凡的价值观")
        self.assertEqual(report["errors"], [])

    def test_density_failure_reports_actual_chars_and_limit_without_truncation(self) -> None:
        payload = load_fixture("lesson-plan-input.json")
        payload["lessons"] = [payload["lessons"][0]]
        payload["total_hours"] = 2
        payload["lessons"][0]["teaching_content"] = [
            f"教学内容{i}：围绕测试范围、证据链和交付要求展开" * 8
            for i in range(8)
        ]
        manifest = load_manifest(V111_MANIFEST)
        report = assess_content_quality(payload, manifest)
        self.assertEqual(report["status"], "failed")
        teaching_errors = [item for item in report["density_errors"] if item["field"] == "teaching_content"]
        self.assertTrue(teaching_errors)
        self.assertGreater(teaching_errors[0]["actual_chars"], teaching_errors[0]["limit"])
        self.assertTrue(any("actual_chars=" in message and "limit=" in message for message in report["errors"]))
        with self.assertRaises(ContentQualityError):
            validate_content_quality(payload, manifest)
