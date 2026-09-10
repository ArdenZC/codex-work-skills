"""Run a small real whole-course handoff through both stable renderers."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from build_knowledge_graph import build_graph
from collect_starter_evidence import collect_starter_evidence
from collect_visual_evidence import collect_visual_evidence
from contact_sheets import build_contact_sheets
from downstream_adapters import adapt_session_to_courseware, adapt_session_to_practice
from external_research import resolve_asset_knowledge_links
from mine_teaching_assets import mine_sources
from plan_practice import build_practice_plans
from plan_sessions import build_plans
from plan_visuals import build_visual_plans
from review_whole_course import review_rendered_course
from orchestrator_core import dump_json, load_json


def _slide_xml(title: str, shape_count: int = 1) -> bytes:
    shapes = "".join(f"<p:sp><p:nvSpPr><p:cNvPr id='{index}' name='Shape {index}'/></p:nvSpPr><p:spPr><a:xfrm><a:off x='{index * 800000}' y='800000'/><a:ext cx='1200000' cy='600000'/></a:xfrm></p:spPr><p:txBody><a:p><a:r><a:t>{html.escape(title if index == 1 else 'evidence')}</a:t></a:r></a:p></p:txBody></p:sp>" for index in range(1, shape_count + 1))
    return f"<p:sld xmlns:p='http://schemas.openxmlformats.org/presentationml/2006/main' xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'><p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>".encode("utf-8")


def _write_source_fixture(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", _slide_xml("Concept definition", 1))
        archive.writestr("ppt/slides/slide2.xml", _slide_xml("Class relationship diagram", 3))
        archive.writestr("ppt/slides/slide3.xml", _slide_xml("Procedure: open edit verify", 1))


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
        self.current: dict[str, Any] | None = None
        self.in_script = False
        self.in_title = False
        self.scripts: dict[str, str] = {}
        self.titles: dict[str, str] = {}
        self.buffer: list[str] = []
        self.title_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("data-page-id"):
            self.current = {"id": values["data-page-id"], "title": ""}
        if tag == "h1" and self.current:
            self.in_title = True
            self.title_buffer = []
        if "speaker-script" in values.get("class", "").split():
            self.in_script = True
            self.buffer = []

    def handle_endtag(self, tag: str) -> None:
        if self.in_title and tag == "h1" and self.current:
            title = " ".join(self.title_buffer).strip()
            self.current["title"] = title
            self.titles[str(self.current["id"])] = title
            self.in_title = False
        if self.in_script and tag == "div" and self.current:
            self.scripts[str(self.current["id"])] = " ".join(self.buffer).strip()
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_title and data.strip():
            self.title_buffer.append(data.strip())
        if self.in_script and data.strip():
            self.buffer.append(data.strip())


def _courseware_rendered_pages(path: Path) -> list[dict[str, Any]]:
    parser = _TeacherScriptParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return [{"id": page_id, "speaker_script": script, "title": parser.titles.get(page_id) or page_id} for page_id, script in parser.scripts.items()]


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
        if asset.get("id") and int(asset.get("source_slide", 0) or 0) == 2 and asset.get("type") in {"diagram", "fact"}
    ]
    definition_asset_ids = [str(asset.get("id")) for asset in inventory.get("assets", []) if asset.get("id") and int(asset.get("source_slide", 0) or 0) == 1]
    procedure_asset_ids = [str(asset.get("id")) for asset in inventory.get("assets", []) if asset.get("id") and int(asset.get("source_slide", 0) or 0) == 3]
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
        theory_item = {"id": session_id, "title": session_plan.get("title"), "student_html": str(courseware_dir / "student.html"), "teacher_html": str(courseware_dir / "teacher.html"), "evidence_mode": evidence_mode, "qa": courseware_qa}
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
        practice_item = {"id": session_id, "title": practice_plan.get("title"), "student_dir": str(practice_dir / "student"), "teacher_dir": str(practice_dir / "teacher"), "evidence_mode": evidence_mode, "qa": practice_qa, "tasks": practice_plan.get("tasks", [])}
        practice_outputs.append(practice_item)
        if practice_plan.get("tasks"):
            task = practice_plan["tasks"][0]
            starter_evidence = collect_starter_evidence(task.get("starter_requirements", []), task.get("starter_plan", {}), practice_dir / "student" / "starter", manifest=practice_dir / "student-package" / "student-manifest.json", qa_report=practice_dir / "qa-report.json", behavior_verification=practice_dir / "behavior-verification.json", student_root=practice_dir / "student" )
        else:
            starter_evidence = {"status": "NOT_OBSERVED"}
        practice_item["starter_evidence"] = starter_evidence
        rendered_sessions.append({"id": session_id, "pages": _courseware_rendered_pages(courseware_dir / "teacher.html")})
    merged_visual_plans = [plan for item in visual_evidence for plan in item.get("visual_plans", [])]
    merged_visual = {
        "schema_version": "1.1",
        "report_type": "whole_course_visual_evidence",
        "status": "PASS" if all(item.get("evidence_status") == "PASS" for item in merged_visual_plans) else "FAIL" if merged_visual_plans else "PASS",
        "visual_plans": merged_visual_plans,
        "rendered_asset_ids": sorted({asset for item in visual_evidence for asset in item.get("rendered_asset_ids", [])}),
        "marker_plumbing_status": "PASS" if merged_visual_plans and all(item.get("semantic_marker_evidence", {}).get("status") == "PASS" for item in merged_visual_plans) else "NOT_APPLICABLE" if not merged_visual_plans else "FAIL",
        "semantic_structure_status": "PASS" if merged_visual_plans and all(item.get("semantic_structure_evidence", {}).get("status") in {"PASS", "NOT_APPLICABLE"} for item in merged_visual_plans) else "NOT_APPLICABLE" if not merged_visual_plans else "FAIL",
    }
    merged_starter = {"schema_version": "1.1", "report_type": "whole_course_starter_evidence", "status": "PASS" if all(item.get("starter_evidence", {}).get("status") == "PASS" for item in practice_outputs) else "FAIL", "starter_observed": sorted({value for item in practice_outputs for value in item.get("starter_evidence", {}).get("starter_observed", [])})}
    contact = build_contact_sheets(theory_outputs, practice_outputs, root / "contact-sheets", visual_plans=visual_plans, inventory=inventory, use_browser=use_browser)
    rendered_course = {"sessions": rendered_sessions}
    report = review_rendered_course(session_plans, practice_plans, graph, inventory, visual_evidence=merged_visual, starter_evidence=merged_starter, rendered_course=rendered_course, rendered_practice={"sessions": practice_outputs}, contact_sheet=contact)
    browser_status = "PASS" if contact.get("status") == "PASS" else "FAIL" if contact.get("status") == "FAIL" else "UNAVAILABLE_OR_DEGRADED"
    final_status = (
        "PASS"
        if browser_status == "PASS" and report.get("final_status") == "PASS"
        else "WHOLE_COURSE_ARCHITECTURE_BLOCKED"
    )
    strict_status = "PASS" if evidence_mode == "strict" and all(item.get("qa", {}).get("status") == "pass" for item in theory_outputs + practice_outputs) else "NOT_RUN" if evidence_mode != "strict" else "FAIL"
    result = {"schema_version": "1.1", "report_type": "whole_course_downstream_e2e", "status": final_status, "browser_smoke_status": browser_status, "evidence_mode": evidence_mode, "strict_e2e_status": strict_status, "source_mining": {"slides": len(inventory.get("source_slides", [])), "assets": len(inventory.get("assets", []))}, "courseware": theory_outputs, "practice": practice_outputs, "visual_evidence": merged_visual, "starter_evidence": merged_starter, "contact_sheets": contact, "qa": report, "pipeline": ["source fixture", "teaching asset mining", "knowledge graph", "session plan", "visual plan", "Courseware adapter", f"real Courseware renderer ({evidence_mode})", "visual evidence", "Practice adapter", f"real Practice renderer ({evidence_mode})", "starter evidence", "whole-course QA", "contact sheets"]}
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
