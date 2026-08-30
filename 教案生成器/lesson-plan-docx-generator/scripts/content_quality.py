"""Deterministic course-level quality checks for Lesson Content V2."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from content_contract import (
    CAPABILITY_STAGES,
    CONTENT_FIELD_NAMES,
    EVALUATION_CRITERIA,
    EVALUATION_CRITERION_IDS,
    EVALUATION_SCORE_MAX,
    EVALUATION_SCORE_MIN,
    EVALUATION_SCORE_STEP,
    IMPLEMENTATION_STAGE_FIELDS,
    IN_CLASS_STAGE_IDS,
    IMPLEMENTATION_STAGE_IDS,
    format_implementation_stage,
    format_reflection,
    format_title,
    lesson_content_field_values,
)


# This starts at the level where a repeated Chinese sentence is substantive,
# while allowing short labels and shared technical terms to recur.
MIN_SENTENCE_LENGTH = 12
REPEATED_SENTENCE_LESSON_COUNT = 3
# The threshold is deliberately aligned with the old six-lesson baseline
# (0.8827 maximum SequenceMatcher score), while new fixtures remain below it.
WHOLE_LESSON_SIMILARITY_THRESHOLD = 0.85
# The calibration tests exercise copy+rename, 20% wording edits, synonym/word
# order edits, and genuinely different lessons.  The adjacent threshold is
# lower because a copied neighboring lesson is actionable even when its whole
# text score is diluted by otherwise different fields.
FIELD_SIMILARITY_THRESHOLD = 0.85
ADJACENT_WHOLE_LESSON_SIMILARITY_THRESHOLD = 0.78
ADJACENT_FIELD_SIMILARITY_THRESHOLD = 0.78
IMPLEMENTATION_SIMILARITY_THRESHOLD = 0.85
ADJACENT_IMPLEMENTATION_SIMILARITY_THRESHOLD = 0.78
IMPLEMENTATION_DUPLICATE_LESSON_COUNT = 3

# Structural repetition is deliberately a separate signal.  It is applied to
# sufficiently long narrative items after masking task-specific entities, so
# a shared verb or a recurring tool name cannot fail a lesson by itself.
STRUCTURAL_SIMILARITY_THRESHOLD = 0.86
ADJACENT_STRUCTURAL_SIMILARITY_THRESHOLD = 0.82
IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD = 0.84
ADJACENT_IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD = 0.80
STRUCTURAL_MIN_ITEM_LENGTH = 18
STRUCTURAL_MIN_ACTIONS = 1
STRUCTURAL_SHORT_FIELDS = ("student_analysis.", "goals.", "reflection.")
PROGRESSION_DECLARED_SAME_UNIT_THRESHOLD = 0.052
# The calibrated positive corpus starts at .176 and the largest negative score
# is 0 after removing the generic "方案" token. The existing cross-domain
# fixture scores .0502, so .045 preserves it while remaining well below a
# calibrated positive pair.
PROGRESSION_DECLARED_BOUNDARY_THRESHOLD = 0.045
PROGRESSION_SEQUENCE_THRESHOLD = 0.018
PROGRESSION_MIN_BIGRAM_SIGNAL = 0.025
PROGRESSION_MIN_TRIGRAM_SIGNAL = 0.012
PROGRESSION_MIN_SEQUENCE_SIGNAL = 0.085
EVALUATION_REMARK_MIN_CHARS = 4
CONTENT_V2_EVALUATION_REMARK_MAX_CHARS = 48
EVALUATION_REMARK_FIXED_CRITERIA = frozenset({"attendance", "compliance", "habits"})
EVALUATION_REMARK_CONTENT_CRITERIA = frozenset(
    {"participation", "discussion", "homework", "practice", "presentation", "improvement"}
)
PROGRESSION_STOPWORDS = (
    "完成",
    "任务",
    "学习",
    "记录",
    "成果",
    "学生",
    "本课",
    "下一课",
    "进行",
    "相关",
    "能够",
    "依据",
    "形成",
    "方案",
)
ACTION_MARKERS = (
    "分析",
    "设计",
    "编写",
    "执行",
    "核对",
    "整理",
    "判断",
    "评估",
    "操作",
    "测量",
    "制定",
    "调试",
    "测试",
    "配置",
    "验证",
    "提交",
    "复盘",
    "改进",
    "实现",
    "部署",
    "查询",
    "维护",
    "训练",
    "演示",
    "检查",
    "核验",
    "编排",
)
REFERENCE_SPECIFIC_PATTERN = re.compile(
    r"(?:isbn\s*[-:]?\s*[0-9x-]+|gb\s*[/-]?\s*t|标准编号|文件编号|出版社|作者|"
    r"(?:19|20)\d{2}\s*年?|第\s*[一二三四五六七八九十百0-9]+\s*版|版次)",
    re.IGNORECASE,
)
REFERENCE_EVIDENCE_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
REFERENCE_EVIDENCE_LOCATOR_PATTERN = re.compile(
    r"(?:官方|政府|教育部|国家卫生健康|行业协会).*(?:官网|章节|条款|第[一二三四五六七八九十百0-9]+[章节条]|页|文号|检索|路径)",
)

BOILERPLATE_PATTERNS = (
    "已具备相关课程基础",
    "理论知识向任务迁移",
    "任务驱动、教师示范、分组实训、过程评价",
    "培养规范操作、职业责任和质量意识",
    "项目教学法、任务驱动法、演示法",
    "提供模板清单、分步演示",
    "多数学生能按要求完成",
    "学生参与度较高",
    "后续增加优秀成果样例",
    "标准机房、多媒体设备、网络环境",
    "课程PPT、微课视频、任务单、评分表和成果模板",
)
REPEATED_SENTENCE_ALLOWLIST = frozenset({"线上+线下", "课堂小结", "项目实训"})
NON_IT_CONTAMINATION_TERMS = (
    "软件技术",
    "标准机房",
    "脚本",
    "截图工具",
    "代码编辑器",
    "数据安全",
)


class ContentQualityError(ValueError):
    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


def _normalize(value: Any) -> str:
    value = unicodedata.normalize("NFKC", str(value))
    value = re.sub(r"(?:^|\n)\s*\d+[.)、]\s*", "\n", value)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_item(value: Any) -> str:
    """Normalize one list item without allowing punctuation or numbering to hide reuse."""

    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = re.sub(r"(?:^|\n)\s*\d+[.)、]\s*", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return "".join(char.casefold() for char in normalized if not unicodedata.category(char).startswith("P"))


def _meaningful_length(value: Any) -> int:
    return len(re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).strip())


def _item_values(lesson: dict[str, Any]) -> dict[str, list[str]]:
    """Expose list items individually so short repeated items cannot hide in a joined field."""

    result: dict[str, list[str]] = {
        "student_analysis.base": list(lesson["student_analysis"]["base"]),
        "student_analysis.problems": list(lesson["student_analysis"]["problems"]),
        "student_analysis.strategies": list(lesson["student_analysis"]["strategies"]),
        "teaching_content": list(lesson["teaching_content"]),
        "goals.knowledge": list(lesson["goals"]["knowledge"]),
        "goals.ability": list(lesson["goals"]["ability"]),
        "goals.quality": list(lesson["goals"]["quality"]),
        "key_point.content": list(lesson["key_point"]["content"]),
        "key_point.strategy": list(lesson["key_point"]["strategy"]),
        "difficult_point.content": list(lesson["difficult_point"]["content"]),
        "difficult_point.strategy": list(lesson["difficult_point"]["strategy"]),
        "teaching_methods": list(lesson["teaching_methods"]),
        "resources": list(lesson["resources"]),
        "references": [reference["text"] for reference in lesson["references"]],
    }
    for stage in lesson["implementation"]:
        stage_id = str(stage["id"])
        for field_name in ("content", "teacher_actions", "student_actions"):
            result[f"implementation.{stage_id}.{field_name}"] = list(stage[field_name])
        result[f"implementation.{stage_id}.objective"] = [stage["objective"]]
    for field_name in ("prior_learning", "deliverable", "next_bridge"):
        result[f"progression.{field_name}"] = [lesson["progression"][field_name]]
    for field_name in ("summary", "innovation", "improvement"):
        result[f"reflection.{field_name}"] = [lesson["reflection"][field_name]]
    for criterion in EVALUATION_CRITERIA:
        criterion_id = criterion[0]
        result[f"evaluation.remarks.{criterion_id}"] = [lesson["evaluation"]["remarks"][criterion_id]]
    return result


def _course_terms(lessons: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for lesson in lessons:
        for value in (
            lesson.get("unit", ""),
            lesson.get("task", ""),
            lesson.get("progression", {}).get("deliverable", ""),
        ):
            normalized = _normalize_item(value)
            if len(normalized) >= 2:
                terms.add(normalized)
    return terms


def _is_allowed_repeated_item(field: str, value: str, course_terms: set[str]) -> bool:
    """Allow metadata-like reuse while keeping substantive teaching prose strict."""

    normalized = _normalize_item(value)
    if not normalized:
        return True
    if field == "teaching_methods":
        return True
    if field == "references":
        return True
    if field == "resources":
        return True
    if field.startswith("evaluation.remarks."):
        criterion = field.rsplit(".", 1)[-1]
        return criterion in EVALUATION_REMARK_FIXED_CRITERIA
    if len(normalized) <= 8 and any(normalized in term or term in normalized for term in course_terms):
        return True
    return False


def _sentences(value: Any) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value))
    parts = re.split(r"[。！？!?；;\n]+", text)
    result = []
    for part in parts:
        normalized = _normalize(part)
        if len(normalized) >= MIN_SENTENCE_LENGTH and normalized not in REPEATED_SENTENCE_ALLOWLIST:
            result.append(normalized)
    return result


def _joined(values: Any) -> str:
    if isinstance(values, list):
        return "\n".join(_normalize(item) for item in values)
    if isinstance(values, dict):
        return "\n".join(_joined(values[key]) for key in sorted(values))
    return _normalize(values)


def _lesson_id(lesson: dict[str, Any], index: int) -> str:
    return str(lesson.get("lesson_id") or f"lesson-{index}")


def _field_groups(lesson: dict[str, Any]) -> dict[str, str]:
    analysis = lesson["student_analysis"]
    goals = lesson["goals"]
    progression = lesson["progression"]
    return {
        "student_analysis.base": _joined(analysis["base"]),
        "student_analysis.problems": _joined(analysis["problems"]),
        "student_analysis.strategies": _joined(analysis["strategies"]),
        "teaching_content": _joined(lesson["teaching_content"]),
        "goals.knowledge": _joined(goals["knowledge"]),
        "goals.ability": _joined(goals["ability"]),
        "goals.quality": _joined(goals["quality"]),
        "key_point.content": _joined(lesson["key_point"]["content"]),
        "key_point.strategy": _joined(lesson["key_point"]["strategy"]),
        "difficult_point.content": _joined(lesson["difficult_point"]["content"]),
        "difficult_point.strategy": _joined(lesson["difficult_point"]["strategy"]),
        "teaching_methods": _joined(lesson["teaching_methods"]),
        "progression.prior_learning": _normalize(progression["prior_learning"]),
        "progression.deliverable": _normalize(progression["deliverable"]),
        "progression.next_bridge": _normalize(progression["next_bridge"]),
        "reflection.summary": _normalize(lesson["reflection"]["summary"]),
        "reflection.innovation": _normalize(lesson["reflection"]["innovation"]),
        "reflection.improvement": _normalize(lesson["reflection"]["improvement"]),
        **{
            f"evaluation.remarks.{criterion_id}": _normalize(lesson["evaluation"]["remarks"][criterion_id])
            for criterion_id in EVALUATION_CRITERION_IDS
        },
    }


def _lesson_narrative(lesson: dict[str, Any]) -> str:
    values = lesson_content_field_values(lesson)
    values["progression"] = _joined(
        {
            key: lesson["progression"][key]
            for key in ("prior_learning", "capability_stage", "deliverable", "next_bridge")
        }
    )
    values["reflection"] = _joined(lesson["reflection"])
    values["evaluation_remarks"] = _joined(lesson["evaluation"]["remarks"])
    values["implementation"] = "\n".join(
        "\n".join(
            _joined(stage[field_name])
            for field_name in IMPLEMENTATION_STAGE_FIELDS
        )
        for stage in lesson["implementation"]
    )
    return "\n".join(_normalize(values[key]) for key in sorted(values))


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    compact = re.sub(r"\s+", "", _normalize(value))
    return {compact[index : index + size] for index in range(max(0, len(compact) - size + 1))}


def _similarity(left: str, right: str) -> tuple[float, float]:
    sequence = SequenceMatcher(None, left, right).ratio()
    left_grams = _character_ngrams(left)
    right_grams = _character_ngrams(right)
    union = left_grams | right_grams
    jaccard = len(left_grams & right_grams) / len(union) if union else 1.0
    return sequence, jaccard


def _top_fragments(left: str, right: str) -> list[str]:
    matcher = SequenceMatcher(None, left, right)
    fragments = []
    for block in matcher.get_matching_blocks():
        fragment = _normalize(left[block.a : block.a + block.size])
        if len(fragment) >= MIN_SENTENCE_LENGTH:
            fragments.append(fragment)
    return sorted(set(fragments), key=lambda value: (-len(value), value))[:3]


def _entity_fragments(lesson: dict[str, Any]) -> set[str]:
    """Collect only lesson-specific noun-like phrases for structural masking."""

    candidates: list[str] = [
        str(lesson.get("unit", "")),
        str(lesson.get("task", "")),
        str(lesson.get("progression", {}).get("deliverable", "")),
        str(lesson.get("progression", {}).get("next_bridge", "")),
    ]
    candidates.extend(str(value) for value in lesson.get("resources", []))
    fragments: set[str] = set()
    for candidate in candidates:
        normalized = _normalize(candidate)
        for fragment in re.split(
            r"[，,、。；;：:（）()\[\]【】/\\\s]+|提交|完成|形成|编写|整理|输出|建立|制作|记录|依据|针对|使用|进入|并|以及|和|与|将|按",
            normalized,
        ):
            fragment = _normalize(fragment)
            if _meaningful_length(fragment) >= 3 and fragment not in PROGRESSION_STOPWORDS:
                fragments.add(fragment)
    return fragments


def _mask_entities(value: Any, entities: set[str]) -> str:
    masked = _normalize(value)
    for entity in sorted(entities, key=lambda item: (-_meaningful_length(item), item)):
        if _meaningful_length(entity) >= 3:
            masked = masked.replace(entity, "<ENTITY>")
    masked = re.sub(r"\d+(?:\.\d+)?", "<NUMBER>", masked)
    return masked


def _similarity_score(sequence: float, jaccard: float) -> float:
    """Combine order and overlap evidence without letting one weak metric win alone."""

    return 0.55 * sequence + 0.45 * jaccard


def _structural_record(
    *,
    left_id: str,
    right_id: str,
    field: str,
    left_text: str,
    right_text: str,
    raw_sequence: float,
    raw_jaccard: float,
    masked_left: str,
    masked_right: str,
    masked_sequence: float,
    masked_jaccard: float,
    adjacent: bool,
    indices: tuple[int, int] | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "lessons": [left_id, right_id],
        "field": field,
        "score": round(_similarity_score(masked_sequence, masked_jaccard), 4),
        "raw_score": round(_similarity_score(raw_sequence, raw_jaccard), 4),
        "masked_score": round(_similarity_score(masked_sequence, masked_jaccard), 4),
        "raw_sequence_matcher": round(raw_sequence, 4),
        "raw_character_3gram_jaccard": round(raw_jaccard, 4),
        "masked_sequence_matcher": round(masked_sequence, 4),
        "masked_character_3gram_jaccard": round(masked_jaccard, 4),
        "masked_fingerprint": _normalize(masked_left)[:120],
        "top_fragments": _top_fragments(masked_left, masked_right),
        "top_repeated_fragments": _top_fragments(masked_left, masked_right),
        "adjacent": adjacent,
    }
    if indices is not None:
        record["item_indices"] = list(indices)
    if stage is not None:
        record["stage"] = stage
    return record


def _structural_item_pairs(
    values: dict[str, dict[str, list[str]]],
    lesson_ids: list[str],
    lessons_by_id: dict[str, dict[str, Any]],
    *,
    threshold: float,
    adjacent_threshold: float,
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    positions = {lesson_id: index for index, lesson_id in enumerate(lesson_ids)}
    for field, per_lesson in values.items():
        for left_index, left_id in enumerate(lesson_ids):
            for right_id in lesson_ids[left_index + 1 :]:
                adjacent = _is_adjacent(left_index, positions[right_id])
                effective_threshold = adjacent_threshold if adjacent else threshold
                entities = _entity_fragments(lessons_by_id[left_id]) | _entity_fragments(lessons_by_id[right_id])
                for left_item_index, left_text in enumerate(per_lesson.get(left_id, []), 1):
                    for right_item_index, right_text in enumerate(per_lesson.get(right_id, []), 1):
                        short_structural_field = field.startswith(STRUCTURAL_SHORT_FIELDS)
                        minimum_length = 8 if short_structural_field else STRUCTURAL_MIN_ITEM_LENGTH
                        if min(_meaningful_length(left_text), _meaningful_length(right_text)) < minimum_length:
                            continue
                        if not short_structural_field and not any(marker in f"{left_text}{right_text}" for marker in ACTION_MARKERS):
                            continue
                        masked_left = _mask_entities(left_text, entities)
                        masked_right = _mask_entities(right_text, entities)
                        raw_sequence, raw_jaccard = _similarity(_normalize(left_text), _normalize(right_text))
                        masked_sequence, masked_jaccard = _similarity(masked_left, masked_right)
                        masked_score = _similarity_score(masked_sequence, masked_jaccard)
                        if masked_score < effective_threshold:
                            continue
                        pairs.append(
                            _structural_record(
                                left_id=left_id,
                                right_id=right_id,
                                field=field,
                                left_text=left_text,
                                right_text=right_text,
                                raw_sequence=raw_sequence,
                                raw_jaccard=raw_jaccard,
                                masked_left=masked_left,
                                masked_right=masked_right,
                                masked_sequence=masked_sequence,
                                masked_jaccard=masked_jaccard,
                                adjacent=adjacent,
                                indices=(left_item_index, right_item_index),
                                stage=field.split(".")[1] if field.startswith("implementation.") else None,
                            )
                        )
    return sorted(
        pairs,
        key=lambda item: (-item["masked_score"], item["field"], item["lessons"], item.get("item_indices", [])),
    )


def _record_duplicate_groups(values: dict[str, dict[str, str]], minimum: int = 2) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for field, per_lesson in values.items():
        by_value: dict[str, list[str]] = {}
        for lesson_id, value in per_lesson.items():
            normalized = _normalize(value)
            if normalized:
                by_value.setdefault(normalized, []).append(lesson_id)
        for value, lesson_ids in by_value.items():
            if len(lesson_ids) >= minimum:
                groups.append({"field": field, "lessons": sorted(lesson_ids), "text": value})
    return sorted(groups, key=lambda item: (item["field"], item["lessons"]))


def _all_content_strings(lesson: dict[str, Any]) -> dict[str, list[str]]:
    values = lesson_content_field_values(lesson)
    result = {name: [values[name]] for name in CONTENT_FIELD_NAMES}
    result["progression"] = [_joined(lesson["progression"])]
    result["reflection"] = format_reflection(lesson["reflection"])
    result.update(
        {
            f"evaluation.remarks.{criterion_id}": [lesson["evaluation"]["remarks"][criterion_id]]
            for criterion_id in EVALUATION_CRITERION_IDS
        }
    )
    for stage in lesson["implementation"]:
        stage_id = str(stage["id"])
        for field_name in IMPLEMENTATION_STAGE_FIELDS:
            result[f"implementation.{stage_id}.{field_name}"] = [_joined(stage[field_name])]
    return result


def _completeness_report(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Check meaningful text after schema validation, including whitespace-only values."""

    counts: dict[str, dict[str, int]] = {}
    errors: list[str] = []

    def check_text(lesson_id: str, field: str, value: Any, minimum: int = 3) -> None:
        if _meaningful_length(value) < minimum:
            errors.append(f"{lesson_id}.{field} does not contain meaningful content")

    for field_name in ("course_name", "major", "audience"):
        if _meaningful_length(data.get(field_name, "")) < 1:
            errors.append(f"course.{field_name} does not contain meaningful content")
    for index, lesson in enumerate(data.get("lessons", []), 1):
        lesson_id = _lesson_id(lesson, index)
        check_text(lesson_id, "unit", lesson.get("unit", ""))
        check_text(lesson_id, "task", lesson.get("task", ""))
        analysis = lesson["student_analysis"]
        goals = lesson["goals"]
        counts[lesson_id] = {
            "student_base": len(analysis["base"]),
            "student_problems": len(analysis["problems"]),
            "student_strategies": len(analysis["strategies"]),
            "teaching_content": len(lesson["teaching_content"]),
            "knowledge_goals": len(goals["knowledge"]),
            "ability_goals": len(goals["ability"]),
            "quality_goals": len(goals["quality"]),
            "teaching_methods": len(lesson["teaching_methods"]),
            "resources": len(lesson["resources"]),
            "references": len(lesson["references"]),
            "implementation_stages": len(lesson["implementation"]),
        }
        for field_name in ("base", "problems", "strategies"):
            for item_index, value in enumerate(analysis[field_name], 1):
                check_text(lesson_id, f"student_analysis.{field_name}[{item_index}]", value)
        for field_name in ("teaching_content", "teaching_methods", "resources"):
            for item_index, value in enumerate(lesson[field_name], 1):
                check_text(lesson_id, f"{field_name}[{item_index}]", value)
        for item_index, reference in enumerate(lesson["references"], 1):
            check_text(lesson_id, f"references[{item_index}]", reference["text"])
        for goal_name in ("knowledge", "ability", "quality"):
            for item_index, value in enumerate(goals[goal_name], 1):
                check_text(lesson_id, f"goals.{goal_name}[{item_index}]", value)
        for point_name in ("key_point", "difficult_point"):
            for list_name in ("content", "strategy"):
                for item_index, value in enumerate(lesson[point_name][list_name], 1):
                    check_text(lesson_id, f"{point_name}.{list_name}[{item_index}]", value)
        for field_name in ("prior_learning", "deliverable", "next_bridge"):
            check_text(lesson_id, f"progression.{field_name}", lesson["progression"][field_name], 6)
        check_text(lesson_id, "progression.capability_stage", lesson["progression"].get("capability_stage", ""), 1)
        for stage in lesson["implementation"]:
            stage_id = str(stage["id"])
            check_text(lesson_id, f"implementation.{stage_id}.label", stage.get("label", ""), 1)
            check_text(lesson_id, f"implementation.{stage_id}.modality", stage.get("modality", ""), 1)
            for field_name in ("content", "teacher_actions", "student_actions"):
                for item_index, value in enumerate(stage[field_name], 1):
                    check_text(lesson_id, f"implementation.{stage_id}.{field_name}[{item_index}]", value)
            check_text(lesson_id, f"implementation.{stage_id}.objective", stage["objective"], 6)
        for field_name in ("summary", "innovation", "improvement"):
            check_text(lesson_id, f"reflection.{field_name}", lesson["reflection"][field_name], 12)
        for criterion_id in EVALUATION_CRITERION_IDS:
            check_text(
                lesson_id,
                f"evaluation.remarks.{criterion_id}",
                lesson["evaluation"]["remarks"].get(criterion_id, ""),
                EVALUATION_REMARK_MIN_CHARS,
            )

    return {"lessons": counts, "meaningful_errors": errors}, errors


