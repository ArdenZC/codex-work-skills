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

from collect_starter_evidence import collect_starter_evidence  # noqa: E402
from collect_visual_evidence import collect_visual_evidence  # noqa: E402
from contact_sheets import build_contact_sheets  # noqa: E402
from downstream_adapters import _drawio_starter  # noqa: E402
from downstream_e2e import run_synthetic_e2e  # noqa: E402
from external_research import detect_gaps, resolve_asset_knowledge_links  # noqa: E402
from mine_teaching_assets import mine_sources  # noqa: E402
from plan_practice import typed_starter  # noqa: E402
from plan_sessions import build_plans  # noqa: E402
from review_whole_course import review_course, review_rendered_course  # noqa: E402
from build_knowledge_graph import build_graph  # noqa: E402
from orchestrator_core import OrchestrationError  # noqa: E402


PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def _slide_xml(title: str, *, connectors: bool = False, image: bool = False, table: bool = False) -> bytes:
    shapes = "".join(
        f"<p:sp><p:nvSpPr><p:cNvPr id='{index}' name='Shape {index}'/></p:nvSpPr><p:spPr><a:xfrm><a:off x='{index * 800000}' y='800000'/><a:ext cx='1200000' cy='600000'/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>{title if index == 1 else 'supporting evidence'}</a:t></a:r></a:p></p:txBody></p:sp>"
        for index in range(1, 4)
    )
    connector = "<p:cxnSp><p:nvCxnSpPr><p:cNvPr id='4' name='Connector 4'/><p:cNvCxnSpPr/></p:nvCxnSpPr><p:spPr><a:prstGeom prst='line'><a:avLst/></a:prstGeom><a:ln><a:tailEnd type='none'/><a:headEnd type='triangle'/></a:ln></p:spPr></p:cxnSp>" if connectors else ""
    picture = "<p:pic><p:nvPicPr><p:cNvPr id='5' name='Image 5'/><p:cNvPicPr/></p:nvPicPr><p:blipFill><a:blip r:embed='rId1'/></p:blipFill></p:pic>" if image else ""
    table_xml = "<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id='6' name='Table 6'/></p:nvGraphicFramePr><a:graphic><a:graphicData uri='http://schemas.openxmlformats.org/drawingml/2006/table'><a:tbl><a:tr><a:tc><a:p><a:r><a:t>Header</a:t></a:r></a:p></a:tc><a:tc><a:p><a:r><a:t>Value</a:t></a:r></a:p></a:tc></a:tr><a:tr><a:tc><a:p><a:r><a:t>Row</a:t></a:r></a:p></a:tc><a:tc><a:p><a:r><a:t>Evidence</a:t></a:r></a:p></a:tc></a:tr></a:tbl></a:graphicData></a:graphic></p:graphicFrame>" if table else ""
    return f"<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><p:cSld><p:spTree>{shapes}{connector}{picture}{table_xml}</p:spTree></p:cSld></p:sld>".encode("utf-8")


def _write_multi_asset_pptx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", _slide_xml("Definition and example", image=True, table=True))
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='../media/image1.png' Type='image'/></Relationships>")
        archive.writestr("ppt/slides/slide2.xml", _slide_xml("Relationship diagram", connectors=True))
        archive.writestr("ppt/slides/_rels/slide2.xml.rels", "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='../media/image1.png' Type='image'/></Relationships>")
        archive.writestr("ppt/media/image1.png", PNG_1X1)
        archive.writestr("ppt/notesSlides/notesSlide1.xml", "<p:notes xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main'><p:cSld><a:t xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'>Teacher note</a:t></p:cSld></p:notes>")


def _inventory(*asset_ids: str) -> dict:
    return {"assets": [{"id": value, "type": "diagram", "teaching_value": "core", "candidate_topics": []} for value in asset_ids]}


def _minimal_course(*, mode: str = "release", with_minutes: bool = True) -> dict:
    question = {"id": "q1", "prompt": "概念如何判断？", "learning_outcome": "能说明判断依据"}
    if with_minutes:
        question["minutes"] = 12
    return {
        "course_id": "timing-test",
        "knowledge_nodes": [{"id": "n1", "title": "概念", "type": "concept"}],
        "sessions": [{"id": "s1", "title": "概念", "new_knowledge_ids": ["n1"], "teaching_questions": [question]}],
        "planning_mode": mode,
    }


