from __future__ import annotations

import base64
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))

from downstream_adapters import _typed_structure_svg  # noqa: E402
from downstream_e2e import run_synthetic_e2e  # noqa: E402
from collect_visual_evidence import collect_visual_evidence  # noqa: E402
from mine_teaching_assets import mine_sources  # noqa: E402
from package_course import package_course  # noqa: E402
from plan_sessions import build_plans  # noqa: E402
from review_whole_course import (  # noqa: E402
    _comparison_quality,
    _quiz_quality,
    review_course,
    review_plan_architecture,
    review_rendered_course,
)
from orchestrator_core import OrchestrationError  # noqa: E402

try:
    from validate_outputs import validate_e2e  # noqa: E402
except SystemExit:  # pragma: no cover - the CI job installs jsonschema
    validate_e2e = None


PNG_A = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
PNG_B = PNG_A.replace(b"\x99", b"\x98")
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _slide_xml(title: str, *, image: bool = False) -> bytes:
    picture = "<p:pic><p:nvPicPr><p:cNvPr id='2' name='Image 2'/><p:cNvPicPr/></p:nvPicPr><p:blipFill><a:blip r:embed='rId1'/></p:blipFill></p:pic>" if image else ""
    return (
        f"<p:sld xmlns:p='{NS['p']}' xmlns:a='{NS['a']}' xmlns:r='{NS['r']}'><p:cSld><p:spTree>"
        f"<p:sp><p:nvSpPr><p:cNvPr id='1' name='Title'/></p:nvSpPr><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>{picture}"
        "</p:spTree></p:cSld></p:sld>"
    ).encode("utf-8")


