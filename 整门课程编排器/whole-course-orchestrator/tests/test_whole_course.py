from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from build_knowledge_graph import build_graph, validate_knowledge_boundary  # noqa: E402
from external_research import research  # noqa: E402
from mine_teaching_assets import mine_sources  # noqa: E402
from package_course import package_course  # noqa: E402
from plan_practice import plan_practice_session, typed_starter  # noqa: E402
from plan_sessions import build_plans  # noqa: E402
from plan_visuals import build_visual_plans  # noqa: E402
from review_whole_course import review_course  # noqa: E402
from orchestrator_core import OrchestrationError, load_json  # noqa: E402


NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _slide_xml(title: str, *, shape_count: int = 1, image: bool = False) -> bytes:
    shapes = [f"<p:sp><p:nvSpPr><p:cNvPr id='{i}' name='Shape {i}'/></p:nvSpPr><p:txBody><a:p><a:r><a:t>{title if i == 1 else 'evidence'}</a:t></a:r></a:p></p:txBody></p:sp>" for i in range(1, shape_count + 1)]
    if image:
        shapes.append("<p:pic><p:blipFill><a:blip r:embed='rId1'/></p:blipFill></p:pic>")
    body = "".join(shapes)
    return f"<p:sld xmlns:p='{NS['p']}' xmlns:a='{NS['a']}' xmlns:r='{NS['r']}'><p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>".encode("utf-8")


