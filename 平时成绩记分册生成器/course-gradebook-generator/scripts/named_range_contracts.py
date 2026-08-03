"""The single source of truth for managed course-gradebook names."""

from __future__ import annotations

from typing import Any


NAMED_RANGE_MODE = "excel_named_range"
MANAGED_NAME_PREFIX = "gb_"
SUPPORTED_TEMPLATE_MAJOR = 1
SUPPORTED_TEMPLATE_MINORS = frozenset({0, 1})


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


# v1.1 semantic fields are deliberately closed.  Keep this mapping independent
# from the YAML so a manifest cannot redefine what a field means.
V11_FIELD_CONTRACTS: dict[str, dict[str, Any]] = {
    "term": {
        "target": "named_range",
        "name": "gb_term",
        "mode": "replace_value",
        "max_chars": 32,
    },
    "course": {
        "target": "named_range",
        "name": "gb_course",
        "mode": "replace_value",
        "max_chars": 64,
    },
    "teacher": {
        "target": "named_range",
        "name": "gb_teacher",
        "mode": "replace_value",
        "max_chars": 32,
    },
    "class_name": {
        "target": "named_range",
        "name": "gb_class_name",
        "mode": "replace_value",
        "max_chars": 64,
    },
    "student_id": {
        "target": "named_range",
        "name": "gb_student_id_col",
        "mode": "text",
        "pattern": r"^\d{8,}$",
    },
    "regular_scores": {
        "target": "named_range",
        "name": "gb_regular_items",
        "mode": "decimal_half",
        "average_matches": "students.regular",
    },
    "theory_score": {
        "target": "named_range",
        "name": "gb_theory_score_col",
        "mode": "number",
    },
    "skill_score": {
        "target": "named_range",
        "name": "gb_skill_score_col",
        "mode": "number",
        "optional_when": "weights.skill == 0",
    },
    "formula_columns_with_skill": {
        "names": [
            "gb_regular_weighted_col",
            "gb_theory_weighted_col",
            "gb_skill_weighted_col",
            "gb_total_score_col",
        ],
        "mode": "formula",
    },
    "formula_columns_without_skill": {
        "names": [
            "gb_regular_weighted_col",
            "gb_theory_weighted_col",
            "gb_total_score_col",
        ],
        "mode": "formula",
    },
}

V11_LAYOUT_CONTRACT: dict[str, Any] = {
    "worksheet_from": "gb_data_table",
    "data_table": "gb_data_table",
    "template_row": "gb_template_row",
    "columns": {
        "serial": "gb_serial_col",
        "student_id": "gb_student_id_col",
        "student_name": "gb_student_name_col",
        "regular_items": "gb_regular_items",
        "regular_weighted": "gb_regular_weighted_col",
        "theory_score": "gb_theory_score_col",
        "theory_weighted": "gb_theory_weighted_col",
        "skill_score": "gb_skill_score_col",
        "skill_weighted": "gb_skill_weighted_col",
        "total_score": "gb_total_score_col",
    },
}

# These contracts describe metadata that changes how the generator reads or
# protects a workbook.  They deliberately live beside the managed-name
# contract so a patch manifest cannot silently redefine generator behavior.
V11_TEMPLATE_KEYS = frozenset({
    "id",
    "name",
    "version",
    "format",
    "file",
    "base_manifest",
    "base_template",
})
V11_TEMPLATE_STATIC = {
    "id": "course-gradebook",
    "name": "湖北职业技术学院学生平时成绩登记表",
    "format": "xls",
}
V11_GENERATOR_CONTRACT = {
    "version": "1.1.0",
    "supported_major": 1,
}
V11_SOURCE_CONTRACT = {
    "metadata_line2_cell": "A2",
    "metadata_line3_cell": "A3",
    "header_row": 4,
    "data_start_row": 5,
    "headers": {
        "student_id": "学号",
        "student_name": "姓名",
        "regular": "平时成绩",
        "theory": "理论成绩",
        "skill": "技能成绩",
        "total": "总成绩",
    },
}
V11_VALIDATION_CONTRACT = {
    "required_headers": ["序号", "学号", "姓名", "平时成绩(20%)", "理论成绩(50%)", "总评\n成绩"],
    "template_data_rows": 48,
    "regular_item_count": 8,
    "require_formula_columns": True,
    "require_student_id_text": True,
    "require_xls_open": True,
    "expected_print_area": "",
    "require_print_area": False,
    "page_orientation": "landscape",
    "expected_freeze_panes": None,
    "required_named_ranges": list(MANAGED_NAMES),
    "required_data_validations": 0,
    "required_conditional_formats": 0,
    "require_no_formula_errors": True,
}
V11_ALLOWED_CHANGES = [
    "named ranges declared under fields and layout",
    "student rows within gb_data_table through the generated last row",
    "regular score cells, theory score, optional skill score and declared formula ranges",
    "deletion of the two skill columns when weights.skill is zero",
]
V11_PROTECTED = [
    "workbook sheet names and non-target sheets",
    "merged ranges, page setup, print settings, widths, heights and base styles",
    "header labels except declared percentage text",
    "formulas and number formats outside declared output columns",
    "student ID text format",
]

V10_TEMPLATE_STATIC = {
    "id": "course-gradebook",
    "name": "湖北职业技术学院学生平时成绩登记表",
    "format": "xls",
}


def v11_variant_contracts() -> dict[str, dict[str, list[str]]]:
    return {
        "with_skill": {"required": list(WITH_SKILL_REQUIRED_NAMES), "forbidden": []},
        "without_skill": {
            "required": list(WITHOUT_SKILL_REQUIRED_NAMES),
            "forbidden": list(WITHOUT_SKILL_REMOVED_NAMES),
        },
    }


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