def _write_simple_pptx(path: Path, titles: list[str], *, image: bytes | None = None, display_order: list[int] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    order = display_order or list(range(1, len(titles) + 1))
    with zipfile.ZipFile(path, "w") as archive:
        for index, title in enumerate(titles, start=1):
            archive.writestr(f"ppt/slides/slide{index}.xml", _slide_xml(title, image=image is not None))
            if image is not None:
                archive.writestr(
                    f"ppt/slides/_rels/slide{index}.xml.rels",
                    "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
                    "<Relationship Id='rId1' Target='../media/image1.png' Type='image'/></Relationships>",
                )
                archive.writestr("ppt/media/image1.png", image)
        rels = [
            f"<Relationship Id='rId{index}' Target='slides/slide{slide}.xml' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide'/ >".replace("/ >", "/>" )
            for index, slide in enumerate(order, start=1)
        ]
        archive.writestr(
            "ppt/presentation.xml",
            f"<p:presentation xmlns:p='{NS['p']}' xmlns:r='{NS['r']}'><p:sldIdLst>"
            + "".join(f"<p:sldId id='{255 + index}' r:id='rId{index}'/>" for index, _slide in enumerate(order, start=1))
            + "</p:sldIdLst></p:presentation>",
        )
        archive.writestr(
            "ppt/_rels/presentation.xml.rels",
            "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>" + "".join(rels) + "</Relationships>",
        )


def _course_bundle(*, mode: str = "release", session_minutes: float = 10, practice_minutes: float | None = None, page_minutes: float = 10, task_minutes: float = 10) -> tuple[dict, dict, dict, dict, dict]:
    page = {
        "id": "p1",
        "session_id": "s1",
        "title": "关系判断",
        "teaching_question_id": "q1",
        "teaching_question": "如何判断关系？",
        "learning_outcome": "能说明判断依据",
        "primary_job": "define",
        "layout": "focus",
        "suggested_minutes": page_minutes,
        "lecture_minutes": max(1, page_minutes - 2),
        "activity_minutes": 2,
        "knowledge_node_ids": ["n1"],
        "page_knowledge_state_before": [],
        "current_new_knowledge_ids": ["n1"],
        "page_knowledge_state_after": ["n1"],
        "future_knowledge_ids": [],
        "content_evidence": {"worked_example": "根据对象和条件核对关系。"},
    }
    session = {
        "id": "s1",
        "title": "关系判断",
        "minutes": session_minutes,
        "planning_mode": mode,
        "pages": [page],
        "knowledge_state_before": [],
        "new_knowledge": ["n1"],
        "knowledge_state_after": ["n1"],
        "future_knowledge": [],
    }
    if practice_minutes is not None:
        session["practice_minutes"] = practice_minutes
    task = {
        "id": "t1",
        "level": "core",
        "title": "完成关系判断",
        "capability": "construct",
        "artifact_type": "class_model",
        "knowledge_node_ids": ["n1"],
        "estimated_minutes": task_minutes,
        "task_shape": "artifact",
        "interaction_type": "model_editing",
        "starter": {"artifact_type": "class_model", "components": ["partial_classes"]},
        "editable_gaps": [{"type": "missing_relation"}],
        "steps": [{"kind": "observe"}, {"kind": "edit"}, {"kind": "verify"}],
    }
    session_plans = {"schema_version": "1.1", "plan_type": "content_native_session_plans", "planning_mode": mode, "sessions": [session]}
    practice_plans = {"schema_version": "1.1", "plan_type": "whole_course_practice_plans", "sessions": [{"id": "s1", "tasks": [task]}]}
    graph = {"schema_version": "1.1", "nodes": [{"id": "n1", "title": "关系判断", "type": "concept"}], "sessions": [{"id": "s1", "knowledge_state_before": [], "new_knowledge": ["n1"], "knowledge_state_after": ["n1"], "future_knowledge": []}]}
    inventory = {"schema_version": "1.1", "assets": []}
    research = {"research_status": "USER_SOURCE_SUFFICIENT", "research_gaps": [], "selected_source_count": 0, "search_performed": False}
    return session_plans, practice_plans, graph, inventory, research


def _rendered_practice(root: Path, *, include_tasks: tuple[str, ...] = ("t1",), task_ids: tuple[str, ...] = ("t1",)) -> dict:
    student_dir = root / "student"
    teacher_dir = root / "teacher"
    student_dir.mkdir(parents=True, exist_ok=True)
    teacher_dir.mkdir(parents=True, exist_ok=True)
    evidence = []
    for task_id in include_tasks:
        evidence.append(
            {
                "task_id": task_id,
                "status": "PASS",
                "required": ["student_artifact", "starter:partial_classes"],
                "missing": [],
                "observed": ["student_artifact", "starter:partial_classes", "editable_artifact"],
                "student_artifact_present": True,
                "teacher_reference_artifact_present": True,
                "student_manifest_present": True,
                "teacher_reference_present": True,
            }
        )
    return {"sessions": [{"id": "s1", "duration_minutes": 10, "student_dir": str(student_dir), "teacher_dir": str(teacher_dir), "task_evidence": evidence, "rendered_task_ids": list(task_ids)}]}


def _rendered_bundle(root: Path, *, script: str = "我们根据关系判断说明页面依据。", rendered_practice: dict | None = None) -> tuple[dict, dict, dict, dict, dict]:
    session_plans, practice_plans, graph, inventory, research = _course_bundle(session_minutes=10, page_minutes=10, task_minutes=10)
    rendered_course = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "title": "关系判断", "speaker_script": script, "blocks": [{"type": "paragraph", "text": "关系判断依据"}]}]}]}
    visual = {"status": "PASS", "visual_plans": [], "rendered_asset_ids": []}
    starter = {"status": "PASS", "starter_observed": ["partial_classes"]}
    contact = {"status": "DEGRADED", "thumbnail_count": 1}
    return session_plans, practice_plans, graph, inventory, research, rendered_course, rendered_practice or _rendered_practice(root)


