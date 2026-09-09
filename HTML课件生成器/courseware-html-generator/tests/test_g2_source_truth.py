from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from activity_time_reviewer import review_courseware_time  # noqa: E402
from source_truth_validator import validate_cross_material_consistency, validate_source_truth  # noqa: E402


def _csv_fact(expected: str = "C3") -> dict:
    return {
        "id": "fact-s002-sales-cell",
        "kind": "structured-data-fact",
        "statement": f"第二条数据记录的销售额单元格为 {expected}",
        "source_slide_ids": ["slide-data"],
        "learning_unit_ids": ["unit-data"],
        "evidence": [{
            "source_id": "sales.csv",
            "evidence_type": "structured-data",
            "locator": {"field": "sales", "data_row_index": 2, "worksheet_row": 3, "column_letter": "C"},
            "value": "200",
        }],
        "verification": {
            "level": 1,
            "status": "verified",
            "method": "csv-cell-address",
            "expected_value": expected,
            "token_family": "cell-address",
            "key_tokens": [expected],
        },
    }


def _courseware(fact: dict) -> dict:
    return {"canonical_facts": [fact], "slides": [{"id": "slide-data", "canonical_fact_ids": [fact["id"]], "speaker_script": fact["statement"]}]}


class SourceTruthTests(unittest.TestCase):
    def csv_root(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="g2-source-truth-"))
        (root / "sales.csv").write_text("id,name,sales\nS001,A,100\nS002,B,200\n", encoding="utf-8")
        return root

    def test_t1_csv_data_index_maps_to_worksheet_row_with_header_offset(self) -> None:
        root = self.csv_root()
        report = validate_source_truth(_courseware(_csv_fact()), root)
        self.assertEqual(report["status"], "pass", report)
        derived = report["facts"][0]["evidence"][0]["derived"]
        self.assertEqual(derived["data_row_index"], 2)
        self.assertEqual(derived["worksheet_row"], 3)

    def test_t2_wrong_cell_address_fails_without_a_fixture_specific_rule(self) -> None:
        root = self.csv_root()
        fact = _csv_fact("C2")
        report = validate_source_truth(_courseware(fact), root)
        self.assertEqual(report["status"], "fail", report)
        self.assertTrue(any("source derives" in error for error in report["errors"]), report)

    def test_t3_correct_cell_address_passes(self) -> None:
        report = validate_source_truth(_courseware(_csv_fact()), self.csv_root())
        self.assertEqual(report["status"], "pass", report)

    def test_t4_cross_material_fact_value_mismatch_fails(self) -> None:
        fact = _csv_fact()
        practice = {"tasks": [{"id": "task-1", "level": "core", "canonical_fact_ids": [fact["id"]], "overview": "第二条记录地址是 C2"}]}
        report = validate_cross_material_consistency(_courseware(fact), practice)
        self.assertEqual(report["status"], "fail", report)
        self.assertTrue(any("FACT_CONTRADICTION" in error for error in report["errors"]), report)

    def test_t5_speaker_script_fact_token_contradiction_fails(self) -> None:
        fact = _csv_fact()
        courseware = _courseware(fact)
        courseware["slides"][0]["speaker_script"] = "第二条记录的地址是 C2，而不是当前表格的其他位置。"
        report = validate_cross_material_consistency(courseware)
        self.assertEqual(report["status"], "fail", report)
        self.assertTrue(any("speaker_script" in error for error in report["errors"]), report)

    def test_t6_pedagogical_inference_does_not_need_deterministic_evidence(self) -> None:
        fact = {"id": "fact-learning-risk", "kind": "pedagogical-inference", "statement": "学生可能混淆两个相邻概念。", "verification": {"level": 4, "status": "inferred"}}
        report = validate_source_truth({"canonical_facts": [fact], "slides": []}, self.csv_root())
        self.assertEqual(report["status"], "pass", report)

    def test_t7_unverified_fact_used_by_core_fails(self) -> None:
        fact = _csv_fact()
        fact["verification"]["status"] = "unverified"
        report = validate_source_truth(_courseware(fact), self.csv_root())
        self.assertEqual(report["status"], "fail", report)
        self.assertTrue(any("unverified" in error for error in report["errors"]), report)

    def test_text_quote_and_simple_computed_fact_are_deterministic(self) -> None:
        root = self.csv_root()
        (root / "notes.md").write_text("路由规则把 URL 映射到视图函数。\n", encoding="utf-8")
        text_fact = {
            "id": "fact-route",
            "kind": "direct-textual-fact",
            "statement": "路由规则把 URL 映射到视图函数。",
            "evidence": [{"source_id": "notes.md", "evidence_type": "direct-text", "locator": {"line": 1}, "quote": "路由规则把 URL 映射到视图函数。"}],
            "verification": {"level": 2, "status": "source-supported", "method": "text-quote"},
        }
        computed = {
            "id": "fact-sales-total",
            "kind": "computed-fact",
            "statement": "销售额总计为 300。",
            "evidence": [{"source_id": "sales.csv", "evidence_type": "structured-data", "locator": {"field": "sales"}}],
            "verification": {"level": 1, "status": "verified", "method": "csv-sum", "expected_result": 300},
        }
        report = validate_source_truth({"canonical_facts": [text_fact, computed], "slides": []}, root)
        self.assertEqual(report["status"], "pass", report)

    def test_declared_numeric_fact_token_conflict_is_detected(self) -> None:
        fact = {
            "id": "fact-total",
            "kind": "computed-fact",
            "statement": "销售额总计为 300。",
            "evidence": [{"source_id": "sales.csv", "evidence_type": "structured-data", "locator": {"field": "sales"}}],
            "verification": {"level": 1, "status": "verified", "method": "csv-sum", "expected_result": 300, "token_family": "number", "key_tokens": ["300"]},
        }
        courseware = {"canonical_facts": [fact], "slides": [{"id": "s1", "canonical_fact_ids": [fact["id"],], "speaker_script": "销售额总计为 301，先检查你的计算。"}]}
        report = validate_cross_material_consistency(courseware)
        self.assertEqual(report["status"], "fail", report)
        self.assertTrue(any("301" in error for error in report["errors"]), report)


