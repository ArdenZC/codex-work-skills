#!/usr/bin/env python3
"""Fail-closed Linux allocator for synthetic/future Owner-provisioned evidence paths.

The command is a filesystem primitive, not an authority provider.  A future fixed
Operator launcher must supply the independently delivered SHA-256 of the Owner
plan.  This module never treats an allocation record as a trust grant.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import subprocess
from typing import Any


class AllocationError(ValueError):
    """The requested allocation failed closed."""


_PLAN_KEYS = {
    "schema_version", "operation_kind", "operation_scope", "target_id",
    "trusted_parent", "protected_trust_root", "parent_device", "parent_inode", "parent_mount_id",
    "operator_uid", "operator_gid", "source_commit", "source_checkout", "archive_sources",
}
_ARCHIVE_SOURCE_NAMES = {"authority-profile.json", "operation-index.json"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TARGET = re.compile(r"^rq03f-(?:[a-z0-9]|[a-z0-9][a-z0-9-]{0,54}[a-z0-9])$")
_RECORD_NAME = ".rq03f-allocation-record.json"
_INCOMPLETE_NAME = ".rq03f-incomplete.json"
_FINALIZED_NAME = ".rq03f-allocation-finalized.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AllocationError(message)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_regular_nofollow(path: Path, *, max_bytes: int = 8 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
    _require(path.is_absolute(), "plan path must be absolute")
    _require(os.path.normpath(str(path)) == str(path), "plan path must be canonical")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        _require(stat.S_ISREG(before.st_mode), "plan/source is not a regular file")
        _require(before.st_nlink == 1, "hard-linked plan/source is refused")
        _require(before.st_size <= max_bytes, "plan/source exceeds size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                 == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                 "plan/source changed while being read")
        _require(len(raw) <= max_bytes, "plan/source exceeds size limit")
        return raw, before
    finally:
        os.close(fd)


def _acl_xattrs(fd: int) -> list[str]:
    try:
        names = os.listxattr(fd)
    except (AttributeError, OSError) as exc:
        raise AllocationError(f"cannot inspect filesystem ACL metadata: {exc}") from exc
    return sorted(name for name in names if name in {
        "system.posix_acl_access", "system.posix_acl_default",
    })


def _mount_id_for(path: str) -> int:
    """Return the most-specific Linux mount ID containing a canonical path."""
    matches: list[tuple[int, int]] = []
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="ascii").splitlines()
    except OSError as exc:
        raise AllocationError(f"cannot read Linux mount table: {exc}") from exc
    for line in lines:
        fields = line.split(" ")
        if len(fields) < 6:
            continue
        try:
            mount_id = int(fields[0])
        except ValueError:
            continue
        mountpoint = fields[4]
        for encoded, decoded in (("\\040", " "), ("\\011", "\t"),
                                 ("\\012", "\n"), ("\\134", "\\")):
            mountpoint = mountpoint.replace(encoded, decoded)
        if path == mountpoint or path.startswith(mountpoint.rstrip("/") + "/"):
            matches.append((len(mountpoint), mount_id))
    _require(bool(matches), "trusted parent has no identifiable Linux mount")
    return max(matches)[1]


def _canonical_absolute(raw: Any, label: str) -> str:
    _require(isinstance(raw, str) and raw != "", f"{label} is unset or empty")
    _require(raw.startswith("/"), f"{label} must be absolute")
    _require("\x00" not in raw and "\\" not in raw, f"{label} contains a forbidden path alias")
    _require(os.path.normpath(raw) == raw, f"{label} must be canonical")
    parts = raw.split("/")
    _require(all(part not in {".", ".."} for part in parts), f"{label} contains dot traversal")
    _require("//" not in raw, f"{label} contains an empty path component")
    return raw


def _open_directory_chain(path: str, operator_uid: int, operator_gid: int) -> tuple[int, list[tuple[str, os.stat_result]]]:
    """Open every path component with O_NOFOLLOW and validate it via its fd."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open("/", flags)
    observed: list[tuple[str, os.stat_result]] = [("/", os.fstat(fd))]
    try:
        for part in Path(path).parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            info = os.fstat(fd)
            _require(stat.S_ISDIR(info.st_mode), f"non-directory path component: {part}")
            _require(info.st_uid in {0, operator_uid}, f"untrusted owner in parent chain: {part}")
            _require(info.st_mode & 0o022 == 0, f"group/world-writable parent component: {part}")
            _require(not _acl_xattrs(fd), f"POSIX ACL is present on parent component: {part}")
            if info.st_uid == operator_uid:
                _require(info.st_gid == operator_gid, f"unexpected operator-owned parent GID: {part}")
            observed.append((part, info))
        return fd, observed
    except BaseException:
        os.close(fd)
        raise


