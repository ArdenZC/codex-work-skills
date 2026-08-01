from __future__ import annotations

import json
import hashlib
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from semantic_bookmarks import (
    IMPLEMENTATION_STAGES,
    SEMANTIC_FIELD_CONTRACTS,
    implementation_bookmark_groups,
    managed_bookmark_names,
    reflection_bookmark_names,
)


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "manifest.yaml"
V10_MANIFEST = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "manifest.yaml"
V11_MANIFEST = DEFAULT_MANIFEST
V10_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.0.0" / "template.docx"
V11_TEMPLATE = SKILL_DIR / "assets" / "templates" / "lesson-plan" / "v1.1.0" / "template.docx"
LEGACY_TEMPLATE = SKILL_DIR / "assets" / "lesson-plan-template.docx"
DEFAULT_SCHEMA = SKILL_DIR / "schemas" / "lesson-plan-input.schema.json"
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
LEGACY_ANCHOR_MODE = "legacy_coordinates"
SEMANTIC_ANCHOR_MODE = "word_bookmark"
MAX_TEACHING_CONTENT_ITEMS = 8
EVALUATION_MAX_POINTS = [3, 3, 4, 5, 5, 5, 5, 10, 10, 10, 25, 10, 5]
EVALUATION_REMARKS = [
    ["出勤正常", "注意力较稳", "参与较积极", "规范意识较好", "质量意识较强", "安全意识较好", "习惯较好", "预习较完整", "答题较准确", "作业较认真", "实操较熟练", "展示较清楚"],
    ["基本到课", "个别环节需提醒", "能主动配合", "流程执行较规范", "能联系项目实际", "职业责任意识较好", "工具使用较规范", "线上学习较及时", "讨论质量尚可", "提交较规范", "任务完成度较高", "汇报条理较清楚"],
    ["考勤良好", "专注度尚可", "参与较自然", "记录较规范", "质量观念较到位", "能注意风险控制", "实训习惯较好", "资料阅读较完整", "关键问题掌握较好", "成果较完整", "能完成主要步骤", "演示基本清楚"],
]


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
    known = ((V11_TEMPLATE, "1.1.0"), (V10_TEMPLATE, "1.0.0"), (LEGACY_TEMPLATE, "1.0.0"))
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


def _validate_package_identity(template: Path, manifest: dict[str, Any], *, explicit_manifest: bool) -> None:
    template_info = manifest.get("template", {})
    if template_info.get("id") != "lesson-plan":
        raise ValueError("Manifest template.id must be lesson-plan")
    if template_info.get("format") != "docx":
        raise ValueError("Manifest template.format must be docx")
    version = str(template_info.get("version", ""))
    known_version = _known_template_version(template)
    if known_version is not None and known_version != version:
        raise ValueError(
            f"Template/manifest mismatch: {template.name} is v{known_version}, manifest declares v{version}"
        )
    if explicit_manifest and not template.exists():
        raise FileNotFoundError(f"Template not found: {template}")


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
        _validate_package_identity(template, manifest, explicit_manifest=False)
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
        if known_version == "1.1.0":
            resolved_manifest = V11_MANIFEST.resolve()
        elif known_version == "1.0.0":
            resolved_manifest = V10_MANIFEST.resolve()
        elif template.parent.name in {"v1.0.0", "v1.1.0"} and (template.parent / "manifest.yaml").exists():
            resolved_manifest = (template.parent / "manifest.yaml").resolve()
        else:
            raise ValueError("Custom template requires a matching --manifest.")
        manifest = load_manifest(resolved_manifest)
    _validate_package_identity(template, manifest, explicit_manifest=bool(manifest_value))
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
        semantic_anchor_metadata = isinstance(anchors, dict) and any(
            key in anchors for key in ("required", "containers")
        )
        fields = manifest.get("fields")
        semantic_field_metadata = isinstance(fields, dict) and any(
            isinstance(fields.get(name), dict) and "bookmark" in fields[name]
            for name in SEMANTIC_FIELD_CONTRACTS
        )
        if semantic_anchor_metadata or semantic_field_metadata:
            raise ValueError(
                f"Legacy anchor mode mismatch for template.version {version}: "
                "1.0.x must not declare semantic bookmark metadata."
            )
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


