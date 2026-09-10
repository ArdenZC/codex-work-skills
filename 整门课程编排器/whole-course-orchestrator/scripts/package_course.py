"""Create a clean teacher-facing course package and separate evidence tree."""

from __future__ import annotations

import argparse
import html
import shutil
import tempfile
from pathlib import Path
from typing import Any

from orchestrator_core import dump_json, html_page, load_json, safe_filename


def _require_file(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"required file does not exist: {path}")
    return path


def _require_dir(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"required directory does not exist: {path}")
    return path


def _copy_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name in {"student-package", "teacher-package"}:
            continue
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination, dirs_exist_ok=True)
        elif child.is_file():
            shutil.copy2(child, destination)


def _write_overview(root: Path, manifest: dict[str, Any], qa: dict[str, Any] | None) -> None:
    overview = root / "00_课程总览"
    overview.mkdir(parents=True, exist_ok=True)
    course_name = str(manifest.get("course_name") or "课程")
    theory = manifest.get("theory_sessions", [])
    practice = manifest.get("practice_sessions", [])
    status = (qa or {}).get("architecture_status", "NOT_REVIEWED")
    theory_rows = "".join(f"<tr><td>{html.escape(str(item.get('id')))}</td><td>{html.escape(str(item.get('title')))}</td><td>{len(item.get('pages', [])) if item.get('pages') else '见课件'}</td></tr>" for item in theory)
    practice_rows = "".join(f"<tr><td>{html.escape(str(item.get('id')))}</td><td>{html.escape(str(item.get('title')))}</td><td>{html.escape(str(item.get('task_count', '见资料')))}</td></tr>" for item in practice)
    body = (
        f"<h1>{html.escape(course_name)}</h1><p>课程级编排包。架构状态：<strong>{html.escape(status)}</strong></p>"
        "<p>理论课与实践课由下游 Skill 生成；本目录只负责清晰的课程级组织与证据入口。</p>"
        "<h2>理论课</h2><table><tr><th>课次</th><th>标题</th><th>页数</th></tr>" + theory_rows + "</table>"
        "<h2>实践课</h2><table><tr><th>课次</th><th>标题</th><th>任务数</th></tr>" + practice_rows + "</table>"
        "<p>完整来源、知识图谱、批量 QA 和研究 provenance 位于 <code>../_evidence/</code>。</p>"
    )
    (overview / "课程总览.html").write_text(html_page(course_name, body), encoding="utf-8")


def _write_dashboards(root: Path, manifest: dict[str, Any], evidence: dict[str, Any]) -> None:
    overview = root / "00_课程总览"
    assets = evidence.get("assets", {}).get("assets", [])
    qa = evidence.get("qa", {})
    graph = evidence.get("knowledge_graph", {})
    visual = evidence.get("visual_plans", {}).get("visual_plans", [])
    research = evidence.get("research", {})

    asset_rows = "".join(
        f"<tr><td>{html.escape(str(asset.get('id')))}</td><td>{html.escape(str(asset.get('type')))}</td><td>{html.escape(str(asset.get('teaching_value')))}</td><td>{html.escape(str(asset.get('source_locator')))}</td></tr>"
        for asset in assets
    ) or "<tr><td colspan='4'>暂无素材记录</td></tr>"
    (overview / "source-usage-dashboard.html").write_text(html_page("Source usage dashboard", "<h1>Source usage dashboard</h1><p>高价值素材是否被选择与实际使用由 QA evidence 追踪。</p><table><tr><th>ID</th><th>类型</th><th>教学价值</th><th>来源定位</th></tr>" + asset_rows + "</table>"), encoding="utf-8")

    graph_rows = "".join(
        f"<tr><td>{html.escape(str(session.get('id')))}</td><td>{html.escape(str(session.get('title')))}</td><td>{html.escape(', '.join(session.get('new_knowledge', [])))}</td><td>{html.escape(', '.join(session.get('review_knowledge', [])))}</td><td>{html.escape(', '.join(session.get('future_knowledge', [])))}</td></tr>"
        for session in graph.get("sessions", [])
    ) or "<tr><td colspan='5'>暂无知识图谱记录</td></tr>"
    (overview / "knowledge-progression.html").write_text(html_page("Knowledge progression", "<h1>Knowledge progression</h1><table><tr><th>Session</th><th>Title</th><th>New</th><th>Review</th><th>Future</th></tr>" + graph_rows + "</table>"), encoding="utf-8")

    visual_rows = "".join(
        f"<tr><td>{html.escape(str(item.get('page_id')))}</td><td>{html.escape(str(item.get('artifact_type')))}</td><td>{html.escape(str(item.get('visual_intent')))}</td><td>{html.escape(', '.join(item.get('semantic_elements', [])))}</td><td>{html.escape(str(item.get('render_strategy')))}</td></tr>"
        for item in visual
    ) or "<tr><td colspan='5'>暂无视觉计划</td></tr>"
    (overview / "visual-gallery.html").write_text(html_page("Visual gallery", "<h1>Visual gallery</h1><p>这是语义视觉审计索引；真实 HTML 渲染后的缩略图由下游 renderer/人工检查补充。</p><table><tr><th>Page</th><th>Artifact</th><th>Intent</th><th>Semantic elements</th><th>Strategy</th></tr>" + visual_rows + "</table>"), encoding="utf-8")

    contact_rows = "".join(f"<tr><td>{html.escape(str(item.get('id')))}</td><td>{html.escape(str(item.get('title')))}</td><td>{html.escape(str(len(item.get('pages', []))))}</td></tr>" for item in manifest.get("theory_sessions", [])) or "<tr><td colspan='3'>暂无课次</td></tr>"
    (overview / "course-contact-sheet.html").write_text(html_page("Course contact sheet", "<h1>Course contact sheet</h1><table><tr><th>Session</th><th>Title</th><th>Planned pages</th></tr>" + contact_rows + "</table>"), encoding="utf-8")

    practice_rows = "".join(f"<tr><td>{html.escape(str(item.get('id')))}</td><td>{html.escape(str(item.get('title')))}</td><td>{html.escape(str(item.get('task_count', '')))}</td></tr>" for item in manifest.get("practice_sessions", [])) or "<tr><td colspan='3'>暂无实践课</td></tr>"
    (overview / "practice-contact-sheet.html").write_text(html_page("Practice contact sheet", "<h1>Practice contact sheet</h1><table><tr><th>Session</th><th>Title</th><th>Tasks</th></tr>" + practice_rows + "</table>"), encoding="utf-8")

    source_counts = {
        "user_sources": len([item for item in assets if item.get("origin_type") == "user-provided"]),
        "external_sources": len(research.get("sources", [])),
        "external_selected": research.get("selected_source_count", 0),
    }
    portfolio = "<h1>Source portfolio</h1><p>User materials define the course; external sources enrich it.</p><ul>" + "".join(f"<li>{html.escape(key)}: {value}</li>" for key, value in source_counts.items()) + "</ul>"
    portfolio += "<h2>Research status</h2><p>" + html.escape(str(research.get("research_status", "not-run"))) + "</p>"
    (overview / "source-portfolio.html").write_text(html_page("Source portfolio", portfolio), encoding="utf-8")


