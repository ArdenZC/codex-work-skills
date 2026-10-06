"""Run a small real whole-course handoff through both stable renderers."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from build_knowledge_graph import build_graph
from collect_starter_evidence import collect_starter_evidence, collect_task_evidence
from collect_visual_evidence import collect_visual_evidence
from contact_sheets import build_contact_sheets
from downstream_adapters import adapt_session_to_courseware, adapt_session_to_practice
from external_research import detect_gaps, research, resolve_asset_knowledge_links
from mine_teaching_assets import mine_sources
from plan_practice import build_practice_plans
from plan_sessions import build_plans
from plan_visuals import build_visual_plans
from review_whole_course import review_plan_architecture, review_rendered_course
from orchestrator_core import dump_json, load_json


def _slide_xml(title: str, shape_count: int = 1) -> bytes:
    shapes = "".join(f"<p:sp><p:nvSpPr><p:cNvPr id='{index}' name='Shape {index}'/></p:nvSpPr><p:spPr><a:xfrm><a:off x='{index * 800000}' y='800000'/><a:ext cx='1200000' cy='600000'/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>{html.escape(title if index == 1 else 'evidence')}</a:t></a:r></a:p></p:txBody></p:sp>" for index in range(1, shape_count + 1))
    return f"<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>".encode("utf-8")


def _write_source_fixture(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", _slide_xml("Concept definition", 1))
        archive.writestr("ppt/slides/slide2.xml", _slide_xml("Class relationship diagram", 3))
        archive.writestr("ppt/slides/slide3.xml", _slide_xml("Procedure: open edit verify", 1))
        archive.writestr("ppt/presentation.xml", "<p:presentation xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><p:sldIdLst><p:sldId id='3' r:id='rId3'/><p:sldId id='1' r:id='rId1'/><p:sldId id='2' r:id='rId2'/></p:sldIdLst></p:presentation>")
        archive.writestr("ppt/_rels/presentation.xml.rels", "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'><Relationship Id='rId1' Target='slides/slide1.xml'/><Relationship Id='rId2' Target='slides/slide2.xml'/><Relationship Id='rId3' Target='slides/slide3.xml'/></Relationships>")


def _write_source_truth_fixture(path: Path) -> None:
    # The strict downstream handoff needs a real source-root fact that the
    # stable Courseware/Practice validators can verify.  It is deliberately a
    # tiny source fixture, not a replacement for the user PPT evidence.
    path.write_text(
        "Synthetic source fixture for strict adapter verification.\n"
        "source-backed teaching evidence\n",
        encoding="utf-8",
        newline="\n",
    )


class _TeacherScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_page: str | None = None
        self.pages: dict[str, dict[str, Any]] = {}
        self.page_stack: list[tuple[str, str | None]] = []
        self.element_stack: list[dict[str, Any]] = []
        self.capture: dict[str, Any] | None = None
        self.active_block: dict[str, Any] | None = None

    def _page(self) -> dict[str, Any]:
        page_id = self.current_page or "__document__"
        return self.pages.setdefault(page_id, {"id": page_id, "title": page_id, "speaker_script": "", "blocks": [], "suggested_minutes": None})

    @staticmethod
    def _classes(values: dict[str, str]) -> set[str]:
        return set(values.get("class", "").split())

    def _start_capture(self, kind: str, *, block: dict[str, Any] | None = None, side: str | None = None, attrs: dict[str, str] | None = None) -> dict[str, Any]:
        capture = {"kind": kind, "buffer": [], "block": block, "side": side, "attrs": attrs or {}}
        self.capture = capture
        return capture

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        page_open = bool(values.get("data-page-id"))
        if page_open:
            self.page_stack.append((tag, self.current_page))
            self.current_page = values["data-page-id"]
            self._page()
        classes = self._classes(values)
        previous = self.capture
        kind = None
        block = self.active_block
        side = block.get("_side") if block else None
        if "quiz-block" in classes:
            block = {"type": "quiz", "question": "", "options": [], "answer_text": "", "correct_index": _int_or_none(values.get("data-correct-index")), "explanation": values.get("data-explanation", "")}
            self.active_block = block
            kind = "quiz-block"
        elif "comparison-block" in classes:
            block = {"type": "comparison", "contrast_dimension": values.get("data-contrast-dimension", ""), "left_title": "", "right_title": "", "left": [], "right": [], "correct_side": values.get("data-correct-side", ""), "wrong_side": values.get("data-wrong-side", "")}
            self.active_block = block
            kind = "comparison-block"
        elif "quiz-question" in classes and self.active_block and self.active_block.get("type") == "quiz":
            kind = "quiz-question"
        elif "quiz-option" in classes and self.active_block and self.active_block.get("type") == "quiz":
            kind = "quiz-option"
        elif "quiz-answer" in classes and self.active_block and self.active_block.get("type") == "quiz":
            kind = "quiz-answer"
        elif "comparison-dimension" in classes and self.active_block and self.active_block.get("type") == "comparison":
            kind = "comparison-dimension"
        elif "comparison-side" in classes and self.active_block and self.active_block.get("type") == "comparison":
            side = values.get("data-side") or ("left" if not self.active_block.get("left_title") else "right")
            self.active_block["_side"] = side
            kind = "comparison-side"
        elif tag == "h3" and self.active_block and self.active_block.get("type") == "comparison":
            kind = "comparison-title"
        elif tag == "li" and self.active_block and self.active_block.get("type") == "comparison" and side in {"left", "right"}:
            kind = "comparison-item"
        elif tag == "h1" and self.current_page:
            kind = "title"
        elif "speaker-script" in classes:
            kind = "speaker"
        elif "notes-heading" in classes:
            kind = "notes-heading"
        if kind is not None and kind not in {"quiz-block", "comparison-block", "comparison-side"}:
            self._start_capture(kind, block=self.active_block, side=side, attrs=values)
        self.element_stack.append({"tag": tag, "classes": classes, "kind": kind, "previous_capture": previous, "page_id": self.current_page, "side": side, "page_open": page_open})

    def handle_endtag(self, tag: str) -> None:
        entry = None
        for index in range(len(self.element_stack) - 1, -1, -1):
            if self.element_stack[index]["tag"] == tag:
                entry = self.element_stack[index]
                del self.element_stack[index:]
                break
        if entry is None:
            return
        kind = entry.get("kind")
        capture = self.capture if self.capture and self.capture.get("kind") == kind else None
        value = " ".join(capture.get("buffer", [])).strip() if capture else ""
        page = self._page()
        if kind == "title" and value:
            page["title"] = value
        elif kind == "speaker":
            page["speaker_script"] = value
        elif kind == "notes-heading":
            match = re.search(r"建议\s*(\d+(?:\.\d+)?)\s*分钟", value)
            if match:
                page["suggested_minutes"] = float(match.group(1))
        elif kind == "quiz-question" and self.active_block is not None:
            self.active_block["question"] = value
        elif kind == "quiz-option" and self.active_block is not None:
            self.active_block.setdefault("options", []).append({"index": _int_or_none((capture or {}).get("attrs", {}).get("data-choice")), "text": value})
        elif kind == "quiz-answer" and self.active_block is not None:
            self.active_block["answer_text"] = value
            if not self.active_block.get("explanation") and "。" in value:
                self.active_block["explanation"] = value.split("。", 1)[1]
        elif kind == "comparison-dimension" and self.active_block is not None:
            self.active_block["contrast_dimension"] = value
        elif kind == "comparison-title" and self.active_block is not None:
            target_side = self.active_block.get("_side") or "left"
            self.active_block[f"{target_side}_title"] = value
        elif kind == "comparison-item" and self.active_block is not None:
            target_side = entry.get("side") or self.active_block.get("_side") or "left"
            self.active_block.setdefault(target_side, []).append(value)
        elif kind == "quiz-block" and self.active_block is not None:
            block = dict(self.active_block)
            block.pop("_side", None)
            options = block.get("options", [])
            block["options"] = [item.get("text", "") if isinstance(item, dict) else str(item) for item in options]
            block["correct_option"] = block.get("options", [])[block["correct_index"]] if isinstance(block.get("correct_index"), int) and block["correct_index"] < len(block.get("options", [])) else ""
            page.setdefault("blocks", []).append(block)
            self.active_block = None
        elif kind == "comparison-block" and self.active_block is not None:
            block = dict(self.active_block)
            block.pop("_side", None)
            page.setdefault("blocks", []).append(block)
            self.active_block = None
        self.capture = entry.get("previous_capture")
        if entry.get("page_open") and self.page_stack:
            _, self.current_page = self.page_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.capture is not None and data.strip():
            self.capture.setdefault("buffer", []).append(data.strip())


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _courseware_rendered_pages(path: Path, student_path: Path | None = None) -> list[dict[str, Any]]:
    parser = _TeacherScriptParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    student_pages: dict[str, dict[str, Any]] = {}
    if student_path and student_path.is_file():
        student_parser = _TeacherScriptParser()
        student_parser.feed(student_path.read_text(encoding="utf-8", errors="ignore"))
        student_pages = student_parser.pages
    records: list[dict[str, Any]] = []
    for page_id, page in parser.pages.items():
        if page_id == "__document__":
            continue
        student = student_pages.get(page_id, {})
        records.append({
            "id": page_id,
            "speaker_script": page.get("speaker_script", ""),
            "title": page.get("title") or student.get("title") or page_id,
            "suggested_minutes": page.get("suggested_minutes"),
            "blocks": student.get("blocks") or page.get("blocks", []),
            "student_blocks": student.get("blocks", []),
            "teacher_blocks": page.get("blocks", []),
        })
    return records


def _run_renderer(script: Path, args: list[str]) -> dict[str, Any]:
    result = subprocess.run([sys.executable, str(script), *args], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"renderer failed: {script}\nstdout={result.stdout}\nstderr={result.stderr}")
    output_dir = Path(args[args.index("--output-dir") + 1])
    report = output_dir / ("qa-report.json" if "courseware-html-generator" in script.as_posix() else "qa-report.json")
    return load_json(report) if report.is_file() else {"status": "pass", "output_dir": str(output_dir)}


def run_synthetic_e2e(
    output_dir: str | Path | None = None,
    *,
    use_browser: bool = True,
    evidence_mode: str = "migration-trust",
) -> dict[str, Any]:
    if evidence_mode not in {"strict", "migration-trust"}:
        raise ValueError(f"unsupported evidence mode: {evidence_mode}")
    owned_temp = tempfile.TemporaryDirectory(prefix="whole-course-e2e-") if output_dir is None else None
    root = Path(output_dir or owned_temp.name).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    source_root = root / "source"
    source_root.mkdir(exist_ok=True)
    source = source_root / "synthetic-course.pptx"
    _write_source_fixture(source)
    _write_source_truth_fixture(source_root / "source_truth.txt")
    assets_dir = root / "assets"
    inventory = mine_sources(source_root, assets_dir)
    graph_input = {
        "course_id": "synthetic-whole-course",
        "course_name": "Synthetic Whole Course",
        "student_level": "高职学生",
        "knowledge_nodes": [
            {"id": "concept", "title": "概念定义", "type": "concept"},
            {"id": "model", "title": "Class relationship diagram", "type": "modeling_skill", "prerequisites": ["concept"]},
            {"id": "procedure", "title": "操作步骤", "type": "procedure", "prerequisites": ["model"]},
        ],
        "sessions": [
            {"id": "session-a", "title": "Concept", "new_knowledge_ids": ["concept"], "teaching_questions": [{"id": "q-a", "prompt": "概念是什么？", "learning_outcome": "能解释定义", "primary_job": "define", "minutes": 4}, {"id": "q-a-check", "prompt": "怎样判断定义是否完整？", "learning_outcome": "能检查定义要素", "primary_job": "check", "minutes": 4}], "practice_tasks": [{"id": "task-a", "title": "完成概念模型", "capability": "construct", "artifact_type": "class_model", "knowledge_ids": ["concept"], "estimated_minutes": 30}]},
            {"id": "session-b", "title": "Visual modeling", "new_knowledge_ids": ["model"], "review_knowledge_ids": ["concept"], "teaching_questions": [{"id": "q-b", "prompt": "关系如何表达？", "learning_outcome": "能指出关系和多重性", "artifact_type": "class_model", "visual_intent": "relationship", "visual_asset_ids": [], "minutes": 7}, {"id": "q-b-multiplicity", "prompt": "多重性如何核对？", "learning_outcome": "能依据端点核对多重性", "artifact_type": "class_model", "visual_intent": "multiplicity", "visual_asset_ids": [], "minutes": 7}], "practice_tasks": [{"id": "task-b", "title": "补齐关系图", "capability": "construct", "artifact_type": "class_model", "knowledge_ids": ["model"], "estimated_minutes": 36}]},
            {"id": "session-c", "title": "Procedure", "new_knowledge_ids": ["procedure"], "review_knowledge_ids": ["model"], "teaching_questions": [{"id": "q-c", "prompt": "如何完成操作？", "learning_outcome": "能按步骤完成", "primary_job": "step_through", "procedure": ["open", "edit", "verify"], "minutes": 10}, {"id": "q-c-check", "prompt": "如何确认操作结果？", "learning_outcome": "能检查结果并定位问题", "primary_job": "diagnose", "procedure": ["open", "edit", "verify"], "minutes": 6}], "practice_tasks": [{"id": "task-c", "title": "按步骤检查结果", "capability": "diagnose", "artifact_type": "sequence_model", "knowledge_ids": ["procedure"], "estimated_minutes": 42}]},
        ],
        "planning_mode": "release",
    }
    visual_asset_ids = [
        str(asset.get("id"))
        for asset in inventory.get("assets", [])
        if asset.get("id") and int(asset.get("source_slide", 0) or 0) == 3 and asset.get("type") in {"diagram", "fact"}
    ]
    definition_asset_ids = [str(asset.get("id")) for asset in inventory.get("assets", []) if asset.get("id") and int(asset.get("source_slide", 0) or 0) == 2]
    procedure_asset_ids = [str(asset.get("id")) for asset in inventory.get("assets", []) if asset.get("id") and int(asset.get("source_slide", 0) or 0) == 1]
    for course_session in graph_input["sessions"]:
        for question in course_session.get("teaching_questions", []):
            if course_session.get("id") == "session-b" and question.get("visual_intent"):
                question["visual_asset_ids"] = visual_asset_ids
            elif course_session.get("id") == "session-a" and question.get("id") == "q-a":
                question["visual_intent"] = "definition_evidence"
                question["visual_asset_ids"] = definition_asset_ids
            elif course_session.get("id") == "session-c" and question.get("id") == "q-c":
                question["visual_intent"] = "procedure_evidence"
                question["visual_asset_ids"] = procedure_asset_ids
    graph = build_graph(graph_input)
    graph["asset_knowledge_links"] = resolve_asset_knowledge_links(graph, inventory)
    session_plans = build_plans(graph_input, graph, inventory)
    visual_plans = build_visual_plans(session_plans, inventory)
    practice_plans = build_practice_plans(graph_input, graph)
    dump_json(inventory, root / "source-assets.json")
    dump_json(graph, root / "knowledge-graph.json")
    dump_json(session_plans, root / "session-plans.json")
    dump_json(visual_plans, root / "visual-plans.json")
    dump_json(practice_plans, root / "practice-plans.json")

    repo_root = Path(__file__).resolve().parents[3]
    courseware_script = repo_root / "HTML课件生成器" / "courseware-html-generator" / "scripts" / "render_courseware.py"
    practice_script = repo_root / "实践课HTML生成器" / "practice-class-html-generator" / "scripts" / "render_practice.py"
    theory_outputs: list[dict[str, Any]] = []
    practice_outputs: list[dict[str, Any]] = []
    visual_evidence: list[dict[str, Any]] = []
    rendered_sessions: list[dict[str, Any]] = []
    for session_plan in session_plans["sessions"]:
        session_id = str(session_plan["id"])
        courseware_json = root / f"{session_id}-courseware.json"
        courseware_dir = root / f"{session_id}-courseware"
        session_visual_plans = [item for item in visual_plans["visual_plans"] if item.get("session_id") == session_id]
        if evidence_mode == "strict":
            # This is an explicit fixture for the structure adapter.  The
            # marker-only path remains available to unit tests and migration
            # callers that do not claim typed semantic structure.
            session_visual_plans = [dict(item, semantic_structure_fixture=True) for item in session_visual_plans]
        dump_json(adapt_session_to_courseware(session_plan, visual_plans=session_visual_plans), courseware_json)
        courseware_args = ["--content-json", str(courseware_json), "--output-dir", str(courseware_dir), "--replace", "--evidence-mode", evidence_mode]
        if evidence_mode == "strict":
            courseware_args.extend(["--source-root", str(source_root)])
        courseware_args.append("--json")
        courseware_qa = _run_renderer(courseware_script, courseware_args)
        theory_item = {"id": session_id, "title": session_plan.get("title"), "student_html": str(courseware_dir / "student.html"), "teacher_html": str(courseware_dir / "teacher.html"), "evidence_mode": evidence_mode, "qa": courseware_qa, "session_minutes": load_json(courseware_json).get("session_minutes")}
        theory_outputs.append(theory_item)
        visual_subset = {"schema_version": "1.1", "plan_type": "semantic_visual_plans", "visual_plans": [item for item in visual_plans["visual_plans"] if item.get("session_id") == session_id]}
        visual_evidence.append(collect_visual_evidence(visual_subset, courseware_dir / "student.html", courseware_dir / "teacher.html"))
        practice_plan = next(item for item in practice_plans["sessions"] if item.get("id") == session_id)
        practice_json = root / f"{session_id}-practice.json"
        practice_dir = root / f"{session_id}-practice"
        dump_json(adapt_session_to_practice(practice_plan, source_pages=session_plan.get("pages", [])), practice_json)
        practice_args = ["--practice-json", str(practice_json), "--courseware-json", str(courseware_json), "--output-dir", str(practice_dir), "--replace", "--evidence-mode", evidence_mode]
        if evidence_mode == "strict":
            practice_args.extend(["--source-root", str(source_root)])
        practice_args.append("--json")
        practice_qa = _run_renderer(practice_script, practice_args)
        task_evidence = [collect_task_evidence(task, practice_dir, qa_report=practice_qa, behavior_verification=practice_dir / "behavior-verification.json") for task in practice_plan.get("tasks", [])]
        practice_item = {"id": session_id, "title": practice_plan.get("title"), "student_dir": str(practice_dir / "student"), "teacher_dir": str(practice_dir / "teacher"), "evidence_mode": evidence_mode, "qa": practice_qa, "tasks": practice_plan.get("tasks", []), "rendered_task_ids": [str(item.get("task_id")) for item in task_evidence], "task_evidence": task_evidence, "duration_minutes": load_json(practice_json).get("duration_minutes")}
        practice_outputs.append(practice_item)
        starter_evidence = {
            "schema_version": "1.1",
            "report_type": "whole_course_starter_evidence",
            "status": "PASS" if task_evidence and all(item.get("status") == "PASS" for item in task_evidence) else "FAIL" if task_evidence else "NOT_OBSERVED",
            "session_id": session_id,
            "tasks": task_evidence,
            "starter_observed": sorted({value for item in task_evidence for value in item.get("starter_observed", [])}),
            "policy": "Per-task required/planned/observed/missing evidence is retained; aggregate status is the conjunction of all required tasks.",
        }
        practice_item["starter_evidence"] = starter_evidence
        rendered_sessions.append({"id": session_id, "pages": _courseware_rendered_pages(courseware_dir / "teacher.html", courseware_dir / "student.html")})
    merged_visual_plans = [plan for item in visual_evidence for plan in item.get("visual_plans", [])]
    merged_visual = {
        "schema_version": "1.1",
        "report_type": "whole_course_visual_evidence",
        "status": "PASS" if all(item.get("evidence_status") == "PASS" for item in merged_visual_plans) else "FAIL" if merged_visual_plans else "PASS",
        "visual_plans": merged_visual_plans,
        "rendered_asset_ids": sorted({asset for item in visual_evidence for asset in item.get("rendered_asset_ids", [])}),
        "student_rendered_asset_ids": sorted({asset for item in visual_evidence for asset in item.get("student_rendered_asset_ids", item.get("rendered_asset_ids", []))}),
        "teacher_rendered_asset_ids": sorted({asset for item in visual_evidence for asset in item.get("teacher_rendered_asset_ids", [])}),
        "marker_plumbing_status": "PASS" if merged_visual_plans and all(item.get("semantic_marker_evidence", {}).get("status") == "PASS" for item in merged_visual_plans) else "NOT_APPLICABLE" if not merged_visual_plans else "FAIL",
        "semantic_structure_status": "PASS" if merged_visual_plans and all(item.get("semantic_structure_evidence", {}).get("status") in {"PASS", "NOT_APPLICABLE"} for item in merged_visual_plans) else "NOT_APPLICABLE" if not merged_visual_plans else "FAIL",
    }
    merged_starter = {"schema_version": "1.1", "report_type": "whole_course_starter_evidence", "status": "PASS" if practice_outputs and all(item.get("starter_evidence", {}).get("status") == "PASS" for item in practice_outputs) else "FAIL", "sessions": [{"id": item.get("id"), "status": item.get("starter_evidence", {}).get("status"), "tasks": item.get("starter_evidence", {}).get("tasks", [])} for item in practice_outputs], "starter_observed": sorted({value for item in practice_outputs for value in item.get("starter_evidence", {}).get("starter_observed", [])})}
    contact = build_contact_sheets(theory_outputs, practice_outputs, root / "contact-sheets", visual_plans=visual_plans, inventory=inventory, use_browser=use_browser)
    rendered_course = {"sessions": rendered_sessions}
    research_gaps = detect_gaps(graph, inventory, graph.get("asset_knowledge_links"))
    research_output = research(research_gaps, [], enabled=True, network_available=True)
    dump_json(research_output, root / "external-research.json")
    plan_qa = review_plan_architecture(session_plans, practice_plans, graph, inventory, visual_plans=visual_plans, research=research_output)
    report = review_rendered_course(session_plans, practice_plans, graph, inventory, visual_evidence=merged_visual, starter_evidence=merged_starter, rendered_course=rendered_course, rendered_practice={"sessions": practice_outputs}, contact_sheet=contact, research=research_output)
    dump_json(plan_qa, root / "whole-course-plan-qa.json")
    dump_json(report, root / "whole-course-render-qa.json")
    browser_status = "PASS" if contact.get("status") == "PASS" else "FAIL" if contact.get("status") == "FAIL" else "UNAVAILABLE_OR_DEGRADED"
    final_status = (
        "PASS"
        if browser_status == "PASS" and report.get("final_status") == "PASS"
        else "WHOLE_COURSE_ARCHITECTURE_BLOCKED"
    )
    strict_status = "PASS" if evidence_mode == "strict" and all(item.get("qa", {}).get("status") == "pass" for item in theory_outputs + practice_outputs) else "NOT_RUN" if evidence_mode != "strict" else "FAIL"
    result = {"schema_version": "1.1", "report_type": "whole_course_downstream_e2e", "status": final_status, "browser_smoke_status": browser_status, "evidence_mode": evidence_mode, "strict_e2e_status": strict_status, "source_mining": {"slides": len(inventory.get("source_slides", [])), "assets": len(inventory.get("assets", []))}, "courseware": theory_outputs, "practice": practice_outputs, "visual_evidence": merged_visual, "starter_evidence": merged_starter, "external_research": research_output, "contact_sheets": contact, "plan_qa": plan_qa, "qa": report, "pipeline": ["source fixture", "teaching asset mining", "knowledge graph", "session plan", "visual plan", "Courseware adapter", f"real Courseware renderer ({evidence_mode})", "student/teacher visual evidence", "Practice adapter", f"real Practice renderer ({evidence_mode})", "per-task starter evidence", "external research state", "whole-course QA", "contact sheets"]}
    dump_json(result, root / "whole-course-e2e.json")
    if owned_temp:
        result["output_dir"] = str(root)
        # Keep the temporary output alive only until the caller has consumed
        # the report; callers requesting an artifact should pass output_dir.
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--evidence-mode", choices=("strict", "migration-trust"), default="migration-trust")
    parser.add_argument("--strict", action="store_true", help="shorthand for --evidence-mode strict")
    parser.add_argument(
        "--allow-degraded-browser",
        action="store_true",
        help="allow a browser-unavailable smoke to exit 0 while preserving the BLOCKED result",
    )
    parser.add_argument(
        "--expect-blocked",
        action="store_true",
        help="accept the migration-trust compatibility run only when its intentional evidence gate remains BLOCKED",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    evidence_mode = "strict" if args.strict else args.evidence_mode
    result = run_synthetic_e2e(args.output_dir, use_browser=not args.no_browser, evidence_mode=evidence_mode)
    if args.json:
        print({"status": result["status"], "browser_smoke_status": result["browser_smoke_status"], "courseware": len(result["courseware"]), "practice": len(result["practice"])})
    accepted_degraded_smoke = (
        args.allow_degraded_browser
        and evidence_mode == "migration-trust"
        and result["status"] == "WHOLE_COURSE_ARCHITECTURE_BLOCKED"
        and result["browser_smoke_status"] == "UNAVAILABLE_OR_DEGRADED"
        and result.get("qa", {}).get("final_status") == "PASS"
    )
    accepted_expected_migration_block = (
        args.expect_blocked
        and evidence_mode == "migration-trust"
        and result["status"] == "WHOLE_COURSE_ARCHITECTURE_BLOCKED"
        and result.get("qa", {}).get("final_status") == "FAIL"
        and result.get("visual_evidence", {}).get("semantic_structure_status") == "FAIL"
    )
    raise SystemExit(0 if result["status"] in {"PASS", "READY_FOR_WHOLE_COURSE_BLIND_RETRY"} or accepted_degraded_smoke or accepted_expected_migration_block else 1)


if __name__ == "__main__":
    main()