def validate_semantic_manifest_contract(manifest: dict[str, Any]) -> None:
    """Require every v1.1 semantic contract field without applying defaults."""
    if anchor_mode(manifest) != SEMANTIC_ANCHOR_MODE:
        return

    anchors = _required_manifest_mapping(manifest, "anchors")
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

    _required_manifest_mapping(manifest, "fields")
    for field, contract in SEMANTIC_FIELD_CONTRACTS.items():
        spec = _required_manifest_mapping(manifest, f"fields.{field}")
        for key in ("target", "bookmark", "mode"):
            value = _required_manifest_value(spec, f"fields.{field}", key)
            expected = contract[key]
            if str(value) != expected:
                raise ValueError(f"Semantic manifest fields.{field}.{key} must be {expected}; got {value}.")

    implementation = _required_manifest_mapping(manifest, "fields.implementation")
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


def _validate_positive_number(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a positive number; received {value}.") from None
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field_name} must be a positive number; received {value}.")


def validate_input(data: dict[str, Any], schema_path: Path | str = DEFAULT_SCHEMA) -> None:
    for field_name in ("default_hours", "total_hours"):
        if field_name in data:
            _validate_positive_number(data[field_name], field_name)

    for index, lesson in enumerate(data.get("lessons", [])):
        if isinstance(lesson, dict) and "hours" in lesson:
            _validate_positive_number(lesson["hours"], f"lessons[{index}].hours")
        if isinstance(lesson, dict):
            flows = lesson.get("flows", [])
            knowledge = lesson.get("knowledge", [])
            if isinstance(flows, list) and isinstance(knowledge, list):
                content_items = len(flows) + len(knowledge)
                if content_items > MAX_TEACHING_CONTENT_ITEMS:
                    raise ValueError(
                        f"lessons[{index}] flows and knowledge combined must contain at most "
                        f"{MAX_TEACHING_CONTENT_ITEMS} items; received {content_items}."
                    )
        if not isinstance(lesson, dict) or "score" not in lesson:
            continue
        try:
            score = Decimal(str(lesson["score"]))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not score.is_finite() or score % Decimal("0.5") != 0:
            raise ValueError(
                f"lessons[{index}].score must use 0.5-point increments; received {lesson['score']}."
            )
    schema = load_schema(schema_path)
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors[:8]
        )
        raise ValueError(f"Input schema validation failed: {details}")
    for index, lesson in enumerate(data.get("lessons", [])):
        if isinstance(lesson, dict) and isinstance(lesson.get("unit"), str):
            unit = lesson["unit"].strip()
            if not unit.startswith("项目"):
                raise ValueError(
                    f"lessons[{index}].unit must start with 项目 for projectized teaching; received {lesson['unit']!r}."
                )


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


def _numbered_text(items: list[Any]) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"{index}. {item}" for index, item in enumerate(values, 1))


def composed_lesson_fields(
    unit: str,
    task: str,
    flows: list[Any],
    knowledge: list[Any],
    tools: Any = "课程PPT、微课视频、任务单、评分表和成果模板",
) -> dict[str, str]:
    numbered_flows = _numbered_text(flows)
    numbered_knowledge = _numbered_text(knowledge)
    return {
        "teaching_content": (
            f"围绕“{unit}”开展“{task}”，完成以下任务：\n"
            f"{numbered_flows}\n"
            f"核心知识点：\n"
            f"{numbered_knowledge}"
        ).rstrip("\n"),
        "knowledge_goal": numbered_knowledge or f"1. 理解{task}的核心概念\n2. 掌握相关流程和成果要求",
        "resources": (
            "1. 教学环境：标准机房、多媒体设备、网络环境及课程实训平台\n"
            f"2. 实训工具：{str(tools)}\n"
            "3. 数字资源：课程PPT、微课视频、任务单、评分表和成果模板"
        ),
    }


