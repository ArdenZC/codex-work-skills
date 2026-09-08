"""Pure formatters for Lesson Content V2/V2.1/V2.2.

This module deliberately does not invent teaching language.  It only maps
validated JSON values to the text representations used by the existing Word
template.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


CONTENT_CONTRACT_VERSION = "2.2"
COMPATIBLE_CONTENT_CONTRACT_VERSIONS = ("2.0", "2.1", "2.2")
LEGACY_CONTENT_CONTRACT_VERSION = "2.0"
EVALUATION_SCORE_MIN = Decimal("85")
EVALUATION_SCORE_MAX = Decimal("96")
EVALUATION_SCORE_STEP = Decimal("0.5")
CAPABILITY_STAGES = ("认知", "理解", "模仿", "独立", "综合", "优化", "迁移")
LESSON_TYPES = ("theory", "practice", "integrated")
DELIVERY_MODES = (
    "theory_only",
    "practice_only",
    "split_lessons",
    "integrated_lessons",
    "hybrid",
)
REFERENCE_TYPES = (
    "book",
    "standard",
    "official_manual",
    "official_documentation",
    "guideline",
    "paper",
    "formal_course_document",
)
REFERENCE_SOURCE_KINDS = ("provided", "generic", "verified_public")
PRACTICE_TASK_GRANULARITIES = ("per_lesson", "per_task", "per_project")
MAX_FILENAME_BYTES = 255
ONLINE_COURSE_PLATFORM_ONLY = frozenset(
    {
        "国家高等教育智慧教育平台",
        "中国大学MOOC",
        "学堂在线",
        "爱课程",
    }
)
CONFIRMED_COURSE_INFO_TEXT_FIELDS = ("course_name", "major", "audience")
CONFIRMED_COURSE_INFO_HOUR_FIELDS = ("total_hours", "theory_hours", "practice_hours")
CONFIRMED_COURSE_INFO_FIELDS = CONFIRMED_COURSE_INFO_TEXT_FIELDS + (
    *CONFIRMED_COURSE_INFO_HOUR_FIELDS,
    "delivery_mode",
)

# This is intentionally a small, conservative boundary check.  It catches
# standalone classroom tools without rejecting document titles that happen to
# contain a product name (for example, "MySQL 8.0 Reference Manual").
REFERENCE_RESOURCE_ONLY_EXACT = frozenset(
    {
        "投影仪",
        "ppt",
        "课程ppt",
        "课堂ppt",
        "教学ppt",
        "ppt课件",
        "mysqlworkbench",
        "血压计",
        "数据库服务器",
        "护理模型",
        "计算机机房",
        "虚拟机",
        "实训任务单",
        "课堂练习材料",
        "案例数据集",
        "课程课件",
        "教学课件",
        "课堂课件",
        "课程案例",
        "教学案例",
        "案例",
        "教学资源",
        "课程资源",
        "内部教学资源",
    }
)
REFERENCE_RESOURCE_ONLY_PATTERN = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百0-9]+章[^。！？\n]{0,80}pptx?"
    r"|(?:课程|课堂|教学|内部)(?:教学)?(?:pptx?|课件|资源)"
    r"|ppt课件"
    r"|(?:课程|课堂|教学|内部)?案例(?:表|集|数据集|材料|卡片|清单|文件)?"
    r"|(?:课堂练习材料|实训任务单)"
    r")$",
    re.IGNORECASE,
)
REFERENCE_PLACEHOLDER_PATTERN = re.compile(
    r"(?:^(?:相关|有关|本课程|课程)(?:的)?(?:公开)?(?:网络)?(?:资料|文献|文档|指南|教材|参考资料|网络资源)$)"
    r"|(?:相关|有关)(?:的)?(?:公开)?(?:网络)?(?:资料|文献|文档|指南|教材|参考资料|网络资源)$",
    re.IGNORECASE,
)

IMPLEMENTATION_STAGE_IDS = (
    "before_class_preparation",
    "task_introduction",
    "operation_demonstration",
    "task_implementation",
    "task_extension",
    "project_practice",
    "peer_review",
    "lesson_summary",
    "after_class_improvement",
)

IN_CLASS_STAGE_IDS = frozenset(IMPLEMENTATION_STAGE_IDS[1:-1])
IMPLEMENTATION_STAGE_FIELDS = (
    "content",
    "teacher_actions",
    "student_actions",
    "objective",
)

# These IDs follow the 13 writable rows in the canonical evaluation table.
EVALUATION_CRITERIA = (
    ("attendance", 3, "考勤"),
    ("attention", 3, "专注度"),
    ("participation", 4, "参与度"),
    ("compliance", 5, "遵守规范、守法意识"),
    ("values", 5, "职业价值观"),
    ("ethics", 5, "职业伦理"),
    ("habits", 5, "行为习惯、环境维护"),
    ("online_learning", 10, "线上学习情况统计"),
    ("discussion", 10, "课中讨论、答题等"),
    ("homework", 10, "课后作业"),
    ("practice", 25, "实操实训情况"),
    ("presentation", 10, "成果展示"),
    ("improvement", 5, "后续改进拓展"),
)
EVALUATION_CRITERION_IDS = tuple(item[0] for item in EVALUATION_CRITERIA)

CONTENT_FIELD_NAMES = (
    "student_base",
    "student_problems",
    "student_strategy",
    "teaching_content",
    "quality_goal",
    "knowledge_goal",
    "ability_goal",
    "key_content",
    "key_strategy",
    "difficult_content",
    "difficult_strategy",
    "teaching_methods",
    "resources",
    "references",
)


def _clean(value: Any) -> str:
    return str(value).strip()


MECHANICAL_TOPIC_MARKERS = (
    "聚焦",
    "聚焦于",
    "围绕",
    "针对",
    "对应主题",
    "核心主题",
    "本节主题",
    "任务主题",
    "本节关联",
)
_MECHANICAL_TOPIC_MARKER_PATTERN = r"(?:聚焦(?:于)?|围绕|针对|对应主题|核心主题|本节主题|任务主题|本节关联)"
MECHANICAL_TOPIC_PAREN_SUFFIX_PATTERN = re.compile(
    rf"\s*[（(]\s*{_MECHANICAL_TOPIC_MARKER_PATTERN}\s*(?:[:：])?\s*[^（）()]*[）)]\s*$"
)
MECHANICAL_TOPIC_TAIL_SUFFIX_PATTERN = re.compile(
    rf"(?:[。！？；;,，]\s*|\s+){_MECHANICAL_TOPIC_MARKER_PATTERN}\s*[:：]\s*[^。！？；;,，\n]+$"
)
MECHANICAL_TOPIC_ONLY_PATTERN = re.compile(
    rf"^{_MECHANICAL_TOPIC_MARKER_PATTERN}\s*[:：]\s*.+$"
)


def strip_mechanical_topic_suffix(value: Any) -> str:
    """Remove QA-oriented topic tails without rewriting ordinary prose."""

    text = _clean(value)
    previous = None
    while text and text != previous:
        previous = text
        text = MECHANICAL_TOPIC_PAREN_SUFFIX_PATTERN.sub("", text).strip()
        text = MECHANICAL_TOPIC_TAIL_SUFFIX_PATTERN.sub("", text).strip()
    if MECHANICAL_TOPIC_ONLY_PATTERN.fullmatch(text):
        return ""
    return text


def confirmed_course_info_errors(data: dict[str, Any]) -> list[str]:
    """Check that the optional intake snapshot and normalized contract agree."""

    snapshot = data.get("confirmed_course_info")
    if snapshot is None:
        return []
    if not isinstance(snapshot, dict):
        return ["confirmed_course_info must be an object"]

    errors: list[str] = []
    for field_name in CONFIRMED_COURSE_INFO_TEXT_FIELDS:
        if field_name not in snapshot:
            errors.append(f"confirmed_course_info.{field_name} is required")
        elif data.get(field_name) != snapshot[field_name]:
            errors.append(
                f"{field_name} must equal the user-confirmed value in confirmed_course_info"
            )

    plan = data.get("delivery_plan") if isinstance(data.get("delivery_plan"), dict) else {}

    def same_number(left: Any, right: Any) -> bool:
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except (InvalidOperation, TypeError, ValueError):
            return left == right

    numeric_sources = {
        "total_hours": data.get("total_hours"),
        "theory_hours": plan.get("theory_hours"),
        "practice_hours": plan.get("practice_hours"),
    }
    for field_name in CONFIRMED_COURSE_INFO_HOUR_FIELDS:
        if field_name not in snapshot:
            errors.append(f"confirmed_course_info.{field_name} is required")
        elif not same_number(numeric_sources[field_name], snapshot[field_name]):
            errors.append(
                f"{field_name} must equal the user-confirmed value in confirmed_course_info"
            )
    if "delivery_mode" not in snapshot:
        errors.append("confirmed_course_info.delivery_mode is required")
    elif plan.get("mode") != snapshot["delivery_mode"]:
        errors.append("delivery_plan.mode must equal confirmed_course_info.delivery_mode")
    return errors


def course_info_values(data: dict[str, Any]) -> dict[str, Any]:
    """Return frozen intake values when present, falling back to compatible inputs."""

    snapshot = data.get("confirmed_course_info")
    return {
        field_name: snapshot[field_name] if isinstance(snapshot, dict) and field_name in snapshot else data[field_name]
        for field_name in ("course_name", "major", "audience")
    }


def safe_name(text: str) -> str:
    """Make a deterministic filesystem-safe lesson filename component."""

    text = re.sub(r"\s+", "", str(text))
    return re.sub(r'[\\/:*?"<>|]+', "", text)


def _utf8_prefix(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def lesson_filename(seq: int, unit: str, task: str) -> str:
    prefix, suffix = f"教案{seq:02d}_", ".docx"
    stem = f"{safe_name(unit)}_{safe_name(task)}"
    filename = f"{prefix}{stem}{suffix}"
    if len(filename.encode("utf-8")) <= MAX_FILENAME_BYTES:
        return filename
    digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:10]
    marker = f"~{digest}"
    budget = MAX_FILENAME_BYTES - len((prefix + marker + suffix).encode("utf-8"))
    return f"{prefix}{_utf8_prefix(stem, budget)}{marker}{suffix}"


def format_numbered_list(items: Iterable[Any]) -> str:
    """Number existing list items without adding or removing their meaning."""

    values = [strip_mechanical_topic_suffix(item) for item in items]
    values = [value for value in values if value]
    return "\n".join(f"{index}. {value}" for index, value in enumerate(values, 1))


_EDITION_PAREN_PATTERN = re.compile(
    r"[（(]\s*第\s*[一二三四五六七八九十百千万零〇0-9]+\s*版\s*[）)]$",
    re.IGNORECASE,
)
_EDITION_SUFFIX_PATTERN = re.compile(
    r"(?:[》>】\]）)]\s*)?(?:[·,，;；:/\s]*)第\s*[一二三四五六七八九十百千万零〇0-9]+\s*版$",
    re.IGNORECASE,
)


def _normalize_reference_title(value: Any) -> str:
    """Normalize identity without collapsing distinct subject titles."""

    title = unicodedata.normalize("NFKC", _clean(value))
    title = re.sub(r"\s+", "", title)
    previous = None
    while title and title != previous:
        previous = title
        title = re.sub(r"^[《<【\[]", "", title)
        title = re.sub(r"[》>】\]]$", "", title)
        title = _EDITION_PAREN_PATTERN.sub("", title)
        title = _EDITION_SUFFIX_PATTERN.sub("", title)
    return title.casefold()


def reference_identity(reference: dict[str, Any]) -> str:
    """Return a conservative source identity used for textbook-overlap checks."""

    title = _normalize_reference_title(reference.get("title", reference.get("text", "")))
    if title:
        return title
    authors = reference.get("authors", [])
    if isinstance(authors, (list, tuple)):
        author_text = "".join(_clean(value) for value in authors)
    else:
        author_text = _clean(authors)
    return re.sub(r"\s+", "", author_text).casefold()


def reference_looks_like_resource_only(text: Any) -> bool:
    """Return true for an unmistakable standalone teaching resource."""

    normalized = unicodedata.normalize("NFKC", str(text))
    normalized = re.sub(r"\s+", "", normalized).strip().casefold()
    compact = "".join(char for char in normalized if not unicodedata.category(char).startswith("P"))
    return compact in REFERENCE_RESOURCE_ONLY_EXACT or bool(REFERENCE_RESOURCE_ONLY_PATTERN.fullmatch(compact))


def reference_looks_like_placeholder(text: Any) -> bool:
    """Detect generic placeholder wording without blocking real named documents."""

    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text)).strip())
    return bool(REFERENCE_PLACEHOLDER_PATTERN.search(normalized))


def format_reference(reference: dict[str, Any]) -> str:
    """Format a reference as formal citation text, omitting internal evidence."""

    if "text" in reference and "reference_type" not in reference:
        return _clean(reference.get("text", ""))
    authors = reference.get("authors", [])
    if isinstance(authors, (list, tuple)):
        author_text = "、".join(_clean(value) for value in authors if _clean(value))
    else:
        author_text = _clean(authors) if authors else ""
    title = _clean(reference.get("title", ""))
    title = re.sub(r"^[《<【\[]|[》>】\]]$", "", title)
    reference_type = reference.get("reference_type")
    institution = _clean(reference.get("institution", ""))
    edition = _clean(reference.get("edition", ""))
    publisher = _clean(reference.get("publisher", ""))
    year = _clean(reference.get("year", ""))
    if edition and edition not in title:
        if title.endswith(("）", ")")) and ("（" in title or "(" in title):
            title = f"{title[:-1]}·{edition}{title[-1]}"
        else:
            title = f"{title}·{edition}" if title else edition

    course_label = False
    if reference_type == "formal_course_document":
        if institution and institution not in author_text:
            author_text = f"{author_text}（{institution}）" if author_text else institution
        course_label = bool(title and not re.search(r"课程$", title))

    # For an official online/manual source, an organization entered as the
    # publisher is the visible authority, not a technical trailing field.
    if reference_type in {"official_manual", "official_documentation"} and not author_text and publisher:
        author_text, publisher = publisher, ""
    title_text = f"《{title}》" if title else ""
    if course_label:
        title_text = f"{title_text}课程"
    core = f"{author_text}：{title_text}" if author_text and title_text else author_text or title_text
    tail = [value for value in (publisher, year) if value]
    citation = "，".join([core, *tail]) if core and tail else core or "，".join(tail)
    return f"{citation}。" if citation else ""


def reference_metadata_errors(reference: dict[str, Any], prefix: str = "reference") -> list[str]:
    """Require visible bibliographic responsibility for typed 2.2 sources."""

    reference_type = reference.get("reference_type")
    authors = reference.get("authors", [])
    if isinstance(authors, (list, tuple)):
        author_values = [_clean(value) for value in authors if _clean(value)]
    else:
        author_values = [_clean(authors)] if _clean(authors) else []
    publisher = _clean(reference.get("publisher", ""))
    institution = _clean(reference.get("institution", ""))
    year = _clean(reference.get("year", ""))
    errors: list[str] = []

    if reference_type == "book":
        if not author_values:
            errors.append(f"{prefix}.authors must preserve the real book author or editor")
        if not publisher:
            errors.append(f"{prefix}.publisher is required for a book")
    elif reference_type == "formal_course_document":
        if not author_values:
            errors.append(f"{prefix}.authors must preserve the course responsible teacher or team")
        elif all(value in ONLINE_COURSE_PLATFORM_ONLY for value in author_values):
            errors.append(
                f"{prefix}.authors must name a real course responsible teacher/team, not only the hosting platform"
            )
        if not institution:
            errors.append(f"{prefix}.institution must preserve the offering university or institution")
        if not publisher:
            errors.append(f"{prefix}.publisher must preserve the course platform or publisher")
    elif reference_type == "paper" and not author_values:
        errors.append(f"{prefix}.authors must preserve the real paper author or team")
    elif reference_type in {"standard", "official_manual", "official_documentation", "guideline"}:
        if not author_values and not publisher:
            errors.append(f"{prefix} must preserve a responsible organization or publisher")
    return errors


def lesson_references(data: dict[str, Any] | None, lesson: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve a lesson's renderable references for either contract version."""

    if not data or data.get("content_contract_version") not in {"2.1", "2.2"}:
        return list(lesson.get("references", []))
    pool = {
        str(reference.get("reference_id")): reference
        for reference in data.get("reference_pool", [])
        if isinstance(reference, dict) and reference.get("reference_id")
    }
    resolved: list[dict[str, Any]] = []
    for reference_id in lesson.get("reference_ids", []):
        reference = pool.get(str(reference_id))
        if reference is None:
            resolved.append(
                {
                    "reference_id": str(reference_id),
                    "reference_type": "formal_course_document",
                    "title": str(reference_id),
                    "source_kind": "",
                    "text": str(reference_id),
                }
            )
            continue
        item = dict(reference)
        item["text"] = format_reference(item)
        resolved.append(item)
    return resolved