def _write_fixture_pptx(path: Path) -> None:
    slides = [
        ("Definition: graph", 1, False),
        ("Architecture diagram", 5, False),
        ("Screenshot: draw.io", 1, True),
        ("Exercise: choose a relation", 1, False),
        ("Steps: open, edit, verify", 1, False),
    ]
    with zipfile.ZipFile(path, "w") as archive:
        for index, (title, shape_count, image) in enumerate(slides, start=1):
            archive.writestr(f"ppt/slides/slide{index}.xml", _slide_xml(title, shape_count=shape_count, image=image))
            if image:
                archive.writestr(f"ppt/slides/_rels/slide{index}.xml.rels", "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='../media/image1.png' Type='image'/></Relationships>")
                archive.writestr("ppt/media/image1.png", base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
            if index == 3:
                archive.writestr(f"ppt/notesSlides/notesSlide{index}.xml", f"<p:notes xmlns:p='{NS['p']}' xmlns:a='{NS['a']}'><p:cSld><a:t>Teacher note for screenshot</a:t></p:cSld></p:notes>")


def _inventory(asset_ids: list[str] | None = None) -> dict:
    return {"assets": [{"id": asset_id, "type": "diagram", "teaching_value": "core", "candidate_topics": []} for asset_id in (asset_ids or [])]}


def _failure_signature_fixture() -> tuple[dict, dict, dict, dict]:
    pages = [
        {"id": "p1", "primary_job": "define", "layout": "focus", "lecture_minutes": 10, "activity_minutes": 5, "block_signature": ["question", "explanation"], "speaker_script": "本页先让学生区分概念。"},
        {"id": "p2", "primary_job": "check", "layout": "check", "lecture_minutes": 10, "activity_minutes": 5, "block_signature": ["question", "diagnostic_check"], "speaker_script": "请学生用一句话回答。", "quiz": {"distractors": ["所有图都一样"]}},
    ]
    sessions = [{"id": f"s{i}", "pages": [dict(page, id=f"s{i}-{page['id']}") for page in pages]} for i in range(1, 4)]
    practice = {"sessions": [{"id": f"s{i}", "tasks": [{"id": "t1", "capability": "construct", "estimated_minutes": 60, "signature": "same", "starter": {"artifact_type": "class_model", "components": ["partial_classes"]}}, {"id": "t2", "capability": "explain", "estimated_minutes": 60, "signature": "same2", "starter": {"artifact_type": "class_model", "components": ["partial_classes"]}}]} for i in range(1, 4)]}
    graph = {"sessions": [{"id": f"s{i}", "knowledge_state_after": []} for i in range(1, 4)]}
    inventory = {"assets": [{"id": "high-1", "teaching_value": "core", "type": "diagram"}]}
    return {"sessions": sessions}, practice, graph, inventory


class WholeCourseTests(unittest.TestCase):
    def test_source_mining_recovers_text_visual_and_procedure_asset_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "fixture.pptx"
            _write_fixture_pptx(source)
            inventory = mine_sources(root, root / "out")
            types = {asset["type"] for asset in inventory["assets"]}
            self.assertTrue({"definition", "diagram", "screenshot", "exercise", "procedure"} <= types)
            screenshot = next(asset for asset in inventory["assets"] if asset["type"] == "screenshot")
            self.assertEqual(screenshot["inventory_evidence"]["speaker_note_count"], 1)
            self.assertTrue((root / "out" / screenshot["image_ref"]).is_file())
            report = load_json(root / "out" / "source-teaching-asset-report.json")
            self.assertEqual(report["asset_counts_by_type"]["screenshot"], 1)

    def test_t12_cumulative_knowledge_state_and_boundary(self) -> None:
        course = {
            "course_id": "synthetic",
            "knowledge_nodes": [
                {"id": "concept-a", "title": "A", "type": "concept"},
                {"id": "procedure-b", "title": "B", "type": "procedure", "prerequisites": ["concept-a"]},
                {"id": "diagnosis-c", "title": "C", "type": "diagnosis", "depends_on": ["procedure-b"]},
            ],
            "sessions": [
                {"id": "s1", "title": "A", "new_knowledge_ids": ["concept-a"]},
                {"id": "s2", "title": "B", "new_knowledge_ids": ["procedure-b"], "review_knowledge_ids": ["concept-a"]},
                {"id": "s3", "title": "C", "new_knowledge_ids": ["diagnosis-c"], "review_knowledge_ids": ["procedure-b"]},
            ],
        }
        graph = build_graph(course)
        self.assertEqual(graph["sessions"][1]["knowledge_state_before"], ["concept-a"])
        self.assertEqual(graph["sessions"][1]["knowledge_state_after"], ["concept-a", "procedure-b"])
        self.assertEqual(validate_knowledge_boundary(graph, "s1", ["procedure-b"]), ["s1: knowledge used before taught: procedure-b"])
        self.assertEqual(graph["nodes"][0]["revisited_sessions"], ["s2"])

    def test_t02_three_synthetic_course_shapes_produce_different_plans(self) -> None:
        graph_input = {
            "course_id": "three-shapes",
            "knowledge_nodes": [
                {"id": "concept", "title": "Concept", "type": "concept"},
                {"id": "model", "title": "Model", "type": "modeling_skill"},
                {"id": "procedure", "title": "Procedure", "type": "procedure"},
            ],
            "sessions": [
                {"id": "concept-course", "title": "Concept", "new_knowledge_ids": ["concept"]},
                {"id": "visual-course", "title": "Visual", "new_knowledge_ids": ["model"]},
                {"id": "procedure-course", "title": "Procedure", "new_knowledge_ids": ["procedure"]},
            ],
        }
        graph = build_graph(graph_input)
        course = {
            **graph_input,
            "sessions": [
                {"id": "concept-course", "title": "Concept", "teaching_questions": [{"id": "q1", "prompt": "概念是什么？", "learning_outcome": "能给出定义", "primary_job": "define", "minutes": 12}]},
                {"id": "visual-course", "title": "Visual", "teaching_questions": [{"id": "q1", "prompt": "图中关系如何表达？", "learning_outcome": "能指出关系", "artifact_type": "class_model", "visual_intent": "relationship", "minutes": 28}]},
                {"id": "procedure-course", "title": "Procedure", "teaching_questions": [{"id": "q1", "prompt": "如何完成操作？", "learning_outcome": "能按步骤完成", "procedure": ["open", "edit", "verify"], "minutes": 20}]},
            ],
        }
        plans = build_plans(course, graph, _inventory())
        jobs = {session["id"]: session["pages"][0]["primary_job"] for session in plans["sessions"]}
        self.assertEqual(jobs, {"concept-course": "define", "visual-course": "visualize", "procedure-course": "step_through"})
        self.assertNotEqual(plans["sessions"][0]["pages"][0]["layout"], plans["sessions"][1]["pages"][0]["layout"])
        visuals = build_visual_plans(plans, _inventory())
        self.assertEqual(visuals["visual_plans"][0]["artifact_type"], "class_model")
        self.assertIn("multiplicity", visuals["visual_plans"][0]["semantic_elements"])

    def test_t09_typed_starter_and_generic_practice_placeholder_rejection(self) -> None:
        with self.assertRaises(OrchestrationError):
            plan_practice_session(
                {"id": "s1", "tasks": [{"id": "t1", "artifact_type": "class_model", "capability": "construct", "knowledge_ids": [], "estimated_minutes": 20, "starter": {"components": ["rectangle"], "editable_gaps": ["TODO_1"]}}]},
                {"sessions": [{"id": "s1", "knowledge_state_after": []}]},
            )
        starter = typed_starter("sequence_model")
        self.assertEqual(starter["starter_kind"], "typed")
        self.assertIn("missing_message", {item["type"] for item in starter["editable_gaps"]})

    def test_t01_template_collapse_gate(self) -> None:
        session_plans, practice, graph, inventory = _failure_signature_fixture()
        report = review_course(session_plans, practice, graph, inventory)
        self.assertIn("WHOLE_COURSE_TEMPLATE_COLLAPSE", {finding["code"] for finding in report["findings"]})

    def test_t03_source_underuse_gate(self) -> None:
        session_plans, practice, graph, inventory = _failure_signature_fixture()
        report = review_course(session_plans, practice, graph, inventory)
        self.assertIn("SOURCE_MATERIAL_UNDERUTILIZED", {finding["code"] for finding in report["findings"]})

    def test_t04_comparison_same_sides_gate(self) -> None:
        session_plans = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "primary_job": "compare", "contrast_dimension": "notation", "content_evidence": {"comparison": {"left": "相同表达", "right": "相同表达"}}}]}]}
        report = review_course(session_plans, {"sessions": []}, {"sessions": []}, {"assets": []})
        self.assertIn("COMPARISON_SIDES_SEMANTICALLY_IDENTICAL", {item["code"] for item in report["metrics"]["comparison_semantic_errors"]})

    def test_t05_comparison_wrong_side_gate(self) -> None:
        session_plans = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "primary_job": "compare", "contrast_dimension": "结果", "content_evidence": {"comparison": {"left": "错误项", "right": "正确项", "wrong_side": "正确项", "correct": "正确项"}}}]}]}
        report = review_course(session_plans, {"sessions": []}, {"sessions": []}, {"assets": []})
        self.assertIn("CORRECT_ITEM_ON_WRONG_SIDE", {item["code"] for item in report["metrics"]["comparison_semantic_errors"]})

    def test_t06_quiz_distractor_reuse_gate(self) -> None:
        session_plans, practice, graph, inventory = _failure_signature_fixture()
        for session in session_plans["sessions"]:
            session["pages"][0]["quiz"] = {"distractors": ["重复项", "重复项", "重复项", "重复项"]}
            session["pages"][1]["quiz"] = {"distractors": ["重复项"]}
        report = review_course(session_plans, practice, graph, inventory)
        self.assertIn("QUIZ_DISTRACTOR_REUSE", {finding["code"] for finding in report["findings"]})

    def test_t07_script_similarity_gate(self) -> None:
        same_script = "请学生观察证据并回答为什么这个关系成立，然后说明依据。"
        session_plans = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "speaker_script": same_script}]}, {"id": "s2", "pages": [{"id": "p2", "speaker_script": same_script}]}]}
        report = review_course(session_plans, {"sessions": []}, {"sessions": []}, {"assets": []})
        self.assertEqual(report["metrics"]["script_cross_similarity"]["same_position_similarity_mean"], 1.0)
        self.assertIn("SCRIPT_CROSS_SESSION_TEMPLATE_REUSE", {finding["code"] for finding in report["findings"]})

    def test_t08_practice_fixed_shape_gate(self) -> None:
        session_plans, practice, graph, inventory = _failure_signature_fixture()
        report = review_course(session_plans, practice, graph, inventory)
        self.assertIn("WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE", {finding["code"] for finding in report["findings"]})

    def test_t10_visual_generic_rectangle_gate(self) -> None:
        with self.assertRaises(OrchestrationError):
            build_visual_plans(
                {"sessions": [{"id": "s1", "pages": [{"id": "p1", "artifact_type": "class_model", "visual_intent": "relationship", "render_strategy": "generic_rectangle"}]}]},
                _inventory(),
            )

    def test_t11_practice_knowledge_before_taught_gate(self) -> None:
        with self.assertRaises(OrchestrationError):
            plan_practice_session(
                {"id": "s1", "tasks": [{"id": "t1", "artifact_type": "class_model", "capability": "construct", "knowledge_ids": ["future-node"], "estimated_minutes": 20}]},
                {"sessions": [{"id": "s1", "knowledge_state_after": []}]},
            )

    def test_external_research_preserves_disabled_and_conflict_states(self) -> None:
        gaps = [{"id": "g1", "topic": "关系", "type": "missing_visual", "priority": "high"}]
        disabled = research(gaps, [], enabled=False)
        self.assertEqual(disabled["research_status"], "EXTERNAL_RESEARCH_DISABLED_BY_USER")
        selected = research(
            gaps,
            [{"query": "relation", "source_url": "https://example.edu/a", "source_title": "A", "authority": "university-course", "gap_ids": ["g1"], "relevance": 0.9, "student_level_fit": 0.9, "teaching_value": 0.8, "claims": [{"canonical_key": "rel", "claim": "new"}], "supersedes_user_version": False}],
            user_facts=[{"canonical_key": "rel", "claim": "old"}],
        )
        self.assertEqual(selected["selected_source_count"], 1)
        self.assertEqual(selected["conflicts"][0]["code"], "UNRESOLVED_SOURCE_CONFLICT")

    def test_t13_t14_clean_package_has_safe_names_and_no_duplicate_student_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            theory = root / "theory.html"
            teacher = root / "teacher.html"
            theory.write_text("<html>student</html>", encoding="utf-8")
            teacher.write_text("<html>teacher</html>", encoding="utf-8")
            student_dir = root / "student"
            teacher_dir = root / "teacher"
            student_dir.mkdir()
            teacher_dir.mkdir()
            (student_dir / "task.html").write_text("task", encoding="utf-8")
            (teacher_dir / "guide.html").write_text("guide", encoding="utf-8")
            package = package_course(
                {"course_name": "C/S 应用系统建模", "theory_sessions": [{"id": "s1", "title": "A/B: first", "student_html": str(theory), "teacher_html": str(teacher)}], "practice_sessions": [{"id": "s1", "title": "Practice", "student_dir": str(student_dir), "teacher_dir": str(teacher_dir)}]},
                root / "out",
            )
            self.assertTrue((package / "理论课" / "01_A-B- first" / "学生课件.html").is_file())
            self.assertFalse(any("student-package" in path.as_posix() for path in package.rglob("*")))


if __name__ == "__main__":
    unittest.main()
