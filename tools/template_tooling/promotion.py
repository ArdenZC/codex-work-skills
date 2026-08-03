"""Atomically promote a validated package into its canonical template tree."""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
import os
from pathlib import Path
from typing import Any

from .discovery import discover_packages
from .models import TemplateToolError
from .paths import display_path, paths_overlap
from .validation import package_from_path, validate_package_path, validation_succeeded
from .manifest import parse_semver


def _canonical_target(package: Any, canonical: list[Any]) -> Path:
    if package.validator is None:
        raise TemplateToolError("cannot compute canonical target without an owner validator")
    skill_root = package.validator.parent.parent
    prefix = "v" if any(item.package_dir.name.startswith("v") for item in canonical) else ""
    return (skill_root / "assets" / "templates" / package.template_id / f"{prefix}{package.version}").resolve(strict=False)


def _run_repo_validator(root: Path) -> dict[str, Any]:
    validator = root / "tests" / "validate_template_packages.py"
    if not validator.is_file():
        raise TemplateToolError(f"repository-wide validator was not found: {validator}")
    command = [sys.executable, str(validator)]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TemplateToolError(f"repository-wide validator could not run: {exc}") from exc
    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def promote_package(package_dir: Path, root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    package = package_from_path(package_dir, root)
    if any(item.package_dir.resolve() == package.package_dir.resolve() and item.is_canonical for item in discover_packages(root)):
        raise TemplateToolError("canonical packages cannot be promoted over themselves")
    if package.errors:
        raise TemplateToolError("package identity validation failed: " + "; ".join(package.errors))
    target_version = parse_semver(package.version)
    canonical = [
        item
        for item in discover_packages(root)
        if item.is_canonical and item.template_id == package.template_id
    ]
    if any(item.errors for item in canonical):
        raise TemplateToolError("cannot promote while an existing canonical package is invalid")
    if target_version.minor not in {item.semver.minor for item in canonical}:
        raise TemplateToolError("Template minor is not supported by the current generator contract.")

    validation = validate_package_path(package.package_dir, root, identity_only=False)
    if not validation_succeeded(validation):
        details = "; ".join(validation.get("errors", []))
        validator = validation.get("validator") or {}
        stderr = str(validator.get("stderr") or "").strip()
        if stderr:
            details = f"{details}; validator stderr: {stderr}"
        raise TemplateToolError(f"full template validation failed: {details}")

    target = _canonical_target(package, canonical)
    canonical_root = target.parent
    if paths_overlap(package.package_dir, canonical_root):
        raise TemplateToolError("promotion source overlaps the canonical target tree")
    if target.exists() or target.is_symlink():
        raise TemplateToolError(f"canonical target already exists: {target}")
    stage = canonical_root / f".{target.name}.{uuid.uuid4().hex}.stage"
    result: dict[str, Any] = {
        "package": display_path(package.package_dir, root),
        "target": display_path(target, root),
        "version": package.version,
        "template_sha256": package.fingerprint,
        "validation": validation,
        "dry_run": dry_run,
    }
    if dry_run:
        result["repo_validation"] = {"status": "not_run", "reason": "dry-run"}
        return result

    moved = False
    try:
        stage.parent.mkdir(parents=True, exist_ok=True)
        from .scaffold import _copy_tree_no_symlinks

        _copy_tree_no_symlinks(package.package_dir, stage)
        if target.exists() or target.is_symlink():
            raise TemplateToolError(f"canonical target appeared during promotion: {target}")
        stage.replace(target)
        moved = True
        rediscovered = [
            item
            for item in discover_packages(root)
            if item.package_dir.resolve() == target.resolve()
        ]
        if len(rediscovered) != 1 or rediscovered[0].errors:
            detail = "; ".join(rediscovered[0].errors) if rediscovered else "target was not discovered"
            raise TemplateToolError(f"promoted package failed rediscovery: {detail}")
        repo_validation = _run_repo_validator(root)
        result["repo_validation"] = repo_validation
        if repo_validation["exit_code"] != 0:
            details = (repo_validation.get("stderr") or repo_validation.get("stdout") or "").strip()
            suffix = f": {details}" if details else ""
            raise TemplateToolError(f"repository-wide validator failed after promotion{suffix}")
        return result
    except Exception:
        if moved and target.exists() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