def format_reference_list(references: Iterable[dict[str, Any]]) -> str:
    """Write only formal citation text; provenance/evidence stays internal."""

    return format_numbered_list(format_reference(reference) for reference in references)


def format_student_analysis(analysis: dict[str, Any]) -> dict[str, str]:
    return {
        "student_base": format_numbered_list(analysis["base"]),
        "student_problems": format_numbered_list(analysis["problems"]),
        "student_strategy": format_numbered_list(analysis["strategies"]),
    }


def format_goal_list(goals: dict[str, Any]) -> dict[str, str]:
    return {
        "knowledge_goal": format_numbered_list(goals["knowledge"]),
        "ability_goal": format_numbered_list(goals["ability"]),
        "quality_goal": format_numbered_list(goals["quality"]),
    }


def format_implementation_stage(stage: dict[str, Any]) -> dict[int, str]:
    """Return the five existing implementation-cell values for one stage."""

    minutes = Decimal(str(stage["minutes"]))
    minutes_text = str(int(minutes)) if minutes == minutes.to_integral_value() else format(minutes, "f")
    return {
        0: f"{strip_mechanical_topic_suffix(stage['label'])}\n{minutes_text}min\n{strip_mechanical_topic_suffix(stage['modality'])}",
        1: format_numbered_list(stage["content"]),
        2: format_numbered_list(stage["teacher_actions"]),
        3: format_numbered_list(stage["student_actions"]),
        4: strip_mechanical_topic_suffix(stage["objective"]),
    }


