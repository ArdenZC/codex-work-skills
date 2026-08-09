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
from .paths import (
    copy_tree_no_symlinks,
    display_path,
    is_within,
    paths_overlap,
    remove_path_or_raise,
    restore_directory_from_snapshot,
    tree_fingerprints,
    tree_inventory,
)
from .validation import (
    _assert_validator_runtime_state,
    _cleanup_validation_workspace,
    _subprocess_text,
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
    errors: list[str] = []
    result: subprocess.CompletedProcess[str] | None = None
    started = False
    environment = _validator_environment(temporary_root)
    for key in ("TEMPLATE_TOOL_TEST_REPO_MUTATION",):
        if key in os.environ:
            environment[key] = os.environ[key]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=1800,
        )
    except subprocess.TimeoutExpired as exc:
        started = True
        return_code = None
        stdout = _subprocess_text(exc.stdout)
        stderr = _subprocess_text(exc.stderr)
        errors.append("repository-wide validator timed out after 1800s")
    except OSError as exc:
        return_code = None
        stdout = ""
        stderr = str(exc)
        errors.append("repository-wide validator could not start")
    except subprocess.SubprocessError as exc:
        started = True
        return_code = None
        stdout = ""
        stderr = str(exc)
        errors.append("repository-wide validator failed to execute")
    else:
        started = True
        return_code = result.returncode
        stdout = _subprocess_text(result.stdout)
        stderr = _subprocess_text(result.stderr)
    try:
        _assert_validator_runtime_state(temporary_root)
    except (OSError, TemplateToolError) as exc:
        errors.append(f"repository validator temporary workspace integrity failed: {exc}")
    cleanup_error = _cleanup_validation_workspace(temporary, temporary_root)
    if cleanup_error:
        errors.append(cleanup_error)
    return {
        "command": [str(item) for item in command],
        "exit_code": return_code,
        "stdout": stdout,
        "stderr": stderr,
        "started": started,
        "errors": errors,
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


def _canonical_template_roots(root: Path, canonical: list[Any]) -> list[Path]:
    repository = root.resolve()
    roots: dict[str, Path] = {}
    for package in canonical:
        if not package.is_canonical or package.validator is None:
            continue
        owner = owner_skill_root(package)
        template_root = owner / "assets" / "templates"
        if template_root.is_symlink() or not template_root.is_dir():
            raise TemplateToolError("canonical template root must be a regular directory")
        resolved = template_root.resolve(strict=False)
        if not is_within(resolved, repository, allow_equal=False):
            raise TemplateToolError("canonical template root escapes the repository")
        roots.setdefault(os.path.normcase(os.fspath(resolved)), resolved)
    return [roots[key] for key in sorted(roots)]


def _snapshot_repository_package_trees(
    root: Path,
    canonical: list[Any],
    snapshot_root: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, protected_root in enumerate(_canonical_template_roots(root, canonical), start=1):
        snapshot = snapshot_root / f"root-{index}"
        source_inventory = tree_inventory(protected_root)
        copy_tree_no_symlinks(protected_root, snapshot)
        if tree_inventory(snapshot) != source_inventory:
            raise TemplateToolError("repository package snapshot did not match its source")
        records.append(
            {
                "root": protected_root,
                "display_root": display_path(protected_root, root),
                "snapshot": snapshot,
                "inventory": source_inventory,
            }
        )
    return records


def _repository_package_difference(record: dict[str, Any]) -> dict[str, Any] | None:
    expected = record["inventory"]
    try:
        actual = tree_inventory(record["root"])
    except (OSError, TemplateToolError):
        return {
            "root": record["display_root"],
            "added": [],
            "removed": sorted(
                [*expected["directories"], *expected["files"].keys()]
            ),
            "changed": ["<protected-root>"],
        }
    expected_files = expected["files"]
    actual_files = actual["files"]
    expected_entries = set(expected["directories"]) | set(expected_files)
    actual_entries = set(actual["directories"]) | set(actual_files)
    added = sorted(actual_entries - expected_entries)
    removed = sorted(expected_entries - actual_entries)
    changed = sorted(
        name
        for name in set(expected_files) & set(actual_files)
        if expected_files[name] != actual_files[name]
    )
    if not added and not removed and not changed:
        return None
    return {
        "root": record["display_root"],
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def _restore_repository_package_trees(
    records: list[dict[str, Any]],
    differences: list[dict[str, Any]],
) -> list[str]:
    changed_roots = {difference["root"] for difference in differences}
    errors: list[str] = []
    for record in records:
        if record["display_root"] not in changed_roots:
            continue
        try:
            restore_directory_from_snapshot(record["snapshot"], record["root"])
            if tree_inventory(record["root"]) != record["inventory"]:
                errors.append(f"{record['display_root']}: restored fingerprint mismatch")
        except (OSError, TemplateToolError) as exc:
            errors.append(f"{record['display_root']}: restore failed: {exc}")
    return errors


def _repository_guard_error(
    differences: list[dict[str, Any]],
    restore_errors: list[str],
) -> str:
    details = [
        f"root={difference['root']}; added={difference['added']}; "
        f"removed={difference['removed']}; changed={difference['changed']}"
        for difference in differences
    ]
    message = "repository package tree mutation detected: " + " | ".join(details)
    if restore_errors:
        message += "; repository package tree restore failure: " + "; ".join(restore_errors)
    return message


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

            repository_snapshot_root = Path(temporary_name) / "repository-package-snapshots"
            repository_snapshot_root.mkdir()
            protected_canonical = [item for item in discover_packages(root) if item.is_canonical]
            repository_package_records = _snapshot_repository_package_trees(
                root,
                protected_canonical,
                repository_snapshot_root,
            )
            repo_validation = _run_repo_validator(root)
            result["repo_validation"] = repo_validation
            differences = [
                difference
                for record in repository_package_records
                if (difference := _repository_package_difference(record)) is not None
            ]
            restore_errors = _restore_repository_package_trees(repository_package_records, differences)
            result["repository_package_guard"] = {
                "protected_roots": len(repository_package_records),
                "unchanged": not differences and not restore_errors,
            }
            failure_messages: list[str] = []
            if differences or restore_errors:
                failure_messages.append(_repository_guard_error(differences, restore_errors))
            assert_tree_matches_snapshot(target, snapshot_fingerprints, phase="repository validation")
            if repo_validation["errors"]:
                details = "; ".join(repo_validation["errors"])
                if repo_validation.get("stderr"):
                    details += f"; stderr: {repo_validation['stderr'].strip()}"
                failure_messages.append(f"repository-wide validator could not complete: {details}")
            elif repo_validation["exit_code"] != 0:
                details = "\n".join(
                    part
                    for part in (
                        f"stdout:\n{str(repo_validation.get('stdout') or '').strip()}" if repo_validation.get("stdout") else "",
                        f"stderr:\n{str(repo_validation.get('stderr') or '').strip()}" if repo_validation.get("stderr") else "",
                    )
                    if part
                )
                suffix = f": {details}" if details else ""
                failure_messages.append(
                    f"repository-wide validator failed after promotion "
                    f"(exit code {repo_validation['exit_code']}){suffix}"
                )
            if failure_messages:
                raise TemplateToolError("; ".join(failure_messages))
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
