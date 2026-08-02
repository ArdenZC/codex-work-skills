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
    template = manifest.get("template")
    if not isinstance(template, dict):
        raise ValueError("Legacy v1.0 manifest must declare a template contract")
    template_keys = set(template)
    if template_keys not in ({"id", "name", "version", "format", "file"}, {"id", "name", "version", "format", "file", "compatibility_entries"}):
        raise ValueError("Legacy v1.0 template has an invalid closed contract")
    if template.get("id") != "course-gradebook" or template.get("format") != "xls":
        raise ValueError("Legacy v1.0 template id and format are protected")
    if not str(template.get("file") or "").strip():
        raise ValueError("Legacy v1.0 template.file is required")
    generator = manifest.get("generator")
    if generator != {"version": "1.0.0", "supported_major": 1}:
        raise ValueError("Legacy v1.0 generator contract is protected")
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
    canonical_manifest = load_manifest(V10_MANIFEST) if Path(manifest.get("_path", "")).resolve() != V10_MANIFEST.resolve() else None
    if canonical_manifest is not None:
        for section in ("structure", "fields", "allowed_changes", "protected", "validation"):
            if manifest.get(section) != canonical_manifest.get(section):
                raise ValueError(f"Legacy v1.0 {section} contract differs from the canonical baseline")


