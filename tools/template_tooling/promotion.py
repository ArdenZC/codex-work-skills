"""Atomically promote a validated package into its canonical template tree."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml

from .discovery import discover_packages, owner_skill_root
from .manifest import load_manifest, package_template_path, sha256_file
from .models import TemplateToolError, parse_semver
from .paths import copy_tree_no_symlinks, display_path, paths_overlap, remove_path_or_raise, tree_fingerprints
from .validation import (
    _assert_validator_runtime_state,
    _cleanup_validation_workspace,
    _validator_environment,
    package_from_path,
    validate_package_path,
    validation_succeeded,
)


def _canonical_target(package: Any, canonical: list[Any]) -> Path:
    if package.validator is None:
        raise TemplateToolError("cannot compute canonical target without an owner validator")
    skill_root = owner_skill_root(package)
    prefix = "v" if any(item.package_dir.name.startswith("v") for item in canonical) else ""
    return (skill_root / "assets" / "templates" / package.template_id / f"{prefix}{package.version}").resolve(strict=False)


def _run_repo_validator(root: Path) -> dict[str, Any]:
    validator = root / "tests" / "validate_template_packages.py"
    if not validator.is_file():
        raise TemplateToolError(f"repository-wide validator was not found: {validator}")
    command = [sys.executable, "-B", str(validator)]
    temporary = tempfile.TemporaryDirectory(prefix="template-tool-repo-validation-")
    temporary_root = Path(temporary.name)
    error: TemplateToolError | None = None
    runtime_error: TemplateToolError | None = None
    result: subprocess.CompletedProcess[str] | None = None
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_validator_environment(temporary_root),
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        error = TemplateToolError(f"repository-wide validator could not run: {exc}")
    try:
        _assert_validator_runtime_state(temporary_root)
    except (OSError, TemplateToolError) as exc:
        runtime_error = TemplateToolError(f"repository validator temporary workspace integrity failed: {exc}")
    cleanup_error = _cleanup_validation_workspace(temporary, temporary_root)
    if cleanup_error:
        cleanup_failure = TemplateToolError(cleanup_error)
        if error is not None:
            raise TemplateToolError(f"{error}; {cleanup_failure}") from error
        if runtime_error is not None:
            raise TemplateToolError(f"{runtime_error}; {cleanup_failure}") from runtime_error
        raise cleanup_failure
    if runtime_error is not None:
        raise runtime_error
    if error is not None:
        raise error
    assert result is not None
    return {
        "command": [str(item) for item in command],
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def remove_installed_target_or_raise(target: Path) -> None:
    """Remove a target created by this promotion and verify the rollback."""
    if os.environ.get("TEMPLATE_TOOL_TEST_FAIL_ROLLBACK") == "1":
        raise OSError("injected promotion rollback failure")
    remove_path_or_raise(target)
    if target.exists() or target.is_symlink():
        raise TemplateToolError(f"promotion rollback did not remove target: {target}")


def _validation_error(report: dict[str, Any]) -> str:
    details = "; ".join(str(item) for item in report.get("errors", [])) or "validator returned no diagnostic"
    validator = report.get("validator") or {}
    stderr = str(validator.get("stderr") or "").strip()
    if stderr:
        details = f"{details}; validator stderr: {stderr}"
    return details


def assert_tree_matches_snapshot(path: Path, expected: dict[str, str], *, phase: str) -> None:
    """Require byte-for-byte equality with the immutable promotion snapshot."""
    actual = tree_fingerprints(path)
    if actual == expected:
        return
    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    changed = sorted(
        name
        for name in set(actual) & set(expected)
        if actual[name] != expected[name]
    )
    raise TemplateToolError(
        f"{phase} changed immutable promotion content; "
        f"added={added[:20]}; removed={removed[:20]}; changed={changed[:20]}"
    )


def _mutate_source_after_snapshot(source: Path) -> None:
    """Test-only TOCTOU hook; production invocations never set this variable."""
    if os.environ.get("TEMPLATE_TOOL_TEST_MUTATE_SOURCE_AFTER_SNAPSHOT") != "1":
        return
    manifest_path = source / "manifest.yaml"
    manifest = load_manifest(manifest_path)
    template = package_template_path(manifest, manifest_path)
    template.write_bytes(template.read_bytes() + b"source mutation after snapshot\n")
    digest = sha256_file(template)
    fingerprint = manifest.setdefault("fingerprint", {})
    fingerprint["sha256"] = digest
    fingerprint["value"] = digest
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _cleanup_stage(stage_root: Path) -> None:
    if stage_root.exists() or stage_root.is_symlink():
        remove_path_or_raise(stage_root)


def promote_package(package_dir: Path, root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    source = package_dir.resolve()
    initial_canonical = discover_packages(root)
    if any(item.package_dir.resolve() == source and item.is_canonical for item in initial_canonical):
        raise TemplateToolError("canonical packages cannot be promoted over themselves")

    with tempfile.TemporaryDirectory(prefix="template-promote-") as temporary_name:
        snapshot_root = Path(temporary_name) / "package"
        snapshot_root.mkdir()
        snapshot = snapshot_root / source.name
        copy_tree_no_symlinks(source, snapshot)
        snapshot_fingerprints = tree_fingerprints(snapshot)
        _mutate_source_after_snapshot(source)

        package = package_from_path(snapshot, root)
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

        validation = validate_package_path(snapshot, root, identity_only=False)
        if not validation_succeeded(validation):
            raise TemplateToolError(f"full template validation failed: {_validation_error(validation)}")
        assert_tree_matches_snapshot(snapshot, snapshot_fingerprints, phase="snapshot validation")

        target = _canonical_target(package, canonical)
        canonical_root = target.parent
        if paths_overlap(source, canonical_root):
            raise TemplateToolError("promotion source overlaps the canonical target tree")
        if target.exists() or target.is_symlink():
            raise TemplateToolError(f"canonical target already exists: {target}")
        stage_root = canonical_root / f".{target.name}.{uuid.uuid4().hex}.stage"
        stage_package = stage_root / target.name
        result: dict[str, Any] = {
            "package": display_path(source, root),
            "target": display_path(target, root),
            "version": package.version,
            "template_sha256": package.fingerprint,
            "owner_skill": display_path(owner_skill_root(package), root),
            "validation": validation,
            "snapshot": {"files": len(snapshot_fingerprints), "immutable": True},
            "dry_run": dry_run,
        }
        if dry_run:
            result["repo_validation"] = {"status": "not_run", "reason": "dry-run"}
            return result

        installed = False
        try:
            canonical_root.mkdir(parents=True, exist_ok=True)
            copy_tree_no_symlinks(snapshot, stage_package)
            assert_tree_matches_snapshot(stage_package, snapshot_fingerprints, phase="stage before validation")
            stage_validation = validate_package_path(stage_package, root, identity_only=False)
            result["stage_validation"] = stage_validation
            if not validation_succeeded(stage_validation):
                raise TemplateToolError(f"stage full template validation failed: {_validation_error(stage_validation)}")
            assert_tree_matches_snapshot(stage_package, snapshot_fingerprints, phase="stage validation")
            if target.exists() or target.is_symlink():
                raise TemplateToolError(f"canonical target appeared during promotion: {target}")
            stage_package.replace(target)
            installed = True
            assert_tree_matches_snapshot(target, snapshot_fingerprints, phase="target installation")

            target_validation = validate_package_path(target, root, identity_only=False)
            result["target_validation"] = target_validation
            if not validation_succeeded(target_validation):
                raise TemplateToolError(f"final canonical target validation failed: {_validation_error(target_validation)}")
            if not target_validation.get("full_validation") or target_validation.get("validation_scope") != "isolated_temp":
                raise TemplateToolError("final canonical target validation did not report isolated full_validation=true")
            assert_tree_matches_snapshot(target, snapshot_fingerprints, phase="target validation")

            repo_validation = _run_repo_validator(root)
            result["repo_validation"] = repo_validation
            assert_tree_matches_snapshot(target, snapshot_fingerprints, phase="repository validation")
            if repo_validation["exit_code"] != 0:
                details = "\n".join(
                    part
                    for part in (
                        f"stdout:\n{str(repo_validation.get('stdout') or '').strip()}" if repo_validation.get("stdout") else "",
                        f"stderr:\n{str(repo_validation.get('stderr') or '').strip()}" if repo_validation.get("stderr") else "",
                    )
                    if part
                )
                suffix = f": {details}" if details else ""
                raise TemplateToolError(
                    f"repository-wide validator failed after promotion "
                    f"(exit code {repo_validation['exit_code']}){suffix}"
                )
            assert_tree_matches_snapshot(target, snapshot_fingerprints, phase="promotion final")
            result["status"] = "passed"
            return result
        except Exception as exc:
            rollback_errors: list[str] = []
            if installed:
                try:
                    remove_installed_target_or_raise(target)
                except Exception as rollback_error:
                    rollback_errors.append(f"target rollback failed: {rollback_error}")
            try:
                _cleanup_stage(stage_root)
            except Exception as cleanup_error:
                rollback_errors.append(f"stage cleanup failed: {cleanup_error}")
            if rollback_errors:
                raise TemplateToolError(f"{exc}; {'; '.join(rollback_errors)}") from exc
            raise
        finally:
            if stage_root.exists() or stage_root.is_symlink():
                _cleanup_stage(stage_root)
