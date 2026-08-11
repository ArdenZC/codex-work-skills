"""Validate static template package contracts without running owner validators."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from template_tooling.discovery import discover_packages, schema_path_for_package  # noqa: E402
from template_tooling.manifest import load_manifest  # noqa: E402
from template_tooling.models import TemplateToolError, parse_semver  # noqa: E402
from template_tooling.validation import validate_package_path, validation_succeeded  # noqa: E402


def validate_static_package(package, root: Path) -> str:
    if not package.is_canonical:
        raise ValueError(f"{package.package_dir}: package is not canonical")
    if package.errors:
        raise ValueError(f"{package.package_dir}: " + "; ".join(package.errors))
    manifest = load_manifest(package.manifest_path)
    schema_path = schema_path_for_package(package)
    with schema_path.open("r", encoding="utf-8") as stream:
        Draft202012Validator.check_schema(json.load(stream))
    report = validate_package_path(package.package_dir, root, identity_only=True)
    if not validation_succeeded(report, allow_identity_only=True):
        raise ValueError(f"{package.package_dir}: static identity validation failed: {report.get('errors')}")
    version = parse_semver(str(manifest.get("template", {}).get("version")))
    return f"{package.template_id} {version} sha256={package.fingerprint} schema=valid"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.repo_root.expanduser().resolve()
    try:
        packages = discover_packages(root)
        errors = [f"{item.package_dir}: " + "; ".join(item.errors) for item in packages if item.errors]
        if errors:
            raise ValueError("template discovery failed: " + " | ".join(errors))
        canonical = [item for item in packages if item.is_canonical]
        if not canonical:
            raise ValueError("no canonical template packages were discovered")
        canonical.sort(key=lambda item: (item.template_id, parse_semver(item.version).as_tuple(), item.package_dir.as_posix().casefold()))
        for package in canonical:
            print(validate_static_package(package, root))
        print(f"Validated {len(canonical)} static canonical template package contracts.")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, TemplateToolError) as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
