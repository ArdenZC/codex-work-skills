"""Pure formatters for Lesson Content V2.

This module deliberately does not invent teaching language.  It only maps
validated JSON values to the text representations used by the existing Word
template.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable


CONTENT_CONTRACT_VERSION = "2.0"
EVALUATION_SCORE_MIN = Decimal("85")
EVALUATION_SCORE_MAX = Decimal("96")
EVALUATION_SCORE_STEP = Decimal("0.5")
CAPABILITY_STAGES = ("认知", "理解", "模仿", "独立", "综合", "优化", "迁移")

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


def format_numbered_list(items: Iterable[Any]) -> str:
    """Number existing list items without adding or removing their meaning."""

    values = [_clean(item) for item in items if _clean(item)]
    return "\n".join(f"{index}. {value}" for index, value in enumerate(values, 1))


def format_reference_list(references: Iterable[dict[str, Any]]) -> str:
    """Write only reference text; source provenance is an internal contract field."""

    return format_numbered_list(reference["text"] for reference in references)


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
        0: f"{_clean(stage['label'])}\n{minutes_text}min\n{_clean(stage['modality'])}",
        1: format_numbered_list(stage["content"]),
        2: format_numbered_list(stage["teacher_actions"]),
        3: format_numbered_list(stage["student_actions"]),
        4: _clean(stage["objective"]),
    }


def format_implementation(implementation: Iterable[dict[str, Any]]) -> list[dict[int, str]]:
    return [format_implementation_stage(stage) for stage in implementation]


def format_reflection(reflection: dict[str, Any]) -> list[str]:
    return [
        _clean(reflection["summary"]),
        _clean(reflection["innovation"]),
        _clean(reflection["improvement"]),
    ]


def lesson_content_field_values(lesson: dict[str, Any]) -> dict[str, str]:
    """Map a V2 lesson to all non-header cells in the canonical template."""

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
    values["references"] = format_reference_list(lesson["references"])
    return values


def lesson_header_values(data: dict[str, Any], lesson: dict[str, Any]) -> dict[str, str]:
    return {
        "course_name": _clean(data["course_name"]),
        "major": _clean(data["major"]),
        "audience": _clean(data["audience"]),
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
        values.append({2: score_text, 3: _clean(remarks[criterion_id])})
    return values


def format_title(sequence: int, data: dict[str, Any], lesson: dict[str, Any]) -> str:
    return f"{sequence} 《{_clean(data['course_name'])}》教学单元设计：{_clean(lesson['task'])}"