def format_implementation(implementation: Iterable[dict[str, Any]]) -> list[dict[int, str]]:
    return [format_implementation_stage(stage) for stage in implementation]


def format_reflection(reflection: dict[str, Any]) -> list[str]:
    return [
        strip_mechanical_topic_suffix(reflection["summary"]),
        strip_mechanical_topic_suffix(reflection["innovation"]),
        strip_mechanical_topic_suffix(reflection["improvement"]),
    ]


def lesson_content_field_values(
    lesson: dict[str, Any],
    data: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Map a V2/V2.1 lesson to all non-header cells in the canonical template."""

    values: dict[str, str] = {}
    values.update(format_student_analysis(lesson["student_analysis"]))
    values["teaching_content"] = format_numbered_list(lesson["teaching_content"])
    values.update(format_goal_list(lesson["goals"]))
    values["key_content"] = format_numbered_list(lesson["key_point"]["content"])
    values["key_strategy"] = format_numbered_list(lesson["key_point"]["strategy"])
    values["difficult_content"] = format_numbered_list(lesson["difficult_point"]["content"])
    values["difficult_strategy"] = format_numbered_list(lesson["difficult_point"]["strategy"])
    values["teaching_methods"] = format_numbered_list(lesson["teaching_methods"])
    values["resources"] = format_numbered_list(lesson["resources"])
    values["references"] = format_reference_list(lesson_references(data, lesson))
    return values


def lesson_header_values(data: dict[str, Any], lesson: dict[str, Any]) -> dict[str, str]:
    course_info = course_info_values(data)
    return {
        "course_name": _clean(course_info["course_name"]),
        "major": _clean(course_info["major"]),
        "audience": _clean(course_info["audience"]),
        "unit": _clean(lesson["unit"]),
        "task": _clean(lesson["task"]),
        "hours": _clean(lesson["hours"]),
    }


def format_evaluation_values(lesson: dict[str, Any], scores: Iterable[Any]) -> list[dict[int, str]]:
    remarks = lesson["evaluation"]["remarks"]
    values: list[dict[int, str]] = []
    for criterion, score in zip(EVALUATION_CRITERIA, scores):
        criterion_id = criterion[0]
        score_decimal = Decimal(str(score))
        score_text = (
            str(int(score_decimal))
            if score_decimal == score_decimal.to_integral_value()
            else format(score_decimal, "f")
        )
        values.append({2: score_text, 3: strip_mechanical_topic_suffix(remarks[criterion_id])})
    return values


def format_title(sequence: int, data: dict[str, Any], lesson: dict[str, Any]) -> str:
    course_info = course_info_values(data)
    return f"{sequence} 《{_clean(course_info['course_name'])}》教学单元设计：{_clean(lesson['task'])}"
