"""Create a non-canonical template package from a canonical base."""

from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .discovery import discover_packages
from .manifest import load_manifest, manifest_reference, package_template_path, sha256_file
from .models import TemplatePackage, TemplateToolError, package_dir_matches_version, parse_semver
from .paths import display_path, is_within, paths_overlap, require_no_overlap


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
    if source.is_symlink():
        raise TemplateToolError(f"refusing to copy symlinked package: {source}")
    created: list[Path] = []
    destination.mkdir(parents=True, exist_ok=False)
    created.append(destination)
    for source_path in sorted(source.rglob("*"), key=lambda item: item.as_posix().lower()):
        relative = source_path.relative_to(source)
        target = destination / relative
        if source_path.is_symlink():
            raise TemplateToolError(f"refusing to copy symlinked package entry: {source_path}")
        if source_path.is_dir():
            target.mkdir()
            created.append(target)
        elif source_path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            created.append(target)
    return created


def _tree_fingerprints(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if path.is_symlink():
            raise TemplateToolError(f"symlink is not allowed in package comparison: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256_file(path)
    return result


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
            return package
    raise TemplateToolError(f"base package was not discovered: {base_dir}")


def _report_path(output_dir: Path, explicit: Path | None) -> Path:
    return (explicit or (output_dir.parent / "scaffold-report.json")).resolve(strict=False)


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
    base = _find_base(base_dir, root)
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
    report = _report_path(output_dir, report_path)
    if paths_overlap(report, output_dir):
        raise TemplateToolError("scaffold report must be outside the template package")
    if output_dir.exists() or output_dir.is_symlink():
        raise TemplateToolError(f"scaffold output already exists: {output_dir}")
    if report.exists() or report.is_symlink():
        raise TemplateToolError(f"scaffold report already exists: {report}")

    dependencies = _dependency_plan(base, output_dir)
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

        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(report_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_written = True
    except Exception:
        if report_written or report.is_file() or report.is_symlink():
            report.unlink(missing_ok=True)
        for destination in reversed(moved):
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination, ignore_errors=True)
            elif destination.exists() or destination.is_symlink():
                destination.unlink(missing_ok=True)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
    return report_data
