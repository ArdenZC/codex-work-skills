"""Validation and migration helpers for Courseware Content Contract 1.1.

The public 1.1 contract makes teaching time, semantic learning units and
cross-page canonical facts explicit. Legacy 1.0 JSON is accepted only through
the deterministic migration below; renderers and validators operate on the
normalized 1.1 shape.
"""

from __future__ import annotations

import copy
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "1.1"
LEGACY_CONTRACT_VERSION = "1.0"
SESSION_DELIVERY_MODES = {"theory-led", "mixed", "practice-led"}
SUPPORTED_LAYOUTS = {"hero", "split", "grid", "focus", "comparison", "timeline", "default"}
SUPPORTED_BLOCKS = {
    "paragraph",
    "bullets",
    "cards",
    "table",
    "code",
    "formula",
    "svg",
    "image",
    "quiz",
    "stepper",
    "comparison",
    "summary",
}
DELIVERY_TRACKS = {"core", "extension"}
TEACHING_INTENT_FIELDS = (
    "opening",
    "core_explanation",
    "example",
    "misconception",
    "question",
    "transition",
)
SLIDE_FIELDS = {
    "id",
    "title",
    "kicker",
    "layout",
    "blocks",
    "speaker_script",
    "lecture_minutes",
    "activity_minutes",
    "suggested_minutes",
    "teaching_intent",
    "learning_unit_ids",
    "canonical_fact_ids",
    "activity_plan",
    "demo_hint",
    "classroom_followup",
    "pacing_note",
    "delivery_track",
    "script_coverage",
    "planning_rationale",
}
COURSE_CONTEXT_STRING_FIELDS = {
    "course_name",
    "audience",
    "language",
    "platform",
    "software",
    "database_dialect",
    "framework",
    "delivery_environment",
}
COURSE_CONTEXT_LIST_FIELDS = {"tools", "other_constraints"}
COURSE_CONTEXT_FIELDS = COURSE_CONTEXT_STRING_FIELDS | COURSE_CONTEXT_LIST_FIELDS
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
ID_PATTERN = re.compile(r'''\bid\s*=\s*(['"])([^'"]+)\1''')
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096


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


def _slug(value: Any) -> str:
    value = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", str(value or "")).strip("-")
    return value or "unit"


