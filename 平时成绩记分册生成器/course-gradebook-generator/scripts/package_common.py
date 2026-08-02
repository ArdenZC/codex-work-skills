from __future__ import annotations

import json
import hashlib
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from named_range_contracts import SUPPORTED_TEMPLATE_MAJOR, SUPPORTED_TEMPLATE_MINORS


SKILL_DIR = Path(__file__).resolve().parents[1]
V10_PACKAGE_DIR = SKILL_DIR / "assets" / "templates" / "course-gradebook" / "v1.0.0"
V11_PACKAGE_DIR = SKILL_DIR / "assets" / "templates" / "course-gradebook" / "v1.1.0"
V10_MANIFEST = V10_PACKAGE_DIR / "manifest.yaml"
V11_MANIFEST = V11_PACKAGE_DIR / "manifest.yaml"
V10_TEMPLATE = V10_PACKAGE_DIR / "template.xls"
V11_TEMPLATE = V11_PACKAGE_DIR / "template.xls"
V10_COMPATIBILITY_TEMPLATE = SKILL_DIR / "assets" / "平时成绩记分册模板.xls"
DEFAULT_MANIFEST = V11_MANIFEST
DEFAULT_SCHEMA = SKILL_DIR / "schemas" / "gradebook-input.schema.json"
REGULAR_SCORE_INCREMENT = Decimal("0.5")
FLOAT_NOISE_TOLERANCE = Decimal("1e-9")


@dataclass(frozen=True)
class TemplatePackage:
    template_path: Path
    manifest_path: Path
    manifest: dict[str, Any]
    anchor_mode: str


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


def parse_template_version(version: Any) -> tuple[int, int, int]:
    text = str(version or "")
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)",
        text,
        flags=re.ASCII,
    )
    if match is None:
        raise ValueError("Manifest must declare an ASCII semantic template version without leading zeros")
    return tuple(int(part) for part in match.groups())


def anchor_mode(manifest_or_version: dict[str, Any] | str) -> str:
    version = (
        manifest_or_version.get("template", {}).get("version")
        if isinstance(manifest_or_version, dict)
        else manifest_or_version
    )
    _, minor, _ = parse_template_version(version)
    if minor not in SUPPORTED_TEMPLATE_MINORS:
        raise ValueError(
            f"Unsupported template minor version {minor}; supported minors are {sorted(SUPPORTED_TEMPLATE_MINORS)}"
        )
    if minor == 0:
        return "legacy_coordinates"
    if minor == 1:
        return "excel_named_range"
    raise ValueError(f"Unsupported template minor version {minor}")


def validate_legacy_manifest_contract(manifest: dict[str, Any]) -> None:
    if "anchors" in manifest or "layout" in manifest:
        raise ValueError("Legacy v1.0 manifest must not declare named-range metadata")
    keys = set(manifest) - {"_path"}
    expected_top_level = {
        "template",
        "generator",
        "structure",
        "fields",
        "allowed_changes",
        "protected",
        "validation",
        "fingerprint",
    }
    if keys != expected_top_level:
        unknown = sorted(keys - expected_top_level)
        missing = sorted(expected_top_level - keys)
        detail = f"unknown keys {unknown}" if unknown else f"missing keys {missing}"
        raise ValueError(f"Legacy v1.0 manifest has an invalid closed contract: {detail}")
    structure = manifest.get("structure")
    if not isinstance(structure, dict) or not structure.get("metadata") or not structure.get("columns"):
        raise ValueError("Legacy v1.0 manifest must declare coordinate structure.metadata and structure.columns")
    expected_fields = {
        "term": {"target": "C2", "mode": "replace_value", "max_chars": 32},
        "course": {"target": "G2", "mode": "replace_value", "max_chars": 64},
        "teacher": {"target": "L2", "mode": "replace_value", "max_chars": 32},
        "class_name": {"target": "O2", "mode": "replace_value", "max_chars": 64},
        "student_id": {"column": "B", "mode": "text", "pattern": r"^\d{8,}$"},
        "regular_scores": {
            "columns": ["D", "E", "F", "G", "H", "I", "J", "K"],
            "mode": "decimal_half",
            "average_matches": "students.regular",
        },
        "theory_score": {"column": "M", "mode": "number"},
        "skill_score": {"column": "O", "mode": "number", "optional_when": "weights.skill == 0"},
        "formula_columns_with_skill": {"columns": ["L", "N", "P", "Q"], "mode": "formula"},
        "formula_columns_without_skill": {"columns": ["L", "N", "O"], "mode": "formula"},
    }
    fields = manifest.get("fields")
    if not isinstance(fields, dict) or set(fields) != set(expected_fields):
        raise ValueError("Legacy v1.0 fields must use the closed coordinate contract")
    for field_name, expected in expected_fields.items():
        if fields.get(field_name) != expected:
            raise ValueError(
                f"Legacy v1.0 field {field_name} contains named-range or coordinate metadata outside its contract"
            )
    validation = manifest.get("validation")
    if not isinstance(validation, dict) or validation.get("required_named_ranges") != []:
        raise ValueError("Legacy v1.0 validation.required_named_ranges must remain an empty list")


