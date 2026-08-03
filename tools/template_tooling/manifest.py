"""Manifest loading, identity and fingerprint helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from .models import SemVer, TemplatePackage, TemplateToolError, package_dir_matches_version, parse_semver
from .paths import ensure_no_parent_escape, safe_relative, validate_windows_component


FINGERPRINT_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise TemplateToolError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TemplateToolError(f"manifest must be a mapping: {path}")
    return value


def manifest_identity(manifest: dict[str, Any], path: Path) -> tuple[str, str, str, str, SemVer]:
    template = manifest.get("template")
    if not isinstance(template, dict):
        raise TemplateToolError(f"manifest template section must be a mapping: {path}")
    template_id = template.get("id")
    version = template.get("version")
    format_name = template.get("format")
    template_file = template.get("file")
    if not isinstance(template_id, str) or not template_id.strip():
        raise TemplateToolError(f"manifest template.id is required: {path}")
    try:
        validate_windows_component(template_id, label="manifest template.id")
    except TemplateToolError as exc:
        raise TemplateToolError(str(exc)) from exc
    if not isinstance(format_name, str) or not format_name.strip():
        raise TemplateToolError(f"manifest template.format is required: {path}")
    semver = parse_semver(version)
    template_rel = safe_relative(str(template_file or ""), label="template.file")
    template_path = (path.parent / template_rel).resolve(strict=False)
    ensure_no_parent_escape(template_path, path.parent, label="template.file")
    fingerprint = manifest_fingerprint(manifest, path)
    return template_id, str(semver), format_name, str(template_path), semver


def manifest_fingerprint(manifest: dict[str, Any], path: Path) -> str:
    fingerprint = manifest.get("fingerprint")
    if not isinstance(fingerprint, dict):
        raise TemplateToolError(f"manifest fingerprint section is required: {path}")
    unsupported = sorted(set(fingerprint) - {"algorithm", "sha256", "value"})
    if unsupported:
        raise TemplateToolError(f"fingerprint contains unsupported keys: {unsupported}")
    if fingerprint.get("algorithm") != "sha256":
        raise TemplateToolError("fingerprint.algorithm must be sha256")
    if "sha256" not in fingerprint:
        raise TemplateToolError("fingerprint.sha256 is required")
    if "value" not in fingerprint:
        raise TemplateToolError("fingerprint.value is required")
    sha_value = fingerprint.get("sha256")
    value = fingerprint.get("value")
    if not isinstance(sha_value, str) or not FINGERPRINT_RE.fullmatch(sha_value):
        raise TemplateToolError("fingerprint.sha256 must be a 64-character hexadecimal SHA-256")
    if not isinstance(value, str) or not FINGERPRINT_RE.fullmatch(value):
        raise TemplateToolError("fingerprint.value must be a 64-character hexadecimal SHA-256")
    if sha_value.upper() != value.upper():
        raise TemplateToolError("fingerprint.sha256 and fingerprint.value must match")
    return sha_value.upper()


def manifest_reference(manifest: dict[str, Any], key: str, manifest_path: Path) -> Path | None:
    template = manifest.get("template")
    if not isinstance(template, dict) or not template.get(key):
        return None
    raw_reference = str(template[key])
    reference = Path(raw_reference)
    if reference.is_absolute() or not raw_reference:
        raise TemplateToolError(f"template.{key} must be a relative path: {raw_reference!r}")
    resolved = (manifest_path.parent / reference).resolve(strict=False)
    # Base packages are intentionally siblings of a version package.  Keep
    # the reference inside the template-id directory while rejecting paths
    # that escape to an unrelated filesystem location.
    ensure_no_parent_escape(resolved, manifest_path.parent.parent, label=f"template.{key}")
    return resolved


def package_template_path(manifest: dict[str, Any], manifest_path: Path) -> Path:
    template = manifest.get("template")
    if not isinstance(template, dict):
        raise TemplateToolError(f"manifest template section must be a mapping: {manifest_path}")
    template_rel = safe_relative(str(template.get("file") or ""), label="template.file")
    template_path = (manifest_path.parent / template_rel).resolve(strict=False)
    ensure_no_parent_escape(template_path, manifest_path.parent, label="template.file")
    return template_path


def inspect_manifest_package(package_dir: Path, validator: Path | None, *, is_canonical: bool, is_default: bool) -> TemplatePackage:
    manifest_path = package_dir / "manifest.yaml"
    errors: list[str] = []
    warnings: list[str] = []
    manifest: dict[str, Any] = {}
    template_id = ""
    version = ""
    format_name = ""
    fingerprint = ""
    template_path = package_dir / "<invalid-template>"
    try:
        manifest = load_manifest(manifest_path)
        template_id, version, format_name, template_string, _ = manifest_identity(manifest, manifest_path)
        template_path = Path(template_string)
        fingerprint = manifest_fingerprint(manifest, manifest_path)
        if not package_dir_matches_version(package_dir.name, version):
            errors.append(f"package directory name {package_dir.name!r} does not equal manifest version {version!r}")
        if not template_path.is_file():
            errors.append(f"template file does not exist: {template_path}")
        elif sha256_file(template_path) != fingerprint:
            errors.append(f"fingerprint mismatch for {template_path.name}")
    except TemplateToolError as exc:
        errors.append(str(exc))
        template_id = str(manifest.get("template", {}).get("id") or "") if isinstance(manifest.get("template"), dict) else ""
        version = str(manifest.get("template", {}).get("version") or "") if isinstance(manifest.get("template"), dict) else ""
        format_name = str(manifest.get("template", {}).get("format") or "") if isinstance(manifest.get("template"), dict) else ""
        fingerprint = str(manifest.get("fingerprint", {}).get("sha256") or "").upper() if isinstance(manifest.get("fingerprint"), dict) else ""
    except OSError as exc:
        errors.append(f"cannot inspect package {package_dir}: {exc}")
    if validator is None:
        errors.append("owner validator scripts/validate_template.py was not found")
    return TemplatePackage(
        template_id=template_id,
        version=version,
        format=format_name,
        package_dir=package_dir,
        template_path=template_path,
        manifest_path=manifest_path,
        fingerprint=fingerprint,
        validator=validator,
        is_default=is_default,
        is_canonical=is_canonical,
        manifest=manifest,
        errors=errors,
        warnings=warnings,
    )
