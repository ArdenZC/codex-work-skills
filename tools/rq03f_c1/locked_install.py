#!/usr/bin/env python3
"""Install trusted Controller source and a fully hash-locked offline runtime.

All target directories must be fresh, empty, and already allocated by the
separate exclusive allocator. Failures leave an incomplete candidate in place;
this tool never cleans up, overwrites, repairs, or reuses it.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

try:
    from . import build_inventory as build
    from . import operator_allocator as allocator
except ImportError:  # Direct script execution from its installed path.
    import build_inventory as build
    import operator_allocator as allocator


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise build.BuildError(message)


def _fresh_allocated_directory(path: Path) -> int:
    info = build._safe_path(path, directory=True)
    _require(info.st_uid == os.geteuid() and info.st_gid == os.getegid(),
             f"preallocated output directory owner differs from current Operator: {path}")
    _require(stat.S_IMODE(info.st_mode) == 0o700, f"preallocated output directory must be mode 0700: {path}")
    parent_fd, _ = allocator._open_directory_chain(str(path.parent), os.geteuid(), os.getegid())
    try:
        parent_info = os.fstat(parent_fd)
        target_fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                            dir_fd=parent_fd)
        target_info = os.fstat(target_fd)
        _require((target_info.st_dev, target_info.st_ino) == (info.st_dev, info.st_ino),
                 f"preallocated directory changed during validation: {path}")
        _require(parent_info.st_uid in {0, os.geteuid()} and parent_info.st_mode & 0o022 == 0,
                 f"preallocated directory parent is writable by another role: {path.parent}")
        fd = target_fd
        try:
            xattrs = os.listxattr(fd)
        except OSError as exc:
            raise build.BuildError(f"cannot inspect output directory ACL: {exc}") from exc
        _require(not ({"system.posix_acl_access", "system.posix_acl_default"} & set(xattrs)),
                 f"preallocated output directory has a POSIX ACL: {path}")
        _require(not any(path.iterdir()), f"preallocated output directory is not empty: {path}")
        return fd
    except BaseException:
        try:
            os.close(fd)
        except UnboundLocalError:
            pass
        raise
    finally:
        os.close(parent_fd)


def _write_file_at(root_fd: int, relative: str, content: bytes) -> None:
    parts = relative.split("/")
    current_fd = os.dup(root_fd)
    opened_dirs: list[int] = [current_fd]
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=current_fd)
            except FileExistsError:
                # The only allowed existing directories are ones this installer
                # created earlier while copying another file in this same tree.
                pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                              dir_fd=current_fd)
            info = os.fstat(next_fd)
            _require(info.st_uid == os.geteuid() and info.st_gid == os.getegid()
                     and stat.S_IMODE(info.st_mode) == 0o700,
                     f"Controller staging directory identity mismatch: {part}")
            current_fd = next_fd
            opened_dirs.append(next_fd)
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                     0o600, dir_fd=current_fd)
        try:
            view = memoryview(content)
            offset = 0
            while offset < len(view):
                amount = os.write(fd, view[offset:])
                _require(amount > 0, f"short Controller install write: {relative}")
                offset += amount
            os.fsync(fd)
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                     f"Controller install file identity mismatch: {relative}")
            os.fchmod(fd, 0o444)
        finally:
            os.close(fd)
    finally:
        for fd in reversed(opened_dirs):
            os.close(fd)


def _create_directory_at(root_fd: int, relative: str) -> None:
    parts = relative.split("/")
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            os.mkdir(part, 0o700, dir_fd=current_fd)
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                              dir_fd=current_fd)
            info = os.fstat(next_fd)
            _require(info.st_uid == os.geteuid() and info.st_gid == os.getegid()
                     and stat.S_IMODE(info.st_mode) == 0o700,
                     f"new Runtime directory identity mismatch: {relative}")
            os.close(current_fd)
            current_fd = next_fd
    finally:
        os.close(current_fd)


def _freeze_tree(root: Path, *, executable_paths: set[Path] | None = None) -> None:
    executable_paths = executable_paths or set()
    directories: list[Path] = []
    for current, names, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in names:
            path = current_path / name
            info = path.lstat()
            _require(stat.S_ISDIR(info.st_mode), f"symlink/special directory in install: {path}")
            directories.append(path)
        for name in files:
            path = current_path / name
            info = path.lstat()
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                     f"symlink/hardlink/special file in install: {path}")
            _require(path.suffix.casefold() not in {".pyc", ".pyo"}
                     and "__pycache__" not in path.parts,
                     f"bytecode cache in candidate install: {path}")
            mode = 0o555 if path in executable_paths or info.st_mode & 0o111 else 0o444
            os.chmod(path, mode, follow_symlinks=False)
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        os.chmod(path, 0o555, follow_symlinks=False)
    os.chmod(root, 0o555, follow_symlinks=False)


def install_controller(plan_path: Path, expected_plan_sha256: str) -> dict[str, str]:
    _require(os.geteuid() != 0, "Controller installation must run as the non-root deployment Operator")
    plan, plan_sha = build._load_plan(plan_path, expected_plan_sha256)
    build._verify_source_checkout(plan)
    build._requirements_and_wheelhouse(plan)
    root_fd = _fresh_allocated_directory(plan["controller_root"])
    try:
        tracked = build._tracked_controller_files(plan)
        for relative, object_id in sorted(tracked.items()):
            result = subprocess.run(
                ["/usr/bin/git", "-C", str(plan["source_checkout"]), "-c", "core.fsmonitor=false",
                 "-c", "core.hooksPath=/dev/null", "cat-file", "blob", object_id],
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1",
                     "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"},
                check=True, capture_output=True, timeout=30,
            )
            _write_file_at(root_fd, relative, result.stdout)
        _require((plan["controller_root"] / "scripts").is_dir()
                 and (plan["controller_root"] / "schemas").is_dir(),
                 "pinned Controller source lacks scripts/ or schemas/")
        _freeze_tree(plan["controller_root"])
        return {"install_status": "CANDIDATE_CONTROLLER_INSTALLED",
                "source_commit": plan["source_commit"], "controller_root": str(plan["controller_root"]),
                "build_plan_sha256": plan_sha}
    finally:
        os.close(root_fd)


def prepare_install_roots(plan_path: Path, expected_plan_sha256: str) -> dict[str, str]:
    """Create the two fixed final roots once beneath an allocated Generation."""
    _require(os.geteuid() != 0, "install-root allocation must run as the non-root deployment Operator")
    plan, plan_sha = build._load_plan(plan_path, expected_plan_sha256)
    build._verify_source_checkout(plan)
    _lock_text, _wheelhouse = build._requirements_and_wheelhouse(plan)
    generation_fd, _ = allocator._open_directory_chain(
        str(plan["generation_root"]), plan["operator_uid"], plan["operator_gid"]
    )
    try:
        generation_stat = os.fstat(generation_fd)
        _require(generation_stat.st_uid == plan["operator_uid"]
                 and generation_stat.st_gid == plan["operator_gid"]
                 and stat.S_IMODE(generation_stat.st_mode) == 0o700,
                 "Generation root identity differs from independent allocation record")
        try:
            xattrs = os.listxattr(generation_fd)
        except OSError as exc:
            raise build.BuildError(f"cannot inspect Generation root ACL: {exc}") from exc
        _require(not ({"system.posix_acl_access", "system.posix_acl_default"} & set(xattrs)),
                 "Generation root has a POSIX ACL")
        record = json.loads(plan["allocation_record_path"].read_text(encoding="utf-8"))
        _require((generation_stat.st_dev, generation_stat.st_ino)
                 == (record["target"]["device"], record["target"]["inode"]),
                 "Generation inode/device differs from exclusive allocation receipt")
        created: list[Path] = []
        for leaf, final_path in (("controller", plan["controller_root"]), ("runtime", plan["runtime_root"])):
            os.mkdir(leaf, 0o700, dir_fd=generation_fd)
            fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                         dir_fd=generation_fd)
            try:
                info = os.fstat(fd)
                _require(info.st_uid == plan["operator_uid"] and info.st_gid == plan["operator_gid"]
                         and stat.S_IMODE(info.st_mode) == 0o700,
                         f"new install root identity mismatch: {leaf}")
            finally:
                os.close(fd)
            created.append(final_path)
        os.fsync(generation_fd)
        return {"install_roots_status": "CANDIDATE_ROOTS_EXCLUSIVELY_CREATED",
                "generation_id": plan["generation_id"], "generation_root": str(plan["generation_root"]),
                "controller_root": str(created[0]), "runtime_root": str(created[1]),
                "allocation_record_sha256": plan["allocation_record_sha256"],
                "build_plan_sha256": plan_sha}
    finally:
        os.close(generation_fd)


def install_runtime(plan_path: Path, expected_plan_sha256: str) -> dict[str, str]:
    _require(os.geteuid() != 0, "Runtime installation must run as the non-root deployment Operator")
    plan, plan_sha = build._load_plan(plan_path, expected_plan_sha256)
    build._verify_source_checkout(plan)
    lock_text, _wheelhouse = build._requirements_and_wheelhouse(plan)
    source_python = plan["build_python_executable"]
    actual_base_version = build._python_version(source_python)
    _require(actual_base_version == plan["python_version"],
             "selected locked Python patch release does not match the Owner plan")
    _require(plan["runtime_root"].is_dir(), "Runtime Root must be preallocated before installation")
    root_fd = _fresh_allocated_directory(plan["runtime_root"])
    try:
        major_minor = ".".join(plan["python_version"].split(".")[:2])
        expected_python = plan["runtime_root"] / "bin" / f"python{major_minor}"
        expected_site = plan["runtime_root"] / "lib" / f"python{major_minor}" / "site-packages"
        _require(plan["python_executable"] == expected_python and plan["site_packages_root"] == expected_site,
                 "final Python/site-packages absolute paths differ from the canonical venv layout")
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PYTHONNOUSERSITE": "1",
               "PIP_CONFIG_FILE": "/dev/null", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
               "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            _create_directory_at(root_fd, "bin")
            _create_directory_at(root_fd, f"lib/python{major_minor}/site-packages")
            source_bytes = source_python.read_bytes()
            _write_file_at(root_fd, f"bin/python{major_minor}", source_bytes)
            os.chmod(expected_python, 0o555, follow_symlinks=False)
            pyvenv_cfg = (
                f"home = {source_python.parent}\n"
                "include-system-site-packages = false\n"
                f"version = {plan['python_version']}\n"
                f"executable = {source_python}\n"
            ).encode("utf-8")
            _write_file_at(root_fd, "pyvenv.cfg", pyvenv_cfg)
            _require(expected_python.is_file() and not expected_python.is_symlink(),
                     "Runtime did not create the exact final Python executable")
            probe = subprocess.run(
                [str(expected_python), "-I", "-B", "-c",
                 "import json,sys,sysconfig; print(json.dumps({'version':sys.version.split()[0], 'prefix':sys.prefix, 'purelib':sysconfig.get_paths()['purelib']}))"],
                env=env, check=True, capture_output=True, text=True, timeout=20,
            )
            probe_info = json.loads(probe.stdout)
            _require(probe_info["version"] == plan["python_version"]
                     and probe_info["prefix"] == str(plan["runtime_root"])
                     and probe_info["purelib"] == str(expected_site),
                     "copied Python did not bind to the exact final Runtime paths")
            pip_args = [str(source_python), "-I", "-m", "pip", "install", "--isolated",
                        "--no-index", "--only-binary=:all:", "--no-build-isolation", "--no-cache-dir",
                        "--no-compile", "--disable-pip-version-check", "--find-links", str(plan["wheelhouse_root"]),
                        "--require-hashes", "--target", str(expected_site),
                        "-r", str(plan["requirements_lock"])]
            subprocess.run(pip_args, env=env, check=True, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            raise build.BuildError(f"locked offline Runtime install failed; keep this Generation incomplete: {exc}") from exc
        _require(expected_site.is_dir(), "exact final site-packages path was not installed")
        version = build._python_version(expected_python)
        _require(version == plan["python_version"], "installed Runtime Python version differs from pin")
        build._verify_installed_distributions(plan, lock_text)
        _freeze_tree(plan["runtime_root"], executable_paths={expected_python})
        return {"install_status": "CANDIDATE_RUNTIME_INSTALLED",
                "runtime_root": str(plan["runtime_root"]), "python_executable": str(expected_python),
                "python_version": version, "site_packages_root": str(expected_site),
                "build_plan_sha256": plan_sha}
    finally:
        os.close(root_fd)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare-paths", "controller", "runtime"):
        child = sub.add_parser(name)
        child.add_argument("--plan", type=Path, required=True)
        child.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    if args.command == "prepare-paths":
        result = prepare_install_roots(args.plan, args.expected_plan_sha256)
    elif args.command == "controller":
        result = install_controller(args.plan, args.expected_plan_sha256)
    else:
        result = install_runtime(args.plan, args.expected_plan_sha256)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except build.BuildError as exc:
        print(f"BLOCKED — {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
