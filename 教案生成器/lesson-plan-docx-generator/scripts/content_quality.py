"""Deterministic course-level quality checks for Lesson Content V2."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from content_contract import (
    CONTENT_FIELD_NAMES,
    EVALUATION_CRITERIA,
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
# Use the same conservative threshold for long narrative fields so a field
# copied with only superficial edits is reported before whole-lesson scoring.
FIELD_SIMILARITY_THRESHOLD = 0.85
IMPLEMENTATION_DUPLICATE_LESSON_COUNT = 3

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
    return {
        "student_analysis.base": _joined(analysis["base"]),
        "student_analysis.problems": _joined(analysis["problems"]),
        "student_analysis.strategies": _joined(analysis["strategies"]),
        "key_point": _joined(lesson["key_point"]),
        "difficult_point": _joined(lesson["difficult_point"]),
        "reflection.summary": _normalize(lesson["reflection"]["summary"]),
        "reflection.innovation": _normalize(lesson["reflection"]["innovation"]),
        "reflection.improvement": _normalize(lesson["reflection"]["improvement"]),
    }


def _lesson_narrative(lesson: dict[str, Any]) -> str:
    values = lesson_content_field_values(lesson)
    values["progression"] = _joined(lesson["progression"])
    values["reflection"] = _joined(lesson["reflection"])
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
        if len(_normalize(value)) < minimum:
            errors.append(f"{lesson_id}.{field} does not contain meaningful content")

    for index, lesson in enumerate(data.get("lessons", []), 1):
        lesson_id = _lesson_id(lesson, index)
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
        for field_name in ("teaching_content", "teaching_methods", "resources", "references"):
            for item_index, value in enumerate(lesson[field_name], 1):
                check_text(lesson_id, f"{field_name}[{item_index}]", value)
        for goal_name in ("knowledge", "ability", "quality"):
            for item_index, value in enumerate(goals[goal_name], 1):
                check_text(lesson_id, f"goals.{goal_name}[{item_index}]", value)
        for point_name in ("key_point", "difficult_point"):
            for list_name in ("content", "strategy"):
                for item_index, value in enumerate(lesson[point_name][list_name], 1):
                    check_text(lesson_id, f"{point_name}.{list_name}[{item_index}]", value)
        for field_name in ("prior_learning", "deliverable", "next_bridge"):
            check_text(lesson_id, f"progression.{field_name}", lesson["progression"][field_name], 6)
        for stage in lesson["implementation"]:
            stage_id = str(stage["id"])
            for field_name in ("content", "teacher_actions", "student_actions"):
                for item_index, value in enumerate(stage[field_name], 1):
                    check_text(lesson_id, f"implementation.{stage_id}.{field_name}[{item_index}]", value)
            check_text(lesson_id, f"implementation.{stage_id}.objective", stage["objective"], 6)
        for field_name in ("summary", "innovation", "improvement"):
            check_text(lesson_id, f"reflection.{field_name}", lesson["reflection"][field_name], 12)

    return {"lessons": counts, "meaningful_errors": errors}, errors


def _density_report(data: dict[str, Any], manifest: dict[str, Any] | None) -> tuple[list[dict[str, Any]], int]:
    if not manifest:
        return [], 0
    errors: list[dict[str, Any]] = []
    total_chars = 0
    fields = manifest.get("fields", {})
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
    return errors, total_chars


def assess_content_quality(data: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    lessons = data.get("lessons", [])
    lesson_ids = [_lesson_id(lesson, index) for index, lesson in enumerate(lessons, 1)]
    errors: list[str] = []

    duplicate_values = {field: {} for field in _field_groups(lessons[0])} if lessons else {}
    for index, lesson in enumerate(lessons, 1):
        for field, value in _field_groups(lesson).items():
            duplicate_values[field][_lesson_id(lesson, index)] = value
    exact_duplicates = _record_duplicate_groups(duplicate_values)
    if exact_duplicates:
        errors.extend(f"exact duplicate {item['field']}: {','.join(item['lessons'])}" for item in exact_duplicates)

    implementation_values: dict[str, dict[str, str]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for stage in lesson.get("implementation", []):
            stage_id = str(stage.get("id", ""))
            formatted = format_implementation_stage(stage)
            for field_name, cell_index in zip(IMPLEMENTATION_STAGE_FIELDS, (1, 2, 3, 4)):
                implementation_values.setdefault(f"{stage_id}.{field_name}", {})[lesson_id] = formatted[cell_index]
    implementation_duplicates = _record_duplicate_groups(implementation_values, IMPLEMENTATION_DUPLICATE_LESSON_COUNT)
    if implementation_duplicates:
        errors.extend(f"implementation duplicate {item['field']}: {','.join(item['lessons'])}" for item in implementation_duplicates)

    field_similarity_pairs: list[dict[str, Any]] = []
    for field, per_lesson in duplicate_values.items():
        ids = list(per_lesson)
        for left_index, left_id in enumerate(ids):
            for right_id in ids[left_index + 1 :]:
                left_text, right_text = per_lesson[left_id], per_lesson[right_id]
                if min(len(left_text), len(right_text)) < 30:
                    continue
                sequence, jaccard = _similarity(left_text, right_text)
                if sequence >= FIELD_SIMILARITY_THRESHOLD:
                    field_similarity_pairs.append(
                        {
                            "field": field,
                            "lessons": sorted((left_id, right_id)),
                            "sequence_matcher": round(sequence, 4),
                            "character_3gram_jaccard": round(jaccard, 4),
                            "top_repeated_fragments": _top_fragments(left_text, right_text),
                        }
                    )
    field_similarity_pairs.sort(key=lambda item: (-item["sequence_matcher"], item["field"], item["lessons"]))
    if field_similarity_pairs:
        errors.extend(
            f"high field similarity {item['field']} {item['lessons']}: {item['sequence_matcher']}"
            for item in field_similarity_pairs
        )

    sentence_locations: dict[str, set[str]] = {}
    for index, lesson in enumerate(lessons, 1):
        lesson_id = _lesson_id(lesson, index)
        for field, values in _all_content_strings(lesson).items():
            for value in values:
                for sentence in _sentences(value):
                    sentence_locations.setdefault(sentence, set()).add(lesson_id)
    repeated_sentences = [
        {"sentence": sentence, "lessons": sorted(locations), "count": len(locations)}
        for sentence, locations in sentence_locations.items()
        if len(locations) >= REPEATED_SENTENCE_LESSON_COUNT
    ]
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
        errors.extend(f"legacy boilerplate in {item['lesson']}.{item['field']}: {item['fragment']}" for item in boilerplate_hits)

    high_similarity_pairs: list[dict[str, Any]] = []
    narratives = {_lesson_id(lesson, index): _lesson_narrative(lesson) for index, lesson in enumerate(lessons, 1)}
    ids = list(narratives)
    for left_index, left_id in enumerate(ids):
        for right_id in ids[left_index + 1 :]:
            left_text, right_text = narratives[left_id], narratives[right_id]
            if min(len(left_text), len(right_text)) < 30:
                continue
            sequence, jaccard = _similarity(left_text, right_text)
            if sequence >= WHOLE_LESSON_SIMILARITY_THRESHOLD:
                high_similarity_pairs.append(
                    {
                        "lessons": sorted((left_id, right_id)),
                        "sequence_matcher": round(sequence, 4),
                        "character_3gram_jaccard": round(jaccard, 4),
                        "top_repeated_fragments": _top_fragments(left_text, right_text),
                    }
                )
    high_similarity_pairs.sort(key=lambda item: (-item["sequence_matcher"], item["lessons"]))
    if high_similarity_pairs:
        errors.extend(f"high whole-lesson similarity {item['lessons']}: {item['sequence_matcher']}" for item in high_similarity_pairs)

    progression_stages = [str(lesson.get("progression", {}).get("capability_stage", "")) for lesson in lessons]
    progression = {
        "lesson_ids": lesson_ids,
        "capability_stages": progression_stages,
        "distinct_capability_stages": sorted(set(progression_stages)),
        "stage_count": len(progression_stages),
        "valid_variety": len(set(progression_stages)) > 1 if len(progression_stages) >= 4 else True,
    }
    if len(progression_stages) >= 4 and len(set(progression_stages)) <= 1:
        errors.append("progression capability_stage is identical across all lessons")

    scores = []
    for lesson in lessons:
        try:
            scores.append(float(lesson["evaluation"]["score"]))
        except (KeyError, TypeError, ValueError):
            pass
    score_pattern = {"values": scores, "all_same": len(scores) > 1 and len(set(scores)) == 1, "simple_cycle": False}
    for period in range(1, min(3, len(scores) - 1) + 1):
        if all(scores[index] == scores[index % period] for index in range(len(scores))):
            score_pattern["simple_cycle"] = True
            break
    if score_pattern["all_same"]:
        errors.append("evaluation scores are identical across lessons")
    if score_pattern["simple_cycle"]:
        errors.append("evaluation scores use a simple repeating cycle")

    completeness, completeness_errors = _completeness_report(data)
    errors.extend(completeness_errors)

    density_errors, meaningful_chars = _density_report(data, manifest)
    if density_errors:
        errors.extend(
            f"content density exceeds {item['field']} for {item['lesson']}: "
            f"actual_chars={item.get('actual_chars', '?')} limit={item.get('limit', '?')}"
            for item in density_errors
        )

    coverage = {
        "lesson_count": len(lessons),
        "implementation_stages": {lesson_id: len(lesson.get("implementation", [])) for lesson_id, lesson in zip(lesson_ids, lessons)},
        "meaningful_characters": meaningful_chars,
        "content_fields": len(CONTENT_FIELD_NAMES),
        "evaluation_criteria": len(EVALUATION_CRITERIA),
        "in_class_stage_ids": sorted(IN_CLASS_STAGE_IDS),
        "required_stage_ids": list(IMPLEMENTATION_STAGE_IDS),
        "score_pattern": score_pattern,
        "completeness": completeness,
        "non_it_contamination_terms": list(NON_IT_CONTAMINATION_TERMS),
    }
    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "exact_duplicates": exact_duplicates,
        "implementation_duplicates": implementation_duplicates,
        "high_similarity_pairs": high_similarity_pairs,
        "field_similarity_pairs": field_similarity_pairs,
        "repeated_sentences": repeated_sentences,
        "boilerplate_hits": boilerplate_hits,
        "progression": progression,
        "coverage": coverage,
        "completeness": completeness,
        "density_errors": density_errors,
    }


def validate_content_quality(data: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    report = assess_content_quality(data, manifest)
    if report["status"] != "passed":
        details = "; ".join(report["errors"][:8])
        raise ContentQualityError(f"Content quality validation failed: {details}", report)
    return report


def detect_non_it_contamination(data: dict[str, Any], rendered_text: str) -> list[str]:
    """Find IT defaults that appear in output without being present in the source JSON."""

    source_text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return sorted(
        term
        for term in NON_IT_CONTAMINATION_TERMS
        if term not in source_text and term in rendered_text
    )


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