def _verify_actor(plan: dict[str, Any]) -> None:
    operator_uid = plan.get("operator_uid")
    operator_gid = plan.get("operator_gid")
    _require(type(operator_uid) is int and operator_uid > 0, "invalid Operator UID")
    _require(type(operator_gid) is int and operator_gid > 0, "invalid Operator GID")
    _require(os.getuid() == os.geteuid() == operator_uid,
             "allocator must run with the exact non-root Owner-approved Operator UID")
    _require(os.getgid() == os.getegid() == operator_gid,
             "allocator must run with the exact Operator primary GID")
    groups = set(os.getgroups())
    _require(groups <= {operator_gid}, "supplementary groups are not permitted for the Operator")


def _validate_plan(raw: bytes) -> dict[str, Any]:
    try:
        plan = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AllocationError(f"invalid Owner allocation plan: {exc}") from exc
    _require(isinstance(plan, dict), "Owner allocation plan must be an object")
    _require(set(plan) == _PLAN_KEYS, "Owner allocation plan has missing or unknown fields")
    _require(plan["schema_version"] == "rq03f-exclusive-allocation-plan-1.0",
             "unsupported allocation plan version")
    kind = plan["operation_kind"]
    expected_scope = {
        "generation": "qualification_controller_generation",
        "legacy_archive": "legacy_profile_index_archive",
    }.get(kind)
    _require(expected_scope is not None and plan["operation_scope"] == expected_scope,
             "operation kind/scope mismatch or unauthorized scope")
    target_id = plan["target_id"]
    _require(isinstance(target_id, str) and _TARGET.fullmatch(target_id) is not None,
             "invalid or empty allocation ID")
    _require(target_id not in {".", ".."}, "dot allocation ID is refused")
    parent = _canonical_absolute(plan["trusted_parent"], "trusted parent")
    plan["trusted_parent"] = parent
    plan["protected_trust_root"] = _canonical_absolute(plan["protected_trust_root"], "protected Trust root")
    for field in ("parent_device", "parent_inode", "parent_mount_id"):
        value = plan[field]
        _require(type(value) is int and value > 0, f"invalid Owner-pinned {field}")
    commit = plan["source_commit"]
    _require(isinstance(commit, str) and _COMMIT.fullmatch(commit) is not None,
             "invalid Owner-approved source commit")
    plan["source_checkout"] = _canonical_absolute(plan["source_checkout"], "source checkout")
    if kind == "generation":
        _require(plan["archive_sources"] is None, "Generation plan cannot contain archive sources")
    else:
        sources = plan["archive_sources"]
        _require(isinstance(sources, list) and len(sources) == 2,
                 "archive must pin exactly the legacy Profile and Index bytes")
        names: set[str] = set()
        for source in sources:
            _require(isinstance(source, dict) and set(source) == {"name", "relative_path", "sha256"},
                     "archive source has missing or unknown fields")
            name = source["name"]
            _require(name in _ARCHIVE_SOURCE_NAMES and name not in names,
                     "archive source filename is not the pinned Profile/Index name")
            names.add(name)
            relative = source["relative_path"]
            _require(isinstance(relative, str) and relative != "" and not relative.startswith("/"),
                     "archive source path must be relative to the immutable Anchor checkout")
            _require("\\" not in relative and "\x00" not in relative, "invalid archive source path")
            parts = relative.split("/")
            _require(all(part not in {"", ".", ".."} for part in parts),
                     "archive source path contains an alias/traversal component")
            _require(isinstance(source["sha256"], str) and _SHA256.fullmatch(source["sha256"]) is not None,
                     "invalid archive source SHA-256")
        _require(names == _ARCHIVE_SOURCE_NAMES, "archive must include the exact Profile and Index names")
    return plan


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _read_plan(plan_path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    _require(isinstance(expected_sha256, str) and _SHA256.fullmatch(expected_sha256) is not None,
             "an independently delivered lowercase Owner plan SHA-256 is required")
    raw, info = _read_regular_nofollow(plan_path, max_bytes=256 * 1024)
    _require(info.st_uid in {0, os.geteuid()}, "allocation plan owner is not trusted")
    _require(info.st_mode & 0o022 == 0, "allocation plan is group/world writable")
    actual = hashlib.sha256(raw).hexdigest()
    _require(actual == expected_sha256, "Owner allocation plan does not match the external SHA pin")
    plan = _validate_plan(raw)
    _verify_actor(plan)
    parent_fd, _ = _open_directory_chain(
        str(plan_path.parent), plan["operator_uid"], plan["operator_gid"]
    )
    try:
        _require(os.readlink(f"/proc/self/fd/{parent_fd}") == str(plan_path.parent),
                 "allocation plan parent is not the canonical Owner path")
        plan_fd = os.open(plan_path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                          dir_fd=parent_fd)
        try:
            current = os.fstat(plan_fd)
            _require((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino),
                     "allocation plan was replaced while being validated")
            _require(current.st_uid in {0, plan["operator_uid"]} and current.st_mode & 0o022 == 0,
                     "allocation plan ownership or mode is unsafe")
        finally:
            os.close(plan_fd)
    finally:
        os.close(parent_fd)
    return plan, actual


def _secure_source(root_fd: int, relative_path: str, expected_sha256: str) -> bytes:
    parts = relative_path.split("/")
    current_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                              dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
            info = os.fstat(current_fd)
            _require(stat.S_ISDIR(info.st_mode), "archive source path has a non-directory component")
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=current_fd)
        try:
            before = os.fstat(leaf)
            _require(stat.S_ISREG(before.st_mode), "archive source is not a regular file")
            _require(before.st_nlink == 1, "hard-linked Anchor source is refused")
            _require(before.st_mode & 0o022 == 0, "archive source is group/world writable")
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            while True:
                chunk = os.read(leaf, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                digest.update(chunk)
            after = os.fstat(leaf)
            _require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                     == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                     "archive source changed while being read")
            _require(digest.hexdigest() == expected_sha256, "archive source SHA differs from Owner pin")
            return b"".join(chunks)
        finally:
            os.close(leaf)
    finally:
        os.close(current_fd)


