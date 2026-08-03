"""Deterministic, self-contained and self-checking template package archives."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .discovery import owner_skill_root
from .manifest import inspect_manifest_package, load_manifest, manifest_reference, package_template_path, sha256_file
from .models import METADATA_SCHEMA_VERSION, TOOL_VERSION, TemplatePackage, TemplateToolError
from .paths import (
    atomic_write_text,
    display_path,
    is_within,
    paths_overlap,
    remove_path_or_raise,
    validate_windows_component,
)
from .validation import package_from_path, validate_package_path, validate_package_with_owner, validation_succeeded


EXCLUDED_DIR_NAMES = {"__pycache__", ".git", "stage", "backup", "qa", "qa-reports"}


def _excluded(relative: Path) -> bool:
    lowered_parts = {part.casefold() for part in relative.parts}
    if lowered_parts & EXCLUDED_DIR_NAMES:
        return True
    if any(part.casefold().endswith((".stage", ".backup")) for part in relative.parts):
        return True
    name = relative.name.casefold()
    return (
        name.startswith("~$")
        or name.endswith((".pyc", ".tmp", ".temp"))
        or "qa-report" in name
        or "scaffold-report" in name
    )


def _validate_archive_name(name: str) -> str:
    if not name or name.startswith("/") or "\\" in name:
        raise TemplateToolError(f"zip-slip or non-portable archive path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TemplateToolError(f"zip-slip or non-portable archive path: {name!r}")
    for part in path.parts:
        validate_windows_component(part, label="archive path")
    return unicodedata.normalize("NFC", name)


def _archive_sort_key(name: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFC", name)
    return normalized.casefold(), normalized


def _package_files(package: TemplatePackage, prefix: str) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    package_dir = package.package_dir
    if package_dir.is_symlink() or not package_dir.is_dir():
        raise TemplateToolError(f"archive package root must be a real directory: {package_dir}")
    for path in sorted(package_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(package_dir)
        if _excluded(relative):
            continue
        if path.is_symlink():
            raise TemplateToolError(f"symlink is not allowed in an archive package: {path}")
        if path.is_dir():
            continue
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            raise TemplateToolError(f"only regular files are allowed in an archive package: {path}")
        archive_name = f"{prefix}/{relative.as_posix()}"
        _validate_archive_name(archive_name)
        files.append((archive_name, path))
    if not any(name == f"{prefix}/manifest.yaml" for name, _ in files):
        raise TemplateToolError(f"archive package does not contain manifest.yaml: {package_dir}")
    return files


def _assert_unique_portable_names(names: list[str]) -> None:
    seen: dict[str, str] = {}
    for name in names:
        normalized = _validate_archive_name(name)
        key = normalized.casefold()
        previous = seen.get(key)
        if previous is not None:
            raise TemplateToolError(f"archive path casefold/NFC collision: {previous!r} and {name!r}")
        seen[key] = name


def _dependency_closure(package: TemplatePackage, root: Path) -> list[TemplatePackage]:
    template_root = package.package_dir.parent.resolve()
    visited: dict[Path, TemplatePackage] = {}
    active: set[Path] = set()

    def visit(current_dir: Path, current_package: TemplatePackage | None = None) -> None:
        current_dir = current_dir.resolve()
        if current_dir in active:
            raise TemplateToolError(f"template dependency cycle detected at {current_dir}")
        if current_dir in visited:
            return
        if not is_within(current_dir, template_root) or current_dir.parent != template_root:
            raise TemplateToolError(f"template dependency escapes its template-id root: {current_dir}")
        if current_package is None:
            if package.validator is None:
                raise TemplateToolError("owner validator is unavailable for archive dependency")
            current_package = inspect_manifest_package(
                current_dir,
                package.validator,
                is_canonical=False,
                is_default=False,
            )
        if current_package.errors:
            raise TemplateToolError(
                f"archive dependency identity validation failed for {current_dir}: "
                + "; ".join(current_package.errors)
            )
        if current_package.template_id != package.template_id:
            raise TemplateToolError("archive dependency crosses template ids")
        active.add(current_dir)
        try:
            visited[current_dir] = current_package
            manifest_path = current_package.manifest_path
            manifest = load_manifest(manifest_path)
            base_manifest = manifest_reference(manifest, "base_manifest", manifest_path)
            base_template = manifest_reference(manifest, "base_template", manifest_path)
            if (base_manifest is None) != (base_template is None):
                raise TemplateToolError("template.base_manifest and template.base_template must be declared together")
            if base_manifest is None:
                return
            if base_manifest.parent != base_template.parent:
                raise TemplateToolError("template.base_manifest and template.base_template must share a package")
            if not base_manifest.is_file() or not base_template.is_file():
                raise TemplateToolError(f"archive dependency is missing: {base_manifest.parent}")
            visit(base_manifest.parent)
        finally:
            active.remove(current_dir)

    visit(package.package_dir, package)
    return sorted(
        visited.values(),
        key=lambda item: (item.template_id, item.semver.as_tuple(), item.package_dir.name.casefold()),
    )


def _archive_sha(path: Path) -> str:
    return sha256_file(path)


def _extract_archive(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            name = info.filename
            _validate_archive_name(name)
            target = (destination / PurePosixPath(name)).resolve(strict=False)
            if not is_within(target, destination):
                raise TemplateToolError(f"archive contains zip-slip path: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))


def _verify_extracted_dependency_closure(entry: TemplatePackage, root: Path, owner_validator: Path) -> None:
    template_root = entry.package_dir.parent.resolve()
    visited: set[Path] = set()
    active: set[Path] = set()

    def visit(package_dir: Path) -> None:
        package_dir = package_dir.resolve()
        if package_dir in active:
            raise TemplateToolError(f"extracted archive dependency cycle detected at {package_dir}")
        if package_dir in visited:
            return
        if package_dir.parent != template_root or not is_within(package_dir, template_root):
            raise TemplateToolError(f"extracted archive dependency escapes template root: {package_dir}")
        current = inspect_manifest_package(package_dir, owner_validator, is_canonical=False, is_default=False)
        if current.errors:
            raise TemplateToolError("extracted dependency identity failed: " + "; ".join(current.errors))
        if current.template_id != entry.template_id:
            raise TemplateToolError("extracted archive dependency crosses template ids")
        active.add(package_dir)
        try:
            visited.add(package_dir)
            manifest = load_manifest(current.manifest_path)
            base_manifest = manifest_reference(manifest, "base_manifest", current.manifest_path)
            base_template = manifest_reference(manifest, "base_template", current.manifest_path)
            if (base_manifest is None) != (base_template is None):
                raise TemplateToolError("extracted dependency references must be declared as a pair")
            if base_manifest is None:
                return
            if base_manifest.parent != base_template.parent or not base_manifest.is_file() or not base_template.is_file():
                raise TemplateToolError("extracted archive dependency is incomplete")
            visit(base_manifest.parent)
        finally:
            active.remove(package_dir)

    visit(entry.package_dir)


def _verify_archive(
    archive_path: Path,
    file_records: list[dict[str, Any]],
    metadata: dict[str, Any],
    package: TemplatePackage,
    expected_archive_sha: str,
) -> None:
    expected_names = [str(record["path"]) for record in file_records]
    expected_hashes = {str(record["path"]): str(record["sha256"]) for record in file_records}
    _assert_unique_portable_names(expected_names)
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if names != expected_names or len(names) != len(set(names)):
            raise TemplateToolError("archive file order or duplicate entries failed verification")
        for name in names:
            if hashlib.sha256(archive.read(name)).hexdigest().upper() != expected_hashes[name]:
                raise TemplateToolError(f"archive entry hash mismatch: {name}")
    if _archive_sha(archive_path) != expected_archive_sha:
        raise TemplateToolError("archive SHA changed during verification")
    if metadata.get("archive_sha256") != expected_archive_sha:
        raise TemplateToolError("archive metadata archive_sha256 does not match the archive")
    if metadata.get("files") != file_records:
        raise TemplateToolError("archive metadata files do not match the archive file set")

    with tempfile.TemporaryDirectory(prefix="template-archive-verify-") as temporary_name:
        extracted = Path(temporary_name)
        _extract_archive(archive_path, extracted)
        entry_name = str(metadata.get("entry_package") or "")
        entry_dir = extracted / PurePosixPath(entry_name)
        if not entry_dir.is_dir():
            raise TemplateToolError("archive metadata entry_package is missing after extraction")
        extracted_entry = inspect_manifest_package(
            entry_dir,
            package.validator,
            is_canonical=False,
            is_default=False,
        )
        if extracted_entry.errors:
            raise TemplateToolError("extracted entry package identity failed: " + "; ".join(extracted_entry.errors))
        _verify_extracted_dependency_closure(extracted_entry, extracted, package.validator)
        validation = validate_package_with_owner(entry_dir, extracted, package.validator)
        if not validation_succeeded(validation) or not validation.get("full_validation"):
            raise TemplateToolError(
                "extracted archive full validation failed: " + "; ".join(validation.get("errors", []))
            )
        expected_packages = {str(item["manifest"]): item for item in metadata.get("packages", [])}
        if metadata.get("template_sha256") != package.fingerprint:
            raise TemplateToolError("archive metadata template_sha256 does not match the entry package")
        for manifest_name, record in expected_packages.items():
            manifest_path = extracted / PurePosixPath(manifest_name)
            if not manifest_path.is_file():
                raise TemplateToolError(f"archive metadata manifest is missing: {manifest_name}")
            template_name = str(record["template"])
            template_path = extracted / PurePosixPath(template_name)
            if not template_path.is_file() or sha256_file(template_path) != str(record["template_sha256"]):
                raise TemplateToolError(f"archive metadata template hash mismatch: {template_name}")


def _cleanup_created(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for path in reversed(paths):
        try:
            remove_path_or_raise(path)
        except Exception as exc:
            errors.append(f"failed to clean committed archive {path}: {exc}")
    return errors


def archive_package(package_dir: Path, output_dir: Path, root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    package = package_from_path(package_dir, root)
    if package.errors:
        raise TemplateToolError("package identity validation failed: " + "; ".join(package.errors))
    validation = validate_package_path(package.package_dir, root, identity_only=False)
    if not validation_succeeded(validation):
        raise TemplateToolError("full template validation failed: " + "; ".join(validation.get("errors", [])))
    closure = _dependency_closure(package, root)
    output_dir = output_dir.resolve(strict=False)
    if any(paths_overlap(output_dir, item.package_dir) for item in closure):
        raise TemplateToolError("archive output directory overlaps the template package or dependency")

    prefix_by_package = {
        item.package_dir.resolve(): f"{item.template_id}/{item.package_dir.name}"
        for item in closure
    }
    files: list[tuple[str, Path]] = []
    for item in closure:
        files.extend(_package_files(item, prefix_by_package[item.package_dir.resolve()]))
    files.sort(key=lambda pair: _archive_sort_key(pair[0]))
    names = [name for name, _ in files]
    _assert_unique_portable_names(names)

    archive_name = f"{package.template_id}-{package.version}.zip"
    validate_windows_component(archive_name, label="archive filename")
    archive_path = output_dir / archive_name
    sidecar_path = output_dir / f"{archive_name}.sha256"
    metadata_path = output_dir / f"{package.template_id}-{package.version}.metadata.json"
    final_paths = [archive_path, sidecar_path, metadata_path]
    if any(path.exists() or path.is_symlink() for path in final_paths):
        raise TemplateToolError("archive output already exists; refusing to overwrite it")

    file_records = [
        {"path": name, "sha256": sha256_file(path), "size": path.stat().st_size}
        for name, path in files
    ]
    target_prefix = prefix_by_package[package.package_dir.resolve()]
    target_template = f"{target_prefix}/{package.template_path.relative_to(package.package_dir).as_posix()}"
    metadata_base: dict[str, Any] = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "template_id": package.template_id,
        "version": package.version,
        "format": package.format,
        "entry_package": target_prefix,
        "template_sha256": package.fingerprint,
        "owner_skill": display_path(owner_skill_root(package), root),
        "packages": [
            {
                "template_id": item.template_id,
                "version": item.version,
                "manifest": f"{prefix_by_package[item.package_dir.resolve()]}/manifest.yaml",
                "template": f"{prefix_by_package[item.package_dir.resolve()]}/{item.template_path.relative_to(item.package_dir).as_posix()}",
                "template_sha256": item.fingerprint,
            }
            for item in closure
        ],
        "files": file_records,
    }
    result: dict[str, Any] = {
        "tool_version": TOOL_VERSION,
        "schema_version": METADATA_SCHEMA_VERSION,
        "template_id": package.template_id,
        "version": package.version,
        "format": package.format,
        "entry_package": target_prefix,
        "template_sha256": package.fingerprint,
        "packages": metadata_base["packages"],
        "files": file_records,
        "archive": display_path(archive_path, root),
        "sidecar": display_path(sidecar_path, root),
        "metadata": display_path(metadata_path, root),
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_archive = output_dir / f".{archive_name}.{uuid.uuid4().hex}.stage"
    temporary_sidecar = output_dir / f".{archive_name}.{uuid.uuid4().hex}.sidecar"
    temporary_metadata = output_dir / f".{archive_name}.{uuid.uuid4().hex}.metadata"
    created: list[Path] = []
    try:
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, path in files:
                info = zipfile.ZipInfo(name)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.flag_bits = 0x800
                archive.writestr(info, path.read_bytes())
        archive_sha = _archive_sha(temporary_archive)
        metadata = dict(metadata_base)
        metadata["archive_sha256"] = archive_sha
        _verify_archive(temporary_archive, file_records, metadata, package, archive_sha)
        result["archive_sha256"] = archive_sha
        atomic_write_text(temporary_sidecar, f"{archive_sha}  {archive_name}\n", encoding="ascii")
        atomic_write_text(temporary_metadata, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        if temporary_sidecar.read_text(encoding="ascii") != f"{archive_sha}  {archive_name}\n":
            raise TemplateToolError("archive sidecar verification failed")
        commit_steps = [(temporary_archive, archive_path), (temporary_sidecar, sidecar_path), (temporary_metadata, metadata_path)]
        for index, (temporary, final) in enumerate(commit_steps, start=1):
            if os.environ.get("TEMPLATE_TOOL_TEST_FAIL_ARCHIVE_COMMIT_STEP") == str(index):
                raise OSError(f"injected archive commit failure at step {index}")
            temporary.replace(final)
            created.append(final)
    except Exception as exc:
        cleanup_errors = _cleanup_created(created)
        for temporary in (temporary_archive, temporary_sidecar, temporary_metadata):
            if temporary.exists() or temporary.is_symlink():
                try:
                    remove_path_or_raise(temporary)
                except Exception as cleanup_error:
                    cleanup_errors.append(f"temporary archive cleanup failed: {cleanup_error}")
        if cleanup_errors:
            raise TemplateToolError(f"archive transaction failed: {exc}; {'; '.join(cleanup_errors)}") from exc
        raise
    return result
