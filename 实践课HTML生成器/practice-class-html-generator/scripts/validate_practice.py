"""Validate Practice Class HTML outputs, audience boundaries, and links."""

from __future__ import annotations

import argparse
import html.parser
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from practice_contract import load_courseware, load_json, validate_content


STUDENT_HTML = (
    Path("student") / "student-task.html",
    Path("student") / "learning-center.html",
    Path("student") / "study-guide.html",
    Path("student") / "foundation-kit.html",
)
TEACHER_HTML = (Path("teacher") / "teacher-guide.html", Path("teacher") / "teacher-reference.html")
REQUIRED_TOP_LEVEL = ("student", "teacher", "practice-content.json", "qa-report.json")
EXTERNAL_PATTERN = re.compile(r"(?i)(?:https?:|//|data:|javascript:|file:)")
FORBIDDEN_LAYOUT = re.compile(r"(?i)border-left\s*:\s*4px\s+solid")
FORBIDDEN_STUDENT_TEXT = ("teacher-guide", "teacher-reference", "教师答案", "教师参考")


class _HTMLProbe(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.doctype = False
        self.meta_charset = False
        self.buttons = 0
        self.interactions = 0
        self.text_parts: list[str] = []

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype html"):
            self.doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")
        if tag == "button":
            self.buttons += 1
        if any(key in values for key in ("data-interaction", "data-stepper", "data-classify", "data-reorder", "data-simulator")):
            self.interactions += 1
        if tag == "meta" and values.get("charset"):
            self.meta_charset = values["charset"].lower() == "utf-8"

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)


def _probe(path: Path) -> _HTMLProbe:
    probe = _HTMLProbe()
    probe.feed(path.read_text(encoding="utf-8"))
    probe.close()
    return probe


def _anchor_ids(path: Path) -> set[str]:
    return _probe(path).ids


def _check_link(source: Path, href: str, output_dir: Path, errors: list[str]) -> None:
    if not href or href.startswith("#"):
        if href.startswith("#") and href[1:] and href[1:] not in _anchor_ids(source):
            errors.append(f"{source.name}: missing local anchor {href}")
        return
    if EXTERNAL_PATTERN.search(href):
        errors.append(f"{source.name}: external, executable, or file link is not allowed: {href}")
        return
    parsed = urlsplit(href)
    relative = unquote(parsed.path)
    target = source if not relative else (source.parent / relative).resolve()
    try:
        target.relative_to(output_dir.resolve())
    except ValueError:
        errors.append(f"{source.name}: link escapes output directory: {href}")
        return
    if not target.is_file():
        errors.append(f"{source.name}: link target does not exist: {href}")
        return
    if parsed.fragment and target.suffix.lower() in {".html", ".htm"} and parsed.fragment not in _anchor_ids(target):
        errors.append(f"{source.name}: target anchor does not exist: {href}")


def validate_html_file(path: Path, output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return {"status": "fail", "errors": [f"missing HTML output: {path}"], "warnings": [], "metrics": {}}
    raw = path.read_text(encoding="utf-8")
    probe = _probe(path)
    if not raw.lstrip().lower().startswith("<!doctype html>") or not probe.doctype:
        errors.append(f"{path.name}: HTML5 doctype is required")
    if not probe.meta_charset:
        errors.append(f"{path.name}: UTF-8 meta charset is required")
    if EXTERNAL_PATTERN.search(raw):
        errors.append(f"{path.name}: external/executable/file URL found in offline HTML")
    if FORBIDDEN_LAYOUT.search(raw):
        errors.append(f"{path.name}: thick left-border template styling is not allowed")
    for href in probe.links:
        _check_link(path, href, output_dir, errors)
    relative = path.resolve().relative_to(output_dir.resolve())
    if relative.parts and relative.parts[0] == "student":
        lowered = raw.casefold()
        for forbidden in FORBIDDEN_STUDENT_TEXT:
            if forbidden.casefold() in lowered:
                errors.append(f"{path.name}: student output contains teacher-only marker: {forbidden}")
        for href in probe.links:
            if href.startswith("#"):
                continue
            target = (path.parent / urlsplit(href).path).resolve()
            try:
                target.relative_to((output_dir / "student").resolve())
            except ValueError:
                errors.append(f"{path.name}: student link leaves student/ tree: {href}")
    if relative == Path("student") / "learning-center.html" and probe.interactions == 0:
        errors.append("student/learning-center.html: at least one content interaction is required")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "metrics": {"links": len(probe.links), "anchors": len(probe.ids), "buttons": probe.buttons, "interactions": probe.interactions, "characters": len(raw)},
    }


