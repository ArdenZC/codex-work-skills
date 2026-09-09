"""Validate the public Practice Blueprint used before task authoring.

It records why a course calls for coding, tool operation, simulation,
debugging, modelling, data work, or scenario analysis.  It deliberately does
not prescribe a task count or an interaction quota.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BLUEPRINT_VERSION = "1.0"
REQUIRED_FIELDS = (
    "practice_goal",
    "duration_minutes",
    "available_learning_units",
    "practiceable_abilities",
    "forbidden_not_yet_taught",
    "activity_affordances",
    "task_plan",
    "scaffold_strategy",
    "tool_workflow",
    "support_strategy",
    "assessment_strategy",
    "coverage_matrix",
)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any, *, allow_empty: bool = False) -> bool:
    return isinstance(value, list) and (allow_empty or bool(value)) and all(_non_empty(item) for item in value)


def _list_or_objects(value: Any, field: str, errors: list[str], *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        errors.append(f"{field} must be a {'possibly empty' if allow_empty else 'non-empty'} list")
        return
    for index, item in enumerate(value):
        if not _non_empty(item) and not isinstance(item, dict):
            errors.append(f"{field}[{index}] must be a non-empty string or object")


def _coverage_errors(matrix: Any, errors: list[str]) -> None:
    if not isinstance(matrix, list) or not matrix:
        errors.append("coverage_matrix must be a non-empty list")
        return
    required = ("ability", "learning_unit", "allowed_depth", "suitable_modality", "starter_need", "scaffold")
    for index, row in enumerate(matrix):
        location = f"coverage_matrix[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{location} must be an object")
            continue
        for field in required:
            if field not in row or (not _non_empty(row[field]) and not isinstance(row[field], list)):
                errors.append(f"{location}.{field} is required")
        facts = row.get("canonical_facts", row.get("canonical_fact_ids", []))
        if not isinstance(facts, list):
            errors.append(f"{location}.canonical_facts must be a list")


def validate_practice_blueprint(value: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return {"status": "fail", "errors": ["practice_blueprint must be an object"], "warnings": []}
    if value.get("blueprint_version", BLUEPRINT_VERSION) != BLUEPRINT_VERSION:
        errors.append(f"blueprint_version must be {BLUEPRINT_VERSION}")
    for field in REQUIRED_FIELDS:
        if field not in value:
            errors.append(f"practice_blueprint is missing {field}")
    if not _non_empty(value.get("practice_goal")):
        errors.append("practice_goal must be a non-empty string")
    duration = value.get("duration_minutes")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 30:
        errors.append("duration_minutes must be an integer of at least 30")
    for field in ("available_learning_units", "practiceable_abilities", "activity_affordances", "task_plan", "scaffold_strategy", "tool_workflow", "support_strategy", "assessment_strategy"):
        _list_or_objects(value.get(field), field, errors)
    _list_or_objects(value.get("forbidden_not_yet_taught"), "forbidden_not_yet_taught", errors, allow_empty=True)
    _coverage_errors(value.get("coverage_matrix"), errors)
    affordances = value.get("activity_affordances", [])
    if isinstance(affordances, list) and affordances and not any(_non_empty(item) or isinstance(item, dict) for item in affordances):
        errors.append("activity_affordances must explain at least one natural course modality")
    forbidden = [key for key in value if any(marker in str(key).casefold() for marker in ("chain_of_thought", "private_reasoning", "hidden_reasoning"))]
    if forbidden:
        errors.append("practice_blueprint must not contain private reasoning fields: " + ", ".join(sorted(forbidden)))
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": []}


__all__ = ["BLUEPRINT_VERSION", "validate_practice_blueprint"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blueprint-json", required=True, type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.blueprint_json.expanduser().resolve().read_text(encoding="utf-8"))
        report = validate_practice_blueprint(value)
    except Exception as exc:  # noqa: BLE001 - CLI keeps the public validation result machine-readable
        report = {"status": "fail", "errors": [str(exc)], "warnings": []}
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else f"status={report['status']} errors={len(report['errors'])}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
