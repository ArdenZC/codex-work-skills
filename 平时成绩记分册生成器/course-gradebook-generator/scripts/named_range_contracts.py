"""The single source of truth for managed course-gradebook names."""

from __future__ import annotations

from typing import Any


NAMED_RANGE_MODE = "excel_named_range"
MANAGED_NAME_PREFIX = "gb_"


NAMED_RANGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "gb_title": {"kind": "cell", "role": "title"},
    "gb_term": {"kind": "cell", "role": "metadata"},
    "gb_course": {"kind": "cell", "role": "metadata"},
    "gb_teacher": {"kind": "cell", "role": "metadata"},
    "gb_class_name": {"kind": "cell", "role": "metadata"},
    "gb_header_serial": {"kind": "cell", "role": "header"},
    "gb_header_student_id": {"kind": "cell", "role": "header"},
    "gb_header_student_name": {"kind": "cell", "role": "header"},
    "gb_header_regular": {"kind": "cell", "role": "header"},
    "gb_header_theory": {"kind": "cell", "role": "header"},
    "gb_header_skill": {"kind": "cell", "role": "header"},
    "gb_header_total": {"kind": "cell", "role": "header"},
    "gb_data_table": {"kind": "matrix", "role": "data_table"},
    "gb_template_row": {"kind": "row", "role": "template_row"},
    "gb_serial_col": {"kind": "column", "role": "serial"},
    "gb_student_id_col": {"kind": "column", "role": "student_id"},
    "gb_student_name_col": {"kind": "column", "role": "student_name"},
    "gb_regular_items": {"kind": "matrix", "columns": 8, "role": "regular_scores"},
    "gb_regular_weighted_col": {"kind": "column", "role": "regular_weighted"},
    "gb_theory_score_col": {"kind": "column", "role": "theory_score"},
    "gb_theory_weighted_col": {"kind": "column", "role": "theory_weighted"},
    "gb_skill_score_col": {"kind": "column", "role": "skill_score"},
    "gb_skill_weighted_col": {"kind": "column", "role": "skill_weighted"},
    "gb_total_score_col": {"kind": "column", "role": "total_score"},
}

MANAGED_NAMES = tuple(NAMED_RANGE_CONTRACTS)
WITH_SKILL_REQUIRED_NAMES = MANAGED_NAMES
WITHOUT_SKILL_REMOVED_NAMES = (
    "gb_header_skill",
    "gb_skill_score_col",
    "gb_skill_weighted_col",
)
WITHOUT_SKILL_REQUIRED_NAMES = tuple(
    name for name in MANAGED_NAMES if name not in WITHOUT_SKILL_REMOVED_NAMES
)


def required_names(variant: str) -> tuple[str, ...]:
    if variant == "with_skill":
        return WITH_SKILL_REQUIRED_NAMES
    if variant == "without_skill":
        return WITHOUT_SKILL_REQUIRED_NAMES
    raise ValueError(f"Unknown gradebook named-range variant: {variant}")


def removed_names(variant: str) -> tuple[str, ...]:
    if variant == "with_skill":
        return ()
    if variant == "without_skill":
        return WITHOUT_SKILL_REMOVED_NAMES
    raise ValueError(f"Unknown gradebook named-range variant: {variant}")


def variant_for_skill(enabled: bool) -> str:
    return "with_skill" if enabled else "without_skill"


def contract_definitions() -> dict[str, dict[str, Any]]:
    """Return a detached copy so callers cannot mutate the global contract."""
    return {name: dict(definition) for name, definition in NAMED_RANGE_CONTRACTS.items()}
