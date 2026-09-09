"""Validate the public Course Blueprint used before Contract 1.1 authoring.

The blueprint is an auditable planning artifact, not a renderer input.  Keeping
this check separate from the content contract lets a course choose its own
sequence while still proving that time, scope, audience, and extension reserve
were considered before slides were written.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BLUEPRINT_VERSION = "1.0"
REQUIRED_FIELDS = (
    "course_goal",
    "session_minutes",
    "prepared_minutes",
    "audience_profile",
    "learning_units",
    "canonical_facts",
    "not_yet_taught",
    "teaching_sequence",
    "visual_needs",
    "activity_needs",
    "likely_misconceptions",
    "prepared_extension_plan",
)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_non_empty(item) for item in value)


def _errors_for_list(value: Any, field: str, errors: list[str], *, allow_empty: bool = True) -> None:
    if not isinstance(value, list) or (not allow_empty and not value):
        errors.append(f"{field} must be a {'possibly empty' if allow_empty else 'non-empty'} list")
        return
    for index, item in enumerate(value):
        if not _non_empty(item) and not isinstance(item, dict):
            errors.append(f"{field}[{index}] must be a non-empty string or object")


def validate_course_blueprint(value: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return {"status": "fail", "errors": ["course_blueprint must be an object"], "warnings": []}
    if value.get("blueprint_version", BLUEPRINT_VERSION) != BLUEPRINT_VERSION:
        errors.append(f"blueprint_version must be {BLUEPRINT_VERSION}")
    for field in REQUIRED_FIELDS:
        if field not in value:
            errors.append(f"course_blueprint is missing {field}")
    if not _non_empty(value.get("course_goal")):
        errors.append("course_goal must be a non-empty string")
    session = value.get("session_minutes")
    prepared = value.get("prepared_minutes")
    core = value.get("core_minutes", session)
    extension = value.get("extension_minutes", 0)
    for field, number in (("session_minutes", session), ("prepared_minutes", prepared), ("core_minutes", core), ("extension_minutes", extension)):
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            errors.append(f"{field} must be a non-negative integer")
    if isinstance(session, int) and session <= 0:
        errors.append("session_minutes must be positive")
    if isinstance(session, int) and isinstance(prepared, int) and prepared < session:
        errors.append("prepared_minutes must be >= session_minutes")
    if isinstance(prepared, int) and isinstance(core, int) and core > prepared:
        errors.append("core_minutes must be <= prepared_minutes")
    if isinstance(session, int) and isinstance(core, int) and core > session:
        errors.append("core_minutes must be <= session_minutes")
    if isinstance(prepared, int) and isinstance(core, int) and isinstance(extension, int) and extension != prepared - core:
        errors.append("extension_minutes must equal prepared_minutes - core_minutes")

    audience = value.get("audience_profile")
    if not isinstance(audience, dict):
        errors.append("audience_profile must be an object")
    else:
        if not _non_empty(audience.get("level")):
            errors.append("audience_profile.level must be a non-empty string")
        for field in ("prior_knowledge", "likely_weaknesses"):
            if not _string_list(audience.get(field)):
                errors.append(f"audience_profile.{field} must be a non-empty string list")

    _errors_for_list(value.get("learning_units"), "learning_units", errors, allow_empty=False)
    _errors_for_list(value.get("canonical_facts"), "canonical_facts", errors)
    _errors_for_list(value.get("not_yet_taught"), "not_yet_taught", errors)
    _errors_for_list(value.get("visual_needs"), "visual_needs", errors)
    _errors_for_list(value.get("activity_needs"), "activity_needs", errors)
    _errors_for_list(value.get("likely_misconceptions"), "likely_misconceptions", errors)
    _errors_for_list(value.get("prepared_extension_plan"), "prepared_extension_plan", errors, allow_empty=not (isinstance(extension, int) and extension > 0))
    sequence = value.get("teaching_sequence")
    if not isinstance(sequence, list) or not sequence:
        errors.append("teaching_sequence must be a non-empty list")
    else:
        sequence_minutes = 0
        for index, phase in enumerate(sequence):
            location = f"teaching_sequence[{index}]"
            if not isinstance(phase, dict):
                errors.append(f"{location} must be an object")
                continue
            for field in ("phase", "purpose"):
                if not _non_empty(phase.get(field)):
                    errors.append(f"{location}.{field} must be a non-empty string")
            minutes = phase.get("minutes")
            if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
                errors.append(f"{location}.minutes must be a positive integer")
            else:
                sequence_minutes += minutes
        if isinstance(prepared, int) and sequence_minutes and sequence_minutes != prepared:
            errors.append(f"teaching_sequence minutes {sequence_minutes} must equal prepared_minutes {prepared}")

    forbidden = [key for key in value if any(marker in str(key).casefold() for marker in ("chain_of_thought", "private_reasoning", "hidden_reasoning"))]
    if forbidden:
        errors.append("course_blueprint must not contain private reasoning fields: " + ", ".join(sorted(forbidden)))
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": []}


__all__ = ["BLUEPRINT_VERSION", "validate_course_blueprint"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blueprint-json", required=True, type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.blueprint_json.expanduser().resolve().read_text(encoding="utf-8"))
        report = validate_course_blueprint(value)
    except Exception as exc:  # noqa: BLE001 - CLI keeps the public validation result machine-readable
        report = {"status": "fail", "errors": [str(exc)], "warnings": []}
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else f"status={report['status']} errors={len(report['errors'])}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