def validate_named_range_manifest_contract(manifest: dict[str, Any]) -> None:
    from named_range_contracts import (
        MANAGED_NAMES,
        NAMED_RANGE_CONTRACTS,
        NAMED_RANGE_MODE,
        V11_FIELD_CONTRACTS,
        V11_LAYOUT_CONTRACT,
        required_names,
        v11_variant_contracts,
    )

    expected_top_level = {
        "template",
        "generator",
        "structure",
        "anchors",
        "fields",
        "layout",
        "allowed_changes",
        "protected",
        "validation",
        "fingerprint",
    }
    keys = set(manifest) - {"_path"}
    if keys != expected_top_level:
        unknown = sorted(keys - expected_top_level)
        missing = sorted(expected_top_level - keys)
        detail = f"unknown keys {unknown}" if unknown else f"missing keys {missing}"
        raise ValueError(f"v1.1 manifest has an invalid closed contract: {detail}")

    anchors = manifest.get("anchors")
    if not isinstance(anchors, dict) or anchors.get("mode") != NAMED_RANGE_MODE or anchors.get("scope") != "workbook":
        raise ValueError("v1.1 manifest must declare anchors.mode=excel_named_range and workbook scope")
    if set(anchors) != {"mode", "scope", "required", "definitions", "variants"}:
        raise ValueError("v1.1 anchors must contain exactly mode, scope, required, definitions, and variants")
    if tuple(anchors.get("required", ())) != MANAGED_NAMES:
        raise ValueError("v1.1 manifest anchors.required must list the complete managed contract")
    definitions = anchors.get("definitions")
    if not isinstance(definitions, dict) or set(definitions) != set(NAMED_RANGE_CONTRACTS):
        raise ValueError("v1.1 manifest named-range definitions must exactly match the managed contract")
    for name, expected in NAMED_RANGE_CONTRACTS.items():
        if definitions.get(name) != expected:
            raise ValueError(f"v1.1 manifest definition mismatch for managed name {name}")
    variants = anchors.get("variants")
    expected_variants = v11_variant_contracts()
    if not isinstance(variants, dict) or set(variants) != set(expected_variants):
        raise ValueError("v1.1 manifest must declare with_skill and without_skill named-range variants")
    for variant in ("with_skill", "without_skill"):
        data = variants.get(variant)
        if not isinstance(data, dict) or set(data) != {"required", "forbidden"}:
            raise ValueError(f"v1.1 manifest is missing named-range variant {variant}")
        if data != expected_variants[variant]:
            raise ValueError(f"v1.1 manifest required names mismatch for {variant}")
    structure = manifest.get("structure")
    if not isinstance(structure, dict) or set(structure) != {"source"}:
        raise ValueError("v1.1 manifest structure may contain only the external-input source contract")
    layout = manifest.get("layout")
    if layout != V11_LAYOUT_CONTRACT:
        raise ValueError(
            "v1.1 manifest layout must map every output coordinate and exactly match the managed semantic layout contract"
        )
    fields = manifest.get("fields")
    if not isinstance(fields, dict) or set(fields) != set(V11_FIELD_CONTRACTS):
        raise ValueError("v1.1 manifest fields must exactly match the closed semantic field contract")
    for field_name, expected in V11_FIELD_CONTRACTS.items():
        if fields.get(field_name) != expected:
            raise ValueError(f"v1.1 manifest field contract mismatch for {field_name}")
    validation = manifest.get("validation", {})
    required = tuple(validation.get("required_named_ranges", ())) if isinstance(validation, dict) else ()
    if required != required_names("with_skill"):
        raise ValueError("v1.1 validation.required_named_ranges must list the complete managed contract")


