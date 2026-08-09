"""Release verification and immutable template-package lifecycle operations.

The archive format is deliberately owned by :mod:`archive`.  This module
verifies that existing contract without changing its deterministic bytes, then
adds the install/release lifecycle around a verified three-file bundle.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .archive import (
    DEFAULT_ARCHIVE_OUTPUT_ROOT,
    MAX_ARCHIVE_COMPRESSION_RATIO,
    MAX_ARCHIVE_ENTRIES,
    MAX_ARCHIVE_ENTRY_SIZE,
    MAX_ARCHIVE_TOTAL_SIZE,
    _assert_unique_portable_names,
    _archive_source_files,
    _dependency_closure,
    _extract_archive,
    _stream_zip_entry,
    _validate_zip_info_type,
    _validate_zip_resource_limits,
    _validate_archive_name,
    _verify_extracted_dependency_closure,
    archive_package,
)
from .discovery import (
    canonical_skill_root_for_package,
    discover_packages,
    find_validator_for_package,
    owner_skill_root,
    trusted_validator_for_package,
)
from .git_trust import GitTrustIndex
from .manifest import (
    inspect_manifest_package,
    load_manifest,
    manifest_reference,
    sha256_file,
)
from .models import (
    INSTALL_STATE_SCHEMA_VERSION,
    RELEASE_TOOL_VERSION,
    SemVer,
    TemplatePackage,
    TemplateToolError,
    parse_semver,
)
from .paths import (
    _lexical_absolute,
    _lexical_is_within,
    _resolve_existing_ancestors,
    atomic_write_text,
    display_path,
    is_within,
    paths_overlap,
    remove_path_or_raise,
    validate_windows_component,
)
from .validation import validate_package_with_owner, validation_succeeded


RELEASE_PLAN_SCHEMA_VERSION = "1.0"
# Keep the public Release limits in this module while sharing the actual
# implementation with deterministic archive verification/extraction.
MAX_RELEASE_ENTRIES = MAX_ARCHIVE_ENTRIES
MAX_RELEASE_ENTRY_SIZE = MAX_ARCHIVE_ENTRY_SIZE
MAX_RELEASE_TOTAL_SIZE = MAX_ARCHIVE_TOTAL_SIZE
MAX_COMPRESSION_RATIO = MAX_ARCHIVE_COMPRESSION_RATIO
ARCHIVE_METADATA_KEYS = {
    "schema_version",
    "tool_version",
    "template_id",
    "version",
    "format",
    "entry_package",
    "template_sha256",
    "owner_skill",
    "packages",
    "files",
    "archive_sha256",
}
ARCHIVE_REQUIRED_KEYS = {
    "schema_version",
    "tool_version",
    "template_id",
    "version",
    "format",
    "entry_package",
    "template_sha256",
    "packages",
    "files",
    "archive_sha256",
}
PACKAGE_RECORD_KEYS = {"template_id", "version", "manifest", "template", "template_sha256"}
FILE_RECORD_KEYS = {"path", "sha256", "size"}
STATE_KEYS = {
    "schema_version",
    "template_id",
    "active_version",
    "previous_version",
    "updated_by_tool_version",
}
INSTALLATION_KEYS = {
    "schema_version",
    "template_id",
    "version",
    "archive_sha256",
    "entry_package",
    "files",
}
INSTALLATION_FILE_KEYS = {"path", "sha256"}
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
HEX_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass(frozen=True)
class TrustedReleaseOwner:
    template_id: str
    format: str
    skill_root: Path
    validator: Path
    reference_package: TemplatePackage


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TemplateToolError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TemplateToolError(f"{label} must be a regular file: {path}")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object_pairs,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TemplateToolError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TemplateToolError(f"{label} must contain a JSON object")
    return value


def _require_keys(value: dict[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"missing keys: {missing}")
        if extra:
            details.append(f"unsupported keys: {extra}")
        raise TemplateToolError(f"{label} contract failed ({'; '.join(details)})")


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise TemplateToolError(f"{label} must be a 64-character hexadecimal SHA-256")
    return value.upper()


def _require_version(value: Any, *, label: str) -> str:
    try:
        return str(parse_semver(value))
    except TemplateToolError as exc:
        raise TemplateToolError(f"{label}: {exc}") from exc


def _require_tool_version(value: Any, *, label: str) -> str:
    """Validate a tool provenance value without coupling it to this reader."""
    return _require_version(value, label=label)


def _strict_archive_name(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise TemplateToolError(f"{label} must be a string")
    normalized = _validate_archive_name(value)
    if normalized != value:
        raise TemplateToolError(f"{label} must use NFC-normalized portable path spelling: {value!r}")
    return value


def _validate_sidecar(sidecar_path: Path, archive_path: Path, expected_sha: str) -> None:
    if sidecar_path.name != f"{archive_path.name}.sha256":
        raise TemplateToolError("archive sidecar filename does not match the archive")
    if sidecar_path.is_symlink() or not sidecar_path.is_file():
        raise TemplateToolError(f"archive sidecar must be a regular file: {sidecar_path}")
    try:
        content = sidecar_path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise TemplateToolError(f"cannot read archive sidecar: {sidecar_path}") from exc
    expected = f"{expected_sha}  {archive_path.name}\n"
    if content != expected:
        raise TemplateToolError("archive sidecar does not match the archive SHA or filename")


def _validate_file_record(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TemplateToolError(f"{label} must be an object")
    _require_keys(value, FILE_RECORD_KEYS, label=label)
    path = _strict_archive_name(value["path"], label=f"{label}.path")
    digest = _require_sha(value["sha256"], label=f"{label}.sha256")
    size = value["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise TemplateToolError(f"{label}.size must be a non-negative integer")
    return {"path": path, "sha256": digest, "size": size}


def _validate_installation_file_record(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TemplateToolError(f"{label} must be an object")
    _require_keys(value, INSTALLATION_FILE_KEYS, label=label)
    return {
        "path": _strict_archive_name(value["path"], label=f"{label}.path"),
        "sha256": _require_sha(value["sha256"], label=f"{label}.sha256"),
    }


def _validate_package_record(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TemplateToolError(f"{label} must be an object")
    _require_keys(value, PACKAGE_RECORD_KEYS, label=label)
    template_id = value["template_id"]
    if not isinstance(template_id, str):
        raise TemplateToolError(f"{label}.template_id must be a string")
    validate_windows_component(template_id, label=f"{label}.template_id")
    version = _require_version(value["version"], label=f"{label}.version")
    manifest = _strict_archive_name(value["manifest"], label=f"{label}.manifest")
    template = _strict_archive_name(value["template"], label=f"{label}.template")
    if not manifest.endswith("/manifest.yaml"):
        raise TemplateToolError(f"{label}.manifest must point to manifest.yaml")
    manifest_parent = manifest.rsplit("/", 1)[0]
    if template.rsplit("/", 1)[0] != manifest_parent:
        raise TemplateToolError(f"{label}.template must belong to the manifest package")
    _require_sha(value["template_sha256"], label=f"{label}.template_sha256")
    package_name = manifest_parent.rsplit("/", 1)[-1]
    if package_name not in {version, f"v{version}"}:
        raise TemplateToolError(f"{label} package directory does not match its version")
    return {
        "template_id": template_id,
        "version": version,
        "manifest": manifest,
        "template": template,
        "template_sha256": str(value["template_sha256"]).upper(),
    }


def _validate_metadata(metadata_path: Path, archive_path: Path) -> dict[str, Any]:
    if metadata_path.name != f"{archive_path.stem}.metadata.json":
        raise TemplateToolError("archive metadata filename does not match the archive")
    metadata = _load_json_object(metadata_path, label="archive metadata")
    _require_keys(metadata, ARCHIVE_METADATA_KEYS, label="archive metadata")
    if metadata["schema_version"] != "1.0":
        raise TemplateToolError("unsupported archive metadata schema_version")
    if metadata["tool_version"] != "0.1.0":
        raise TemplateToolError("unsupported archive metadata tool_version")
    template_id = metadata["template_id"]
    if not isinstance(template_id, str):
        raise TemplateToolError("archive metadata template_id must be a string")
    validate_windows_component(template_id, label="archive metadata template_id")
    version = _require_version(metadata["version"], label="archive metadata.version")
    if not isinstance(metadata["format"], str) or not metadata["format"].strip():
        raise TemplateToolError("archive metadata format must be a non-empty string")
    entry_package = _strict_archive_name(metadata["entry_package"], label="archive metadata.entry_package")
    _require_sha(metadata["template_sha256"], label="archive metadata.template_sha256")
    _require_sha(metadata["archive_sha256"], label="archive metadata.archive_sha256")
    owner_skill = metadata["owner_skill"]
    if not isinstance(owner_skill, str) or not owner_skill or owner_skill.startswith("/") or "\\" in owner_skill:
        raise TemplateToolError("archive metadata owner_skill must be a portable repository-relative path")
    if owner_skill:
        _strict_archive_name(owner_skill, label="archive metadata.owner_skill")
    packages_value = metadata["packages"]
    files_value = metadata["files"]
    if not isinstance(packages_value, list) or not packages_value:
        raise TemplateToolError("archive metadata packages must be a non-empty list")
    if not isinstance(files_value, list) or not files_value:
        raise TemplateToolError("archive metadata files must be a non-empty list")
    packages = [_validate_package_record(item, label=f"archive metadata packages[{index}]") for index, item in enumerate(packages_value)]
    files = [_validate_file_record(item, label=f"archive metadata files[{index}]") for index, item in enumerate(files_value)]
    package_keys = [(item["template_id"], parse_semver(item["version"]).as_tuple()) for item in packages]
    if package_keys != sorted(package_keys + []):
        raise TemplateToolError("archive metadata packages are not in stable order")
    package_manifests = [item["manifest"] for item in packages]
    if len(package_manifests) != len(set(package_manifests)):
        raise TemplateToolError("archive metadata packages contain duplicate manifests")
    package_identities = [(item["template_id"], item["version"]) for item in packages]
    if len(package_identities) != len(set(package_identities)):
        raise TemplateToolError("archive metadata packages contain duplicate identities")
    file_names = [item["path"] for item in files]
    if file_names != sorted(file_names, key=lambda item: (item.casefold(), item)):
        raise TemplateToolError("archive metadata files are not in stable order")
    _assert_unique_portable_names(file_names)
    package_prefixes = {
        item["manifest"].rsplit("/", 1)[0]
        for item in packages
    }
    for item in packages:
        if not item["manifest"].startswith(f"{template_id}/"):
            raise TemplateToolError("archive metadata package crosses template ids")
        if item["template_id"] != template_id:
            raise TemplateToolError("archive metadata package template_id mismatch")
        prefix = item["manifest"].rsplit("/", 1)[0]
        if item["manifest"] not in file_names or item["template"] not in file_names:
            raise TemplateToolError(f"archive metadata package files are missing: {prefix}")
    for name in file_names:
        if not any(name.startswith(f"{prefix}/") for prefix in package_prefixes):
            raise TemplateToolError(f"archive metadata file is outside a declared package: {name}")
    if entry_package != next(
        (item["manifest"].rsplit("/", 1)[0] for item in packages
         if item["template_id"] == template_id and item["version"] == version),
        None,
    ):
        raise TemplateToolError("archive metadata entry_package does not identify the entry package")
    expected_archive_name = f"{template_id}-{version}.zip"
    if archive_path.name != expected_archive_name:
        raise TemplateToolError("archive filename does not match metadata template identity")
    return {
        **metadata,
        "template_id": template_id,
        "version": version,
        "entry_package": entry_package,
        "template_sha256": str(metadata["template_sha256"]).upper(),
        "archive_sha256": str(metadata["archive_sha256"]).upper(),
        "packages": packages,
        "files": files,
    }


def _regular_file(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise TemplateToolError(f"{label} must be a regular file: {path}")
    if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
        raise TemplateToolError(f"{label} must be a regular file: {path}")


def _validate_zip_entries(archive_path: Path, file_records: list[dict[str, Any]], expected_sha: str) -> None:
    expected_names = [record["path"] for record in file_records]
    expected_hashes = {record["path"]: record["sha256"] for record in file_records}
    expected_sizes = {record["path"]: record["size"] for record in file_records}
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            _validate_zip_resource_limits(
                infos,
                max_entries=MAX_RELEASE_ENTRIES,
                max_entry_size=MAX_RELEASE_ENTRY_SIZE,
                max_total_size=MAX_RELEASE_TOTAL_SIZE,
                max_compression_ratio=MAX_COMPRESSION_RATIO,
            )
            actual_names: list[str] = []
            for info in infos:
                name = _strict_archive_name(info.filename, label="ZIP entry")
                _validate_zip_info_type(info)
                actual_names.append(name)
            if actual_names != expected_names:
                raise TemplateToolError("ZIP entries do not exactly match metadata files")
            _assert_unique_portable_names(actual_names)
            for info, name in zip(infos, actual_names):
                count, digest = _stream_zip_entry(archive, info)
                if count != expected_sizes[name]:
                    raise TemplateToolError(f"ZIP entry size mismatch: {name}")
                if digest != expected_hashes[name]:
                    raise TemplateToolError(f"ZIP entry SHA-256 mismatch: {name}")
    except zipfile.BadZipFile as exc:
        raise TemplateToolError(f"invalid ZIP archive: {archive_path}") from exc
    actual_archive_sha = sha256_file(archive_path)
    if actual_archive_sha != expected_sha:
        raise TemplateToolError("archive SHA-256 does not match metadata")


def _find_trusted_release_owner(metadata: dict[str, Any], root: Path) -> TrustedReleaseOwner:
    """Resolve one current Git-tracked Skill owner, independent of release version."""
    candidates: dict[Path, list[TemplatePackage]] = {}
    for package in discover_packages(root):
        if (
            not package.is_canonical
            or package.errors
            or package.template_id != metadata["template_id"]
            or package.format != metadata["format"]
            or package.validator is None
        ):
            continue
        skill_root = owner_skill_root(package).resolve()
        expected_owner = display_path(skill_root, root)
        if metadata["owner_skill"] != expected_owner:
            continue
        candidates.setdefault(skill_root, []).append(package)

    if not candidates:
        raise TemplateToolError(
            "current trusted Skill owner is unavailable for release bundle: "
            f"{metadata['template_id']} {metadata['format']} {metadata['owner_skill']}"
        )
    if len(candidates) != 1:
        owners = ", ".join(path.as_posix() for path in sorted(candidates, key=lambda item: item.as_posix().casefold()))
        raise TemplateToolError(f"current trusted Skill owner is ambiguous for release bundle: {owners}")

    skill_root, packages = next(iter(candidates.items()))
    packages.sort(key=lambda item: (item.semver.as_tuple(), item.package_dir.as_posix().casefold()), reverse=True)
    reference_package = packages[0]
    validator = trusted_validator_for_package(reference_package, root)
    return TrustedReleaseOwner(
        template_id=metadata["template_id"],
        format=metadata["format"],
        skill_root=skill_root,
        validator=validator,
        reference_package=reference_package,
    )


def _validate_extracted_packages(
    extracted: Path,
    metadata: dict[str, Any],
    owner: TrustedReleaseOwner,
    root: Path,
) -> None:
    owner_validator = owner.validator
    package_records = metadata["packages"]
    expected_manifest_paths = {item["manifest"] for item in package_records}
    entry_dir = extracted / PurePosixPath(metadata["entry_package"])
    if not entry_dir.is_dir() or entry_dir.is_symlink():
        raise TemplateToolError("archive entry package is missing or is not a real directory")
    expected_inventory = [
        {"path": record["path"], "sha256": record["sha256"]}
        for record in metadata["files"]
    ]
    if _bundle_inventory(extracted) != expected_inventory:
        raise TemplateToolError("extracted archive inventory does not match metadata files")
    for record in package_records:
        manifest_path = extracted / PurePosixPath(record["manifest"])
        template_path = extracted / PurePosixPath(record["template"])
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise TemplateToolError(f"archive package manifest is missing: {record['manifest']}")
        if not template_path.is_file() or template_path.is_symlink():
            raise TemplateToolError(f"archive package template is missing: {record['template']}")
        package_dir = manifest_path.parent
        inspected = inspect_manifest_package(package_dir, owner_validator, is_canonical=False, is_default=False)
        if inspected.errors:
            raise TemplateToolError(
                f"extracted package identity failed for {record['manifest']}: "
                + "; ".join(inspected.errors)
            )
        if (inspected.template_id, inspected.version) != (record["template_id"], record["version"]):
            raise TemplateToolError(f"extracted package metadata identity mismatch: {record['manifest']}")
        if sha256_file(template_path) != record["template_sha256"]:
            raise TemplateToolError(f"extracted package template SHA mismatch: {record['template']}")
    _verify_extracted_dependency_closure(
        inspect_manifest_package(entry_dir, owner_validator, is_canonical=False, is_default=False),
        extracted,
        owner_validator,
    )
    discovered_manifest_paths: set[str] = set()
    for manifest in extracted.rglob("manifest.yaml"):
        if manifest.is_symlink():
            raise TemplateToolError("symlinked manifest is not allowed in an extracted archive")
        discovered_manifest_paths.add(manifest.relative_to(extracted).as_posix())
    if discovered_manifest_paths != expected_manifest_paths:
        raise TemplateToolError("archive package dependency closure does not match metadata packages")
    entry_record = next(
        (record for record in package_records if record["manifest"].rsplit("/", 1)[0] == metadata["entry_package"]),
        None,
    )
    if entry_record is None:
        raise TemplateToolError("archive entry package record is missing")
    if metadata["template_sha256"] != entry_record["template_sha256"]:
        raise TemplateToolError("archive metadata template_sha256 does not match the entry package record")
    entry_template = extracted / PurePosixPath(entry_record["template"])
    if sha256_file(entry_template) != metadata["template_sha256"]:
        raise TemplateToolError("archive metadata template_sha256 does not match the extracted entry template")
    validation = validate_package_with_owner(
        entry_dir,
        extracted,
        owner_validator,
        trusted_root=root,
    )
    if not validation_succeeded(validation) or not validation.get("full_validation"):
        raise TemplateToolError(
            "extracted archive full validation failed: " + "; ".join(validation.get("errors", []))
        )
    if _bundle_inventory(extracted) != expected_inventory:
        raise TemplateToolError("archive validator modified the extracted bundle")


@dataclass(frozen=True)
class _VerifiedBundle:
    archive: Path
    sidecar: Path
    metadata_path: Path
    metadata: dict[str, Any]
    owner: TrustedReleaseOwner

    @property
    def archive_sha256(self) -> str:
        return str(self.metadata["archive_sha256"])

    def report(self, root: Path) -> dict[str, Any]:
        return {
            "status": "passed",
            "schema_version": RELEASE_PLAN_SCHEMA_VERSION,
            "tool_version": RELEASE_TOOL_VERSION,
            "template_id": self.metadata["template_id"],
            "version": self.metadata["version"],
            "format": self.metadata["format"],
            "entry_package": self.metadata["entry_package"],
            "archive_sha256": self.archive_sha256,
            "files_verified": len(self.metadata["files"]),
            "packages_verified": len(self.metadata["packages"]),
            "full_validation": True,
            "archive": display_path(self.archive, root),
            "sidecar": display_path(self.sidecar, root),
            "metadata": display_path(self.metadata_path, root),
        }


def _verify_release_bundle(
    archive_path: Path,
    root: Path,
    *,
    sidecar_path: Path | None = None,
    metadata_path: Path | None = None,
) -> _VerifiedBundle:
    _regular_file(archive_path, label="release archive")
    sidecar_path = sidecar_path or archive_path.with_name(f"{archive_path.name}.sha256")
    metadata_path = metadata_path or archive_path.with_name(f"{archive_path.stem}.metadata.json")
    _regular_file(sidecar_path, label="release sidecar")
    _regular_file(metadata_path, label="release metadata")
    metadata = _validate_metadata(metadata_path, archive_path)
    archive_sha = sha256_file(archive_path)
    _validate_sidecar(sidecar_path, archive_path, archive_sha)
    if metadata["archive_sha256"] != archive_sha:
        raise TemplateToolError("release metadata archive_sha256 does not match the archive")
    _validate_zip_entries(archive_path, metadata["files"], archive_sha)
    owner = _find_trusted_release_owner(metadata, root)
    with tempfile.TemporaryDirectory(prefix="template-release-verify-") as temporary_name:
        extracted = Path(temporary_name)
        _extract_archive(archive_path, extracted)
        _validate_extracted_packages(extracted, metadata, owner, root)
    return _VerifiedBundle(
        archive=archive_path,
        sidecar=sidecar_path,
        metadata_path=metadata_path,
        metadata=metadata,
        owner=owner,
    )


def verify_release_bundle(
    archive_path: Path,
    root: Path,
    *,
    sidecar_path: Path | None = None,
    metadata_path: Path | None = None,
) -> dict[str, Any]:
    """Verify sidecar, ZIP inventory, metadata, dependency closure and owner QA."""
    return _verify_release_bundle(
        archive_path.expanduser().absolute(),
        root.resolve(),
        sidecar_path=(sidecar_path.expanduser().absolute() if sidecar_path else None),
        metadata_path=(metadata_path.expanduser().absolute() if metadata_path else None),
    ).report(root.resolve())


def resolve_release_inputs(
    *,
    archive: Path | None = None,
    release_dir: Path | None = None,
    sidecar: Path | None = None,
    metadata: Path | None = None,
) -> tuple[Path, Path, Path]:
    if (archive is None) == (release_dir is None):
        raise TemplateToolError("exactly one of --archive and --release-dir is required")
    if release_dir is not None:
        release_dir = release_dir.expanduser().absolute()
        if release_dir.is_symlink() or not release_dir.is_dir():
            raise TemplateToolError(f"release directory must be a real directory: {release_dir}")
        archives = sorted(
            path
            for path in release_dir.iterdir()
            if not path.is_symlink() and path.is_file() and path.suffix.casefold() == ".zip"
        )
        if any(path.is_symlink() and path.suffix.casefold() == ".zip" for path in release_dir.iterdir()):
            raise TemplateToolError("release directory contains a symlinked ZIP archive")
        if len(archives) != 1:
            raise TemplateToolError("release directory must contain exactly one ZIP archive")
        archive = archives[0]
        sidecar = sidecar or archive.with_name(f"{archive.name}.sha256")
        metadata = metadata or archive.with_name(f"{archive.stem}.metadata.json")
    else:
        archive = archive.expanduser().absolute()  # type: ignore[union-attr]
        sidecar = sidecar or archive.with_name(f"{archive.name}.sha256")
        metadata = metadata or archive.with_name(f"{archive.stem}.metadata.json")
    return archive, sidecar.expanduser().absolute(), metadata.expanduser().absolute()  # type: ignore[union-attr]


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="ascii",
        errors="replace",
        check=False,
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not HEX_COMMIT_RE.fullmatch(value):
        raise TemplateToolError("release source_commit requires a committed Git HEAD")
    return value.lower()


def _git_status(root: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        raise TemplateToolError(f"cannot inspect release source worktree: {details}")
    return result.stdout


def _assert_release_worktree_clean(root: Path) -> None:
    if _git_status(root).strip():
        raise TemplateToolError("release requires a clean worktree")


def _relative_git_paths(root: Path, paths: Iterable[Path]) -> list[str]:
    repository = root.resolve()
    relative_paths: list[str] = []
    for path in paths:
        try:
            relative = path.resolve(strict=False).relative_to(repository)
        except ValueError as exc:
            raise TemplateToolError(f"release source file is outside the repository: {path}") from exc
        relative_paths.append(relative.as_posix())
    return relative_paths


def _assert_release_source_matches_head(root: Path, paths: Iterable[Path]) -> None:
    relative_paths = _relative_git_paths(root, paths)
    if not relative_paths:
        raise TemplateToolError("release source package contains no archive files")
    for diff_args in (
        ["diff", "--quiet", "HEAD", "--", *relative_paths],
        ["diff", "--cached", "--quiet", "HEAD", "--", *relative_paths],
    ):
        result = subprocess.run(
            ["git", "-C", str(root), *diff_args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode == 1:
            raise TemplateToolError("release source package differs from source_commit")
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip()
            raise TemplateToolError(f"cannot compare release source with source_commit: {details}")
    for relative in relative_paths:
        expected = subprocess.run(
            ["git", "-C", str(root), "rev-parse", f"HEAD:{relative}"],
            capture_output=True,
            text=True,
            encoding="ascii",
            errors="replace",
            check=False,
        )
        actual = subprocess.run(
            ["git", "-C", str(root), "hash-object", "--", relative],
            capture_output=True,
            text=True,
            encoding="ascii",
            errors="replace",
            check=False,
        )
        expected_blob = expected.stdout.strip().lower()
        actual_blob = actual.stdout.strip().lower()
        if expected.returncode != 0 or actual.returncode != 0 or expected_blob != actual_blob:
            raise TemplateToolError("release source package differs from source_commit")


def _require_release_source_is_committed_canonical(
    package: TemplatePackage,
    root: Path,
    trust_index: GitTrustIndex,
    closure: Iterable[TemplatePackage],
) -> None:
    if not package.is_canonical or canonical_skill_root_for_package(package.package_dir, root) is None:
        raise TemplateToolError("release requires a canonical repository package")
    if package.validator is None:
        raise TemplateToolError("release canonical package owner validator is unavailable")
    trust_index.require_tracked_regular_file(package.validator, label="release owner validator")

    source_files = _archive_source_files(list(closure))
    for archive_name, source_path in source_files:
        trust_index.require_tracked_regular_file(
            source_path,
            label=f"release source file {archive_name}",
        )
    _assert_release_source_matches_head(root, (path for _, path in source_files))


def _canonical_package_for_release(root: Path, package: Path | None, template_id: str | None, version: str | None) -> TemplatePackage:
    trust_index = GitTrustIndex.from_repo_root(root)
    packages = discover_packages(root, trust_index=trust_index)
    if package is not None:
        requested = package.expanduser().resolve(strict=False)
        candidates = [
            item for item in packages
            if item.package_dir.resolve(strict=False) == requested and item.is_canonical
        ]
        if len(candidates) != 1:
            raise TemplateToolError("release requires a canonical repository package")
        return candidates[0]
    if not template_id or not version:
        raise TemplateToolError("release requires --package or both --template-id and --version")
    canonical_version = _require_version(version, label="release.version")
    candidates = [
        item for item in packages
        if item.is_canonical and item.template_id == template_id and item.version == canonical_version
    ]
    if len(candidates) != 1:
        raise TemplateToolError("release target must identify exactly one canonical template package")
    return candidates[0]


def _validate_release_output(output_dir: Path, root: Path, closure: Iterable[TemplatePackage]) -> Path:
    lexical_root = _lexical_absolute(root)
    lexical_output = _lexical_absolute(output_dir)
    resolved_root = _resolve_existing_ancestors(lexical_root)
    resolved_output = _resolve_existing_ancestors(lexical_output)
    allowed = lexical_root / DEFAULT_ARCHIVE_OUTPUT_ROOT
    allowed_resolved = _resolve_existing_ancestors(allowed)
    if not _lexical_is_within(lexical_output, lexical_root):
        raise TemplateToolError("release output must be inside the repository")
    if not _lexical_is_within(lexical_output, allowed):
        raise TemplateToolError("release output must be below dist/template-packages/")
    if not _lexical_is_within(resolved_output, resolved_root) or not _lexical_is_within(resolved_output, allowed_resolved):
        raise TemplateToolError("release output symlink escapes dist/template-packages")
    for package in closure:
        if paths_overlap(lexical_output, _lexical_absolute(package.package_dir)) or paths_overlap(resolved_output, _resolve_existing_ancestors(package.package_dir)):
            raise TemplateToolError("release output overlaps a canonical package")
    return lexical_output


def _cleanup_release_output(path: Path) -> None:
    injected = os.environ.get("TEMPLATE_TOOL_TEST_FAIL_RELEASE_CLEANUP")
    if injected and (injected == "all" or injected == path.name):
        raise OSError(f"injected release cleanup failure for {path.name}")
    remove_path_or_raise(path)


def release_package(
    root: Path,
    *,
    package: Path | None = None,
    template_id: str | None = None,
    version: str | None = None,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    target = _canonical_package_for_release(root, package, template_id, version)
    _assert_release_worktree_clean(root)
    closure = _dependency_closure(target, root)
    trust_index = GitTrustIndex.from_repo_root(root)
    source_commit = _git_head(root)
    _require_release_source_is_committed_canonical(target, root, trust_index, closure)
    output_dir = _validate_release_output(output_dir or (root / DEFAULT_ARCHIVE_OUTPUT_ROOT), root, closure)
    archive_name = f"{target.template_id}-{target.version}.zip"
    sidecar_name = f"{archive_name}.sha256"
    metadata_name = f"{target.template_id}-{target.version}.metadata.json"
    plan_name = f"{target.template_id}-{target.version}.release-plan.json"
    base_plan: dict[str, Any] = {
        "status": "planned" if dry_run else "pending",
        "schema_version": RELEASE_PLAN_SCHEMA_VERSION,
        "tool_version": RELEASE_TOOL_VERSION,
        "template_id": target.template_id,
        "version": target.version,
        "format": target.format,
        "tag": f"template/{target.template_id}/v{target.version}",
        "release_name": f"{target.template_id} v{target.version}",
        "archive": archive_name,
        "sha256": sidecar_name,
        "metadata": metadata_name,
        "assets": [archive_name, sidecar_name, metadata_name],
        "archive_sha256": None,
        "prerelease": False,
        "source_commit": source_commit,
    }
    plan_path = output_dir / plan_name
    final_paths = [output_dir / archive_name, output_dir / sidecar_name, output_dir / metadata_name, plan_path]
    if any(path.exists() or path.is_symlink() for path in final_paths):
        raise TemplateToolError("release output already exists; refusing to overwrite it")
    if dry_run:
        archive_package(target.package_dir, output_dir, root, dry_run=True)
        base_plan["dry_run"] = True
        base_plan["plan"] = plan_name
        return base_plan
    created_paths: list[Path] = []
    try:
        result = archive_package(target.package_dir, output_dir, root, dry_run=False)
        created_paths = final_paths[:3]
        archive_path = output_dir / archive_name
        if os.environ.get("TEMPLATE_TOOL_TEST_FAIL_RELEASE_VERIFY") == "1":
            raise TemplateToolError("injected release verification failure")
        verified = _verify_release_bundle(archive_path, root)
        base_plan["archive_sha256"] = verified.archive_sha256
        base_plan["status"] = "passed"
        base_plan["dry_run"] = False
        base_plan["plan"] = plan_name
        created_paths.append(plan_path)
        atomic_write_text(plan_path, json.dumps(base_plan, ensure_ascii=False, indent=2) + "\n")
    except Exception as original:
        cleanup_errors: list[str] = []
        for path in reversed(created_paths):
            try:
                _cleanup_release_output(path)
            except Exception as cleanup:
                cleanup_errors.append(f"failed to remove {path.name}: {cleanup}")
        message = f"release transaction failed: {original}"
        if cleanup_errors:
            message += "; " + "; ".join(cleanup_errors)
        raise TemplateToolError(message) from original
    return {
        **base_plan,
        "status": "passed",
        "dry_run": False,
        "plan": display_path(plan_path, root),
        "archive": result.get("archive", archive_name),
        "sidecar": result.get("sidecar", sidecar_name),
        "metadata": result.get("metadata", metadata_name),
    }


def default_install_root(root: Path) -> Path:
    return root / "installed" / "template-packages"


def _canonical_package_dirs(root: Path) -> list[Path]:
    return [package.package_dir for package in discover_packages(root) if package.is_canonical]


def _validate_install_root(
    install_root: Path,
    root: Path,
    *,
    protected_paths: Iterable[Path] = (),
) -> Path:
    lexical_root = _lexical_absolute(root)
    lexical_install = _lexical_absolute(install_root)
    resolved_root = _resolve_existing_ancestors(lexical_root)
    resolved_install = _resolve_existing_ancestors(lexical_install)
    lexical_inside_repo = _lexical_is_within(lexical_install, lexical_root)
    resolved_inside_repo = _lexical_is_within(resolved_install, resolved_root)
    allowed = lexical_root / "installed" / "template-packages"
    allowed_resolved = _resolve_existing_ancestors(allowed)
    if lexical_inside_repo:
        if not resolved_inside_repo:
            raise TemplateToolError("install root symlink escapes the repository")
        if not _lexical_is_within(lexical_install, allowed):
            raise TemplateToolError("repository install root must be below installed/template-packages/")
        if not _lexical_is_within(resolved_install, allowed_resolved):
            raise TemplateToolError("install root symlink escapes installed/template-packages")
    elif resolved_inside_repo:
        raise TemplateToolError("external install root resolves inside the repository")
    for canonical in _canonical_package_dirs(root):
        if paths_overlap(lexical_install, _lexical_absolute(canonical)) or paths_overlap(
            resolved_install, _resolve_existing_ancestors(canonical)
        ):
            raise TemplateToolError("install root overlaps a canonical template package")
    for protected in protected_paths:
        if paths_overlap(lexical_install, _lexical_absolute(protected)) or paths_overlap(
            resolved_install, _resolve_existing_ancestors(protected)
        ):
            raise TemplateToolError(f"install root overlaps protected path: {protected}")
    return lexical_install


def _validate_release_inputs_against_install_root(
    install_root: Path,
    inputs: Iterable[Path],
) -> None:
    for input_path in inputs:
        if paths_overlap(install_root, _lexical_absolute(input_path)) or paths_overlap(
            _resolve_existing_ancestors(install_root), _resolve_existing_ancestors(input_path)
        ):
            raise TemplateToolError(f"install root overlaps release input: {input_path}")


class _InstallationLock:
    def __init__(self, path: Path, template_id: str) -> None:
        self.path = path
        self.template_id = template_id
        self._owned = False
        self._injected_release_failure = False

    @property
    def owned(self) -> bool:
        return self._owned

    def acquire(self) -> "_InstallationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise TemplateToolError(f"installation lock is a symlink: {self.path}")
        payload = json.dumps(
            {
                "schema_version": INSTALL_STATE_SCHEMA_VERSION,
                "tool_version": RELEASE_TOOL_VERSION,
                "template_id": self.template_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ) + "\n"
        try:
            descriptor = os.open(
                os.fspath(self.path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise TemplateToolError(f"installation lock already exists: {self.path}") from exc
        except OSError as exc:
            raise TemplateToolError(f"cannot create installation lock: {self.path}: {exc}") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(payload)
                stream.flush()
                try:
                    os.fsync(stream.fileno())
                except OSError:
                    pass
            self._owned = True
            return self
        except Exception:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def release(self) -> None:
        if not self._owned:
            return
        failure_mode = os.environ.get("TEMPLATE_TOOL_TEST_FAIL_LOCK_RELEASE")
        if failure_mode == "always" or (failure_mode == "1" and not self._injected_release_failure):
            self._injected_release_failure = True
            raise OSError("injected installation lock release failure")
        try:
            self.path.unlink()
        except OSError as exc:
            raise TemplateToolError(f"cannot remove installation lock: {self.path}: {exc}") from exc
        self._owned = False

    def __enter__(self) -> "_InstallationLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._owned:
            try:
                self.release()
            except OSError as error:
                if exc is None:
                    raise TemplateToolError(f"cannot remove installation lock: {self.path}: {error}") from error


def _load_state(path: Path, template_id: str) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    state = _load_json_object(path, label="active installation state")
    _require_keys(state, STATE_KEYS, label="active installation state")
    if state["schema_version"] != INSTALL_STATE_SCHEMA_VERSION:
        raise TemplateToolError("unsupported active installation state schema_version")
    if state["template_id"] != template_id:
        raise TemplateToolError("active installation state template_id mismatch")
    active = _require_version(state["active_version"], label="active_version")
    previous = state["previous_version"]
    if previous is not None:
        previous = _require_version(previous, label="previous_version")
    updated_by_tool_version = _require_tool_version(
        state["updated_by_tool_version"],
        label="updated_by_tool_version",
    )
    return {
        **state,
        "active_version": active,
        "previous_version": previous,
        "updated_by_tool_version": updated_by_tool_version,
    }


def _load_installation(path: Path, template_id: str, version: str) -> dict[str, Any]:
    installation = _load_json_object(path, label="installed version inventory")
    _require_keys(installation, INSTALLATION_KEYS, label="installed version inventory")
    if installation["schema_version"] != INSTALL_STATE_SCHEMA_VERSION:
        raise TemplateToolError("unsupported installed version inventory schema_version")
    if installation["template_id"] != template_id or _require_version(installation["version"], label="installed version") != version:
        raise TemplateToolError("installed version inventory identity mismatch")
    digest = _require_sha(installation["archive_sha256"], label="installed archive_sha256")
    entry = _strict_archive_name(installation["entry_package"], label="installed entry_package")
    records = installation["files"]
    if not isinstance(records, list) or not records:
        raise TemplateToolError("installed version inventory files must be a non-empty list")
    normalized = [_validate_installation_file_record(item, label=f"installed files[{index}]") for index, item in enumerate(records)]
    if [item["path"] for item in normalized] != sorted(
        (item["path"] for item in normalized), key=lambda item: (item.casefold(), item)
    ):
        raise TemplateToolError("installed version inventory files are not in stable order")
    _assert_unique_portable_names([item["path"] for item in normalized])
    return {
        **installation,
        "version": version,
        "archive_sha256": digest,
        "entry_package": entry,
        "files": normalized,
    }


def _bundle_inventory(bundle: Path) -> list[dict[str, Any]]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise TemplateToolError(f"installed bundle must be a real directory: {bundle}")
    records: list[dict[str, Any]] = []
    for path in sorted(bundle.rglob("*"), key=lambda item: (item.relative_to(bundle).as_posix().casefold(), item.relative_to(bundle).as_posix())):
        relative_path = path.relative_to(bundle)
        if any(
            part.casefold() in {"stage", "backup", "cache", "qa", "qa-reports", "__pycache__"}
            or part.casefold().endswith((".stage", ".backup", ".cache"))
            for part in relative_path.parts
        ):
            raise TemplateToolError(f"installed bundle contains a staging or cache path: {path}")
        if path.is_symlink():
            raise TemplateToolError(f"symlink is not allowed in installed bundle: {path}")
        if path.is_dir():
            continue
        mode = path.stat(follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode):
            raise TemplateToolError(f"installed bundle contains a special file: {path}")
        relative = _strict_archive_name(relative_path.as_posix(), label="installed bundle path")
        records.append({"path": relative, "sha256": sha256_file(path)})
    if not records:
        raise TemplateToolError("installed bundle is empty")
    _assert_unique_portable_names([item["path"] for item in records])
    return records


def _validate_installed_inventory_only(
    version_dir: Path,
    template_id: str,
    version: str,
) -> dict[str, Any]:
    """Check installation metadata and real bundle bytes without full QA."""
    installation = _load_installation(version_dir / ".installation.json", template_id, version)
    actual_inventory = _bundle_inventory(version_dir / "bundle")
    if actual_inventory != installation["files"]:
        raise TemplateToolError("installed bundle inventory does not match .installation.json")
    return {"installation": installation, "inventory": actual_inventory}


def _installed_entry(bundle: Path, installation: dict[str, Any], template_id: str) -> tuple[Path, Path]:
    entry = installation["entry_package"]
    entry_dir = bundle / PurePosixPath(entry)
    if entry_dir.is_symlink() or not entry_dir.is_dir():
        raise TemplateToolError("installed entry package is missing or is not a real directory")
    manifest_path = entry_dir / "manifest.yaml"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise TemplateToolError("installed entry manifest is missing")
    manifest = load_manifest(manifest_path)
    actual_id = str(manifest.get("template", {}).get("id") or "") if isinstance(manifest.get("template"), dict) else ""
    if actual_id != template_id:
        raise TemplateToolError("installed entry package template_id mismatch")
    return entry_dir, manifest_path


def _validate_installed_version(
    version_dir: Path,
    template_id: str,
    version: str,
    root: Path,
    *,
    expected_archive_sha: str | None = None,
    inventory_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = version_dir / "bundle"
    inventory_result = inventory_result or _validate_installed_inventory_only(version_dir, template_id, version)
    installation = inventory_result["installation"]
    actual_inventory = inventory_result["inventory"]
    if expected_archive_sha is not None and installation["archive_sha256"] != expected_archive_sha:
        raise TemplateToolError("installed archive SHA does not match the release bundle")
    entry_dir, manifest_path = _installed_entry(bundle, installation, template_id)
    manifest = load_manifest(manifest_path)
    format_name = str(manifest.get("template", {}).get("format") or "")
    owner_validator = find_validator_for_package(
        entry_dir,
        root,
        template_id=template_id,
        format_name=format_name,
    )
    if owner_validator is None:
        raise TemplateToolError("no current trusted owner validator for installed package")
    inspected = inspect_manifest_package(entry_dir, owner_validator, is_canonical=False, is_default=False)
    if inspected.errors:
        raise TemplateToolError("installed package identity failed: " + "; ".join(inspected.errors))
    if inspected.version != version or inspected.format != format_name:
        raise TemplateToolError("installed package version or format mismatch")
    _verify_extracted_dependency_closure(inspected, bundle, owner_validator)
    validation = validate_package_with_owner(
        entry_dir,
        bundle,
        owner_validator,
        trusted_root=root,
    )
    if not validation_succeeded(validation) or not validation.get("full_validation"):
        raise TemplateToolError("installed package full validation failed: " + "; ".join(validation.get("errors", [])))
    if _bundle_inventory(bundle) != actual_inventory:
        raise TemplateToolError("installed package validator modified the bundle")
    return {
        "status": "passed",
        "template_id": template_id,
        "version": version,
        "archive_sha256": installation["archive_sha256"],
        "files_verified": len(actual_inventory),
        "full_validation": True,
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    if path.is_symlink():
        raise TemplateToolError(f"active installation state is a symlink: {path}")
    if os.environ.get("TEMPLATE_TOOL_TEST_FAIL_ACTIVE_STATE") == "1":
        raise OSError("injected active state update failure")
    atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _restore_active_bytes(path: Path, previous: bytes | None) -> None:
    if previous is None:
        if path.exists() or path.is_symlink():
            remove_path_or_raise(path)
        return
    if path.is_symlink():
        remove_path_or_raise(path)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.restore"
    try:
        temporary.write_bytes(previous)
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            remove_path_or_raise(temporary)


def _assert_active_bytes(path: Path, expected: bytes | None) -> None:
    if expected is None:
        if path.exists() or path.is_symlink():
            raise TemplateToolError(f"active installation state was not restored: {path}")
        return
    if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
        raise TemplateToolError(f"active installation state was not restored: {path}")


def _extract_verified_to_stage(verified: _VerifiedBundle, stage_bundle: Path) -> None:
    stage_bundle.mkdir(parents=True, exist_ok=False)
    _extract_archive(verified.archive, stage_bundle)
    actual = _bundle_inventory(stage_bundle)
    expected = [
        {"path": record["path"], "sha256": record["sha256"]}
        for record in verified.metadata["files"]
    ]
    if actual != expected:
        raise TemplateToolError("staged release bundle inventory does not match verified metadata")


def _install_verified_bundle(
    verified: _VerifiedBundle,
    root: Path,
    install_root: Path,
    *,
    operation: str,
    dry_run: bool,
    lock: _InstallationLock | None = None,
) -> dict[str, Any]:
    template_id = str(verified.metadata["template_id"])
    version = str(verified.metadata["version"])
    template_dir = install_root / template_id
    versions_dir = template_dir / "versions"
    active_path = template_dir / "active.json"
    target_dir = versions_dir / version
    if template_dir.exists() and template_dir.is_symlink():
        raise TemplateToolError("installed template directory is a symlink")
    if versions_dir.exists() and versions_dir.is_symlink():
        raise TemplateToolError("installed versions directory is a symlink")
    state = _load_state(active_path, template_id)
    old_active_version = state["active_version"] if state else None
    if operation == "install":
        if state is not None:
            raise TemplateToolError("template is already installed; use upgrade")
        if versions_dir.exists() and any(item.is_symlink() or item.is_dir() for item in versions_dir.iterdir()):
            raise TemplateToolError("installed versions exist without an active installation; refusing install")
    elif operation == "upgrade":
        if state is None:
            raise TemplateToolError("template is not installed; use install")
        current = parse_semver(old_active_version)
        target_semver = parse_semver(version)
        if target_semver <= current:
            raise TemplateToolError("upgrade target must be newer than the active version")
        active_dir = versions_dir / old_active_version
        if not active_dir.is_dir() or active_dir.is_symlink():
            raise TemplateToolError("active installation version is missing or unsafe")
        if target_dir.exists() or target_dir.is_symlink():
            raise TemplateToolError("upgrade target version is already installed; versions are immutable")
    else:
        raise TemplateToolError(f"unsupported installation operation: {operation}")
    if target_dir.exists() or target_dir.is_symlink():
        raise TemplateToolError("target version is already installed; versions are immutable")
    if dry_run:
        return {
            "status": "planned",
            "operation": operation,
            "template_id": template_id,
            "version": version,
            "previous_active_version": old_active_version,
            "archive_sha256": verified.archive_sha256,
            "dry_run": True,
        }

    template_dir.mkdir(parents=True, exist_ok=True)
    versions_dir.mkdir(parents=True, exist_ok=True)
    stage = versions_dir / f".{version}.{uuid.uuid4().hex}.stage"
    old_active_bytes: bytes | None = None
    if active_path.exists() or active_path.is_symlink():
        if active_path.is_symlink() or not active_path.is_file():
            raise TemplateToolError("active installation state is not a regular file")
        old_active_bytes = active_path.read_bytes()
    installed = False
    try:
        stage.mkdir(exist_ok=False)
        _extract_verified_to_stage(verified, stage / "bundle")
        installation = {
            "schema_version": INSTALL_STATE_SCHEMA_VERSION,
            "template_id": template_id,
            "version": version,
            "archive_sha256": verified.archive_sha256,
            "entry_package": verified.metadata["entry_package"],
            "files": [
                {"path": record["path"], "sha256": record["sha256"]}
                for record in verified.metadata["files"]
            ],
        }
        atomic_write_text(stage / ".installation.json", json.dumps(installation, ensure_ascii=False, indent=2) + "\n")
        if os.environ.get("TEMPLATE_TOOL_TEST_FAIL_POST_INSTALL_VALIDATION") == "1":
            raise TemplateToolError("injected post-install validation failure")
        _validate_installed_version(
            stage,
            template_id,
            version,
            root,
            expected_archive_sha=verified.archive_sha256,
        )
        if target_dir.exists() or target_dir.is_symlink():
            raise TemplateToolError("target version appeared during install")
        stage.replace(target_dir)
        installed = True
        _validate_installed_version(
            target_dir,
            template_id,
            version,
            root,
            expected_archive_sha=verified.archive_sha256,
        )
        if os.environ.get("TEMPLATE_TOOL_TEST_INSTALL_HOLD_SECONDS"):
            time.sleep(float(os.environ["TEMPLATE_TOOL_TEST_INSTALL_HOLD_SECONDS"]))
        new_state = {
            "schema_version": INSTALL_STATE_SCHEMA_VERSION,
            "template_id": template_id,
            "active_version": version,
            "previous_version": old_active_version if operation == "upgrade" else None,
            "updated_by_tool_version": RELEASE_TOOL_VERSION,
        }
        _write_state(active_path, new_state)
        if _load_state(active_path, template_id) != new_state:
            raise TemplateToolError("active installation state verification failed")
        result = {
            "status": "passed",
            "operation": operation,
            "template_id": template_id,
            "version": version,
            "previous_active_version": old_active_version,
            "archive_sha256": verified.archive_sha256,
            "install_root": display_path(install_root, root),
            "dry_run": False,
        }
        if lock is not None:
            try:
                lock.release()
            except Exception as lock_error:
                raise TemplateToolError(f"installation lock release failed: {lock_error}") from lock_error
        return result
    except Exception as original:
        recovery_errors: list[str] = []
        if installed and (target_dir.exists() or target_dir.is_symlink()):
            try:
                remove_path_or_raise(target_dir)
            except Exception as error:
                recovery_errors.append(f"failed to remove new installed version: {error}")
        if stage.exists() or stage.is_symlink():
            try:
                remove_path_or_raise(stage)
            except Exception as error:
                recovery_errors.append(f"failed to remove installation stage: {error}")
        try:
            _restore_active_bytes(active_path, old_active_bytes)
            _assert_active_bytes(active_path, old_active_bytes)
        except Exception as error:
            recovery_errors.append(f"failed to restore active state: {error}")
        if lock is not None and lock.owned:
            try:
                lock.release()
            except Exception as error:
                recovery_errors.append(f"failed to release installation lock after rollback: {error}")
        message = f"{operation} transaction failed: {original}"
        if recovery_errors:
            message += "; " + "; ".join(recovery_errors)
        raise TemplateToolError(message) from original


def _install_or_upgrade(
    root: Path,
    *,
    operation: str,
    archive: Path | None,
    release_dir: Path | None,
    sidecar: Path | None,
    metadata: Path | None,
    install_root: Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    archive_path, sidecar_path, metadata_path = resolve_release_inputs(
        archive=archive,
        release_dir=release_dir,
        sidecar=sidecar,
        metadata=metadata,
    )
    verified = _verify_release_bundle(
        archive_path,
        root,
        sidecar_path=sidecar_path,
        metadata_path=metadata_path,
    )
    target_root = _validate_install_root(
        install_root or default_install_root(root),
        root,
        protected_paths=(archive_path, sidecar_path, metadata_path),
    )
    _validate_release_inputs_against_install_root(target_root, (archive_path, sidecar_path, metadata_path))
    template_id = str(verified.metadata["template_id"])
    validate_windows_component(template_id, label="template_id")
    lock_path = target_root / template_id / ".lock"
    template_dir = target_root / template_id
    if template_dir.is_symlink():
        raise TemplateToolError("installed template directory is a symlink")
    if template_dir.exists() and not template_dir.is_dir():
        raise TemplateToolError("installed template directory is not a real directory")
    if dry_run:
        return _install_verified_bundle(verified, root, target_root, operation=operation, dry_run=True)
    template_dir_existed = template_dir.exists() or template_dir.is_symlink()
    lock = _InstallationLock(lock_path, template_id)
    try:
        lock.acquire()
        return _install_verified_bundle(
            verified,
            root,
            target_root,
            operation=operation,
            dry_run=False,
            lock=lock,
        )
    except Exception as original:
        recovery_errors: list[str] = []
        if lock.owned:
            try:
                lock.release()
            except Exception as error:
                recovery_errors.append(f"failed to release installation lock: {error}")
        if operation == "install" and not template_dir_existed and template_dir.is_dir() and not template_dir.is_symlink():
            try:
                versions = template_dir / "versions"
                if versions.is_dir() and not versions.is_symlink() and not any(versions.iterdir()):
                    remove_path_or_raise(versions)
                if not any(template_dir.iterdir()):
                    remove_path_or_raise(template_dir)
            except Exception as error:
                recovery_errors.append(f"failed to remove empty installation directory: {error}")
        if recovery_errors:
            raise TemplateToolError(f"{operation} transaction failed: {original}; {'; '.join(recovery_errors)}") from original
        raise


def install_release(
    root: Path,
    *,
    archive: Path | None = None,
    release_dir: Path | None = None,
    sidecar: Path | None = None,
    metadata: Path | None = None,
    install_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return _install_or_upgrade(
        root,
        operation="install",
        archive=archive,
        release_dir=release_dir,
        sidecar=sidecar,
        metadata=metadata,
        install_root=install_root,
        dry_run=dry_run,
    )


def upgrade_release(
    root: Path,
    *,
    archive: Path | None = None,
    release_dir: Path | None = None,
    sidecar: Path | None = None,
    metadata: Path | None = None,
    install_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return _install_or_upgrade(
        root,
        operation="upgrade",
        archive=archive,
        release_dir=release_dir,
        sidecar=sidecar,
        metadata=metadata,
        install_root=install_root,
        dry_run=dry_run,
    )


def rollback_installation(
    root: Path,
    *,
    template_id: str,
    to_version: str | None = None,
    install_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    validate_windows_component(template_id, label="template_id")
    target_root = _validate_install_root(install_root or default_install_root(root), root)
    template_dir = target_root / template_id
    if template_dir.is_symlink() or not template_dir.is_dir():
        raise TemplateToolError("template has no installed lifecycle state")
    lock_path = template_dir / ".lock"
    lock = _InstallationLock(lock_path, template_id)
    if not dry_run:
        lock.acquire()
    old_active_bytes: bytes | None = None
    old_active_captured = False
    try:
        active_path = template_dir / "active.json"
        state = _load_state(active_path, template_id)
        if state is None:
            raise TemplateToolError("template has no active installation")
        current_version = state["active_version"]
        target_version = to_version or state["previous_version"]
        if target_version is None:
            raise TemplateToolError("no previous installed version is available for rollback")
        target_version = _require_version(target_version, label="rollback target version")
        if target_version == current_version:
            raise TemplateToolError("rollback target must differ from the active version")
        target_dir = template_dir / "versions" / target_version
        if target_dir.is_symlink() or not target_dir.is_dir():
            raise TemplateToolError("rollback target version is not installed")
        target_report = _validate_installed_version(target_dir, template_id, target_version, root)
        if dry_run:
            return {
                "status": "planned",
                "operation": "rollback",
                "template_id": template_id,
                "version": target_version,
                "previous_active_version": current_version,
                "archive_sha256": target_report["archive_sha256"],
                "dry_run": True,
            }
        old_active_bytes = active_path.read_bytes() if active_path.is_file() else None
        old_active_captured = True
        new_state = {
            "schema_version": INSTALL_STATE_SCHEMA_VERSION,
            "template_id": template_id,
            "active_version": target_version,
            "previous_version": current_version,
            "updated_by_tool_version": RELEASE_TOOL_VERSION,
        }
        _write_state(active_path, new_state)
        if _load_state(active_path, template_id) != new_state:
            raise TemplateToolError("rollback active state verification failed")
        result = {
            "status": "passed",
            "operation": "rollback",
            "template_id": template_id,
            "version": target_version,
            "previous_active_version": current_version,
            "archive_sha256": target_report["archive_sha256"],
            "install_root": display_path(target_root, root),
            "dry_run": False,
        }
        try:
            lock.release()
        except Exception as lock_error:
            raise TemplateToolError(f"installation lock release failed: {lock_error}") from lock_error
        return result
    except Exception as original:
        recovery_errors: list[str] = []
        if old_active_captured:
            try:
                _restore_active_bytes(active_path, old_active_bytes)
                _assert_active_bytes(active_path, old_active_bytes)
            except Exception as recovery:
                recovery_errors.append(f"failed to restore active state: {recovery}")
        if lock.owned:
            try:
                lock.release()
            except Exception as recovery:
                recovery_errors.append(f"failed to release installation lock after rollback: {recovery}")
        message = f"rollback transaction failed: {original}"
        if recovery_errors:
            message += "; " + "; ".join(recovery_errors)
        raise TemplateToolError(message) from original


def _installed_template_ids(install_root: Path) -> list[str]:
    if not install_root.exists() and not install_root.is_symlink():
        return []
    if install_root.is_symlink() or not install_root.is_dir():
        raise TemplateToolError("install root must be a real directory")
    result: list[str] = []
    for path in sorted(install_root.iterdir(), key=lambda item: (item.name.casefold(), item.name)):
        if path.name.startswith("."):
            continue
        if path.is_symlink() or not path.is_dir():
            raise TemplateToolError(f"install root contains an unsafe entry: {path.name}")
        validate_windows_component(path.name, label="installed template id")
        result.append(path.name)
    return result


def list_installed(
    root: Path,
    *,
    template_id: str | None = None,
    install_root: Path | None = None,
    verify: bool = False,
) -> dict[str, Any]:
    target_root = _validate_install_root(install_root or default_install_root(root), root)
    if template_id is not None:
        validate_windows_component(template_id, label="template_id")
        template_ids = [template_id] if template_id in _installed_template_ids(target_root) else []
    else:
        template_ids = _installed_template_ids(target_root)
    templates: list[dict[str, Any]] = []
    for current_id in template_ids:
        template_dir = target_root / current_id
        active_path = template_dir / "active.json"
        state = _load_state(active_path, current_id)
        versions_dir = template_dir / "versions"
        versions: list[dict[str, Any]] = []
        if versions_dir.exists() or versions_dir.is_symlink():
            if versions_dir.is_symlink() or not versions_dir.is_dir():
                raise TemplateToolError(f"installed versions directory is unsafe: {versions_dir}")
            version_entries = list(versions_dir.iterdir())
            if any(item.name.startswith(".") for item in version_entries):
                raise TemplateToolError(f"installed versions directory contains a staging entry: {versions_dir}")
            for version_dir in sorted(
                version_entries,
                key=lambda item: (parse_semver(item.name).as_tuple(), item.name),
            ):
                if version_dir.is_symlink() or not version_dir.is_dir():
                    raise TemplateToolError(f"installed version is unsafe: {version_dir}")
                version = _require_version(version_dir.name, label="installed version directory")
                inventory_result = _validate_installed_inventory_only(version_dir, current_id, version)
                installation = inventory_result["installation"]
                is_active = bool(state and state["active_version"] == version)
                item: dict[str, Any] = {
                    "version": version,
                    "status": "active" if is_active else "installed",
                    "active": is_active,
                    "integrity": "passed",
                    "archive_sha256": installation["archive_sha256"],
                    "files": len(installation["files"]),
                }
                if verify:
                    item["verification"] = _validate_installed_version(
                        version_dir,
                        current_id,
                        version,
                        root,
                        inventory_result=inventory_result,
                    )
                versions.append(item)
        version_names = {item["version"] for item in versions}
        if state is None and version_names:
            raise TemplateToolError("installed versions exist without an active installation")
        if state is not None:
            if state["active_version"] not in version_names:
                raise TemplateToolError("active installation version is missing")
            if state["previous_version"] is not None and state["previous_version"] not in version_names:
                raise TemplateToolError("previous installation version is missing")
        templates.append(
            {
                "template_id": current_id,
                "active_version": state["active_version"] if state else None,
                "previous_version": state["previous_version"] if state else None,
                "versions": versions,
                "integrity": "passed",
                "verified": verify,
            }
        )
    return {
        "status": "passed",
        "tool_version": RELEASE_TOOL_VERSION,
        "install_root": display_path(target_root, root),
        "templates": templates,
        "count": len(templates),
        "integrity": "passed",
        "verify": verify,
    }
