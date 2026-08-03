"""Generic discovery of versioned template packages."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .manifest import inspect_manifest_package, load_manifest
from .models import TemplatePackage, TemplateToolError, parse_semver
from .paths import is_within, repo_root, safe_relative


def skill_root_for_validator(validator: Path) -> Path:
    return validator.resolve().parent.parent


SCHEMA_BY_TEMPLATE_ID = {
    "lesson-plan": "lesson-plan-input.schema.json",
    "course-gradebook": "gradebook-input.schema.json",
}


def owner_skill_root(package: TemplatePackage) -> Path:
    if package.validator is None:
        raise TemplateToolError(f"owner validator is unavailable for {package.package_dir}")
    return skill_root_for_validator(package.validator)


def schema_path_for_package(package: TemplatePackage) -> Path:
    """Resolve a package schema from its owner skill and closed id mapping."""
    owner = owner_skill_root(package)
    raw = package.manifest.get("schema") or package.manifest.get("input_schema")
    if raw:
        relative = safe_relative(str(raw), label="manifest schema")
        candidate = (owner / relative).resolve(strict=False)
    else:
        filename = SCHEMA_BY_TEMPLATE_ID.get(package.template_id)
        if filename is None:
            raise TemplateToolError(
                f"cannot determine input schema for template id {package.template_id!r}; "
                "declare manifest.schema"
            )
        candidate = owner / "schemas" / filename
    if not is_within(candidate, owner):
        raise TemplateToolError(f"manifest schema escapes owner skill: {candidate}")
    if not candidate.is_file():
        raise TemplateToolError(f"input schema was not found: {candidate}")
    return candidate


def _validator_for_manifest(manifest_path: Path) -> Path | None:
    for ancestor in (manifest_path.parent, *manifest_path.parent.parents):
        candidate = ancestor / "scripts" / "validate_template.py"
        if candidate.is_file():
            return candidate.resolve()
    return None


def _default_markers(skill_root: Path, template_id: str, version: str) -> bool:
    marker_pattern = re.compile(
        r"(?:default[^\n;；]*?|默认使用[^\n;；]*?|built-in[^\n;；]*?)"
        r"assets/templates/([^`\s/]+)/((?:v)?[0-9]+\.[0-9]+\.[0-9]+)",
        re.IGNORECASE,
    )
    candidates = [
        path
        for path in skill_root.iterdir()
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".py"}
    ] if skill_root.is_dir() else []
    candidates.extend(sorted((skill_root / "scripts").glob("*.py")) if (skill_root / "scripts").is_dir() else [])
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").replace("\\", "/")
        except OSError:
            continue
        for line in text.splitlines():
            for match in marker_pattern.finditer(line):
                if match.group(1) == template_id and match.group(2).lstrip("v") == version:
                    return True
    return False


def _canonical_package_shape(package_dir: Path, validator: Path | None) -> tuple[bool, Path | None]:
    if validator is None:
        return False, None
    resolved = package_dir.resolve()
    try:
        templates_root = resolved.parents[1]
    except IndexError:
        return False, None
    if templates_root.name != "templates" or templates_root.parent.name != "assets":
        return False, None
    if resolved.parent.parent != templates_root:
        return False, None
    skill_root = skill_root_for_validator(validator)
    return is_within(templates_root, skill_root / "assets" / "templates"), skill_root


def _scan_manifest_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        raise TemplateToolError(f"repository root does not exist: {root}")
    paths: list[Path] = []
    for path in sorted(root.glob("**/assets/templates/*/*/manifest.yaml"), key=lambda item: item.as_posix().lower()):
        resolved = path.resolve(strict=False)
        if not is_within(resolved, root):
            continue
        paths.append(resolved)
    return paths


def discover_packages(root: Path | None = None) -> list[TemplatePackage]:
    root = (root or repo_root()).resolve()
    packages: list[TemplatePackage] = []
    for manifest_path in _scan_manifest_paths(root):
        validator = _validator_for_manifest(manifest_path)
        is_canonical, skill_root = _canonical_package_shape(manifest_path.parent, validator)
        try:
            preliminary = load_manifest(manifest_path)
            template = preliminary.get("template", {})
            template_id = str(template.get("id") or "") if isinstance(template, dict) else ""
            version = str(template.get("version") or "") if isinstance(template, dict) else ""
        except TemplateToolError:
            template_id = ""
            version = ""
            skill_root = skill_root or (manifest_path.parent.parents[3] if len(manifest_path.parent.parents) > 3 else None)
        is_default = bool(skill_root and template_id and version and _default_markers(skill_root, template_id, version))
        packages.append(
            inspect_manifest_package(
                manifest_path.parent,
                validator,
                is_canonical=is_canonical,
                is_default=is_default,
            )
        )

    by_identity: dict[tuple[str, str], list[TemplatePackage]] = defaultdict(list)
    for package in packages:
        if package.template_id and package.version:
            by_identity[(package.template_id, package.version)].append(package)
    for identity, duplicates in by_identity.items():
        if len(duplicates) <= 1:
            continue
        locations = ", ".join(item.package_dir.as_posix() for item in duplicates)
        for package in duplicates:
            package.errors.append(f"duplicate template id/version {identity[0]} {identity[1]}: {locations}")
    def sort_key(package: TemplatePackage) -> tuple[str, tuple[int, int, int], str]:
        try:
            version = parse_semver(package.version).as_tuple()
        except TemplateToolError:
            version = (2**31 - 1, 2**31 - 1, 2**31 - 1)
        return package.template_id, version, package.package_dir.as_posix().casefold()

    return sorted(packages, key=sort_key)


def find_validator_for_package(package_dir: Path, root: Path | None = None, *, template_id: str | None = None, format_name: str | None = None) -> Path | None:
    manifest_path = package_dir / "manifest.yaml"
    local = _validator_for_manifest(manifest_path)
    if local is not None:
        return local
    root = (root or repo_root()).resolve()
    candidates: list[Path] = []
    for package in discover_packages(root):
        if package.validator is None:
            continue
        if template_id and package.template_id != template_id:
            continue
        if format_name and package.format != format_name:
            continue
        if package.validator not in candidates:
            candidates.append(package.validator)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    raise TemplateToolError(
        "owner validator is ambiguous; pass a package within a skill template tree: "
        + ", ".join(path.as_posix() for path in candidates)
    )


def find_discovered_package(path: Path, root: Path | None = None) -> TemplatePackage:
    target = path.resolve()
    for package in discover_packages(root):
        if package.package_dir.resolve() == target:
            return package
    raise TemplateToolError(f"template package was not discovered under the repository root: {path}")
