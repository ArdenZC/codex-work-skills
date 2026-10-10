"""Stdlib-only verification bootstrap for an installed Operator controller.

Run this file from the immutable, Owner-pinned controller installation with
``python -I -S -B``. It checks the externally pinned build inventory before
importing any controller or third-party validation module, then narrows ``sys.path`` to
the pinned controller, this Python installation's standard library, and its
pinned site-packages directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import sysconfig
from typing import Any


class BootstrapError(ValueError):
    """The installed controller is not the externally pinned build."""


REQUIRED_MODULES = frozenset({
    "operator_controller_bootstrap",
    "semantic_scope_records",
    "semantic_scope_review",
    "operation_provenance",
    "reviewer_qualification",
    "qualification_corpus_intake",
    "lifecycle_digest",
    "source_truth",
    "exemplar_contract",
    "exemplar_split",
    "path_safety",
})
REQUIRED_CONTROLLER_TREES = frozenset({"controller_scripts_tree", "controller_schemas_tree"})
REQUIRED_SCHEMAS = frozenset({
    "managed-reviewer-service-observation-v1.1.schema.json",
    "managed-service-capture-manifest-v1.1.schema.json",
    "managed-service-observation-policy-v1.1.schema.json",
    "operation-provenance-receipt-v1.2.schema.json",
    "operator-authority-profile-v1.1.schema.json",
    "operator-controller-build-inventory-v1.1.schema.json",
    "operator-role-authorization-v1.1.schema.json",
    "protected-operation-index-v1.1.schema.json",
    "qualification-adjudication.schema.json",
    "qualification-corpus-intake-v1.0.schema.json",
    "qualification-corpus.schema.json",
    "reviewer-configuration-v1.1.schema.json",
    "reviewer-qualification-v1.1.schema.json",
    "semantic-scope-review.schema.json",
    "source-truth-manifest.schema.json",
})
REQUIRED_PACKAGES = frozenset({
    "attr",
    "attrs",
    "jsonschema",
    "jsonschema_specifications",
    "referencing",
    "rpds",
})
REQUIRED_DEPENDENCY_MODULES = frozenset({"typing_extensions"})
_BOOTSTRAP_ATTESTATION: tuple[str, str] | None = None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BootstrapError(message)


def bootstrap_attested(expected_sha256: str, controller_root: Path) -> bool:
    return (
        sys.flags.isolated
        and _BOOTSTRAP_ATTESTATION == (
            expected_sha256,
            str(controller_root.resolve(strict=True)),
        )
    )


def _ordinary_path(path: Path) -> Path:
    _require(path.is_absolute(), f"path must be absolute: {path}")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        info = cursor.lstat()
        _require(not stat.S_ISLNK(info.st_mode), f"symlink path component refused: {cursor}")
    return path


def sha256_file(path: Path) -> str:
    file_path = _ordinary_path(path)
    info = file_path.stat(follow_symlinks=False)
    _require(stat.S_ISREG(info.st_mode), f"not a regular file: {path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path, *, include_bytecode_cache: bool = False) -> str:
    """Hash a directory tree; runtime dependency pins include bytecode caches."""
    root = _ordinary_path(root)
    _require(root.is_dir(), f"package path is not a directory: {root}")
    rows: list[tuple[str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            info = child.lstat()
            _require(not stat.S_ISLNK(info.st_mode), f"symlink in runtime package: {child}")
            _require(stat.S_ISDIR(info.st_mode), f"special entry in runtime package: {child}")
            if include_bytecode_cache or name != "__pycache__":
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = current_path / name
            if (not include_bytecode_cache and path.suffix.casefold() in {".pyc", ".pyo"}
                    and "__pycache__" in path.parts):
                continue
            info = path.lstat()
            _require(not stat.S_ISLNK(info.st_mode), f"symlink in runtime package: {path}")
            _require(stat.S_ISREG(info.st_mode), f"special entry in runtime package: {path}")
            relative = path.relative_to(root).as_posix()
            rows.append((relative, sha256_file(path)))
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_runtime_tree(root: Path) -> str:
    """Hash every site-packages entry, including symlink target identity/bytes."""
    root = _ordinary_path(root)
    _require(root.is_dir(), f"runtime package root is not a directory: {root}")
    rows: list[tuple[str, str, str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            path = current_path / name
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                _require(resolved.is_file(), f"runtime directory symlink is unsupported: {path}")
                rows.append((relative, "symlink-file", target, sha256_file(resolved)))
            else:
                _require(stat.S_ISDIR(info.st_mode), f"special runtime entry: {path}")
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = current_path / name
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                _require(resolved.is_file(), f"runtime symlink target is not a file: {path}")
                rows.append((relative, "symlink-file", target, sha256_file(resolved)))
            else:
                _require(stat.S_ISREG(info.st_mode), f"special runtime entry: {path}")
                rows.append((relative, "file", "", sha256_file(path)))
    rows.sort(key=lambda item: item[0])
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate build-inventory JSON key: {key}")
        result[key] = value
    return result


def _read_build_inventory(path: Path, expected_sha256: str) -> tuple[bytes, dict[str, Any]]:
    raw = _ordinary_path(path).read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256,
             "Owner-pinned controller build inventory SHA mismatch")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"invalid controller build inventory: {exc}") from exc
    _require(isinstance(payload, dict), "controller build inventory must be an object")
    _require(payload.get("build_inventory_version") == "1.1",
             "controller bootstrap requires Build Inventory 1.1")
    return raw, payload


def verify_build_inventory(
    inventory_path: Path,
    expected_sha256: str,
    controller_root: Path | None = None,
    *,
    require_isolated: bool = True,
    verify_runtime_tree: bool = True,
) -> dict[str, Any]:
    """Verify files and runtime before importing any non-stdlib dependencies."""
    if require_isolated:
        _require(sys.flags.isolated, "Operator controller must start with Python -I")
        _require(sys.flags.no_site, "Operator controller must start with Python -S")
        _require(sys.dont_write_bytecode, "Operator controller must start with Python -B")
    raw, payload = _read_build_inventory(inventory_path, expected_sha256)
    del raw
    root = Path(payload["controller_root"])
    _ordinary_path(root)
    _require(root.is_dir(), "pinned controller root is unavailable")
    if controller_root is not None:
        _require(root.resolve(strict=True) == controller_root.resolve(strict=True),
                 "controller root differs from the external launch pin")

    runtime = payload["python_runtime"]
    executable = Path(runtime["python_executable"])
    _require(executable.resolve(strict=True) == Path(sys.executable).resolve(strict=True),
             "Python executable differs from the pinned controller runtime")
    _require(sys.version.split()[0] == runtime["python_version"],
             "Python version differs from the pinned controller runtime")
    _require(sha256_file(executable) == runtime["python_executable_sha256"],
             "Python executable SHA differs from the pinned controller runtime")
    purelib = Path(sysconfig.get_paths()["purelib"]).resolve(strict=True)
    site_packages = Path(runtime["site_packages_root"]).resolve(strict=True)
    _require(purelib == site_packages,
             "site-packages root differs from the pinned controller runtime")
    if verify_runtime_tree:
        _require(sha256_runtime_tree(site_packages) == runtime["site_packages_sha256"],
                 "site-packages runtime tree differs from the Owner-pinned build")

    rows = payload["components"]
    _require(isinstance(rows, list), "controller components must be an array")
    components = {row["component_id"]: row for row in rows}
    _require(len(components) == len(rows), "duplicate controller build component")
    modules = {key for key, row in components.items() if row["component_type"] == "python_module"}
    schemas = {key for key, row in components.items() if row["component_type"] == "json_schema"}
    trees = {key for key, row in components.items() if row["component_type"] == "controller_tree"}
    packages = {key for key, row in components.items() if row["component_type"] == "python_package"}
    dependency_modules = {
        key for key, row in components.items()
        if row["component_type"] == "python_dependency_module"
    }
    _require(REQUIRED_MODULES <= modules and REQUIRED_SCHEMAS <= schemas
             and REQUIRED_CONTROLLER_TREES <= trees
             and REQUIRED_PACKAGES <= packages
             and REQUIRED_DEPENDENCY_MODULES <= dependency_modules,
             "operator controller build inventory is incomplete")

    for row in rows:
        kind = row["component_type"]
        path = Path(row["runtime_path"])
        _ordinary_path(path)
        if kind in {"python_module", "json_schema"}:
            _require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
                     f"controller file outside pinned install root: {row['component_id']}")
            actual = sha256_file(path)
        elif kind == "python_package":
            _require(path.resolve(strict=True).is_relative_to(site_packages),
                     f"Python package outside pinned site-packages: {row['component_id']}")
            actual = sha256_tree(path, include_bytecode_cache=True)
        elif kind == "controller_tree":
            _require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
                     f"controller tree outside pinned install root: {row['component_id']}")
            if require_isolated:
                for current, directories, files in os.walk(path, topdown=True, followlinks=False):
                    _require("__pycache__" not in directories,
                             f"controller installation contains bytecode cache: {current}")
                    _require(not any(Path(name).suffix.casefold() in {".pyc", ".pyo"}
                                     for name in files),
                             f"controller installation contains loose bytecode: {current}")
            actual = sha256_tree(path)
        elif kind == "python_dependency_module":
            _require(path.resolve(strict=True).is_relative_to(site_packages),
                     f"Python dependency outside pinned site-packages: {row['component_id']}")
            actual = sha256_file(path)
        else:
            raise BootstrapError(f"unsupported controller component type: {kind}")
        _require(actual == row["sha256"],
                 f"controller component SHA mismatch: {row['component_id']}")

    return payload


def prepare_isolated_runtime(
    inventory_path: Path,
    expected_sha256: str,
    controller_root: Path | None = None,
) -> dict[str, Any]:
    global _BOOTSTRAP_ATTESTATION
    payload = verify_build_inventory(inventory_path, expected_sha256, controller_root)
    root = Path(payload["controller_root"]).resolve(strict=True)
    runtime = payload["python_runtime"]
    paths = sysconfig.get_paths()
    standard_root = Path(paths["stdlib"]).resolve(strict=True)
    site_packages = Path(runtime["site_packages_root"]).resolve(strict=True)
    prefix = Path(sys.prefix).resolve(strict=True)
    allowed = [str(root / "scripts")]
    for value in sys.path:
        if not value:
            continue
        candidate = Path(value)
        if not candidate.exists():
            continue
        resolved = candidate.resolve(strict=True)
        if (resolved.is_relative_to(standard_root)
                or resolved.is_relative_to(site_packages)
                or resolved.is_relative_to(prefix)):
            allowed.append(str(resolved))
    allowed.extend((str(standard_root), str(site_packages)))
    sys.path[:] = list(dict.fromkeys(allowed))
    _BOOTSTRAP_ATTESTATION = (
        expected_sha256,
        str(root),
    )
    return payload


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-inventory", type=Path, required=True)
    parser.add_argument("--build-sha256", required=True)
    parser.add_argument("--controller-root", type=Path)
    parser.add_argument("--probe-module", help="import one pinned module after verification")
    parser.add_argument("--entrypoint", help="run a pinned module:function after verification")
    args = parser.parse_args()
    payload = prepare_isolated_runtime(
        args.build_inventory, args.build_sha256, args.controller_root
    )
    if args.probe_module:
        row = next((item for item in payload["components"]
                    if item["component_id"] == args.probe_module
                    and item["component_type"] == "python_module"), None)
        _require(row is not None, "probe module is not present in pinned build inventory")
        import importlib

        loaded = importlib.import_module(args.probe_module)
        _require(Path(loaded.__file__).resolve(strict=True)
                 == Path(row["runtime_path"]).resolve(strict=True),
                 "loaded module origin differs from pinned controller path")
        print(f"loaded={args.probe_module} path={Path(loaded.__file__).resolve(strict=True)}")
    elif args.entrypoint:
        module_name, separator, function_name = args.entrypoint.partition(":")
        _require(bool(separator and function_name), "entrypoint must use module:function syntax")
        row = next((item for item in payload["components"]
                    if item["component_id"] == module_name
                    and item["component_type"] == "python_module"), None)
        _require(row is not None, "entrypoint module is not present in pinned build inventory")
        import importlib

        loaded = importlib.import_module(module_name)
        _require(Path(loaded.__file__).resolve(strict=True)
                 == Path(row["runtime_path"]).resolve(strict=True),
                 "loaded entrypoint origin differs from pinned controller path")
        function = getattr(loaded, function_name, None)
        _require(callable(function), "pinned entrypoint is not callable")
        result = function()
        if result is not None:
            print(result)
    else:
        print("controller_build=verified")
    return 0


if __name__ == "__main__":
    # The controller modules import this name after bootstrap. Share the
    # verified state with the already-running __main__ module.
    sys.modules["operator_controller_bootstrap"] = sys.modules[__name__]
    try:
        raise SystemExit(_main())
    except (BootstrapError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"operator controller bootstrap blocked: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
