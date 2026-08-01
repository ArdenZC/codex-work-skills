from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_DIR / "assets" / "templates" / "course-gradebook" / "v1.0.0" / "manifest.yaml"
DEFAULT_SCHEMA = SKILL_DIR / "schemas" / "gradebook-input.schema.json"
REGULAR_SCORE_INCREMENT = Decimal("0.5")
FLOAT_NOISE_TOLERANCE = Decimal("1e-9")


def _decimal(value: Any, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not numeric: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"{label} must be finite: {value!r}")
    return number


def excel_round(value: Any) -> int:
    """Return the positive-grade equivalent of Excel ROUND(value, 0)."""
    return int(_decimal(value, "Grade value").quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate_expected_total(student: dict[str, Any], weights: dict[str, Any]) -> int:
    weighted = (
        _decimal(student["regular"], "regular score") * _decimal(weights["regular"], "regular weight")
        + _decimal(student["theory"], "theory score") * _decimal(weights["theory"], "theory weight")
        + _decimal(student.get("skill", 0), "skill score") * _decimal(weights["skill"], "skill weight")
    )
    return excel_round(weighted)


def source_total_matches(source_total: Any, expected_total: int) -> bool:
    actual = _decimal(source_total, "Source total")
    return abs(actual - Decimal(int(expected_total))) <= FLOAT_NOISE_TOLERANCE


def validate_source_totals(students: list[dict[str, Any]], weights: dict[str, Any]) -> None:
    for index, student in enumerate(students, start=1):
        expected = calculate_expected_total(student, weights)
        if not source_total_matches(student["total"], expected):
            actual = _decimal(student["total"], "Source total")
            raise ValueError(
                f"Source total mismatch at record {index}: expected {expected} after Excel ROUND(...,0), "
                f"received {actual}. The source total may include a manual adjustment or be inconsistent "
                "with the configured formula."
            )


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


def validate_input(data: dict[str, Any], schema_path: Path | str = DEFAULT_SCHEMA) -> None:
    for index, student in enumerate(data.get("students", [])):
        if not isinstance(student, dict) or "regular" not in student:
            continue
        try:
            regular = Decimal(str(student["regular"]))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not regular.is_finite() or regular % REGULAR_SCORE_INCREMENT != 0:
            raise ValueError(
                f"students[{index}].regular must use 0.5-point increments; received {student['regular']}."
            )
    schema = load_schema(schema_path)
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise ValueError(f"Input schema validation failed: {details}")
    weights = data["weights"]
    if not math.isclose(sum(float(weights[name]) for name in ("regular", "theory", "skill")), 1.0, abs_tol=1e-6):
        raise ValueError("Input weights must sum to 1.0")


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


def column_number(column: str) -> int:
    value = 0
    for char in column.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"Invalid Excel column: {column}")
        value = value * 26 + ord(char) - ord("A") + 1
    return value


def cell_address(column: str, row: int) -> str:
    return f"{column.upper()}{row}"


def percentage_label(value: Any) -> str:
    percent = (_decimal(value, "Percentage") * Decimal("100")).quantize(
        Decimal("0.000000000001"), rounding=ROUND_HALF_UP
    )
    return format(percent.normalize(), "f")
