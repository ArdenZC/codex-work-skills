"""Generic discovery of versioned template packages."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
import stat

from .manifest import inspect_manifest_package, load_manifest
from .git_trust import GitTrustIndex, trusted_script_files
from .models import TemplatePackage, TemplateToolError, parse_semver
from .paths import is_within, repo_root, safe_relative


def skill_root_for_validator(validator: Path) -> Path:
    return validator.resolve().parent.parent


def canonical_skill_root_for_package(package_dir: Path, root: Path) -> Path | None:
    """Return the owning skill root only for an in-repository package shape."""
    package = package_dir.resolve(strict=False)
    repository = root.resolve()
    if package_dir.is_symlink() or not is_within(package, repository):
        return None
    templates_root = package.parent.parent
    if templates_root.name != "templates" or templates_root.parent.name != "assets":
        return None
    skill_root = templates_root.parent.parent
    if not is_within(skill_root, repository):
        return None
    return skill_root


def _regular_local_file(path: Path, root: Path) -> Path | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            return None
    except OSError:
        return None
    resolved = path.resolve(strict=False)
    if not is_within(resolved, root):
        return None
    return resolved


def trusted_local_validator_for_canonical_package(
    package_dir: Path,
    root: Path,
    trust_index: GitTrustIndex | None = None,
) -> Path | None:
    """Resolve only the validator owned by a canonical in-repository Skill."""
    skill_root = canonical_skill_root_for_package(package_dir, root)
    if skill_root is None:
        return None
    candidate = skill_root / "scripts" / "validate_template.py"
    resolved = _regular_local_file(candidate, root.resolve())
    if resolved is None or resolved.parent != (skill_root / "scripts").resolve():
        return None
    trust_index = trust_index or GitTrustIndex.from_repo_root(root)
    try:
        trust_index.require_tracked_regular_file(resolved, label="Owner validator")
    except TemplateToolError:
        return None
    return resolved


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


def discover_packages(root: Path | None = None, *, trust_index: GitTrustIndex | None = None) -> list[TemplatePackage]:
    root = (root or repo_root()).resolve()
    trust_index = trust_index or GitTrustIndex.from_repo_root(root)
    packages: list[TemplatePackage] = []
    for manifest_path in _scan_manifest_paths(root):
        skill_root = canonical_skill_root_for_package(manifest_path.parent, root)
        is_canonical = skill_root is not None
        validator = (
            trusted_local_validator_for_canonical_package(manifest_path.parent, root, trust_index)
            if is_canonical
            else None
        )
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
                validator_error=(
                    "canonical-like package has no trusted Git-tracked owner validator"
                    if is_canonical
                    else None
                ),
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


def find_validator_for_package(
    package_dir: Path,
    root: Path | None = None,
    *,
    template_id: str | None = None,
    format_name: str | None = None,
    trust_index: GitTrustIndex | None = None,
) -> Path | None:
    root = (root or repo_root()).resolve()
    trust_index = trust_index or GitTrustIndex.from_repo_root(root)
    local_shape = canonical_skill_root_for_package(package_dir, root)
    local = trusted_local_validator_for_canonical_package(package_dir, root, trust_index)
    if local_shape is not None:
        return local
    candidates: list[Path] = []
    for package in discover_packages(root, trust_index=trust_index):
        if not package.is_canonical or package.validator is None:
            continue
        if template_id and package.template_id != template_id:
            continue
        if format_name and package.format != format_name:
            continue
        trusted = trusted_local_validator_for_canonical_package(package.package_dir, root, trust_index)
        if trusted is not None and trusted not in candidates:
            candidates.append(trusted)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    raise TemplateToolError(
        "owner validator is ambiguous; pass a package within a skill template tree: "
        + ", ".join(path.as_posix() for path in candidates)
    )


def trusted_validator_for_package(
    package: TemplatePackage,
    root: Path,
    trust_index: GitTrustIndex | None = None,
) -> Path:
    """Re-check the resolved validator immediately before execution."""
    trust_index = trust_index or GitTrustIndex.from_repo_root(root)
    if package.validator is None:
        raise TemplateToolError("owner validator is unavailable")
    raw_validator = package.validator
    resolved_validator = _regular_local_file(raw_validator, root.resolve())
    if resolved_validator is None:
        raise TemplateToolError(f"owner validator is not a trusted regular file: {raw_validator}")
    trust_index.require_tracked_regular_file(resolved_validator, label="Owner validator")

    local_validator = trusted_local_validator_for_canonical_package(package.package_dir, root, trust_index)
    if local_validator is not None:
        if resolved_validator != local_validator:
            raise TemplateToolError("canonical package validator is outside its owning Skill")
        trusted_script_files(skill_root_for_validator(local_validator), trust_index)
        return local_validator

    candidates: list[Path] = []
    for candidate in discover_packages(root, trust_index=trust_index):
        if not candidate.is_canonical or candidate.template_id != package.template_id or candidate.format != package.format:
            continue
        trusted = trusted_local_validator_for_canonical_package(candidate.package_dir, root, trust_index)
        if trusted is not None and trusted not in candidates:
            candidates.append(trusted)
    if len(candidates) != 1:
        if not candidates:
            raise TemplateToolError("no trusted canonical owner validator was found")
        raise TemplateToolError(
            "owner validator is ambiguous: " + ", ".join(path.as_posix() for path in candidates)
        )
    if resolved_validator != candidates[0]:
        raise TemplateToolError("resolved validator is not the trusted canonical owner validator")
    trusted_script_files(skill_root_for_validator(candidates[0]), trust_index)
    return candidates[0]


def find_discovered_package(path: Path, root: Path | None = None) -> TemplatePackage:
    target = path.resolve()
    for package in discover_packages(root):
        if package.package_dir.resolve() == target:
            return package
    raise TemplateToolError(f"template package was not discovered under the repository root: {path}")
