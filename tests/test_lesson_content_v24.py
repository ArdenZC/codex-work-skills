from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "教案生成器" / "lesson-plan-docx-generator"
SCRIPTS = SKILL / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from content_contract import DELIVERY_MODES, expected_lesson_coverage_hours, reference_source_binding_errors
from generation_evidence import validate_generation_evidence
from lesson_acceptance import _generation_evidence_gate
from package_common import canonical_json_sha256, content_digest_rollup, lesson_agent_content
from project_merge import validate_project_merge
from tests.test_lesson_content_v22 import _refresh_review_digests
from tests.test_lesson_content_v23 import _base_payload, _bind_v23, _outline_row, _task
from tests.test_lesson_content_v2 import lesson_generator


DIMENSIONS = [
    "source_truth_alignment", "learner_analysis", "objective_quality", "content_selection",
    "key_difficult_point_resolution", "teacher_action_quality", "student_cognitive_activity",
    "learning_evidence", "objective_activity_evidence_assessment_alignment", "authentic_vocational_context",
    "differentiation_scaffold", "interaction_deep_learning", "assessment_quality", "progression_capacity",
    "teacher_usability",
]


def make_v24_payload(*, mode: str, theory_hours: int, practice_hours: int, workorders: bool = False) -> dict:
    total = theory_hours + practice_hours
    count = total // 2 + bool(total % 2)
    payload = _base_payload(theory_hours=total, lesson_count=count)
    # Build a legacy 2.3 carrier first, then explicitly author Content 2.4.
    carrier_mode = "integrated_lessons" if workorders and practice_hours else "theory_only"
    links = None
    if workorders:
        practical_ids = [item["lesson_id"] for item in payload["lessons"][-(practice_hours // 2):]]
        links = [[lesson_id] for lesson_id in practical_ids]
    _bind_v23(
        payload,
        mode=carrier_mode,
        theory_hours=theory_hours,
        practice_hours=practice_hours,
        workorders=workorders,
        task_links=links,
    )
    payload["content_contract_version"] = "2.4"
    payload["course_case_facts_sha256"] = hashlib.sha256(b"synthetic-contract-test-shared-case-facts").hexdigest().upper()
    payload["delivery_plan"]["mode"] = mode
    payload["confirmed_course_info"]["delivery_mode"] = mode
    payload["artifact_plan"]["lesson_plans"] = True
    payload["reference_pool"] = []
    for index, lesson in enumerate(payload["lessons"]):
        if mode == "theory_only" or index < theory_hours // 2:
            lesson.update(lesson_type="theory", hours=2, theory_hours=2, practice_hours=0)
        else:
            lesson.update(lesson_type="practice", hours=2, theory_hours=0, practice_hours=2)
        lesson["practice_task_ids"] = []
        lesson["reference_ids"] = []
    if workorders:
        contract = payload["practice_task_contract"]
        contract["course_profile"]["delivery_mode"] = mode
        practical_lessons = [lesson for lesson in payload["lessons"] if lesson["lesson_type"] == "practice"]
        for index, lesson in enumerate(practical_lessons):
            task_id = f"PT-{index + 1:02d}"
            contract["tasks"][index]["task_id"] = task_id
            contract["tasks"][index]["lesson_ids"] = [lesson["lesson_id"]]
            lesson["practice_task_ids"] = [task_id]
    else:
        payload.pop("practice_task_contract", None)
    payload["outline"] = [_outline_row(item) for item in payload["lessons"]]
    payload["reference_research"] = {
        "status": "searched_no_reliable_source",
        "note": "Synthetic contract test; queries executed but no source claim is made.",
        "queries": [{
            "query_id": "Q-ZH-01", "query": "高职 数据结构课程 项目教学 公开教材检索",
            "language": "zh", "lesson_ids": [item["lesson_id"] for item in payload["lessons"]],
            "searched_at": "2026-10-29T00:00:00Z", "tool": "test fixture search receipt", "result_urls": [],
        }],
        "sources": [],
    }
    _refresh_review_digests(payload)
    payload["authoring_provenance"]["source_snapshot"] = {
        "confirmed_course_profile_sha256": canonical_json_sha256(payload["confirmed_course_info"]),
        "whole_course_outline_sha256": canonical_json_sha256(payload["outline"]),
        "reference_pool_sha256": canonical_json_sha256(payload["reference_pool"]),
    }
    return payload


class LessonContentV24Tests(unittest.TestCase):
    def validate(self, payload: dict) -> None:
        lesson_generator.validate_test_fixture_content_v2_input(payload)

    def test_40_hour_separate_course_generates_10_theory_and_10_practice_lessons_with_or_without_workorders(self) -> None:
        self.assertEqual(expected_lesson_coverage_hours({"mode": "split_lessons", "theory_hours": 20}, "2.3"), 20)
        self.assertEqual(expected_lesson_coverage_hours({"mode": "practice_only", "total_hours": 40}, "2.3"), 0)
        self.assertEqual(expected_lesson_coverage_hours({"mode": "practice_only", "total_hours": 40}, "2.4"), 40)
        self.assertIn("separate_full_lessons", DELIVERY_MODES)
        for workorders in (False, True):
            with self.subTest(workorders=workorders):
                payload = make_v24_payload(mode="separate_full_lessons", theory_hours=20, practice_hours=20, workorders=workorders)
                self.validate(payload)
                self.assertEqual(len(payload["lessons"]), 20)
                self.assertEqual(sum(item["lesson_type"] == "theory" for item in payload["lessons"]), 10)
                self.assertEqual(sum(item["lesson_type"] == "practice" for item in payload["lessons"]), 10)
                self.assertEqual(sum(item["hours"] for item in payload["lessons"]), 40)
                self.assertEqual(payload["artifact_plan"]["practice_work_orders"], workorders)

    def test_40_hour_practice_only_generates_20_practical_lessons_with_or_without_workorders(self) -> None:
        for workorders in (False, True):
            with self.subTest(workorders=workorders):
                payload = make_v24_payload(mode="practice_only", theory_hours=0, practice_hours=40, workorders=workorders)
                self.validate(payload)
                self.assertEqual(len(payload["lessons"]), 20)
                self.assertTrue(all(item["lesson_type"] == "practice" for item in payload["lessons"]))
                self.assertEqual(sum(item["practice_hours"] for item in payload["lessons"]), 40)
                self.assertEqual(len(payload.get("practice_task_contract", {}).get("tasks", [])), 20 if workorders else 0)

    def test_40_hour_theory_only_generates_20_theory_lessons(self) -> None:
        payload = make_v24_payload(mode="theory_only", theory_hours=40, practice_hours=0)
        self.validate(payload)
        self.assertEqual(len(payload["lessons"]), 20)
        self.assertTrue(all(item["lesson_type"] == "theory" for item in payload["lessons"]))
        self.assertEqual(sum(item["theory_hours"] for item in payload["lessons"]), 40)

    def test_separate_identifier_url_does_not_reinterpret_legacy_source_binding(self) -> None:
        reference = {
            "reference_id": "BOOK-1", "title": "数据结构教材", "authors": ["作者"],
            "publisher": "出版社", "year": 2021, "source_identifier": "978-7-04-055957-6",
            "source_url": "https://publisher.example/books/one", "authoritative_source": "出版社官方页",
        }
        source = {
            "reference_id": "BOOK-1", "source_url": reference["source_url"], "source_title": reference["title"],
            "source_author_or_organization": "作者", "source_year": 2021,
            "source_identifier": reference["source_identifier"], "source_identifier_evidence_url": "https://publisher.example/books/one",
            "authoritative_source": reference["authoritative_source"],
        }
        self.assertTrue(any("must be evidenced" in error for error in reference_source_binding_errors(reference, source)))
        self.assertEqual(reference_source_binding_errors(reference, source, allow_identifier_evidence_url=True), [])

    def test_missing_or_duplicate_lessons_and_split_mismatch_fail_closed(self) -> None:
        payload = make_v24_payload(mode="separate_full_lessons", theory_hours=20, practice_hours=20)
        missing = copy.deepcopy(payload)
        missing["lessons"].pop()
        missing["outline"].pop()
        missing["reference_research"]["queries"][0]["lesson_ids"].pop()
        _refresh_review_digests(missing)
        missing["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"] = canonical_json_sha256(missing["outline"])
        with self.assertRaisesRegex(ValueError, "Lesson count|outline"):
            self.validate(missing)

        duplicate = copy.deepcopy(payload)
        duplicate["lessons"][1]["lesson_id"] = duplicate["lessons"][0]["lesson_id"]
        duplicate["outline"] = [_outline_row(item) for item in duplicate["lessons"]]
        duplicate["reference_research"]["queries"][0]["lesson_ids"] = list(dict.fromkeys(item["lesson_id"] for item in duplicate["lessons"]))
        _refresh_review_digests(duplicate)
        duplicate["authoring_provenance"]["source_snapshot"]["whole_course_outline_sha256"] = canonical_json_sha256(duplicate["outline"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.validate(duplicate)

        mismatch = copy.deepcopy(payload)
        mismatch["delivery_plan"]["practice_hours"] = 18
        mismatch["delivery_plan"]["theory_hours"] = 22
        mismatch["confirmed_course_info"]["practice_hours"] = 18
        mismatch["confirmed_course_info"]["theory_hours"] = 22
        mismatch["authoring_provenance"]["source_snapshot"]["confirmed_course_profile_sha256"] = canonical_json_sha256(mismatch["confirmed_course_info"])
        with self.assertRaisesRegex(ValueError, "confirmed course information|theory/practice|reconcile|hour"):
            self.validate(mismatch)

    def test_search_not_run_fake_citation_and_project_scope_conflict_are_rejected(self) -> None:
        payload = make_v24_payload(mode="theory_only", theory_hours=2, practice_hours=0)
        blocked = copy.deepcopy(payload)
        blocked["reference_research"]["status"] = "not_executed"
        with self.assertRaisesRegex(ValueError, "not_executed"):
            self.validate(blocked)
        fake = copy.deepcopy(payload)
        fake["reference_pool"] = [{"reference_id": "FAKE", "reference_type": "book", "title": "虚构教材", "authors": ["虚构作者"], "publisher": "虚构出版社", "source_kind": "verified_public", "source_region": "domestic", "evidence": "https://example.invalid", "source_url": "https://example.invalid/fake", "authoritative_source": "虚构"}]
        fake["reference_research"]["status"] = "searched_verified_sources"
        fake["reference_research"]["sources"] = []
        with self.assertRaisesRegex(ValueError, "placeholder|matching reference_pool|verified"):
            self.validate(fake)

        outline = [{"lesson_id": "L01", "unit": "项目一", "task": "主题", "lesson_type": "theory", "hours": 2, "theory_hours": 2, "practice_hours": 0}]
        project = {"project_id": "项目一", "outline_sha256": canonical_json_sha256(outline), "lessons": [{**outline[0], "unit": "项目二"}]}
        result = validate_project_merge(outline, [project])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["project_scope_conflicts"])

        valid_project = {"project_id": "项目一", "outline_sha256": canonical_json_sha256(outline), "lessons": [dict(outline[0])]}
        duplicate = validate_project_merge(outline, [valid_project, valid_project])
        self.assertTrue(any("duplicate project result" in error for error in duplicate["errors"]))
        duplicate_lesson = dict(valid_project)
        duplicate_lesson["lessons"] = [dict(outline[0]), dict(outline[0])]
        repeated = validate_project_merge(outline, [duplicate_lesson])
        self.assertTrue(repeated["duplicate_lesson_ids"])
        two_project_outline = [
            {"lesson_id": "L01", "unit": "项目一", "task": "主题一", "lesson_type": "theory", "hours": 2, "theory_hours": 2, "practice_hours": 0},
            {"lesson_id": "L02", "unit": "项目二", "task": "主题二", "lesson_type": "practice", "hours": 2, "theory_hours": 0, "practice_hours": 2},
        ]
        project_one = {"project_id": "项目一", "outline_sha256": canonical_json_sha256(two_project_outline[:1]), "lessons": [dict(two_project_outline[0])]}
        project_two_duplicate = {
            "project_id": "项目二", "outline_sha256": canonical_json_sha256(two_project_outline[1:]),
            "lessons": [{**two_project_outline[1], "lesson_id": "L01"}],
        }
        cross_project_duplicate = validate_project_merge(two_project_outline, [project_one, project_two_duplicate])
        self.assertIn("L01", cross_project_duplicate["duplicate_lesson_ids"])
        self.assertTrue(cross_project_duplicate["project_scope_conflicts"])
        reordered = validate_project_merge(
            [{**outline[0], "lesson_id": "L01"}, {**outline[0], "lesson_id": "L02", "task": "主题2"}],
            [{"project_id": "项目一", "outline_sha256": canonical_json_sha256([{**outline[0], "lesson_id": "L01"}, {**outline[0], "lesson_id": "L02", "task": "主题2"}]), "lessons": [{**outline[0], "lesson_id": "L02", "task": "主题2"}, {**outline[0], "lesson_id": "L01"}]}],
        )
        self.assertTrue(any("preserve frozen outline order" in error for error in reordered["errors"]))
        mismatched = dict(valid_project)
        mismatched["lessons"] = [{**outline[0], "hours": 4}]
        hours = validate_project_merge(outline, [mismatched])
        self.assertTrue(any("hours" in error or "project-hour mismatch" in error for error in hours["errors"]))
        wrong_facts = {**valid_project, "course_case_facts_sha256": "0" * 64}
        facts_result = validate_project_merge(outline, [wrong_facts], course_case_facts_sha256="1" * 64)
        self.assertTrue(any("shared course case facts" in error for error in facts_result["errors"]))

    def test_generation_evidence_requires_search_15_dimensions_and_main_course_reconciliation(self) -> None:
        payload = make_v24_payload(mode="theory_only", theory_hours=2, practice_hours=0)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        lesson = payload["lessons"][0]
        project_id = lesson["unit"]
        project_work = json.loads(
            (SKILL / "docs/evidence/issue-73-synthetic-course/project-work/project-1-linear.json").read_text(encoding="utf-8")
        )
        source_read = project_work["research"]["exemplar_search_and_reading"]["source_read"]
        search_record = next(item for item in project_work["research"]["queries"] if item["query_id"] == "Q-AIIT-01")
        excerpt = source_read["read_excerpt"][:3900]
        url = source_read["url"]
        dims = [{
            "dimension": dimension, "status": "MEETS", "existing_design": "已有本课的具体教学设计与学习证据，能够对应该评价维度。",
            "current_evidence": "教案中的教师追问、学生操作产物和核验标准均可定位。",
            "exemplar_pattern": "对照公开完整设计中展示的任务分解和即时反馈方法。",
            "gap": "未发现需要修改的实质差距。", "improvement_reason": "现有方式适配冻结的课程目标与学时，保留原设计。", "conclusion": "retain",
        } for dimension in DIMENSIONS]
        from generation_evidence import sha256_bytes
        evidence = {
            "generation_evidence_version": "1.0", "content_contract_version": "2.4", "content_sha256": sha256_bytes(raw),
            "course_case_facts_sha256": payload["course_case_facts_sha256"],
            "project_workflow": {"mode": "project_subagents", "outline_sha256": canonical_json_sha256(payload["outline"]),
                "frozen_outline": copy.deepcopy(payload["outline"]),
                "frozen_outline_sha256": canonical_json_sha256(payload["outline"]),
                "course_case_facts_sha256": payload["course_case_facts_sha256"], "projects": [{
                "project_id": project_id, "lesson_ids": [lesson["lesson_id"]], "owner": "subagent:project-1", "status": "completed",
                "input_sha256": canonical_json_sha256(payload["outline"]), "output_sha256": canonical_json_sha256([lesson]),
                "returned_lesson_ids": [lesson["lesson_id"]], "hours": 2, "theory_hours": 2, "practice_hours": 0,
                "course_case_facts_sha256": payload["course_case_facts_sha256"],
                "self_check": "已核对课程项目范围、六个步骤、学习证据、评价闭环与课程冻结数据。",
            }]},
            "exemplar_research": {"status": "completed_limited_comparison", "queries": [{
                "query_id": "Q1", "query": search_record["query"], "language": "zh", "tool": search_record["tool"],
                "searched_at": search_record["searched_at"], "result_urls": search_record["result_urls"], "project_ids": [project_id],
                "lesson_ids": [lesson["lesson_id"]],
            }], "sources": [{
                "source_id": "EX1", "title": source_read["title"], "author_or_organization": f"{source_read['author']}；{source_read['organization']}", "url": url, "discovery_url": url,
                "source_type": "complete_teaching_design", "read_scope": source_read["read_scope"],
                "read_excerpt": excerpt, "capture_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                "lesson_ids": [lesson["lesson_id"]], "project_ids": [project_id], "excellence_status": "not_proven",
                "excellence_evidence": source_read["excellence_evidence"], "transferable_methods": source_read["transferable_patterns_only"],
                "limitations": source_read["population_and_topic_limit"],
            }]},
            "lesson_comparisons": [{
                "lesson_id": lesson["lesson_id"], "lesson_content_sha256": canonical_json_sha256(lesson_agent_content(lesson)),
                "comparison_status": "EXEMPLAR_COMPARISON_DONE", "comparison_status_note": "已阅读公开教学设计，逐项对照现有设计并保留方法迁移边界。",
                "comparison_type": "daily_non_blind", "source_ids": ["EX1"], "dimensions": dims,
                "revision": {"necessary": False, "actual_issue": "", "reason": "未发现足以改写的实际教学问题，保留初稿。",
                    "changed": False, "draft_content_sha256": canonical_json_sha256(lesson["pedagogical_review"]["draft_content"]),
                    "final_content_sha256": canonical_json_sha256(lesson["pedagogical_review"]["revised_content"]),
                    "re_review": "逐项复核15维结果与最终 Content 摘要，决定保留初稿。"},
            }],
            "course_review": {"status": "passed", "lesson_ids": [lesson["lesson_id"]], "project_ids": [project_id],
                "declared_hours": 2, "lesson_hours": 2, "theory_hours": 2, "practice_hours": 0,
                "duplicate_lesson_ids": [], "project_scope_conflicts": [],
                "cross_project_checks": {"progression": "已核对先修、目标和下一课衔接均与冻结 outline 一致。", "terminology": "术语和案例数据采用课程统一约定，没有项目间冲突。", "lesson_types": "理论/实践类型与课程总账核对一致，工单不重复累计学时。"}},
        }
        self.assertEqual(validate_generation_evidence(evidence, payload, content_bytes=raw), [])
        placeholder_source = copy.deepcopy(evidence)
        placeholder_source["exemplar_research"]["sources"][0]["url"] = "https://example.org/fake-design"
        self.assertTrue(any("reserved placeholder URL" in message for message in validate_generation_evidence(placeholder_source, payload, content_bytes=raw)))
        fallback = copy.deepcopy(evidence)
        fallback["project_workflow"]["mode"] = "sequential_fallback"
        fallback["project_workflow"]["projects"][0]["owner"] = "main_agent_fallback"
        self.assertEqual(validate_generation_evidence(fallback, payload, content_bytes=raw), [])
        missing = copy.deepcopy(evidence)
        missing["lesson_comparisons"][0]["dimensions"].pop()
        self.assertTrue(any("dimensions" in message for message in validate_generation_evidence(missing, payload, content_bytes=raw)))
        unsearched = copy.deepcopy(evidence)
        unsearched["exemplar_research"]["status"] = "not_executed"
        self.assertTrue(any("cannot pass" in message for message in validate_generation_evidence(unsearched, payload, content_bytes=raw)))
        no_comparison = copy.deepcopy(evidence)
        no_comparison["lesson_comparisons"] = []
        self.assertTrue(validate_generation_evidence(no_comparison, payload, content_bytes=raw))
        no_read_source = copy.deepcopy(evidence)
        no_read_source["exemplar_research"]["status"] = "searched_no_qualified_exemplar"
        no_read_source["exemplar_research"]["sources"] = []
        no_read_source["exemplar_research"]["queries"][0]["result_urls"] = []
        no_read_source["lesson_comparisons"][0].update(
            comparison_status="SEARCHED_NO_QUALIFIED_EXEMPLAR",
            comparison_status_note="已执行中文检索并读取检索结果，但未找到可用于本课逐项对照的完整教学设计。",
            comparison_type="search_no_qualified_exemplar",
            source_ids=[],
        )
        no_read_source["course_review"]["status"] = "limited"
        self.assertEqual(validate_generation_evidence(no_read_source, payload, content_bytes=raw), [])
        falsely_complete = copy.deepcopy(no_read_source)
        falsely_complete["course_review"]["status"] = "passed"
        self.assertTrue(any("must be limited" in error for error in validate_generation_evidence(falsely_complete, payload, content_bytes=raw)))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            content_path = output / "lesson-content.json"
            content_path.write_bytes(raw)
            evidence_bytes = (json.dumps(no_read_source, ensure_ascii=False, indent=2) + "\n").encode()
            evidence_path = output / "generation-evidence.json"
            evidence_path.write_bytes(evidence_bytes)
            evidence_sha = sha256_bytes(evidence_bytes)
            gate = _generation_evidence_gate(
                payload,
                {"teaching_quality_gate": {"status": "evidence_limited", "generation_evidence_sha256": evidence_sha}},
                output,
                {"generation_evidence_path": evidence_path.name, "generation_evidence_sha256": evidence_sha, "source_json_path": str(content_path)},
                content_path,
            )
        self.assertEqual(gate["status"], "FAIL")
        self.assertTrue(any("limited" in error for error in gate["observed"]["errors"]))
        false_excellence = copy.deepcopy(evidence)
        false_excellence["exemplar_research"]["status"] = "completed_with_qualified_exemplar"
        self.assertTrue(any("requires at least one source" in message for message in validate_generation_evidence(false_excellence, payload, content_bytes=raw)))

    def test_v24_preserves_different_per_lesson_review_rounds(self) -> None:
        payload = make_v24_payload(mode="theory_only", theory_hours=4, practice_hours=0)
        first = payload["lessons"][0]
        review = first["pedagogical_review"]
        final_content = copy.deepcopy(review["revised_content"])
        draft_content = copy.deepcopy(final_content)
        draft_content["teaching_content"][0] += " 初稿未明确边界条件。"
        draft_sha = canonical_json_sha256(draft_content)
        final_sha = canonical_json_sha256(final_content)
        review["draft_content"] = draft_content
        review["revised_content"] = final_content
        review["review_history"] = [
            {
                "round": 1,
                "issues": [{"category": "other", "severity": "major", "message": "初稿缺少可检查的边界条件，已要求补充。"}],
                "decision": "needs_revision",
                "content_sha256": draft_sha,
            },
            {"round": 2, "issues": [], "decision": "approved", "content_sha256": final_sha},
        ]
        provenance = payload["authoring_provenance"]
        provenance["review_rounds"] = 2
        provenance["draft_content_sha256"] = content_digest_rollup([
            canonical_json_sha256(lesson["pedagogical_review"]["draft_content"])
            for lesson in payload["lessons"]
        ])
        provenance["final_content_sha256"] = content_digest_rollup([
            canonical_json_sha256(lesson["pedagogical_review"]["revised_content"])
            for lesson in payload["lessons"]
        ])
        self.validate(payload)
        self.assertEqual(len(first["pedagogical_review"]["review_history"]), 2)
        self.assertEqual(len(payload["lessons"][1]["pedagogical_review"]["review_history"]), 1)

    def test_acceptance_cannot_pass_without_retained_generation_evidence(self) -> None:
        payload = make_v24_payload(mode="theory_only", theory_hours=2, practice_hours=0)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            gate = _generation_evidence_gate(
                payload,
                {"teaching_quality_gate": {"status": "evidence_complete", "generation_evidence_sha256": "0" * 64}},
                output,
                {"generation_evidence_path": "generation-evidence.json", "generation_evidence_sha256": "0" * 64},
                None,
            )
        self.assertEqual(gate["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
