#!/usr/bin/env python3
"""Disposable root-provisioned C2 Launcher/Provider test on hosted Ubuntu.

All authority material created here is synthetic, short-lived, and removed in
finally. The script never installs or starts the candidate systemd unit and
never reads or writes the formal Trust Anchor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "scripts"
SCHEMAS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "schemas"
REQUIREMENTS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "requirements.txt"
UNIT_SOURCE = ROOT / "systemd" / "rq03f-operator-preflight.service"
CONFIG_ROOT = Path("/etc/rq03f")
POLICY_PATH = CONFIG_ROOT / "launch-policy.json"
PIN_PATH = CONFIG_ROOT / "launch-policy.pin.json"
BUILD_PATH = CONFIG_ROOT / "controller-build-inventory.json"
RUNTIME_CLOSURE_PATH = CONFIG_ROOT / "runtime-closure.json"
DEPENDENCY_INVENTORY_PATH = CONFIG_ROOT / "dependency-inventory.json"
ROLE_NAMES = ("operator", "candidate", "author", "reviewer", "approver")
GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent",
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_OPTIONAL_LOCKS": "0",
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_new(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, mode)
    try:
        view = memoryview(raw)
        offset = 0
        while offset < len(view):
            count = os.write(fd, view[offset:])
            if count <= 0:
                fail("short write in synthetic fixture")
            offset += count
        os.fsync(fd)
    finally:
        os.close(fd)


def write_replace(path: Path, raw: bytes, *, owner: int = 0, group: int = 0, mode: int = 0o644) -> None:
    temp = path.with_name(path.name + ".c2-test-replacement")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, mode)
        try:
            os.write(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chown(temp, owner, group)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def command(args: list[str], *, check: bool = True, cwd: Path | None = None,
            env: dict[str, str] | None = None, pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True,
                            check=False, pass_fds=pass_fds)
    if check and result.returncode != 0:
        fail(f"command failed ({result.returncode}): {args[0]}: {result.stderr[-1200:]}")
    return result


def account_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def group_exists(name: str) -> bool:
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def add_identities(run_root: Path, created_users: list[str], created_groups: list[str]) -> tuple[dict[str, dict[str, Any]], int]:
    token = str(os.getpid())
    identities: dict[str, dict[str, Any]] = {}
    del run_root  # identities are system-level only for the duration of this hosted job
    uid = 4601
    gid = 4601
    for role in ROLE_NAMES:
        username = f"rq03c2-{token}-{role[:3]}"
        groupname = username
        if account_exists(username) or group_exists(groupname):
            fail("temporary C2 identity name already exists; refusing to reuse it")
        while True:
            try:
                pwd.getpwuid(uid)
                uid += 10
                gid += 10
                continue
            except KeyError:
                pass
            try:
                grp.getgrgid(gid)
                uid += 10
                gid += 10
                continue
            except KeyError:
                break
            uid += 10
            gid += 10
        created_groups.append(groupname)
        command(["/usr/sbin/groupadd", "--system", "--gid", str(gid), groupname])
        created_users.append(username)
        command(["/usr/sbin/useradd", "--no-create-home", "--no-log-init", "--shell", "/usr/sbin/nologin",
                 "--uid", str(uid), "--gid", str(gid), username])
        identities[role] = {
            "principal_id": f"c2-{role}-principal",
            "uid": uid,
            "gid": gid,
            "username": username,
            "groupname": groupname,
        }
        uid += 1
        gid += 1
    extra_group = f"rq03c2-{token}-extra"
    if group_exists(extra_group):
        fail("temporary C2 extra group name already exists; refusing to reuse it")
    while True:
        try:
            grp.getgrgid(gid)
            gid += 1
        except KeyError:
            break
    created_groups.append(extra_group)
    command(["/usr/sbin/groupadd", "--system", "--gid", str(gid), extra_group])
    return identities, gid


def tree_sha(root: Path, *, include_bytecode: bool = False) -> str:
    rows: list[tuple[str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        retained = []
        for name in sorted(directories):
            info = (base / name).lstat()
            if not stat.S_ISDIR(info.st_mode):
                fail(f"test build tree contains a symlink/special directory: {base / name}")
            if include_bytecode or name != "__pycache__":
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = base / name
            if (not include_bytecode and path.suffix.casefold() in {".pyc", ".pyo"}
                    and "__pycache__" in path.parts):
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                fail(f"test build tree contains a symlink/special file: {path}")
            rows.append((path.relative_to(root).as_posix(), sha_bytes(path.read_bytes())))
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return sha_bytes(raw)


def runtime_tree_sha(root: Path) -> str:
    rows: list[tuple[str, str, str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            path = base / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                if not resolved.is_file():
                    fail(f"test runtime has an unsupported directory symlink: {path}")
                rows.append((path.relative_to(root).as_posix(), "symlink-file", target, sha_bytes(resolved.read_bytes())))
            else:
                if not stat.S_ISDIR(info.st_mode):
                    fail(f"test runtime has a special directory: {path}")
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = base / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                if not resolved.is_file():
                    fail(f"test runtime symlink target is not a file: {path}")
                rows.append((path.relative_to(root).as_posix(), "symlink-file", target, sha_bytes(resolved.read_bytes())))
            else:
                if not stat.S_ISREG(info.st_mode):
                    fail(f"test runtime has a special file: {path}")
                rows.append((path.relative_to(root).as_posix(), "file", "", sha_bytes(path.read_bytes())))
    rows.sort(key=lambda row: row[0])
    return sha_bytes(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode())


def _source_directory_fd(path: Path) -> int:
    if not path.is_absolute() or str(path) != os.path.normpath(str(path)):
        fail("candidate Controller source path is not canonical")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            info = os.fstat(next_fd)
            if not stat.S_ISDIR(info.st_mode):
                os.close(next_fd)
                fail("candidate Controller source contains a non-directory path component")
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _copy_source_directory_fd(source_fd: int, destination: Path, *, relative: str = "",
                              expected_blobs: dict[str, tuple[str, str]] | None = None) -> None:
    """Copy only stable regular files from an untrusted checkout dirfd.

    Root provisioning must not follow a Candidate symlink or hardlink while
    copying source into the synthetic root-owned Controller generation.
    Directory and file descriptors pin each object while bytes are read.
    """
    destination.mkdir(mode=0o755)
    directory_before = os.fstat(source_fd)
    names = sorted(os.listdir(source_fd))
    for name in names:
        if name == "__pycache__" or fnmatch.fnmatchcase(name, "*.pyc"):
            continue
        if name in {".", ".."} or "/" in name or "\x00" in name:
            fail("candidate Controller source has an invalid path entry")
        info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        target = destination / name
        if stat.S_ISDIR(info.st_mode):
            child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                               dir_fd=source_fd)
            try:
                opened = os.fstat(child_fd)
                if (not stat.S_ISDIR(opened.st_mode)
                        or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                    fail("candidate Controller directory changed during copy")
                child_relative = f"{relative}/{name}" if relative else name
                _copy_source_directory_fd(child_fd, target, relative=child_relative,
                                          expected_blobs=expected_blobs)
                current = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                    fail("candidate Controller directory path changed during copy")
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                fail("candidate Controller source contains a hard-linked file")
            fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=source_fd)
            try:
                before = os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                        or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)):
                    fail("candidate Controller file identity changed during copy")
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(fd)
                current = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
                stable = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns,
                                      row.st_ctime_ns, row.st_mode, row.st_uid, row.st_gid, row.st_nlink)
                if stable(before) != stable(after) or stable(after) != stable(current):
                    fail("candidate Controller file changed during copy")
                raw = b"".join(chunks)
                rel_path = f"{relative}/{name}" if relative else name
                expected = expected_blobs.get(rel_path) if expected_blobs is not None else None
                if expected_blobs is not None and expected is None:
                    fail("Candidate working tree contains a Controller file absent from pinned Git HEAD")
                blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                if expected is not None and blob_sha != expected[1]:
                    fail("Candidate Controller source bytes differ from pinned Git HEAD blob")
                if expected is not None:
                    expected_blobs.pop(rel_path)
                executable = (expected[0] == "100755" if expected is not None
                              else bool(before.st_mode & 0o111))
                mode = 0o555 if executable else 0o444
                out_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                                 0o600)
                try:
                    view = memoryview(raw)
                    offset = 0
                    while offset < len(view):
                        count = os.write(out_fd, view[offset:])
                        if count <= 0:
                            fail("short write copying synthetic Controller file")
                        offset += count
                    os.fsync(out_fd)
                    os.fchmod(out_fd, mode)
                finally:
                    os.close(out_fd)
            finally:
                os.close(fd)
        else:
            fail("candidate Controller source contains a symlink or special file")
    directory_after = os.fstat(source_fd)
    if ((directory_before.st_dev, directory_before.st_ino, directory_before.st_mtime_ns,
         directory_before.st_ctime_ns) !=
        (directory_after.st_dev, directory_after.st_ino, directory_after.st_mtime_ns,
         directory_after.st_ctime_ns)
            or names != sorted(os.listdir(source_fd))):
        fail("candidate Controller directory changed during copy")


def copy_source_tree(source: Path, destination: Path,
                     *, expected_blobs: dict[str, tuple[str, str]] | None = None) -> None:
    source_fd = _source_directory_fd(source)
    try:
        _copy_source_directory_fd(source_fd, destination, expected_blobs=expected_blobs)
    finally:
        os.close(source_fd)
    if expected_blobs:
        fail("pinned Git Controller blobs were missing from the checked-out source tree")


def _git_source_blob_manifest(source: Path, commit: str) -> dict[str, tuple[str, str]]:
    try:
        source_key = source.relative_to(ROOT).as_posix()
    except ValueError:
        fail("Controller source is outside the checked-out repository")
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "ls-tree", "-r", "-z", "--full-tree",
         commit, "--", source_key],
        env=GIT_ENV, capture_output=True, check=False,
    )
    if result.returncode != 0:
        fail("could not enumerate the exact Controller source Git tree")
    prefix = source_key + "/"
    manifest: dict[str, tuple[str, str]] = {}
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode_raw, object_type, oid_raw = header.split(b" ", 2)
            path = raw_path.decode("utf-8", errors="strict")
            mode = mode_raw.decode("ascii")
            oid = oid_raw.decode("ascii")
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("malformed Git tree entry in Controller source") from exc
        if (object_type != b"blob" or mode not in {"100644", "100755"}
                or not path.startswith(prefix) or re.fullmatch(r"[a-f0-9]{40}", oid) is None):
            fail("pinned Controller Git tree contains a symlink, special mode or invalid path")
        relative = path[len(prefix):]
        if (not relative or relative.startswith("/") or "\\" in relative
                or any(part in {"", ".", ".."} for part in relative.split("/"))
                or relative in manifest):
            fail("pinned Controller Git tree contains an aliased or duplicate path")
        manifest[relative] = (mode, oid)
    if not manifest:
        fail("pinned Git HEAD has no Controller source files")
    return manifest


def copy_controller(controller_root: Path, source_commit: str) -> None:
    controller_root.mkdir(parents=True)
    for source, destination in ((SCRIPTS, controller_root / "scripts"),
                                (SCHEMAS, controller_root / "schemas")):
        copy_source_tree(source, destination,
                         expected_blobs=_git_source_blob_manifest(source, source_commit))


def build_inventory(controller_root: Path, runtime_root: Path, build_path: Path,
                    controller_id: str) -> tuple[dict[str, Any], bytes, Path]:
    sys.path.insert(0, str(controller_root / "scripts"))
    import operator_controller_bootstrap as bootstrap
    scripts_root = controller_root / "scripts"
    schemas_root = controller_root / "schemas"
    executable = runtime_root / "bin" / "python"
    version_code = "import json,sys; print(json.dumps({'version':sys.version.split()[0]}))"
    version = json.loads(command([str(executable), "-I", "-S", "-B", "-c", version_code]).stdout)["version"]
    version_parts = version.split(".")
    site_packages = runtime_root / "lib" / f"python{version_parts[0]}.{version_parts[1]}" / "site-packages"
    components: list[dict[str, str]] = [
        {"component_id": "controller_scripts_tree", "component_type": "controller_tree",
         "runtime_path": str(scripts_root), "sha256": bootstrap.sha256_tree(scripts_root)},
        {"component_id": "controller_schemas_tree", "component_type": "controller_tree",
         "runtime_path": str(schemas_root), "sha256": bootstrap.sha256_tree(schemas_root)},
    ]
    for path in sorted(scripts_root.rglob("*.py")):
        parts = list(path.relative_to(scripts_root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        component_id = ".".join(parts)
        components.append({"component_id": component_id, "component_type": "python_module",
                           "inventory_key": f"controller-module:{component_id}",
                           "runtime_path": str(path), "sha256": bootstrap.sha256_file(path)})
    seen_schema_names: set[str] = set()
    for path in sorted(schemas_root.rglob("*.schema.json")):
        component_id = path.name if path.name not in seen_schema_names else path.relative_to(schemas_root).as_posix()
        seen_schema_names.add(path.name)
        components.append({"component_id": component_id, "component_type": "json_schema",
                           "inventory_key": f"controller-schema:{path.relative_to(schemas_root).as_posix()}",
                           "runtime_path": str(path), "sha256": bootstrap.sha256_file(path)})
    for path in sorted(site_packages.iterdir()):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            if path.name.endswith((".dist-info", ".egg-info", ".data")) or path.name == "__pycache__":
                continue
            if any(child.is_file() and child.suffix in {".py", ".pyi", ".so", ".pyd", ".dll"}
                   for child in path.rglob("*")):
                components.append({"component_id": path.name, "component_type": "python_package",
                                   "runtime_path": str(path),
                                   "sha256": bootstrap.sha256_tree(path, include_bytecode_cache=True)})
        elif stat.S_ISREG(info.st_mode) and path.suffix == ".py":
            components.append({"component_id": path.stem, "component_type": "python_dependency_module",
                               "runtime_path": str(path), "sha256": bootstrap.sha256_file(path)})
        else:
            if not stat.S_ISREG(info.st_mode):
                fail(f"site-packages contains a special path: {path}")
    payload = {
        "build_inventory_version": "1.1",
        "controller_id": controller_id,
        "controller_root": str(controller_root),
        "python_runtime": {
            "python_executable": str(executable),
            "python_executable_sha256": bootstrap.sha256_file(executable),
            "python_version": version,
            "site_packages_root": str(site_packages),
            "site_packages_sha256": bootstrap.sha256_runtime_tree(site_packages),
        },
        "components": sorted(components, key=lambda row: (row["component_type"], row["component_id"])),
    }
    raw = canonical(payload)
    write_new(build_path, raw, 0o444)
    return payload, raw, site_packages


def profile_and_index(identities: dict[str, dict[str, Any]], controller_id: str,
                      controller_impl: str, controller_version: str, build_sha: str,
                      trust_root: Path, now: datetime) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes, dict[str, bytes]]:
    role_specs = {
        "operator": ("qualification_corpus_custodian",),
        "author": ("author",),
        "reviewer": ("scope_reviewer",),
        "approver": ("qualification_approver",),
    }
    role_rows: list[dict[str, Any]] = []
    auth_bytes: dict[str, bytes] = {}
    for role, allowed in role_specs.items():
        identity = identities[role]
        key = f"auth-{role}"
        auth = {"record_version": "1.1", "principal_id": identity["principal_id"],
                "allowed_roles": list(allowed)}
        raw = canonical(auth)
        auth_bytes[key] = raw
        role_rows.append({
            "principal_id": identity["principal_id"],
            "allowed_roles": list(allowed),
            "authorization_reference": key,
            "valid_from": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            "valid_until": (now + timedelta(days=365)).isoformat().replace("+00:00", "Z"),
            "revoked_at": None,
            "revocation_reason": None,
        })
    profile = {
        "profile_version": "1.1",
        "authority_profile_id": "synthetic-c2-profile",
        "policy_epoch": 1,
        "operator_reference": "operator-reference",
        "controller_id": controller_id,
        "controller_implementation": controller_impl,
        "controller_version": controller_version,
        "ingress_procedure_reference": "ingress-reference",
        "evidence_repository_reference": "evidence-repository-reference",
        "roles": role_rows,
        "revoked_authority_ids": [],
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "qualification_corpus_custodian_principal": identities["operator"]["principal_id"],
        "operator_unix_uid": identities["operator"]["uid"],
        "non_operator_process_unix_uids": sorted(identities[role]["uid"] for role in ROLE_NAMES if role != "operator"),
        "controller_build_inventory_key": "controller_build_inventory",
        "controller_build_inventory_sha256": build_sha,
    }
    index = {
        "index_version": "1.1",
        "controller_id": controller_id,
        "policy_epoch": 1,
        "receipts": [],
        "authors": [],
        "adjudications": [],
        "qualification_runs": [],
        "qualification_corpus_intakes": [],
    }
    return profile, canonical(profile), index, canonical(index), auth_bytes


def build_policy(identities: dict[str, dict[str, Any]], generation_root: Path,
                 controller_root: Path, runtime_root: Path, python_executable: Path,
                 build_path: Path, build_sha: str, profile_path: Path, profile_sha: str,
                 index_path: Path, index_sha: str, runtime_closure_path: Path,
                 runtime_closure_sha: str, package_sha: str, libraries_sha: str,
                 inventory_path: Path, inventory_sha: str, trust_root: Path,
                 source_commit: str) -> tuple[dict[str, Any], bytes, dict[str, Any], bytes]:
    controller_id = "rq03f-c2-synthetic-controller"
    controller_impl = "fixed-operator-launcher"
    controller_version = "1.0"
    role_map = {
        "operator": ["qualification_corpus_custodian"],
        "author": ["author"],
        "reviewer": ["scope_reviewer"],
        "approver": ["qualification_approver"],
    }
    role_refs = []
    for role, allowed in role_map.items():
        principal = identities[role]["principal_id"]
        ref = "auth-" + role
        auth_path = trust_root / (ref + ".json")
        role_refs.append({"principal_id": principal, "authorization_reference": ref,
                          "authorization_sha256": sha_bytes(auth_path.read_bytes()),
                          "allowed_roles": allowed})
    launcher_path = controller_root / "scripts" / "rq03f_fixed_operator_launcher.py"
    policy = {
        "policy_version": "rq03f-operator-launch-policy-1.0",
        "authority_status": "candidate_only_not_owner_authority",
        "owner_adopted_policy_source_identity": {
            "adoption_status": "candidate_only",
            "policy_identity": "synthetic-hosted-c2-policy",
            "source_commit": source_commit,
        },
        "source_commit": source_commit,
        "generation": {
            "generation_id": "rq03f-c2-hosted-synthetic",
            "final_path": str(generation_root),
            "operation_root": str(generation_root / "operations"),
        },
        "controller": {
            "controller_id": controller_id,
            "implementation": controller_impl,
            "version": controller_version,
            "root": str(controller_root),
            "runtime_root": str(runtime_root),
            "python_executable": str(python_executable),
            "build_inventory": {"key": "controller_build_inventory", "path": str(build_path), "sha256": build_sha},
            "controller_allowlist": [{"controller_id": controller_id, "implementation": controller_impl, "version": controller_version}],
            "fixed_entrypoint": {"entrypoint_id": "rq03f-operator-preflight-v1",
                                 "operation": "read_only_preflight", "module_path": str(launcher_path),
                                 "module_sha256": sha_bytes(launcher_path.read_bytes())},
        },
        "profile": {"version": "1.1", "path": str(profile_path), "sha256": profile_sha, "policy_epoch": 1},
        "operation_index": {"version": "1.1", "path": str(index_path),
                            "initial_adoption_sha256": index_sha,
                            "consistency": "current_append_only_each_operation"},
        "runtime_closure": {
            "path": str(runtime_closure_path), "sha256": runtime_closure_sha,
            "base_image_digest_claim": "sha256:" + "0" * 64,
            "os_package_manifest_sha256": package_sha,
            "shared_libraries_manifest_sha256": libraries_sha,
            "authority_status": "candidate_only_unverified_host_claims",
        },
        "dependency_inventory": {"path": str(inventory_path), "sha256": inventory_sha,
                                 "run_root": str(generation_root / "operations"),
                                 "protected_roots": [str(CONFIG_ROOT), str(trust_root), str(controller_root), str(runtime_root)]},
        "identities": {role: {"principal_id": identities[role]["principal_id"],
                              "uid": identities[role]["uid"], "gid": identities[role]["gid"]}
                       for role in ROLE_NAMES},
        "role_authorization_references": role_refs,
        "revocation_references": {"inventory_key": "authority_profile",
                                  "fields": ["revoked_authority_ids", "roles[].revoked_at", "roles[].revocation_reason"],
                                  "recheck_each_operation": True},
        "anti_rollback": {"required": True, "interface": "rq03f-c3-anti-rollback-gate-v1",
                          "production_writes_allowed": False, "absent_behavior": "block"},
        "service": {"disabled_by_default": True, "install_or_start_authorized": False},
    }
    policy_raw = canonical(policy)
    pin = {"pin_version": "rq03f-operator-policy-pin-1.0",
           "policy_identity": "synthetic-hosted-c2-policy",
           "policy_sha256": sha_bytes(policy_raw), "adoption_status": "candidate_only"}
    return policy, policy_raw, pin, canonical(pin)


def create_dependency_inventory(payload: dict[str, Any], build_raw: bytes,
                                profile_path: Path, profile_raw: bytes,
                                index_path: Path, index_raw: bytes,
                                trust_root: Path, controller_root: Path,
                                runtime_root: Path, run_root: Path,
                                build_path: Path, auth_files: dict[str, bytes],
                                manifest_path: Path) -> tuple[dict[str, Any], bytes]:
    entries: list[dict[str, str]] = []
    def add(key: str, path: Path, raw: bytes, storage: str = "protected_external") -> None:
        entries.append({"inventory_key": key, "path": str(path), "sha256": sha_bytes(raw), "storage_class": storage})
    add("authority_profile", profile_path, profile_raw)
    add("operation_index", index_path, index_raw)
    add("controller_build_inventory", build_path, build_raw)
    references = {
        "operator_reference": b"synthetic operator reference\n",
        "ingress-reference": b"synthetic ingress reference\n",
        "evidence-repository-reference": b"synthetic evidence repository reference\n",
    }
    for key, raw in references.items():
        path = trust_root / f"{key}.txt"
        write_new(path, raw, 0o600)
        add(key, path, raw)
    for key, raw in auth_files.items():
        path = trust_root / f"{key}.json"
        write_new(path, raw, 0o600)
        add(key, path, raw)
    for component in payload["components"]:
        key = component.get("inventory_key")
        if key:
            path = Path(component["runtime_path"])
            add(key, path, path.read_bytes())
    run_file = run_root / "preflight-input.json"
    write_new(run_file, b'{"purpose":"preflight"}\n', 0o444)
    add("preflight_input", run_file, run_file.read_bytes(), "run")
    manifest = {"inventory_version": "1.0", "entries": entries}
    raw = canonical(manifest)
    write_new(manifest_path, raw, 0o444)
    return manifest, raw


def set_tree_owner(root: Path, uid: int, gid: int, *, files_mode: int, dirs_mode: int) -> None:
    for current, directories, files in os.walk(root, topdown=False, followlinks=False):
        base = Path(current)
        for name in files:
            path = base / name
            os.chown(path, uid, gid, follow_symlinks=False)
            os.chmod(path, files_mode, follow_symlinks=False)
        for name in directories:
            path = base / name
            os.chown(path, uid, gid, follow_symlinks=False)
            os.chmod(path, dirs_mode, follow_symlinks=False)
    os.chown(root, uid, gid)
    os.chmod(root, dirs_mode)


def set_root_readonly(root: Path) -> None:
    for current, directories, files in os.walk(root, topdown=False, followlinks=False):
        for name in files:
            path = Path(current) / name
            os.chown(path, 0, 0, follow_symlinks=False)
            os.chmod(path, 0o555 if os.access(path, os.X_OK) else 0o444, follow_symlinks=False)
        for name in directories:
            path = Path(current) / name
            os.chown(path, 0, 0, follow_symlinks=False)
            os.chmod(path, 0o555, follow_symlinks=False)
    os.chown(root, 0, 0)
    os.chmod(root, 0o555)


def identity_command(identity: dict[str, Any], argv: list[str], *, env: dict[str, str] | None = None,
                     supplementary: tuple[int, ...] | None = None, bounding: str = "-all",
                     pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess:
    args = ["/usr/bin/setpriv", "--reuid", str(identity["uid"]), "--regid", str(identity["gid"])]
    if supplementary is None:
        args.append("--clear-groups")
    else:
        args.extend(["--groups", ",".join(map(str, supplementary))])
    args.extend(["--bounding-set", bounding, "--inh-caps", "-all", "--ambient-caps", "-all", "--no-new-privs", "--"])
    args.extend(argv)
    clean_env = {"PATH": "/usr/bin:/bin", "HOME": "/var/empty", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if env:
        clean_env.update(env)
    return command(args, check=False, env=clean_env, pass_fds=pass_fds)


def expected_code(result: subprocess.CompletedProcess, code: str, label: str, evidence: list[dict[str, Any]]) -> None:
    output = (result.stdout + result.stderr).strip()
    try:
        row = json.loads(output.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        fail(f"{label}: launcher did not emit a structured refusal: {output[-800:]}")
    if result.returncode != 2 or row.get("status") != "blocked" or row.get("error_code") != code:
        fail(f"{label}: expected {code}, got exit={result.returncode}, record={row}")
    evidence.append({"case": label, "expected": code, "actual": code,
                     "exit_code": result.returncode, "uid": row.get("operator_uid")})


def rebind_config(policy: dict[str, Any], pin: dict[str, Any], *, profile: dict[str, Any] | None = None,
                  index: dict[str, Any] | None = None,
                  update_policy: Any = None) -> tuple[bytes, bytes, bytes, bytes]:
    old_policy = POLICY_PATH.read_bytes()
    old_pin = PIN_PATH.read_bytes()
    profile_path = Path(policy["profile"]["path"])
    index_path = Path(policy["operation_index"]["path"])
    old_profile = profile_path.read_bytes()
    old_index = index_path.read_bytes()
    policy = json.loads(old_policy)
    if profile is not None:
        new_profile = canonical(profile)
        write_replace(profile_path, new_profile, owner=policy["identities"]["operator"]["uid"],
                      group=policy["identities"]["operator"]["gid"], mode=0o600)
        policy["profile"]["sha256"] = sha_bytes(new_profile)
    if index is not None:
        new_index = canonical(index)
        write_replace(index_path, new_index, owner=policy["identities"]["operator"]["uid"],
                      group=policy["identities"]["operator"]["gid"], mode=0o600)
        policy["operation_index"]["initial_adoption_sha256"] = sha_bytes(new_index)
    if update_policy is not None:
        update_policy(policy)
    policy_raw = canonical(policy)
    pin = json.loads(old_pin)
    pin["policy_sha256"] = sha_bytes(policy_raw)
    write_replace(POLICY_PATH, policy_raw, mode=0o444)
    pin_raw = canonical(pin)
    write_replace(PIN_PATH, pin_raw, mode=0o444)
    return old_policy, old_pin, old_profile, old_index


def restore_config(policy_raw: bytes, pin_raw: bytes, profile_raw: bytes, index_raw: bytes,
                   operator: dict[str, Any]) -> None:
    profile_path = Path(json.loads(policy_raw)["profile"]["path"])
    index_path = Path(json.loads(policy_raw)["operation_index"]["path"])
    write_replace(profile_path, profile_raw, owner=operator["uid"], group=operator["gid"], mode=0o600)
    write_replace(index_path, index_raw, owner=operator["uid"], group=operator["gid"], mode=0o600)
    write_replace(POLICY_PATH, policy_raw, mode=0o444)
    write_replace(PIN_PATH, pin_raw, mode=0o444)


def setup_systemd_verify_root(root: Path, identities: dict[str, dict[str, Any]]) -> Path:
    fake_root = root / "systemd-verify-root"
    unit_path = fake_root / "usr/lib/systemd/system/rq03f-operator-preflight.service"
    python_path = fake_root / "opt/rq03f/generations/rq03f-candidate-0001/runtime/bin/python"
    launcher_path = fake_root / "opt/rq03f/generations/rq03f-candidate-0001/controller/scripts/rq03f_fixed_operator_launcher.py"
    (fake_root / "etc/rq03f").mkdir(parents=True)
    (fake_root / "etc").mkdir(exist_ok=True)
    for directory in ("root", "home", "run/user", "var/empty"):
        (fake_root / directory).mkdir(parents=True, exist_ok=True)
    (fake_root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/sh\n", encoding="utf-8")
    (fake_root / "etc/group").write_text("root:x:0:\n", encoding="utf-8")
    operator = identities["operator"]
    with (fake_root / "etc/passwd").open("a", encoding="utf-8") as stream:
        stream.write(f"rq03f-operator:x:{operator['uid']}:{operator['gid']}::/nonexistent:/usr/sbin/nologin\n")
    with (fake_root / "etc/group").open("a", encoding="utf-8") as stream:
        stream.write(f"rq03f-operator:x:{operator['gid']}:\n")
    sysinit_target = fake_root / "usr/lib/systemd/system/sysinit.target"
    sysinit_target.parent.mkdir(parents=True, exist_ok=True)
    sysinit_target.write_text("[Unit]\nDescription=synthetic sysinit target\n", encoding="utf-8")
    os.chmod(sysinit_target, 0o444)
    for role in ROLE_NAMES:
        ident = identities[role]
        with (fake_root / "etc/passwd").open("a", encoding="utf-8") as stream:
            stream.write(f"{ident['username']}:x:{ident['uid']}:{ident['gid']}::/nonexistent:/usr/sbin/nologin\n")
        with (fake_root / "etc/group").open("a", encoding="utf-8") as stream:
            stream.write(f"{ident['groupname']}:x:{ident['gid']}:\n")
    python_path.parent.mkdir(parents=True)
    launcher_path.parent.mkdir(parents=True)
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher_path.write_text("# synthetic unit verification only\n", encoding="utf-8")
    os.chmod(python_path, 0o755)
    os.chmod(launcher_path, 0o444)
    shutil.copy2(UNIT_SOURCE, unit_path)
    os.chmod(unit_path, 0o444)
    return unit_path


def main() -> int:
    if os.geteuid() != 0 or not sys.platform.startswith("linux"):
        fail("Hosted C2 qualification must run as real Linux root for provisioning")
    if CONFIG_ROOT.exists():
        fail("/etc/rq03f already exists; refusing to reuse any trust/config path")
    source_commit = os.environ.get("C2_EXPECTED_SOURCE_COMMIT", "")
    if re.fullmatch(r"[a-f0-9]{40}", source_commit) is None:
        fail("exact GitHub event source commit must be explicitly provided")
    checked_out_head = command(
        ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD^{commit}"],
        env=GIT_ENV,
    ).stdout.strip()
    if checked_out_head != source_commit:
        fail("checked-out HEAD differs from the exact GitHub event source commit")
    evidence: list[dict[str, Any]] = []
    created_users: list[str] = []
    created_groups: list[str] = []
    base: Path | None = None
    config_created = False
    failure: BaseException | None = None
    try:
        base = Path(tempfile.mkdtemp(prefix="rq03f-c2-", dir="/var/lib"))
        os.chown(base, 0, 0)
        os.chmod(base, 0o755)
        identities, extra_gid = add_identities(base, created_users, created_groups)
        operator = identities["operator"]
        generation_root = base / "generation"
        controller_root = generation_root / "controller"
        runtime_root = generation_root / "runtime"
        operation_root = generation_root / "operations"
        trust_root = base / "protected-trust"
        generation_root.mkdir()
        operation_root.mkdir()
        trust_root.mkdir(mode=0o700)
        python3 = Path("/usr/bin/python3")
        command([str(python3), "-m", "venv", "--copies", str(runtime_root)])
        venv_python = runtime_root / "bin/python"
        command([str(venv_python), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "-r", str(REQUIREMENTS)])
        command([str(venv_python), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "typing_extensions"])
        copy_controller(controller_root, source_commit)
        os.chown(generation_root, 0, 0)
        os.chown(operation_root, 0, 0)
        os.chmod(generation_root, 0o755)
        os.chmod(operation_root, 0o755)

        CONFIG_ROOT.mkdir(mode=0o755)
        config_created = True
        os.chown(CONFIG_ROOT, 0, 0)
        os.chmod(CONFIG_ROOT, 0o755)
        controller_id = "rq03f-c2-synthetic-controller"
        build_payload, build_raw, site_packages = build_inventory(
            controller_root, runtime_root, BUILD_PATH, controller_id)
        build_sha = sha_bytes(build_raw)
        (CONFIG_ROOT / "os-package-manifest.txt").write_text("synthetic hosted package evidence only\n", encoding="utf-8")
        (CONFIG_ROOT / "shared-libraries-manifest.txt").write_text("synthetic hosted shared-library evidence only\n", encoding="utf-8")
        package_sha = sha_bytes((CONFIG_ROOT / "os-package-manifest.txt").read_bytes())
        libraries_sha = sha_bytes((CONFIG_ROOT / "shared-libraries-manifest.txt").read_bytes())
        for path in (CONFIG_ROOT / "os-package-manifest.txt", CONFIG_ROOT / "shared-libraries-manifest.txt"):
            os.chown(path, 0, 0)
            os.chmod(path, 0o444)
        sys.path.insert(0, str(ROOT / "tools" / "rq03f_c1"))
        import runtime_closure
        os_release = Path("/usr/lib/os-release") if Path("/usr/lib/os-release").is_file() else Path("/etc/os-release")
        closure = runtime_closure.capture(
            source_commit=source_commit,
            inventory_sha256=build_sha,
            base_image_digest_claim="sha256:" + "0" * 64,
            os_release=os_release,
            python_executable=venv_python,
            runtime_root=runtime_root,
            os_package_manifest=CONFIG_ROOT / "os-package-manifest.txt",
            os_package_manifest_sha256=package_sha,
            shared_libraries_manifest=CONFIG_ROOT / "shared-libraries-manifest.txt",
            shared_libraries_manifest_sha256=libraries_sha,
            protected_trust_root=trust_root,
            output=RUNTIME_CLOSURE_PATH,
        )
        now = datetime.now(timezone.utc)
        profile, profile_raw, index, index_raw, auth_files = profile_and_index(
            identities, controller_id, "fixed-operator-launcher", "1.0", build_sha, trust_root, now)
        profile_path = trust_root / "authority-profile.json"
        index_path = trust_root / "operation-index.json"
        write_new(profile_path, profile_raw, 0o600)
        write_new(index_path, index_raw, 0o600)
        for key, raw in auth_files.items():
            write_new(trust_root / f"{key}.json", raw, 0o600)
        for key, raw in (("operator-reference", b"synthetic operator reference\n"),
                         ("ingress-reference", b"synthetic ingress reference\n"),
                         ("evidence-repository-reference", b"synthetic evidence repository reference\n")):
            write_new(trust_root / f"{key}.txt", raw, 0o600)
        # Precreate the run file, then use the shared builder for every exact
        # module/schema/Build/Profile/Index and role authorization path binding.
        run_file = operation_root / "preflight-input.json"
        write_new(run_file, b'{"purpose":"preflight"}\n', 0o444)
        inventory_entries = []
        def add_entry(key: str, path: Path, raw: bytes, storage: str = "protected_external") -> None:
            inventory_entries.append({"inventory_key": key, "path": str(path), "sha256": sha_bytes(raw), "storage_class": storage})
        add_entry("authority_profile", profile_path, profile_raw)
        add_entry("operation_index", index_path, index_raw)
        add_entry("controller_build_inventory", BUILD_PATH, build_raw)
        for key, raw in (("operator-reference", b"synthetic operator reference\n"),
                         ("ingress-reference", b"synthetic ingress reference\n"),
                         ("evidence-repository-reference", b"synthetic evidence repository reference\n")):
            add_entry(key, trust_root / f"{key}.txt", raw)
        for key, raw in auth_files.items():
            add_entry(key, trust_root / f"{key}.json", raw)
        for component in build_payload["components"]:
            key = component.get("inventory_key")
            if key:
                path = Path(component["runtime_path"])
                add_entry(key, path, path.read_bytes())
        add_entry("preflight_input", run_file, run_file.read_bytes(), "run")
        inventory_payload = {"inventory_version": "1.0", "entries": inventory_entries}
        inventory_raw = canonical(inventory_payload)
        write_new(DEPENDENCY_INVENTORY_PATH, inventory_raw, 0o444)
        os.chown(trust_root, operator["uid"], operator["gid"])
        set_tree_owner(trust_root, operator["uid"], operator["gid"], files_mode=0o600, dirs_mode=0o700)
        set_root_readonly(controller_root)
        set_root_readonly(runtime_root)
        for path in (RUNTIME_CLOSURE_PATH, DEPENDENCY_INVENTORY_PATH, BUILD_PATH):
            os.chown(path, 0, 0)
            os.chmod(path, 0o444)
        for path in (CONFIG_ROOT / "os-package-manifest.txt", CONFIG_ROOT / "shared-libraries-manifest.txt"):
            os.chown(path, 0, 0)
            os.chmod(path, 0o444)

        policy, policy_raw, pin, pin_raw = build_policy(
            identities, generation_root, controller_root, runtime_root, venv_python,
            BUILD_PATH, build_sha, profile_path, sha_bytes(profile_raw), index_path,
            sha_bytes(index_raw), RUNTIME_CLOSURE_PATH, closure["evidence_sha256"],
            package_sha, libraries_sha, DEPENDENCY_INVENTORY_PATH, sha_bytes(inventory_raw), trust_root,
            source_commit,
        )
        write_new(POLICY_PATH, policy_raw, 0o444)
        write_new(PIN_PATH, pin_raw, 0o444)
        os.chown(CONFIG_ROOT, 0, 0)
        os.chmod(CONFIG_ROOT, 0o755)

        launcher = venv_python
        launcher_path = controller_root / "scripts" / "rq03f_fixed_operator_launcher.py"
        base_cmd = [str(launcher), "-I", "-S", "-B", str(launcher_path)]
        success = identity_command(operator, base_cmd)
        if success.returncode != 0:
            fail(f"Operator fixed preflight failed: exit={success.returncode}, stdout={success.stdout[-1200:]}, stderr={success.stderr[-1200:]}")
        record = json.loads(success.stdout.strip().splitlines()[-1])
        if (record.get("status") != "preflight_pass" or record.get("protected_operation_performed") is not False
                or record.get("policy_sha256") != sha_bytes(policy_raw)
                or record.get("build_inventory_sha256") != build_sha):
            fail(f"Operator preflight output mismatch: {record}")
        evidence.append({"case": "operator-fixed-read-only-preflight", "result": "PASS",
                         "uid": operator["uid"], "gid": operator["gid"], "exit_code": success.returncode,
                         "policy_sha256": sha_bytes(policy_raw), "build_inventory_sha256": build_sha,
                         "protected_operation_performed": False})

        for role in ROLE_NAMES:
            ident = identities[role]
            id_result = identity_command(ident, ["/usr/bin/id", "-a"])
            evidence.append({"case": f"actual-identity-{role}", "uid": ident["uid"], "gid": ident["gid"],
                             "exit_code": id_result.returncode, "identity": id_result.stdout.strip()})

        # Candidate, Author, Reviewer, and Approver cannot read or mutate any
        # protected evidence or root-controlled launcher configuration.
        permission_probe = """