def generated_lesson_fields(
    unit: str,
    task: str,
    flows: list[Any],
    knowledge: list[Any],
    tools: Any = "课程PPT、微课视频、任务单、评分表和成果模板",
) -> dict[str, str]:
    composed = composed_lesson_fields(unit, task, flows, knowledge, tools)
    return {
        "student_base": "1. 已具备相关课程基础，能理解任务涉及的基本概念\n2. 能按照教师演示完成基本工具操作\n3. 对项目案例、实操训练和线上资源接受度较高",
        "student_problems": "1. 理论知识向任务迁移时容易停留在照步骤操作\n2. 操作记录、结果分析和成果表达不够规范\n3. 小组分工、工具使用和成果整理能力存在差异",
        "student_strategy": "1. 以项目任务驱动教学，明确每次课成果\n2. 提供任务单、模板和检查表降低入门难度\n3. 通过过程性评分和小组互评及时反馈改进",
        "teaching_content": composed["teaching_content"],
        "quality_goal": "1. 培养规范操作、职业责任和质量意识\n2. 树立严谨记录、客观评价和持续改进的工程态度\n3. 强化团队协作、诚信意识和数据安全意识",
        "knowledge_goal": composed["knowledge_goal"],
        "ability_goal": f"1. 能根据任务要求完成{task}相关操作\n2. 能按模板提交规范成果\n3. 能对任务结果进行说明、分析和改进",
        "key_content": f"{task}的操作流程、成果规范和结果分析",
        "key_strategy": "任务驱动、教师示范、分组实训、过程评价",
        "difficult_content": f"在真实项目情境下完成{task}并形成规范成果",
        "difficult_strategy": "提供模板清单、分步演示、同伴互评和教师点评",
        "teaching_methods": "项目教学法、任务驱动法、演示法、分组实训法、成果评价法",
        "resources": composed["resources"],
        "references": "1. 课程配套教学资源\n2. 相关课程标准、项目任务书及主流工具官方文档\n3. 行业案例资料和实训成果模板",
    }


def reflection_cell_values(task: str) -> list[str]:
    return [
        f"多数学生能按要求完成{task}，对任务流程和成果规范有较清晰认识；少数学生在记录完整性和结果分析上仍需加强。",
        "以项目任务贯穿教学，突出实操产出和过程评价，学生参与度较高，互评环节能促进成果完善。",
        "后续增加优秀成果样例和常见错误清单，对基础薄弱学生提供分步检查表，对能力较强学生增加扩展场景。",
    ]


def score_breakdown(target: float) -> list[float]:
    target_decimal = Decimal(str(target))
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


def evaluation_cell_values(target: float, sequence: int) -> list[dict[int, str]]:
    target_value = float(target)
    remarks = EVALUATION_REMARKS[(sequence - 1) % len(EVALUATION_REMARKS)]
    values = []
    for row_index, score in enumerate(score_breakdown(target_value), start=1):
        display = str(int(score)) if abs(score - int(score)) < 0.01 else f"{score:.1f}"
        note = remarks[row_index - 1] if row_index <= 12 else f"综合{target_value:.1f}分，后续加强完整项目迁移"
        values.append({2: display, 3: note})
    return values


def implementation_cell_values(task: str, flows: list[Any]) -> list[dict[int, str]]:
    numbered_flows = _numbered_text(flows[:3])
    return [
        {
            0: "课前准备\n10min\n线上+线下",
            1: f"阅读任务单，了解{task}的成果要求和评价标准",
            2: "1. 发布任务单和模板\n2. 推送操作提示\n3. 收集预习问题",
            3: "1. 阅读任务材料\n2. 检查工具环境\n3. 标记疑问",
            4: "保证任务开始前目标明确、环境可用",
        },
        {
            0: "任务导入5min\n线下",
            1: f"以项目情境导入“{task}”，说明本次任务产出物",
            2: "1. 展示项目背景\n2. 明确任务边界\n3. 说明评分要点",
            3: "1. 了解项目情境\n2. 明确小组分工\n3. 确认成果要求",
            4: "用真实任务激活学习动机，形成任务驱动",
        },
        {
            0: "操作示范\n15min\n线下",
            1: f"示范本次任务关键步骤：\n{numbered_flows}",
            2: "1. 演示关键流程\n2. 提醒易错点\n3. 展示合格成果样例",
            3: "1. 观察记录\n2. 对照模板理解要求\n3. 提问确认",
            4: "降低实操门槛，让学生掌握基本路径",
        },
        {
            0: "任务实施\n25min\n线下",
            1: f"小组完成{task}，形成课堂阶段性成果",
            2: "1. 巡视指导\n2. 解答工具和流程问题\n3. 记录共性问题",
            3: "1. 按分工完成任务\n2. 记录操作过程\n3. 整理成果文件",
            4: "通过做中学完成知识、技能和规范的转化",
        },
        {
            0: "任务拓展\n10min\n线下",
            1: "根据教师反馈修正记录、脚本、用例或文档中的问题",
            2: "1. 点评典型问题\n2. 指导小组修正\n3. 强调质量标准",
            3: "1. 对照反馈修改\n2. 复查成果完整性\n3. 完成自评",
            4: "强化规范意识和质量闭环",
        },
        {
            0: "项目实训\n15min\n线下",
            1: f"提交{task}相关成果包，包括记录、截图、脚本或文档",
            2: "1. 检查提交材料\n2. 抽查关键成果\n3. 给出即时建议",
            3: "1. 提交成果包\n2. 补充说明\n3. 记录改进点",
            4: "形成可评价、可追溯的学习成果",
        },
        {
            0: "组间互评8min\n线下",
            1: "小组交换成果，从正确性、完整性、规范性和可复现性四方面互评",
            2: "1. 下发互评标准\n2. 组织互评\n3. 抽取典型成果点评",
            3: "1. 根据标准互评\n2. 记录建议\n3. 完善本组成果",
            4: "让评价标准显性化，促进互学互改",
        },
        {
            0: "课堂小结7min\n线下",
            1: "归纳本次任务的关键流程、常见问题和成果规范",
            2: "1. 总结重难点\n2. 发布课后完善要求\n3. 提醒下次课准备",
            3: "1. 回顾任务过程\n2. 完成自评\n3. 明确课后任务",
            4: "帮助学生沉淀经验，形成持续改进意识",
        },
        {
            0: "课后完善\n15min\n线上+线下",
            1: "根据课堂反馈完善成果包，并在线提交最终版本",
            2: "1. 在线答疑\n2. 检查最终提交\n3. 记录过程性成绩",
            3: "1. 修改成果\n2. 上传最终版本\n3. 完成学习反思",
            4: "延伸课堂任务，保证成果质量",
        },
    ]


