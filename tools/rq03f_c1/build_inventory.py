#!/usr/bin/env python3
"""Create a candidate Profile/Index-compatible Controller Build Inventory 1.1.

This tool only inventories an already-installed, final-path runtime. It does not
adopt an Inventory, write a Trust Anchor, create authority, or make an OS/runtime
trust claim. The independently delivered plan digest is a caller pin; the future
fixed Operator launcher and Owner approval remain outside this package.
"""

from __future__ import annotations

import argparse
import csv
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


class BuildError(ValueError):
    """Candidate build inputs or installed bytes are incomplete or unsafe."""


_PLAN_KEYS = {
    "schema_version", "purpose", "source_commit", "source_checkout", "target_platform",
    "operator_uid", "operator_gid",
    "controller_id", "inventory_key", "generation_id", "generation_root",
    "allocation_plan_sha256", "allocation_record_path", "allocation_record_sha256",
    "controller_root", "protected_trust_root",
    "scripts_root", "schemas_root",
    "runtime_root", "build_python_executable", "python_executable", "python_version", "site_packages_root",
    "requirements_lock", "requirements_lock_sha256", "wheelhouse_root",
    "wheelhouse_manifest", "wheelhouse_manifest_sha256", "inventory_output",
}
_LOCK_LINE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9._+!]*)(?:\s+--hash=sha256:([0-9a-f]{64}))+\s*$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_:-]{0,159}$")
_ALLOCATION_INCOMPLETE = ".rq03f-incomplete.json"
_ALLOCATION_FINALIZED = ".rq03f-allocation-finalized.json"


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)

REQUIRED_MODULES = frozenset({
    "operator_controller_bootstrap", "semantic_scope_records", "semantic_scope_review",
    "operation_provenance", "reviewer_qualification", "qualification_corpus_intake",
    "lifecycle_digest", "source_truth", "exemplar_contract", "exemplar_split", "path_safety",
})
REQUIRED_SCHEMAS = frozenset({
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
})
REQUIRED_PACKAGES = frozenset({
    "attr", "attrs", "jsonschema", "jsonschema_specifications", "referencing", "rpds",
})
REQUIRED_DEPENDENCY_MODULES = frozenset({"typing_extensions"})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _absolute(raw: Any, label: str) -> Path:
    _require(isinstance(raw, str) and raw != "", f"{label} is unset or empty")
    _require(raw.startswith("/") and "\x00" not in raw and "\\" not in raw,
             f"{label} must be a canonical absolute Linux path")
    _require(os.path.normpath(raw) == raw and "//" not in raw,
             f"{label} contains a path alias")
    _require(all(part not in {".", ".."} for part in raw.split("/")),
             f"{label} contains dot traversal")
    return Path(raw)


def _safe_path(path: Path, *, directory: bool | None = None, require_readonly: bool = False) -> os.stat_result:
    _require(path.is_absolute() and os.path.normpath(str(path)) == str(path),
             f"path is not canonical and absolute: {path}")
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as exc:
            raise BuildError(f"missing path component: {cursor}: {exc}") from exc
        _require(not stat.S_ISLNK(info.st_mode), f"symlink path component refused: {cursor}")
    info = path.lstat()
    if directory is True:
        _require(stat.S_ISDIR(info.st_mode), f"expected directory: {path}")
    elif directory is False:
        _require(stat.S_ISREG(info.st_mode), f"expected regular file: {path}")
    if not stat.S_ISDIR(info.st_mode):
        _require(info.st_nlink == 1, f"hard-linked file refused: {path}")
    if require_readonly:
        _require(info.st_mode & 0o022 == 0, f"group/world-writable installed path: {path}")
    try:
        canonical = str(path.resolve(strict=True))
    except OSError as exc:
        raise BuildError(f"cannot resolve path: {path}: {exc}") from exc
    _require(canonical == str(path), f"path resolves through an alias: {path}")
    return info


