"""Validate every canonical template package discovered in the repository."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
if str(DEFAULT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(DEFAULT_ROOT / "tools"))

from template_tooling.discovery import discover_packages, schema_path_for_package  # noqa: E402
from template_tooling.manifest import load_manifest  # noqa: E402
from template_tooling.models import TemplateToolError, parse_semver  # noqa: E402
from template_tooling.validation import validate_package_path, validation_succeeded  # noqa: E402


def _clip_diagnostic(value: object, limit: int = 6000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len("\n[truncated]"))].rstrip() + "\n[truncated]"


def _format_validation_failure(package, validation: dict, *, max_chars: int = 12000) -> str:
    package_info = validation.get("package") or {}
    validator = validation.get("validator") or {}
    command = validator.get("command") or []
    if isinstance(command, list):
        command_text = json.dumps(command, ensure_ascii=False)
    else:
        command_text = str(command)
    errors = validation.get("errors") or []
    if not isinstance(errors, list):
        errors = [errors]
    lines = [
        f"package: {package_info.get('id', package.template_id)} {package_info.get('version', package.version)}",
        f"manifest: {package_info.get('manifest', package.manifest_path)}",
        f"template: {package_info.get('template', package.template_path)}",
        f"validation_scope: {validation.get('validation_scope', '<not-run>')}",
        f"validator command: {command_text}",
        f"validator exit_code: {validator.get('exit_code', '<not-run>')}",
        "errors: " + "; ".join(str(error) for error in errors),
        "stderr:\n" + _clip_diagnostic(validator.get("stderr")),
        "stdout:\n" + _clip_diagnostic(validator.get("stdout")),
    ]
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    marker = "\n[truncated]"
    return text[: max(0, max_chars - len(marker))].rstrip() + marker


def _validate_legacy_descriptor(package: dict[str, Path | str]) -> str:
    """Keep the old helper shape for manifest-contract regression tests.

    The repository validator itself is discovery-driven.  This narrow adapter
    exists only for tests that deliberately pass an isolated manifest to the
    owner contract without pretending that the temporary directory is a
    canonical package.
    """
    manifest_path = Path(package["manifest"]).expanduser().resolve()
    schema_path = Path(package["schema"]).expanduser().resolve()
    with manifest_path.open("r", encoding="utf-8") as stream:
        import yaml

        manifest = yaml.safe_load(stream) or {}
    if not isinstance(manifest, dict):
        raise ValueError(f"{package['name']}: manifest must be a mapping")
    with schema_path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    Draft202012Validator.check_schema(schema)

    template_id = str(manifest.get("template", {}).get("id") or "")
    owners = {
        item.validator
        for item in discover_packages(DEFAULT_ROOT)
        if item.template_id == template_id and item.validator is not None
    }
    if len(owners) != 1:
        raise ValueError(f"{package['name']}: owner validator is ambiguous or unavailable")
    validator = next(iter(owners))
    scripts_path = validator.parent
    if str(scripts_path) not in sys.path:
        sys.path.insert(0, str(scripts_path))
    sys.modules.pop("package_common", None)
    from package_common import anchor_mode, validate_legacy_manifest_contract, validate_semantic_manifest_contract

    mode = anchor_mode(manifest)
    if mode == "legacy_coordinates":
        validate_legacy_manifest_contract(manifest)
    else:
        validate_semantic_manifest_contract(manifest)
    version = manifest.get("template", {}).get("version")
    fingerprint = str(manifest.get("fingerprint", {}).get("sha256") or "").upper()
    return f"{package['name']}: version={version} sha256={fingerprint} schema=valid"


def validate_package(package, root: Path | None = None) -> str:
    if isinstance(package, dict):
        return _validate_legacy_descriptor(package)
    root = (root or DEFAULT_ROOT).expanduser().resolve()
    if not package.is_canonical:
        raise ValueError(f"{package.package_dir}: package is not in a canonical skill template tree")
    if package.errors:
        raise ValueError(f"{package.template_id or '<unknown>'} {package.version or '<unknown>'}: " + "; ".join(package.errors))
    manifest = load_manifest(package.manifest_path)
    schema_path = schema_path_for_package(package)
    with schema_path.open("r", encoding="utf-8") as stream:
        schema = json.load(stream)
    Draft202012Validator.check_schema(schema)
    validation = validate_package_path(package.package_dir, root, identity_only=False)
    if not validation_succeeded(validation):
        raise ValueError(f"template validator failed:\n{_format_validation_failure(package, validation)}")
    if not validation.get("full_validation") or validation.get("status") != "passed":
        raise ValueError(f"{package.template_id} {package.version}: validator did not report a complete pass")
    expected_hash = package.fingerprint
    version = parse_semver(str(manifest.get("template", {}).get("version"))).as_tuple()
    return f"{package.template_id} {version[0]}.{version[1]}.{version[2]} sha256={expected_hash} schema=valid"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate all discovered canonical template packages")
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    root = args.repo_root.expanduser().resolve()
    try:
        packages = discover_packages(root)
        discover_errors = [
            f"{item.package_dir}: " + "; ".join(item.errors)
            for item in packages
            if item.errors
        ]
        if discover_errors:
            raise ValueError("template discovery failed: " + " | ".join(discover_errors))
        canonical = [item for item in packages if item.is_canonical]
        if not canonical:
            raise ValueError("no canonical template packages were discovered")
        canonical.sort(key=lambda item: (item.template_id, parse_semver(item.version).as_tuple(), item.package_dir.as_posix().casefold()))
        for package in canonical:
            print(validate_package(package, root))
        print(f"Validated {len(canonical)} canonical template packages.")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, TemplateToolError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