def _sentences(value: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s*|\n+", value) if part.strip()]
    return parts or [value.strip()]


def _legacy_intent(slide: dict[str, Any]) -> dict[str, str]:
    script = _text(slide.get("speaker_script"))
    parts = _sentences(script)
    first = parts[0]
    last = parts[-1]
    middle = "".join(parts[: max(1, min(3, len(parts)))])
    title = _text(slide.get("title"))
    return {
        "opening": first,
        "core_explanation": middle,
        "example": last,
        "misconception": f"围绕“{title}”检查学生是否把相邻概念混用。",
        "question": f"请学生用自己的话解释“{title}”并指出一个判断依据。",
        "transition": f"下一页继续把“{title}”放进新的例子或操作步骤中。",
    }


def _legacy_learning_units(slides: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    for slide in slides:
        slide_id = _slug(slide.get("id"))
        unit_id = f"legacy-{slide_id}"
        fact_id = f"legacy-fact-{slide_id}"
        title = _text(slide.get("title")) or slide_id
        statement = _sentences(_text(slide.get("speaker_script")))[0] or title
        units.append(
            {
                "id": unit_id,
                "title": title,
                "students_should_know": [title],
                "students_should_be_able_to": [f"根据“{title}”完成一次课堂解释或检查。"],
                "prerequisites": [],
                "not_yet_taught": [],
                "canonical_fact_ids": [fact_id],
            }
        )
        facts.append(
            {
                "id": fact_id,
                "kind": "teaching-summary",
                "statement": statement,
                "source_slide_ids": [slide.get("id")],
                "learning_unit_ids": [unit_id],
            }
        )
        slide["learning_unit_ids"] = [unit_id]
        slide["teaching_intent"] = _legacy_intent(slide)
    return units, facts


def normalize_content(content: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a normalized 1.1 document and migration metadata."""

    if not isinstance(content, dict):
        return content, {"migrated": False, "from": None, "to": CONTRACT_VERSION}
    normalized = copy.deepcopy(content)
    version = normalized.get("contract_version")
    migration = {"migrated": False, "from": version, "to": CONTRACT_VERSION}
    if version == LEGACY_CONTRACT_VERSION:
        slides = [slide for slide in normalized.get("slides", []) if isinstance(slide, dict)]
        units, facts = _legacy_learning_units(slides)
        total = sum(int(slide.get("suggested_minutes", 0) or 0) for slide in slides)
        total = max(1, total)
        for slide in slides:
            suggested = int(slide.get("suggested_minutes", 1) or 1)
            slide["lecture_minutes"] = suggested
            slide["activity_minutes"] = 0
            slide["suggested_minutes"] = suggested
        normalized["slides"] = slides
        normalized["learning_units"] = units
        normalized["canonical_facts"] = facts
        normalized["assets"] = normalized.get("assets", []) or []
        normalized["session_minutes"] = total
        normalized["prepared_minutes"] = total
        normalized["core_minutes"] = total
        normalized["extension_minutes"] = 0
        normalized["contract_version"] = CONTRACT_VERSION
        normalized.pop("content_reserve_minutes", None)
        migration["migrated"] = True
    return normalized, migration


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


def _validate_string_list(value: Any, location: str, errors: list[str], *, allow_empty: bool = False) -> None:
    _add(errors, isinstance(value, list) and (allow_empty or bool(value)), f"{location} must be a {'possibly empty' if allow_empty else 'non-empty'} list")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _add(errors, _non_empty(item), f"{location}[{index}] must be a non-empty string")


def _validate_text_or_list(value: Any, location: str, errors: list[str]) -> None:
    if isinstance(value, list):
        _validate_string_list(value, location, errors)
    else:
        _add(errors, _non_empty(value), f"{location} must be a non-empty string or string list")


def _image_dimensions(raw: bytes) -> tuple[int, int] | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if raw[:3] == b"GIF" and len(raw) >= 10:
        return int.from_bytes(raw[6:8], "little"), int.from_bytes(raw[8:10], "little")
    if raw[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(raw):
            if raw[index] != 0xFF:
                index += 1
                continue
            marker = raw[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(raw):
                break
            length = int.from_bytes(raw[index:index + 2], "big")
            if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
                if index + 7 <= len(raw):
                    return int.from_bytes(raw[index + 5:index + 7], "big"), int.from_bytes(raw[index + 3:index + 5], "big")
                break
            index += max(2, length)
    if raw[8:12] == b"WEBP" and len(raw) >= 30 and raw[12:16] == b"VP8X":
        return 1 + int.from_bytes(raw[24:27], "little"), 1 + int.from_bytes(raw[27:30], "little")
    return None


def _validate_assets(assets: Any, base_dir: Path | None, errors: list[str]) -> tuple[set[str], dict[str, dict[str, Any]]]:
    if assets is None:
        assets = []
    if not isinstance(assets, list):
        errors.append("assets must be a list")
        return set(), {}
    ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for index, asset in enumerate(assets):
        location = f"assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{location} must be an object")
            continue
        for field in ("id", "path", "kind"):
            _add(errors, _non_empty(asset.get(field)), f"{location}.{field} is required")
        asset_id = asset.get("id")
        if isinstance(asset_id, str):
            if asset_id in ids:
                errors.append(f"duplicate asset id: {asset_id}")
            ids.add(asset_id)
            by_id[asset_id] = asset
        if asset.get("kind") != "image":
            errors.append(f"{location}.kind must be image")
        path_value = asset.get("path")
        if not isinstance(path_value, str):
            continue
        candidate = Path(path_value)
        if candidate.is_absolute() or ".." in candidate.parts or re.match(r"(?i)^(?:https?:|data:|file:)", path_value):
            errors.append(f"{location}.path must be a safe relative local path: {path_value}")
            continue
        if candidate.suffix.casefold() not in IMAGE_EXTENSIONS:
            errors.append(f"{location}.path must use a supported local image extension: {path_value}")
            continue
        if base_dir is None:
            continue
        resolved_base = base_dir.expanduser().resolve()
        resolved = (resolved_base / candidate).resolve()
        try:
            resolved.relative_to(resolved_base)
        except ValueError:
            errors.append(f"{location}.path escapes the content directory: {path_value}")
            continue
        if not resolved.is_file():
            errors.append(f"{location}.path does not exist: {path_value}")
            continue
        raw = resolved.read_bytes()
        if len(raw) > MAX_IMAGE_BYTES:
            errors.append(f"{location}.path exceeds {MAX_IMAGE_BYTES} bytes: {path_value}")
        signatures = (
            raw.startswith(b"\x89PNG\r\n\x1a\n"),
            raw[:3] == b"\xff\xd8\xff",
            raw[:4] == b"GIF8",
            raw[8:12] == b"WEBP",
        )
        if not any(signatures):
            errors.append(f"{location}.path is not a supported image payload: {path_value}")
        dimensions = _image_dimensions(raw)
        if dimensions and (dimensions[0] > MAX_IMAGE_DIMENSION or dimensions[1] > MAX_IMAGE_DIMENSION):
            errors.append(f"{location}.path exceeds {MAX_IMAGE_DIMENSION}px dimension limit: {path_value}")
    return ids, by_id


def _validate_block(block: Any, location: str, errors: list[str], metrics: dict[str, int], asset_ids: set[str]) -> None:
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
                _add(errors, isinstance(row, list) and len(row) == len(headers), f"{location}.rows[{row_index}] must have {len(headers)} cells")
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
    elif block_type == "image":
        _add(errors, _non_empty(block.get("asset_id")), f"{location}.asset_id is required")
        if block.get("asset_id") not in asset_ids:
            errors.append(f"{location}.asset_id references an unknown image asset: {block.get('asset_id')}")
        if "caption" in block:
            _add(errors, isinstance(block.get("caption"), str), f"{location}.caption must be a string")
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


def _validate_course_context(value: Any, location: str, errors: list[str]) -> None:
    if not isinstance(value, dict) or not value:
        errors.append(f"{location} must be a non-empty object")
        return
    extra = sorted(set(value) - COURSE_CONTEXT_FIELDS)
    errors.extend(f"{location} has unsupported field: {field}" for field in extra)
    for field in COURSE_CONTEXT_STRING_FIELDS & set(value):
        _add(errors, _non_empty(value[field]), f"{location}.{field} must be a non-empty string")
    for field in COURSE_CONTEXT_LIST_FIELDS & set(value):
        _validate_string_list(value[field], f"{location}.{field}", errors)


def _validate_formula_fact_shapes(value: Any, location: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        errors.append(f"{location} must be a list")
        return
    seen: set[str] = set()
    for index, fact in enumerate(value):
        item_location = f"{location}[{index}]"
        if not isinstance(fact, dict):
            errors.append(f"{item_location} must be an object")
            continue
        for field in ("id", "formula", "example_scope"):
            _add(errors, _non_empty(fact.get(field)), f"{item_location}.{field} is required")
        fact_id = fact.get("id")
        if isinstance(fact_id, str):
            if fact_id in seen:
                errors.append(f"{item_location}.id is duplicated")
            seen.add(fact_id)
        if fact.get("example_scope") not in {"abstract", "current-dataset"}:
            errors.append(f"{item_location}.example_scope must be abstract or current-dataset")
        if not _text(fact.get("formula")).strip().startswith("="):
            errors.append(f"{item_location}.formula must start with =")
        if fact.get("example_scope") == "current-dataset":
            for field in ("source_id", "semantic_intent", "operation_location"):
                _add(errors, _non_empty(fact.get(field)), f"{item_location}.{field} is required for current-dataset facts")
            bindings = fact.get("bindings")
            if not isinstance(bindings, dict) or not (bindings.get("input_field") or bindings.get("input_fields")):
                errors.append(f"{item_location}.bindings must declare input_field or input_fields")


def _validate_learning_units(value: Any, facts: list[dict[str, Any]], errors: list[str]) -> tuple[set[str], dict[str, dict[str, Any]]]:
    if not isinstance(value, list) or not value:
        errors.append("learning_units must be a non-empty list")
        return set(), {}
    ids: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    fact_ids = {str(item.get("id")) for item in facts if isinstance(item, dict)}
    for index, unit in enumerate(value):
        location = f"learning_units[{index}]"
        if not isinstance(unit, dict):
            errors.append(f"{location} must be an object")
            continue
        for field in ("id", "title"):
            _add(errors, _non_empty(unit.get(field)), f"{location}.{field} is required")
        unit_id = unit.get("id")
        if isinstance(unit_id, str):
            if unit_id in ids:
                errors.append(f"duplicate learning unit id: {unit_id}")
            ids.add(unit_id)
            by_id[unit_id] = unit
        for field in ("students_should_know", "students_should_be_able_to"):
            _validate_string_list(unit.get(field), f"{location}.{field}", errors)
        for field in ("prerequisites", "not_yet_taught", "canonical_fact_ids"):
            _validate_string_list(unit.get(field, []), f"{location}.{field}", errors, allow_empty=True)
        for fact_id in unit.get("canonical_fact_ids", []):
            if fact_id not in fact_ids:
                errors.append(f"{location}.canonical_fact_ids references unknown fact: {fact_id}")
    return ids, by_id


def _validate_fact_evidence_shape(value: Any, location: str, errors: list[str]) -> None:
    """Validate the transport shape; source agreement belongs to the truth layer."""

    if value is None:
        return
    if not isinstance(value, list):
        errors.append(f"{location} must be a list when present")
        return
    for index, evidence in enumerate(value):
        item_location = f"{location}[{index}]"
        if not isinstance(evidence, dict):
            errors.append(f"{item_location} must be an object")
            continue
        for field in ("source_id", "evidence_type"):
            _add(errors, _non_empty(evidence.get(field)), f"{item_location}.{field} is required")
        if "locator" in evidence and not isinstance(evidence.get("locator"), (str, dict)):
            errors.append(f"{item_location}.locator must be a string or object when present")
        if "quote" in evidence:
            _add(errors, _non_empty(evidence.get("quote")), f"{item_location}.quote must be a non-empty string when present")


def _validate_fact_verification(value: Any, location: str, errors: list[str]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(f"{location} must be an object when present")
        return
    status = value.get("status")
    if status is not None:
        _add(errors, status in {"verified", "source-supported", "inferred", "unverified"}, f"{location}.status is invalid")
    for field in ("method", "verifier", "expected_value", "expected_result", "expression", "derivation_summary", "token_family"):
        if field in value and not isinstance(value.get(field), (str, int, float, bool, type(None))):
            errors.append(f"{location}.{field} must be scalar when present")
    for field in ("key_tokens", "allowed_tokens", "conflict_tokens"):
        if field in value:
            _validate_string_list(value.get(field), f"{location}.{field}", errors, allow_empty=True)


def _validate_facts(value: Any, slide_ids: set[str], errors: list[str]) -> tuple[list[dict[str, Any]], set[str]]:
    if not isinstance(value, list):
        errors.append("canonical_facts must be a list")
        return [], set()
    ids: set[str] = set()
    facts: list[dict[str, Any]] = []
    for index, fact in enumerate(value):
        location = f"canonical_facts[{index}]"
        if not isinstance(fact, dict):
            errors.append(f"{location} must be an object")
            continue
        for field in ("id", "kind", "statement"):
            _add(errors, _non_empty(fact.get(field)), f"{location}.{field} is required")
        _validate_fact_evidence_shape(fact.get("evidence"), f"{location}.evidence", errors)
        _validate_fact_verification(fact.get("verification"), f"{location}.verification", errors)
        if "source_refs" in fact:
            _validate_string_list(fact.get("source_refs"), f"{location}.source_refs", errors, allow_empty=True)
        fact_id = fact.get("id")
        if isinstance(fact_id, str):
            if fact_id in ids:
                errors.append(f"duplicate canonical fact id: {fact_id}")
            ids.add(fact_id)
        values = fact.get("source_slide_ids", [])
        _validate_string_list(values, f"{location}.source_slide_ids", errors, allow_empty=True)
        for ref in values:
            if ref not in slide_ids:
                errors.append(f"{location}.source_slide_ids references unknown id: {ref}")
        facts.append(fact)
    return facts, ids


def _intent_overlap(intent: dict[str, Any], script: str) -> bool:
    script_compact = re.sub(r"\s+", "", script)
    for field in TEACHING_INTENT_FIELDS:
        value = re.sub(r"\s+", "", _text(intent.get(field)))
        if not value:
            return False
        chunks = [value[index:index + 3] for index in range(0, max(0, len(value) - 2), 3)]
        if chunks and not any(chunk in script_compact for chunk in chunks if len(chunk) >= 3):
            return False
    return True


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
    elif block_type in {"svg", "image"}:
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
    normalized, _ = normalize_content(content)
    values = [_text(normalized.get("course_title")), _text(normalized.get("chapter_title"))]
    for slide in normalized.get("slides", []):
        values.extend((_text(slide.get("title")), _text(slide.get("kicker"))))
        for block in slide.get("blocks", []):
            if isinstance(block, dict):
                values.extend(_block_visible_text(block))
    return "\n".join(value for value in values if value)


def _validate_normalized(content: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "slides": 0,
        "blocks": 0,
        "svg_count": 0,
        "svg_elements": 0,
        "stepper_count": 0,
        "session_minutes": 0,
        "prepared_minutes": 0,
        "core_minutes": 0,
        "extension_minutes": 0,
        "planned_slide_minutes": 0,
        "core_slide_minutes": 0,
        "extension_slide_minutes": 0,
        "learning_units": 0,
        "covered_learning_units": 0,
        "uncovered_learning_units": [],
        "canonical_facts": 0,
        "assets": 0,
        "extensions": 0,
        "session_delivery_mode": content.get("session_delivery_mode", "theory-led") if isinstance(content, dict) else "theory-led",
    }
    if not isinstance(content, dict):
        return {"status": "fail", "errors": ["content root must be an object"], "warnings": [], "metrics": metrics}
    allowed_root = {
        "contract_version", "course_title", "chapter_title", "audience", "session_minutes", "prepared_minutes",
        "core_minutes", "extension_minutes", "theme", "course_context", "learning_units", "canonical_facts",
        "assets", "slides",
        "extensions",
        "integrity_version", "formula_facts", "session_delivery_mode",
    }
    errors.extend(f"content has unsupported field: {field}" for field in sorted(set(content) - allowed_root))
    _add(errors, content.get("contract_version") == CONTRACT_VERSION, f"contract_version must be {CONTRACT_VERSION}")
    for field in ("course_title", "chapter_title", "audience"):
        _add(errors, _non_empty(content.get(field)), f"{field} must be a non-empty string")
    duration_fields: dict[str, int] = {}
    for field in ("session_minutes", "prepared_minutes", "core_minutes", "extension_minutes"):
        value = content.get(field)
        _add(errors, isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"{field} must be a non-negative integer")
        if isinstance(value, int) and not isinstance(value, bool):
            duration_fields[field] = value
    _add(errors, duration_fields.get("session_minutes", 0) > 0, "session_minutes must be positive")
    _add(errors, duration_fields.get("prepared_minutes", 0) >= duration_fields.get("session_minutes", 0), "prepared_minutes must be >= session_minutes")
    _add(errors, duration_fields.get("core_minutes", -1) <= duration_fields.get("prepared_minutes", 0), "core_minutes must be <= prepared_minutes")
    _add(errors, duration_fields.get("core_minutes", -1) <= duration_fields.get("session_minutes", 0), "core_minutes must be <= session_minutes")
    if duration_fields:
        _add(errors, duration_fields.get("extension_minutes") == duration_fields.get("prepared_minutes", 0) - duration_fields.get("core_minutes", 0), "extension_minutes must equal prepared_minutes - core_minutes")
    metrics.update(duration_fields)
    if "theme" in content:
        _add(errors, _non_empty(content.get("theme")), "theme must be a non-empty string when present")
    session_delivery_mode = content.get("session_delivery_mode", "theory-led")
    _add(
        errors,
        session_delivery_mode in SESSION_DELIVERY_MODES,
        f"session_delivery_mode must be one of {sorted(SESSION_DELIVERY_MODES)} when present",
    )
    metrics["session_delivery_mode"] = session_delivery_mode
    context = content.get("course_context")
    if context is not None:
        _validate_course_context(context, "course_context", errors)
        if isinstance(context, dict):
            if context.get("course_name") and context.get("course_name") != content.get("course_title"):
                errors.append("course_context.course_name must match course_title")
            if context.get("audience") and context.get("audience") != content.get("audience"):
                errors.append("course_context.audience must match audience")
    integrity_version = content.get("integrity_version")
    if integrity_version is not None and integrity_version != "1.0":
        errors.append("integrity_version must be 1.0 when present")
    _validate_formula_fact_shapes(content.get("formula_facts"), "formula_facts", errors)
    slides = content.get("slides")
    _add(errors, isinstance(slides, list) and len(slides) >= 2, "slides must contain at least two pages")
    if not isinstance(slides, list):
        return {"status": "fail", "errors": errors, "warnings": warnings, "metrics": metrics}
    metrics["slides"] = len(slides)
    slide_ids: set[str] = set()
    for slide in slides:
        if isinstance(slide, dict) and _non_empty(slide.get("id")):
            slide_id = str(slide["id"])
            if slide_id in slide_ids:
                errors.append(f"duplicate slide id: {slide_id}")
            slide_ids.add(slide_id)
    facts, fact_ids = _validate_facts(content.get("canonical_facts"), slide_ids, errors)
    unit_ids, _ = _validate_learning_units(content.get("learning_units"), facts, errors)
    for index, fact in enumerate(facts):
        for ref in fact.get("learning_unit_ids", []):
            if ref not in unit_ids:
                errors.append(f"canonical_facts[{index}].learning_unit_ids references unknown id: {ref}")
    metrics["learning_units"] = len(unit_ids)
    metrics["canonical_facts"] = len(fact_ids)
    asset_ids, _ = _validate_assets(content.get("assets", []), base_dir, errors)
    metrics["assets"] = len(asset_ids)
    extensions = content.get("extensions", [])
    extension_ids: set[str] = set()
    if not isinstance(extensions, list):
        errors.append("extensions must be a list when present")
        extensions = []
    for index, extension in enumerate(extensions):
        location = f"extensions[{index}]"
        if not isinstance(extension, dict):
            errors.append(f"{location} must be an object")
            continue
        for field in ("id", "title", "content", "activity", "use_when"):
            _add(errors, _non_empty(extension.get(field)), f"{location}.{field} is required")
        extension_id = extension.get("id")
        if isinstance(extension_id, str):
            if extension_id in extension_ids:
                errors.append(f"duplicate extension id: {extension_id}")
            extension_ids.add(extension_id)
        minutes = extension.get("minutes")
        _add(errors, isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0, f"{location}.minutes must be a positive integer")
    metrics["extensions"] = len(extension_ids)
    planned = 0
    covered_units: set[str] = set()
    planned_by_track = {"core": 0, "extension": 0}
    for slide_index, slide in enumerate(slides, start=1):
        location = f"slides[{slide_index - 1}]"
        if not isinstance(slide, dict):
            errors.append(f"{location} must be an object")
            continue
        extra_slide = sorted(set(slide) - SLIDE_FIELDS)
        errors.extend(f"{location} has unsupported field: {field}" for field in extra_slide)
        slide_id = slide.get("id")
        _add(errors, _non_empty(slide_id), f"{location}.id must be a non-empty string")
        _add(errors, _non_empty(slide.get("title")), f"{location}.title must be a non-empty string")
        layout = slide.get("layout")
        _add(errors, layout in SUPPORTED_LAYOUTS, f"{location}.layout must be one of {sorted(SUPPORTED_LAYOUTS)}")
        delivery_track = slide.get("delivery_track", "core")
        _add(errors, delivery_track in DELIVERY_TRACKS, f"{location}.delivery_track must be core or extension when present")
        blocks = slide.get("blocks")
        _add(errors, isinstance(blocks, list) and bool(blocks), f"{location}.blocks must be a non-empty list")
        if isinstance(blocks, list):
            for block_index, block in enumerate(blocks):
                _validate_block(block, f"{location}.blocks[{block_index}]", errors, metrics, asset_ids)
        script = slide.get("speaker_script")
        _add(errors, _non_empty(script), f"{location}.speaker_script must be a non-empty string")
        lecture = slide.get("lecture_minutes")
        activity = slide.get("activity_minutes")
        suggested = slide.get("suggested_minutes")
        _add(errors, isinstance(lecture, int) and not isinstance(lecture, bool) and lecture >= 0, f"{location}.lecture_minutes must be a non-negative integer")
        _add(errors, isinstance(activity, int) and not isinstance(activity, bool) and activity >= 0, f"{location}.activity_minutes must be a non-negative integer")
        _add(errors, isinstance(suggested, int) and not isinstance(suggested, bool) and suggested > 0, f"{location}.suggested_minutes must be a positive integer")
        if isinstance(lecture, int) and isinstance(activity, int) and isinstance(suggested, int):
            _add(errors, suggested == lecture + activity, f"{location}.suggested_minutes must equal lecture_minutes + activity_minutes")
            planned += suggested
        unit_refs = slide.get("learning_unit_ids")
        _validate_string_list(unit_refs, f"{location}.learning_unit_ids", errors)
        for ref in unit_refs if isinstance(unit_refs, list) else []:
            if ref not in unit_ids:
                errors.append(f"{location}.learning_unit_ids references unknown unit: {ref}")
            else:
                covered_units.add(ref)
        fact_refs = slide.get("canonical_fact_ids", [])
        _validate_string_list(fact_refs, f"{location}.canonical_fact_ids", errors, allow_empty=True)
        for ref in fact_refs if isinstance(fact_refs, list) else []:
            if ref not in fact_ids:
                errors.append(f"{location}.canonical_fact_ids references unknown fact: {ref}")
        intent = slide.get("teaching_intent")
        if not isinstance(intent, dict):
            errors.append(f"{location}.teaching_intent must be an object")
        else:
            for field in TEACHING_INTENT_FIELDS:
                _add(errors, _non_empty(intent.get(field)), f"{location}.teaching_intent.{field} is required")
            if _non_empty(script) and not _intent_overlap(intent, script):
                warnings.append(f"{location}.teaching_intent should be reconciled with speaker_script")
        if isinstance(suggested, int) and suggested > 0 and delivery_track in planned_by_track:
            planned_by_track[delivery_track] += suggested
        for field in ("kicker", "demo_hint", "classroom_followup", "pacing_note"):
            if field in slide:
                _add(errors, isinstance(slide.get(field), str), f"{location}.{field} must be a string when present")
        if integrity_version == "1.0":
            _add(errors, _non_empty(slide.get("planning_rationale")), f"{location}.planning_rationale is required in integrity mode")
        coverage = slide.get("script_coverage")
        if coverage is not None:
            if not isinstance(coverage, dict) or any(not isinstance(key, str) or not _non_empty(value) for key, value in coverage.items()):
                errors.append(f"{location}.script_coverage must map labels to non-empty excerpts")
    metrics["planned_slide_minutes"] = planned
    metrics["core_slide_minutes"] = planned_by_track["core"]
    metrics["extension_slide_minutes"] = planned_by_track["extension"]
    metrics["covered_learning_units"] = len(covered_units)
    metrics["uncovered_learning_units"] = sorted(unit_ids - covered_units)
    if unit_ids - covered_units:
        errors.append("every learning unit must be covered by at least one slide: " + ", ".join(sorted(unit_ids - covered_units)))
    tolerance = max(1, round(duration_fields.get("prepared_minutes", 0) * 0.10))
    prepared_target = duration_fields.get("prepared_minutes", 0)
    core_target = duration_fields.get("core_minutes", 0)
    if min(abs(planned - prepared_target), abs(planned - core_target)) > tolerance:
        errors.append(
            f"slide planned minutes {planned} must match prepared_minutes {prepared_target} "
            f"or core_minutes {core_target} within ±{tolerance}"
        )
    visible = student_visible_text(content)
    for forbidden in STUDENT_FORBIDDEN:
        if forbidden in visible:
            errors.append(f"student-visible content contains forbidden phrase: {forbidden}")
    for pattern in STUDENT_FORBIDDEN_PATTERNS:
        match = pattern.search(visible)
        if match:
            errors.append(f"student-visible content contains forbidden timing/source pattern: {match.group(0)}")
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "metrics": metrics}


def validate_content(content: Any, *, base_dir: Path | None = None) -> dict[str, Any]:
    """Validate 1.1 content, accepting legacy 1.0 through migration."""

    normalized, migration = normalize_content(content)
    report = _validate_normalized(normalized, base_dir=base_dir)
    report["migration"] = migration
    return report


def load_content(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoursewareContractError(f"cannot read content JSON {path}: {exc}") from exc
    normalized, _ = normalize_content(raw)
    report = _validate_normalized(normalized, base_dir=path.parent)
    if report["status"] != "pass":
        raise CoursewareContractError("invalid courseware content: " + "; ".join(report["errors"]))
    return normalized


def block_visible_text(block: dict[str, Any]) -> list[str]:
    """Public wrapper used by output QA and the renderer."""

    return _block_visible_text(block)


if __name__ == "__main__":  # pragma: no cover - convenience diagnostic
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("content_json", type=Path)
    args = parser.parse_args()
    result = validate_content(json.loads(args.content_json.read_text(encoding="utf-8")), base_dir=args.content_json.parent)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "pass" else 1)