def _time_content(**overrides: object) -> dict:
    content = {
        "session_minutes": 8,
        "prepared_minutes": 8,
        "core_minutes": 8,
        "extension_minutes": 0,
        "slides": [{"id": "s1", "delivery_track": "core", "lecture_minutes": 0, "activity_minutes": 8, "suggested_minutes": 8}],
        "extensions": [],
    }
    content.update(overrides)
    return content


def _plan(segments: list[dict[str, object]], student_action: str = "独立计算并与同伴核对结果") -> dict:
    return {
        "type": "guided-practice",
        "teacher_prompt": "请先独立完成，再说明判断依据。",
        "student_action": student_action,
        "expected_artifact_or_response": "一行计算结果和一句判断依据",
        "check_method": "同伴核对后由教师抽查一份结果",
        "segments": segments,
    }


class TimeEvidenceTests(unittest.TestCase):
    def test_t8_activity_without_plan_fails(self) -> None:
        report = review_courseware_time(_time_content())
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("requires activity_plan" in error for error in report["errors"]), report)

    def test_t9_activity_segments_match_pass(self) -> None:
        content = _time_content()
        content["slides"][0]["activity_plan"] = _plan([{"label": "独立完成", "minutes": 3}, {"label": "同伴核对", "minutes": 2}, {"label": "教师讲评", "minutes": 3}])
        self.assertEqual(review_courseware_time(content)["status"], "PASS")

    def test_t10_activity_segment_mismatch_fails(self) -> None:
        content = _time_content()
        content["slides"][0]["activity_plan"] = _plan([{"label": "独立完成", "minutes": 3}])
        report = review_courseware_time(content)
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("approximately equal" in error for error in report["errors"]), report)

    def test_t11_simple_question_cannot_claim_eight_minutes(self) -> None:
        content = _time_content()
        content["slides"][0]["activity_plan"] = _plan([{"label": "思考", "minutes": 8}], "请思考")
        report = review_courseware_time(content)
        self.assertIn(report["status"], {"FAIL", "DEGRADED"}, report)

    def test_t12_core_and_real_extension_content_pass(self) -> None:
        content = _time_content(
            session_minutes=90,
            prepared_minutes=120,
            core_minutes=90,
            extension_minutes=30,
            slides=[{"id": "s1", "delivery_track": "core", "lecture_minutes": 90, "activity_minutes": 0, "suggested_minutes": 90}],
            extensions=[
                {"id": "e1", "title": "备用案例", "minutes": 10, "content": "比较两个边界案例", "activity": "小组比较并讲解", "use_when": "主线提前完成"},
                {"id": "e2", "title": "备用练习", "minutes": 20, "content": "完成一组迁移练习", "activity": "独立完成后教师抽查", "use_when": "学生需要巩固"},
            ],
        )
        self.assertEqual(review_courseware_time(content)["status"], "PASS")

    def test_t13_empty_extension_content_fails(self) -> None:
        content = _time_content(
            session_minutes=90,
            prepared_minutes=120,
            core_minutes=90,
            extension_minutes=30,
            slides=[{"id": "s1", "delivery_track": "core", "lecture_minutes": 90, "activity_minutes": 0, "suggested_minutes": 90}],
            extensions=[{"id": "e1", "title": "备用", "minutes": 30, "content": "", "activity": "", "use_when": ""}],
        )
        self.assertEqual(review_courseware_time(content)["status"], "FAIL")

    def test_t14_unplanned_activity_time_fails(self) -> None:
        content = _time_content(
            session_minutes=24,
            prepared_minutes=24,
            core_minutes=24,
            slides=[
                {"id": "s1", "lecture_minutes": 4, "activity_minutes": 8, "suggested_minutes": 12},
                {"id": "s2", "lecture_minutes": 4, "activity_minutes": 8, "suggested_minutes": 12},
            ],
        )
        report = review_courseware_time(content)
        self.assertEqual(report["status"], "FAIL", report)

    def test_t15_teacher_reserve_is_counted_as_real_extension(self) -> None:
        content = _time_content(
            session_minutes=90,
            prepared_minutes=120,
            core_minutes=90,
            extension_minutes=30,
            slides=[{"id": "s1", "lecture_minutes": 90, "activity_minutes": 0, "suggested_minutes": 90}],
            extensions=[{"id": "e1", "title": "备用内容", "minutes": 30, "content": "再做一个边界案例", "activity": "分组比较并汇报", "use_when": "讲得快时使用"}],
        )
        report = review_courseware_time(content)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["extension"]["content_minutes"], 30)


if __name__ == "__main__":
    unittest.main()
