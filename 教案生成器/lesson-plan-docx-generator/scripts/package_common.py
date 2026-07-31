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
    for index, lesson in enumerate(data.get("lessons", [])):
        if isinstance(lesson, dict) and isinstance(lesson.get("unit"), str):
            unit = lesson["unit"].strip()
            if not unit.startswith("项目"):
                raise ValueError(
                    f"lessons[{index}].unit must start with 项目 for projectized teaching; received {lesson['unit']!r}."
                )


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


def composed_lesson_fields(
    unit: str,
    task: str,
    flows: list[Any],
    knowledge: list[Any],
    tools: Any = "课程PPT、微课视频、任务单、评分表和成果模板",
) -> dict[str, str]:
    numbered_flows = _numbered_text(flows)
    numbered_knowledge = _numbered_text(knowledge)
    return {
        "teaching_content": (
            f"围绕“{unit}”开展“{task}”，完成以下任务：\n"
            f"{numbered_flows}\n"
            f"核心知识点：\n"
            f"{numbered_knowledge}"
        ).rstrip("\n"),
        "knowledge_goal": numbered_knowledge or f"1. 理解{task}的核心概念\n2. 掌握相关流程和成果要求",
        "resources": (
            "1. 教学环境：标准机房、多媒体设备、网络环境及课程实训平台\n"
            f"2. 实训工具：{str(tools)}\n"
            "3. 数字资源：课程PPT、微课视频、任务单、评分表和成果模板"
        ),
    }


def implementation_cell_values(task: str, flows: list[Any]) -> list[dict[int, str]]:
    numbered_flows = _numbered_text(flows[:3])
    return [
        {
            0: "课前准备\n10min\n线上+线下",
            1: f"阅读任务单，了解{task}的成果要求和评价标准",
            2: "1. 发布任务单和模板\n2. 推送操作提示\n3. 收集预习问题",
            3: "1. 阅读任务材料\n2. 检查工具环境\n3. 标记疑问",
            4: "保证任务开始前目标明确、环境可用",
        },
        {
            0: "任务导入5min\n线下",
            1: f"以项目情境导入“{task}”，说明本次任务产出物",
            2: "1. 展示项目背景\n2. 明确任务边界\n3. 说明评分要点",
            3: "1. 了解项目情境\n2. 明确小组分工\n3. 确认成果要求",
            4: "用真实任务激活学习动机，形成任务驱动",
        },
        {
            0: "操作示范\n15min\n线下",
            1: f"示范本次任务关键步骤：\n{numbered_flows}",
            2: "1. 演示关键流程\n2. 提醒易错点\n3. 展示合格成果样例",
            3: "1. 观察记录\n2. 对照模板理解要求\n3. 提问确认",
            4: "降低实操门槛，让学生掌握基本路径",
        },
        {
            0: "任务实施\n25min\n线下",
            1: f"小组完成{task}，形成课堂阶段性成果",
            2: "1. 巡视指导\n2. 解答工具和流程问题\n3. 记录共性问题",
            3: "1. 按分工完成任务\n2. 记录操作过程\n3. 整理成果文件",
            4: "通过做中学完成知识、技能和规范的转化",
        },
        {
            0: "任务拓展\n10min\n线下",
            1: "根据教师反馈修正记录、脚本、用例或文档中的问题",
            2: "1. 点评典型问题\n2. 指导小组修正\n3. 强调质量标准",
            3: "1. 对照反馈修改\n2. 复查成果完整性\n3. 完成自评",
            4: "强化规范意识和质量闭环",
        },
        {
            0: "项目实训\n15min\n线下",
            1: f"提交{task}相关成果包，包括记录、截图、脚本或文档",
            2: "1. 检查提交材料\n2. 抽查关键成果\n3. 给出即时建议",
            3: "1. 提交成果包\n2. 补充说明\n3. 记录改进点",
            4: "形成可评价、可追溯的学习成果",
        },
        {
            0: "组间互评8min\n线下",
            1: "小组交换成果，从正确性、完整性、规范性和可复现性四方面互评",
            2: "1. 下发互评标准\n2. 组织互评\n3. 抽取典型成果点评",
            3: "1. 根据标准互评\n2. 记录建议\n3. 完善本组成果",
            4: "让评价标准显性化，促进互学互改",
        },
        {
            0: "课堂小结7min\n线下",
            1: "归纳本次任务的关键流程、常见问题和成果规范",
            2: "1. 总结重难点\n2. 发布课后完善要求\n3. 提醒下次课准备",
            3: "1. 回顾任务过程\n2. 完成自评\n3. 明确课后任务",
            4: "帮助学生沉淀经验，形成持续改进意识",
        },
        {
            0: "课后完善\n15min\n线上+线下",
            1: "根据课堂反馈完善成果包，并在线提交最终版本",
            2: "1. 在线答疑\n2. 检查最终提交\n3. 记录过程性成绩",
            3: "1. 修改成果\n2. 上传最终版本\n3. 完成学习反思",
            4: "延伸课堂任务，保证成果质量",
        },
    ]


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
    resources_spec = field_spec(manifest, "resources")
    implementation_spec = field_spec(manifest, "implementation")
    title_spec = field_spec(manifest, "title")
    for index, lesson in enumerate(data.get("lessons", []), start=1):
        if not isinstance(lesson, dict):
            continue
        unit = str(lesson.get("unit", ""))
        task = str(lesson.get("task", ""))
        course = str(lesson.get("course_name") or data.get("course_name", ""))
        flows = [str(item) for item in lesson.get("flows", [])]
        knowledge = [str(item) for item in lesson.get("knowledge", [])]
        composed = composed_lesson_fields(
            unit,
            task,
            flows,
            knowledge,
            lesson.get("tools", "课程PPT、微课视频、任务单、评分表和成果模板"),
        )
        _validate_composed_limit(
            f"lessons[{index - 1}].teaching_content",
            composed["teaching_content"],
            teaching_spec,
        )
        _validate_composed_limit(
            f"lessons[{index - 1}].knowledge_goal",
            composed["knowledge_goal"],
            knowledge_goal_spec,
        )
        _validate_composed_limit(
            f"lessons[{index - 1}].resources",
            composed["resources"],
            resources_spec,
        )
        hours_spec = field_spec(manifest, "hours")
        _validate_composed_limit(
            f"lessons[{index - 1}].hours",
            str(lesson.get("hours", "")).strip(),
            hours_spec,
        )
        for row_index, values in enumerate(implementation_cell_values(task, flows), start=1):
            for cell_index, value in values.items():
                _validate_composed_limit(
                    f"lessons[{index - 1}].implementation row {row_index} cell {cell_index}",
                    str(value),
                    implementation_spec,
                )
        title = f"{index} 《{course}》教学单元设计：{task}"
        _validate_composed_limit(f"lessons[{index - 1}].title", title, title_spec)