def _verify_source_checkout(path: str, expected_commit: str, operator_uid: int, operator_gid: int) -> int:
    checkout_fd, _ = _open_directory_chain(path, operator_uid, operator_gid)
    try:
        _require(os.readlink(f"/proc/self/fd/{checkout_fd}") == path,
                 "source checkout fd does not match its canonical Owner path")
        git = Path("/usr/bin/git")
        _require(git.is_file() and not git.is_symlink(), "fixed system Git executable is unavailable")
        env = {
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        common = [str(git), "-C", path, "-c", "core.fsmonitor=false", "-c",
                  "core.hooksPath=/dev/null"]
        try:
            head = subprocess.run(common + ["rev-parse", "--verify", "HEAD^{commit}"],
                                  env=env, check=True, capture_output=True, text=True,
                                  timeout=10).stdout.strip()
            status = subprocess.run(common + ["status", "--porcelain=v1", "--untracked-files=all"],
                                    env=env, check=True, capture_output=True, text=True,
                                    timeout=20).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise AllocationError(f"cannot verify Owner-pinned source checkout: {exc}") from exc
        _require(head == expected_commit, "source checkout commit differs from Owner-pinned commit")
        _require(status == "", "Owner-pinned source checkout is not clean")
        return checkout_fd
    except BaseException:
        os.close(checkout_fd)
        raise


def _write_exclusive(directory_fd: int, name: str, payload: bytes, mode: int = 0o600) -> os.stat_result:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(name, flags, mode, dir_fd=directory_fd)
    try:
        view = memoryview(payload)
        offset = 0
        while offset < len(view):
            count = os.write(fd, view[offset:])
            _require(count > 0, f"short write for exclusive file {name}")
            offset += count
        os.fsync(fd)
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                 f"exclusive destination identity check failed: {name}")
        return info
    finally:
        os.close(fd)


def _fsync_directory(fd: int) -> None:
    os.fsync(fd)


