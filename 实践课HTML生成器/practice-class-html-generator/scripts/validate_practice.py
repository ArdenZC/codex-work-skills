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

from practice_contract import RENDERER_FAMILIES, load_courseware, load_json, validate_content


STUDENT_INDEXES = (
    Path("student") / "student-task.html",
    Path("student") / "learning-center.html",
    Path("student") / "study-guide.html",
    Path("student") / "foundation-kit.html",
)
TEACHER_INDEXES = (Path("teacher") / "teacher-guide.html", Path("teacher") / "teacher-reference.html")
REQUIRED_TOP_LEVEL = ("student", "teacher", "practice-content.json", "qa-report.json")
EXTERNAL_PATTERN = re.compile(r"(?i)(?:https?:|//|data:|javascript:|file:)")
FORBIDDEN_LAYOUT = re.compile(r"(?i)border-left\s*:\s*4px\s+solid")
FORBIDDEN_STUDENT_TEXT = ("teacher-guide", "teacher-reference", "教师答案", "教师参考", "Contract 1.0", "Practice Class")
INTERACTION_TEXT = set(RENDERER_FAMILIES) | set(RENDERER_FAMILIES.values())


class _HTMLProbe(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.doctype = False
        self.meta_charset = False
        self.buttons = 0
        self.interactions = 0
        self.renderer_families: set[str] = set()
        self.text_parts: list[str] = []
        self._ignored_depth = 0

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
        if "data-interaction-root" in values:
            self.interactions += 1
            family = values.get("data-renderer-family")
            if family:
                self.renderer_families.add(family)
        if tag == "meta" and values.get("charset"):
            self.meta_charset = values["charset"].lower() == "utf-8"
        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.text_parts.append(data)

    @property
    def visible_text(self) -> str:
        return " ".join(" ".join(self.text_parts).split())


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


def validate_html_file(path: Path, output_dir: Path, *, content: dict[str, Any] | None = None) -> dict[str, Any]:
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
        visible = probe.visible_text.casefold()
        for forbidden in FORBIDDEN_STUDENT_TEXT:
            if forbidden.casefold() in visible:
                errors.append(f"{path.name}: student output contains teacher-only or machine marker: {forbidden}")
        if content:
            machine_values = {
                str(content.get("contract_version", "")),
                *[str(task.get("id")) for task in content.get("tasks", []) if isinstance(task, dict)],
                *[str(center.get("id")) for center in content.get("learning_center", []) if isinstance(center, dict)],
                *[str(guide.get("id")) for guide in content.get("study_guide", []) if isinstance(guide, dict)],
                *[str(kit.get("id")) for kit in content.get("foundation_kit", []) if isinstance(kit, dict)],
                *[str(ref) for item in content.get("knowledge_links", []) if isinstance(item, dict) for ref in item.get("source_slide_ids", [])],
            }
            machine_values.update(str(ref) for ref in content.get("source_courseware", {}).get("taught_slide_ids", []))
            machine_values.update(INTERACTION_TEXT)
            for value in sorted(item for item in machine_values if item):
                if value.casefold() in visible:
                    errors.append(f"{path.name}: student visible text contains machine value: {value}")
        for href in probe.links:
            if href.startswith("#"):
                continue
            target = (path.parent / urlsplit(href).path).resolve()
            try:
                target.relative_to((output_dir / "student").resolve())
            except ValueError:
                errors.append(f"{path.name}: student link leaves student/ tree: {href}")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "metrics": {"links": len(probe.links), "anchors": len(probe.ids), "buttons": probe.buttons, "interactions": probe.interactions, "renderer_families": sorted(probe.renderer_families), "characters": len(raw), "visible_characters": len(probe.visible_text)},
    }


def _expected_html_paths(content: dict[str, Any]) -> list[Path]:
    paths = [*STUDENT_INDEXES, *TEACHER_INDEXES]
    paths.extend(Path("student") / "tasks" / f"{_slug(task.get('id'))}.html" for task in content.get("tasks", []) if isinstance(task, dict))
    paths.extend(Path("student") / "learning" / f"{_slug(center.get('id'))}.html" for center in content.get("learning_center", []) if isinstance(center, dict))
    paths.extend(Path("student") / "guides" / f"{_slug(guide.get('id'))}.html" for guide in content.get("study_guide", []) if isinstance(guide, dict))
    paths.extend(Path("student") / "kit" / f"{_slug(kit.get('id'))}.html" for kit in content.get("foundation_kit", []) if isinstance(kit, dict))
    paths.extend(Path("teacher") / "references" / f"{_slug(ref.get('task_id'))}.html" for ref in content.get("teacher_reference", {}).get("task_references", []) if isinstance(ref, dict))
    return paths


def _slug(value: Any) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", str(value or "")).strip("-")
    return cleaned or "item"


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

    expected = _expected_html_paths(content)
    for relative in expected:
        result = validate_html_file(output_dir / relative, output_dir, content=content)
        errors.extend(result["errors"])
        warnings.extend(result["warnings"])
    actual_html = {path.relative_to(output_dir) for path in output_dir.rglob("*.html")}
    expected_html = set(expected)
    unexpected = sorted(actual_html - expected_html)
    if unexpected:
        errors.extend(f"unexpected HTML output: {path.as_posix()}" for path in unexpected)

    student_root = output_dir / "student"
    teacher_root = output_dir / "teacher"
    for center in content.get("learning_center", []):
        if isinstance(center, dict):
            detail = student_root / "learning" / f"{_slug(center.get('id'))}.html"
            probe = _probe(detail) if detail.is_file() else None
            if not probe or probe.interactions != 1:
                errors.append(f"learning detail must contain exactly one interaction: {detail.relative_to(output_dir)}")
    if student_root.is_dir() and teacher_root.is_dir():
        student_html = list(student_root.rglob("*.html"))
        for page in student_html:
            probe = _probe(page)
            if not probe.renderer_families and "learning" in page.parts:
                errors.append(f"learning detail has no renderer family: {page.relative_to(output_dir)}")

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

    student_index = output_dir / "student" / "student-task.html"
    student_raw = student_index.read_text(encoding="utf-8") if student_index.is_file() else ""
    for task in content.get("tasks", []):
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("id"))
        task_path = output_dir / "student" / "tasks" / f"{_slug(task_id)}.html"
        task_raw = task_path.read_text(encoding="utf-8") if task_path.is_file() else ""
        if task.get("level") == "core":
            if not task_raw:
                errors.append(f"student/tasks/{_slug(task_id)}.html is missing core task")
            source_refs = set(task.get("source_slide_ids", []))
            marker = re.search(r'data-source-slide-ids="([^"]*)"', task_raw)
            declared = set((marker.group(1).split() if marker else []))
            if source_refs and not source_refs <= declared:
                errors.append(f"student task detail lacks source slide references: {task_id}")
        reference_path = teacher_root / "references" / f"{_slug(task_id)}.html"
        if not reference_path.is_file():
            errors.append(f"teacher/references/{_slug(task_id)}.html is missing task reference")
    if content.get("source_courseware", {}).get("mode") == "courseware":
        for ref in {ref for item in content.get("knowledge_links", []) for ref in item.get("source_slide_ids", [])}:
            if ref not in student_raw:
                errors.append(f"student/student-task.html is missing source slide association: {ref}")

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
