from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "manifest.yaml"
DEFAULT_SCHEMA = SKILL_DIR / "schemas" / "lesson-plan-input.schema.json"
MAX_TEACHING_CONTENT_ITEMS = 8


def load_manifest(path: Path | str = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = yaml.safe_load(stream) or {}
    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest must be a YAML object: {manifest_path}")
    manifest["_path"] = str(manifest_path)
    return manifest


def manifest_template_path(manifest: dict[str, Any]) -> Path:
    manifest_path = Path(manifest["_path"])
    file_value = manifest.get("template", {}).get("file")
    if not file_value:
        raise ValueError("Manifest is missing template.file")
    return (manifest_path.parent / str(file_value)).resolve()


def load_schema(path: Path | str = DEFAULT_SCHEMA) -> dict[str, Any]:
    schema_path = Path(path).expanduser().resolve()
    with schema_path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    if not isinstance(schema, dict):
        raise ValueError(f"Schema must be a JSON object: {schema_path}")
    return schema


def _validate_positive_number(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive number; received {value}.") from None
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field_name} must be a positive number; received {value}.")


def validate_input(data: dict[str, Any], schema_path: Path | str = DEFAULT_SCHEMA) -> None:
    for field_name in ("default_hours", "total_hours"):
        if field_name in data:
            _validate_positive_number(data[field_name], field_name)

    for index, lesson in enumerate(data.get("lessons", [])):
        if isinstance(lesson, dict) and "hours" in lesson:
            _validate_positive_number(lesson["hours"], f"lessons[{index}].hours")
        if isinstance(lesson, dict):
            flows = lesson.get("flows", [])
            knowledge = lesson.get("knowledge", [])
            if isinstance(flows, list) and isinstance(knowledge, list):
                content_items = len(flows) + len(knowledge)
                if content_items > MAX_TEACHING_CONTENT_ITEMS:
                    raise ValueError(
                        f"lessons[{index}] flows and knowledge combined must contain at most "
                        f"{MAX_TEACHING_CONTENT_ITEMS} items; received {content_items}."
                    )
        if not isinstance(lesson, dict) or "score" not in lesson:
            continue
        try:
            score = Decimal(str(lesson["score"]))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not score.is_finite() or score % Decimal("0.5") != 0:
            raise ValueError(
                f"lessons[{index}].score must use 0.5-point increments; received {lesson['score']}."
            )
    schema = load_schema(schema_path)
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise ValueError(f"Input schema validation failed: {details}")


def ensure_supported_major(manifest: dict[str, Any]) -> None:
    version = str(manifest.get("template", {}).get("version", ""))
    supported = manifest.get("generator", {}).get("supported_major")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Manifest must declare a semantic template version and generator.supported_major")
    try:
        major = int(version.split(".", 1)[0])
        supported_major = int(supported)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Manifest must declare a semantic template version and generator.supported_major") from exc
    if major != supported_major:
        raise ValueError(f"Unsupported template major version {major}; generator supports {supported_major}")


def field_spec(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    fields = manifest.get("fields", {})
    value = fields.get(name)
    if not isinstance(value, dict):
        raise KeyError(f"Manifest field is missing or invalid: {name}")
    return value


def _numbered_text(items: list[Any]) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(values, 1))


def _validate_composed_limit(label: str, value: str, spec: dict[str, Any]) -> None:
    max_chars = spec.get("max_chars")
    if max_chars is not None and len(value) > int(max_chars):
        raise ValueError(f"{label} exceeds manifest max_chars={max_chars}: {len(value)}")
    max_paragraphs = spec.get("max_paragraphs")
    paragraph_count = len(value.splitlines()) or 1
    if max_paragraphs is not None and paragraph_count > int(max_paragraphs):
        raise ValueError(
            f"{label} exceeds manifest max_paragraphs={max_paragraphs}: {paragraph_count}"
        )


def validate_composed_fields(data: dict[str, Any], manifest: dict[str, Any]) -> None:
    teaching_spec = field_spec(manifest, "teaching_content")
    knowledge_goal_spec = field_spec(manifest, "knowledge_goal")
    title_spec = field_spec(manifest, "title")
    for index, lesson in enumerate(data.get("lessons", []), start=1):
        if not isinstance(lesson, dict):
            continue
        unit = str(lesson.get("unit", ""))
        task = str(lesson.get("task", ""))
        course = str(lesson.get("course_name") or data.get("course_name", ""))
        flows = [str(item) for item in lesson.get("flows", [])]
        knowledge = [str(item) for item in lesson.get("knowledge", [])]
        teaching_content = (
            f"围绕“{unit}”开展“{task}”，完成以下任务：\n"
            f"{_numbered_text(flows)}\n"
            f"核心知识点：\n"
            f"{_numbered_text(knowledge)}"
        )
        _validate_composed_limit(
            f"lessons[{index - 1}].teaching_content",
            teaching_content,
            teaching_spec,
        )
        knowledge_goal = _numbered_text(knowledge) or f"1. 理解{task}的核心概念\n2. 掌握相关流程和成果要求"
        _validate_composed_limit(
            f"lessons[{index - 1}].knowledge_goal",
            knowledge_goal,
            knowledge_goal_spec,
        )
        title = f"{index} 《{course}》教学单元设计：{task}"
        _validate_composed_limit(f"lessons[{index - 1}].title", title, title_spec)