def validate_named_range_manifest_contract(manifest: dict[str, Any]) -> None:
    from named_range_contracts import (
        MANAGED_NAMES,
        NAMED_RANGE_CONTRACTS,
        NAMED_RANGE_MODE,
        V11_ALLOWED_CHANGES,
        V11_FIELD_CONTRACTS,
        V11_GENERATOR_CONTRACT,
        V11_LAYOUT_CONTRACT,
        V11_PROTECTED,
        V11_SOURCE_CONTRACT,
        V11_TEMPLATE_KEYS,
        V11_TEMPLATE_STATIC,
        V11_VALIDATION_CONTRACT,
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

    template = manifest.get("template")
    if not isinstance(template, dict) or set(template) != set(V11_TEMPLATE_KEYS):
        raise ValueError("v1.1 template must contain exactly the protected template keys")
    for key, expected in V11_TEMPLATE_STATIC.items():
        if template.get(key) != expected:
            raise ValueError(f"v1.1 template.{key} differs from the protected contract")
    if not str(template.get("file") or "").strip():
        raise ValueError("v1.1 template.file is required")
    generator = manifest.get("generator")
    if not isinstance(generator, dict) or set(generator) != set(V11_GENERATOR_CONTRACT):
        raise ValueError("v1.1 generator must contain exactly version and supported_major")
    if generator.get("supported_major") != V11_GENERATOR_CONTRACT["supported_major"]:
        raise ValueError("v1.1 generator.supported_major is protected")
    generator_version = str(generator.get("version") or "")
    template_version = str(template.get("version") or "")
    if not re.fullmatch(r"1\.1\.[0-9]+", generator_version, flags=re.ASCII):
        raise ValueError("v1.1 generator.version must be an ASCII 1.1.x semantic version")
    if generator_version.split(".")[:2] != template_version.split(".")[:2]:
        raise ValueError("v1.1 generator.version must use the same major and minor as template.version")

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
    if not isinstance(structure, dict) or structure != {"source": V11_SOURCE_CONTRACT}:
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
    if manifest.get("allowed_changes") != V11_ALLOWED_CHANGES:
        raise ValueError("v1.1 allowed_changes is protected and must use the closed contract")
    if manifest.get("protected") != V11_PROTECTED:
        raise ValueError("v1.1 protected is protected and must use the closed contract")
    validation = manifest.get("validation")
    if validation != V11_VALIDATION_CONTRACT:
        raise ValueError("v1.1 validation must exactly match the closed generator contract")


def validate_manifest_contract(manifest: dict[str, Any]) -> str:
    ensure_supported_major(manifest)
    validate_fingerprint_contract(manifest)
    mode = anchor_mode(manifest)
    if mode == "legacy_coordinates":
        validate_legacy_manifest_contract(manifest)
    else:
        validate_named_range_manifest_contract(manifest)
        validate_template_baseline_references(manifest)
    return mode


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _path_key(path: Path | str) -> str:
    return str(Path(path).expanduser().resolve()).casefold()


def validate_fingerprint_contract(manifest: dict[str, Any]) -> tuple[str, str]:
    fingerprint = manifest.get("fingerprint")
    if not isinstance(fingerprint, dict) or set(fingerprint) != {"algorithm", "sha256", "value"}:
        raise ValueError("Manifest fingerprint must contain exactly algorithm, sha256, and value")
    if str(fingerprint.get("algorithm", "")).lower() != "sha256":
        raise ValueError("Manifest fingerprint.algorithm must be sha256")
    sha_value = str(fingerprint.get("sha256") or "").upper()
    value = str(fingerprint.get("value") or "").upper()
    if not re.fullmatch(r"[0-9A-F]{64}", sha_value) or not re.fullmatch(r"[0-9A-F]{64}", value):
        raise ValueError("Manifest fingerprint.sha256 and fingerprint.value must be 64-digit hexadecimal SHA-256 values")
    if sha_value != value:
        raise ValueError("Manifest fingerprint.sha256 and fingerprint.value must match")
    return sha_value, value


def canonical_template_for_mode(mode: str) -> Path:
    if mode == "legacy_coordinates":
        return V10_TEMPLATE.resolve()
    if mode == "excel_named_range":
        return V11_TEMPLATE.resolve()
    raise ValueError(f"Unsupported template anchor mode: {mode}")


def validate_canonical_baselines(require_v11: bool = False) -> None:
    required = [(V10_TEMPLATE, V10_MANIFEST)]
    if require_v11:
        required.append((V11_TEMPLATE, V11_MANIFEST))
    for template, manifest_path in required:
        if not template.is_file() or not manifest_path.is_file():
            raise ValueError(f"Canonical template baseline is missing: {template} / {manifest_path}")
        manifest = load_manifest(manifest_path)
        expected, _ = validate_fingerprint_contract(manifest)
        actual = sha256_file(template)
        if actual != expected:
            raise ValueError(f"Canonical template baseline fingerprint mismatch: {template}")


def validate_template_baseline_references(manifest: dict[str, Any]) -> None:
    """Ensure a patch manifest can reference only the fixed v1.0 baseline."""
    validate_canonical_baselines(require_v11=False)
    template = manifest["template"]
    if "_path" not in manifest:
        # Pure contract callers may validate an in-memory manifest. Filesystem
        # reference resolution is performed by load_manifest-based entrypoints.
        if not str(template.get("base_manifest") or "") or not str(template.get("base_template") or ""):
            raise ValueError("v1.1 template.base_manifest and template.base_template are required")
        return
    manifest_path = Path(manifest["_path"]).resolve()
    base_manifest_value = str(template.get("base_manifest") or "")
    base_template_value = str(template.get("base_template") or "")
    if not base_manifest_value or not base_template_value:
        raise ValueError("v1.1 template.base_manifest and template.base_template are required")
    base_manifest = (manifest_path.parent / base_manifest_value).resolve()
    base_template = (manifest_path.parent / base_template_value).resolve()
    if _path_key(base_manifest) == _path_key(manifest_path) or _path_key(base_template) == _path_key(manifest_template_path(manifest)):
        raise ValueError("v1.1 template baseline references must not point to the selected manifest or template")
    if not base_manifest.is_file() or not base_template.is_file():
        raise ValueError("v1.1 template baseline references must point to existing files")
    allowed_base_root = V11_PACKAGE_DIR.parent.resolve() if manifest_path == V11_MANIFEST.resolve() else manifest_path.parent
    for reference in (base_manifest, base_template):
        reference_key = _path_key(reference)
        root_key = _path_key(allowed_base_root).rstrip("\\/")
        if reference_key != _path_key(V10_TEMPLATE) and not (
            reference_key == _path_key(V10_MANIFEST)
            or reference_key.startswith(root_key + "\\")
            or reference_key.startswith(root_key + "/")
        ):
            raise ValueError("v1.1 template baseline references must remain inside the approved template package root")
    if sha256_file(base_template) != sha256_file(V10_TEMPLATE):
        raise ValueError("v1.1 template.base_template must point to the canonical v1.0 template")
    referenced_manifest = load_manifest(base_manifest)
    validate_legacy_manifest_contract(referenced_manifest)
    expected_base_manifest = load_manifest(V10_MANIFEST)
    for section in ("template", "generator", "structure", "fields", "allowed_changes", "protected", "validation", "fingerprint"):
        if referenced_manifest.get(section) != expected_base_manifest.get(section):
            raise ValueError("v1.1 template.base_manifest must point to the canonical v1.0 manifest")


def validate_output_paths(
    output_dir: Path | str,
    final_paths: list[Path | str],
    *,
    source_paths: list[Path | str] | None = None,
    template_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
    schema_path: Path | str | None = None,
    qa_paths: list[Path | str] | None = None,
) -> Path:
    """Reject output collisions before creating or modifying any output."""
    out_dir = Path(output_dir).expanduser().resolve()
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(f"Output directory is not a directory: {out_dir}")
    package_dirs = {
        V10_PACKAGE_DIR.resolve(),
        V11_PACKAGE_DIR.resolve(),
        V10_COMPATIBILITY_TEMPLATE.resolve().parent,
    }
    out_key = _path_key(out_dir)
    for package_dir in package_dirs:
        package_key = _path_key(package_dir)
        if out_key == package_key or out_key.startswith(package_key + "\\") or out_key.startswith(package_key + "/"):
            raise ValueError(f"Output directory must not be inside a template package directory: {out_dir}")

    forbidden = {
        _path_key(path)
        for path in (source_paths or [])
        + ([template_path] if template_path else [])
        + ([manifest_path] if manifest_path else [])
        + ([schema_path] if schema_path else [])
        + [V10_TEMPLATE, V11_TEMPLATE, V10_COMPATIBILITY_TEMPLATE]
    }
    normalized_final_paths: list[Path] = []
    for final in final_paths:
        target = Path(final).expanduser()
        if not target.is_absolute():
            target = out_dir / target
        target = target.resolve()
        normalized_final_paths.append(target)
        try:
            target.relative_to(out_dir)
        except ValueError as exc:
            raise ValueError(f"Output file must be inside --output-dir: {target}") from exc
        if target.exists() and target.is_dir():
            raise ValueError(f"Output file path is a directory: {target}")
        if target.suffix.lower() != ".xls":
            raise ValueError(f"Output file must use the .xls extension: {target}")
        if _path_key(target) in forbidden:
            if source_paths and _path_key(target) in {_path_key(path) for path in source_paths}:
                raise ValueError("Output file must not overwrite the source workbook.")
            if template_path and _path_key(target) == _path_key(template_path):
                raise ValueError("Output file must not overwrite the template file.")
            raise ValueError("Output file must not overwrite an input or template package file.")
    final_keys = [_path_key(path) for path in normalized_final_paths]
    if len(final_keys) != len(set(final_keys)):
        raise ValueError("Output file paths must be unique.")
    final_key_set = set(final_keys)
    for qa in qa_paths or []:
        qa_path = Path(qa).expanduser()
        if not qa_path.is_absolute():
            qa_path = out_dir / qa_path
        qa_path = qa_path.resolve()
        if qa_path.exists() and qa_path.is_dir():
            raise ValueError(f"QA report path is a directory: {qa_path}")
        if _path_key(qa_path) in final_key_set:
            raise ValueError("QA report must not overwrite a generated XLS output.")
        if _path_key(qa_path) in forbidden:
            raise ValueError("QA report must not overwrite an input or template package file.")
    qa_keys = [_path_key(path) for path in qa_paths or []]
    if len(qa_keys) != len(set(qa_keys)):
        raise ValueError("QA report paths must be unique.")
    return out_dir


def validate_template_package_identity(template: Path | str, manifest: dict[str, Any]) -> str:
    template_path = Path(template).expanduser().resolve()
    if not template_path.exists():
        raise ValueError(f"Template not found: {template_path}")
    expected, _ = validate_fingerprint_contract(manifest)
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
    declared_template = manifest_template_path(manifest)
    if explicit_template and not declared_template.is_file():
        raise ValueError(f"Canonical template not found: {declared_template}")
    resolved_template = template or declared_template
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