def _open_secure_directory(path: Path, uid: int, gid: int) -> int:
    """Open each component without following symlinks or writable/ACL parents."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            info = os.fstat(fd)
            _require(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, uid}
                     and info.st_mode & 0o022 == 0,
                     f"untrusted or writable directory in pinned path: {path}")
            if info.st_uid == uid:
                _require(info.st_gid == gid, f"unexpected Operator group in pinned path: {path}")
            try:
                xattrs = os.listxattr(fd)
            except OSError as exc:
                raise BuildError(f"cannot inspect path ACL metadata: {exc}") from exc
            _require(not ({"system.posix_acl_access", "system.posix_acl_default"} & set(xattrs)),
                     f"POSIX ACL in pinned path: {path}")
        _require(os.readlink(f"/proc/self/fd/{fd}") == str(path),
                 f"directory fd does not match canonical path: {path}")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_pinned_file(path: Path, *, uid: int, gid: int, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    parent_fd = _open_secure_directory(path.parent, uid, gid)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                     and before.st_uid in {0, uid} and before.st_mode & 0o022 == 0
                     and before.st_size <= max_bytes,
                     f"Owner-pinned input file identity/mode is unsafe: {path}")
            if before.st_uid == uid:
                _require(before.st_gid == gid, f"Owner-pinned input has unexpected group: {path}")
            data = bytearray()
            while len(data) <= max_bytes:
                block = os.read(fd, min(1024 * 1024, max_bytes + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
            after = os.fstat(fd)
            _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                     f"Owner-pinned input changed during read: {path}")
            _require(len(data) <= max_bytes, f"Owner-pinned input too large: {path}")
            return bytes(data)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _sha256_pinned_file(path: Path, *, uid: int, gid: int) -> str:
    parent_fd = _open_secure_directory(path.parent, uid, gid)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                     and before.st_uid in {0, uid} and before.st_mode & 0o022 == 0,
                     f"Owner-pinned file identity/mode is unsafe: {path}")
            if before.st_uid == uid:
                _require(before.st_gid == gid, f"Owner-pinned file has unexpected group: {path}")
            digest = hashlib.sha256()
            while True:
                block = os.read(fd, 1024 * 1024)
                if not block:
                    break
                digest.update(block)
            after = os.fstat(fd)
            _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                     f"Owner-pinned file changed during hashing: {path}")
            return digest.hexdigest()
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def _sha256_file(path: Path) -> str:
    _safe_path(path, directory=False)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(root: Path, *, include_bytecode_cache: bool = False) -> str:
    _safe_path(root, directory=True)
    rows: list[tuple[str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            info = child.lstat()
            _require(stat.S_ISDIR(info.st_mode), f"symlink/special directory refused: {child}")
            if include_bytecode_cache or name != "__pycache__":
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = current_path / name
            if (not include_bytecode_cache and path.suffix.casefold() in {".pyc", ".pyo"}
                    and "__pycache__" in path.parts):
                continue
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode), f"symlink/special file refused: {path}")
            relative = path.relative_to(root).as_posix()
            rows.append((relative, _sha256_file(path)))
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_runtime_tree(root: Path) -> str:
    """Reproduce Build Inventory 1.1's runtime site-packages digest semantics."""
    _safe_path(root, directory=True)
    rows: list[tuple[str, str, str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            path = current_path / name
            info = path.lstat()
            _require(stat.S_ISDIR(info.st_mode), f"runtime symlink/special directory refused: {path}")
            retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = current_path / name
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode), f"runtime symlink/special file refused: {path}")
            rows.append((path.relative_to(root).as_posix(), "file", "", _sha256_file(path)))
    rows.sort(key=lambda item: item[0])
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                        allow_nan=False) + "\n").encode("utf-8")


def _require_finalized_allocation(generation_root: Path, *, plan_sha256: str,
                                  record_sha256: str, generation_id: str,
                                  allocation_record: dict[str, Any], uid: int, gid: int) -> None:
    """Require one finalization receipt and no failure marker for this record."""
    incomplete_path = generation_root / _ALLOCATION_INCOMPLETE
    try:
        incomplete_path.lstat()
    except FileNotFoundError:
        pass
    else:
        raise BuildError("Generation allocation has an incomplete/failure marker")

    target = allocation_record.get("target")
    _require(isinstance(target, dict)
             and set(target) == {"device", "inode", "uid", "gid", "mode"}
             and type(target.get("device")) is int and target["device"] >= 0
             and type(target.get("inode")) is int and target["inode"] > 0
             and type(target.get("uid")) is int and target["uid"] == uid
             and type(target.get("gid")) is int and target["gid"] == gid
             and target.get("mode") == "0700",
             "Generation allocation target identity is incomplete or invalid")
    finalization_path = generation_root / _ALLOCATION_FINALIZED
    try:
        raw = _read_pinned_file(finalization_path, uid=uid, gid=gid, max_bytes=16 * 1024)
    except FileNotFoundError as exc:
        raise BuildError("Generation allocation is unfinalized: finalization receipt is absent") from exc
    try:
        finalization = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid Generation allocation finalization receipt: {exc}") from exc
    expected = {
        "record_version": "rq03f-allocation-finalization-1.0",
        "finalization_status": "finalized",
        "target_id": generation_id,
        "owner_plan_sha256": plan_sha256,
        "allocation_record_sha256": record_sha256,
        "target": target,
    }
    _require(isinstance(finalization, dict) and finalization == expected
             and raw == _canonical_json(finalization),
             "Generation allocation is unfinalized or its finalization receipt conflicts")
    try:
        incomplete_path.lstat()
    except FileNotFoundError:
        return
    raise BuildError("Generation allocation acquired an incomplete/failure marker during validation")


