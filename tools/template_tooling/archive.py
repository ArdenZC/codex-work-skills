"""Deterministic, self-checking template package archives."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

import yaml

from .manifest import load_manifest, sha256_file
from .models import METADATA_SCHEMA_VERSION, TOOL_VERSION, TemplateToolError
from .paths import display_path, paths_overlap
from .validation import package_from_path, validate_package_path, validation_succeeded


EXCLUDED_DIR_NAMES = {"__pycache__", ".git", "stage", "backup", "qa", "qa-reports"}


def _excluded(relative: Path) -> bool:
    lowered_parts = {part.lower() for part in relative.parts}
    if lowered_parts & EXCLUDED_DIR_NAMES:
        return True
    if any(part.lower().endswith((".stage", ".backup")) for part in relative.parts):
        return True
    name = relative.name.lower()
    return (
        name.startswith("~$")
        or name.endswith((".pyc", ".tmp", ".temp"))
        or "qa-report" in name
        or "scaffold-report" in name
    )


def _package_files(package_dir: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for path in sorted(package_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
        relative = path.relative_to(package_dir)
        if _excluded(relative):
            continue
        if path.is_symlink():
            raise TemplateToolError(f"symlink is not allowed in an archive package: {path}")
        if path.is_file():
            archive_name = relative.as_posix()
            if archive_name.startswith("/") or ".." in Path(archive_name).parts:
                raise TemplateToolError(f"zip-slip path is not allowed: {archive_name}")
            files.append((archive_name, path))
    if not any(name == "manifest.yaml" for name, _ in files):
        raise TemplateToolError("archive package does not contain manifest.yaml")
    return files


def _archive_sha(path: Path) -> str:
    return sha256_file(path)


def _verify_archive(
    archive_path: Path,
    files: list[tuple[str, Path]],
    manifest: dict[str, Any],
    expected_template_sha: str,
    expected_archive_sha: str,
) -> None:
    expected_names = [name for name, _ in files]
    expected_hashes = {name: sha256_file(path) for name, path in files}
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if names != expected_names or len(names) != len(set(names)):
            raise TemplateToolError("archive file order or duplicate entries failed verification")
        for name in names:
            if Path(name).is_absolute() or ".." in Path(name).parts or "\\" in name:
                raise TemplateToolError(f"archive contains zip-slip path: {name}")
            if hashlib.sha256(archive.read(name)).hexdigest().upper() != expected_hashes[name]:
                raise TemplateToolError(f"archive entry hash mismatch: {name}")
        manifest_bytes = archive.read("manifest.yaml")
        try:
            archive_manifest = yaml.safe_load(manifest_bytes.decode("utf-8"))
        except (UnicodeError, yaml.YAMLError) as exc:
            raise TemplateToolError(f"archived manifest is not readable: {exc}") from exc
        if not isinstance(archive_manifest, dict):
            raise TemplateToolError("archived manifest is not a mapping")
        template = archive_manifest.get("template")
        template_name = str(template.get("file") or "") if isinstance(template, dict) else ""
        template_path = Path(template_name)
        if template_path.is_absolute() or not template_name or ".." in template_path.parts:
            raise TemplateToolError("archived manifest contains an unsafe template path")
        template_name = template_path.as_posix()
        if template_name not in names:
            raise TemplateToolError("archived manifest template is missing from archive")
        if expected_hashes[template_name] != expected_template_sha:
            raise TemplateToolError("archived template SHA does not match manifest fingerprint")
    if _archive_sha(archive_path) != expected_archive_sha:
        raise TemplateToolError("archive SHA changed during verification")


def archive_package(package_dir: Path, output_dir: Path, root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    package = package_from_path(package_dir, root)
    if package.errors:
        raise TemplateToolError("package identity validation failed: " + "; ".join(package.errors))
    validation = validate_package_path(package.package_dir, root, identity_only=False)
    if not validation_succeeded(validation):
        raise TemplateToolError("full template validation failed: " + "; ".join(validation.get("errors", [])))
    output_dir = output_dir.resolve(strict=False)
    if paths_overlap(output_dir, package.package_dir):
        raise TemplateToolError("archive output directory overlaps the template package")
    files = _package_files(package.package_dir)
    manifest = load_manifest(package.manifest_path)
    template_name = package.template_path.relative_to(package.package_dir).as_posix()
    if not any(name == template_name for name, _ in files):
        raise TemplateToolError("archive template file was excluded from the file set")
    archive_name = f"{package.template_id}-{package.version}.zip"
    archive_path = output_dir / archive_name
    sidecar_path = output_dir / f"{archive_name}.sha256"
    metadata_path = output_dir / f"{archive_name}.json"
    final_paths = [archive_path, sidecar_path, metadata_path]
    if any(path.exists() or path.is_symlink() for path in final_paths):
        raise TemplateToolError("archive output already exists; refusing to overwrite it")

    file_records = [
        {"path": name, "sha256": sha256_file(path), "size": path.stat().st_size}
        for name, path in files
    ]
    result: dict[str, Any] = {
        "tool_version": TOOL_VERSION,
        "schema_version": METADATA_SCHEMA_VERSION,
        "template_id": package.template_id,
        "version": package.version,
        "format": package.format,
        "template_sha256": package.fingerprint,
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
        _verify_archive(temporary_archive, files, manifest, package.fingerprint, archive_sha)
        result["archive_sha256"] = archive_sha
        temporary_sidecar.write_text(f"{archive_sha}  {archive_name}\n", encoding="ascii")
        metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "template_id": package.template_id,
            "version": package.version,
            "format": package.format,
            "template_sha256": package.fingerprint,
            "archive_sha256": archive_sha,
            "files": file_records,
        }
        temporary_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary_archive.replace(archive_path)
        created.append(archive_path)
        temporary_sidecar.replace(sidecar_path)
        created.append(sidecar_path)
        temporary_metadata.replace(metadata_path)
        created.append(metadata_path)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    finally:
        for path in (temporary_archive, temporary_sidecar, temporary_metadata):
            path.unlink(missing_ok=True)
    return result