def _density_report(data: dict[str, Any], manifest: dict[str, Any] | None) -> tuple[list[dict[str, Any]], int]:
    errors: list[dict[str, Any]] = []
    total_chars = 0
    fields = manifest.get("fields", {}) if manifest else {}
    for index, lesson in enumerate(data["lessons"], 1):
        lesson_id = _lesson_id(lesson, index)
        title = format_title(index, data, lesson)
        title_spec = fields.get("title", {})
        title_limit = title_spec.get("max_chars")
        if title_limit is not None and len(title) > int(title_limit):
            errors.append({"lesson": lesson_id, "field": "title", "actual_chars": len(title), "limit": int(title_limit)})
        values = lesson_content_field_values(lesson)
        for field_name, value in values.items():
            total_chars += len(value)
            spec = fields.get(field_name, {})
            max_chars = spec.get("max_chars")
            max_paragraphs = spec.get("max_paragraphs")
            if max_chars is not None and len(value) > int(max_chars):
                errors.append({"lesson": lesson_id, "field": field_name, "actual_chars": len(value), "limit": int(max_chars)})
            paragraphs = len(value.splitlines()) or 1
            if max_paragraphs is not None and paragraphs > int(max_paragraphs):
                errors.append({"lesson": lesson_id, "field": field_name, "actual_paragraphs": paragraphs, "limit": int(max_paragraphs)})
        implementation_spec = fields.get("implementation", {})
        for stage in lesson["implementation"]:
            formatted = format_implementation_stage(stage)
            for cell_index, value in formatted.items():
                total_chars += len(value)
                max_chars = implementation_spec.get("max_chars")
                max_paragraphs = implementation_spec.get("max_paragraphs")
                if max_chars is not None and len(value) > int(max_chars):
                    errors.append({"lesson": lesson_id, "field": f"implementation.{stage['id']}.{cell_index}", "actual_chars": len(value), "limit": int(max_chars)})
                paragraphs = len(value.splitlines()) or 1
                if max_paragraphs is not None and paragraphs > int(max_paragraphs):
                    errors.append({"lesson": lesson_id, "field": f"implementation.{stage['id']}.{cell_index}", "actual_paragraphs": paragraphs, "limit": int(max_paragraphs)})
        reflection_spec = fields.get("reflection", {})
        for name, value in zip(("summary", "innovation", "improvement"), format_reflection(lesson["reflection"])):
            total_chars += len(value)
            max_chars = reflection_spec.get("max_chars")
            max_paragraphs = reflection_spec.get("max_paragraphs")
            if max_chars is not None and len(value) > int(max_chars):
                errors.append({"lesson": lesson_id, "field": f"reflection.{name}", "actual_chars": len(value), "limit": int(max_chars)})
            paragraphs = len(value.splitlines()) or 1
            if max_paragraphs is not None and paragraphs > int(max_paragraphs):
                errors.append({"lesson": lesson_id, "field": f"reflection.{name}", "actual_paragraphs": paragraphs, "limit": int(max_paragraphs)})
        evaluation_spec = fields.get("evaluation", {})
        manifest_limit = evaluation_spec.get("max_remark_chars")
        remark_limit = CONTENT_V2_EVALUATION_REMARK_MAX_CHARS
        if manifest_limit is not None:
            remark_limit = min(remark_limit, int(manifest_limit))
        for criterion_id in EVALUATION_CRITERION_IDS:
            value = _normalize(lesson["evaluation"]["remarks"][criterion_id])
            total_chars += len(value)
            if _meaningful_length(value) > remark_limit:
                errors.append(
                    {
                        "lesson": lesson_id,
                        "field": f"evaluation.remarks.{criterion_id}",
                        "actual_chars": _meaningful_length(value),
                        "limit": remark_limit,
                    }
                )
    return errors, total_chars


