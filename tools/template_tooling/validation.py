"""Identity checks and owner-validator execution in an isolated workspace."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from .discovery import (
    canonical_skill_root_for_package,
    discover_packages,
    find_validator_for_package,
    owner_skill_root,
    trusted_validator_for_package,
)
from .git_trust import GitTrustIndex, trusted_script_files
from .manifest import (
    inspect_manifest_package,
    load_manifest,
    manifest_reference,
    package_template_path,
    sha256_file,
)
from .models import TemplatePackage, TemplateToolError
from .paths import copy_tree_no_symlinks, display_path, is_within, remove_path_or_raise, tree_fingerprints


_PYTHON_CACHE_SUFFIXES = {".pyc", ".pyo"}
_VALIDATOR_ENVIRONMENT_KEYS = (
    "PATH",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "LANG",
    "LC_ALL",
)
_BLOCKED_PYTHON_ENVIRONMENT_KEYS = (
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONINSPECT",
    "PYTHONUSERBASE",
    "PYTHONBREAKPOINT",
    "PYTHONWARNDEFAULTENCODING",
)


def _display_command(command: list[str], root: Path) -> list[str]:
    displayed: list[str] = []
    for token in command:
        candidate = Path(token)
        if candidate.is_absolute():
            displayed.append(display_path(candidate, root) or "<external>")
        else:
            displayed.append(token)
    return displayed


def _subprocess_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _display_output(
    value: str | bytes | None,
    package: TemplatePackage,
    root: Path,
    *,
    temporary_root: Path | None = None,
) -> str:
    value = _subprocess_text(value)
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


def _validator_environment(temporary_root: Path) -> dict[str, str]:
    """Build a minimal environment for an owner validator subprocess."""
    parent_environment = dict(os.environ)
    override = parent_environment.get("TEMPLATE_TOOL_TEST_VALIDATOR_ENV_JSON")
    if override:
        try:
            parsed = json.loads(override)
        except (TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            parent_environment.update({str(key): str(value) for key, value in parsed.items()})

    environment = {
        key: parent_environment[key]
        for key in _VALIDATOR_ENVIRONMENT_KEYS
        if parent_environment.get(key) is not None
    }
    for key in _BLOCKED_PYTHON_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    environment.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(temporary_root / "python-cache"),
        }
    )
    return environment


def _validator_environment_diagnostics(
    environment: dict[str, str],
    temporary_root: Path,
) -> dict[str, bool]:
    cache_root = Path(environment["PYTHONPYCACHEPREFIX"]).expanduser()
    return {
        "isolated_python_path": all(key not in environment for key in _BLOCKED_PYTHON_ENVIRONMENT_KEYS),
        "user_site_disabled": environment.get("PYTHONNOUSERSITE") == "1",
        "pycache_redirected": is_within(cache_root, temporary_root, allow_equal=False),
    }


def _copy_regular_file(source: Path, destination: Path) -> None:
    if source.is_symlink():
        raise TemplateToolError(f"symlink is not allowed in validation workspace: {source}")
    mode = source.stat(follow_symlinks=False).st_mode
    if not stat.S_ISREG(mode):
        raise TemplateToolError(f"only regular files are allowed in validation workspace: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_owner_support(owner: Path, isolated_skill: Path, template_id: str, trust_index: GitTrustIndex) -> None:
    scripts = owner / "scripts"
    trusted_scripts = trusted_script_files(owner, trust_index)
    target_scripts = isolated_skill / "scripts"
    target_scripts.mkdir(parents=True, exist_ok=False)
    for source in trusted_scripts:
        relative = source.relative_to(scripts)
        _copy_regular_file(source, target_scripts / relative)

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


def _copy_package_without_python_cache(source: Path, destination: Path) -> None:
    """Copy a package while leaving build-time Python caches out of the temp tree."""
    if source.is_symlink() or not source.is_dir():
        raise TemplateToolError(f"package root must be a real directory: {source}")
    destination.mkdir(parents=True, exist_ok=False)
    entries = sorted(
        source.rglob("*"),
        key=lambda item: item.relative_to(source).as_posix().casefold(),
    )
    for source_path in entries:
        relative = source_path.relative_to(source)
        if any(part.casefold() == "__pycache__" for part in relative.parts):
            continue
        target = destination / relative
        if source_path.is_symlink():
            raise TemplateToolError(f"symlink is not allowed: {source_path}")
        if source_path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        _copy_regular_file(source_path, target)


def _copy_dependency_closure(
    source_package: Path,
    destination_root: Path,
    *,
    copied: dict[Path, Path],
    active: set[Path],
    entry_source_package: Path,
    entry_destination_package: Path,
) -> None:
    source_package = source_package.resolve()
    entry_source_package = entry_source_package.resolve()
    entry_destination_package = entry_destination_package.resolve()
    template_root = entry_source_package.parent
    if is_within(source_package, entry_source_package, allow_equal=False):
        destination_package = entry_destination_package / source_package.relative_to(entry_source_package)
    elif source_package.parent == template_root:
        destination_package = destination_root / source_package.name
    else:
        raise TemplateToolError(f"template dependency escapes its template-id root: {source_package}")
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
            _copy_package_without_python_cache(source_package, destination_package)
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
        if not (
            base_manifest.parent.parent == template_root
            or is_within(base_manifest.parent, entry_source_package, allow_equal=False)
        ):
            raise TemplateToolError(f"template dependency escapes its template-id root: {base_manifest.parent}")
        if not base_manifest.is_file() or not base_template.is_file():
            raise TemplateToolError(f"template dependency is missing: {base_manifest.parent}")
        _copy_dependency_closure(
            base_manifest.parent,
            destination_root,
            copied=copied,
            active=active,
            entry_source_package=entry_source_package,
            entry_destination_package=entry_destination_package,
        )
    finally:
        active.remove(source_package)


def _assert_no_python_cache_or_bytecode(root: Path) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part.casefold() == "__pycache__" for part in relative.parts):
            raise TemplateToolError(
                f"validation workspace contains forbidden Python cache: {path}"
            )
        if path.is_file() and path.suffix.casefold() in _PYTHON_CACHE_SUFFIXES:
            raise TemplateToolError(
                f"validation workspace contains forbidden Python bytecode: {path}"
            )


def _assert_validator_runtime_state(temporary_root: Path) -> None:
    skill_root = temporary_root / "skill"
    if skill_root.exists():
        _assert_no_python_cache_or_bytecode(skill_root)
    cache_root = temporary_root / "python-cache"
    if cache_root.is_symlink() or (cache_root.exists() and not is_within(cache_root, temporary_root, allow_equal=False)):
        raise TemplateToolError("validator Python cache escaped the temporary workspace")
    for path in temporary_root.rglob("*"):
        relative = path.relative_to(temporary_root)
        if relative.parts and relative.parts[0].casefold() == "python-cache":
            continue
        if any(part.casefold() == "__pycache__" for part in relative.parts):
            raise TemplateToolError(f"validator created Python cache outside python-cache: {path}")
        if path.is_file() and path.suffix.casefold() in _PYTHON_CACHE_SUFFIXES:
            raise TemplateToolError(f"validator created Python bytecode outside python-cache: {path}")


def _cleanup_validation_workspace(
    temporary: tempfile.TemporaryDirectory[str],
    temporary_root: Path,
) -> str | None:
    errors: list[str] = []
    try:
        temporary.cleanup()
    except Exception as exc:
        errors.append(f"failed to clean validation temporary workspace: {exc}")
    if temporary_root.exists() or temporary_root.is_symlink():
        try:
            remove_path_or_raise(temporary_root)
        except Exception as exc:
            errors.append(f"failed to remove validation temporary workspace: {exc}")
    if temporary_root.exists() or temporary_root.is_symlink():
        errors.append("validation temporary workspace was not cleaned up")
    return "; ".join(errors) if errors else None


def _prepare_isolated_package(
    package: TemplatePackage,
    trust_index: GitTrustIndex,
) -> tuple[TemplatePackage, tempfile.TemporaryDirectory[str], Path]:
    if package.validator is None:
        raise TemplateToolError("owner validator is unavailable")
    trusted_validator = trusted_validator_for_package(package, trust_index.repo_root, trust_index)
    owner = trusted_validator.parent.parent
    temporary = tempfile.TemporaryDirectory(prefix="template-tool-validation-")
    temporary_root = Path(temporary.name)
    isolated_skill = temporary_root / "skill"
    isolated_skill.mkdir()
    try:
        _copy_owner_support(owner, isolated_skill, package.template_id, trust_index)
        target_root = isolated_skill / "assets" / "templates" / package.template_id
        destination_package = target_root / package.package_dir.name

        # Copy owner baselines first, then the submitted package and its declared
        # dependencies.  This gives validators their normal __file__ layout while
        # ensuring all input bytes are inside the disposable workspace.
        copied: dict[Path, Path] = {}
        if destination_package.exists():
            remove_path_or_raise(destination_package)
        _copy_package_without_python_cache(package.package_dir, destination_package)
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
            _copy_dependency_closure(
                base_manifest.parent,
                target_root,
                copied=copied,
                active=set(),
                entry_source_package=package.package_dir,
                entry_destination_package=destination_package,
            )

        _assert_no_python_cache_or_bytecode(temporary_root)

        validator_relative = trusted_validator.relative_to(owner / "scripts")
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
    except Exception as exc:
        cleanup_error = _cleanup_validation_workspace(temporary, temporary_root)
        if cleanup_error:
            raise TemplateToolError(f"{exc}; {cleanup_error}") from exc
        raise


def package_from_path(
    package_dir: Path,
    root: Path,
    *,
    trust_index: GitTrustIndex | None = None,
) -> TemplatePackage:
    trust_index = trust_index or GitTrustIndex.from_repo_root(root)
    package_dir = package_dir.resolve()
    manifest_path = package_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise TemplateToolError(f"manifest.yaml was not found in package: {package_dir}")
    manifest = load_manifest(manifest_path)
    template = manifest.get("template") if isinstance(manifest, dict) else None
    template_id = str(template.get("id") or "") if isinstance(template, dict) else ""
    format_name = str(template.get("format") or "") if isinstance(template, dict) else ""
    validator = find_validator_for_package(
        package_dir,
        root,
        template_id=template_id,
        format_name=format_name,
        trust_index=trust_index,
    )
    local_shape = canonical_skill_root_for_package(package_dir, root)
    return inspect_manifest_package(
        package_dir,
        validator,
        is_canonical=False,
        is_default=False,
        validator_error=(
            "canonical-like package has no trusted Git-tracked owner validator"
            if local_shape is not None
            else None
        ),
    )


def identity_report(
    package: TemplatePackage,
    root: Path,
    *,
    source_scope: str = "external",
) -> dict[str, Any]:
    return {
        "package": package.to_dict(root),
        "source_scope": source_scope,
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
    trust_index: GitTrustIndex | None = None,
    timeout: int,
) -> dict[str, Any]:
    if package.validator is None:
        report["status"] = "failed"
        report["errors"].append("owner validator is unavailable")
        return report
    try:
        if (
            validation_scope != "isolated_temp"
            or temporary_root is None
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
        "-B",
        str(package.validator),
        "--template",
        str(package.template_path),
        "--manifest",
        str(package.manifest_path),
        "--json",
    ]
    cwd = package.validator.parent.parent
    environment = _validator_environment(temporary_root)
    report["validator_environment"] = _validator_environment_diagnostics(environment, temporary_root)
    report["validation_scope"] = validation_scope
    result: subprocess.CompletedProcess[str] | None = None
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _subprocess_text(exc.stdout)
        stderr = _subprocess_text(exc.stderr)
        report["status"] = "failed"
        report["errors"].append(f"template validator timed out after {timeout}s")
        report["validator"] = {
            "command": _display_command(command, root),
            "exit_code": None,
            "stdout": _display_output(stdout, package, root, temporary_root=temporary_root),
            "stderr": _display_output(stderr, package, root, temporary_root=temporary_root),
        }
    except OSError as exc:
        report["status"] = "failed"
        report["errors"].append(f"cannot execute template validator: {exc}")
        report["validator"] = {
            "command": _display_command(command, root),
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
        }
    else:
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
        else:
            report["status"] = "passed"
    try:
        _assert_validator_runtime_state(temporary_root)
    except (OSError, TemplateToolError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"validator temporary workspace integrity failed: {exc}")
    return report


def validate_package_path(package_dir: Path, root: Path, *, identity_only: bool = False, timeout: int = 900) -> dict[str, Any]:
    trust_index = GitTrustIndex.from_repo_root(root)
    package = package_from_path(package_dir, root, trust_index=trust_index)
    source_scope = "canonical" if canonical_skill_root_for_package(package.package_dir, root) is not None else "external"
    report = identity_report(package, root, source_scope=source_scope)
    if package.errors or identity_only:
        return report
    if package.validator is None:
        report["status"] = "failed"
        report["errors"].append("owner validator is unavailable")
        return report
    isolated = None
    temporary_root: Path | None = None
    try:
        validator_package, isolated, temporary_root = _prepare_isolated_package(package, trust_index)
        return _run_validator(
            validator_package,
            root,
            report,
            validation_scope="isolated_temp",
            temporary_root=temporary_root,
            trust_index=trust_index,
            timeout=timeout,
        )
    except (OSError, TemplateToolError, ValueError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"cannot prepare validator workspace: {exc}")
        return report
    finally:
        if isolated is not None:
            cleanup_error = _cleanup_validation_workspace(isolated, temporary_root)
            if cleanup_error:
                report["status"] = "failed"
                report.setdefault("errors", []).append(cleanup_error)


def validate_package_with_owner(
    package_dir: Path,
    root: Path,
    owner_validator: Path,
    *,
    trusted_root: Path | None = None,
    trust_index: GitTrustIndex | None = None,
    timeout: int = 900,
) -> dict[str, Any]:
    """Validate an extracted package with the already-resolved owner validator."""
    package = inspect_manifest_package(
        package_dir.resolve(),
        owner_validator.resolve(),
        is_canonical=False,
        is_default=False,
    )
    report = identity_report(package, root, source_scope="external")
    if package.errors:
        return report
    try:
        if trusted_root is not None:
            trust_index = trust_index or GitTrustIndex.from_repo_root(trusted_root)
            trusted_validator_for_package(package, trusted_root, trust_index)
        elif owner_validator.is_symlink() or not owner_validator.is_file() or not is_within(owner_validator, root):
            raise TemplateToolError("owner validator is not a trusted regular file")
    except (OSError, TemplateToolError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"untrusted owner validator: {exc}")
        return report
    isolated = None
    temporary_root: Path | None = None
    try:
        if trust_index is None:
            trust_index = GitTrustIndex.from_repo_root(trusted_root or root)
        validator_package, isolated, temporary_root = _prepare_isolated_package(package, trust_index)
        return _run_validator(
            validator_package,
            root,
            report,
            validation_scope="isolated_temp",
            temporary_root=temporary_root,
            trust_index=trust_index,
            timeout=timeout,
        )
    except (OSError, TemplateToolError, ValueError) as exc:
        report["status"] = "failed"
        report["errors"].append(f"cannot prepare validator workspace: {exc}")
        return report
    finally:
        if isolated is not None:
            cleanup_error = _cleanup_validation_workspace(isolated, temporary_root)
            if cleanup_error:
                report["status"] = "failed"
                report.setdefault("errors", []).append(cleanup_error)


def validation_succeeded(report: dict[str, Any], *, allow_identity_only: bool = False) -> bool:
    if report.get("errors"):
        return False
    if report.get("status") == "passed":
        return True
    return allow_identity_only and report.get("status") == "identity_only"