def validate_manifest_contract(manifest: dict[str, Any]) -> str:
    ensure_supported_major(manifest)
    mode = anchor_mode(manifest)
    if mode == "legacy_coordinates":
        validate_legacy_manifest_contract(manifest)
    else:
        validate_named_range_manifest_contract(manifest)
    return mode


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def validate_template_package_identity(template: Path | str, manifest: dict[str, Any]) -> str:
    template_path = Path(template).expanduser().resolve()
    if not template_path.exists():
        raise ValueError(f"Template not found: {template_path}")
    expected = str(manifest.get("fingerprint", {}).get("sha256") or manifest.get("fingerprint", {}).get("value", "")).upper()
    if not re.fullmatch(r"[0-9A-F]{64}", expected):
        raise ValueError("Manifest fingerprint.sha256 must be a SHA-256 hex digest")
    actual = sha256_file(template_path)
    if actual != expected:
        raise ValueError(f"Template fingerprint mismatch: expected {expected}, got {actual}")
    return actual


def _known_template_manifest(template: Path) -> Path | None:
    template = template.resolve()
    for candidate, manifest in (
        (V10_TEMPLATE, V10_MANIFEST),
        (V11_TEMPLATE, V11_MANIFEST),
        (V10_COMPATIBILITY_TEMPLATE, V10_MANIFEST),
    ):
        if template == candidate.resolve():
            return manifest
    return None


def resolve_template_package(
    template_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
) -> TemplatePackage:
    explicit_template = bool(template_path and str(template_path).strip())
    explicit_manifest = bool(manifest_path and str(manifest_path).strip())
    template = Path(template_path).expanduser().resolve() if explicit_template else None
    if explicit_manifest:
        selected_manifest = Path(manifest_path).expanduser().resolve()
    elif template is not None:
        selected_manifest = _known_template_manifest(template)
        if selected_manifest is None:
            raise ValueError("Custom template requires a matching --manifest")
    else:
        selected_manifest = DEFAULT_MANIFEST.resolve()
    manifest = load_manifest(selected_manifest)
    mode = validate_manifest_contract(manifest)
    resolved_template = template or manifest_template_path(manifest)
    if not resolved_template.exists():
        raise ValueError(f"Template not found: {resolved_template}")
    if explicit_template and not explicit_manifest and _known_template_manifest(resolved_template) is None:
        raise ValueError("Custom template requires a matching --manifest")
    return TemplatePackage(resolved_template, selected_manifest, manifest, mode)


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
    version = manifest.get("template", {}).get("version", "")
    major, minor, _ = parse_template_version(version)
    if major != SUPPORTED_TEMPLATE_MAJOR:
        raise ValueError(
            f"Unsupported template major version {major}; supported major is {SUPPORTED_TEMPLATE_MAJOR}"
        )
    if minor not in SUPPORTED_TEMPLATE_MINORS:
        raise ValueError(
            f"Unsupported template minor version {minor}; supported minors are {sorted(SUPPORTED_TEMPLATE_MINORS)}"
        )
    declared = manifest.get("generator", {}).get("supported_major")
    if declared is None:
        raise ValueError("Manifest must declare generator.supported_major")
    try:
        declared_major = int(declared)
    except (ValueError, TypeError) as exc:
        raise ValueError("Manifest generator.supported_major must be an integer") from exc
    if declared_major != SUPPORTED_TEMPLATE_MAJOR:
        raise ValueError(
            f"Manifest generator.supported_major must remain {SUPPORTED_TEMPLATE_MAJOR}; it does not define support"
        )


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