class Phase11EvidenceTests(unittest.TestCase):
    def test_t15_multi_asset_mining_keeps_slide_assets_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"
            _write_multi_asset_pptx(source)
            inventory = mine_sources(root, root / "assets")
            slide = next(item for item in inventory["source_slides"] if item["slide"] == 1)
            asset_ids = slide["asset_ids"]
            self.assertGreaterEqual(len(asset_ids), 6)
            self.assertEqual(len(asset_ids), len(set(asset_ids)))
            self.assertTrue({"definition", "table", "image", "diagram"} <= {item["type"] for item in inventory["assets"] if item["id"] in asset_ids})
            self.assertTrue(all(item.get("source_slide_id") for item in inventory["assets"] if item["id"] in asset_ids))
            self.assertTrue(Path(inventory["asset_root"]).is_dir())

    def test_t16_shape_graph_preserves_connectors_and_rendered_visual(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "shape.pptx"
            _write_multi_asset_pptx(source)
            inventory = mine_sources(root, root / "assets")
            slide = next(item for item in inventory["source_slides"] if item["slide"] == 2)
            self.assertTrue(slide["shape_graph"]["connectors"])
            diagram = next(item for item in inventory["assets"] if item.get("rendered_visual_ref"))
            self.assertTrue((root / "assets" / diagram["rendered_visual_ref"]).is_file())
            self.assertEqual(diagram["structured_parse_status"], "complete")

    def test_t17_planned_visual_without_dom_is_not_observed(self) -> None:
        result = collect_visual_evidence({"visual_plans": [{"page_id": "p1", "artifact_type": "class_model", "required_semantic_elements": ["class", "relationship"]}]}, "<html><body></body></html>")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["visual_plans"][0]["evidence_status"], "PLANNED_NOT_OBSERVED")

    def test_t18_rendered_visual_markers_pass_through_nested_dom(self) -> None:
        html = '<section data-page-id="p1"><div><figure data-artifact-type="class_model" data-semantic-role="class relationship multiplicity" data-source-asset-id="asset-1"><svg></svg></figure></div></section>'
        result = collect_visual_evidence({"visual_plans": [{"page_id": "p1", "artifact_type": "class_model", "required_semantic_elements": ["class", "relationship", "multiplicity"]}]}, html)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["visual_plans"][0]["evidence_status"], "PASS")
        self.assertEqual(result["rendered_asset_ids"], ["asset-1"])

    def test_t19_starter_plan_without_file_is_not_observed(self) -> None:
        plan = typed_starter("class_model")
        result = collect_starter_evidence(plan["components"] + [f"editable_gap:{item['type']}" for item in plan["editable_gaps"]], plan, None)
        self.assertEqual(result["status"], "NOT_OBSERVED")
        self.assertEqual(result["starter_observed"], [])

    def test_t20_real_drawio_starter_observes_typed_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "starter.drawio"
            path.write_text(_drawio_starter({"artifact_type": "class_model"}), encoding="utf-8")
            plan = typed_starter("class_model")
            result = collect_starter_evidence(plan["components"] + [f"editable_gap:{item['type']}" for item in plan["editable_gaps"]], plan, path)
            self.assertEqual(result["status"], "PASS")
            self.assertIn("partial_classes", result["starter_observed"])
            self.assertIn("missing_multiplicity", result["starter_observed"])

    def test_t21_release_requires_time_evidence(self) -> None:
        course = _minimal_course(with_minutes=False)
        with self.assertRaises(OrchestrationError):
            build_plans(course, build_graph(course), _inventory())

    def test_t22_draft_without_time_evidence_is_explicitly_degraded(self) -> None:
        course = _minimal_course(mode="draft", with_minutes=False)
        plan = build_plans(course, build_graph(course), _inventory())
        self.assertEqual(plan["sessions"][0]["timing_status"], "DEGRADED_ESTIMATE")
        self.assertTrue(plan["sessions"][0]["timing_reasons"])

    def test_t23_asset_reference_alone_is_not_actual_usage(self) -> None:
        session_plans = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "primary_job": "define", "layout": "focus", "source_asset_ids": ["asset-1"]}]}]}
        report = review_course(session_plans, {"sessions": []}, {"sessions": []}, _inventory("asset-1"))
        usage = report["metrics"]["teaching_asset_usage"]
        self.assertEqual(usage["selected_assets"], ["asset-1"])
        self.assertEqual(usage["actually_used"], [])

    def test_t24_rendered_asset_marker_counts_as_actual_usage(self) -> None:
        session_plans = {"sessions": [{"id": "s1", "pages": [{"id": "p1", "title": "关系", "primary_job": "define", "layout": "focus", "source_asset_ids": ["asset-1"]}]}]}
        result = review_rendered_course(session_plans, {"sessions": []}, {"sessions": []}, _inventory("asset-1"), visual_evidence={"status": "PASS", "visual_plans": [], "rendered_asset_ids": ["asset-1"]}, starter_evidence={"status": "PASS"}, rendered_course={"sessions": [{"id": "s1", "pages": [{"id": "p1", "title": "关系", "speaker_script": "关系页面说明依据。"}]}]}, contact_sheet={"status": "DEGRADED", "thumbnail_count": 1})
        self.assertEqual(result["metrics"]["render_evidence"]["actual_asset_usage"]["status"], "PASS")
        self.assertNotIn("SOURCE_MATERIAL_UNDERUTILIZED", {item["code"] for item in result["findings"]})

    def test_t25_source_mapping_prevents_false_missing_visual_gap(self) -> None:
        graph = {"nodes": [{"id": "model", "title": "关系模型", "source_assets": ["asset-1"]}]}
        inventory = {"assets": [{"id": "asset-1", "type": "diagram", "teaching_value": "core"}]}
        links = resolve_asset_knowledge_links(graph, inventory)
        gaps = detect_gaps(graph, inventory, links)
        self.assertNotIn("missing_visual", {item["type"] for item in gaps})

    def test_t26_true_missing_visual_gap_remains(self) -> None:
        graph = {"nodes": [{"id": "model", "title": "关系模型", "source_assets": []}]}
        gaps = detect_gaps(graph, {"assets": []})
        self.assertIn("missing_visual", {item["type"] for item in gaps})

    def test_t27_structural_practice_similarity_ignores_knowledge_ids(self) -> None:
        practice = {"sessions": [{"id": "s1", "tasks": [{"id": "t1", "capability": "construct", "artifact_type": "class_model", "knowledge_node_ids": ["n1"], "estimated_minutes": 30, "structural_task_signature": "same-shape", "semantic_task_signature": "semantic-1", "starter": {"artifact_type": "class_model", "components": ["partial_classes"]}}]}, {"id": "s2", "tasks": [{"id": "t2", "capability": "construct", "artifact_type": "class_model", "knowledge_node_ids": ["n2"], "estimated_minutes": 30, "structural_task_signature": "same-shape", "semantic_task_signature": "semantic-2", "starter": {"artifact_type": "class_model", "components": ["partial_classes"]}}]}]}
        report = review_course({"sessions": []}, practice, {"sessions": []}, {"assets": []})
        self.assertEqual(report["metrics"]["practice_task_signatures"], [["same-shape"], ["same-shape"]])
        self.assertNotEqual(report["metrics"]["practice_semantic_task_signatures"][0], report["metrics"]["practice_semantic_task_signatures"][1])

    def test_t28_near_identical_course_cluster_triggers_collapse_gate(self) -> None:
        sessions = [{"id": f"s{index}", "pages": [{"id": f"p{index}", "primary_job": "define", "layout": "focus", "layout_family": ["focus", "split"], "lecture_minutes": 8, "activity_minutes": 2, "block_signature": ["question", "explanation"]}]} for index in range(8)]
        report = review_course({"sessions": sessions}, {"sessions": []}, {"sessions": []}, {"assets": []})
        self.assertIn("WHOLE_COURSE_TEMPLATE_COLLAPSE", {item["code"] for item in report["findings"]})
        self.assertEqual(report["metrics"]["similarity_calibration"]["pair_threshold"], 0.85)

    def test_t29_final_script_is_read_from_rendered_courseware_output(self) -> None:
        result = review_rendered_course({"sessions": [{"id": "s1", "pages": [{"id": "p1", "title": "真实页面", "primary_job": "define", "layout": "focus"}]}]}, {"sessions": []}, {"sessions": []}, {"assets": []}, visual_evidence={"status": "PASS", "visual_plans": [], "rendered_asset_ids": []}, starter_evidence={"status": "PASS"}, rendered_course={"sessions": [{"id": "s1", "pages": [{"id": "p1", "title": "真实页面", "speaker_script": "真实页面讲稿说明证据和判断。"}]}]}, contact_sheet={"status": "DEGRADED", "thumbnail_count": 1})
        self.assertEqual(result["metrics"]["render_evidence"]["script_to_slide_grounding"]["status"], "PASS")
        self.assertNotIn("SCRIPT_TO_SLIDE_GROUNDING_INCOMPLETE", {item["code"] for item in result["findings"]})

    def test_t33_rendered_script_reuse_is_not_ignored(self) -> None:
        script = "请学生观察页面证据并说明判断依据，再检查遗漏条件。"
        rendered = {"sessions": [{"id": f"s{index}", "pages": [{"id": f"p{index}", "title": f"页面{index}", "speaker_script": script}]} for index in range(3)]}
        result = review_rendered_course({"sessions": []}, {"sessions": []}, {"sessions": []}, {"assets": []}, visual_evidence={"status": "PASS", "visual_plans": [], "rendered_asset_ids": []}, starter_evidence={"status": "PASS"}, rendered_course=rendered, contact_sheet={"status": "DEGRADED", "thumbnail_count": 3})
        self.assertIn("SCRIPT_CROSS_SESSION_TEMPLATE_REUSE", {item["code"] for item in result["findings"]})
        self.assertEqual(result["final_status"], "FAIL")

    def test_t30_frozen_failure_benchmark_and_old_shape_still_fail(self) -> None:
        benchmark = json.loads((SKILL_ROOT.parents[1] / "benchmarks" / "WHOLE_COURSE_FAILURE_BENCHMARK_V1" / "whole-course-failure-benchmark.json").read_text(encoding="utf-8"))
        expected = set(benchmark["failure_findings"]["theory"]["finding_codes"] + benchmark["failure_findings"]["practice"]["finding_codes"])
        sessions = [{"id": f"s{index}", "pages": [{"id": f"p{index}", "primary_job": "define", "layout": "focus", "lecture_minutes": 8, "activity_minutes": 2, "block_signature": ["question", "explanation"], "speaker_script": "同一模板讲稿。"}]} for index in range(8)]
        practice = {"sessions": [{"id": f"s{index}", "tasks": [{"id": f"t{index}", "capability": "construct", "artifact_type": "class_model", "estimated_minutes": 60, "structural_task_signature": "old-fixed-shape", "starter": {"artifact_type": "class_model", "components": ["partial_classes"]}}]} for index in range(8)]}
        report = review_course({"sessions": sessions}, practice, {"sessions": []}, {"assets": []})
        self.assertTrue(expected <= {item["code"] for item in report["findings"]})
        self.assertEqual(benchmark["failure_findings"]["status"], "FAIL")

    def test_t31_real_three_session_downstream_e2e_reaches_both_renderers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = run_synthetic_e2e(temp, use_browser=False)
            self.assertEqual(result["status"], "WHOLE_COURSE_ARCHITECTURE_BLOCKED")
            self.assertEqual(result["browser_smoke_status"], "UNAVAILABLE_OR_DEGRADED")
            self.assertEqual(len(result["courseware"]), 3)
            self.assertEqual(len(result["practice"]), 3)
            self.assertEqual(result["visual_evidence"]["status"], "PASS")
            self.assertEqual(result["starter_evidence"]["status"], "PASS")
            self.assertTrue(all(Path(item["student_html"]).is_file() for item in result["courseware"]))
            self.assertTrue(all(Path(item["student_dir"]).is_dir() for item in result["practice"]))

    def test_t32_contact_sheet_contains_real_artifact_thumbnails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            student = root / "student.html"
            student.write_text('<!doctype html><section data-page-id="p1"><h1>Page</h1><p>Evidence</p></section>', encoding="utf-8")
            starter = root / "student" / "starter"
            starter.mkdir(parents=True)
            (starter / "starter.drawio").write_text(_drawio_starter({"artifact_type": "class_model"}), encoding="utf-8")
            result = build_contact_sheets([{"id": "s1", "title": "Theory", "student_html": str(student)}], [{"id": "p1", "title": "Practice", "student_dir": str(root / "student"), "tasks": [{"id": "t1", "title": "Task", "estimated_minutes": 20}]}], root / "contact", use_browser=False)
            self.assertEqual(result["status"], "DEGRADED")
            self.assertGreaterEqual(result["thumbnail_count"], 2)
            self.assertTrue(all(Path(path).is_file() for path in result["thumbnail_paths"]))
            self.assertIn("<img", (root / "contact" / "course-contact-sheet.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
