#!/usr/bin/env python3
"""Independent stdlib-only verifier for a candidate Controller Build Inventory.

This verifier intentionally does not import the builder, controller modules,
third-party packages, or anything from PYTHONPATH. It recomputes all pinned
paths and byte digests from the separately supplied build plan.
"""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from typing import Any


class VerifyError(ValueError):
    """Candidate Inventory cannot be independently verified."""


_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_:-]{0,159}$")
_LOCK = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9._+!]*)(?:\s+--hash=sha256:([0-9a-f]{64}))+\s*$")
_KINDS = {"python_module", "json_schema", "python_package",
          "python_dependency_module", "controller_tree"}


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)

REQUIRED_MODULES = {
    "operator_controller_bootstrap", "semantic_scope_records", "semantic_scope_review",
    "operation_provenance", "reviewer_qualification", "qualification_corpus_intake",
    "lifecycle_digest", "source_truth", "exemplar_contract", "exemplar_split", "path_safety",
}
REQUIRED_SCHEMAS = {
    "managed-reviewer-service-observation-v1.1.schema.json",
    "managed-service-capture-manifest-v1.1.schema.json",
    "managed-service-observation-policy-v1.1.schema.json",
    "operation-provenance-receipt-v1.2.schema.json",
    "operator-authority-profile-v1.1.schema.json",
    "operator-controller-build-inventory-v1.1.schema.json",
    "operator-role-authorization-v1.1.schema.json",
    "protected-operation-index-v1.1.schema.json",
    "qualification-adjudication.schema.json", "qualification-corpus-intake-v1.0.schema.json",
    "qualification-corpus.schema.json", "reviewer-configuration-v1.1.schema.json",
    "reviewer-qualification-v1.1.schema.json", "semantic-scope-review.schema.json",
    "source-truth-manifest.schema.json",
}
REQUIRED_PACKAGES = {
    "attr", "attrs", "jsonschema", "jsonschema_specifications", "referencing", "rpds",
}
REQUIRED_DEPENDENCY_MODULES = {"typing_extensions"}
PLAN_KEYS = {
    "schema_version", "purpose", "source_commit", "source_checkout", "target_platform",
    "operator_uid", "operator_gid",
    "controller_id", "inventory_key", "generation_id", "generation_root",
    "allocation_plan_sha256", "allocation_record_path", "allocation_record_sha256",
    "controller_root", "protected_trust_root",
    "scripts_root", "schemas_root", "runtime_root", "python_executable", "python_version",
    "build_python_executable", "site_packages_root", "requirements_lock", "requirements_lock_sha256", "wheelhouse_root",
    "wheelhouse_manifest", "wheelhouse_manifest_sha256", "inventory_output",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerifyError(message)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _path(raw: Any, label: str) -> Path:
    _require(isinstance(raw, str) and raw.startswith("/") and "\x00" not in raw
             and "\\" not in raw and "//" not in raw, f"invalid absolute {label}")
    _require(os.path.normpath(raw) == raw and all(x not in {".", ".."} for x in raw.split("/")),
             f"non-canonical {label}")
    return Path(raw)


def _ordinary(path: Path, *, directory: bool | None = None, readonly: bool = True) -> os.stat_result:
    _require(path.is_absolute() and os.path.normpath(str(path)) == str(path),
             f"path is not absolute and canonical: {path}")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        info = current.lstat()
        _require(not stat.S_ISLNK(info.st_mode), f"symlink path component refused: {current}")
    info = path.lstat()
    if directory is True:
        _require(stat.S_ISDIR(info.st_mode), f"expected directory: {path}")
    elif directory is False:
        _require(stat.S_ISREG(info.st_mode), f"expected regular file: {path}")
    if not stat.S_ISDIR(info.st_mode):
        _require(info.st_nlink == 1, f"hard-linked file refused: {path}")
    if readonly:
        _require(info.st_mode & 0o022 == 0, f"group/world-writable path refused: {path}")
    _require(str(path.resolve(strict=True)) == str(path), f"path alias refused: {path}")
    return info


def _file_sha(path: Path) -> str:
    _ordinary(path, directory=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha(root: Path, *, bytecode: bool = False) -> str:
    _ordinary(root, directory=True)
    rows: list[tuple[str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        retained = []
        for name in sorted(directories):
            path = base / name
            info = path.lstat()
            _require(stat.S_ISDIR(info.st_mode), f"symlink/special directory: {path}")
            if bytecode or name != "__pycache__":
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = base / name
            if not bytecode and path.suffix.casefold() in {".pyc", ".pyo"} and "__pycache__" in path.parts:
                continue
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode), f"symlink/special file: {path}")
            rows.append((path.relative_to(root).as_posix(), _file_sha(path)))
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _runtime_sha(root: Path) -> str:
    _ordinary(root, directory=True)
    rows: list[tuple[str, str, str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        for name in directories:
            child = base / name
            info = child.lstat()
            _require(stat.S_ISDIR(info.st_mode), f"site-packages symlink/special directory: {child}")
        directories[:] = sorted(directories)
        for name in sorted(files):
            path = base / name
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode), f"site-packages symlink/special file: {path}")
            rows.append((path.relative_to(root).as_posix(), "file", "", _file_sha(path)))
    rows.sort(key=lambda row: row[0])
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _read_plan(path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    _require(_SHA.fullmatch(expected_sha256 or "") is not None,
             "independent build plan SHA-256 is required")
    _ordinary(path, directory=False)
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    _require(actual == expected_sha256, "build plan SHA differs from independent pin")
    try:
        plan = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"invalid build plan: {exc}") from exc
    _require(isinstance(plan, dict) and set(plan) == PLAN_KEYS,
             "build plan has missing or unknown fields")
    _require(plan["schema_version"] == "rq03f-build-inputs-1.0"
             and plan["purpose"] == "candidate_inventory_only", "unsupported/non-candidate build plan")
    _require(type(plan["operator_uid"]) is int and plan["operator_uid"] > 0
             and type(plan["operator_gid"]) is int and plan["operator_gid"] > 0
             and os.geteuid() != 0 and os.getuid() == os.geteuid() == plan["operator_uid"]
             and os.getgid() == os.getegid() == plan["operator_gid"]
             and set(os.getgroups()) <= {plan["operator_gid"]},
             "verifier process identity differs from independent non-root build plan")
    _require(_COMMIT.fullmatch(str(plan["source_commit"])) is not None, "invalid pinned source commit")
    _require(_SHA.fullmatch(str(plan["allocation_plan_sha256"])) is not None
             and _SHA.fullmatch(str(plan["allocation_record_sha256"])) is not None,
             "missing independent allocation plan/record pins")
    for field in ("source_checkout", "generation_root", "allocation_record_path", "controller_root",
                  "protected_trust_root", "scripts_root",
                  "schemas_root", "runtime_root", "python_executable", "site_packages_root",
                  "build_python_executable", "requirements_lock", "wheelhouse_root", "wheelhouse_manifest", "inventory_output"):
        plan[field] = _path(plan[field], field)
    _require(plan["scripts_root"] == plan["controller_root"] / "scripts"
             and plan["schemas_root"] == plan["controller_root"] / "schemas",
             "Controller module/schema paths differ from the exact root binding")
    _require(plan["controller_root"] == plan["generation_root"] / "controller"
             and plan["runtime_root"] == plan["generation_root"] / "runtime"
             and plan["allocation_record_path"] == plan["generation_root"] / ".rq03f-allocation-record.json",
             "final install paths do not match the exclusive Generation record")
    _require(isinstance(plan["generation_id"], str)
             and re.fullmatch(r"rq03f-(?:[a-z0-9]|[a-z0-9][a-z0-9-]{0,54}[a-z0-9])", plan["generation_id"]),
             "invalid pinned Generation ID")
    _ordinary(plan["allocation_record_path"], directory=False)
    allocation_raw = plan["allocation_record_path"].read_bytes()
    _require(hashlib.sha256(allocation_raw).hexdigest() == plan["allocation_record_sha256"],
             "exclusive Generation allocation record hash mismatch")
    try:
        allocation = json.loads(allocation_raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"invalid exclusive Generation record: {exc}") from exc
    _require(isinstance(allocation, dict)
             and allocation.get("record_version") == "rq03f-allocation-record-1.0"
             and allocation.get("allocation_status") == "complete"
             and allocation.get("operation_kind") == "generation"
             and allocation.get("operation_scope") == "qualification_controller_generation"
             and allocation.get("target_id") == plan["generation_id"]
             and allocation.get("source_commit") == plan["source_commit"]
             and allocation.get("owner_plan_sha256") == plan["allocation_plan_sha256"]
             and allocation.get("protected_trust_root") == str(plan["protected_trust_root"])
             and allocation.get("authority_status") == "candidate_allocation_only",
             "exclusive Generation record does not bind this exact build plan")
    parent = allocation.get("parent", {}).get("canonical_path", "")
    _require(os.path.join(parent, str(plan["generation_id"])) == str(plan["generation_root"]),
             "Generation ID/path differ from allocation record")
    output = plan["inventory_output"]
    _require(not _paths_overlap(plan["generation_root"], plan["protected_trust_root"]),
             "Generation Root overlaps protected Trust root")
    for protected in (plan["protected_trust_root"], plan["source_checkout"], plan["generation_root"],
                      plan["wheelhouse_root"], plan["requirements_lock"], plan["wheelhouse_manifest"]):
        _require(not output.is_relative_to(protected) and not protected.is_relative_to(output),
                 f"Inventory output overlaps protected/input path: {protected}")
    _require(plan["python_executable"].is_relative_to(plan["runtime_root"])
             and plan["site_packages_root"].is_relative_to(plan["runtime_root"]),
             "runtime path escapes the pinned Runtime Root")
    _require(plan["target_platform"] == f"linux-{platform.machine().lower()}",
             "target platform differs from verifier host")
    return plan, actual


def _git(plan: dict[str, Any], args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(plan["source_checkout"]), "-c", "core.fsmonitor=false",
             "-c", "core.hooksPath=/dev/null", *args],
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
            check=True, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerifyError(f"source verification failed: {exc}") from exc
    return result.stdout


def _verify_source(plan: dict[str, Any]) -> dict[str, str]:
    _ordinary(plan["source_checkout"], directory=True)
    head = _git(plan, ["rev-parse", "--verify", "HEAD^{commit}"]).strip()
    _require(head == plan["source_commit"], "source checkout HEAD differs from exact Owner pin")
    _require(_git(plan, ["status", "--porcelain=v1", "--untracked-files=all"]) == "",
             "trusted source checkout is dirty")
    source_prefix = "教案生成器/lesson-plan-docx-generator/"
    expected: dict[str, str] = {}
    for tree in ("scripts", "schemas"):
        raw = _git(plan, ["ls-tree", "-r", "-z", "--full-tree", plan["source_commit"],
                          "--", source_prefix + tree]).encode("utf-8", errors="surrogateescape")
        for row in raw.split(b"\x00"):
            if not row:
                continue
            metadata, raw_path = row.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split(" ")
            rel_repo_path = raw_path.decode("utf-8")
            _require(mode in {"100644", "100755"} and kind == "blob",
                     f"pinned source tree contains non-regular path: {rel_repo_path}")
            relative = rel_repo_path[len(source_prefix + tree + "/"):]
            expected[f"{tree}/{relative}"] = object_id
    _require(expected, "source commit has no Controller source files")
    actual: set[str] = set()
    for tree, root in (("scripts", plan["scripts_root"]), ("schemas", plan["schemas_root"])):
        _ordinary(root, directory=True)
        for current, directories, files in os.walk(root, topdown=True, followlinks=False):
            base = Path(current)
            directories[:] = sorted(directories)
            for name in directories:
                child = base / name
                info = child.lstat()
                _require(stat.S_ISDIR(info.st_mode) and info.st_mode & 0o022 == 0,
                         f"Controller directory is unsafe: {child}")
            for name in sorted(files):
                path = base / name
                info = path.lstat()
                _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_mode & 0o022 == 0,
                         f"Controller file is unsafe: {path}")
                _require(path.suffix.casefold() not in {".pyc", ".pyo"}
                         and "__pycache__" not in path.parts,
                         f"Controller bytecode is refused: {path}")
                actual.add(f"{tree}/{path.relative_to(root).as_posix()}")
    _require(actual == set(expected), "installed Controller tree set differs from exact source commit")
    for relative, object_id in expected.items():
        tree = relative.split("/", 1)[0]
        root = plan["scripts_root"] if tree == "scripts" else plan["schemas_root"]
        path = root / relative.split("/", 1)[1]
        try:
            content = subprocess.run(
                ["/usr/bin/git", "-C", str(plan["source_checkout"]), "-c", "core.fsmonitor=false",
                 "-c", "core.hooksPath=/dev/null", "cat-file", "blob", object_id],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                     "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
                check=True, capture_output=True, timeout=30,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise VerifyError(f"cannot read pinned source blob: {exc}") from exc
        _require(path.read_bytes() == content, f"installed file does not match source commit: {relative}")
    return expected


def _python_version(executable: Path) -> str:
    _ordinary(executable, directory=False)
    _require(os.access(executable, os.X_OK), "pinned Python executable is not executable")
    try:
        result = subprocess.run([str(executable), "-I", "-S", "-B", "-c",
                                 "import sys;print(sys.version.split()[0])"],
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                check=True, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VerifyError(f"pinned Python did not execute in isolated mode: {exc}") from exc
    return result.stdout.strip()


def _expected_modules(scripts_root: Path) -> set[str]:
    names: set[str] = set()
    for path in scripts_root.rglob("*.py"):
        parts = list(path.relative_to(scripts_root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        _require(parts and all(part.isidentifier() for part in parts), f"non-importable module path: {path}")
        names.add(".".join(parts))
    return names


def _site_component_sets(root: Path) -> tuple[set[str], set[str]]:
    packages: set[str] = set()
    modules: set[str] = set()
    for path in root.iterdir():
        info = path.lstat()
        _require(not stat.S_ISLNK(info.st_mode)
                 and (stat.S_ISDIR(info.st_mode) or info.st_nlink == 1),
                 f"site-packages top-level alias: {path}")
        if stat.S_ISDIR(info.st_mode):
            if path.name.endswith((".dist-info", ".egg-info", ".data")) or path.name == "__pycache__":
                continue
            if any(child.is_file() and child.suffix in {".py", ".pyi", ".so", ".pyd", ".dll"}
                   for child in path.rglob("*")):
                packages.add(path.name)
        elif stat.S_ISREG(info.st_mode) and path.suffix == ".py":
            modules.add(path.stem)
    return packages, modules


def _verify_locked_inputs_and_installed_distributions(plan: dict[str, Any]) -> None:
    lock_path = plan["requirements_lock"]
    _ordinary(lock_path, directory=False)
    lock_raw = lock_path.read_bytes()
    _require(hashlib.sha256(lock_raw).hexdigest() == plan["requirements_lock_sha256"],
             "requirements lock raw SHA mismatch")
    try:
        lock_text = lock_raw.decode("utf-8")
    except UnicodeError as exc:
        raise VerifyError("requirements lock is not UTF-8") from exc
    expected: dict[str, tuple[str, set[str]]] = {}
    for number, raw_line in enumerate(lock_text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK.fullmatch(line)
        _require(match is not None, f"requirements line {number} is not exact/hash-locked")
        name, version = match.group(1), match.group(2)
        key = re.sub(r"[-_.]+", "-", name).lower()
        hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", line))
        _require(key not in expected, f"duplicate requirement: {key}")
        expected[key] = (version, hashes)
    _require(bool(expected), "requirements lock is empty")

    manifest_path = plan["wheelhouse_manifest"]
    _ordinary(manifest_path, directory=False)
    manifest_raw = manifest_path.read_bytes()
    _require(hashlib.sha256(manifest_raw).hexdigest() == plan["wheelhouse_manifest_sha256"],
             "wheelhouse manifest raw SHA mismatch")
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"invalid wheelhouse manifest: {exc}") from exc
    _require(isinstance(manifest, dict) and set(manifest) == {"schema_version", "files"}
             and manifest["schema_version"] == "rq03f-wheelhouse-manifest-1.0"
             and isinstance(manifest["files"], list), "invalid wheelhouse manifest shape")
    wheelhouse = plan["wheelhouse_root"]
    _ordinary(wheelhouse, directory=True)
    rows: dict[str, str] = {}
    for row in manifest["files"]:
        _require(isinstance(row, dict) and set(row) == {"name", "sha256"},
                 "invalid wheel manifest row")
        name, digest = row["name"], row["sha256"]
        _require(isinstance(name, str) and name.endswith(".whl") and "/" not in name
                 and "\\" not in name and name not in rows and _SHA.fullmatch(str(digest)) is not None,
                 "unsafe/duplicate wheel manifest row")
        rows[name] = digest
    actual_wheels = set()
    projects = set()
    for path in wheelhouse.iterdir():
        info = path.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                 f"wheelhouse special/hard-linked file: {path}")
        _require(path.name.endswith(".whl") and path.name in rows,
                 f"unmanifested wheelhouse entry: {path.name}")
        digest = _file_sha(path)
        _require(digest == rows[path.name], f"wheelhouse file SHA mismatch: {path.name}")
        parts = path.name[:-4].split("-")
        _require(len(parts) >= 5, f"invalid wheel name: {path.name}")
        project = re.sub(r"[-_.]+", "-", parts[0]).lower()
        _require(project in expected and expected[project][0] == parts[1]
                 and digest in expected[project][1], f"wheel not pinned by locked requirements: {path.name}")
        projects.add(project)
        actual_wheels.add(path.name)
    _require(actual_wheels == set(rows) and projects == set(expected),
             "wheelhouse files do not exactly satisfy the complete locked requirement set")

    installed: dict[str, str] = {}
    site = plan["site_packages_root"]
    for metadata in sorted(site.glob("*.dist-info/METADATA")):
        _ordinary(metadata, directory=False)
        parsed = email.parser.Parser().parsestr(metadata.read_text(encoding="utf-8"))
        name, version = parsed.get("Name"), parsed.get("Version")
        _require(name and version, f"invalid installed dist-info metadata: {metadata}")
        key = re.sub(r"[-_.]+", "-", name).lower()
        _require(key not in installed, f"duplicate installed distribution: {key}")
        installed[key] = version
    _require(installed == {name: version for name, (version, _hashes) in expected.items()},
             "installed runtime distributions do not exactly match the locked requirements")


def verify_candidate(inventory_path: Path, expected_inventory_sha256: str,
                     plan_path: Path, expected_plan_sha256: str) -> dict[str, Any]:
    _require(sys.platform.startswith("linux"), "independent verifier is Linux-only")
    plan, plan_sha256 = _read_plan(plan_path, expected_plan_sha256)
    _ordinary(inventory_path, directory=False)
    plan_raw = inventory_path.read_bytes()
    actual_sha = hashlib.sha256(plan_raw).hexdigest()
    _require(_SHA.fullmatch(expected_inventory_sha256 or "") is not None
             and actual_sha == expected_inventory_sha256,
             "candidate Inventory raw SHA differs from the independent pin")
    try:
        inventory = json.loads(plan_raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerifyError(f"invalid Inventory JSON: {exc}") from exc
    _require(isinstance(inventory, dict)
             and set(inventory) == {"build_inventory_version", "controller_id", "controller_root",
                                    "python_runtime", "components"},
             "Inventory 1.1 has missing or unknown top-level fields")
    canonical = (json.dumps(inventory, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                            allow_nan=False) + "\n").encode("utf-8")
    _require(canonical == plan_raw, "Inventory bytes are not in deterministic canonical form")
    _require(inventory["build_inventory_version"] == "1.1"
             and inventory["controller_id"] == plan["controller_id"]
             and inventory["controller_root"] == str(plan["controller_root"]),
             "Inventory version/controller/path differs from the independent build plan")
    _verify_source(plan)

    runtime = inventory["python_runtime"]
    _require(isinstance(runtime, dict)
             and set(runtime) == {"python_executable", "python_executable_sha256", "python_version",
                                  "site_packages_root", "site_packages_sha256"},
             "Inventory Python runtime has missing or unknown fields")
    _require(runtime["python_executable"] == str(plan["python_executable"])
             and runtime["site_packages_root"] == str(plan["site_packages_root"]),
             "Inventory Python executable/site-packages path differs from independent pin")
    _require(_SHA.fullmatch(str(runtime["python_executable_sha256"])) is not None
             and runtime["python_executable_sha256"] == _file_sha(plan["python_executable"]),
             "Python executable SHA mismatch")
    _require(runtime["python_version"] == plan["python_version"]
             and runtime["python_version"] == _python_version(plan["python_executable"]),
             "Python executable/version differs from the pinned patch release")
    _require(_ordinary(plan["site_packages_root"], directory=True).st_mode & 0o022 == 0,
             "site-packages root is group/world writable")
    _require(runtime["site_packages_sha256"] == _runtime_sha(plan["site_packages_root"]),
             "site-packages tree SHA mismatch")

    expected_component_fields = {"component_id", "component_type", "runtime_path", "sha256"}
    components = inventory["components"]
    _require(isinstance(components, list) and components, "Inventory components must be a nonempty array")
    by_id: dict[str, dict[str, Any]] = {}
    inventory_keys: set[str] = set()
    for row in components:
        _require(isinstance(row, dict) and expected_component_fields <= set(row)
                 and set(row) <= expected_component_fields | {"inventory_key"},
                 "Inventory component row has missing or unknown fields")
        component_id = row["component_id"]
        _require(isinstance(component_id, str) and component_id not in by_id,
                 "duplicate/invalid Inventory component ID")
        _require(row["component_type"] in _KINDS and _SHA.fullmatch(str(row["sha256"])) is not None,
                 f"invalid component type or SHA: {component_id}")
        path = _path(row["runtime_path"], f"component path {component_id}")
        kind = row["component_type"]
        if kind in {"python_module", "json_schema"}:
            expected_parent = plan["scripts_root"] if kind == "python_module" else plan["schemas_root"]
            _require(path.is_relative_to(expected_parent), f"component escapes Controller tree: {component_id}")
            _require(isinstance(row.get("inventory_key"), str) and row["inventory_key"] != "",
                     f"missing Inventory key: {component_id}")
            _require(row["inventory_key"] not in inventory_keys,
                     f"duplicate Inventory key: {row['inventory_key']}")
            inventory_keys.add(row["inventory_key"])
            actual = _file_sha(path)
        elif kind == "python_package":
            _require(path == plan["site_packages_root"] / component_id,
                     f"Python package path does not match package ID: {component_id}")
            actual = _tree_sha(path, bytecode=True)
        elif kind == "python_dependency_module":
            _require(path == plan["site_packages_root"] / f"{component_id}.py",
                     f"dependency module path does not match module ID: {component_id}")
            actual = _file_sha(path)
        else:
            expected = {"controller_scripts_tree": plan["scripts_root"],
                        "controller_schemas_tree": plan["schemas_root"]}.get(component_id)
            _require(expected is not None and path == expected,
                     f"unexpected/incorrect Controller tree component: {component_id}")
            actual = _tree_sha(path)
        _require(actual == row["sha256"], f"component SHA mismatch: {component_id}")
        by_id[component_id] = row

    module_ids = {row["component_id"] for row in components if row["component_type"] == "python_module"}
    schema_ids = {row["component_id"] for row in components if row["component_type"] == "json_schema"}
    package_ids = {row["component_id"] for row in components if row["component_type"] == "python_package"}
    dependency_ids = {row["component_id"] for row in components
                      if row["component_type"] == "python_dependency_module"}
    _require(module_ids == _expected_modules(plan["scripts_root"]),
             "Inventory omits or invents Controller Python modules")
    expected_schema_ids = {p.name for p in plan["schemas_root"].rglob("*.schema.json")}
    _require(expected_schema_ids <= schema_ids, "Inventory omits Controller schemas")
    packages, dependency_modules = _site_component_sets(plan["site_packages_root"])
    _require(package_ids == packages and dependency_ids == dependency_modules,
             "Inventory omits or invents site-packages component paths")
    _require(REQUIRED_MODULES <= module_ids and REQUIRED_SCHEMAS <= schema_ids
             and REQUIRED_PACKAGES <= package_ids and REQUIRED_DEPENDENCY_MODULES <= dependency_ids,
             "Inventory lacks a required Controller module/schema/dependency")
    _require({"controller_scripts_tree", "controller_schemas_tree"} <= {
        row["component_id"] for row in components if row["component_type"] == "controller_tree"
    }, "Inventory lacks complete Controller tree components")

    _verify_locked_inputs_and_installed_distributions(plan)
    expected_out = plan["inventory_output"]
    _require(inventory_path == expected_out, "Inventory output path differs from the build plan")
    return {"verification_status": "PASS", "authority_status": "candidate_only_not_owner_approved",
            "inventory_sha256": actual_sha, "build_plan_sha256": plan_sha256,
            "components_verified": len(components), "source_commit": plan["source_commit"],
            "controller_root": str(plan["controller_root"]), "runtime_root": str(plan["runtime_root"])}


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--expected-inventory-sha256", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--adopt", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.adopt:
        raise VerifyError("Inventory verifier cannot adopt or write protected trust material")
    result = verify_candidate(args.inventory, args.expected_inventory_sha256,
                              args.plan, args.expected_plan_sha256)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except VerifyError as exc:
        print(f"BLOCKED — {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
