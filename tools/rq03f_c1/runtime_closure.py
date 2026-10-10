#!/usr/bin/env python3
"""Capture/check a separate, explicitly untrusted OS/Python runtime evidence sidecar."""

from __future__ import annotations

import argparse
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


class RuntimeEvidenceError(ValueError):
    """External runtime evidence is missing, malformed, or no longer matches bytes."""


_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_FIELDS = {
    "schema_version", "authority_status", "target_platform", "source_commit",
    "build_inventory_sha256", "base_image_digest_claim", "os_release_path",
    "os_release_sha256", "python_executable", "python_version", "python_stdlib_root",
    "python_stdlib_tree_sha256", "runtime_root", "runtime_root_tree_sha256",
    "os_package_manifest_path", "os_package_manifest_sha256",
    "shared_libraries_manifest_path", "shared_libraries_manifest_sha256",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeEvidenceError(message)


def _absolute(raw: str, label: str) -> Path:
    _require(isinstance(raw, str) and raw.startswith("/") and "\x00" not in raw
             and "\\" not in raw and "//" not in raw and os.path.normpath(raw) == raw,
             f"{label} must be a canonical absolute path")
    _require(all(part not in {".", ".."} for part in raw.split("/")),
             f"{label} contains path traversal")
    return Path(raw)


def _ordinary(path: Path, *, directory: bool = False) -> None:
    _require(path.is_absolute() and os.path.normpath(str(path)) == str(path),
             f"non-canonical path: {path}")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        _require(not stat.S_ISLNK(info.st_mode), f"symlink path refused: {current}")
    info = path.lstat()
    _require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
             f"unexpected file type: {path}")
    if not directory:
        _require(info.st_nlink == 1, f"hard-linked runtime evidence file refused: {path}")
    _require(info.st_mode & 0o022 == 0, f"group/world-writable runtime path refused: {path}")
    _require(str(path.resolve(strict=True)) == str(path), f"path alias refused: {path}")


def _path_overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _secure_parent(path: Path) -> int:
    uid, gid = os.geteuid(), os.getegid()
    _require(uid != 0, "runtime candidate capture must run as a non-root identity")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
            info = os.fstat(fd)
            _require(info.st_uid in {0, uid} and info.st_mode & 0o022 == 0,
                     f"runtime evidence output parent is not protected: {path}")
            if info.st_uid == uid:
                _require(info.st_gid == gid, f"runtime evidence output parent GID mismatch: {path}")
            try:
                xattrs = os.listxattr(fd)
            except OSError as exc:
                raise RuntimeEvidenceError(f"cannot inspect runtime evidence output ACL: {exc}") from exc
            _require(not ({"system.posix_acl_access", "system.posix_acl_default"} & set(xattrs)),
                     f"runtime evidence output parent has ACL: {path}")
        _require(os.readlink(f"/proc/self/fd/{fd}") == str(path),
                 "runtime evidence output parent changed during validation")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file_sha(path: Path) -> str:
    _ordinary(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha(root: Path, *, excluded_roots: tuple[Path, ...] = ()) -> str:
    _ordinary(root, directory=True)
    rows: list[tuple[str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        directories[:] = sorted(directories)
        directories[:] = [
            name for name in directories
            if not any((base / name) == excluded or (base / name).is_relative_to(excluded)
                       for excluded in excluded_roots)
        ]
        for name in directories:
            info = (base / name).lstat()
            _require(stat.S_ISDIR(info.st_mode), f"symlink/special runtime directory: {base / name}")
        for name in sorted(files):
            path = base / name
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode), f"symlink/special runtime file: {path}")
            rows.append((path.relative_to(root).as_posix(), _file_sha(path)))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                        allow_nan=False) + "\n").encode("utf-8")


def _python_properties(executable: Path) -> tuple[str, Path, tuple[Path, ...]]:
    _ordinary(executable)
    _require(os.access(executable, os.X_OK), "Python executable is not executable")
    code = ("import json,sys,sysconfig; p=sysconfig.get_paths(); "
            "print(json.dumps({'version':sys.version.split()[0],'stdlib':p['stdlib'],"
            "'site_paths':[p.get('purelib'),p.get('platlib')]}))")
    try:
        result = subprocess.run([str(executable), "-I", "-S", "-B", "-c", code],
                                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                                check=True, capture_output=True, text=True, timeout=15)
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise RuntimeEvidenceError(f"isolated Python runtime query failed: {exc}") from exc
    stdlib = _absolute(payload["stdlib"], "Python stdlib root")
    site_paths = tuple(
        path for raw in payload["site_paths"] if raw
        for path in (_absolute(raw, "Python site-packages path"),)
        if path == stdlib or path.is_relative_to(stdlib)
    )
    return payload["version"], stdlib, site_paths


