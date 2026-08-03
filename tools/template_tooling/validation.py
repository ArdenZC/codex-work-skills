"""Identity checks and owner-validator execution in an isolated workspace."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from .discovery import discover_packages, find_validator_for_package, owner_skill_root, trusted_validator_for_package
from .manifest import (
    inspect_manifest_package,
    load_manifest,
    manifest_reference,
    package_template_path,
    sha256_file,
)
from .models import TemplatePackage, TemplateToolError
from .paths import copy_tree_no_symlinks, display_path, is_within, remove_path_or_raise, tree_fingerprints


def _display_command(command: list[str], root: Path) -> list[str]:
    displayed: list[str] = []
    for token in command:
        candidate = Path(token)
        if candidate.is_absolute():
            displayed.append(display_path(candidate, root) or "<external>")
        else:
            displayed.append(token)
    return displayed


def _display_output(value: str, package: TemplatePackage, root: Path, *, temporary_root: Path | None = None) -> str:
    for path in (package.package_dir, package.template_path, package.manifest_path, package.validator):
        if path is None:
            continue
        replacement = display_path(path, root) or "<external>"
        value = value.replace(path.as_posix(), replacement)
        value = value.replace(str(path), replacement)
    if temporary_root is not None:
        for raw_path in (temporary_root.as_posix(), str(temporary_root)):
            value = value.replace(raw_path, "<external>")
            value = value.replace(raw_path.replace("\\", "\\\\"), "<external>")
    return value


def _copy_regular_file(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise TemplateToolError(f"symlink is not allowed in validation workspace: {source}")
    mode = source.stat(follow_symlinks=False).st_mode
    if not stat.S_ISREG(mode):
        raise TemplateToolError(f"only regular files are allowed in validation workspace: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_owner_support(owner: Path, isolated_skill: Path, template_id: str) -> None:
    scripts = owner / "scripts"
    if not scripts.is_dir():
        raise TemplateToolError(f"owner validator scripts directory was not found: {scripts}")
    copy_tree_no_symlinks(scripts, isolated_skill / "scripts")

    source_schemas = owner / "schemas"
    if source_schemas.is_dir():
        copy_tree_no_symlinks(source_schemas, isolated_skill / "schemas")

    source_assets = owner / "assets"
    target_assets = isolated_skill / "assets"
    target_assets.mkdir(parents=True, exist_ok=False)
    if source_assets.is_dir():
        for entry in sorted(source_assets.iterdir(), key=lambda item: item.name.casefold()):
            if entry.name == "templates":
                continue
            target = target_assets / entry.name
            if entry.is_symlink():
                raise TemplateToolError(f"symlink is not allowed in validation workspace: {entry}")
            if entry.is_dir():
                copy_tree_no_symlinks(entry, target)
            elif entry.is_file():
                _copy_regular_file(entry, target)

    source_template_root = source_assets / "templates" / template_id
    target_template_root = target_assets / "templates" / template_id
    target_template_root.mkdir(parents=True, exist_ok=False)
    if source_template_root.is_dir():
        for entry in sorted(source_template_root.iterdir(), key=lambda item: item.name.casefold()):
            if entry.is_symlink():
                raise TemplateToolError(f"symlink is not allowed in validation workspace: {entry}")
            if entry.is_dir():
                copy_tree_no_symlinks(entry, target_template_root / entry.name)


def _copy_dependency_closure(
    source_package: Path,
    destination_root: Path,
    *,
    copied: dict[Path, Path],
    active: set[Path],
) -> None:
    source_package = source_package.resolve()
    destination_package = destination_root / source_package.name
    if source_package in active:
        raise TemplateToolError(f"template dependency cycle detected at {source_package}")
    existing = copied.get(source_package)
    if existing is not None:
        if existing != destination_package:
            raise TemplateToolError(f"template dependency maps to two archive locations: {source_package}")
        return
    if not source_package.is_dir() or source_package.is_symlink():
        raise TemplateToolError(f"template dependency package is not a real directory: {source_package}")
    active.add(source_package)
    try:
        if destination_package.exists():
            if tree_fingerprints(source_package) != tree_fingerprints(destination_package):
                raise TemplateToolError(f"validation dependency conflicts with owner baseline: {source_package}")
        else:
            copy_tree_no_symlinks(source_package, destination_package)
        copied[source_package] = destination_package
        manifest_path = source_package / "manifest.yaml"
        manifest = load_manifest(manifest_path)
        base_manifest = manifest_reference(manifest, "base_manifest", manifest_path)
        base_template = manifest_reference(manifest, "base_template", manifest_path)
        if (base_manifest is None) != (base_template is None):
            raise TemplateToolError("template.base_manifest and template.base_template must be declared together")
        if base_manifest is None:
            return
        if base_manifest.parent != base_template.parent:
            raise TemplateToolError("template.base_manifest and template.base_template must share a package")
        if not is_within(base_manifest.parent, source_package.parent):
            raise TemplateToolError(f"template dependency escapes its template-id root: {base_manifest.parent}")
        if not base_manifest.is_file() or not base_template.is_file():
            raise TemplateToolError(f"template dependency is missing: {base_manifest.parent}")
        _copy_dependency_closure(
            base_manifest.parent,
            destination_root,
            copied=copied,
            active=active,
        )
    finally:
        active.remove(source_package)


def _prepare_isolated_package(package: TemplatePackage) -> tuple[TemplatePackage, tempfile.TemporaryDirectory[str], Path]:
    if package.validator is None:
        raise TemplateToolError("owner validator is unavailable")
    owner = owner_skill_root(package)
    temporary = tempfile.TemporaryDirectory(prefix="template-tool-validation-")
    temporary_root = Path(temporary.name)
    isolated_skill = temporary_root / "skill"
    isolated_skill.mkdir()
    try:
        _copy_owner_support(owner, isolated_skill, package.template_id)
        target_root = isolated_skill / "assets" / "templates" / package.template_id
        destination_package = target_root / package.package_dir.name

        # Copy owner baselines first, then the submitted package and its declared
        # dependencies.  This gives validators their normal __file__ layout while
        # ensuring all input bytes are inside the disposable workspace.
        copied: dict[Path, Path] = {}
        if destination_package.exists():
            remove_path_or_raise(destination_package)
        copy_tree_no_symlinks(package.package_dir, destination_package)
        copied[package.package_dir.resolve()] = destination_package
        manifest_path = package.manifest_path
        manifest = load_manifest(manifest_path)
        base_manifest = manifest_reference(manifest, "base_manifest", manifest_path)
        base_template = manifest_reference(manifest, "base_template", manifest_path)
        if (base_manifest is None) != (base_template is None):
            raise TemplateToolError("template.base_manifest and template.base_template must be declared together")
        if base_manifest is not None:
            if base_manifest.parent != base_template.parent or not base_manifest.is_file() or not base_template.is_file():
                raise TemplateToolError("template base dependency is incomplete")
            _copy_dependency_closure(base_manifest.parent, target_root, copied=copied, active=set())

        validator_relative = package.validator.resolve().relative_to(owner / "scripts")
        isolated_validator = isolated_skill / "scripts" / validator_relative
        isolated_manifest = destination_package / "manifest.yaml"
        isolated_template = package_template_path(load_manifest(isolated_manifest), isolated_manifest)
        isolated_package = replace(
            package,
            package_dir=destination_package,
            manifest_path=isolated_manifest,
            template_path=isolated_template,
            validator=isolated_validator,
        )
        return isolated_package, temporary, temporary_root
    except Exception:
        temporary.cleanup()
        if temporary_root.exists():
            try:
                remove_path_or_raise(temporary_root)
            except Exception:
                pass
        raise


def package_from_path(package_dir: Path, root: Path) -> TemplatePackage:
    package_dir = package_dir.resolve()
    manifest_path = package_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise TemplateToolError(f"manifest.yaml was not found in package: {package_dir}")
    manifest = load_manifest(manifest_path)
    template = manifest.get("template") if isinstance(manifest, dict) else None
    template_id = str(template.get("id") or "") if isinstance(template, dict) else ""
    format_name = str(template.get("format") or "") if isinstance(template, dict) else ""
    validator = find_validator_for_package(package_dir, root, template_id=template_id, format_name=format_name)
    return inspect_manifest_package(
        package_dir,
        validator,
        is_canonical=False,
        is_default=False,
    )


def identity_report(package: TemplatePackage, root: Path) -> dict[str, Any]:
    return {
        "package": package.to_dict(root),
        "status": "identity_only" if not package.errors else "failed",
        "full_validation": False,
        "errors": list(package.errors),
        "warnings": list(package.warnings),
        "validator": None,
    }


def _run_validator(
    package: TemplatePackage,
    root: Path,
    report: dict[str, Any],
    *,
    validation_scope: str,
    temporary_root: Path | None = None,
    timeout: int,
) -> dict[str, Any]:
    if package.validator is None:
        report["status"] = "failed"
        report["errors"].append("owner validator is unavailable")
        return report
    try:
        if validation_scope == "package":
            trusted_validator_for_package(package, root)
        elif (
            temporary_root is None
            or package.validator.is_symlink()
            or not package.validator.is_file()
            or not is_within(package.validator, temporary_root)
        ):
            raise TemplateToolError("isolated validator is not inside the disposable validation workspace")
    except (OSError, TemplateToolError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"untrusted owner validator: {exc}")
        return report
    command = [
        sys.executable,
        str(package.validator),
        "--template",
        str(package.template_path),
        "--manifest",
        str(package.manifest_path),
        "--json",
    ]
    cwd = package.validator.parent.parent
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        report["status"] = "failed"
        report["errors"].append(f"template validator timed out after {timeout}s")
        report["validator"] = {
            "command": _display_command(command, root),
            "exit_code": None,
            "stdout": _display_output(exc.stdout or "", package, root, temporary_root=temporary_root),
            "stderr": _display_output(exc.stderr or "", package, root, temporary_root=temporary_root),
        }
        return report
    except OSError as exc:
        report["status"] = "failed"
        report["errors"].append(f"cannot execute template validator: {exc}")
        report["validator"] = {
            "command": _display_command(command, root),
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
        }
        return report
    report["validator"] = {
        "command": _display_command(command, root),
        "exit_code": result.returncode,
        "stdout": _display_output(result.stdout, package, root, temporary_root=temporary_root),
        "stderr": _display_output(result.stderr, package, root, temporary_root=temporary_root),
    }
    report["full_validation"] = True
    report["validation_scope"] = validation_scope
    if result.returncode != 0:
        report["status"] = "failed"
        report["errors"].append(f"template validator exited with code {result.returncode}")
        return report
    report["status"] = "passed"
    return report


def validate_package_path(package_dir: Path, root: Path, *, identity_only: bool = False, timeout: int = 900) -> dict[str, Any]:
    package = package_from_path(package_dir, root)
    report = identity_report(package, root)
    if package.errors or identity_only:
        return report
    if package.validator is None:
        report["status"] = "failed"
        report["errors"].append("owner validator is unavailable")
        return report
    try:
        trusted_validator_for_package(package, root)
    except (OSError, TemplateToolError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"untrusted owner validator: {exc}")
        return report

    isolated = None
    temporary_root: Path | None = None
    validator_package = package
    validation_scope = "package"
    try:
        owner = owner_skill_root(package)
        canonical_package = any(
            item.is_canonical and item.package_dir.resolve() == package.package_dir.resolve()
            for item in discover_packages(root)
        )
        if not canonical_package:
            validator_package, isolated, temporary_root = _prepare_isolated_package(package)
            validation_scope = "isolated_temp"
        return _run_validator(
            validator_package,
            root,
            report,
            validation_scope=validation_scope,
            temporary_root=temporary_root,
            timeout=timeout,
        )
    except (OSError, TemplateToolError, ValueError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"cannot prepare validator workspace: {exc}")
        return report
    finally:
        if isolated is not None:
            isolated.cleanup()
            if temporary_root is not None and temporary_root.exists():
                report.setdefault("errors", []).append("validation temporary workspace was not cleaned up")


def validate_package_with_owner(
    package_dir: Path,
    root: Path,
    owner_validator: Path,
    *,
    trusted_root: Path | None = None,
    timeout: int = 900,
) -> dict[str, Any]:
    """Validate an extracted package with the already-resolved owner validator."""
    package = inspect_manifest_package(
        package_dir.resolve(),
        owner_validator.resolve(),
        is_canonical=False,
        is_default=False,
    )
    report = identity_report(package, root)
    if package.errors:
        return report
    try:
        if trusted_root is not None:
            trusted_validator_for_package(package, trusted_root)
        elif owner_validator.is_symlink() or not owner_validator.is_file() or not is_within(owner_validator, root):
            raise TemplateToolError("owner validator is not a trusted regular file")
    except (OSError, TemplateToolError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"untrusted owner validator: {exc}")
        return report
    isolated = None
    temporary_root: Path | None = None
    try:
        validator_package, isolated, temporary_root = _prepare_isolated_package(package)
        return _run_validator(
            validator_package,
            root,
            report,
            validation_scope="isolated_temp",
            temporary_root=temporary_root,
            timeout=timeout,
        )
    except (OSError, TemplateToolError, ValueError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"cannot prepare validator workspace: {exc}")
        return report
    finally:
        if isolated is not None:
            isolated.cleanup()


def validation_succeeded(report: dict[str, Any], *, allow_identity_only: bool = False) -> bool:
    if report.get("errors"):
        return False
    if report.get("status") == "passed":
        return True
    return allow_identity_only and report.get("status") == "identity_only"