def _git(plan: dict[str, Any], args: list[str], *, timeout: int = 30) -> str:
    source = str(plan["source_checkout"])
    git = Path("/usr/bin/git")
    _require(git.is_file() and not git.is_symlink(), "fixed system Git executable is unavailable")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0",
           "GIT_TERMINAL_PROMPT": "0"}
    cmd = [str(git), "-C", source, "-c", "core.fsmonitor=false", "-c",
           "core.hooksPath=/dev/null", *args]
    try:
        return subprocess.run(cmd, env=env, check=True, capture_output=True, text=True,
                              timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError(f"cannot verify trusted source checkout: {exc}") from exc


def _load_plan(path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    _require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") is not None,
             "independent Owner plan SHA-256 is required")
    _require(os.geteuid() != 0, "build tools must run as a non-root deployment identity")
    plan_path = _absolute(str(path), "plan path")
    raw = _read_pinned_file(plan_path, uid=os.geteuid(), gid=os.getegid(), max_bytes=512 * 1024)
    actual = hashlib.sha256(raw).hexdigest()
    _require(actual == expected_sha256, "build input plan differs from independent SHA pin")
    try:
        plan = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid build input plan: {exc}") from exc
    _require(isinstance(plan, dict) and set(plan) == _PLAN_KEYS,
             "build input plan has missing or unknown fields")
    _require(plan["schema_version"] == "rq03f-build-inputs-1.0",
             "unsupported build input plan version")
    _require(plan["purpose"] == "candidate_inventory_only",
             "build tool refuses any purpose other than candidate inventory generation")
    _require(os.geteuid() != 0 and type(plan["operator_uid"]) is int and plan["operator_uid"] > 0
             and type(plan["operator_gid"]) is int and plan["operator_gid"] > 0,
             "build must run as an explicitly pinned non-root deployment identity")
    _require(os.getuid() == os.geteuid() == plan["operator_uid"]
             and os.getgid() == os.getegid() == plan["operator_gid"]
             and set(os.getgroups()) <= {plan["operator_gid"]},
             "build process UID/GID/supplementary groups differ from Owner build plan")
    _require(_COMMIT.fullmatch(str(plan["source_commit"])) is not None,
             "invalid Owner-approved source commit")
    _require(_SHA256.fullmatch(str(plan["requirements_lock_sha256"])) is not None,
             "invalid locked requirements SHA-256")
    _require(_SHA256.fullmatch(str(plan["wheelhouse_manifest_sha256"])) is not None,
             "invalid wheelhouse manifest SHA-256")
    _require(_SHA256.fullmatch(str(plan["allocation_plan_sha256"])) is not None
             and _SHA256.fullmatch(str(plan["allocation_record_sha256"])) is not None,
             "exclusive Generation allocation plan/record SHA pins are required")
    _require(isinstance(plan["controller_id"], str) and plan["controller_id"].strip() != "",
             "controller ID is required")
    _require(_KEY.fullmatch(str(plan["inventory_key"])) is not None,
             "invalid Build Inventory key")
    generation_id = plan["generation_id"]
    _require(isinstance(generation_id, str)
             and re.fullmatch(r"rq03f-(?:[a-z0-9]|[a-z0-9][a-z0-9-]{0,54}[a-z0-9])", generation_id),
             "invalid exclusively allocated Generation ID")
    for field in ("source_checkout", "generation_root", "allocation_record_path", "controller_root",
                  "protected_trust_root", "scripts_root", "schemas_root", "runtime_root",
                  "build_python_executable", "python_executable", "site_packages_root", "requirements_lock", "wheelhouse_root",
                  "wheelhouse_manifest", "inventory_output"):
        plan[field] = _absolute(plan[field], field)
    _require(plan["allocation_record_path"] == plan["generation_root"] / ".rq03f-allocation-record.json",
             "allocation record path does not match the Generation root")
    _require(plan["controller_root"] == plan["generation_root"] / "controller"
             and plan["runtime_root"] == plan["generation_root"] / "runtime",
             "final Controller/Runtime paths are not the fixed allocated Generation children")
    record_path = plan["allocation_record_path"]
    record_raw = _read_pinned_file(record_path, uid=plan["operator_uid"], gid=plan["operator_gid"])
    _require(hashlib.sha256(record_raw).hexdigest() == plan["allocation_record_sha256"],
             "Generation allocation record SHA differs from Owner plan")
    try:
        allocation_record = json.loads(record_raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid Generation allocation record: {exc}") from exc
    _require(isinstance(allocation_record, dict), "Generation allocation record must be an object")
    _require_finalized_allocation(
        plan["generation_root"], plan_sha256=plan["allocation_plan_sha256"],
        record_sha256=plan["allocation_record_sha256"], generation_id=generation_id,
        allocation_record=allocation_record, uid=plan["operator_uid"], gid=plan["operator_gid"],
    )
    _require(isinstance(allocation_record, dict)
             and allocation_record.get("record_version") == "rq03f-allocation-record-1.0"
             and allocation_record.get("allocation_status") == "complete"
             and allocation_record.get("operation_kind") == "generation"
             and allocation_record.get("operation_scope") == "qualification_controller_generation"
             and allocation_record.get("target_id") == generation_id
             and allocation_record.get("source_commit") == plan["source_commit"]
             and allocation_record.get("owner_plan_sha256") == plan["allocation_plan_sha256"]
             and allocation_record.get("protected_trust_root") == str(plan["protected_trust_root"])
             and allocation_record.get("authority_status") == "candidate_allocation_only",
             "Generation allocation evidence is incomplete or does not bind the build plan")
    _require(os.path.join(allocation_record.get("parent", {}).get("canonical_path", ""), generation_id)
             == str(plan["generation_root"]), "allocation record target path differs from Build plan")
    _require(plan["scripts_root"] == plan["controller_root"] / "scripts",
             "Scripts root does not equal the pinned Controller Root child")
    _require(plan["schemas_root"] == plan["controller_root"] / "schemas",
             "Schemas root does not equal the pinned Controller Root child")
    _require(plan["python_executable"].is_relative_to(plan["runtime_root"])
             and plan["site_packages_root"].is_relative_to(plan["runtime_root"]),
             "Python executable/site-packages must remain beneath the pinned Runtime Root")
    _require(plan["build_python_executable"] != plan["python_executable"],
             "build interpreter and final Runtime executable must be distinct paths")
    _require(plan["controller_root"] != plan["runtime_root"]
             and not plan["controller_root"].is_relative_to(plan["runtime_root"])
             and not plan["runtime_root"].is_relative_to(plan["controller_root"]),
             "Controller and Runtime paths overlap")
    protected = plan["protected_trust_root"]
    output = plan["inventory_output"]
    _require(not _paths_overlap(plan["generation_root"], protected),
             "Generation root overlaps protected Trust root")
    for protected_path in (protected, plan["source_checkout"], plan["controller_root"], plan["runtime_root"],
                           plan["wheelhouse_root"], plan["requirements_lock"], plan["wheelhouse_manifest"]):
        _require(output != protected_path and not output.is_relative_to(protected_path),
                 f"candidate Inventory output overlaps protected/input path: {protected_path}")
        _require(not protected_path.is_relative_to(output),
                 f"candidate Inventory output is an ancestor of protected/input path: {protected_path}")
    target_platform = plan["target_platform"]
    _require(target_platform == f"linux-{platform.machine().lower()}",
             "target platform does not match this Linux build host")
    return plan, actual


def _requirements_and_wheelhouse(plan: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    lock_path = plan["requirements_lock"]
    raw_lock = _read_pinned_file(lock_path, uid=plan["operator_uid"], gid=plan["operator_gid"])
    _require(hashlib.sha256(raw_lock).hexdigest() == plan["requirements_lock_sha256"],
             "locked requirements raw SHA differs from Owner input pin")
    try:
        lock_text = raw_lock.decode("utf-8")
    except UnicodeError as exc:
        raise BuildError("locked requirements must be UTF-8") from exc
    locked = _parse_locked_requirements(lock_text)
    _require(bool(locked), "locked requirements file contains no pinned dependencies")
    wheelhouse = plan["wheelhouse_root"]
    wheelhouse_fd = _open_secure_directory(wheelhouse, plan["operator_uid"], plan["operator_gid"])
    try:
        wheelhouse_info = os.fstat(wheelhouse_fd)
        _require(wheelhouse_info.st_uid in {0, plan["operator_uid"]}
                 and wheelhouse_info.st_mode & 0o022 == 0,
                 "offline wheelhouse root owner/mode is unsafe")
    finally:
        os.close(wheelhouse_fd)
    manifest_path = plan["wheelhouse_manifest"]
    manifest_raw = _read_pinned_file(manifest_path, uid=plan["operator_uid"], gid=plan["operator_gid"])
    _require(hashlib.sha256(manifest_raw).hexdigest() == plan["wheelhouse_manifest_sha256"],
             "wheelhouse manifest raw SHA differs from Owner input pin")
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid wheelhouse manifest: {exc}") from exc
    _require(isinstance(manifest, dict) and set(manifest) == {"schema_version", "files"}
             and manifest["schema_version"] == "rq03f-wheelhouse-manifest-1.0"
             and isinstance(manifest["files"], list), "invalid closed wheelhouse manifest")
    entries: dict[str, str] = {}
    for row in manifest["files"]:
        _require(isinstance(row, dict) and set(row) == {"name", "sha256"},
                 "invalid wheelhouse file manifest row")
        name, digest = row["name"], row["sha256"]
        _require(isinstance(name, str) and name.endswith(".whl") and "/" not in name
                 and "\\" not in name and name not in {".", ".."}, "unsafe wheelhouse filename")
        _require(name not in entries and _SHA256.fullmatch(str(digest)) is not None,
                 "duplicate or invalid wheelhouse SHA entry")
        entries[name] = digest
    _require(entries, "empty wheelhouse is not a locked dependency source")
    actual_names = set()
    for entry in wheelhouse.iterdir():
        info = entry.lstat()
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                 f"wheelhouse symlink/hardlink/special entry refused: {entry.name}")
        _require(entry.suffix == ".whl", f"non-wheel input in offline wheelhouse: {entry.name}")
        actual_names.add(entry.name)
        _require(entry.name in entries and _sha256_pinned_file(
            entry, uid=plan["operator_uid"], gid=plan["operator_gid"]
        ) == entries[entry.name], f"wheelhouse file missing/mismatched: {entry.name}")
    _require(actual_names == set(entries), "wheelhouse manifest does not exactly cover directory entries")

    seen_projects: set[str] = set()
    for filename, digest in entries.items():
        parts = filename[:-4].split("-")
        _require(len(parts) >= 5, f"invalid wheel filename: {filename}")
        distribution, version = parts[0], parts[1]
        normalized = _normalize_project(distribution)
        _require(normalized in locked, f"wheel not named by exact requirements lock: {filename}")
        locked_version, hashes = locked[normalized]
        _require(version == locked_version and digest in hashes,
                 f"wheel version/hash is not pinned by requirements lock: {filename}")
        seen_projects.add(normalized)
    _require(seen_projects == set(locked), "wheelhouse is missing one or more locked projects")
    return lock_text, manifest["files"]


def _normalize_project(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_locked_requirements(lock_text: str) -> dict[str, tuple[str, set[str]]]:
    locked: dict[str, tuple[str, set[str]]] = {}
    for line_number, original in enumerate(lock_text.splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        _require(match is not None,
                 f"requirements lock line {line_number} is not an exact version plus SHA-256 hash set")
        name, version = match.group(1), match.group(2)
        hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", line))
        normalized = _normalize_project(name)
        _require(normalized not in locked, f"duplicate locked requirement: {name}")
        locked[normalized] = (version, hashes)
    return locked


def _verify_installed_distributions(plan: dict[str, Any], lock_text: str) -> None:
    expected = _parse_locked_requirements(lock_text)
    site = plan["site_packages_root"]
    actual: dict[str, str] = {}
    for metadata in sorted(site.glob("*.dist-info/METADATA")):
        _safe_path(metadata, directory=False, require_readonly=True)
        parsed = email.parser.Parser().parsestr(metadata.read_text(encoding="utf-8"))
        name, version = parsed.get("Name"), parsed.get("Version")
        _require(name and version, f"invalid installed distribution metadata: {metadata}")
        normalized = _normalize_project(name)
        _require(normalized not in actual, f"duplicate installed distribution metadata: {normalized}")
        actual[normalized] = version
    _require(actual == {name: version for name, (version, _hashes) in expected.items()},
             "installed site-packages distributions do not exactly match locked requirements")


def _verify_source_checkout(plan: dict[str, Any]) -> None:
    root = plan["source_checkout"]
    _safe_path(root, directory=True, require_readonly=True)
    head = _git(plan, ["rev-parse", "--verify", "HEAD^{commit}"]).strip()
    _require(head == plan["source_commit"], "source checkout HEAD differs from Owner-pinned commit")
    status = _git(plan, ["status", "--porcelain=v1", "--untracked-files=all"])
    _require(status == "", "trusted source checkout is not clean")


def _tracked_controller_files(plan: dict[str, Any]) -> dict[str, str]:
    prefix = "教案生成器/lesson-plan-docx-generator/"
    output: dict[str, str] = {}
    for tree in ("scripts", "schemas"):
        listing = _git(plan, ["ls-tree", "-r", "-z", "--full-tree", plan["source_commit"],
                              "--", prefix + tree])
        # Git NUL records contain mode/type/object/path separated by one tab.
        if listing:
            for row in listing.encode("utf-8", errors="surrogateescape").split(b"\x00"):
                if not row:
                    continue
                metadata, raw_path = row.split(b"\t", 1)
                mode, object_type, object_id = metadata.decode("ascii").split(" ")
                path = raw_path.decode("utf-8")
                _require(mode in {"100644", "100755"} and object_type == "blob",
                         f"controller source contains symlink or special Git entry: {path}")
                rel = path[len(prefix + tree + "/"):]
                _require(rel and not any(part in {".", "..", ""} for part in rel.split("/")),
                         f"invalid source path in pinned commit: {path}")
                output[f"{tree}/{rel}"] = object_id
    _require(output, "pinned source commit contains no controller files")
    return output


def _verify_installed_controller(plan: dict[str, Any]) -> None:
    _safe_path(plan["controller_root"], directory=True, require_readonly=True)
    _require({entry.name for entry in plan["controller_root"].iterdir()} == {"scripts", "schemas"},
             "Controller Root must contain exactly scripts/ and schemas/")
    source_files = _tracked_controller_files(plan)
    expected = set(source_files)
    actual: set[str] = set()
    for tree_name, root in (("scripts", plan["scripts_root"]), ("schemas", plan["schemas_root"])):
        _safe_path(root, directory=True, require_readonly=True)
        for current, directories, files in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            for name in sorted(directories):
                child = current_path / name
                info = child.lstat()
                _require(stat.S_ISDIR(info.st_mode) and info.st_mode & 0o022 == 0,
                         f"writable/symlinked Controller directory: {child}")
            for name in sorted(files):
                path = current_path / name
                info = path.lstat()
                _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_mode & 0o022 == 0,
                         f"writable/symlinked/hard-linked Controller file: {path}")
                _require(path.suffix.casefold() not in {".pyc", ".pyo"}
                         and "__pycache__" not in path.parts,
                         f"bytecode cache in Controller installation: {path}")
                actual.add(f"{tree_name}/{path.relative_to(root).as_posix()}")
    _require(actual == expected, "installed Controller file set differs from exact source commit")
    for rel, object_id in source_files.items():
        root = plan["scripts_root"] if rel.startswith("scripts/") else plan["schemas_root"]
        path = root / rel.split("/", 1)[1]
        expected_bytes = subprocess.run(
            ["/usr/bin/git", "-C", str(plan["source_checkout"]), "-c", "core.fsmonitor=false",
             "-c", "core.hooksPath=/dev/null", "cat-file", "blob", object_id],
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                 "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
            check=True, capture_output=True, timeout=30,
        ).stdout
        _require(path.read_bytes() == expected_bytes, f"installed Controller bytes differ from source: {rel}")


def _python_version(executable: Path) -> str:
    _safe_path(executable, directory=False, require_readonly=True)
    _require(os.access(executable, os.X_OK), "pinned Python executable is not executable")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONNOUSERSITE": "1"}
    try:
        version = subprocess.run([str(executable), "-I", "-S", "-B", "-c",
                                  "import sys; print(sys.version.split()[0])"],
                                 env=env, check=True, capture_output=True, text=True,
                                 timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError(f"cannot verify pinned Python executable: {exc}") from exc
    return version


def _component(component_id: str, component_type: str, path: Path,
               *, inventory_key: str | None = None, include_bytecode_cache: bool = False) -> dict[str, str]:
    _safe_path(path, directory=component_type in {"controller_tree", "python_package"},
               require_readonly=True)
    digest = (_sha256_tree(path, include_bytecode_cache=include_bytecode_cache)
              if component_type in {"controller_tree", "python_package"}
              else _sha256_file(path))
    row = {"component_id": component_id, "component_type": component_type,
           "runtime_path": str(path), "sha256": digest}
    if inventory_key is not None:
        row["inventory_key"] = inventory_key
    return row


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    _require(parts and all(part.isidentifier() for part in parts),
             f"Controller Python path is not importable: {path}")
    return ".".join(parts)


def build_candidate(plan_path: Path, expected_plan_sha256: str) -> dict[str, Any]:
    _require(sys.platform.startswith("linux"), "candidate Controller Inventory builder is Linux-only")
    plan, plan_sha256 = _load_plan(plan_path, expected_plan_sha256)
    _verify_source_checkout(plan)
    lock_text, _wheelhouse = _requirements_and_wheelhouse(plan)
    _verify_installed_controller(plan)

    controller_root = plan["controller_root"]
    runtime_root = plan["runtime_root"]
    _safe_path(controller_root, directory=True, require_readonly=True)
    _safe_path(runtime_root, directory=True, require_readonly=True)
    python_executable = plan["python_executable"]
    site_packages = plan["site_packages_root"]
    _safe_path(python_executable, directory=False, require_readonly=True)
    _safe_path(site_packages, directory=True, require_readonly=True)
    actual_version = _python_version(python_executable)
    _require(actual_version == plan["python_version"], "Python patch version differs from Owner pin")
    _require(site_packages.is_relative_to(runtime_root), "site-packages escaped Runtime Root")
    _require(python_executable.is_relative_to(runtime_root), "Python executable escaped Runtime Root")
    _verify_installed_distributions(plan, lock_text)
    allocation_raw = _read_pinned_file(
        plan["allocation_record_path"], uid=plan["operator_uid"], gid=plan["operator_gid"]
    )
    _require(hashlib.sha256(allocation_raw).hexdigest() == plan["allocation_record_sha256"],
             "Generation allocation record changed during build")
    allocation_record = json.loads(allocation_raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    _require_finalized_allocation(
        plan["generation_root"], plan_sha256=plan["allocation_plan_sha256"],
        record_sha256=plan["allocation_record_sha256"], generation_id=plan["generation_id"],
        allocation_record=allocation_record, uid=plan["operator_uid"], gid=plan["operator_gid"],
    )

    components: list[dict[str, str]] = [
        _component("controller_scripts_tree", "controller_tree", plan["scripts_root"]),
        _component("controller_schemas_tree", "controller_tree", plan["schemas_root"]),
    ]
    seen_modules: set[str] = set()
    for path in sorted(plan["scripts_root"].rglob("*.py")):
        _require("__pycache__" not in path.parts, "Controller installation has bytecode cache")
        name = _module_name(path, plan["scripts_root"])
        _require(name not in seen_modules, f"duplicate Controller module name: {name}")
        seen_modules.add(name)
        components.append(_component(name, "python_module", path,
                                     inventory_key=f"controller-module:{name}"))
    schema_names: set[str] = set()
    for path in sorted(plan["schemas_root"].rglob("*.schema.json")):
        name = path.name
        component_id = name if name not in schema_names else path.relative_to(plan["schemas_root"]).as_posix()
        schema_names.add(name)
        components.append(_component(component_id, "json_schema", path,
                                     inventory_key=f"controller-schema:{path.relative_to(plan['schemas_root']).as_posix()}"))
    _require(REQUIRED_MODULES <= seen_modules,
             f"required Controller modules are missing: {sorted(REQUIRED_MODULES - seen_modules)}")
    _require(REQUIRED_SCHEMAS <= schema_names,
             f"required schemas are missing: {sorted(REQUIRED_SCHEMAS - schema_names)}")

    # Pin each installed Python package root and direct dependency module path;
    # site_packages_sha256 below additionally binds every entry in the tree.
    package_names: set[str] = set()
    dependency_names: set[str] = set()
    for path in sorted(site_packages.iterdir()):
        info = path.lstat()
        _require(not stat.S_ISLNK(info.st_mode)
                 and (stat.S_ISDIR(info.st_mode) or info.st_nlink == 1),
                 f"runtime site-packages alias/hardlink refused: {path}")
        if stat.S_ISDIR(info.st_mode):
            if path.name.endswith((".dist-info", ".egg-info", ".data")) or path.name == "__pycache__":
                continue
            if any(child.is_file() and child.suffix in {".py", ".pyi", ".so", ".pyd", ".dll"}
                   for child in path.rglob("*")):
                package_names.add(path.name)
                components.append(_component(path.name, "python_package", path,
                                             include_bytecode_cache=True))
        elif stat.S_ISREG(info.st_mode) and path.suffix == ".py":
            dependency_names.add(path.stem)
            components.append(_component(path.stem, "python_dependency_module", path))
        else:
            _require(stat.S_ISREG(info.st_mode), f"special site-packages entry: {path}")
    _require(REQUIRED_PACKAGES <= package_names,
             f"required Python packages are missing: {sorted(REQUIRED_PACKAGES - package_names)}")
    _require(REQUIRED_DEPENDENCY_MODULES <= dependency_names,
             f"required dependency modules are missing: {sorted(REQUIRED_DEPENDENCY_MODULES - dependency_names)}")

    inventory = {
        "build_inventory_version": "1.1",
        "controller_id": plan["controller_id"],
        "controller_root": str(controller_root),
        "python_runtime": {
            "python_executable": str(python_executable),
            "python_executable_sha256": _sha256_file(python_executable),
            "python_version": actual_version,
            "site_packages_root": str(site_packages),
            "site_packages_sha256": _sha256_runtime_tree(site_packages),
        },
        "components": sorted(components, key=lambda row: (row["component_type"], row["component_id"])),
    }
    raw_inventory = _canonical_json(inventory)
    output = plan["inventory_output"]
    parent_fd = _open_secure_directory(output.parent, plan["operator_uid"], plan["operator_gid"])
    try:
        try:
            fd = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                         0o600, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise BuildError("candidate Inventory output already exists; never overwrite/reuse it") from exc
        view = memoryview(raw_inventory)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            _require(written > 0, "short write for candidate Inventory")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.fsync(parent_fd)
    except BaseException:
        try:
            if fd >= 0:
                os.close(fd)
        except (UnboundLocalError, OSError):
            pass
        raise
    finally:
        os.close(parent_fd)
    _require(hashlib.sha256(output.read_bytes()).hexdigest() == hashlib.sha256(raw_inventory).hexdigest(),
             "candidate Inventory changed during final read-back")
    receipt = {
        "receipt_version": "rq03f-build-candidate-receipt-1.0",
        "authority_status": "candidate_only_not_owner_approved",
        "source_commit": plan["source_commit"],
        "source_checkout": str(plan["source_checkout"]),
        "target_platform": plan["target_platform"],
        "controller_id": plan["controller_id"],
        "inventory_key_candidate": plan["inventory_key"],
        "generation_id": plan["generation_id"],
        "generation_allocation_record_sha256": plan["allocation_record_sha256"],
        "inventory_path": str(output),
        "inventory_sha256": hashlib.sha256(raw_inventory).hexdigest(),
        "build_plan_sha256": plan_sha256,
        "requirements_lock_sha256": plan["requirements_lock_sha256"],
        "wheelhouse_manifest_sha256": plan["wheelhouse_manifest_sha256"],
        "controller_root": str(controller_root),
        "runtime_root": str(runtime_root),
        "python_executable": str(python_executable),
        "site_packages_root": str(site_packages),
    }
    return {"inventory": inventory, "inventory_sha256": hashlib.sha256(raw_inventory).hexdigest(),
            "receipt": receipt, "receipt_sha256": hashlib.sha256(_canonical_json(receipt)).hexdigest()}


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--adopt", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.adopt:
        raise BuildError("Build Inventory adoption is Owner-only and is not implemented here")
    result = build_candidate(args.plan, args.expected_plan_sha256)
    print(json.dumps(result["receipt"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except BuildError as exc:
        print(f"BLOCKED — {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
