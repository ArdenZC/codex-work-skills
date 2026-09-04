from __future__ import annotations

import json
import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from semantic_bookmarks import (
    IMPLEMENTATION_STAGES,
    LEGACY_FIXED_ALLOWED_KEYS,
    LEGACY_IMPLEMENTATION_ALLOWED_KEYS,
    LEGACY_REFLECTION_ALLOWED_KEYS,
    SEMANTIC_FIELD_NAMES,
    SEMANTIC_FIELD_CONTRACTS,
    SEMANTIC_FIXED_ALLOWED_KEYS,
    SEMANTIC_IMPLEMENTATION_ALLOWED_KEYS,
    SEMANTIC_REFLECTION_ALLOWED_KEYS,
    SEMANTIC_STAGE_ALLOWED_KEYS,
    implementation_bookmark_groups,
    managed_bookmark_names,
    reflection_bookmark_names,
)
from content_contract import (
    COMPATIBLE_CONTENT_CONTRACT_VERSIONS,
    CONTENT_CONTRACT_VERSION,
    DELIVERY_MODES,
    LESSON_TYPES,
    REFERENCE_SOURCE_KINDS,
    REFERENCE_TYPES,
    PRACTICE_TASK_GRANULARITIES,
    CAPABILITY_STAGES,
    EVALUATION_CRITERIA,
    EVALUATION_SCORE_MAX,
    EVALUATION_SCORE_MIN,
    EVALUATION_SCORE_STEP,
    IMPLEMENTATION_STAGE_IDS,
    IN_CLASS_STAGE_IDS,
    format_reference,
    lesson_references,
    reference_identity,
    reference_looks_like_placeholder,
    reference_looks_like_resource_only,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "manifest.yaml"
V10_MANIFEST = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "manifest.yaml"
V11_MANIFEST = DEFAULT_MANIFEST
V111_MANIFEST = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.1" / "manifest.yaml"
V10_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx"
V11_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.2" / "template.docx"
V111_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.1" / "template.docx"
LEGACY_TEMPLATE = SKILL_DIR / "assets" / "lesson-plan-template.docx"
DEFAULT_SCHEMA = SKILL_DIR / "schemas" / "lesson-plan-input.schema.json"
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
LEGACY_ANCHOR_MODE = "legacy_coordinates"
SEMANTIC_ANCHOR_MODE = "word_bookmark"
EVALUATION_MAX_POINTS = [3, 3, 4, 5, 5, 5, 5, 10, 10, 10, 25, 10, 5]
MINUTES_PER_LESSON_HOUR = 45
MAX_HOURS_TEXT_LENGTH = 12
REFERENCE_SPECIFIC_PATTERN = re.compile(
    r"(?:isbn\s*[-:]?\s*[0-9x-]+|gb\s*[/-]?\s*t|标准编号|文件编号|出版社|作者|"
    r"(?:19|20)\d{2}\s*年?|第\s*[一二三四五六七八九十百0-9]+\s*版|版次)",
    re.IGNORECASE,
)
REFERENCE_TITLE_PATTERN = re.compile(r"《[^》]{2,}》")
REFERENCE_EVIDENCE_URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
REFERENCE_EVIDENCE_LOCATOR_PATTERN = re.compile(
    r"(?:官方|政府|教育部|国家卫生健康|行业协会).*(?:官网|章节|条款|第[一二三四五六七八九十百0-9]+[章节条]|页|文号|检索|路径)",
)
REPOSITORY_ROOT = SKILL_DIR.parents[1]
PRACTICE_CONTRACT_SCHEMA = REPOSITORY_ROOT / "schemas" / "shared" / "practice-task-contract.schema.json"
PRACTICE_CONTRACT_SCHEMA_ID = "https://codex-work-skills.local/schemas/shared/practice-task-contract-v1.json"


def require_meaningful_text(value: Any, field_name: str, minimum: int = 1) -> str:
    """Reject whitespace-only values after the same normalization used by QA."""

    normalized = unicodedata.normalize("NFKC", str(value))
    compact = re.sub(r"\s+", "", normalized).strip()
    if len(compact) < minimum:
        raise ValueError(f"{field_name} must contain meaningful text; received {value!r}")
    return normalized.strip()


def load_manifest(path: Path | str = DEFAULT_MANIFEST) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    with manifest_path.open("r", encoding="utf-8") as stream:
        manifest = yaml.safe_load(stream) or {}
    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest must be a YAML object: {manifest_path}")
    manifest["_path"] = str(manifest_path)
    validate_semantic_manifest_contract(manifest)
    return manifest


def manifest_template_path(manifest: dict[str, Any]) -> Path:
    manifest_path = Path(manifest["_path"])
    file_value = manifest.get("template", {}).get("file")
    if not file_value:
        raise ValueError("Manifest is missing template.file")
    return (manifest_path.parent / str(file_value)).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _known_template_version(path: Path) -> str | None:
    path = path.expanduser().resolve()
    known = (
        (V11_TEMPLATE, "1.1.2"),
        (V111_TEMPLATE, "1.1.1"),
        (V10_TEMPLATE, "1.0.0"),
        (LEGACY_TEMPLATE, "1.0.0"),
        (SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "template.docx", "1.1.0"),
    )
    for candidate, version in known:
        if path == candidate:
            return version
    if not path.exists():
        return None
    actual = _sha256(path)
    for candidate, version in known:
        if candidate.exists() and actual == _sha256(candidate):
            return version
    return None


def _exact_template_version(path: Path) -> str | None:
    path = path.expanduser().resolve()
    for candidate, version in (
        (V11_TEMPLATE, "1.1.2"),
        (V111_TEMPLATE, "1.1.1"),
        (SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "template.docx", "1.1.0"),
        (V10_TEMPLATE, "1.0.0"),
        (LEGACY_TEMPLATE, "1.0.0"),
    ):
        if path == candidate.resolve():
            return version
    return None


def _manifest_fingerprint(manifest: dict[str, Any]) -> str:
    fingerprint = manifest.get("fingerprint")
    value = fingerprint.get("sha256") if isinstance(fingerprint, dict) else None
    if value is None and isinstance(fingerprint, dict):
        value = fingerprint.get("value")
    expected = str(value or "").upper()
    if re.fullmatch(r"[0-9A-F]{64}", expected) is None:
        raise ValueError("Manifest fingerprint.sha256 must be a 64-character SHA-256 value")
    return expected


def _validate_template_fingerprint(template: Path, manifest: dict[str, Any]) -> None:
    expected = _manifest_fingerprint(manifest)
    actual = _sha256(template)
    if actual != expected:
        raise ValueError(f"Template fingerprint mismatch: expected {expected}, got {actual}")


def validate_template_fingerprint(template: Path, manifest: dict[str, Any]) -> None:
    _validate_template_fingerprint(template, manifest)


def _validate_package_identity(
    template: Path,
    manifest: dict[str, Any],
    *,
    explicit_manifest: bool,
    explicit_template: bool = False,
    check_fingerprint: bool = True,
) -> None:
    template_info = manifest.get("template", {})
    if template_info.get("id") != "lesson-plan":
        raise ValueError("Manifest template.id must be lesson-plan")
    if template_info.get("format") != "docx":
        raise ValueError("Manifest template.format must be docx")
    version = str(template_info.get("version", ""))
    if not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")

    exact_version = _exact_template_version(template)
    if exact_version is not None and exact_version != version:
        raise ValueError(
            f"Template/manifest mismatch: {template.name} is v{exact_version}, manifest declares v{version}"
        )

    known_version = _known_template_version(template)
    if known_version is not None and (
        (not explicit_manifest and known_version != version)
        or (explicit_manifest and known_version.split(".")[:2] != version.split(".")[:2])
    ):
        raise ValueError(
            f"Template/manifest mismatch: {template.name} is v{known_version}, manifest declares v{version}"
        )

    if check_fingerprint:
        _validate_template_fingerprint(template, manifest)


def validate_template_package_identity(
    template: Path,
    manifest: dict[str, Any],
    *,
    explicit_manifest: bool,
    explicit_template: bool = False,
    check_fingerprint: bool = True,
) -> None:
    _validate_package_identity(
        template,
        manifest,
        explicit_manifest=explicit_manifest,
        explicit_template=explicit_template,
        check_fingerprint=check_fingerprint,
    )


def resolve_template_package(
    template_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """Resolve a lesson-plan template and manifest as one versioned package.

    Canonical v1.0/v1.1 templates and the published v1.0 compatibility entry can
    be selected by template alone. Arbitrary custom DOCX files require an
    explicit matching manifest so semantic mode is never guessed.
    """
    template_value = str(template_path) if template_path else ""
    manifest_value = str(manifest_path) if manifest_path else ""
    if not template_value and not manifest_value:
        resolved_manifest = V11_MANIFEST.resolve()
        manifest = load_manifest(resolved_manifest)
        template = manifest_template_path(manifest)
        validate_template_package_identity(template, manifest, explicit_manifest=False)
        return template, resolved_manifest, manifest

    if manifest_value:
        resolved_manifest = Path(manifest_value).expanduser().resolve()
        manifest = load_manifest(resolved_manifest)
        ensure_supported_major(manifest)
    else:
        resolved_manifest = None
        manifest = None

    if template_value:
        template = Path(template_value).expanduser().resolve()
    elif manifest is not None:
        template = manifest_template_path(manifest)
    else:  # pragma: no cover - guarded by the first branch
        raise ValueError("Unable to resolve lesson-plan template package")

    if manifest is None:
        known_version = _known_template_version(template)
        if known_version == "1.1.2":
            resolved_manifest = V11_MANIFEST.resolve()
        elif known_version == "1.1.1":
            resolved_manifest = V111_MANIFEST.resolve()
        elif known_version == "1.1.0":
            resolved_manifest = (SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "manifest.yaml").resolve()
        elif known_version == "1.0.0":
            resolved_manifest = V10_MANIFEST.resolve()
        elif template.parent.name in {"v1.0.0", "v1.1.0", "v1.1.1", "v1.1.2"} and (template.parent / "manifest.yaml").exists():
            resolved_manifest = (template.parent / "manifest.yaml").resolve()
        else:
            raise ValueError("Custom template requires a matching --manifest.")
        manifest = load_manifest(resolved_manifest)
    validate_template_package_identity(
        template,
        manifest,
        explicit_manifest=bool(manifest_value),
        explicit_template=bool(template_value),
    )
    return template, resolved_manifest, manifest


def is_semantic_manifest(manifest: dict[str, Any]) -> bool:
    """Return whether the manifest uses the v1.1 semantic bookmark contract."""
    return anchor_mode(manifest) == SEMANTIC_ANCHOR_MODE


def parse_template_version(manifest: dict[str, Any]) -> tuple[int, int, int]:
    template_info = manifest.get("template")
    version = template_info.get("version") if isinstance(template_info, dict) else None
    if not isinstance(version, str) or SEMVER_PATTERN.fullmatch(version) is None:
        raise ValueError(
            f"Invalid template.version {version!r}; expected MAJOR.MINOR.PATCH using ASCII digits without leading zeros."
        )
    return tuple(int(part) for part in version.split("."))


def expected_anchor_mode(manifest: dict[str, Any]) -> str:
    major, minor, patch = parse_template_version(manifest)
    if major != 1:
        raise ValueError(
            f"Unsupported template major version {major}.{minor}.{patch}; generator supports major 1."
        )
    if minor == 0:
        return LEGACY_ANCHOR_MODE
    if minor == 1:
        return SEMANTIC_ANCHOR_MODE
    raise ValueError(f"Unsupported lesson-plan template minor version {major}.{minor}.x.")


def anchor_mode(manifest: dict[str, Any]) -> str:
    expected = expected_anchor_mode(manifest)
    anchors = manifest.get("anchors")
    declared = anchors.get("mode") if isinstance(anchors, dict) else None
    version = manifest["template"]["version"]
    if expected == SEMANTIC_ANCHOR_MODE and declared != SEMANTIC_ANCHOR_MODE:
        actual = "<missing>" if declared is None else str(declared)
        raise ValueError(
            f"Semantic anchor mode mismatch for template.version {version}: "
            f"expected anchors.mode={SEMANTIC_ANCHOR_MODE}; got {actual}."
        )
    if expected == LEGACY_ANCHOR_MODE:
        if declared not in {None, LEGACY_ANCHOR_MODE}:
            raise ValueError(
                f"Legacy anchor mode mismatch for template.version {version}: "
                f"expected anchors.mode={LEGACY_ANCHOR_MODE} or no semantic anchors; got {declared}."
            )
        validate_legacy_manifest_contract(manifest)
    return expected


def _required_manifest_mapping(manifest: dict[str, Any], path: str) -> dict[str, Any]:
    current: Any = manifest
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            raise ValueError(f"Semantic manifest is missing {path}.")
        current = current[component]
    if not isinstance(current, dict):
        raise ValueError(f"Semantic manifest {path} must be a mapping.")
    return current


def _required_manifest_value(mapping: dict[str, Any], path: str, key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Semantic manifest is missing {path}.{key}.")
    return mapping[key]


def _reject_semantic_keys(mapping: dict[str, Any], path: str, allowed: set[str] | frozenset[str]) -> None:
    for key in mapping:
        if key not in allowed:
            raise ValueError(f"Semantic manifest {path} contains unsupported key {key}.")


def validate_legacy_manifest_contract(manifest: dict[str, Any]) -> None:
    major, minor, patch = parse_template_version(manifest)
    if (major, minor) != (1, 0):
        return
    version = manifest["template"]["version"]

    anchors = manifest.get("anchors")
    if anchors is not None:
        if not isinstance(anchors, dict):
            raise ValueError(f"Legacy manifest anchors must be a mapping for template.version {version}.")
        for key in anchors:
            if key != "mode":
                raise ValueError(
                    f"Legacy manifest anchors.{key} is not allowed for template.version {version}."
                )
        if anchors.get("mode") not in {None, LEGACY_ANCHOR_MODE}:
            raise ValueError(
                f"Legacy manifest anchors.mode must be {LEGACY_ANCHOR_MODE} for template.version {version}."
            )

    fields = _required_manifest_mapping(manifest, "fields")
    allowed_fields = set(LEGACY_FIXED_ALLOWED_KEYS) | {"implementation", "reflection"}
    for key in fields:
        if key not in allowed_fields:
            raise ValueError(f"Legacy manifest fields.{key} is not allowed for template.version {version}.")

    for name, allowed in LEGACY_FIXED_ALLOWED_KEYS.items():
        spec = _required_manifest_mapping(manifest, f"fields.{name}")
        for key in spec:
            if key not in allowed:
                raise ValueError(
                    f"Legacy manifest fields.{name}.{key} is not allowed for template.version {version}."
                )

    implementation = _required_manifest_mapping(manifest, "fields.implementation")
    for key in implementation:
        if key not in LEGACY_IMPLEMENTATION_ALLOWED_KEYS:
            raise ValueError(
                f"Legacy manifest fields.implementation.{key} is not allowed for template.version {version}."
            )
    if str(_required_manifest_value(implementation, "fields.implementation", "mode")) != "row_cells":
        raise ValueError(
            f"Legacy manifest fields.implementation.mode must be row_cells for template.version {version}."
        )

    reflection = _required_manifest_mapping(manifest, "fields.reflection")
    for key in reflection:
        if key not in LEGACY_REFLECTION_ALLOWED_KEYS:
            raise ValueError(
                f"Legacy manifest fields.reflection.{key} is not allowed for template.version {version}."
            )
    if str(_required_manifest_value(reflection, "fields.reflection", "mode")) != "row_cells":
        raise ValueError(
            f"Legacy manifest fields.reflection.mode must be row_cells for template.version {version}."
        )

    evaluation = _required_manifest_mapping(manifest, "fields.evaluation")
    if str(_required_manifest_value(evaluation, "fields.evaluation", "mode")) != "nested_table":
        raise ValueError(
            f"Legacy manifest fields.evaluation.mode must be nested_table for template.version {version}."
        )
    if str(_required_manifest_value(evaluation, "fields.evaluation", "target")) != "nested_table":
        raise ValueError(
            f"Legacy manifest fields.evaluation.target must be nested_table for template.version {version}."
        )


def validate_semantic_manifest_contract(manifest: dict[str, Any]) -> None:
    """Require every v1.1 semantic contract field without applying defaults."""
    if anchor_mode(manifest) != SEMANTIC_ANCHOR_MODE:
        return

    anchors = _required_manifest_mapping(manifest, "anchors")
    _reject_semantic_keys(anchors, "anchors", {"mode", "required", "containers"})
    mode = _required_manifest_value(anchors, "anchors", "mode")
    if str(mode) != "word_bookmark":
        raise ValueError("Semantic manifest anchors.mode must be word_bookmark.")

    expected_names = managed_bookmark_names()
    required = _required_manifest_value(anchors, "anchors", "required")
    if not isinstance(required, list):
        raise ValueError("Semantic manifest anchors.required must be a list.")
    if [str(value) for value in required] != expected_names:
        raise ValueError("Semantic manifest anchors.required does not match the managed definition.")

    expected_containers = {
        contract["bookmark"]: contract["container"]
        for contract in SEMANTIC_FIELD_CONTRACTS.values()
    }
    expected_containers.update(
        {name: "cell" for name in expected_names if name not in expected_containers}
    )
    containers = _required_manifest_value(anchors, "anchors", "containers")
    if not isinstance(containers, dict):
        raise ValueError("Semantic manifest anchors.containers must be a mapping.")
    if {str(name): str(value) for name, value in containers.items()} != expected_containers:
        raise ValueError("Semantic manifest anchors.containers does not match the managed definition.")

    fields = _required_manifest_mapping(manifest, "fields")
    _reject_semantic_keys(fields, "fields", SEMANTIC_FIELD_NAMES)
    for field, contract in SEMANTIC_FIELD_CONTRACTS.items():
        spec = _required_manifest_mapping(manifest, f"fields.{field}")
        _reject_semantic_keys(spec, f"fields.{field}", SEMANTIC_FIXED_ALLOWED_KEYS[field])
        for key in ("target", "bookmark", "mode"):
            value = _required_manifest_value(spec, f"fields.{field}", key)
            expected = contract[key]
            if str(value) != expected:
                raise ValueError(f"Semantic manifest fields.{field}.{key} must be {expected}; got {value}.")

    implementation = _required_manifest_mapping(manifest, "fields.implementation")
    _reject_semantic_keys(implementation, "fields.implementation", SEMANTIC_IMPLEMENTATION_ALLOWED_KEYS)
    implementation_mode = _required_manifest_value(implementation, "fields.implementation", "mode")
    if str(implementation_mode) != "anchored_cells":
        raise ValueError("Semantic manifest fields.implementation.mode must be anchored_cells.")
    stages = _required_manifest_value(implementation, "fields.implementation", "stages")
    if not isinstance(stages, list):
        raise ValueError("Semantic manifest fields.implementation.stages must be a list.")
    expected_stage_groups = implementation_bookmark_groups()
    if len(stages) != len(IMPLEMENTATION_STAGES):
        raise ValueError(
            "Semantic manifest fields.implementation.stages count does not match the managed definition."
        )
    for index, (stage, expected, expected_bookmarks) in enumerate(
        zip(stages, IMPLEMENTATION_STAGES, expected_stage_groups)
    ):
        path = f"fields.implementation.stages[{index}]"
        if not isinstance(stage, dict):
            raise ValueError(f"Semantic manifest {path} must be a mapping.")
        _reject_semantic_keys(stage, path, SEMANTIC_STAGE_ALLOWED_KEYS)
        stage_id, stage_code, _row = expected
        stage_id_value = _required_manifest_value(stage, path, "id")
        stage_code_value = _required_manifest_value(stage, path, "code")
        bookmarks = _required_manifest_value(stage, path, "bookmarks")
        if str(stage_id_value) != stage_id:
            raise ValueError(
                f"Semantic manifest stage id mismatch at index {index}: expected {stage_id}, got {stage_id_value}."
            )
        if str(stage_code_value) != stage_code:
            raise ValueError(
                f"Semantic manifest stage code mismatch at index {index}: expected {stage_code}, got {stage_code_value}."
            )
        if not isinstance(bookmarks, list):
            raise ValueError(f"Semantic manifest {path}.bookmarks must be a list.")
        if [str(value) for value in bookmarks] != expected_bookmarks:
            raise ValueError(f"Semantic manifest {path}.bookmarks does not match the managed definition.")

    reflection = _required_manifest_mapping(manifest, "fields.reflection")
    _reject_semantic_keys(reflection, "fields.reflection", SEMANTIC_REFLECTION_ALLOWED_KEYS)
    reflection_mode = _required_manifest_value(reflection, "fields.reflection", "mode")
    if str(reflection_mode) != "anchored_cells":
        raise ValueError("Semantic manifest fields.reflection.mode must be anchored_cells.")
    reflection_names = _required_manifest_value(reflection, "fields.reflection", "bookmarks")
    if not isinstance(reflection_names, list):
        raise ValueError("Semantic manifest fields.reflection.bookmarks must be a list.")
    if [str(value) for value in reflection_names] != reflection_bookmark_names():
        raise ValueError("Semantic manifest fields.reflection.bookmarks does not match the managed definition.")

def base_manifest_path(manifest: dict[str, Any]) -> Path | None:
    """Resolve the legacy layout manifest used as the v1.1 protected baseline."""
    if not is_semantic_manifest(manifest):
        return None
    value = manifest.get("template", {}).get("base_manifest")
    if not value:
        raise ValueError("Semantic template manifest is missing template.base_manifest")
    return (Path(manifest["_path"]).parent / str(value)).resolve()


def layout_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the coordinate manifest used only for protected layout comparisons."""
    reference = base_manifest_path(manifest)
    return load_manifest(reference) if reference is not None else manifest


def required_bookmarks(manifest: dict[str, Any]) -> list[str]:
    if anchor_mode(manifest) != SEMANTIC_ANCHOR_MODE:
        return []
    validate_semantic_manifest_contract(manifest)
    expected = managed_bookmark_names()
    values = manifest["anchors"]["required"]
    declared = [str(value) for value in values]
    if declared != expected:
        raise ValueError("Semantic manifest anchors.required does not match the managed bookmark definition")
    return expected


def bookmark_containers(manifest: dict[str, Any]) -> dict[str, str]:
    if anchor_mode(manifest) != SEMANTIC_ANCHOR_MODE:
        return {}
    validate_semantic_manifest_contract(manifest)
    expected = {
        contract["bookmark"]: contract["container"]
        for contract in SEMANTIC_FIELD_CONTRACTS.values()
    }
    expected.update({name: "cell" for name in managed_bookmark_names() if name not in expected})
    values = manifest["anchors"]["containers"]
    declared = {str(name): str(container) for name, container in values.items()}
    if declared != expected:
        raise ValueError("Semantic manifest anchors.containers does not match the managed bookmark definition")
    return expected


def field_bookmark(manifest: dict[str, Any], name: str) -> str:
    spec = field_spec(manifest, name)
    contract = SEMANTIC_FIELD_CONTRACTS.get(name)
    if contract is None:
        raise ValueError(f"Semantic manifest field {name} is missing bookmark")
    expected = contract["bookmark"]
    if anchor_mode(manifest) == SEMANTIC_ANCHOR_MODE:
        validate_semantic_manifest_contract(manifest)
    if "bookmark" not in spec:
        raise ValueError(f"Semantic manifest is missing fields.{name}.bookmark.")
    value = spec["bookmark"]
    if str(value) != expected:
        raise ValueError(f"Semantic manifest field {name} bookmark does not match the managed definition")
    return expected


def implementation_bookmarks(manifest: dict[str, Any]) -> list[list[str]]:
    spec = field_spec(manifest, "implementation")
    if anchor_mode(manifest) == SEMANTIC_ANCHOR_MODE:
        validate_semantic_manifest_contract(manifest)
    if spec.get("mode") != "anchored_cells":
        return []
    expected = implementation_bookmark_groups()
    stages = spec["stages"]
    result = []
    for index, stage in enumerate(stages, 1):
        if not isinstance(stage, dict) or not isinstance(stage["bookmarks"], list):
            raise ValueError(f"Semantic implementation stage {index} is missing bookmarks")
        result.append([str(value) for value in stage["bookmarks"]])
    if result != expected:
        raise ValueError("Semantic implementation bookmarks do not match the managed definition")
    return expected


def reflection_bookmarks(manifest: dict[str, Any]) -> list[str]:
    spec = field_spec(manifest, "reflection")
    if anchor_mode(manifest) == SEMANTIC_ANCHOR_MODE:
        validate_semantic_manifest_contract(manifest)
    if spec.get("mode") != "anchored_cells":
        return []
    expected = reflection_bookmark_names()
    values = spec["bookmarks"]
    declared = [str(value) for value in values]
    if declared != expected:
        raise ValueError("Semantic reflection bookmarks do not match the managed definition")
    return expected


def load_schema(path: Path | str = DEFAULT_SCHEMA) -> dict[str, Any]:
    schema_path = Path(path).expanduser().resolve()
    with schema_path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    if not isinstance(schema, dict):
        raise ValueError(f"Schema must be a JSON object: {schema_path}")
    return schema


def _schema_store(schema_path: Path) -> dict[str, dict[str, Any]]:
    """Load the small set of local external schemas used by Lesson input."""

    candidates = (
        schema_path.parent / "shared" / "practice-task-contract.schema.json",
        PRACTICE_CONTRACT_SCHEMA,
    )
    store: dict[str, dict[str, Any]] = {}
    for candidate in dict.fromkeys(path.resolve() for path in candidates):
        if not candidate.is_file():
            continue
        with candidate.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError(f"External schema must be a JSON object: {candidate}")
        store[candidate.as_uri()] = value
        identifier = value.get("$id")
        if identifier:
            store[str(identifier)] = value
    return store


def _validate_positive_number(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{field_name} must be a positive number; received {value}. Lesson hours must be a positive integer.")
    if isinstance(value, str) and value != value.strip():
        raise ValueError(f"{field_name} must be a positive number; received {value}. Lesson hours must be a positive integer.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive number; received {value}. Lesson hours must be a positive integer.") from None
    if not number.is_finite() or number <= 0 or number != number.to_integral_value():
        raise ValueError(f"{field_name} must be a positive number; received {value}. Lesson hours must be a positive integer.")


def _schema_errors(data: dict[str, Any], schema_path: Path | str) -> None:
    resolved_schema_path = Path(schema_path).expanduser().resolve()
    schema = load_schema(resolved_schema_path)
    resources = [(resolved_schema_path.as_uri(), Resource.from_contents(schema))]
    schema_id = schema.get("$id")
    if schema_id and schema_id != resolved_schema_path.as_uri():
        resources.append((str(schema_id), Resource.from_contents(schema)))
    resources.extend(
        (uri, Resource.from_contents(value))
        for uri, value in _schema_store(resolved_schema_path).items()
        if uri not in {item[0] for item in resources}
    )
    registry = Registry().with_resources(resources)
    errors = sorted(
        Draft202012Validator(schema, registry=registry).iter_errors(data),
        key=lambda error: list(error.path),
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise ValueError(f"Input schema validation failed: {details}")


def _decimal_hours(value: Any, field_name: str, *, allow_zero: bool = False) -> Decimal:
    """Parse the contract's integer-hour vocabulary with fail-closed errors."""

    _validate_positive_number(value, field_name) if not allow_zero else None
    if allow_zero:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise ValueError(f"{field_name} must be a non-negative integer hour value; received {value!r}")
        if isinstance(value, str) and value != value.strip():
            raise ValueError(f"{field_name} must be a non-negative integer hour value; received {value!r}")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{field_name} must be a non-negative integer hour value; received {value!r}") from None
        if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
            raise ValueError(f"{field_name} must be a non-negative integer hour value; received {value!r}")
        return parsed
    return Decimal(str(value))


def _validate_locator_evidence(reference: dict[str, Any], prefix: str, *, allow_generic: bool) -> None:
    title = require_meaningful_text(reference.get("title", reference.get("text", "")), f"{prefix}.title", 2)
    source_kind = reference.get("source_kind")
    if source_kind not in REFERENCE_SOURCE_KINDS:
        raise ValueError(f"{prefix}.source_kind must be one of {', '.join(REFERENCE_SOURCE_KINDS)}")
    if reference_looks_like_resource_only(title):
        raise ValueError(f"{prefix} is a resource-only item, not a citable document")
    if reference_looks_like_placeholder(title):
        raise ValueError(f"{prefix}.title is a generic reference placeholder and is not renderable")
    evidence = reference.get("evidence")
    evidence_text = require_meaningful_text(evidence, f"{prefix}.evidence") if evidence is not None else None
    if source_kind == "generic":
        if not allow_generic:
            raise ValueError(f"{prefix}.generic is compatibility-only and is not renderable in the current Lesson Content contract")
        if REFERENCE_SPECIFIC_PATTERN.search(title) or REFERENCE_TITLE_PATTERN.search(title):
            raise ValueError(
                f"{prefix}.generic cannot claim a specific bibliographic identity; "
                "use provided or verified_public only for a real source"
            )
        if evidence_text is not None:
            raise ValueError(f"{prefix}.generic references must not declare evidence")
        return
    if evidence_text is None:
        raise ValueError(f"{prefix}.{source_kind} requires evidence identifying the source")
    if source_kind == "verified_public" and not (
        REFERENCE_EVIDENCE_URL_PATTERN.search(evidence_text)
        or REFERENCE_EVIDENCE_LOCATOR_PATTERN.search(evidence_text)
    ):
        raise ValueError(f"{prefix}.verified_public evidence must contain a URL or an official locatable source")


def _validate_materials_v21(data: dict[str, Any]) -> None:
    materials = data["course_materials"]
    textbook = materials.get("textbook") if isinstance(materials, dict) else None
    if textbook is not None:
        _validate_locator_evidence(textbook, "course_materials.textbook", allow_generic=False)

    pool = data.get("reference_pool", [])
    reference_ids: set[str] = set()
    for index, reference in enumerate(pool, 1):
        prefix = f"reference_pool[{index}]"
        reference_id = require_meaningful_text(reference["reference_id"], f"{prefix}.reference_id")
        if reference_id in reference_ids:
            raise ValueError(f"{prefix}.reference_id must be unique; duplicate {reference_id!r}")
        reference_ids.add(reference_id)
        if reference.get("reference_type") not in REFERENCE_TYPES:
            raise ValueError(f"{prefix}.reference_type must be one of {', '.join(REFERENCE_TYPES)}")
        _validate_locator_evidence(reference, prefix, allow_generic=True)

    textbook_identity = reference_identity(textbook) if textbook is not None else ""
    if textbook_identity and not data.get("allow_textbook_as_reference", False):
        for reference in pool:
            if reference_identity(reference) == textbook_identity:
                raise ValueError(
                    "reference_pool contains the course textbook; set allow_textbook_as_reference=true "
                    "only when the textbook should also be rendered as a lesson reference"
                )

    for index, lesson in enumerate(data["lessons"]):
        prefix = f"lessons[{index}]"
        ids = [str(value) for value in lesson.get("reference_ids", [])]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{prefix}.reference_ids must not contain duplicate IDs within one lesson")
        missing = [value for value in ids if value not in reference_ids]
        if missing:
            raise ValueError(f"{prefix}.reference_ids contains unresolved IDs: {', '.join(missing)}")
        seen_reference_content: dict[str, str] = {}
        for reference_id in ids:
            reference = next(item for item in pool if str(item.get("reference_id")) == reference_id)
            normalized_text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", format_reference(reference))).casefold()
            if normalized_text and normalized_text in seen_reference_content:
                raise ValueError(
                    f"{prefix}.reference_ids contains duplicate reference content: "
                    f"{reference_id!r} duplicates {seen_reference_content[normalized_text]!r} within the same lesson"
                )
            if normalized_text:
                seen_reference_content[normalized_text] = reference_id
        task_ids = [str(value) for value in lesson.get("practice_task_ids", [])]
        if lesson["lesson_type"] == "theory" and task_ids:
            raise ValueError(f"{prefix}.theory lessons must have practice_task_ids=[]")


def _validate_materials_v22(data: dict[str, Any]) -> None:
    """Validate the 2.2 course reference catalog and theory Lesson boundary."""

    materials = data["course_materials"]
    textbook = materials.get("textbook") if isinstance(materials, dict) else None
    if textbook is not None:
        _validate_locator_evidence(textbook, "course_materials.textbook", allow_generic=False)

    pool = data.get("reference_pool", [])
    reference_by_id: dict[str, dict[str, Any]] = {}
    for index, reference in enumerate(pool, 1):
        prefix = f"reference_pool[{index}]"
        reference_id = require_meaningful_text(reference["reference_id"], f"{prefix}.reference_id")
        if reference_id in reference_by_id:
            raise ValueError(f"{prefix}.reference_id must be unique; duplicate {reference_id!r}")
        reference_by_id[reference_id] = reference
        if reference.get("reference_type") not in REFERENCE_TYPES:
            raise ValueError(f"{prefix}.reference_type must be one of {', '.join(REFERENCE_TYPES)}")
        if reference.get("source_region") not in {"domestic", "foreign", "unknown"}:
            raise ValueError(f"{prefix}.source_region must be domestic, foreign, or unknown")
        _validate_locator_evidence(reference, prefix, allow_generic=True)

    textbook_identity = reference_identity(textbook) if textbook is not None else ""
    if textbook_identity and not data.get("allow_textbook_as_reference", False):
        for reference in pool:
            if reference_identity(reference) == textbook_identity:
                raise ValueError(
                    "reference_pool contains the course textbook; set allow_textbook_as_reference=true "
                    "only when the textbook should also be rendered as a lesson reference"
                )

    for index, lesson in enumerate(data["lessons"]):
        prefix = f"lessons[{index}]"
        if lesson["lesson_type"] != "theory":
            raise ValueError(f"{prefix}.lesson_type must be theory; practice belongs to Practice Task/WorkOrder artifacts")
        ids = [str(value) for value in lesson.get("reference_ids", [])]
        if not ids:
            raise ValueError(f"{prefix}.reference_ids must contain at least one citable reference")
        if len(ids) != len(set(ids)):
            raise ValueError(f"{prefix}.reference_ids must not contain duplicate IDs within one lesson")
        missing = [value for value in ids if value not in reference_by_id]
        if missing:
            raise ValueError(f"{prefix}.reference_ids contains unresolved IDs: {', '.join(missing)}")
        seen_reference_content: dict[str, str] = {}
        for reference_id in ids:
            reference = reference_by_id[reference_id]
            normalized_text = re.sub(r"\s+", "", unicodedata.normalize("NFKC", format_reference(reference))).casefold()
            if normalized_text and normalized_text in seen_reference_content:
                raise ValueError(
                    f"{prefix}.reference_ids contains duplicate reference content: "
                    f"{reference_id!r} duplicates {seen_reference_content[normalized_text]!r} within the same lesson"
                )
            if normalized_text:
                seen_reference_content[normalized_text] = reference_id


def _validate_practice_contract_v21(data: dict[str, Any]) -> None:
    plan = data["delivery_plan"]
    total = _decimal_hours(plan["total_hours"], "delivery_plan.total_hours")
    theory = _decimal_hours(plan["theory_hours"], "delivery_plan.theory_hours", allow_zero=True)
    practice = _decimal_hours(plan["practice_hours"], "delivery_plan.practice_hours", allow_zero=True)
    if theory + practice != total:
        raise ValueError("delivery_plan.theory_hours + practice_hours must equal delivery_plan.total_hours")
    if total != _decimal_hours(data["total_hours"], "total_hours"):
        raise ValueError("delivery_plan.total_hours must equal total_hours")

    lesson_ids: list[str] = []
    lesson_id_set: set[str] = set()
    actual_theory = Decimal("0")
    actual_practice = Decimal("0")
    lesson_by_id: dict[str, dict[str, Any]] = {}
    for index, lesson in enumerate(data["lessons"]):
        prefix = f"lessons[{index}]"
        lesson_id = str(lesson["lesson_id"])
        if lesson_id in lesson_id_set:
            raise ValueError(f"{prefix}.lesson_id must be unique; duplicate {lesson_id!r}")
        lesson_ids.append(lesson_id)
        lesson_id_set.add(lesson_id)
        lesson_by_id[lesson_id] = lesson
        hours = _decimal_hours(lesson["hours"], f"{prefix}.hours")
        lesson_theory = _decimal_hours(lesson["theory_hours"], f"{prefix}.theory_hours", allow_zero=True)
        lesson_practice = _decimal_hours(lesson["practice_hours"], f"{prefix}.practice_hours", allow_zero=True)
        if lesson_theory + lesson_practice != hours:
            raise ValueError(f"{prefix}.theory_hours + practice_hours must equal hours")
        lesson_type = lesson["lesson_type"]
        if lesson_type == "theory" and (lesson_theory != hours or lesson_practice != 0):
            raise ValueError(f"{prefix}.theory must have theory_hours=hours and practice_hours=0")
        if lesson_type == "practice" and (lesson_practice != hours or lesson_theory != 0):
            raise ValueError(f"{prefix}.practice must have practice_hours=hours and theory_hours=0")
        if lesson_type == "integrated" and (lesson_theory <= 0 or lesson_practice <= 0):
            raise ValueError(f"{prefix}.integrated must contain positive theory_hours and practice_hours")
        actual_theory += lesson_theory
        actual_practice += lesson_practice
    if actual_theory != theory or actual_practice != practice:
        raise ValueError(
            "lesson theory/practice hour sums must equal delivery_plan: "
            f"expected {theory}/{practice}, got {actual_theory}/{actual_practice}"
        )
    mode = plan["mode"]
    lesson_types = {lesson["lesson_type"] for lesson in data["lessons"]}
    if mode == "theory_only" and practice != 0:
        raise ValueError("delivery_plan.mode=theory_only requires practice_hours=0")
    if mode == "practice_only" and theory != 0:
        raise ValueError("delivery_plan.mode=practice_only requires theory_hours=0")
    if mode == "split_lessons" and "integrated" in lesson_types:
        raise ValueError("delivery_plan.mode=split_lessons cannot contain integrated lessons")
    if mode == "integrated_lessons" and lesson_types - {"integrated"}:
        raise ValueError("delivery_plan.mode=integrated_lessons requires every lesson to be integrated")

    outline = data.get("outline", [])
    if len(outline) != len(data["lessons"]):
        raise ValueError("outline must contain exactly one entry for each lesson")
    for index, (item, lesson) in enumerate(zip(outline, data["lessons"])):
        expected_outline = {
            "lesson_id": lesson.get("lesson_id"),
            "unit": lesson.get("unit"),
            "task": lesson.get("task"),
            "lesson_type": lesson.get("lesson_type"),
            "hours": lesson.get("hours"),
            "theory_hours": lesson.get("theory_hours"),
            "practice_hours": lesson.get("practice_hours"),
            "prior_learning": lesson["progression"].get("prior_learning"),
            "capability_stage": lesson["progression"].get("capability_stage"),
            "deliverable": lesson["progression"].get("deliverable"),
            "next_bridge": lesson["progression"].get("next_bridge"),
            "practice_task_ids": lesson.get("practice_task_ids", []),
        }
        for field_name, expected in expected_outline.items():
            if item.get(field_name) != expected:
                raise ValueError(f"outline[{index}].{field_name} must match lessons[{index}]")

    practice_contract = data.get("practice_task_contract")
    if practice == 0:
        if practice_contract is not None and _decimal_hours(practice_contract["practice_hours"], "practice_task_contract.practice_hours", allow_zero=True) != 0:
            raise ValueError("practice_task_contract.practice_hours must be 0 when delivery_plan.practice_hours=0")
        return
    if not isinstance(practice_contract, dict):
        raise ValueError("practice_task_contract is required when delivery_plan.practice_hours is positive")
    if practice_contract["course_name"] != data["course_name"]:
        raise ValueError("practice_task_contract.course_name must equal course_name")
    contract_hours = _decimal_hours(practice_contract["practice_hours"], "practice_task_contract.practice_hours", allow_zero=True)
    if contract_hours != practice:
        raise ValueError("practice_task_contract.practice_hours must equal delivery_plan.practice_hours")
    tasks = practice_contract.get("tasks", [])
    task_by_id: dict[str, dict[str, Any]] = {}
    task_hours = Decimal("0")
    for index, task in enumerate(tasks):
        prefix = f"practice_task_contract.tasks[{index}]"
        task_id = str(task["task_id"])
        if task_id in task_by_id:
            raise ValueError(f"{prefix}.task_id must be unique; duplicate {task_id!r}")
        task_by_id[task_id] = task
        task_hours += _decimal_hours(task["practice_hours"], f"{prefix}.practice_hours")
        for lesson_id in task["lesson_ids"]:
            linked = lesson_by_id.get(str(lesson_id))
            if linked is None:
                raise ValueError(f"{prefix}.lesson_ids contains unknown lesson {lesson_id!r}")
            if linked["lesson_type"] == "theory":
                raise ValueError(f"{prefix}.lesson_ids cannot point to a theory lesson: {lesson_id}")
    if task_hours != practice:
        raise ValueError(
            "practice task hours must equal delivery_plan.practice_hours: "
            f"expected {practice}, got {task_hours}"
        )
    linked_task_ids = {str(value) for lesson in data["lessons"] for value in lesson.get("practice_task_ids", [])}
    unresolved_task_ids = sorted(linked_task_ids - set(task_by_id))
    if unresolved_task_ids:
        raise ValueError("lessons.practice_task_ids contains unresolved task IDs: " + ", ".join(unresolved_task_ids))
    for lesson in data["lessons"]:
        ids = [str(value) for value in lesson.get("practice_task_ids", [])]
        lesson_practice_hours = _decimal_hours(
            lesson["practice_hours"],
            f"lessons[{lesson['lesson_id']}].practice_hours",
            allow_zero=True,
        )
        if lesson["lesson_type"] in {"practice", "integrated"} and lesson_practice_hours > 0 and not ids:
            raise ValueError(f"{lesson['lesson_id']} practice/integrated lesson must declare practice_task_ids")
    unlinked_task_ids = sorted(set(task_by_id) - linked_task_ids)
    if unlinked_task_ids:
        raise ValueError("practice tasks must be linked by lesson.practice_task_ids: " + ", ".join(unlinked_task_ids))


def _validate_practice_contract_v22(data: dict[str, Any]) -> None:
    """Enforce artifact-level theory/practice accounting for Content 2.2."""

    plan = data["delivery_plan"]
    total = _decimal_hours(plan["total_hours"], "delivery_plan.total_hours")
    theory = _decimal_hours(plan["theory_hours"], "delivery_plan.theory_hours", allow_zero=True)
    practice = _decimal_hours(plan["practice_hours"], "delivery_plan.practice_hours", allow_zero=True)
    declared_total = _decimal_hours(data["total_hours"], "total_hours")
    if theory + practice != total or total != declared_total:
        raise ValueError(
            "delivery_plan.total_hours, theory_hours, practice_hours and total_hours must reconcile"
        )

    lessons = data["lessons"]
    if theory == 0 and lessons:
        raise ValueError("theory_hours=0 requires zero Lesson DOCX lessons")
    if theory > 0 and not lessons:
        raise ValueError("positive theory_hours requires theory Lesson DOCX lessons")
    default_hours = _decimal_hours(data["default_hours"], "default_hours")
    expected_lesson_count = int(theory // default_hours) + (1 if theory % default_hours else 0)
    if len(lessons) != expected_lesson_count:
        raise ValueError(
            "theory Lesson count must equal ceil(theory_hours / default_hours): "
            f"expected {expected_lesson_count}, got {len(lessons)}"
        )

    lesson_by_id: dict[str, dict[str, Any]] = {}
    actual_theory = Decimal("0")
    for index, lesson in enumerate(lessons):
        prefix = f"lessons[{index}]"
        lesson_id = str(lesson["lesson_id"])
        if lesson_id in lesson_by_id:
            raise ValueError(f"{prefix}.lesson_id must be unique; duplicate {lesson_id!r}")
        lesson_by_id[lesson_id] = lesson
        hours = _decimal_hours(lesson["hours"], f"{prefix}.hours")
        lesson_theory = _decimal_hours(lesson["theory_hours"], f"{prefix}.theory_hours", allow_zero=True)
        lesson_practice = _decimal_hours(lesson["practice_hours"], f"{prefix}.practice_hours", allow_zero=True)
        if lesson["lesson_type"] != "theory":
            raise ValueError(f"{prefix}.lesson_type must be theory; practice is a separate artifact")
        if lesson_theory != hours or lesson_practice != 0:
            raise ValueError(f"{prefix} theory Lesson must have theory_hours=hours and practice_hours=0")
        actual_theory += hours
        for task_id in lesson.get("practice_task_ids", []):
            if not isinstance(task_id, str) or not task_id.strip():
                raise ValueError(f"{prefix}.practice_task_ids contains an empty task ID")

    if actual_theory != theory:
        raise ValueError(
            f"Lesson theory hours must equal delivery_plan.theory_hours: expected {theory}, got {actual_theory}"
        )

    mode = plan["mode"]
    if mode == "theory_only" and practice != 0:
        raise ValueError("delivery_plan.mode=theory_only requires practice_hours=0")
    if mode == "practice_only" and theory != 0:
        raise ValueError("delivery_plan.mode=practice_only requires theory_hours=0")

    artifact_plan = data["artifact_plan"]
    expected_lesson_artifact = theory > 0
    if bool(artifact_plan.get("lesson_plans")) != expected_lesson_artifact:
        raise ValueError(
            "artifact_plan.lesson_plans must be true exactly when theory_hours is positive"
        )

    outline = data.get("outline", [])
    if len(outline) != len(lessons):
        raise ValueError("outline must contain exactly one entry for each theory Lesson")
    for index, (item, lesson) in enumerate(zip(outline, lessons)):
        expected_outline = {
            "lesson_id": lesson.get("lesson_id"),
            "unit": lesson.get("unit"),
            "task": lesson.get("task"),
            "lesson_type": "theory",
            "hours": lesson.get("hours"),
            "theory_hours": lesson.get("theory_hours"),
            "practice_hours": 0,
            "prior_learning": lesson["progression"].get("prior_learning"),
            "capability_stage": lesson["progression"].get("capability_stage"),
            "deliverable": lesson["progression"].get("deliverable"),
            "next_bridge": lesson["progression"].get("next_bridge"),
            "practice_task_ids": lesson.get("practice_task_ids", []),
        }
        for field_name, expected in expected_outline.items():
            if item.get(field_name) != expected:
                raise ValueError(f"outline[{index}].{field_name} must match lessons[{index}]")

    practice_contract = data.get("practice_task_contract")
    if practice == 0:
        if practice_contract is not None and _decimal_hours(
            practice_contract["practice_hours"],
            "practice_task_contract.practice_hours",
            allow_zero=True,
        ) != 0:
            raise ValueError("practice_task_contract.practice_hours must be 0 when practice_hours=0")
        return

    if not isinstance(practice_contract, dict):
        raise ValueError("practice_task_contract is required when practice_hours is positive")
    if practice_contract["course_name"] != data["course_name"]:
        raise ValueError("practice_task_contract.course_name must equal course_name")
    contract_hours = _decimal_hours(
        practice_contract["practice_hours"],
        "practice_task_contract.practice_hours",
        allow_zero=True,
    )
    if contract_hours != practice:
        raise ValueError("practice_task_contract.practice_hours must equal delivery_plan.practice_hours")

    task_by_id: dict[str, dict[str, Any]] = {}
    task_hours = Decimal("0")
    for index, task in enumerate(practice_contract.get("tasks", [])):
        prefix = f"practice_task_contract.tasks[{index}]"
        task_id = str(task["task_id"])
        if task_id in task_by_id:
            raise ValueError(f"{prefix}.task_id must be unique; duplicate {task_id!r}")
        task_by_id[task_id] = task
        task_hours += _decimal_hours(task["practice_hours"], f"{prefix}.practice_hours")
        linked_ids = [str(value) for value in task.get("lesson_ids", [])]
        if theory > 0 and not linked_ids:
            raise ValueError(f"{prefix}.lesson_ids must identify related theory Lessons")
        if theory == 0 and linked_ids:
            raise ValueError(f"{prefix}.lesson_ids must be empty for a pure-practice course")
        for lesson_id in linked_ids:
            if lesson_id not in lesson_by_id:
                raise ValueError(f"{prefix}.lesson_ids contains unknown theory Lesson {lesson_id!r}")

    if task_hours != practice:
        raise ValueError(
            "practice task hours must equal delivery_plan.practice_hours: "
            f"expected {practice}, got {task_hours}"
        )
    unresolved_task_ids = sorted(
        {
            str(task_id)
            for lesson in lessons
            for task_id in lesson.get("practice_task_ids", [])
            if str(task_id) not in task_by_id
        }
    )
    if unresolved_task_ids:
        raise ValueError("lessons.practice_task_ids contains unresolved task IDs: " + ", ".join(unresolved_task_ids))


def _validate_meaningful_contract(data: dict[str, Any]) -> None:
    """Apply semantic text rules that JSON Schema cannot express for whitespace."""

    for field_name in ("course_name", "major", "audience"):
        require_meaningful_text(data[field_name], field_name)

    for index, lesson in enumerate(data["lessons"]):
        prefix = f"lessons[{index}]"
        for field_name in ("unit", "task"):
            require_meaningful_text(lesson[field_name], f"{prefix}.{field_name}")
        progression = lesson["progression"]
        for field_name in ("prior_learning", "deliverable", "next_bridge"):
            require_meaningful_text(progression[field_name], f"{prefix}.progression.{field_name}", 6)
        if progression["prior_lesson_id"] is not None:
            require_meaningful_text(progression["prior_lesson_id"], f"{prefix}.progression.prior_lesson_id")
        if progression["capability_stage"] not in CAPABILITY_STAGES:
            raise ValueError(
                f"{prefix}.progression.capability_stage must be one of {', '.join(CAPABILITY_STAGES)}; "
                f"received {progression['capability_stage']!r}"
            )

        list_fields = (
            ("student_analysis.base", lesson["student_analysis"]["base"]),
            ("student_analysis.problems", lesson["student_analysis"]["problems"]),
            ("student_analysis.strategies", lesson["student_analysis"]["strategies"]),
            ("teaching_content", lesson["teaching_content"]),
            ("goals.knowledge", lesson["goals"]["knowledge"]),
            ("goals.ability", lesson["goals"]["ability"]),
            ("goals.quality", lesson["goals"]["quality"]),
            ("key_point.content", lesson["key_point"]["content"]),
            ("key_point.strategy", lesson["key_point"]["strategy"]),
            ("difficult_point.content", lesson["difficult_point"]["content"]),
            ("difficult_point.strategy", lesson["difficult_point"]["strategy"]),
            ("teaching_methods", lesson["teaching_methods"]),
            ("resources", lesson["resources"]),
        )
        for field_name, values in list_fields:
            for item_index, value in enumerate(values, 1):
                require_meaningful_text(value, f"{prefix}.{field_name}[{item_index}]")

        for stage_index, stage in enumerate(lesson["implementation"], 1):
            stage_prefix = f"{prefix}.implementation[{stage_index}]"
            for field_name in ("label", "modality", "objective"):
                require_meaningful_text(stage[field_name], f"{stage_prefix}.{field_name}")
            for field_name in ("content", "teacher_actions", "student_actions"):
                for item_index, value in enumerate(stage[field_name], 1):
                    require_meaningful_text(value, f"{stage_prefix}.{field_name}[{item_index}]")

        for criterion, _maximum, _label in EVALUATION_CRITERIA:
            require_meaningful_text(
                lesson["evaluation"]["remarks"][criterion],
                f"{prefix}.evaluation.remarks.{criterion}",
                4,
            )
        if data.get("content_contract_version") not in {"2.1", "2.2"}:
            for reference_index, reference in enumerate(lesson["references"], 1):
                reference_prefix = f"{prefix}.references[{reference_index}]"
                reference_text = require_meaningful_text(reference["text"], f"{reference_prefix}.text")
                source_kind = reference["source_kind"]
                evidence = reference.get("evidence")
                if evidence is not None:
                    evidence = require_meaningful_text(evidence, f"{reference_prefix}.evidence")
                if source_kind == "generic":
                    if evidence is not None:
                        raise ValueError(f"{reference_prefix}.generic references must not declare evidence")
                    if REFERENCE_SPECIFIC_PATTERN.search(reference_text) or REFERENCE_TITLE_PATTERN.search(reference_text):
                        raise ValueError(
                            f"{reference_prefix} uses source_kind=generic for a specific citation; "
                            "mark it provided or verified_public only when the source is real"
                        )
                elif source_kind == "provided":
                    if evidence is None:
                        raise ValueError(
                            f"{reference_prefix}.provided requires evidence identifying the supplied material"
                        )
                elif source_kind == "verified_public":
                    if evidence is None:
                        raise ValueError(
                            f"{reference_prefix}.verified_public requires evidence such as a URL or an official locator"
                        )
                    if not (
                        REFERENCE_EVIDENCE_URL_PATTERN.search(evidence)
                        or REFERENCE_EVIDENCE_LOCATOR_PATTERN.search(evidence)
                    ):
                        raise ValueError(
                            f"{reference_prefix}.verified_public evidence must contain a URL or an official locatable source"
                        )


def _validate_content_v2(data: dict[str, Any], schema_path: Path | str) -> None:
    version = data.get("content_contract_version")
    if version not in COMPATIBLE_CONTENT_CONTRACT_VERSIONS:
        raise ValueError(
            "Legacy sparse lesson content is no longer accepted for production generation. "
            "Regenerate tasks JSON using the Lesson Content V2 Skill workflow. Content V2.2 is the current contract."
        )
    if version == "2.1":
        _schema_errors(data, schema_path)
        _validate_meaningful_contract(data)
        _validate_materials_v21(data)
        _validate_practice_contract_v21(data)
        return
    if version == "2.2":
        _schema_errors(data, schema_path)
        _validate_meaningful_contract(data)
        _validate_materials_v22(data)
        _validate_practice_contract_v22(data)
        return
    for field_name in ("default_hours", "total_hours"):
        if field_name in data:
            _validate_positive_number(data[field_name], field_name)
    for index, lesson in enumerate(data.get("lessons", [])):
        if not isinstance(lesson, dict):
            continue
        if "hours" in lesson:
            _validate_positive_number(lesson["hours"], f"lessons[{index}].hours")
            if len(str(lesson["hours"]).strip()) > MAX_HOURS_TEXT_LENGTH:
                raise ValueError(
                    f"lessons[{index}].hours exceeds manifest max_chars={MAX_HOURS_TEXT_LENGTH}: "
                    f"{len(str(lesson['hours']).strip())}"
                )
        evaluation = lesson.get("evaluation")
        if isinstance(evaluation, dict) and "score" in evaluation:
            try:
                score = Decimal(str(evaluation["score"]))
            except (InvalidOperation, TypeError, ValueError):
                score = None
            if score is not None and (
                not score.is_finite()
                or score < EVALUATION_SCORE_MIN
                or score > EVALUATION_SCORE_MAX
                or score % EVALUATION_SCORE_STEP != 0
            ):
                raise ValueError(
                    f"lessons[{index}].evaluation.score must be between 85 and 96 in 0.5-point increments; "
                    f"received {evaluation['score']}."
                )
    _schema_errors(data, schema_path)
    _validate_meaningful_contract(data)

    try:
        default_hours = Decimal(str(data["default_hours"]))
        total_hours = Decimal(str(data["total_hours"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Content Contract V2 course hours are invalid: {exc}") from None
    if not default_hours.is_finite() or default_hours <= 0 or default_hours != default_hours.to_integral_value():
        raise ValueError(
            "default_hours must be a positive number; "
            f"received {data.get('default_hours')}. Lesson hours must be a positive integer."
        )
    if not total_hours.is_finite() or total_hours <= 0 or total_hours != total_hours.to_integral_value():
        raise ValueError(
            "total_hours must be a positive number; "
            f"received {data.get('total_hours')}. Lesson hours must be a positive integer."
        )

    lesson_ids: set[str] = set()
    ordered_lesson_ids: list[str] = []
    lesson_hours = Decimal("0")
    expected_stage_ids = list(IMPLEMENTATION_STAGE_IDS)
    placeholder_values = {"已有一定基础", "完成相应任务", "为下一课打基础"}
    for index, lesson in enumerate(data["lessons"]):
        lesson_id = str(lesson["lesson_id"])
        if lesson_id in lesson_ids:
            raise ValueError(f"lessons[{index}].lesson_id must be unique; duplicate {lesson_id!r}")
        lesson_ids.add(lesson_id)
        previous_lesson_ids = set(ordered_lesson_ids)
        ordered_lesson_ids.append(lesson_id)
        hours = Decimal(str(lesson["hours"]))
        lesson_hours += hours
        classroom_minutes = Decimal("0")
        out_of_class_minutes: list[tuple[str, int]] = []
        stages = lesson["implementation"]
        stage_ids = [str(stage["id"]) for stage in stages]
        if stage_ids != expected_stage_ids:
            raise ValueError(
                f"lessons[{index}].implementation must contain stages in canonical order: "
                f"{', '.join(expected_stage_ids)}"
            )
        for stage_index, stage in enumerate(stages):
            minutes = int(stage["minutes"])
            if stage["id"] in IN_CLASS_STAGE_IDS:
                if minutes <= 0:
                    raise ValueError(f"lessons[{index}].implementation[{stage_index}].minutes must be positive for in-class stages")
                classroom_minutes += Decimal(minutes)
            else:
                out_of_class_minutes.append((str(stage["id"]), minutes))
        expected_minutes = hours * Decimal(MINUTES_PER_LESSON_HOUR)
        if expected_minutes != expected_minutes.to_integral_value():
            raise ValueError(f"lessons[{index}].hours must produce whole classroom minutes: {lesson['hours']}")
        if classroom_minutes != expected_minutes:
            raise ValueError(
                f"lessons[{index}] in-class implementation minutes must equal hours*45: "
                f"expected {int(expected_minutes)}, got {int(classroom_minutes)}"
            )
        out_of_class_limit = max(60, int(expected_minutes))
        for stage_id, minutes in out_of_class_minutes:
            if minutes < 0 or minutes > out_of_class_limit:
                raise ValueError(
                    "out-of-class minutes sanity failed: "
                    f"lesson_id={lesson_id} stage={stage_id} actual={minutes} limit={out_of_class_limit}"
                )
        out_of_class_total = sum(minutes for _stage_id, minutes in out_of_class_minutes)
        total_limit = 2 * int(expected_minutes)
        if out_of_class_total > total_limit:
            raise ValueError(
                "out-of-class minutes sanity failed: "
                f"lesson_id={lesson_id} stage=out_of_class_total "
                f"actual={out_of_class_total} limit={total_limit}"
            )
        progression = lesson["progression"]
        prior_lesson_id = progression["prior_lesson_id"]
        if index == 0:
            if prior_lesson_id is not None:
                raise ValueError("lessons[0].progression.prior_lesson_id must be null")
        elif prior_lesson_id not in previous_lesson_ids:
            raise ValueError(
                f"lessons[{index}].progression.prior_lesson_id must reference an earlier lesson; "
                f"received {prior_lesson_id!r}"
            )
        for name in ("prior_learning", "deliverable", "next_bridge"):
            if str(progression[name]).strip() in placeholder_values:
                raise ValueError(f"lessons[{index}].progression.{name} must contain specific information")

        score = Decimal(str(lesson["evaluation"]["score"]))
        if (
            not score.is_finite()
            or score < EVALUATION_SCORE_MIN
            or score > EVALUATION_SCORE_MAX
            or score % EVALUATION_SCORE_STEP != 0
        ):
            raise ValueError(
                f"lessons[{index}].evaluation.score must be between 85 and 96 in 0.5-point increments; "
                f"received {lesson['evaluation']['score']}"
            )
        if set(lesson["evaluation"]["remarks"]) != {criterion[0] for criterion in EVALUATION_CRITERIA}:
            raise ValueError(f"lessons[{index}].evaluation.remarks must match the canonical evaluation criterion IDs")
    if lesson_hours != total_hours:
        raise ValueError(f"total_hours must equal the sum of lesson hours; expected {total_hours}, got {lesson_hours}")


def _validate_legacy_input(data: dict[str, Any]) -> None:
    """Keep the import-level helper useful for old callers without enabling production generation."""
    if not isinstance(data, dict) or "course_name" not in data or "lessons" not in data:
        raise ValueError("Input schema validation failed: <root> must contain course_name and lessons")
    if set(data) - {"course_name", "major", "audience", "default_hours", "total_hours", "lessons"}:
        raise ValueError("Input schema validation failed: <root>: Additional properties are not allowed")
    if not isinstance(data["course_name"], str) or not data["course_name"] or len(data["course_name"]) > 32:
        raise ValueError("Input schema validation failed: course_name is invalid")
    if not isinstance(data["lessons"], list) or not data["lessons"]:
        raise ValueError("Input schema validation failed: lessons must be a non-empty array")
    for index, lesson in enumerate(data["lessons"]):
        if not isinstance(lesson, dict):
            raise ValueError(f"Input schema validation failed: lessons[{index}] must be an object")
        for name in ("unit", "task", "hours"):
            if name not in lesson:
                raise ValueError(f"Input schema validation failed: lessons[{index}] is missing {name}")
        _validate_positive_number(lesson["hours"], f"lessons[{index}].hours")


def validate_input(
    data: dict[str, Any],
    schema_path: Path | str = DEFAULT_SCHEMA,
    *,
    require_v2: bool = True,
) -> None:
    if not isinstance(data, dict):
        raise ValueError("Input schema validation failed: <root> must be an object")
    if require_v2 or "content_contract_version" in data:
        _validate_content_v2(data, schema_path)
        return
    _validate_legacy_input(data)


def validate_content_v2_input(data: dict[str, Any], schema_path: Path | str = DEFAULT_SCHEMA) -> None:
    """Explicit production entry point used by both generation and output QA."""
    _validate_content_v2(data, schema_path)


def validate_input_legacy_compatibility(data: dict[str, Any]) -> None:
    _validate_legacy_input(data)


def ensure_supported_major(manifest: dict[str, Any]) -> None:
    major, _minor, _patch = parse_template_version(manifest)
    supported = manifest.get("generator", {}).get("supported_major")
    supported_text = str(supported) if isinstance(supported, (str, int)) and not isinstance(supported, bool) else ""
    if re.fullmatch(r"(0|[1-9][0-9]*)", supported_text) is None:
        raise ValueError("Manifest must declare a semantic template version and generator.supported_major")
    supported_major = int(supported_text)
    if major != supported_major:
        raise ValueError(f"Unsupported template major version {major}; generator supports {supported_major}")


def field_spec(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    fields = manifest.get("fields", {})
    value = fields.get(name)
    if not isinstance(value, dict):
        raise KeyError(f"Manifest field is missing or invalid: {name}")
    return value


def score_breakdown(target: float) -> list[float]:
    target_decimal = Decimal(str(target))
    if (
        not target_decimal.is_finite()
        or target_decimal < EVALUATION_SCORE_MIN
        or target_decimal > EVALUATION_SCORE_MAX
        or target_decimal % EVALUATION_SCORE_STEP != 0
    ):
        raise ValueError(f"Evaluation score must be between 85 and 96 in 0.5-point increments: {target}")
    target_units_decimal = target_decimal * 2
    if target_units_decimal != target_units_decimal.to_integral_value():
        raise ValueError(f"Evaluation score must use 0.5-point increments: {target}")
    target_units = int(target_units_decimal)
    scores_units = [
        int((Decimal(point) * target_decimal * 2 / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        for point in EVALUATION_MAX_POINTS
    ]
    diff_units = target_units - sum(scores_units)
    step = 1 if diff_units > 0 else -1
    order = [10, 8, 9, 12, 2, 7, 11, 3, 4, 5, 6, 1, 0]
    while diff_units:
        changed = False
        for pos in order:
            candidate = scores_units[pos] + step
            if 0 <= candidate <= EVALUATION_MAX_POINTS[pos] * 2:
                scores_units[pos] = candidate
                diff_units = target_units - sum(scores_units)
                changed = True
                break
        if not changed:
            break
    return [units / 2 for units in scores_units]