def capture(*, source_commit: str, inventory_sha256: str, base_image_digest_claim: str,
            os_release: Path, python_executable: Path, runtime_root: Path,
            os_package_manifest: Path, os_package_manifest_sha256: str,
            shared_libraries_manifest: Path, shared_libraries_manifest_sha256: str,
            protected_trust_root: Path, output: Path) -> dict[str, Any]:
    _require(_COMMIT.fullmatch(source_commit or "") is not None, "invalid source commit pin")
    _require(_SHA.fullmatch(inventory_sha256 or "") is not None, "invalid Build Inventory SHA pin")
    _require(_DIGEST.fullmatch(base_image_digest_claim or "") is not None,
             "base image must be a literal sha256 digest claim")
    _require(_SHA.fullmatch(os_package_manifest_sha256 or "") is not None
             and _SHA.fullmatch(shared_libraries_manifest_sha256 or "") is not None,
             "external package/library manifest SHA pins are required")
    _ordinary(os_release)
    _ordinary(runtime_root, directory=True)
    _ordinary(os_package_manifest)
    _ordinary(shared_libraries_manifest)
    _ordinary(python_executable)
    _ordinary(protected_trust_root, directory=True)
    _require(not _path_overlaps(output, protected_trust_root),
             "runtime candidate evidence output overlaps protected Trust Anchor path")
    python_version, stdlib_root, site_paths = _python_properties(python_executable)
    _ordinary(stdlib_root, directory=True)
    package_sha = _file_sha(os_package_manifest)
    library_sha = _file_sha(shared_libraries_manifest)
    _require(package_sha == os_package_manifest_sha256, "OS package manifest raw SHA mismatch")
    _require(library_sha == shared_libraries_manifest_sha256, "shared libraries manifest raw SHA mismatch")
    evidence = {
        "schema_version": "rq03f-runtime-closure-candidate-1.0",
        "authority_status": "candidate_only_unverified_host_claims",
        "target_platform": f"{platform.system().lower()}-{platform.machine().lower()}",
        "source_commit": source_commit,
        "build_inventory_sha256": inventory_sha256,
        "base_image_digest_claim": base_image_digest_claim,
        "os_release_path": str(os_release),
        "os_release_sha256": _file_sha(os_release),
        "python_executable": str(python_executable),
        "python_version": python_version,
        "python_stdlib_root": str(stdlib_root),
        "python_stdlib_tree_sha256": _tree_sha(stdlib_root, excluded_roots=site_paths),
        "runtime_root": str(runtime_root),
        "runtime_root_tree_sha256": _tree_sha(runtime_root),
        "os_package_manifest_path": str(os_package_manifest),
        "os_package_manifest_sha256": package_sha,
        "shared_libraries_manifest_path": str(shared_libraries_manifest),
        "shared_libraries_manifest_sha256": library_sha,
    }
    raw = _canonical_bytes(evidence)
    parent_fd = _secure_parent(output.parent)
    try:
        fd = os.open(output.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
        try:
            view = memoryview(raw)
            offset = 0
            while offset < len(view):
                size = os.write(fd, view[offset:])
                _require(size > 0, "short runtime evidence write")
                offset += size
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return {"evidence": evidence, "evidence_sha256": hashlib.sha256(raw).hexdigest()}


def verify(evidence_path: Path, expected_sha256: str, *, expected_base_image_digest: str,
           expected_package_manifest_sha256: str,
           expected_shared_libraries_manifest_sha256: str,
           protected_trust_root: Path) -> dict[str, Any]:
    _require(_SHA.fullmatch(expected_sha256 or "") is not None, "external evidence SHA pin is required")
    _ordinary(evidence_path)
    _ordinary(protected_trust_root, directory=True)
    _require(not _path_overlaps(evidence_path, protected_trust_root),
             "runtime evidence path overlaps protected Trust Anchor")
    raw = evidence_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    _require(actual == expected_sha256, "runtime evidence raw SHA mismatch")
    try:
        evidence = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeEvidenceError(f"invalid runtime evidence JSON: {exc}") from exc
    _require(isinstance(evidence, dict) and set(evidence) == _FIELDS,
             "runtime evidence has missing or unknown fields")
    _require(evidence["schema_version"] == "rq03f-runtime-closure-candidate-1.0"
             and evidence["authority_status"] == "candidate_only_unverified_host_claims",
             "unsupported runtime evidence version/status")
    _require(evidence["base_image_digest_claim"] == expected_base_image_digest
             and evidence["os_package_manifest_sha256"] == expected_package_manifest_sha256
             and evidence["shared_libraries_manifest_sha256"] == expected_shared_libraries_manifest_sha256,
             "runtime evidence claims do not match separately delivered expected pins")
    for field in ("os_release_path", "python_executable", "python_stdlib_root", "runtime_root",
                  "os_package_manifest_path", "shared_libraries_manifest_path"):
        evidence[field] = _absolute(evidence[field], field)
    _require(_file_sha(evidence["os_release_path"]) == evidence["os_release_sha256"],
             "os-release bytes changed")
    _require(_file_sha(evidence["os_package_manifest_path"]) == evidence["os_package_manifest_sha256"],
             "OS package manifest bytes changed")
    _require(_file_sha(evidence["shared_libraries_manifest_path"])
             == evidence["shared_libraries_manifest_sha256"], "shared-library manifest bytes changed")
    version, stdlib, site_paths = _python_properties(evidence["python_executable"])
    _require(version == evidence["python_version"] and stdlib == evidence["python_stdlib_root"],
             "Python executable, version, or standard-library path changed")
    _require(_tree_sha(stdlib, excluded_roots=site_paths) == evidence["python_stdlib_tree_sha256"],
             "Python stdlib tree changed")
    _require(_tree_sha(evidence["runtime_root"]) == evidence["runtime_root_tree_sha256"],
             "final Runtime Root tree changed")
    return {"verification_status": "PASS_CANDIDATE_BYTES_ONLY",
            "authority_status": evidence["authority_status"], "evidence_sha256": actual,
            "base_image_digest_claim": evidence["base_image_digest_claim"],
            "target_platform": evidence["target_platform"]}


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--source-commit", required=True)
    cap.add_argument("--inventory-sha256", required=True)
    cap.add_argument("--base-image-digest-claim", required=True)
    cap.add_argument("--os-release", required=True, type=Path)
    cap.add_argument("--python-executable", required=True, type=Path)
    cap.add_argument("--runtime-root", required=True, type=Path)
    cap.add_argument("--os-package-manifest", required=True, type=Path)
    cap.add_argument("--os-package-manifest-sha256", required=True)
    cap.add_argument("--shared-libraries-manifest", required=True, type=Path)
    cap.add_argument("--shared-libraries-manifest-sha256", required=True)
    cap.add_argument("--protected-trust-root", required=True, type=Path)
    cap.add_argument("--output", required=True, type=Path)
    ver = sub.add_parser("verify")
    ver.add_argument("--evidence", required=True, type=Path)
    ver.add_argument("--expected-sha256", required=True)
    ver.add_argument("--expected-base-image-digest", required=True)
    ver.add_argument("--expected-package-manifest-sha256", required=True)
    ver.add_argument("--expected-shared-libraries-manifest-sha256", required=True)
    ver.add_argument("--protected-trust-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "capture":
        result = capture(source_commit=args.source_commit, inventory_sha256=args.inventory_sha256,
                         base_image_digest_claim=args.base_image_digest_claim, os_release=args.os_release,
                         python_executable=args.python_executable, runtime_root=args.runtime_root,
                         os_package_manifest=args.os_package_manifest,
                         os_package_manifest_sha256=args.os_package_manifest_sha256,
                         shared_libraries_manifest=args.shared_libraries_manifest,
                         shared_libraries_manifest_sha256=args.shared_libraries_manifest_sha256,
                         protected_trust_root=args.protected_trust_root, output=args.output)
        print(json.dumps({"evidence_sha256": result["evidence_sha256"], **result["evidence"]},
                         sort_keys=True, separators=(",", ":")))
    else:
        result = verify(args.evidence, args.expected_sha256,
                        expected_base_image_digest=args.expected_base_image_digest,
                        expected_package_manifest_sha256=args.expected_package_manifest_sha256,
                        expected_shared_libraries_manifest_sha256=args.expected_shared_libraries_manifest_sha256,
                        protected_trust_root=args.protected_trust_root)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except RuntimeEvidenceError as exc:
        print(f"BLOCKED — {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