def _mark_incomplete(target_fd: int, target_id: str, plan_sha256: str, error: BaseException) -> bool:
    marker = {
        "record_version": "rq03f-allocation-record-1.0",
        "allocation_status": "incomplete",
        "target_id": target_id,
        "owner_plan_sha256": plan_sha256,
        "failure_type": type(error).__name__,
        "failure": str(error)[:512],
    }
    try:
        raw = (json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n").encode()
        _write_exclusive(target_fd, _INCOMPLETE_NAME, raw)
        _fsync_directory(target_fd)
        return True
    except BaseException:
        # Preserve the original allocation failure.  A successfully created
        # marker remains immutable even when its directory fsync also fails.
        return False


def allocate(plan_path: Path, expected_plan_sha256: str) -> dict[str, Any]:
    """Allocate one new directory and, for legacy archives, byte-copy two pins."""
    _require(sys.platform.startswith("linux"), "allocator is Linux-only and fails closed elsewhere")
    plan, plan_sha256 = _read_plan(plan_path, expected_plan_sha256)
    operator_uid = plan["operator_uid"]
    operator_gid = plan["operator_gid"]
    parent_path = plan["trusted_parent"]
    protected_path = plan["protected_trust_root"]
    target_path = str(Path(parent_path) / plan["target_id"])
    _require(not _paths_overlap(Path(target_path), Path(protected_path)),
             "allocation target overlaps the protected Trust root")
    protected_fd, _ = _open_directory_chain(protected_path, operator_uid, operator_gid)
    try:
        _require(os.readlink(f"/proc/self/fd/{protected_fd}") == protected_path,
                 "protected Trust root is not its canonical pinned path")
        _require(not _acl_xattrs(protected_fd), "protected Trust root has a POSIX ACL")
    finally:
        os.close(protected_fd)
    parent_fd, _chain = _open_directory_chain(parent_path, operator_uid, operator_gid)
    target_fd: int | None = None
    created = False
    try:
        parent_stat = os.fstat(parent_fd)
        _require(parent_stat.st_uid == operator_uid and parent_stat.st_gid == operator_gid,
                 "trusted parent is not owned by the approved Operator UID/GID")
        _require(stat.S_IMODE(parent_stat.st_mode) == 0o700,
                 "trusted parent mode must be exactly 0700")
        _require(parent_stat.st_dev == plan["parent_device"] and parent_stat.st_ino == plan["parent_inode"],
                 "trusted parent device/inode differs from Owner pin")
        _require(_mount_id_for(parent_path) == plan["parent_mount_id"],
                 "trusted parent mount ID differs from Owner pin")
        _require(os.readlink(f"/proc/self/fd/{parent_fd}") == parent_path,
                 "trusted parent fd does not resolve to its canonical Owner path")
        _require(not _acl_xattrs(parent_fd), "trusted parent has a POSIX ACL")

        source_root_fd = _verify_source_checkout(
            plan["source_checkout"], plan["source_commit"], operator_uid, operator_gid
        )

        payloads: dict[str, bytes] = {}
        if plan["operation_kind"] == "legacy_archive":
            # All pre-copy byte checks complete before the target or any destination exists.
            try:
                for source in plan["archive_sources"]:
                    payloads[source["name"]] = _secure_source(
                        source_root_fd, source["relative_path"], source["sha256"]
                    )
            finally:
                os.close(source_root_fd)
        else:
            os.close(source_root_fd)

        target_id = plan["target_id"]
        os.mkdir(target_id, 0o700, dir_fd=parent_fd)
        created = True
        target_fd = os.open(target_id, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                            dir_fd=parent_fd)
        target_stat = os.fstat(target_fd)
        _require(target_stat.st_uid == operator_uid and target_stat.st_gid == operator_gid
                 and stat.S_IMODE(target_stat.st_mode) == 0o700,
                 "new target owner/mode identity mismatch")
        _require(os.fstat(parent_fd).st_ino == plan["parent_inode"], "parent changed after target creation")
        check_parent_fd, _ = _open_directory_chain(parent_path, operator_uid, operator_gid)
        try:
            check_parent_stat = os.fstat(check_parent_fd)
            _require((check_parent_stat.st_dev, check_parent_stat.st_ino)
                     == (parent_stat.st_dev, parent_stat.st_ino),
                     "trusted parent was renamed or replaced during allocation")
        finally:
            os.close(check_parent_fd)

        file_rows: list[dict[str, Any]] = []
        for name, payload in payloads.items():
            info = _write_exclusive(target_fd, name, payload)
            file_rows.append({"name": name, "sha256": hashlib.sha256(payload).hexdigest(),
                              "size": len(payload), "device": info.st_dev, "inode": info.st_ino})
        _fsync_directory(target_fd)

        record = {
            "record_version": "rq03f-allocation-record-1.0",
            "allocation_status": "complete",
            "operation_kind": plan["operation_kind"],
            "operation_scope": plan["operation_scope"],
            "target_id": target_id,
            "source_commit": plan["source_commit"],
            "protected_trust_root": protected_path,
            "owner_plan_sha256": plan_sha256,
            "operator_uid": operator_uid,
            "operator_gid": operator_gid,
            "parent": {"canonical_path": parent_path, "device": parent_stat.st_dev,
                       "inode": parent_stat.st_ino, "mount_id": plan["parent_mount_id"]},
            "target": {"device": target_stat.st_dev, "inode": target_stat.st_ino,
                       "uid": target_stat.st_uid, "gid": target_stat.st_gid, "mode": "0700"},
            "files": sorted(file_rows, key=lambda item: item["name"]),
            "authority_status": "candidate_allocation_only",
        }
        record_bytes = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        _write_exclusive(target_fd, _RECORD_NAME, record_bytes)

        # The complete record is only prepared evidence.  It is deliberately
        # not consumable until the target and parent durability checks and the
        # reopened-parent identity check have succeeded.  Any failure before
        # the finalization receipt leaves an immutable incomplete marker.
        _fsync_directory(target_fd)
        _fsync_directory(parent_fd)
        final_parent_fd, _ = _open_directory_chain(parent_path, operator_uid, operator_gid)
        try:
            final_parent_stat = os.fstat(final_parent_fd)
            _require((final_parent_stat.st_dev, final_parent_stat.st_ino)
                     == (parent_stat.st_dev, parent_stat.st_ino),
                     "trusted parent identity changed before allocation completed")
            final_target_fd = os.open(
                target_id, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=final_parent_fd,
            )
            try:
                final_target_stat = os.fstat(final_target_fd)
                _require((final_target_stat.st_dev, final_target_stat.st_ino)
                         == (target_stat.st_dev, target_stat.st_ino)
                         and final_target_stat.st_uid == operator_uid
                         and final_target_stat.st_gid == operator_gid
                         and stat.S_IMODE(final_target_stat.st_mode) == 0o700,
                         "target identity changed before allocation finalization")
                _require(os.fstat(target_fd).st_ino == final_target_stat.st_ino,
                         "open target identity differs from final parent entry")
            finally:
                os.close(final_target_fd)
        finally:
            os.close(final_parent_fd)

        finalization = {
            "record_version": "rq03f-allocation-finalization-1.0",
            "finalization_status": "finalized",
            "target_id": target_id,
            "owner_plan_sha256": plan_sha256,
            "allocation_record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            "target": {"device": target_stat.st_dev, "inode": target_stat.st_ino,
                       "uid": target_stat.st_uid, "gid": target_stat.st_gid, "mode": "0700"},
        }
        finalization_bytes = (json.dumps(finalization, sort_keys=True, separators=(",", ":"))
                              + "\n").encode("utf-8")
        _write_exclusive(target_fd, _FINALIZED_NAME, finalization_bytes)
        # The target directory entry is the final commit record.  It is created
        # only after all path and parent checks.  If this sync fails, the
        # exception path adds an incomplete marker; every reader rejects that
        # marker even though the prepared complete record and finalizer remain.
        _fsync_directory(target_fd)
        return {"path": os.path.join(parent_path, target_id), "record": record,
                "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
                "finalization": finalization,
                "finalization_sha256": hashlib.sha256(finalization_bytes).hexdigest()}
    except BaseException as exc:
        if created and target_fd is not None:
            marked = _mark_incomplete(target_fd, plan["target_id"], plan_sha256, exc)
            if not marked:
                exc.add_note("allocation remains unusable; incomplete marker could not be written")
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)
        os.close(parent_fd)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    allocate_parser = sub.add_parser("allocate", help="perform one exact Owner-pinned allocation")
    allocate_parser.add_argument("--plan", required=True, type=Path)
    allocate_parser.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    result = allocate(args.plan, args.expected_plan_sha256)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except (AllocationError, OSError, ValueError) as exc:
        print(f"BLOCKED — {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
