#!/usr/bin/env python3
"""Discover, author, archive, verify and install template packages."""

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
from template_tooling.release import (
    install_release,
    list_installed,
    release_package,
    resolve_release_inputs,
    rollback_installation,
    upgrade_release,
    verify_release_bundle,
)
from template_tooling.scaffold import scaffold_package
from template_tooling.validation import validate_package_path, validation_succeeded


def _lexical_path(value: Path) -> Path:
    """Make an absolute path without resolving symlinks."""
    return value.expanduser().absolute()


def _add_repo_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", type=Path, default=argparse.SUPPRESS, help="repository root for discovery and validation")


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit structured JSON")


def _add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="show the operation without creating files")


def _add_release_source(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="release ZIP archive")
    source.add_argument("--release-dir", type=Path, help="directory containing one release ZIP and its assets")
    parser.add_argument("--sha256-file", dest="sidecar", type=Path, help="archive SHA-256 sidecar")
    parser.add_argument("--metadata", type=Path, help="archive metadata JSON")


def _add_install_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--install-root", type=Path, help="immutable install root (default: installed/template-packages)")


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

    verify_release = commands.add_parser("verify-release", help="verify a release archive and its metadata contract")
    _add_repo_root(verify_release)
    _add_release_source(verify_release)
    _add_json(verify_release)

    install = commands.add_parser("install", help="install an immutable template package release")
    _add_repo_root(install)
    _add_release_source(install)
    _add_install_root(install)
    _add_dry_run(install)
    _add_json(install)

    upgrade = commands.add_parser("upgrade", help="install a newer release and activate it")
    _add_repo_root(upgrade)
    _add_release_source(upgrade)
    _add_install_root(upgrade)
    _add_dry_run(upgrade)
    _add_json(upgrade)

    rollback = commands.add_parser("rollback", help="switch active state to another installed version")
    _add_repo_root(rollback)
    rollback.add_argument("--template-id", required=True)
    rollback.add_argument("--to-version")
    _add_install_root(rollback)
    _add_dry_run(rollback)
    _add_json(rollback)

    installed = commands.add_parser("list-installed", help="list immutable installed template versions")
    _add_repo_root(installed)
    installed.add_argument("--template-id")
    _add_install_root(installed)
    installed.add_argument("--verify", action="store_true", help="run current trusted owner validation")
    _add_json(installed)

    release = commands.add_parser("release", help="archive a canonical package and create a release plan")
    _add_repo_root(release)
    release.add_argument("--package", type=Path)
    release.add_argument("--template-id")
    release.add_argument("--version")
    release.add_argument("--output-dir", type=Path)
    _add_dry_run(release)
    _add_json(release)
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
        for key in (
            "package",
            "target",
            "archive",
            "archive_sha256",
            "install_root",
            "plan",
            "promotable",
            "reason",
        ):
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
            Path(args.output_dir).expanduser().absolute(),
            root,
            version=args.version,
            generator_version=args.generator_version,
            allow_unsupported_minor=args.allow_unsupported_minor,
            dry_run=args.dry_run,
            report_path=(Path(args.report_path).expanduser().absolute() if args.report_path else None),
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
        output_dir = Path(args.output_dir).expanduser().absolute()
        result = archive_package(resolve_path(args.package), output_dir, root, dry_run=args.dry_run)
        return 0, result
    if args.command == "verify-release":
        archive, sidecar, metadata = resolve_release_inputs(
            archive=(_lexical_path(args.archive) if args.archive else None),
            release_dir=(_lexical_path(args.release_dir) if args.release_dir else None),
            sidecar=(_lexical_path(args.sidecar) if args.sidecar else None),
            metadata=(_lexical_path(args.metadata) if args.metadata else None),
        )
        result = verify_release_bundle(archive, root, sidecar_path=sidecar, metadata_path=metadata)
        return 0, result
    if args.command in {"install", "upgrade"}:
        function = install_release if args.command == "install" else upgrade_release
        result = function(
            root,
            archive=(_lexical_path(args.archive) if args.archive else None),
            release_dir=(_lexical_path(args.release_dir) if args.release_dir else None),
            sidecar=(_lexical_path(args.sidecar) if args.sidecar else None),
            metadata=(_lexical_path(args.metadata) if args.metadata else None),
            install_root=(_lexical_path(args.install_root) if args.install_root else None),
            dry_run=args.dry_run,
        )
        return 0, result
    if args.command == "rollback":
        result = rollback_installation(
            root,
            template_id=args.template_id,
            to_version=args.to_version,
            install_root=(_lexical_path(args.install_root) if args.install_root else None),
            dry_run=args.dry_run,
        )
        return 0, result
    if args.command == "list-installed":
        result = list_installed(
            root,
            template_id=args.template_id,
            install_root=(_lexical_path(args.install_root) if args.install_root else None),
            verify=args.verify,
        )
        return 0, result
    if args.command == "release":
        result = release_package(
            root,
            package=(resolve_path(args.package) if args.package else None),
            template_id=args.template_id,
            version=args.version,
            output_dir=(Path(args.output_dir).expanduser().absolute() if args.output_dir else None),
            dry_run=args.dry_run,
        )
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