import errno, os, sys
protected, profile, index, build, policy, launcher = sys.argv[1:]
checks = [
 ('profile-read', lambda: open(profile, 'rb')),
 ('index-read', lambda: open(index, 'rb')),
 ('index-write', lambda: os.open(index, os.O_WRONLY)),
 ('index-unlink', lambda: os.unlink(index)),
 ('index-rename', lambda: os.rename(index, index + '.renamed')),
 ('index-forge', lambda: os.open(protected + '/forged.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)),
 ('profile-replace', lambda: os.replace(profile, profile + '.replacement')),
 ('build-replace', lambda: os.open(build, os.O_WRONLY)),
 ('policy-replace', lambda: os.open(policy, os.O_WRONLY)),
 ('controller-replace', lambda: os.open(launcher, os.O_WRONLY)),
 ('index-symlink', lambda: os.symlink(index, protected + '/index-link')),
 ('index-hardlink', lambda: os.link(index, protected + '/index-hardlink')),
]
for label, operation in checks:
 try:
  obj = operation()
  if hasattr(obj, 'close'): obj.close()
  elif isinstance(obj, int): os.close(obj)
  print(label + '=UNEXPECTED_SUCCESS')
  raise SystemExit(1)
 except PermissionError as exc:
  if exc.errno != errno.EACCES: raise
  print(label + '=EACCES')
"""
        for role in ("candidate", "author", "reviewer", "approver"):
            result = identity_command(identities[role], [str(venv_python), "-I", "-S", "-B", "-c", permission_probe,
                                                          str(trust_root), str(profile_path), str(index_path),
                                                          str(BUILD_PATH), str(POLICY_PATH), str(launcher_path)])
            if result.returncode != 0 or "UNEXPECTED_SUCCESS" in result.stdout or result.stdout.count("=EACCES") != 12:
                fail(f"{role} protected evidence denial matrix failed: {result.stdout} {result.stderr}")
            evidence.append({"case": f"protected-evidence-denials-{role}", "uid": identities[role]["uid"],
                             "exit_code": result.returncode, "denials": result.stdout.strip().splitlines()})

        # Caller-controlled arguments, environment, UID, GID groups, Linux
        # capabilities, and inherited descriptors are all rejected by the
        # fixed entrypoint before a TrustContext can be returned.
        expected_code(identity_command(operator, base_cmd + ["--entrypoint", "evil:run"]),
                      "ARGUMENTS_REFUSED", "candidate-entrypoint-argument", evidence)
        expected_code(identity_command(operator, base_cmd, env={"PYTHONPATH": str(base / "evil")}),
                      "PYTHON_ENV_REFUSED", "malicious-pythonpath", evidence)
        marker = base / "sitecustomize-marker"
        evil = base / "evil"
        evil.mkdir()
        (evil / "sitecustomize.py").write_text(f"from pathlib import Path; Path({str(marker)!r}).write_text('executed')\n", encoding="utf-8")
        expected_code(identity_command(operator, base_cmd, env={"PYTHONPATH": str(evil)}),
                      "PYTHON_ENV_REFUSED", "sitecustomize-shadow-attempt", evidence)
        if marker.exists():
            fail("malicious sitecustomize.py executed")
        expected_code(identity_command(identities["candidate"], base_cmd),
                      "PROCESS_IDENTITY", "candidate-cannot-launch-as-operator", evidence)
        expected_code(identity_command(operator, base_cmd, supplementary=(extra_gid,)),
                      "SUPPLEMENTARY_GROUPS", "extra-supplementary-group", evidence)
        expected_code(identity_command(operator, base_cmd, bounding="+dac_override"),
                      "CAPABILITIES", "unexpected-capability-bounding-set", evidence)
        fd = os.open(POLICY_PATH, os.O_RDONLY)
        try:
            expected_code(identity_command(operator, base_cmd, pass_fds=(fd,)),
                          "INHERITED_FD", "inherited-policy-descriptor", evidence)
        finally:
            os.close(fd)

        # The independent Pin and Launch Policy must be safely read before any
        # Policy-selected Python validator is loaded.
        for source, label in ((PIN_PATH, "pin"), (POLICY_PATH, "policy")):
            backup_path = source.with_name(source.name + ".c2-symlink-backup")
            os.replace(source, backup_path)
            try:
                os.symlink(backup_path, source)
                expected_code(identity_command(operator, base_cmd), "BOOTSTRAP_PATH",
                              f"{label}-symlink-rejected-before-code-load", evidence)
            finally:
                source.unlink(missing_ok=True)
                os.replace(backup_path, source)
                os.chown(source, 0, 0)
                os.chmod(source, 0o444)

        untrusted_build_path = operation_root / "candidate-controlled-build.json"
        write_new(untrusted_build_path, b'{"candidate":"untrusted"}\n', 0o600)
        os.chown(untrusted_build_path, identities["candidate"]["uid"], identities["candidate"]["gid"])
        old = rebind_config(policy, pin, update_policy=lambda p: p["controller"]["build_inventory"].update(
            path=str(untrusted_build_path), sha256=sha_bytes(untrusted_build_path.read_bytes())))
        try:
            expected_code(identity_command(operator, base_cmd), "BOOTSTRAP_PATH",
                          "candidate-controlled-build-path-rejected-before-code-load", evidence)
        finally:
            restore_config(*old, operator)
            untrusted_build_path.unlink()

        # Root changes only synthetic files to simulate policy/profile/index
        # drift. Each run must stop, and the exact original bytes are restored.
        original_policy, original_pin = POLICY_PATH.read_bytes(), PIN_PATH.read_bytes()
        original_profile, original_index = profile_path.read_bytes(), index_path.read_bytes()
        try:
            write_replace(POLICY_PATH, original_policy + b" ", mode=0o444)
            expected_code(identity_command(operator, base_cmd), "POLICY_PIN_MISMATCH", "policy-file-replacement", evidence)
        finally:
            write_replace(POLICY_PATH, original_policy, mode=0o444)

        try:
            changed_policy = json.loads(original_policy)
            changed_policy["controller"]["build_inventory"]["sha256"] = "f" * 64
            changed_policy_raw = canonical(changed_policy)
            changed_pin = json.loads(original_pin)
            changed_pin["policy_sha256"] = sha_bytes(changed_policy_raw)
            write_replace(POLICY_PATH, changed_policy_raw, mode=0o444)
            write_replace(PIN_PATH, canonical(changed_pin), mode=0o444)
            expected_code(identity_command(operator, base_cmd), "BUILD_INVENTORY_SHA", "wrong-build-inventory-sha", evidence)
        finally:
            write_replace(POLICY_PATH, original_policy, mode=0o444)
            write_replace(PIN_PATH, original_pin, mode=0o444)

        profile_mutations = [
            ("profile-epoch-change", lambda p: p.update(policy_epoch=2), "AUTHORITY_REVALIDATION"),
            ("role-revocation", lambda p: (p["revoked_authority_ids"].append(p["roles"][0]["principal_id"],),
                                            p["roles"][0].update(revoked_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                                                 revocation_reason="synthetic revocation")), "AUTHORITY_REVALIDATION"),
            ("expired-role", lambda p: p["roles"][0].update(valid_from="1999-01-01T00:00:00Z", valid_until="2000-01-01T00:00:00Z"), "AUTHORITY_REVALIDATION"),
        ]
        for label, mutate, code in profile_mutations:
            profile_value = json.loads(original_profile)
            mutate(profile_value)
            old = rebind_config(policy, pin, profile=profile_value)
            try:
                expected_code(identity_command(operator, base_cmd), code, label, evidence)
            finally:
                restore_config(*old, operator)

        def wrong_gid_policy(current: dict[str, Any]) -> None:
            current["identities"]["operator"]["gid"] = 60001
        old = rebind_config(policy, pin, update_policy=wrong_gid_policy)
        try:
            expected_code(identity_command(operator, base_cmd), "PROCESS_IDENTITY", "wrong-pinned-operator-gid", evidence)
        finally:
            restore_config(*old, operator)

        # A valid synthetic Index append is accepted only within the process
        # lifetime; a changed startup snapshot, unsupported version, or rollback
        # is rejected because C2 lacks a cross-restart C3 high-water ledger.
        index_v1 = json.loads(original_index)
        index_v1["index_version"] = "1.0"
        old = rebind_config(policy, pin, index=index_v1)
        try:
            expected_code(identity_command(operator, base_cmd), "INDEX_APPEND_ONLY", "index-version-drift", evidence)
        finally:
            restore_config(*old, operator)

        # Hardlink and symlink authority-file substitutions fail before parsing.
        backup = profile_path.with_name("authority-profile.backup.json")
        os.replace(profile_path, backup)
        try:
            os.symlink(backup, profile_path)
            expected_code(identity_command(operator, base_cmd), "PATH_SYMLINK", "profile-symlink", evidence)
        finally:
            profile_path.unlink(missing_ok=True)
            os.replace(backup, profile_path)
            os.chown(profile_path, operator["uid"], operator["gid"])
            os.chmod(profile_path, 0o600)
        hardlink = profile_path.with_name("authority-profile-hardlink.json")
        os.link(profile_path, hardlink)
        try:
            expected_code(identity_command(operator, base_cmd), "PATH_HARDLINK", "profile-hardlink", evidence)
        finally:
            hardlink.unlink()

        # Modify a non-entrypoint controller module and the runtime in turn;
        # full C1 Bootstrap and Runtime Closure re-hashes must block both.
        drift_path = controller_root / "scripts" / "lifecycle_digest.py"
        original_bytes = drift_path.read_bytes()
        drift_path.write_bytes(original_bytes + b"\n# C2 synthetic drift\n")
        try:
            expected_code(identity_command(operator, base_cmd), "PREFLIGHT_BLOCKED", "controller-byte-drift", evidence)
        finally:
            drift_path.write_bytes(original_bytes)
            os.chown(drift_path, 0, 0)
            os.chmod(drift_path, 0o444)
        runtime_file = next(path for path in (runtime_root / "lib").rglob("validators.py")
                            if "jsonschema" in path.parts)
        runtime_original = runtime_file.read_bytes()
        runtime_file.write_bytes(runtime_original + b"\n# C2 synthetic runtime drift\n")
        try:
            expected_code(identity_command(operator, base_cmd), "PREFLIGHT_BLOCKED", "runtime-byte-drift", evidence)
        finally:
            runtime_file.write_bytes(runtime_original)
            os.chown(runtime_file, 0, 0)
            os.chmod(runtime_file, 0o444)

        # No C2 operation may authorize an Intake, authoring, Teacher, PA, or
        # Generation write. The systemd unit is verified only in a temporary
        # systemd root and never installed/enabled/started.
        unit_root = setup_systemd_verify_root(base, identities)
        verify_root = unit_root.parents[4]
        verify = command(["/usr/bin/systemd-analyze", "--man=no", "verify", "--root", str(verify_root),
                          "/usr/lib/systemd/system/rq03f-operator-preflight.service"], check=False)
        evidence.append({"case": "systemd-analyze-verify", "exit_code": verify.returncode,
                         "stdout": verify.stdout[-2000:], "stderr": verify.stderr[-2000:],
                         "unit_installed": False, "unit_enabled": False, "unit_started": False})
        if verify.returncode != 0:
            fail(f"systemd-analyze verify failed: {verify.stderr[-1600:]}")

        event = {
            "result": "HOSTED_OS_ISOLATION_PASS",
            "authority_status": "synthetic_candidate_only",
            "operator_uid": operator["uid"], "operator_gid": operator["gid"],
            "non_operator_identities": {role: {"uid": identities[role]["uid"], "gid": identities[role]["gid"]}
                                         for role in ROLE_NAMES if role != "operator"},
            "build_inventory_sha256": build_sha,
            "launch_policy_sha256": sha_bytes(policy_raw),
            "runtime_closure_authority_status": "candidate_only_unverified_host_claims",
            "production_trust_established": False,
            "c3_anti_rollback_gate": "MISSING; protected production writes fail closed",
            "systemd_service_installed_or_started": False,
            "tests": evidence,
        }
        print(json.dumps(event, sort_keys=True, ensure_ascii=False, indent=2))
        return 0
    except BaseException as exc:
        failure = exc
        raise
    finally:
        cleanup_errors: list[str] = []
        for user in reversed(created_users):
            result = subprocess.run(["/usr/sbin/userdel", "--remove", "--", user], capture_output=True, text=True)
            if result.returncode not in (0, 6):
                cleanup_errors.append(f"userdel {user}: {result.stderr.strip()}")
        for group in reversed(created_groups):
            result = subprocess.run(["/usr/sbin/groupdel", "--", group], capture_output=True, text=True)
            if result.returncode not in (0, 6):
                cleanup_errors.append(f"groupdel {group}: {result.stderr.strip()}")
        if base is not None:
            try:
                shutil.rmtree(base)
            except OSError as exc:
                cleanup_errors.append(f"remove test generation: {exc}")
        if config_created and CONFIG_ROOT.exists():
            try:
                shutil.rmtree(CONFIG_ROOT)
            except OSError as exc:
                cleanup_errors.append(f"remove synthetic /etc/rq03f: {exc}")
        if cleanup_errors:
            print("C2 cleanup failures: " + "; ".join(cleanup_errors), file=sys.stderr)
            if failure is None:
                fail("temporary C2 identities or trust paths were not cleaned")


if __name__ == "__main__":
    raise SystemExit(main())
