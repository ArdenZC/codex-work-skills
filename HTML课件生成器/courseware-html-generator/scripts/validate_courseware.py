"""Deterministic content and generated HTML QA for courseware outputs."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from content_contract import (
    STUDENT_FORBIDDEN,
    STUDENT_FORBIDDEN_PATTERNS,
    load_content,
    validate_content,
)


def _resource_errors(document: str) -> list[str]:
    errors: list[str] = []
    if re.search(r"(?is)<link\b|<iframe\b|<object\b|<embed\b", document):
        errors.append("generated document contains an external-capable HTML resource element")
    if re.search(r"(?is)<script\b[^>]*\bsrc\s*=", document):
        errors.append("generated document contains an external script source")
    for raw_img in re.findall(r"(?is)<img\b[^>]*>", document):
        src = re.search(r'''(?i)\bsrc\s*=\s*["']([^"']+)["']''', raw_img)
        if not src or not re.match(r"(?i)^data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$", src.group(1)):
            errors.append("generated document contains an image without a safe local data URI")
    if re.search(r"(?i)@import|url\(\s*['\"]?https?://|(?:src|href)\s*=\s*['\"]https?://", document):
        errors.append("generated document contains an external URL or stylesheet reference")
    if re.search(r"(?i)fonts\.googleapis|fonts\.gstatic|@font-face", document):
        errors.append("generated document contains an external font reference")
    return errors


def _page_attrs(document: str, marker: str) -> list[tuple[str, int]]:
    pages: list[tuple[str, int]] = []
    for tag in re.findall(r"(?is)<[^>]+>", document):
        classes = re.search(r'class="([^"]+)"', tag, re.IGNORECASE)
        if not classes or marker not in classes.group(1).split():
            continue
        page_id = re.search(r'data-page-id="([^"]+)"', tag, re.IGNORECASE)
        page_index = re.search(r'data-page-index="(\d+)"', tag, re.IGNORECASE)
        if page_id and page_index:
            pages.append((page_id.group(1), int(page_index.group(1))))
    return pages


def _teacher_page_attrs(document: str) -> list[tuple[str, int]]:
    return _page_attrs(document, "teacher-page")


def _svg_qa(document: str) -> list[str]:
    errors: list[str] = []
    opening = len(re.findall(r"(?i)<svg\b", document))
    closing = len(re.findall(r"(?i)</svg\s*>", document))
    if opening != closing:
        errors.append(f"SVG tag count mismatch: opening={opening}, closing={closing}")
    ids: list[str] = []
    for index, raw_svg in enumerate(re.findall(r"(?is)<svg\b.*?</svg\s*>", document), start=1):
        try:
            ET.fromstring(raw_svg)
        except ET.ParseError as exc:
            errors.append(f"output SVG {index} is not well-formed: {exc}")
        ids.extend(re.findall(r"\bid\s*=\s*['\"]([^'\"]+)['\"]", raw_svg))
        without_svg_namespace = re.sub(r'xmlns\s*=\s*["\']https?://www\.w3\.org/2000/svg["\']', "", raw_svg, flags=re.IGNORECASE)
        if re.search(r'''(?is)<\s*script\b|\bon[a-z]+\s*=|data:|(?:href|src)\s*=\s*["'](?!\#)''', without_svg_namespace):
            errors.append(f"output SVG {index} contains unsafe markup or a resource")
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        errors.append("SVG ids are not globally namespaced: " + ", ".join(duplicates[:8]))
    return errors


def _student_text_errors(document: str) -> list[str]:
    errors: list[str] = []
    for phrase in STUDENT_FORBIDDEN:
        if phrase in document:
            errors.append(f"student.html contains forbidden phrase: {phrase}")
    for pattern in STUDENT_FORBIDDEN_PATTERNS:
        match = pattern.search(document)
        if match:
            errors.append(f"student.html contains forbidden timing/source pattern: {match.group(0)}")
    for internal_field in ("content_reserve_minutes", "suggested_minutes", "speaker_script", "demo_hint", "classroom_followup", "pacing_note"):
        if internal_field in document:
            errors.append(f"student.html leaks internal field name: {internal_field}")
    return errors


def validate_html_outputs(content: dict[str, Any], student_html: str, teacher_html: str) -> dict[str, Any]:
    """Validate the two generated documents and their one-to-one page mapping."""

    errors: list[str] = []
    warnings: list[str] = []
    content_report = validate_content(content)
    if content_report["status"] != "pass":
        errors.extend("content: " + item for item in content_report["errors"])
    if not re.search(r"(?is)<!doctype html>", student_html) or not re.search(r"(?is)<!doctype html>", teacher_html):
        errors.append("both outputs must be complete HTML documents")
    for label, document in (("student.html", student_html), ("teacher.html", teacher_html)):
        errors.extend(f"{label}: {item}" for item in _resource_errors(document))
        if document.count('<meta charset="utf-8">') != 1:
            errors.append(f"{label}: exactly one UTF-8 meta charset is required")
        if 'data-courseware-runtime="1"' not in document:
            errors.append(f"{label}: deterministic runtime marker is missing")
        if "courseware:pagechange" not in document:
            errors.append(f"{label}: page-change runtime hook is missing")
        if "border-left" in document.lower():
            errors.append(f"{label}: border-left emphasis styling is forbidden")
    errors.extend(_student_text_errors(student_html))
    errors.extend(_svg_qa(student_html))
    errors.extend(f"teacher.html: {item}" for item in _svg_qa(teacher_html))

    expected = [(str(slide["id"]), index) for index, slide in enumerate(content["slides"])]
    student_pages = _page_attrs(student_html, "slide-page")
    teacher_pages = _teacher_page_attrs(teacher_html)
    if student_pages != expected:
        errors.append(f"student page mapping mismatch: expected {expected}, got {student_pages}")
    if teacher_pages != expected:
        errors.append(f"teacher page mapping mismatch: expected {expected}, got {teacher_pages}")
    if student_pages != teacher_pages:
        errors.append("student and teacher page IDs/indexes are not one-to-one")
    teacher_scripts = len(re.findall(r'class="speaker-script"', teacher_html))
    if teacher_scripts != len(expected):
        errors.append(f"teacher.html has {teacher_scripts} speaker-script regions for {len(expected)} pages")
    teacher_headers = len(re.findall(r"建议\s+\d+\s*分钟", teacher_html))
    if teacher_headers != len(expected):
        errors.append(f"teacher.html has {teacher_headers} page timing headers for {len(expected)} pages")
    if len(re.findall(r'class="quiz-block"', student_html)) == 0:
        warnings.append("fixture contains no quiz block; a production chapter may still choose not to use one")
    if len(re.findall(r'class="stepper-block"', student_html)) == 0:
        warnings.append("fixture contains no stepper block; a production chapter may still choose not to use one")
    metrics = {
        "student_bytes": len(student_html.encode("utf-8")),
        "teacher_bytes": len(teacher_html.encode("utf-8")),
        "student_pages": len(student_pages),
        "teacher_pages": len(teacher_pages),
        "student_svgs": len(re.findall(r"(?i)<svg\b", student_html)),
        "teacher_svgs": len(re.findall(r"(?i)<svg\b", teacher_html)),
    }
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "metrics": metrics}


def validate_files(content_path: Path, student_path: Path, teacher_path: Path) -> dict[str, Any]:
    try:
        content = load_content(content_path)
        student = student_path.read_text(encoding="utf-8")
        teacher = teacher_path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - CLI boundary needs a JSON report
        return {"status": "fail", "errors": [str(exc)], "warnings": [], "metrics": {}}
    return validate_html_outputs(content, student, teacher)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-json", required=True, type=Path)
    parser.add_argument("--student-html", required=True, type=Path)
    parser.add_argument("--teacher-html", required=True, type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a compact status line")
    args = parser.parse_args(argv)
    report = validate_files(args.content_json, args.student_html, args.teacher_html)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"courseware QA: {report['status']}")
        for error in report["errors"]:
            print(f"ERROR: {error}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