def package_course(manifest: dict[str, Any], output_dir: Path, *, replace: bool = False) -> Path:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and not replace:
        raise ValueError(f"output exists; use replace explicitly: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{safe_filename(manifest.get('course_name', 'course'))}.stage-", dir=str(output_dir.parent)))
    try:
        course_root = stage / safe_filename(str(manifest.get("course_name") or "课程"))
        theory_root = course_root / "理论课"
        practice_root = course_root / "实践课"
        evidence_root = course_root / "_evidence"
        for index, item in enumerate(manifest.get("theory_sessions", []), start=1):
            session_root = theory_root / f"{index:02d}_{safe_filename(str(item.get('title') or item.get('id') or f'session-{index}'))}"
            session_root.mkdir(parents=True, exist_ok=True)
            student_target = session_root / "学生课件.html"
            teacher_target = session_root / "教师备课.html"
            shutil.copy2(_require_file(item["student_html"]), student_target)
            shutil.copy2(_require_file(item["teacher_html"]), teacher_target)
        for index, item in enumerate(manifest.get("practice_sessions", []), start=1):
            session_root = practice_root / f"{index:02d}_{safe_filename(str(item.get('title') or item.get('id') or f'session-{index}'))}"
            _copy_contents(_require_dir(item["student_dir"]), session_root / "学生资料")
            _copy_contents(_require_dir(item["teacher_dir"]), session_root / "教师资料")

        evidence_root.mkdir(parents=True, exist_ok=True)
        evidence_map: dict[str, Any] = {}
        for label, source in (manifest.get("evidence") or {}).items():
            source_path = Path(source).expanduser().resolve()
            destination = evidence_root / safe_filename(label)
            if source_path.is_file():
                shutil.copy2(source_path, destination.with_suffix(source_path.suffix))
                evidence_map[label] = destination.with_suffix(source_path.suffix).relative_to(course_root).as_posix()
            elif source_path.is_dir():
                shutil.copytree(source_path, destination, dirs_exist_ok=True)
                evidence_map[label] = destination.relative_to(course_root).as_posix()
            else:
                raise ValueError(f"evidence path does not exist: {source_path}")
        dump_json({"schema_version": "1.0", "evidence": evidence_map}, evidence_root / "package-manifest.json")
        evidence = {}
        for key, path in manifest.get("evidence_data", {}).items():
            evidence[key] = load_json(path)
        _write_overview(course_root, manifest, evidence.get("qa"))
        _write_dashboards(course_root, manifest, evidence)
        forbidden = [path for path in course_root.rglob("*") if path.is_dir() and "student-package" in path.as_posix().lower()]
        if forbidden:
            raise ValueError(f"duplicate student/package tree detected: {forbidden}")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        stage_course = stage / course_root.name
        shutil.move(str(stage_course), str(output_dir))
        stage.rmdir()
        return output_dir
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = package_course(load_json(args.package_json), Path(args.output_dir), replace=args.replace)
    if args.json:
        print({"output_dir": str(result), "status": "ok"})


if __name__ == "__main__":
    main()