class Phase12PlanAndEvidenceTests(unittest.TestCase):
    def test_a_empty_review_is_blocked(self) -> None:
        result = review_plan_architecture({}, {}, {}, {}, research={"research_status": "USER_SOURCE_SUFFICIENT", "research_gaps": []})
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("INPUT_INTEGRITY_ERROR", {item["code"] for item in result["findings"]})

    def test_b_theory_duration_mismatch_blocks_release(self) -> None:
        session, practice, graph, inventory, research = _course_bundle(session_minutes=30, page_minutes=10)
        result = review_plan_architecture(session, practice, graph, inventory, research=research)
        self.assertIn("THEORY_DURATION_MISMATCH", {item["code"] for item in result["findings"]})
        self.assertEqual(result["plan_status"], "FAIL")

    def test_c_practice_duration_mismatch_blocks_release(self) -> None:
        session, practice, graph, inventory, research = _course_bundle(practice_minutes=30, task_minutes=10)
        result = review_plan_architecture(session, practice, graph, inventory, research=research)
        self.assertIn("PRACTICE_DURATION_MISMATCH", {item["code"] for item in result["findings"]})

    def test_d_future_theory_knowledge_is_rejected(self) -> None:
        session, practice, graph, inventory, research = _course_bundle()
        session["sessions"][0]["pages"][0]["knowledge_node_ids"] = ["future"]
        graph["sessions"][0]["future_knowledge"] = ["future"]
        result = review_plan_architecture(session, practice, graph, inventory, research=research)
        self.assertIn("THEORY_KNOWLEDGE_BOUNDARY_ERROR", {item["code"] for item in result["findings"]})

    def test_e_teacher_visual_cannot_fill_student_gap(self) -> None:
        plans = {"visual_plans": [{"page_id": "p1", "artifact_type": "class_model", "required_semantic_elements": ["class"]}]}
        teacher = '<section data-page-id="p1"><figure>%s</figure></section>' % _typed_structure_svg("class_model", ["class"])
        result = collect_visual_evidence(plans, '<section data-page-id="p1"><p>no student visual</p></section>', teacher)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["visual_plans"][0]["student_semantic_structure_evidence"]["status"], "FAIL")
        self.assertEqual(result["visual_plans"][0]["teacher_semantic_structure_evidence"]["status"], "PASS")

    def test_f_marker_only_visual_fails_structure(self) -> None:
        html = '<section data-page-id="p1"><figure data-artifact-type="class_model" data-semantic-role="class relationship"><svg data-artifact-type="class_model"><text>class relationship</text></svg></figure></section>'
        result = collect_visual_evidence({"visual_plans": [{"page_id": "p1", "artifact_type": "class_model", "required_semantic_elements": ["class", "relationship"]}]}, html)
        self.assertEqual(result["marker_plumbing_status"], "PASS")
        self.assertEqual(result["semantic_structure_status"], "FAIL")
        self.assertEqual(result["status"], "FAIL")

    def test_g_to_j_non_uml_and_single_class_visuals_use_typed_structure(self) -> None:
        cases = [
            ("class_model", ["class"], "PASS"),
            ("tree_graph_structure", ["node", "edge", "parent_child"], "PASS"),
            ("relational_table_model", ["table", "field", "key"], "PASS"),
            ("network_topology", ["device", "link", "direction"], "PASS"),
            ("worksheet_dataflow", ["cell", "formula", "dependency"], "PASS"),
        ]
        for artifact, roles, expected in cases:
            with self.subTest(artifact=artifact):
                html = f'<section data-page-id="p1"><figure>{_typed_structure_svg(artifact, roles)}</figure></section>'
                result = collect_visual_evidence({"visual_plans": [{"page_id": "p1", "artifact_type": artifact, "required_semantic_elements": roles}]}, html)
                self.assertEqual(result["status"], expected, result)
                self.assertEqual(result["visual_plans"][0]["semantic_structure_evidence"]["status"], expected)

    def test_k_generic_script_fails_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session, practice, graph, inventory, research, rendered, rendered_practice = _rendered_bundle(Path(temp), script="天气很好，今天休息。")
            result = review_rendered_course(session, practice, graph, inventory, visual_evidence={"status": "PASS", "visual_plans": []}, starter_evidence={"status": "PASS"}, rendered_course=rendered, rendered_practice=rendered_practice, contact_sheet={"status": "DEGRADED", "thumbnail_count": 1}, research=research)
            self.assertIn("SCRIPT_TO_SLIDE_GROUNDING_INCOMPLETE", {item["code"] for item in result["findings"]})

    def test_l_specific_script_passes_grounding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session, practice, graph, inventory, research, rendered, rendered_practice = _rendered_bundle(Path(temp))
            result = review_rendered_course(session, practice, graph, inventory, visual_evidence={"status": "PASS", "visual_plans": []}, starter_evidence={"status": "PASS"}, rendered_course=rendered, rendered_practice=rendered_practice, contact_sheet={"status": "DEGRADED", "thumbnail_count": 1}, research=research)
            self.assertEqual(result["metrics"]["render_evidence"]["script_to_slide_grounding"]["status"], "PASS", result)

    def test_m_trivial_quiz_fails_and_n_grounded_distractors_pass(self) -> None:
        trivial = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "title": "关系判断", "blocks": [{"type": "quiz", "question": "如何判断关系？", "options": ["天气", "随便", "都一样"], "answer_index": 0, "answer_text": "天气", "explanation": "天气"}]}]}]}
        bad = _quiz_quality(trivial)
        self.assertEqual(bad["status"], "FAIL")
        valid = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "title": "关系判断", "blocks": [{"type": "quiz", "question": "判断关系需要哪些依据？", "options": ["对象和必要条件", "只说明对象，不检查必要条件", "只说例子，不说明适用条件"], "answer_index": 0, "answer_text": "对象和必要条件", "explanation": "对象和必要条件都要回到页面证据核对。", "distractor_metadata": [{"text": "只说明对象，不检查必要条件", "misconception_type": "missing-condition", "rationale": "遗漏必要条件"}, {"text": "只说例子，不说明适用条件", "misconception_type": "example-without-boundary", "rationale": "把例子当成规则"}]}]}]}]}
        good = _quiz_quality(valid)
        self.assertEqual(good["status"], "PASS", good)

    def test_o_broken_comparison_fails(self) -> None:
        plan = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "teaching_question_id": "q1", "content_evidence": {"comparison": {"dimension": "依据"}}}]}]}
        rendered = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "blocks": [{"type": "comparison", "contrast_dimension": "依据", "left_title": "A", "right_title": "B", "left": ["相同内容"], "right": ["相同内容"], "correct_side": "A", "wrong_side": "A"}]}]}]}
        result = _comparison_quality(rendered, plan)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["errors"])

    def test_p_missing_practice_task_fails_session_closure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session, practice, graph, inventory, research, rendered, _ = _rendered_bundle(Path(temp), rendered_practice=_rendered_practice(Path(temp), include_tasks=(), task_ids=("t1",)))
            practice["sessions"][0]["tasks"].append({"id": "t2", "level": "core", "artifact_type": "class_model", "estimated_minutes": 10})
            result = review_rendered_course(session, practice, graph, inventory, visual_evidence={"status": "PASS", "visual_plans": []}, starter_evidence={"status": "PASS"}, rendered_course=rendered, rendered_practice=_rendered_practice(Path(temp), include_tasks=("t1",), task_ids=("t1",)), contact_sheet={"status": "DEGRADED", "thumbnail_count": 1}, research=research)
            self.assertEqual(result["final_status"], "FAIL")
            self.assertIn("RENDERED_PRACTICE_EVIDENCE_INCOMPLETE", {item["code"] for item in result["findings"]})

    def test_q_missing_rendered_practice_can_never_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session, practice, graph, inventory, research, rendered, _ = _rendered_bundle(Path(temp))
            result = review_rendered_course(session, practice, graph, inventory, visual_evidence={"status": "PASS", "visual_plans": []}, starter_evidence={"status": "PASS"}, rendered_course=rendered, rendered_practice=None, contact_sheet={"status": "DEGRADED", "thumbnail_count": 1}, research=research)
            self.assertEqual(result["final_status"], "FAIL")
            self.assertIn("REQUIRED_RENDER_EVIDENCE_MISSING", {item["code"] for item in result["findings"]})

    def test_r_ppt_display_order_is_not_zip_or_filename_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_simple_pptx(root / "reordered.pptx", ["Physical one", "Physical two", "Displayed three"], display_order=[3, 1, 2])
            inventory = mine_sources(root, root / "out")
            titles = [item["title"] for item in inventory["source_slides"]]
            self.assertEqual(titles[:3], ["Displayed three", "Physical one", "Physical two"])
            self.assertEqual([item["source_slide"] for item in inventory["assets"][:3]], [1, 2, 3])

    def test_teaching_beats_preserve_one_question_and_distribute_time(self) -> None:
        course = {"course_id": "beats", "planning_mode": "release", "knowledge_nodes": [{"id": "n1", "title": "证据", "type": "concept"}], "sessions": [{"id": "s1", "title": "分段问题", "minutes": 20, "teaching_questions": [{"id": "q1", "prompt": "如何分段验证？", "learning_outcome": "能按阶段核对", "minutes": 20, "knowledge_node_ids": ["n1"], "beats": [{"title": "先观察", "minutes": 8}, {"title": "再验证", "minutes": 12}]}]}]}
        graph = {"course_id": "beats", "nodes": [{"id": "n1", "title": "证据", "type": "concept"}], "sessions": [{"id": "s1", "knowledge_state_before": [], "new_knowledge": ["n1"], "knowledge_state_after": ["n1"], "future_knowledge": []}]}
        plans = build_plans(course, graph, {"assets": []})
        pages = plans["sessions"][0]["pages"]
        self.assertEqual(len(pages), 2)
        self.assertEqual({page["teaching_question_id"] for page in pages}, {"q1"})
        self.assertAlmostEqual(sum(page["suggested_minutes"] for page in pages), 20)
        self.assertEqual(len(plans["sessions"][0]["teaching_questions"][0]["page_ids"]), 2)

    def test_s_same_stem_sources_have_distinct_namespaces_and_media(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_simple_pptx(root / "one" / "deck.pptx", ["Screenshot one"], image=PNG_A)
            _write_simple_pptx(root / "two" / "deck.pptx", ["Screenshot two"], image=PNG_B)
            inventory = mine_sources(root, root / "out")
            sources = {Path(item["source_file"]).parent.name: item for item in inventory["sources"]}
            self.assertNotEqual(sources["one"]["source_namespace"], sources["two"]["source_namespace"])
            images = [item["image_ref"] for item in inventory["assets"] if item.get("image_ref")]
            self.assertEqual(len(set(images)), 2)
            self.assertEqual({Path(item).parts[1] for item in set(images)}, {sources["one"]["source_namespace"], sources["two"]["source_namespace"]})

    def test_t_legacy_ppt_retains_original_provenance_after_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = root / "sources" / "legacy.ppt"
            legacy.parent.mkdir()
            legacy.write_bytes(b"legacy-ppt-placeholder")
            converted = root / "converted.pptx"
            _write_simple_pptx(converted, ["Definition after conversion"])
            with patch("mine_teaching_assets._convert_legacy_ppt", return_value=converted):
                inventory = mine_sources(root / "sources", root / "out")
            source = inventory["sources"][0]
            asset = inventory["assets"][0]
            self.assertEqual(source["format"], "ppt")
            self.assertEqual(source["source_file"], str(legacy))
            self.assertEqual(asset["source_file"], str(legacy))
            self.assertEqual(asset["parsed_file"], str(converted))
            self.assertTrue(asset["source_locator"].startswith("ppt:legacy.ppt#slide-1"))

    def test_u_decorative_slide_is_low_value_not_teaching_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_simple_pptx(root / "decorative.pptx", ["Decorative credits"])
            inventory = mine_sources(root, root / "out")
            self.assertTrue(inventory["assets"])
            self.assertTrue(all(item["teaching_value"] in {"low-value", "optional"} for item in inventory["assets"]))
            self.assertNotIn("diagram", {item["type"] for item in inventory["assets"]})

    def test_v_final_packaging_is_fail_closed_on_bad_qa(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            qa = root / "qa.json"
            qa.write_text(json.dumps({"status": "FAIL", "final_status": "FAIL", "render_status": "FAIL", "plan_status": "BLOCKED", "architecture_status": "WHOLE_COURSE_ARCHITECTURE_BLOCKED"}), encoding="utf-8")
            manifest = {"course_name": "Blocked", "package_kind": "final", "theory_sessions": [], "practice_sessions": [], "evidence_data": {"qa": str(qa)}}
            with self.assertRaisesRegex(ValueError, "PACKAGING_BLOCKED"):
                package_course(manifest, root / "delivery")

    def test_w_schema_validation_covers_real_e2e_outputs(self) -> None:
        if validate_e2e is None:
            self.skipTest("jsonschema is not installed in the local interpreter")
        with tempfile.TemporaryDirectory() as temp:
            run_synthetic_e2e(temp, use_browser=False, evidence_mode="migration-trust")
            self.assertGreaterEqual(validate_e2e(Path(temp)), 12)

    def test_x_near_identical_practice_is_collapsed_after_knowledge_normalization(self) -> None:
        session, _practice, graph, inventory, research = _course_bundle()
        sessions = []
        practice_sessions = []
        for index in range(1, 4):
            sid = f"s{index}"
            page = copy.deepcopy(session["sessions"][0]["pages"][0])
            page.update({"id": f"{sid}-p1", "session_id": sid})
            sessions.append({"id": sid, "pages": [page]})
            practice_sessions.append({"id": sid, "tasks": [{"id": f"{sid}-t1", "capability": "construct", "artifact_type": "class_model", "estimated_minutes": 30, "task_shape": "artifact", "interaction_type": "model_editing", "starter": {"artifact_type": "class_model", "components": ["partial_classes"]}, "editable_gaps": [{"type": "missing_relation"}], "steps": [{"kind": "observe"}, {"kind": "edit"}, {"kind": "verify"}], "semantic_task_signature": f"semantic-{index}", "structural_task_signature": f"shape-{index}"}]})
        session_plan = {"sessions": sessions}
        practice_plan = {"sessions": practice_sessions}
        graph["sessions"] = [{"id": f"s{index}", "knowledge_state_after": [f"n{index}"]} for index in range(1, 4)]
        result = review_course(session_plan, practice_plan, graph, inventory, research=research)
        self.assertIn("WHOLE_COURSE_PRACTICE_SIMILARITY_COLLAPSE", {item["code"] for item in result["findings"]})

    def test_y_healthy_varied_practice_does_not_false_collapse(self) -> None:
        session, _practice, graph, inventory, research = _course_bundle()
        sessions = []
        practice_sessions = []
        variants = [("class_model", "construct", 20, "model_editing"), ("tree_graph_structure", "trace", 35, "traversal"), ("worksheet_dataflow", "verify", 50, "dataflow")]
        for index, (artifact, capability, minutes, interaction) in enumerate(variants, start=1):
            sid = f"s{index}"
            page = copy.deepcopy(session["sessions"][0]["pages"][0])
            page.update({"id": f"{sid}-p1", "session_id": sid, "primary_job": "visualize" if index == 2 else "step_through", "artifact_type": artifact})
            sessions.append({"id": sid, "pages": [page]})
            practice_sessions.append({"id": sid, "tasks": [{"id": f"{sid}-t1", "capability": capability, "artifact_type": artifact, "estimated_minutes": minutes, "task_shape": artifact, "interaction_type": interaction, "level": "core", "starter": {"artifact_type": artifact, "components": [artifact]}, "editable_gaps": [{"type": f"gap-{index}"}], "steps": [{"kind": f"observe-{index}"}, {"kind": f"act-{index}"}], "semantic_task_signature": f"semantic-{index}", "structural_task_signature": f"shape-{index}"}]})
        graph["sessions"] = [{"id": f"s{index}", "knowledge_state_after": [f"n{index}"]} for index in range(1, 4)]
        result = review_course({"sessions": sessions}, {"sessions": practice_sessions}, graph, inventory, research=research)
        self.assertNotIn("WHOLE_COURSE_PRACTICE_SIMILARITY_COLLAPSE", {item["code"] for item in result["findings"]})

    def test_z_omitted_research_state_blocks_when_gaps_exist(self) -> None:
        session, practice, graph, inventory, _research = _course_bundle()
        result = review_plan_architecture(session, practice, graph, inventory)
        self.assertIn("RESEARCH_STATE_MISSING", {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
