#!/usr/bin/env python3
"""Discover, scaffold, validate, promote and archive template packages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from template_tooling.archive import archive_package
from template_tooling.discovery import discover_packages
from template_tooling.models import TOOL_VERSION, TemplateToolError
from template_tooling.paths import repo_root, resolve_path
from template_tooling.promotion import promote_package
from template_tooling.scaffold import scaffold_package
from template_tooling.validation import validate_package_path, validation_succeeded


def _add_repo_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=argparse.SUPPRESS, help="repository root for discovery and validation")


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit structured JSON")


def _add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="show the operation without creating files")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="template_package.py", description="Generic versioned template package tooling")
    parser.add_argument("--repo-root", type=Path, default=repo_root(), help="repository root for discovery and validation")
    parser.add_argument("--version", action="version", version=TOOL_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)

    discover = commands.add_parser("discover", help="discover template packages")
    _add_repo_root(discover)
    _add_json(discover)

    scaffold = commands.add_parser("scaffold", help="create a non-canonical package")
    _add_repo_root(scaffold)
    scaffold.add_argument("--base-package", required=True, type=Path)
    scaffold.add_argument("--version", required=True)
    scaffold.add_argument("--output-dir", required=True, type=Path)
    scaffold.add_argument("--generator-version")
    scaffold.add_argument("--allow-unsupported-minor", action="store_true")
    scaffold.add_argument("--report-path", type=Path)
    _add_dry_run(scaffold)
    _add_json(scaffold)

    validate = commands.add_parser("validate", help="validate a template package")
    _add_repo_root(validate)
    validate.add_argument("--package", required=True, type=Path)
    validate.add_argument("--identity-only", action="store_true", help="run identity checks only; this is not a full pass")
    _add_json(validate)

    promote = commands.add_parser("promote", help="atomically promote a package to canonical")
    _add_repo_root(promote)
    promote.add_argument("--package", required=True, type=Path)
    _add_dry_run(promote)
    _add_json(promote)

    archive = commands.add_parser("archive", help="create a deterministic package archive")
    _add_repo_root(archive)
    archive.add_argument("--package", required=True, type=Path)
    archive.add_argument("--output-dir", required=True, type=Path)
    _add_dry_run(archive)
    _add_json(archive)
    return parser


def _json_or_text(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if isinstance(value, dict):
        if "status" in value:
            print(f"status: {value['status']}")
        if "errors" in value and value["errors"]:
            for error in value["errors"]:
                print(f"error: {error}")
        for key in ("package", "target", "archive", "archive_sha256", "promotable", "reason"):
            if key in value:
                print(f"{key}: {value[key]}")
        if "packages" in value:
            for package in value["packages"]:
                status = "invalid" if package.get("errors") else "ok"
                print(f"{status}: {package.get('id') or '<unknown>'} {package.get('version') or '<unknown>'} {package.get('package')}")
        return
    print(value)


def _run(args: argparse.Namespace) -> tuple[int, Any]:
    root = resolve_path(args.repo_root)
    if args.command == "discover":
        packages = discover_packages(root)
        payload = {
            "tool_version": TOOL_VERSION,
            "root": ".",
            "packages": [package.to_dict(root) for package in packages],
            "count": len(packages),
            "errors": [
                {"package": package.to_dict(root)["package"], "errors": package.errors}
                for package in packages
                if package.errors
            ],
        }
        return (1 if payload["errors"] else 0), payload
    if args.command == "scaffold":
        result = scaffold_package(
            resolve_path(args.base_package),
            resolve_path(args.output_dir),
            root,
            version=args.version,
            generator_version=args.generator_version,
            allow_unsupported_minor=args.allow_unsupported_minor,
            dry_run=args.dry_run,
            report_path=resolve_path(args.report_path) if args.report_path else None,
        )
        return 0, result
    if args.command == "validate":
        result = validate_package_path(
            resolve_path(args.package),
            root,
            identity_only=args.identity_only,
        )
        return (0 if validation_succeeded(result, allow_identity_only=args.identity_only) else 1), result
    if args.command == "promote":
        result = promote_package(resolve_path(args.package), root, dry_run=args.dry_run)
        return 0, result
    if args.command == "archive":
        result = archive_package(resolve_path(args.package), resolve_path(args.output_dir), root, dry_run=args.dry_run)
        return 0, result
    raise TemplateToolError(f"unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code, payload = _run(args)
    except (TemplateToolError, OSError, ValueError, TypeError) as exc:
        if getattr(args, "json", False):
            print(json.dumps({"status": "failed", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    _json_or_text(payload, getattr(args, "json", False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
