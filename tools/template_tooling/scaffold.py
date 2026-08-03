"""Create a non-canonical template package from a canonical base."""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .discovery import discover_packages, owner_skill_root
from .manifest import load_manifest, manifest_reference, package_template_path, sha256_file
from .models import TemplatePackage, TemplateToolError, package_dir_matches_version, parse_semver
from .paths import (
    atomic_write_text,
    copy_tree_no_symlinks,
    display_path,
    is_within,
    paths_overlap,
    remove_path_or_raise,
    require_no_overlap,
    tree_fingerprints,
    validate_windows_component,
)
from .validation import validate_package_path, validation_succeeded


UNSUPPORTED_MINOR_REASON = "Template minor is not supported by the current generator contract."


def _replace_section_scalar(text: str, section: str, key: str, value: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    in_section = False
    section_indent = -1
    replaced = False
    pattern = re.compile(r"^([ \t]*" + re.escape(key) + r"[ \t]*:[ \t]*)(.*?)(\r?\n)?$")
    output: list[str] = []
    for line in lines:
        section_match = re.match(r"^(\s*)([A-Za-z0-9_-]+)\s*:", line)
        if section_match and len(section_match.group(1)) == 0:
            in_section = section_match.group(2) == section
            section_indent = 0 if in_section else -1
        match = pattern.match(line) if in_section else None
        if match and len(match.group(1)) > section_indent and not replaced:
            newline = match.group(3) or ""
            output.append(f"{match.group(1)}{value}{newline}")
            replaced = True
        else:
            output.append(line)
    return "".join(output), replaced


def _update_manifest_text(
    source_manifest: Path,
    target_manifest: Path,
    *,
    version: str,
    fingerprint: str,
    generator_version: str | None,
) -> list[str]:
    text = source_manifest.read_text(encoding="utf-8")
    changed: list[str] = []
    for section, key, value, field in (
        ("template", "version", version, "template.version"),
        ("fingerprint", "sha256", fingerprint, "fingerprint.sha256"),
        ("fingerprint", "value", fingerprint, "fingerprint.value"),
    ):
        text, replaced = _replace_section_scalar(text, section, key, value)
        if not replaced:
            raise TemplateToolError(f"manifest is missing {field}: {source_manifest}")
        changed.append(field)
    if generator_version is not None:
        text, replaced = _replace_section_scalar(text, "generator", "version", generator_version)
        if not replaced:
            raise TemplateToolError(f"manifest is missing generator.version: {source_manifest}")
        changed.append("generator.version")
    target_manifest.write_text(text, encoding="utf-8", newline="")
    return changed


def _without_mutable_manifest_fields(manifest: dict[str, Any], *, generator_version: str | None) -> dict[str, Any]:
    value = copy.deepcopy(manifest)
    template = value.get("template")
    if isinstance(template, dict):
        template.pop("version", None)
    fingerprint = value.get("fingerprint")
    if isinstance(fingerprint, dict):
        fingerprint.pop("sha256", None)
        fingerprint.pop("value", None)
    if generator_version is not None:
        generator = value.get("generator")
        if isinstance(generator, dict):
            generator.pop("version", None)
    return value


def _copy_tree_no_symlinks(source: Path, destination: Path) -> list[Path]:
    return copy_tree_no_symlinks(source, destination)


def _tree_fingerprints(root: Path) -> dict[str, str]:
    return tree_fingerprints(root)


def _dependency_plan(base: TemplatePackage, output_dir: Path) -> list[tuple[Path, Path]]:
    base_manifest = manifest_reference(base.manifest, "base_manifest", base.manifest_path)
    base_template = manifest_reference(base.manifest, "base_template", base.manifest_path)
    if base_manifest is None and base_template is None:
        return []
    if base_manifest is None or base_template is None:
        raise TemplateToolError("template.base_manifest and template.base_template must be declared together")
    source_package = base_manifest.parent
    if not source_package.is_dir() or not (source_package / "manifest.yaml").is_file():
        raise TemplateToolError(f"base package dependency is missing: {source_package}")
    destination_manifest = (output_dir / str(base.manifest["template"]["base_manifest"])).resolve(strict=False)
    destination_package = destination_manifest.parent
    if not is_within(destination_package, output_dir.parent):
        raise TemplateToolError(f"base package dependency escapes scaffold workspace: {destination_package}")
    if destination_package == output_dir:
        raise TemplateToolError("base package dependency overlaps scaffold output")
    return [(source_package, destination_package)]


def _find_base(base_dir: Path, root: Path) -> TemplatePackage:
    target = base_dir.resolve()
    for package in discover_packages(root):
        if package.package_dir.resolve() == target:
            if not package.is_canonical or package.errors:
                detail = "; ".join(package.errors) or "package is not canonical"
                raise TemplateToolError(f"base package is not a valid canonical package: {detail}")
            validation = validate_package_path(package.package_dir, root, identity_only=False)
            if not validation_succeeded(validation):
                detail = "; ".join(validation.get("errors", []))
                raise TemplateToolError(f"base package full validation failed: {detail}")
            return package
    raise TemplateToolError(f"base package was not discovered: {base_dir}")


def _report_path(output_dir: Path, explicit: Path | None, template_id: str, version: str) -> Path:
    path = explicit or (output_dir.parent / f"scaffold-report-{template_id}-{version}.json")
    return path.expanduser().absolute()


def _protected_report_paths(root: Path, base: TemplatePackage, canonical: list[TemplatePackage], dependencies: list[tuple[Path, Path]], output_dir: Path) -> list[Path]:
    protected: list[Path] = [
        root / "tools",
        root / "tests",
        root / ".github",
        base.package_dir,
        output_dir,
    ]
    for package in canonical:
        protected.append(package.package_dir)
        if package.validator is not None:
            owner = owner_skill_root(package)
            protected.extend((owner / "assets" / "templates", owner / "assets" / "templates" / package.template_id))
    for source, destination in dependencies:
        protected.extend((source, destination))
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "manifest.yaml" or path.name.endswith(".schema.json") or path.suffix.lower() in {".docx", ".xls", ".xlsx"}:
            protected.append(path)
    return protected


def scaffold_package(
    base_dir: Path,
    output_dir: Path,
    root: Path,
    *,
    version: str,
    generator_version: str | None = None,
    allow_unsupported_minor: bool = False,
    dry_run: bool = False,
    report_path: Path | None = None,
) -> dict[str, Any]:
    if generator_version is not None:
        generator_semver = parse_semver(generator_version)
    else:
        generator_semver = None
    base = _find_base(base_dir, root)
    supported_major = base.manifest.get("generator", {}).get("supported_major")
    if generator_semver is not None and generator_semver.major != supported_major:
        raise TemplateToolError(
            f"generator version major {generator_semver.major} does not match generator.supported_major {supported_major}"
        )
    target_version = parse_semver(version)
    base_version = base.semver
    if target_version <= base_version:
        raise TemplateToolError(f"new version must be greater than base version: {version} <= {base.version}")
    if target_version.major != base_version.major:
        raise TemplateToolError("new version must keep the base major version")
    if not package_dir_matches_version(output_dir.name, version):
        raise TemplateToolError(f"output directory name must equal target version {version!r} or v{version!r}")

    all_packages = discover_packages(root)
    canonical_same_id = [item for item in all_packages if item.is_canonical and item.template_id == base.template_id]
    if any(item.errors for item in canonical_same_id):
        raise TemplateToolError("cannot scaffold while a canonical package for this template id is invalid")
    supported_minors = {item.semver.minor for item in canonical_same_id}
    unsupported_minor = target_version.minor not in supported_minors
    if unsupported_minor and not allow_unsupported_minor:
        raise TemplateToolError(f"template minor {target_version.minor} is not supported by the current generator contract")

    canonical_roots: list[Path] = []
    if base.validator is not None:
        skill_root = base.validator.parent.parent
        canonical_roots.append(skill_root / "assets" / "templates" / base.template_id)
    protected = [base.package_dir, *[item.package_dir for item in canonical_same_id], *canonical_roots]
    require_no_overlap(output_dir, protected, label="scaffold output")
    dependencies = _dependency_plan(base, output_dir)
    report = _report_path(output_dir, report_path, base.template_id, version)
    if report.parent.resolve(strict=False) != output_dir.parent.resolve(strict=False):
        raise TemplateToolError("scaffold report must be in the output package sibling directory")
    if report.suffix.casefold() != ".json":
        raise TemplateToolError("scaffold report filename must use the .json suffix")
    validate_windows_component(report.name, label="scaffold report filename")
    all_canonical = [item for item in all_packages if item.is_canonical]
    for protected_path in _protected_report_paths(root, base, all_canonical, dependencies, output_dir):
        if paths_overlap(report, protected_path):
            raise TemplateToolError(f"scaffold report overlaps protected path: {report} <> {protected_path}")
    if output_dir.exists() or output_dir.is_symlink():
        raise TemplateToolError(f"scaffold output already exists: {output_dir}")
    if report.exists() or report.is_symlink():
        raise TemplateToolError(f"scaffold report already exists: {report}")

    for source, destination in dependencies:
        if destination.exists() or destination.is_symlink():
            if not destination.is_dir() or _tree_fingerprints(source) != _tree_fingerprints(destination):
                raise TemplateToolError(f"scaffold dependency already exists and differs: {destination}")

    template_relative = base.template_path.relative_to(base.package_dir)
    new_template_sha = sha256_file(base.template_path)
    file_list = [
        (output_dir / "manifest.yaml"),
        (output_dir / template_relative),
    ]
    changelog = base.package_dir / "CHANGELOG.md"
    if changelog.is_file():
        file_list.append(output_dir / "CHANGELOG.md")
    for source, destination in dependencies:
        file_list.extend(
            destination / path.relative_to(source)
            for path in sorted(source.rglob("*"), key=lambda item: item.as_posix().lower())
            if path.is_file()
        )

    report_data: dict[str, Any] = {
        "tool_version": "0.1.0",
        "base_package": display_path(base.package_dir, root),
        "base_version": base.version,
        "base_sha256": base.fingerprint,
        "base_validation": {"status": "passed", "full_validation": True, "validation_scope": "package"},
        "owner_skill": display_path(owner_skill_root(base), root) if base.validator is not None else None,
        "version": version,
        "template_sha256": new_template_sha,
        "changed_manifest_fields": ["template.version", "fingerprint.sha256", "fingerprint.value"]
        + (["generator.version"] if generator_version is not None else []),
        "promotable": not unsupported_minor,
        "warnings": [],
        "files": [display_path(path, root) for path in file_list],
        "report_path": display_path(report, root),
        "dry_run": dry_run,
    }
    if unsupported_minor:
        report_data["reason"] = UNSUPPORTED_MINOR_REASON
        report_data["warnings"].append(UNSUPPORTED_MINOR_REASON)

    if dry_run:
        return report_data

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.stage"
    moved: list[Path] = []
    report_written = False
    try:
        stage.mkdir()
        staged_output = stage / output_dir.name
        staged_output.mkdir()
        shutil.copy2(base.template_path, staged_output / template_relative)
        if changelog.is_file():
            shutil.copy2(changelog, staged_output / "CHANGELOG.md")
        staged_manifest = staged_output / "manifest.yaml"
        changed = _update_manifest_text(
            base.manifest_path,
            staged_manifest,
            version=version,
            fingerprint=new_template_sha,
            generator_version=generator_version,
        )
        loaded_new = load_manifest(staged_manifest)
        if loaded_new.get("template", {}).get("version") != version:
            raise TemplateToolError("scaffold manifest version update did not persist")
        if _without_mutable_manifest_fields(loaded_new, generator_version=generator_version) != _without_mutable_manifest_fields(base.manifest, generator_version=generator_version):
            raise TemplateToolError("scaffold changed manifest fields outside the declared mutable fields")
        if generator_version is None:
            if loaded_new.get("generator", {}).get("version") != base.manifest.get("generator", {}).get("version"):
                raise TemplateToolError("scaffold changed generator.version unexpectedly")
        report_data["changed_manifest_fields"] = changed

        staged_dependencies: list[tuple[Path, Path]] = []
        for source, destination in dependencies:
            if destination.exists():
                continue
            staged_dependency = stage / destination.name
            _copy_tree_no_symlinks(source, staged_dependency)
            staged_dependencies.append((staged_dependency, destination))
        staged_items = staged_dependencies + [(staged_output, output_dir)]
        for staged_item, destination in staged_items:
            if destination.exists() or destination.is_symlink():
                raise TemplateToolError(f"path appeared during scaffold transaction: {destination}")
            staged_item.replace(destination)
            moved.append(destination)

        if os.environ.get("TEMPLATE_TOOL_TEST_FAIL_REPORT_COMMIT") == "1":
            raise OSError("injected scaffold report commit failure")
        atomic_write_text(report, json.dumps(report_data, ensure_ascii=False, indent=2) + "\n")
        report_written = True
    except Exception as exc:
        rollback_errors: list[str] = []
        if report_written or report.is_file() or report.is_symlink():
            try:
                remove_path_or_raise(report)
            except Exception as rollback_error:
                rollback_errors.append(f"report cleanup failed: {rollback_error}")
        for destination in reversed(moved):
            try:
                remove_path_or_raise(destination)
            except Exception as rollback_error:
                rollback_errors.append(f"rollback failed for {destination}: {rollback_error}")
        if rollback_errors:
            raise TemplateToolError(f"scaffold transaction failed: {exc}; {'; '.join(rollback_errors)}") from exc
        raise
    finally:
        if stage.exists():
            remove_path_or_raise(stage)
    return report_data