def _task_html(raw: str, task_id: str) -> str:
    marker = f'data-task-id="{task_id}"'
    start = raw.find(marker)
    if start < 0:
        return ""
    end = raw.find("</article>", start)
    return raw[start:end if end >= 0 else len(raw)]


def validate_output_files(content: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not output_dir.is_dir():
        return {"status": "fail", "errors": [f"missing output directory: {output_dir}"], "warnings": [], "files": []}
    names = {path.name for path in output_dir.iterdir()}
    for required in REQUIRED_TOP_LEVEL:
        if required not in names:
            errors.append(f"missing required output: {required}")
    for stale in ("student-task.html", "learning-center.html", "study-guide.html", "foundation-kit.html", "teacher-guide.html", "starter"):
        if (output_dir / stale).exists():
            errors.append(f"output must be physically split; stale root item exists: {stale}")
    html_paths = [output_dir / relative for relative in (*STUDENT_HTML, *TEACHER_HTML)]
    for page in html_paths:
        result = validate_html_file(page, output_dir)
        errors.extend(result["errors"])
        warnings.extend(result["warnings"])

    if content.get("starter_assets") and not (output_dir / "student" / "starter").is_dir():
        errors.append("starter_assets are declared but student/starter/ output is missing")
    for asset in content.get("starter_assets", []):
        if isinstance(asset, dict):
            target = output_dir / "student" / "starter" / str(asset.get("path", ""))
            if not target.is_file():
                errors.append(f"starter asset output is missing: {target.relative_to(output_dir)}")
            if str(asset.get("path", "")).lower().endswith(".drawio"):
                try:
                    ET.fromstring(target.read_text(encoding="utf-8"))
                except (OSError, ET.ParseError) as exc:
                    errors.append(f"draw.io starter is not parseable: {asset.get('path')}: {exc}")

    student_task_path = output_dir / "student" / "student-task.html"
    student_raw = student_task_path.read_text(encoding="utf-8") if student_task_path.is_file() else ""
    teacher_reference_path = output_dir / "teacher" / "teacher-reference.html"
    teacher_reference_raw = teacher_reference_path.read_text(encoding="utf-8") if teacher_reference_path.is_file() else ""
    for task in content.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id"))
        if task.get("level") == "core":
            task_html = _task_html(student_raw, task_id)
            if not task_html:
                errors.append(f"student/student-task.html is missing core task: {task_id}")
            source_refs = set(task.get("source_slide_ids", []))
            if source_refs and not all(ref in task_html for ref in source_refs):
                errors.append(f"student/student-task.html core task lacks source slide references: {task_id}")
        if f'id="reference-{task_id}"' not in teacher_reference_raw:
            errors.append(f"teacher/teacher-reference.html is missing task reference: {task_id}")
    if content.get("source_courseware", {}).get("mode") == "courseware":
        for ref in {ref for item in content.get("knowledge_links", []) for ref in item.get("source_slide_ids", [])}:
            if ref not in student_raw:
                errors.append(f"student/student-task.html is missing source slide reference: {ref}")

    files = sorted(str(path.relative_to(output_dir)).replace("\\", "/") for path in output_dir.rglob("*") if path.is_file())
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "files": files}


def validate(practice_path: Path, output_dir: Path, courseware_path: Path | None = None) -> dict[str, Any]:
    content = load_json(practice_path)
    courseware = load_courseware(courseware_path) if courseware_path else None
    contract = validate_content(content, courseware)
    output = validate_output_files(content, output_dir)
    errors = [*contract["errors"], *output["errors"]]
    warnings = [*contract["warnings"], *output["warnings"]]
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "contract": contract, "outputs": output}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-json", required=True, type=Path)
    parser.add_argument("--courseware-json", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = validate(args.practice_json, args.output_dir, args.courseware_json)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else f"status={report['status']} errors={len(report['errors'])} warnings={len(report['warnings'])}")
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
