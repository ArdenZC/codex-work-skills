"""Validation helpers for Courseware Content Contract 1.0."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "1.0"
SUPPORTED_LAYOUTS = {"hero", "split", "grid", "focus", "comparison", "timeline", "default"}
SUPPORTED_BLOCKS = {
    "paragraph",
    "bullets",
    "cards",
    "table",
    "code",
    "formula",
    "svg",
    "quiz",
    "stepper",
    "comparison",
    "summary",
}
SLIDE_FIELDS = {
    "id",
    "title",
    "kicker",
    "layout",
    "blocks",
    "speaker_script",
    "suggested_minutes",
    "demo_hint",
    "classroom_followup",
    "pacing_note",
}
STUDENT_FORBIDDEN = (
    "120分钟",
    "备课版",
    "学生版",
    "教师版",
    "最大可用",
    "本页建议",
    "教师提示",
    "时间充裕时展开",
    "原PPT",
    "上传资料",
    "根据你提供的文件",
    "制作信息",
    "生成器",
)
STUDENT_FORBIDDEN_PATTERNS = (
    re.compile(r"第\s*\d+\s*次理论课"),
    re.compile(r"\d+\s*分钟"),
    re.compile(r"(?:建议|最大可用|课堂用时)\s*\d+"),
)
SVG_EXTERNAL_PATTERN = re.compile(
    r'''(?ix)(?:data:|(?:href|xlink:href|src)\s*=\s*["'](?!\#)|url\(\s*["']?(?!\#))'''
)
SVG_EVENT_PATTERN = re.compile(r"(?i)\bon[a-z]+\s*=")
ID_PATTERN = re.compile(r"\bid\s*=\s*(['\"])([^'\"]+)\1")


class CoursewareContractError(ValueError):
    """Raised when a courseware content contract cannot be used safely."""


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _meaningful_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return ""
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _validate_svg(svg: Any, location: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(svg, str) or not svg.strip():
        errors.append(f"{location}.svg must be a non-empty string")
        return {"ids": [], "elements": 0}
    raw = svg.strip()
    if not re.match(r"(?is)^\s*<svg\b", raw) or not re.search(r"</svg>\s*$", raw):
        errors.append(f"{location}.svg must have a closed <svg> root")
    if re.search(r"(?is)<\s*(?:script|foreignObject|iframe)\b", raw):
        errors.append(f"{location}.svg contains a forbidden executable/foreign element")
    if SVG_EVENT_PATTERN.search(raw):
        errors.append(f"{location}.svg contains an event attribute")
    if SVG_EXTERNAL_PATTERN.search(raw):
        errors.append(f"{location}.svg contains an external or non-fragment resource")
    ids = [match.group(2) for match in ID_PATTERN.finditer(raw)]
    if len(ids) != len(set(ids)):
        errors.append(f"{location}.svg contains duplicate ids")
    try:
        root = ET.fromstring(raw)
        local_name = root.tag.rsplit("}", 1)[-1]
        if local_name != "svg":
            errors.append(f"{location}.svg root is not svg")
        elements = sum(1 for _ in root.iter())
    except ET.ParseError as exc:
        errors.append(f"{location}.svg is not well-formed XML: {exc}")
        elements = 0
    return {"ids": ids, "elements": elements}


def _validate_string_list(value: Any, location: str, errors: list[str]) -> None:
    _add(errors, isinstance(value, list) and bool(value), f"{location} must be a non-empty list")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _add(errors, _non_empty(item), f"{location}[{index}] must be a non-empty string")


def _validate_text_or_list(value: Any, location: str, errors: list[str]) -> None:
    if isinstance(value, list):
        _validate_string_list(value, location, errors)
    else:
        _add(errors, _non_empty(value), f"{location} must be a non-empty string or string list")


def _validate_block(block: Any, location: str, errors: list[str], metrics: dict[str, int]) -> None:
    if not isinstance(block, dict):
        errors.append(f"{location} must be an object")
        return
    block_type = block.get("type")
    if block_type not in SUPPORTED_BLOCKS:
        errors.append(f"{location}.type must be one of {sorted(SUPPORTED_BLOCKS)}")
        return
    metrics["blocks"] += 1
    if block_type == "paragraph":
        _add(errors, _non_empty(block.get("text")), f"{location}.text must be a non-empty string")
    elif block_type in {"bullets", "summary"}:
        _validate_string_list(block.get("items"), f"{location}.items", errors)
    elif block_type == "cards":
        items = block.get("items")
        _add(errors, isinstance(items, list) and bool(items), f"{location}.items must be a non-empty list")
        if isinstance(items, list):
            for index, item in enumerate(items):
                item_location = f"{location}.items[{index}]"
                _add(errors, isinstance(item, dict), f"{item_location} must be an object")
                if isinstance(item, dict):
                    _add(errors, _non_empty(item.get("title")), f"{item_location}.title is required")
                    _add(errors, _non_empty(item.get("text")), f"{item_location}.text is required")
    elif block_type == "table":
        headers = block.get("headers")
        rows = block.get("rows")
        _validate_string_list(headers, f"{location}.headers", errors)
        _add(errors, isinstance(rows, list) and bool(rows), f"{location}.rows must be a non-empty list")
        if isinstance(headers, list) and isinstance(rows, list):
            for row_index, row in enumerate(rows):
                _add(
                    errors,
                    isinstance(row, list) and len(row) == len(headers),
                    f"{location}.rows[{row_index}] must have {len(headers)} cells",
                )
                if isinstance(row, list):
                    for cell_index, cell in enumerate(row):
                        _add(errors, _text(cell) != "", f"{location}.rows[{row_index}][{cell_index}] is empty")
    elif block_type == "code":
        _add(errors, _non_empty(block.get("language")), f"{location}.language is required")
        _add(errors, isinstance(block.get("code"), str), f"{location}.code must be a string")
    elif block_type == "formula":
        _add(errors, _non_empty(block.get("formula")), f"{location}.formula is required")
        if "explanation" in block:
            _add(errors, isinstance(block.get("explanation"), str), f"{location}.explanation must be a string")
    elif block_type == "svg":
        result = _validate_svg(block.get("svg"), location, errors)
        metrics["svg_count"] += 1
        metrics["svg_elements"] += result["elements"]
    elif block_type == "quiz":
        _add(errors, _non_empty(block.get("question")), f"{location}.question is required")
        options = block.get("options")
        _validate_string_list(options, f"{location}.options", errors)
        answer = block.get("answer_index")
        _add(errors, isinstance(answer, int) and not isinstance(answer, bool), f"{location}.answer_index must be an integer")
        if isinstance(answer, int) and isinstance(options, list):
            _add(errors, 0 <= answer < len(options), f"{location}.answer_index is out of range")
        if "explanation" in block:
            _add(errors, _non_empty(block.get("explanation")), f"{location}.explanation is required when present")
    elif block_type == "stepper":
        steps = block.get("steps")
        _add(errors, isinstance(steps, list) and len(steps) >= 2, f"{location}.steps must contain at least two steps")
        if isinstance(steps, list):
            for index, step in enumerate(steps):
                step_location = f"{location}.steps[{index}]"
                _add(errors, isinstance(step, dict), f"{step_location} must be an object")
                if isinstance(step, dict):
                    _add(errors, _non_empty(step.get("title")), f"{step_location}.title is required")
                    _add(errors, _non_empty(step.get("text")), f"{step_location}.text is required")
        metrics["stepper_count"] += 1
    elif block_type == "comparison":
        for field in ("left_title", "right_title"):
            _add(errors, _non_empty(block.get(field)), f"{location}.{field} is required")
        for field in ("left", "right"):
            _validate_text_or_list(block.get(field), f"{location}.{field}", errors)


def _block_visible_text(block: dict[str, Any]) -> list[str]:
    block_type = block.get("type")
    values: list[str] = []
    if block_type == "paragraph":
        values.append(_text(block.get("text")))
    elif block_type in {"bullets", "summary"}:
        values.extend(_text(item) for item in block.get("items", []))
    elif block_type == "cards":
        for item in block.get("items", []):
            if isinstance(item, dict):
                values.extend((_text(item.get("title")), _text(item.get("text"))))
    elif block_type == "table":
        values.extend(_text(item) for item in block.get("headers", []))
        for row in block.get("rows", []):
            if isinstance(row, list):
                values.extend(_text(item) for item in row)
    elif block_type == "code":
        values.extend((_text(block.get("language")), _text(block.get("caption")), _text(block.get("code"))))
    elif block_type == "formula":
        values.extend((_text(block.get("formula")), _text(block.get("explanation"))))
    elif block_type == "svg":
        values.append(_text(block.get("caption")))
    elif block_type == "quiz":
        values.extend((_text(block.get("question")), *(_text(item) for item in block.get("options", []))))
    elif block_type == "stepper":
        for item in block.get("steps", []):
            if isinstance(item, dict):
                values.extend((_text(item.get("title")), _text(item.get("text"))))
    elif block_type == "comparison":
        values.append(_text(block.get("left_title")))
        left = block.get("left")
        values.extend(_text(item) for item in left) if isinstance(left, list) else values.append(_text(left))
        values.append(_text(block.get("right_title")))
        right = block.get("right")
        values.extend(_text(item) for item in right) if isinstance(right, list) else values.append(_text(right))
    return [value for value in values if value]


def student_visible_text(content: dict[str, Any]) -> str:
    """Return the text that the renderer is allowed to place in student.html."""

    values = [_text(content.get("course_title")), _text(content.get("chapter_title"))]
    for slide in content.get("slides", []):
        values.extend((_text(slide.get("title")), _text(slide.get("kicker"))))
        for block in slide.get("blocks", []):
            if isinstance(block, dict):
                values.extend(_block_visible_text(block))
    return "\n".join(value for value in values if value)


def validate_content(content: Any) -> dict[str, Any]:
    """Validate content without requiring jsonschema."""

    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, int] = {
        "slides": 0,
        "blocks": 0,
        "svg_count": 0,
        "svg_elements": 0,
        "stepper_count": 0,
    }
    if not isinstance(content, dict):
        return {"status": "fail", "errors": ["content root must be an object"], "warnings": [], "metrics": metrics}
    allowed_root = {"contract_version", "course_title", "chapter_title", "audience", "content_reserve_minutes", "theme", "slides"}
    extra = sorted(set(content) - allowed_root)
    errors.extend(f"content has unsupported field: {field}" for field in extra)
    _add(errors, content.get("contract_version") == CONTRACT_VERSION, f"contract_version must be {CONTRACT_VERSION}")
    for field in ("course_title", "chapter_title", "audience"):
        _add(errors, _non_empty(content.get(field)), f"{field} must be a non-empty string")
    reserve = content.get("content_reserve_minutes")
    _add(errors, isinstance(reserve, int) and not isinstance(reserve, bool) and reserve > 0, "content_reserve_minutes must be a positive integer")
    if "theme" in content:
        _add(errors, _non_empty(content.get("theme")), "theme must be a non-empty string when present")
    slides = content.get("slides")
    _add(errors, isinstance(slides, list) and len(slides) >= 2, "slides must contain at least two pages")
    if not isinstance(slides, list):
        return {"status": "fail", "errors": errors, "warnings": warnings, "metrics": metrics}
    metrics["slides"] = len(slides)
    ids: set[str] = set()
    for slide_index, slide in enumerate(slides, start=1):
        location = f"slides[{slide_index - 1}]"
        if not isinstance(slide, dict):
            errors.append(f"{location} must be an object")
            continue
        extra_slide = sorted(set(slide) - SLIDE_FIELDS)
        errors.extend(f"{location} has unsupported field: {field}" for field in extra_slide)
        slide_id = slide.get("id")
        _add(errors, _non_empty(slide_id), f"{location}.id must be a non-empty string")
        if _non_empty(slide_id):
            if slide_id in ids:
                errors.append(f"duplicate slide id: {slide_id}")
            ids.add(slide_id)
        _add(errors, _non_empty(slide.get("title")), f"{location}.title must be a non-empty string")
        layout = slide.get("layout")
        _add(errors, layout in SUPPORTED_LAYOUTS, f"{location}.layout must be one of {sorted(SUPPORTED_LAYOUTS)}")
        blocks = slide.get("blocks")
        _add(errors, isinstance(blocks, list) and bool(blocks), f"{location}.blocks must be a non-empty list")
        if isinstance(blocks, list):
            for block_index, block in enumerate(blocks):
                _validate_block(block, f"{location}.blocks[{block_index}]", errors, metrics)
        script = slide.get("speaker_script")
        _add(errors, _non_empty(script), f"{location}.speaker_script must be a non-empty string")
        minutes = slide.get("suggested_minutes")
        _add(errors, isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0, f"{location}.suggested_minutes must be a positive integer")
        if _non_empty(script) and isinstance(minutes, int) and minutes > 0:
            minimum = max(120, minutes * 45)
            actual = _meaningful_length(script)
            if actual < minimum:
                errors.append(f"{location}.speaker_script has {actual} meaningful chars; minimum for {minutes} minutes is {minimum}")
        for field in ("kicker", "demo_hint", "classroom_followup", "pacing_note"):
            if field in slide:
                _add(errors, isinstance(slide.get(field), str), f"{location}.{field} must be a string when present")

    visible = student_visible_text(content)
    for forbidden in STUDENT_FORBIDDEN:
        if forbidden in visible:
            errors.append(f"student-visible content contains forbidden phrase: {forbidden}")
    for pattern in STUDENT_FORBIDDEN_PATTERNS:
        match = pattern.search(visible)
        if match:
            errors.append(f"student-visible content contains forbidden timing/source pattern: {match.group(0)}")
    if isinstance(reserve, int) and reserve < sum(slide.get("suggested_minutes", 0) for slide in slides if isinstance(slide, dict)):
        warnings.append("content_reserve_minutes is lower than the sum of suggested_minutes")
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "metrics": metrics}


def load_content(path: Path) -> dict[str, Any]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoursewareContractError(f"cannot read content JSON {path}: {exc}") from exc
    report = validate_content(content)
    if report["status"] != "pass":
        raise CoursewareContractError("invalid courseware content: " + "; ".join(report["errors"]))
    return content


def block_visible_text(block: dict[str, Any]) -> list[str]:
    """Public wrapper used by output QA and the renderer."""

    return _block_visible_text(block)


if __name__ == "__main__":  # pragma: no cover - convenience diagnostic
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content_json", type=Path)
    args = parser.parse_args()
    result = validate_content(json.loads(args.content_json.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 1)
