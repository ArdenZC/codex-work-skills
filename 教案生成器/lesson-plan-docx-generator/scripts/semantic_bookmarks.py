from __future__ import annotations

import re
from typing import Iterable


BOOKMARK_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
RESERVED_BOOKMARK_NAMES = frozenset({"_GoBack"})


# This is the single source of truth for the managed v1.1 semantic anchors.
FIXED_BOOKMARKS = (
    ("title", "lp_title"),
    ("course_name", "lp_course_name"),
    ("major", "lp_major"),
    ("audience", "lp_audience"),
    ("unit", "lp_unit"),
    ("task", "lp_task"),
    ("hours", "lp_hours"),
    ("student_base", "lp_student_base"),
    ("student_problems", "lp_student_problems"),
    ("student_strategy", "lp_student_strategy"),
    ("teaching_content", "lp_teaching_content"),
    ("quality_goal", "lp_quality_goal"),
    ("knowledge_goal", "lp_knowledge_goal"),
    ("ability_goal", "lp_ability_goal"),
    ("key_content", "lp_key_content"),
    ("key_strategy", "lp_key_strategy"),
    ("difficult_content", "lp_difficult_content"),
    ("difficult_strategy", "lp_difficult_strategy"),
    ("teaching_methods", "lp_teaching_methods"),
    ("resources", "lp_resources"),
    ("references", "lp_references"),
    ("evaluation", "lp_evaluation"),
)

IMPLEMENTATION_STAGES = (
    ("before_class_preparation", "prep", 16),
    ("task_introduction", "intro", 18),
    ("operation_demonstration", "demo", 19),
    ("task_implementation", "exec", 20),
    ("task_extension", "extend", 21),
    ("project_practice", "practice", 22),
    ("peer_review", "peer", 23),
    ("lesson_summary", "summary", 24),
    ("after_class_improvement", "improve", 26),
)

IMPLEMENTATION_COLUMNS = (
    ("stage", "stage", 0),
    ("content", "content", 1),
    ("teacher_activity", "teacher", 2),
    ("student_activity", "student", 3),
    ("objective", "goal", 4),
)

REFLECTION_BOOKMARKS = (
    ("summary", "lp_reflection_summary", 27),
    ("innovation", "lp_reflection_innovation", 28),
    ("improvement", "lp_reflection_improvement", 29),
)


FIXED_BOOKMARK_MAP = dict(FIXED_BOOKMARKS)
REFLECTION_BOOKMARK_MAP = {field: name for field, name, _row in REFLECTION_BOOKMARKS}


SEMANTIC_FIELD_CONTRACTS = {
    "title": {
        "bookmark": FIXED_BOOKMARK_MAP["title"],
        "target": "document_paragraph",
        "mode": "replace_text_preserve_style",
        "container": "document_paragraph",
    },
    "course_name": {
        "bookmark": FIXED_BOOKMARK_MAP["course_name"],
        "target": "table_cell",
        "mode": "replace_single_paragraph",
        "container": "cell",
    },
    "major": {
        "bookmark": FIXED_BOOKMARK_MAP["major"],
        "target": "table_cell",
        "mode": "replace_single_paragraph",
        "container": "cell",
    },
    "audience": {
        "bookmark": FIXED_BOOKMARK_MAP["audience"],
        "target": "table_cell",
        "mode": "replace_single_paragraph",
        "container": "cell",
    },
    "unit": {
        "bookmark": FIXED_BOOKMARK_MAP["unit"],
        "target": "table_cell",
        "mode": "replace_single_paragraph",
        "container": "cell",
    },
    "task": {
        "bookmark": FIXED_BOOKMARK_MAP["task"],
        "target": "table_cell",
        "mode": "replace_single_paragraph",
        "container": "cell",
    },
    "hours": {
        "bookmark": FIXED_BOOKMARK_MAP["hours"],
        "target": "table_cell",
        "mode": "replace_single_paragraph",
        "container": "cell",
    },
    "student_base": {
        "bookmark": FIXED_BOOKMARK_MAP["student_base"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "student_problems": {
        "bookmark": FIXED_BOOKMARK_MAP["student_problems"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "student_strategy": {
        "bookmark": FIXED_BOOKMARK_MAP["student_strategy"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "teaching_content": {
        "bookmark": FIXED_BOOKMARK_MAP["teaching_content"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "quality_goal": {
        "bookmark": FIXED_BOOKMARK_MAP["quality_goal"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "knowledge_goal": {
        "bookmark": FIXED_BOOKMARK_MAP["knowledge_goal"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "ability_goal": {
        "bookmark": FIXED_BOOKMARK_MAP["ability_goal"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "key_content": {
        "bookmark": FIXED_BOOKMARK_MAP["key_content"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "key_strategy": {
        "bookmark": FIXED_BOOKMARK_MAP["key_strategy"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "difficult_content": {
        "bookmark": FIXED_BOOKMARK_MAP["difficult_content"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "difficult_strategy": {
        "bookmark": FIXED_BOOKMARK_MAP["difficult_strategy"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "teaching_methods": {
        "bookmark": FIXED_BOOKMARK_MAP["teaching_methods"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "resources": {
        "bookmark": FIXED_BOOKMARK_MAP["resources"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "references": {
        "bookmark": FIXED_BOOKMARK_MAP["references"],
        "target": "table_cell",
        "mode": "replace_paragraphs",
        "container": "cell",
    },
    "evaluation": {
        "bookmark": FIXED_BOOKMARK_MAP["evaluation"],
        "target": "nested_table",
        "mode": "nested_table",
        "container": "cell",
    },
}


def fixed_bookmark(field: str) -> str:
    try:
        return FIXED_BOOKMARK_MAP[field]
    except KeyError as exc:
        raise KeyError(f"Unknown semantic fixed field: {field}") from exc


def semantic_field_contract(field: str) -> dict[str, str]:
    try:
        return dict(SEMANTIC_FIELD_CONTRACTS[field])
    except KeyError as exc:
        raise KeyError(f"Unknown semantic field: {field}") from exc


def reflection_bookmark(field: str) -> str:
    try:
        return REFLECTION_BOOKMARK_MAP[field]
    except KeyError as exc:
        raise KeyError(f"Unknown semantic reflection field: {field}") from exc


def implementation_bookmark(stage_code: str, column_code: str) -> str:
    return f"lp_impl_{stage_code}_{column_code}"


def implementation_bookmark_groups() -> list[list[str]]:
    return [
        [implementation_bookmark(stage_code, column_code) for _field, column_code, _cell in IMPLEMENTATION_COLUMNS]
        for _stage_id, stage_code, _row in IMPLEMENTATION_STAGES
    ]


def reflection_bookmark_names() -> list[str]:
    return [name for _field, name, _row in REFLECTION_BOOKMARKS]


def managed_bookmark_names() -> list[str]:
    fixed = [name for _field, name in FIXED_BOOKMARKS]
    implementation = [name for group in implementation_bookmark_groups() for name in group]
    return fixed + implementation + reflection_bookmark_names()


def managed_bookmark_name_errors(names: Iterable[str]) -> list[str]:
    errors: list[str] = []
    for name in names:
        value = str(name)
        if not value:
            errors.append("empty bookmark name")
        elif value in RESERVED_BOOKMARK_NAMES:
            errors.append(f"reserved Word bookmark name {value}")
        elif not BOOKMARK_NAME_PATTERN.fullmatch(value):
            errors.append(f"bookmark {value!r} violates the Word 40-character safe-name rule")
    return errors