def _is_adjacent(left_index: int, right_index: int) -> bool:
    return right_index == left_index + 1


def _similarity_record(
    *,
    left_id: str,
    right_id: str,
    left_text: str,
    right_text: str,
    sequence: float,
    jaccard: float,
    field: str | None = None,
    stage: str | None = None,
    adjacent: bool = False,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "lessons": [left_id, right_id],
        "score": round(max(sequence, jaccard), 4),
        "sequence_matcher": round(sequence, 4),
        "character_3gram_jaccard": round(jaccard, 4),
        "top_fragments": _top_fragments(left_text, right_text),
        "top_repeated_fragments": _top_fragments(left_text, right_text),
        "adjacent": adjacent,
    }
    if field is not None:
        record["field"] = field
    if stage is not None:
        record["stage"] = stage
    return record


def _similarity_exceeds(sequence: float, jaccard: float, threshold: float) -> bool:
    """Use both order-sensitive and character-overlap evidence for paraphrase detection."""

    return sequence >= threshold or (jaccard >= threshold and sequence >= threshold - 0.12)


def _adjacent_exact_duplicates(
    values: dict[str, dict[str, str]],
    lesson_ids: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for field, per_lesson in values.items():
        for index in range(len(lesson_ids) - 1):
            left_id, right_id = lesson_ids[index : index + 2]
            left_text = _normalize(per_lesson.get(left_id, ""))
            right_text = _normalize(per_lesson.get(right_id, ""))
            if left_text and left_text == right_text:
                records.append(
                    {
                        "lessons": [left_id, right_id],
                        "field": field,
                        "score": 1.0,
                        "top_fragments": [left_text[:120]],
                        "top_repeated_fragments": [left_text[:120]],
                    }
                )
    return sorted(records, key=lambda item: (item["lessons"], item.get("field", "")))


def _item_duplicate_reports(
    values: dict[str, dict[str, list[str]]],
    lesson_ids: list[str],
    course_terms: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return all item duplicates, adjacent violations, and non-adjacent violations."""

    all_duplicates: list[dict[str, Any]] = []
    adjacent_violations: list[dict[str, Any]] = []
    frequency_violations: list[dict[str, Any]] = []
    positions = {lesson_id: index for index, lesson_id in enumerate(lesson_ids)}
    for field, per_lesson in values.items():
        occurrences: dict[str, list[tuple[str, int, str]]] = {}
        for lesson_id in lesson_ids:
            for item_index, text in enumerate(per_lesson.get(lesson_id, []), 1):
                normalized = _normalize_item(text)
                if normalized:
                    occurrences.setdefault(normalized, []).append((lesson_id, item_index, _normalize(text)))
        for normalized, entries in occurrences.items():
            unique_lesson_ids = sorted({entry[0] for entry in entries}, key=lambda item: positions[item])
            if len(unique_lesson_ids) < 2:
                continue
            record = {
                "field": field,
                "lessons": unique_lesson_ids,
                "count": len(unique_lesson_ids),
                "text": entries[0][2],
                "normalized": normalized,
                "items": [
                    {"lesson": lesson_id, "index": item_index}
                    for lesson_id, item_index, _text in entries
                ],
                "allowed": _is_allowed_repeated_item(field, entries[0][2], course_terms),
            }
            all_duplicates.append(record)
            if record["allowed"]:
                continue
            adjacent = any(
                positions[right] == positions[left] + 1
                for left, right in zip(unique_lesson_ids, unique_lesson_ids[1:])
            )
            if adjacent:
                adjacent_violations.append(record)
            if len(unique_lesson_ids) >= 3:
                frequency_violations.append(record)
    sort_key = lambda item: (item["field"], item["lessons"], item["normalized"])
    return (
        sorted(all_duplicates, key=sort_key),
        sorted(adjacent_violations, key=sort_key),
        sorted(frequency_violations, key=sort_key),
    )


def _pairwise_similarity(
    values: dict[str, dict[str, str]],
    lesson_ids: list[str],
    *,
    threshold: float,
    adjacent_threshold: float,
    implementation: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs: list[dict[str, Any]] = []
    adjacent_pairs: list[dict[str, Any]] = []
    positions = {lesson_id: index for index, lesson_id in enumerate(lesson_ids)}
    for field, per_lesson in values.items():
        for left_index, left_id in enumerate(lesson_ids):
            for right_id in lesson_ids[left_index + 1 :]:
                left_text, right_text = per_lesson.get(left_id, ""), per_lesson.get(right_id, "")
                if min(len(left_text), len(right_text)) < 30:
                    continue
                adjacent = _is_adjacent(positions[left_id], positions[right_id])
                effective_threshold = adjacent_threshold if adjacent else threshold
                sequence, jaccard = _similarity(left_text, right_text)
                if not _similarity_exceeds(sequence, jaccard, effective_threshold):
                    continue
                stage = field.split(".", 1)[0] if implementation else None
                record = _similarity_record(
                    left_id=left_id,
                    right_id=right_id,
                    left_text=left_text,
                    right_text=right_text,
                    sequence=sequence,
                    jaccard=jaccard,
                    field=None if implementation else field,
                    stage=stage,
                    adjacent=adjacent,
                )
                pairs.append(record)
                if adjacent:
                    adjacent_pairs.append(record)
    pairs.sort(key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"]))
    adjacent_pairs.sort(key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"]))
    return pairs, adjacent_pairs


def _progression_signal_text(value: Any) -> str:
    text = _joined(value) if isinstance(value, (list, tuple, dict)) else _normalize(value)
    for stopword in PROGRESSION_STOPWORDS:
        text = text.replace(stopword, "")
    return re.sub(r"\s+", "", text)


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _progression_gate(upstream: Any, downstream: Any, threshold: float) -> dict[str, Any]:
    """Evaluate one directional progression claim with independent evidence."""

    upstream = _progression_signal_text(upstream)
    downstream = _progression_signal_text(downstream)
    sequence, _ = _similarity(upstream, downstream)
    bigrams_left = _character_ngrams(upstream, 2)
    bigrams_right = _character_ngrams(downstream, 2)
    trigrams_left = _character_ngrams(upstream, 3)
    trigrams_right = _character_ngrams(downstream, 3)
    bigram_jaccard = _jaccard(bigrams_left, bigrams_right)
    trigram_jaccard = _jaccard(trigrams_left, trigrams_right)
    weighted = 0.20 * sequence + 0.45 * bigram_jaccard + 0.35 * trigram_jaccard
    signal_count = sum(
        (
            bigram_jaccard >= PROGRESSION_MIN_BIGRAM_SIGNAL,
            trigram_jaccard >= PROGRESSION_MIN_TRIGRAM_SIGNAL,
            sequence >= PROGRESSION_MIN_SEQUENCE_SIGNAL,
        )
    )
    overlap = sorted(bigrams_left & bigrams_right, key=lambda value: (-len(value), value))[:5]
    return {
        "score": weighted,
        "sequence_matcher": sequence,
        "character_2gram_jaccard": bigram_jaccard,
        "character_3gram_jaccard": trigram_jaccard,
        "signal_count": signal_count,
        "top_overlap": overlap,
        "status": "passed" if weighted >= threshold and signal_count >= 2 else "failed",
    }


def _progression_gates(previous: dict[str, Any], current: dict[str, Any], threshold: float) -> dict[str, Any]:
    """Keep artifact inheritance and the next-step bridge as separate gates."""

    previous_progression = previous["progression"]
    current_progression = current["progression"]
    artifact_inheritance = _progression_gate(
        [previous_progression["deliverable"], previous.get("task", "")],
        current_progression["prior_learning"],
        threshold,
    )
    forward_transition = _progression_gate(
        previous_progression["next_bridge"],
        [current.get("task", ""), *current.get("teaching_content", []), current_progression["deliverable"]],
        threshold,
    )
    return {
        "artifact_inheritance": artifact_inheritance,
        "forward_transition": forward_transition,
        "status": (
            "passed"
            if artifact_inheritance["status"] == "passed" and forward_transition["status"] == "passed"
            else "failed"
        ),
    }


PROGRESSION_GATE_CALIBRATION_CORPUS = (
    (
        "false_inheritance",
        {
            "task": "完成需求分析",
            "progression": {
                "deliverable": "数据库需求分析报告",
                "next_bridge": "根据表结构完成SQL查询",
            },
        },
        {
            "task": "完成SQL查询设计",
            "teaching_content": ["依据表结构编写查询语句", "验证查询结果"],
            "progression": {
                "prior_learning": "承接护理实训基础",
                "deliverable": "SQL查询脚本和结果记录",
            },
        },
        "failed",
        "passed",
        "failed",
    ),
    (
        "false_bridge",
        {
            "task": "完成关系模式设计",
            "progression": {
                "deliverable": "E-R图",
                "next_bridge": "根据表结构完成SQL查询",
            },
        },
        {
            "task": "设计护理床整理流程",
            "teaching_content": ["整理床单位", "检查护理操作规范"],
            "progression": {
                "prior_learning": "承接E-R图中的实体及联系",
                "deliverable": "护理床整理记录",
            },
        },
        "passed",
        "failed",
        "failed",
    ),
    (
        "connected",
        {
            "task": "完成需求分析",
            "progression": {
                "deliverable": "E-R图",
                "next_bridge": "将实体关系转换为关系表",
            },
        },
        {
            "task": "完成关系模式设计",
            "teaching_content": ["主键、外键与关系表映射", "依据E-R图确定字段"],
            "progression": {
                "prior_learning": "能解释上一课E-R图中的实体及联系",
                "deliverable": "关系模式设计表",
            },
        },
        "passed",
        "passed",
        "passed",
    ),
)


def progression_gate_calibration() -> list[dict[str, Any]]:
    calibrated: list[dict[str, Any]] = []
    for (
        label,
        previous,
        current,
        expected_artifact,
        expected_forward,
        expected_overall,
    ) in PROGRESSION_GATE_CALIBRATION_CORPUS:
        gates = _progression_gates(previous, current, PROGRESSION_DECLARED_BOUNDARY_THRESHOLD)
        actual = {
            "artifact_inheritance": gates["artifact_inheritance"]["status"],
            "forward_transition": gates["forward_transition"]["status"],
            "overall": gates["status"],
        }
        calibrated.append(
            {
                "case": label,
                "expected": {
                    "artifact_inheritance": expected_artifact,
                    "forward_transition": expected_forward,
                    "overall": expected_overall,
                },
                "actual": actual,
                "gates": gates,
            }
        )
    return calibrated


# This small, reviewable corpus calibrates the threshold classes.  The positive
# pairs share a concrete artifact or clinical action; the negative pairs only
# share generic teaching language and must not pass by one accidental n-gram.
PROGRESSION_CALIBRATION_CORPUS = (
    ("测试需求分析结果", "依据测试需求分析结果设计测试用例", "通过"),
    ("实体关系模型", "根据实体关系模型建立表结构", "通过"),
    ("表结构约束", "利用表结构约束编写SQL查询", "通过"),
    ("护理评估记录", "依据护理评估记录完成无菌操作准备", "通过"),
    ("生命体征监测", "结合生命体征监测开展异常护理判断", "通过"),
    ("数据库设计方案", "制定植物病害防治方案", "失败"),
    ("无菌护理流程", "开展索引优化操作", "失败"),
    ("会计凭证审核", "完成Java接口测试", "失败"),
)


def progression_calibration() -> list[dict[str, Any]]:
    calibrated: list[dict[str, Any]] = []
    for upstream, downstream, expected in PROGRESSION_CALIBRATION_CORPUS:
        signals = _progression_gate(upstream, downstream, PROGRESSION_DECLARED_BOUNDARY_THRESHOLD)
        calibrated.append(
            {
                "upstream": upstream,
                "downstream": downstream,
                "expected": expected,
                "signals": signals,
                "calibrated_status": (
                    "通过"
                    if signals["score"] >= PROGRESSION_DECLARED_BOUNDARY_THRESHOLD and signals["signal_count"] >= 2
                    else "失败"
                ),
            }
        )
    return calibrated


def _score_pattern(scores: list[float], errors: list[str]) -> dict[str, Any]:
    score_pattern: dict[str, Any] = {
        "values": scores,
        "all_same": len(scores) > 1 and len(set(scores)) == 1,
        "simple_cycle": False,
        "cycle_period": None,
        "arithmetic_progression": False,
        "arithmetic_step": None,
        "strict_monotonic": False,
        "range_valid": True,
    }
    for value in scores:
        if value < float(EVALUATION_SCORE_MIN) or value > float(EVALUATION_SCORE_MAX) or (value * 2) % 1:
            score_pattern["range_valid"] = False
            errors.append(f"evaluation score {value} is outside 85-96 half-point contract")
    for period in range(1, len(scores) // 2 + 1):
        repeated = all(scores[index] == scores[index % period] for index in range(period, len(scores)))
        complete_cycle = len(scores) >= 2 * period and repeated
        tail_length = len(scores) - period
        partial_tail_cycle = 2 <= tail_length < period and repeated
        if complete_cycle or partial_tail_cycle:
            score_pattern["simple_cycle"] = True
            score_pattern["cycle_period"] = period
            break
    if len(scores) >= 4:
        steps = [round(scores[index + 1] - scores[index], 6) for index in range(len(scores) - 1)]
        if steps and steps[0] != 0 and all(step == steps[0] for step in steps):
            score_pattern["arithmetic_progression"] = True
            score_pattern["arithmetic_step"] = steps[0]
    if score_pattern["all_same"]:
        errors.append("evaluation scores are identical across lessons")
    if score_pattern["simple_cycle"]:
        errors.append("evaluation scores use a simple repeating cycle")
    if score_pattern["arithmetic_progression"]:
        errors.append("evaluation scores use a mechanical arithmetic progression")
    if len(scores) >= 4:
        steps = [scores[index + 1] - scores[index] for index in range(len(scores) - 1)]
        if all(step > 0 for step in steps) or all(step < 0 for step in steps):
            score_pattern["strict_monotonic"] = True
            errors.append("evaluation scores use a strict monotonic sequence")
    return score_pattern


def _reference_provenance_report(lessons: list[dict[str, Any]], lesson_ids: list[str]) -> dict[str, Any]:
    by_lesson: dict[str, list[dict[str, Any]]] = {}
    missing_evidence: list[dict[str, Any]] = []
    invalid_generic: list[dict[str, Any]] = []
    invalid_verified_public: list[dict[str, Any]] = []
    for lesson_id, lesson in zip(lesson_ids, lessons):
        entries: list[dict[str, Any]] = []
        for index, reference in enumerate(lesson.get("references", []), 1):
            text = _normalize(reference.get("text", ""))
            source_kind = str(reference.get("source_kind", ""))
            evidence = reference.get("evidence")
            evidence_present = _meaningful_length(evidence or "") > 0
            entry = {
                "index": index,
                "source_kind": source_kind,
                "evidence_present": evidence_present,
            }
            entries.append(entry)
            if source_kind in {"provided", "verified_public"} and not evidence_present:
                missing_evidence.append(
                    {"lesson": lesson_id, "reference": index, "source_kind": source_kind}
                )
            if source_kind == "verified_public" and evidence_present:
                evidence_text = _normalize(evidence)
                if not (
                    REFERENCE_EVIDENCE_URL_PATTERN.search(evidence_text)
                    or REFERENCE_EVIDENCE_LOCATOR_PATTERN.search(evidence_text)
                ):
                    invalid_verified_public.append(
                        {"lesson": lesson_id, "reference": index}
                    )
            if source_kind == "generic" and (
                REFERENCE_SPECIFIC_PATTERN.search(text)
                or re.search(r"《[^》]{2,}》", text)
                or re.search(r"(?:isbn|gb\s*[/-]?\s*t|出版社|作者|标准编号|文件编号|版次)", text, re.IGNORECASE)
            ):
                invalid_generic.append({"lesson": lesson_id, "reference": index})
        by_lesson[lesson_id] = entries
    return {
        "by_lesson": by_lesson,
        "missing_evidence": missing_evidence,
        "invalid_generic": invalid_generic,
        "invalid_verified_public": invalid_verified_public,
    }


def assess_content_quality(data: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run deterministic course-level checks, including item and skeleton repetition."""

    lessons = data.get("lessons", [])
    lesson_ids = [_lesson_id(lesson, index) for index, lesson in enumerate(lessons, 1)]
    lessons_by_id = dict(zip(lesson_ids, lessons))
    errors: list[str] = []
    warnings: list[str] = []
    course_terms = _course_terms(lessons)

    duplicate_values: dict[str, dict[str, str]] = {}
    item_values: dict[str, dict[str, list[str]]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for field, value in _field_groups(lesson).items():
            duplicate_values.setdefault(field, {})[lesson_id] = value
        for field, values in _item_values(lesson).items():
            item_values.setdefault(field, {})[lesson_id] = values

    exact_duplicates = _record_duplicate_groups(duplicate_values)
    adjacent_exact_duplicates = _adjacent_exact_duplicates(duplicate_values, lesson_ids)
    item_duplicates, adjacent_item_duplicates, frequency_item_duplicates = _item_duplicate_reports(
        item_values,
        lesson_ids,
        course_terms,
    )

    def allowed(field: str, text: str) -> bool:
        return _is_allowed_repeated_item(field, text, course_terms)

    for item in exact_duplicates:
        if not allowed(item["field"], item["text"]):
            errors.append(f"exact duplicate {item['field']}: {','.join(item['lessons'])}")
    for item in adjacent_exact_duplicates:
        if not allowed(item["field"], item.get("text", "")):
            errors.append(f"adjacent exact duplicate {item['field']} {item['lessons']}")
    reported_item_errors: set[tuple[str, tuple[str, ...], str]] = set()
    for item in (*adjacent_item_duplicates, *frequency_item_duplicates):
        key = (item["field"], tuple(item["lessons"]), item["normalized"])
        if key in reported_item_errors:
            continue
        reported_item_errors.add(key)
        reason = "adjacent" if item in adjacent_item_duplicates else "frequency"
        errors.append(f"{reason} repeated item {item['field']}: {','.join(item['lessons'])}")

    implementation_values: dict[str, dict[str, str]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for stage in lesson.get("implementation", []):
            stage_id = str(stage.get("id", ""))
            formatted = format_implementation_stage(stage)
            for field_name, cell_index in zip(IMPLEMENTATION_STAGE_FIELDS, (1, 2, 3, 4)):
                implementation_values.setdefault(f"{stage_id}.{field_name}", {})[lesson_id] = formatted[cell_index]
    implementation_duplicates = _record_duplicate_groups(
        implementation_values,
        IMPLEMENTATION_DUPLICATE_LESSON_COUNT,
    )
    adjacent_implementation_exact_duplicates = _adjacent_exact_duplicates(implementation_values, lesson_ids)
    for record in adjacent_implementation_exact_duplicates:
        record["stage"] = record["field"].split(".", 1)[0]
    if implementation_duplicates:
        errors.extend(
            f"implementation duplicate {item['field']}: {','.join(item['lessons'])}"
            for item in implementation_duplicates
        )

    similarity_values = {
        field: values
        for field, values in duplicate_values.items()
        if field != "teaching_methods"
    }
    field_similarity_pairs, adjacent_field_similarity_pairs = _pairwise_similarity(
        similarity_values,
        lesson_ids,
        threshold=FIELD_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_FIELD_SIMILARITY_THRESHOLD,
    )
    for item in field_similarity_pairs:
        if not allowed(item["field"], duplicate_values[item["field"]][item["lessons"][0]]):
            errors.append(f"high field similarity {item['field']} {item['lessons']}: {item['score']}")

    implementation_similarity_pairs, adjacent_implementation_similarity_pairs = _pairwise_similarity(
        implementation_values,
        lesson_ids,
        threshold=IMPLEMENTATION_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_IMPLEMENTATION_SIMILARITY_THRESHOLD,
        implementation=True,
    )
    implementation_similarity_pairs = adjacent_implementation_exact_duplicates + implementation_similarity_pairs
    adjacent_implementation_similarity_pairs = (
        adjacent_implementation_exact_duplicates + adjacent_implementation_similarity_pairs
    )
    implementation_similarity_pairs.sort(
        key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"])
    )
    adjacent_implementation_similarity_pairs.sort(
        key=lambda item: (-item["score"], item.get("field", item.get("stage", "")), item["lessons"])
    )
    if implementation_similarity_pairs:
        errors.extend(
            f"high implementation similarity {item.get('stage', item.get('field'))} {item['lessons']}: {item['score']}"
            for item in implementation_similarity_pairs
        )

    remark_values = {
        field: values
        for field, values in duplicate_values.items()
        if field.startswith("evaluation.remarks.")
    }
    evaluation_remark_duplicates = [
        item for item in item_duplicates if item["field"].startswith("evaluation.remarks.")
    ]
    evaluation_remark_similarity, _adjacent_remark_similarity = _pairwise_similarity(
        remark_values,
        lesson_ids,
        threshold=0.82,
        adjacent_threshold=0.78,
    )
    for item in evaluation_remark_similarity:
        criterion = item["field"].rsplit(".", 1)[-1]
        if criterion in EVALUATION_REMARK_FIXED_CRITERIA:
            warnings.append(
                f"evaluation remark similarity is expected for {criterion}: {','.join(item['lessons'])}"
            )
        else:
            errors.append(f"high evaluation remark similarity {item['field']} {item['lessons']}: {item['score']}")
    for item in evaluation_remark_duplicates:
        criterion = item["field"].rsplit(".", 1)[-1]
        if criterion in EVALUATION_REMARK_FIXED_CRITERIA and item["count"] >= 4:
            warnings.append(f"evaluation remark {criterion} repeats across {item['count']} lessons")

    resource_values = {
        "resources": {
            lesson_id: _joined(lesson.get("resources", []))
            for lesson_id, lesson in zip(lesson_ids, lessons)
        }
    }
    resource_reuse = _record_duplicate_groups(resource_values)
    if len(lessons) >= 4 and resource_reuse and len(resource_reuse[0]["lessons"]) == len(lessons):
        warnings.append("all lessons reuse the same complete resources list")

    structural_pairs = _structural_item_pairs(
        {
            field: values
            for field, values in item_values.items()
            if not field.startswith("implementation.")
            and not field.startswith("progression.")
            and field != "resources"
        },
        lesson_ids,
        lessons_by_id,
        threshold=STRUCTURAL_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_STRUCTURAL_SIMILARITY_THRESHOLD,
    )
    implementation_structural_pairs = _structural_item_pairs(
        {
            field: values
            for field, values in item_values.items()
            if field.startswith("implementation.")
        },
        lesson_ids,
        lessons_by_id,
        threshold=IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
        adjacent_threshold=ADJACENT_IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
    )
    if structural_pairs:
        errors.extend(
            f"structural similarity {item['field']} {item['lessons']}: masked_score={item['masked_score']}"
            for item in structural_pairs
        )
    if implementation_structural_pairs:
        errors.extend(
            f"implementation structural similarity {item['stage']} {item['lessons']}: masked_score={item['masked_score']}"
            for item in implementation_structural_pairs
        )

    sentence_locations: dict[str, dict[str, set[str]]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for field, values in _all_content_strings(lesson).items():
            for value in values:
                for sentence in _sentences(value):
                    sentence_locations.setdefault(sentence, {}).setdefault(lesson_id, set()).add(field)
    repeated_sentences: list[dict[str, Any]] = []
    for sentence, locations in sentence_locations.items():
        ordered_locations = [lesson_id for lesson_id in lesson_ids if lesson_id in locations]
        adjacent = any(
            _is_adjacent(lesson_ids.index(left_id), lesson_ids.index(right_id))
            for left_id, right_id in zip(ordered_locations, ordered_locations[1:])
        )
        if len(locations) >= REPEATED_SENTENCE_LESSON_COUNT or adjacent:
            repeated_sentences.append(
                {
                    "sentence": sentence,
                    "lessons": ordered_locations,
                    "count": len(locations),
                    "fields": {lesson_id: sorted(locations[lesson_id]) for lesson_id in ordered_locations},
                    "adjacent": adjacent,
                    "score": 1.0,
                    "top_fragments": [sentence],
                }
            )
    repeated_sentences.sort(key=lambda item: (-item["count"], item["sentence"]))
    if repeated_sentences:
        errors.extend(f"repeated sentence across lessons: {item['sentence']}" for item in repeated_sentences)

    boilerplate_hits: list[dict[str, str]] = []
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for field, values in _all_content_strings(lesson).items():
            text = "\n".join(values)
            for pattern in BOILERPLATE_PATTERNS:
                if pattern in text:
                    boilerplate_hits.append({"lesson": lesson_id, "field": field, "fragment": pattern})
    boilerplate_hits.sort(key=lambda item: (item["lesson"], item["field"], item["fragment"]))
    if boilerplate_hits:
        errors.extend(
            f"legacy boilerplate in {item['lesson']}.{item['field']}: {item['fragment']}"
            for item in boilerplate_hits
        )

    narratives = {_lesson_id(lesson, index): _lesson_narrative(lesson) for index, lesson in enumerate(lessons, 1)}
    whole_lesson_similarity_pairs: list[dict[str, Any]] = []
    adjacent_similarity_pairs: list[dict[str, Any]] = []
    for left_index, left_id in enumerate(lesson_ids):
        for right_id in lesson_ids[left_index + 1 :]:
            left_text, right_text = narratives[left_id], narratives[right_id]
            if min(len(left_text), len(right_text)) < 30:
                continue
            adjacent = _is_adjacent(left_index, lesson_ids.index(right_id))
            threshold = ADJACENT_WHOLE_LESSON_SIMILARITY_THRESHOLD if adjacent else WHOLE_LESSON_SIMILARITY_THRESHOLD
            sequence, jaccard = _similarity(left_text, right_text)
            if _similarity_exceeds(sequence, jaccard, threshold):
                record = _similarity_record(
                    left_id=left_id,
                    right_id=right_id,
                    left_text=left_text,
                    right_text=right_text,
                    sequence=sequence,
                    jaccard=jaccard,
                    adjacent=adjacent,
                )
                whole_lesson_similarity_pairs.append(record)
                if adjacent:
                    adjacent_similarity_pairs.append(record)
    whole_lesson_similarity_pairs.sort(key=lambda item: (-item["score"], item["lessons"]))
    adjacent_similarity_pairs.sort(key=lambda item: (-item["score"], item["lessons"]))
    if whole_lesson_similarity_pairs:
        errors.extend(f"high whole-lesson similarity {item['lessons']}: {item['score']}" for item in whole_lesson_similarity_pairs)

    progression_stages = [str(lesson.get("progression", {}).get("capability_stage", "")) for lesson in lessons]
    declared_prior_links: list[dict[str, Any]] = []
    sequence_links: list[dict[str, Any]] = []
    prior_ids: set[str] = set()
    for index, lesson in enumerate(lessons):
        current_id = lesson_ids[index]
        progression_data = lesson.get("progression", {})
        declared_prior = progression_data.get("prior_lesson_id")
        if index == 0:
            if declared_prior is not None:
                errors.append("lessons[0].progression.prior_lesson_id must be null")
        elif declared_prior not in prior_ids:
            errors.append(f"{current_id}.progression.prior_lesson_id must reference an earlier lesson")
        elif declared_prior != current_id:
            prior_lesson = lessons_by_id[str(declared_prior)]
            same_unit = str(prior_lesson.get("unit", "")) == str(lesson.get("unit", ""))
            threshold = PROGRESSION_DECLARED_SAME_UNIT_THRESHOLD if same_unit else PROGRESSION_DECLARED_BOUNDARY_THRESHOLD
            gates = _progression_gates(prior_lesson, lesson, threshold)
            artifact = gates["artifact_inheritance"]
            forward = gates["forward_transition"]
            link = {
                "from": str(declared_prior),
                "to": current_id,
                "kind": "declared_prior",
                "score": round(min(artifact["score"], forward["score"]), 4),
                "sequence_matcher": round(min(artifact["sequence_matcher"], forward["sequence_matcher"]), 4),
                "character_2gram_jaccard": round(min(artifact["character_2gram_jaccard"], forward["character_2gram_jaccard"]), 4),
                "character_3gram_jaccard": round(min(artifact["character_3gram_jaccard"], forward["character_3gram_jaccard"]), 4),
                "signal_count": min(artifact["signal_count"], forward["signal_count"]),
                "threshold": threshold,
                "same_unit": same_unit,
                "status": gates["status"],
                "top_overlap": sorted(set(artifact["top_overlap"] + forward["top_overlap"]))[:5],
                "artifact_inheritance": artifact,
                "forward_transition": forward,
            }
            declared_prior_links.append(link)
            if link["status"] == "failed":
                errors.append(
                    f"progression declared prior gate failed {link['from']}->{link['to']}: "
                    f"score={link['score']} threshold={threshold}"
                )
        if index > 0:
            previous_id = lesson_ids[index - 1]
            previous = lessons_by_id[previous_id]
            same_unit = str(previous.get("unit", "")) == str(lesson.get("unit", ""))
            signal = _progression_gate(
                previous["progression"]["next_bridge"],
                [lesson.get("task", ""), *lesson.get("teaching_content", []), lesson["progression"]["deliverable"]],
                PROGRESSION_SEQUENCE_THRESHOLD,
            )
            status = "passed" if signal["status"] == "passed" else "review"
            hard_failure = status == "review" and declared_prior in {None, previous_id}
            link = {
                "from": previous_id,
                "to": current_id,
                "kind": "sequence",
                "score": round(signal["score"], 4),
                "sequence_matcher": round(signal["sequence_matcher"], 4),
                "character_2gram_jaccard": round(signal["character_2gram_jaccard"], 4),
                "character_3gram_jaccard": round(signal["character_3gram_jaccard"], 4),
                "signal_count": signal["signal_count"],
                "threshold": PROGRESSION_SEQUENCE_THRESHOLD,
                "same_unit": same_unit,
                "status": "failed" if hard_failure else status,
                "hard_failure": hard_failure,
                "top_overlap": signal["top_overlap"],
                "forward_transition": signal,
            }
            sequence_links.append(link)
            if hard_failure:
                errors.append(
                    f"progression sequence coherence failed {link['from']}->{link['to']}: "
                    f"score={link['score']} threshold={PROGRESSION_SEQUENCE_THRESHOLD}"
                )
        prior_ids.add(current_id)
    progression_variety = len(set(progression_stages)) > 1 if len(progression_stages) >= 4 else True
    if not progression_variety:
        errors.append("progression capability_stage is identical across all lessons")
    progression = {
        "status": "passed"
        if progression_variety
        and all(item["status"] == "passed" for item in declared_prior_links)
        and not any(item["hard_failure"] for item in sequence_links)
        else "failed",
        "lesson_ids": lesson_ids,
        "capability_stages": progression_stages,
        "distinct_capability_stages": sorted(set(progression_stages)),
        "stage_count": len(progression_stages),
        "valid_variety": progression_variety,
        "links": declared_prior_links or sequence_links,
        "declared_prior_links": declared_prior_links,
        "sequence_links": sequence_links,
        "thresholds": {
            "declared_same_unit": PROGRESSION_DECLARED_SAME_UNIT_THRESHOLD,
            "declared_project_boundary": PROGRESSION_DECLARED_BOUNDARY_THRESHOLD,
            "sequence": PROGRESSION_SEQUENCE_THRESHOLD,
            "minimum_signal_count": 2,
        },
    }

    scores: list[float] = []
    for lesson in lessons:
        try:
            scores.append(float(lesson["evaluation"]["score"]))
        except (KeyError, TypeError, ValueError):
            pass
    score_pattern = _score_pattern(scores, errors)

    completeness, completeness_errors = _completeness_report(data)
    errors.extend(completeness_errors)
    density_errors, meaningful_chars = _density_report(data, manifest)
    if density_errors:
        errors.extend(
            f"content density exceeds {item['field']} for {item['lesson']}: "
            f"actual_chars={item.get('actual_chars', '?')} limit={item.get('limit', '?')}"
            for item in density_errors
        )

    reference_provenance = _reference_provenance_report(lessons, lesson_ids)
    for item in reference_provenance["missing_evidence"]:
        errors.append(
            f"{item['lesson']}.references[{item['reference']}].{item['source_kind']} requires evidence"
        )
    for item in reference_provenance["invalid_generic"]:
        errors.append(f"{item['lesson']}.references[{item['reference']}] generic source is too specific")
    for item in reference_provenance["invalid_verified_public"]:
        errors.append(
            f"{item['lesson']}.references[{item['reference']}] verified_public evidence is not locatable"
        )

    coverage = {
        "lesson_count": len(lessons),
        "implementation_stages": {lesson_id: len(lesson.get("implementation", [])) for lesson_id, lesson in zip(lesson_ids, lessons)},
        "meaningful_characters": meaningful_chars,
        "content_fields": len(CONTENT_FIELD_NAMES),
        "evaluation_criteria": len(EVALUATION_CRITERIA),
        "evaluation_remark_contract_limit": CONTENT_V2_EVALUATION_REMARK_MAX_CHARS,
        "in_class_stage_ids": sorted(IN_CLASS_STAGE_IDS),
        "required_stage_ids": list(IMPLEMENTATION_STAGE_IDS),
        "score_pattern": score_pattern,
        "capability_stage_vocabulary": list(CAPABILITY_STAGES),
        "completeness": completeness,
        "non_it_contamination_terms": list(NON_IT_CONTAMINATION_TERMS),
        "similarity_thresholds": {
            "whole_lesson": WHOLE_LESSON_SIMILARITY_THRESHOLD,
            "adjacent_whole_lesson": ADJACENT_WHOLE_LESSON_SIMILARITY_THRESHOLD,
            "field": FIELD_SIMILARITY_THRESHOLD,
            "adjacent_field": ADJACENT_FIELD_SIMILARITY_THRESHOLD,
            "implementation": IMPLEMENTATION_SIMILARITY_THRESHOLD,
            "adjacent_implementation": ADJACENT_IMPLEMENTATION_SIMILARITY_THRESHOLD,
            "structural": STRUCTURAL_SIMILARITY_THRESHOLD,
            "adjacent_structural": ADJACENT_STRUCTURAL_SIMILARITY_THRESHOLD,
            "implementation_structural": IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
            "adjacent_implementation_structural": ADJACENT_IMPLEMENTATION_STRUCTURAL_SIMILARITY_THRESHOLD,
        },
    }
    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "exact_duplicates": exact_duplicates,
        "adjacent_exact_duplicates": adjacent_exact_duplicates,
        "item_duplicates": item_duplicates,
        "adjacent_item_duplicates": adjacent_item_duplicates,
        "frequency_item_duplicates": frequency_item_duplicates,
        "adjacent_similarity_pairs": adjacent_similarity_pairs,
        "field_similarity_pairs": field_similarity_pairs,
        "adjacent_field_similarity_pairs": adjacent_field_similarity_pairs,
        "whole_lesson_similarity_pairs": whole_lesson_similarity_pairs,
        "high_similarity_pairs": whole_lesson_similarity_pairs,
        "implementation_duplicates": implementation_duplicates,
        "adjacent_implementation_exact_duplicates": adjacent_implementation_exact_duplicates,
        "implementation_similarity_pairs": implementation_similarity_pairs,
        "adjacent_implementation_similarity_pairs": adjacent_implementation_similarity_pairs,
        "structural_similarity_pairs": structural_pairs,
        "implementation_structural_similarity_pairs": implementation_structural_pairs,
        "evaluation_remark_duplicates": evaluation_remark_duplicates,
        "evaluation_remark_similarity": evaluation_remark_similarity,
        "repeated_sentences": repeated_sentences,
        "boilerplate_hits": boilerplate_hits,
        "progression": progression,
        "reference_provenance": reference_provenance,
        "coverage": coverage,
        "completeness": completeness,
        "density_errors": density_errors,
        "resource_reuse": resource_reuse,
        "evaluation_remark_density": [
            item for item in density_errors if str(item.get("field", "")).startswith("evaluation.remarks.")
        ],
    }


def validate_content_quality(data: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    report = assess_content_quality(data, manifest)
    if report["status"] != "passed":
        details = "; ".join(report["errors"][:8])
        raise ContentQualityError(f"Content quality validation failed: {details}", report)
    return report


def detect_non_it_contamination(
    course_metadata: dict[str, Any],
    lesson: dict[str, Any] | str,
    rendered_text: str | None = None,
) -> list[str]:
    """Find IT defaults absent from the course metadata and current lesson source.

    The two-argument form remains accepted for callers that only have a complete
    source object; output validation uses the lesson-scoped three-argument form.
    """

    if rendered_text is None:
        rendered_text = str(lesson)
        lesson_scope: dict[str, Any] = {}
    else:
        lesson_scope = lesson if isinstance(lesson, dict) else {}
    source_text = json.dumps(
        {"course": course_metadata, "lesson": lesson_scope},
        ensure_ascii=False,
        sort_keys=True,
    )
    return sorted(
        term
        for term in NON_IT_CONTAMINATION_TERMS
        if term not in source_text and term in rendered_text
    )


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
