"""Validate Practice Class HTML outputs and their internal links."""

from __future__ import annotations

import argparse
import html.parser
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from practice_contract import load_courseware, load_json, validate_content


REQUIRED_HTML = (
    "student-task.html",
    "learning-center.html",
    "study-guide.html",
    "foundation-kit.html",
    "teacher-guide.html",
)
REQUIRED_FILES = (*REQUIRED_HTML, "practice-content.json", "qa-report.json")
EXTERNAL_PATTERN = re.compile(r"(?i)(?:https?:|//|data:|javascript:)")
FORBIDDEN_LAYOUT = re.compile(r"(?i)border-left\s*:\s*4px\s+solid")


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
        if "data-interaction" in values or "data-stepper" in values:
            self.interactions += 1
        if tag == "meta" and values.get("charset"):
            self.meta_charset = values["charset"].lower() == "utf-8"

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)


def _anchor_ids(path: Path) -> set[str]:
    probe = _HTMLProbe()
    probe.feed(path.read_text(encoding="utf-8"))
    return probe.ids


def _check_link(source: Path, href: str, output_dir: Path, errors: list[str]) -> None:
    if not href or href.startswith("#"):
        if href.startswith("#") and href[1:] and href[1:] not in _anchor_ids(source):
            errors.append(f"{source.name}: missing local anchor {href}")
        return
    if EXTERNAL_PATTERN.search(href):
        errors.append(f"{source.name}: external or executable link is not allowed: {href}")
        return
    parsed = urlsplit(href)
    relative = unquote(parsed.path)
    if not relative:
        target = source
    else:
        target = (source.parent / relative).resolve()
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
        return {"status": "fail", "errors": [f"missing HTML output: {path.name}"], "warnings": [], "metrics": {}}
    raw = path.read_text(encoding="utf-8")
    probe = _HTMLProbe()
    try:
        probe.feed(raw)
        probe.close()
    except Exception as exc:  # pragma: no cover - parser implementation detail
        errors.append(f"{path.name}: HTML parse failed: {exc}")
    if not raw.lstrip().lower().startswith("<!doctype html>") or not probe.doctype:
        errors.append(f"{path.name}: HTML5 doctype is required")
    if not probe.meta_charset:
        errors.append(f"{path.name}: UTF-8 meta charset is required")
    if EXTERNAL_PATTERN.search(raw):
        errors.append(f"{path.name}: external/executable URL found in offline HTML")
    if FORBIDDEN_LAYOUT.search(raw):
        errors.append(f"{path.name}: thick left-border template styling is not allowed")
    for href in probe.links:
        _check_link(path, href, output_dir, errors)
    if path.name == "learning-center.html" and probe.interactions == 0:
        errors.append("learning-center.html: at least one content interaction is required")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "metrics": {"links": len(probe.links), "anchors": len(probe.ids), "buttons": probe.buttons, "interactions": probe.interactions, "characters": len(raw)},
    }


def validate_output_files(content: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    files = {path.name for path in output_dir.iterdir()} if output_dir.is_dir() else set()
    for required in REQUIRED_FILES:
        if required not in files:
            errors.append(f"missing required output: {required}")
    if output_dir.is_dir():
        for name in REQUIRED_HTML:
            page = validate_html_file(output_dir / name, output_dir)
            errors.extend(page["errors"])
            warnings.extend(page["warnings"])
    if content.get("starter_assets") and not (output_dir / "starter").is_dir():
        errors.append("starter_assets are declared but starter/ output is missing")
    student_raw = (output_dir / "student-task.html").read_text(encoding="utf-8") if (output_dir / "student-task.html").is_file() else ""
    for task in content.get("tasks", []):
        if task.get("level") == "core":
            marker = f'data-task-id="{task.get("id")}"'
            if marker not in student_raw:
                errors.append(f"student-task.html is missing core task: {task.get('id')}")
            else:
                start = student_raw.find(marker)
                end = student_raw.find("</article>", start)
                task_html = student_raw[start:end if end >= 0 else len(student_raw)]
                source_refs = {
                    source_ref
                    for knowledge in content.get("knowledge_links", [])
                    if knowledge.get("id") in task.get("knowledge_link_ids", [])
                    for source_ref in knowledge.get("source_slide_ids", [])
                }
                if source_refs and not any(ref in task_html for ref in source_refs):
                    errors.append(f"student-task.html core task lacks its source slide reference: {task.get('id')}")
    if content.get("source_courseware", {}).get("mode") == "courseware":
        for ref in {ref for item in content.get("knowledge_links", []) for ref in item.get("source_slide_ids", [])}:
            if ref not in student_raw:
                errors.append(f"student-task.html is missing source slide reference: {ref}")
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "files": sorted(files)}


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
