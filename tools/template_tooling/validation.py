"""Identity checks and owner-validator execution."""

from __future__ import annotations

import subprocess
import sys
import shutil
import uuid
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from .discovery import find_validator_for_package
from .manifest import inspect_manifest_package, load_manifest
from .models import TemplatePackage, TemplateToolError
from .paths import display_path, is_within


def _display_command(command: list[str], root: Path) -> list[str]:
    displayed: list[str] = []
    for token in command:
        candidate = Path(token)
        if candidate.is_absolute():
            displayed.append(display_path(candidate, root) or "<external>")
        else:
            displayed.append(token)
    return displayed


def _display_output(value: str, package: TemplatePackage, root: Path) -> str:
    for path in (package.package_dir, package.template_path, package.manifest_path):
        value = value.replace(path.as_posix(), display_path(path, root) or "<external>")
        value = value.replace(str(path), display_path(path, root) or "<external>")
    return value


def _validation_scope(package: TemplatePackage, root: Path) -> tuple[TemplatePackage, Path | None]:
    """Place external packages in a disposable owner-tree shadow for validation.

    Some owner validators resolve a relative v1.0 baseline against the
    canonical template root.  The shadow keeps the submitted package bytes and
    manifest unchanged while giving that validator the same filesystem
    context it will have after promotion.
    """
    if package.validator is None:
        return package, None
    skill_root = package.validator.parent.parent
    canonical_root = (skill_root / "assets" / "templates" / package.template_id).resolve()
    if is_within(package.package_dir, canonical_root):
        return package, None
    shadow = canonical_root / f".template-tool-validation-{uuid.uuid4().hex}"
    shadow.parent.mkdir(parents=True, exist_ok=True)
    from .scaffold import _copy_tree_no_symlinks

    try:
        _copy_tree_no_symlinks(package.package_dir, shadow)
    except Exception:
        if shadow.exists():
            shutil.rmtree(shadow, ignore_errors=True)
        raise
    template_relative = package.template_path.relative_to(package.package_dir)
    return replace(
        package,
        package_dir=shadow,
        template_path=shadow / template_relative,
        manifest_path=shadow / "manifest.yaml",
    ), shadow


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


def validate_package_path(package_dir: Path, root: Path, *, identity_only: bool = False, timeout: int = 900) -> dict[str, Any]:
    package = package_from_path(package_dir, root)
    report = identity_report(package, root)
    if package.errors or identity_only:
        return report

    if package.validator is None:
        report["status"] = "failed"
        report["errors"].append("owner validator is unavailable")
        return report

    validator_package = package
    shadow: Path | None = None
    try:
        validator_package, shadow = _validation_scope(package, root)
    except (OSError, TemplateToolError, ValueError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"cannot prepare validator package shadow: {exc}")
        return report

    command = [
        sys.executable,
        str(validator_package.validator),
        "--template",
        str(validator_package.template_path),
        "--manifest",
        str(validator_package.manifest_path),
        "--json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
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
            "stdout": _display_output(exc.stdout or "", validator_package, root),
            "stderr": _display_output(exc.stderr or "", validator_package, root),
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
    finally:
        if shadow is not None and shadow.exists():
            shutil.rmtree(shadow, ignore_errors=True)

    report["validator"] = {
        "command": _display_command(command, root),
        "exit_code": result.returncode,
        "stdout": _display_output(result.stdout, validator_package, root),
        "stderr": _display_output(result.stderr, validator_package, root),
    }
    report["full_validation"] = True
    report["validation_scope"] = "canonical_shadow" if shadow is not None else "package"
    if result.returncode != 0:
        report["status"] = "failed"
        report["errors"].append(f"template validator exited with code {result.returncode}")
        return report
    report["status"] = "passed"
    return report


def validation_succeeded(report: dict[str, Any], *, allow_identity_only: bool = False) -> bool:
    if report.get("errors"):
        return False
    if report.get("status") == "passed":
        return True
    return allow_identity_only and report.get("status") == "identity_only"