def _validate_composed_limit(label: str, value: str, spec: dict[str, Any]) -> None:
    max_chars = spec.get("max_chars")
    if max_chars is not None and len(value) > int(max_chars):
        raise ValueError(f"{label} exceeds manifest max_chars={max_chars}: {len(value)}")
    max_paragraphs = spec.get("max_paragraphs")
    paragraph_count = len(value.splitlines()) or 1
    if max_paragraphs is not None and paragraph_count > int(max_paragraphs):
        raise ValueError(
            f"{label} exceeds manifest max_paragraphs={max_paragraphs}: {paragraph_count}"
        )


def validate_composed_fields(data: dict[str, Any], manifest: dict[str, Any]) -> None:
    implementation_spec = field_spec(manifest, "implementation")
    title_spec = field_spec(manifest, "title")
    reflection_spec = field_spec(manifest, "reflection")
    for index, lesson in enumerate(data.get("lessons", []), start=1):
        if not isinstance(lesson, dict):
            continue
        unit = str(lesson.get("unit", ""))
        task = str(lesson.get("task", ""))
        course = str(lesson.get("course_name") or data.get("course_name", ""))
        flows = [str(item) for item in lesson.get("flows", [])]
        knowledge = [str(item) for item in lesson.get("knowledge", [])]
        generated = generated_lesson_fields(
            unit,
            task,
            flows,
            knowledge,
            lesson.get("tools", "课程PPT、微课视频、任务单、评分表和成果模板"),
        )
        for name, value in generated.items():
            _validate_composed_limit(
                f"lessons[{index - 1}].{name}",
                value,
                field_spec(manifest, name),
            )
        hours_spec = field_spec(manifest, "hours")
        _validate_composed_limit(
            f"lessons[{index - 1}].hours",
            str(lesson.get("hours", "")).strip(),
            hours_spec,
        )
        for row_index, values in enumerate(implementation_cell_values(task, flows), start=1):
            for cell_index, value in values.items():
                _validate_composed_limit(
                    f"lessons[{index - 1}].implementation row {row_index} cell {cell_index}",
                    str(value),
                    implementation_spec,
                )
        reflection_targets = (
            reflection_bookmarks(manifest)
            if is_semantic_manifest(manifest)
            else [int(row) for row in manifest["fields"]["reflection"]["rows"]]
        )
        for row_index, value in zip(reflection_targets, reflection_cell_values(task)):
            _validate_composed_limit(
                f"lessons[{index - 1}].reflection {row_index}",
                value,
                reflection_spec,
            )
        title = f"{index} 《{course}》教学单元设计：{task}"
        _validate_composed_limit(f"lessons[{index - 1}].title", title, title_spec)
