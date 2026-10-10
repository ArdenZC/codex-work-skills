from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
import base64
import csv
import io
import multiprocessing

from tools.rq03f_c1 import build_inventory, locked_install, operator_allocator, runtime_closure, verify_inventory


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools" / "rq03f_c1"
CONTROLLER = REPO_ROOT / "教案生成器" / "lesson-plan-docx-generator"
EXPECTED_PROFILE_SHA = "d8e2ac76552f76b5dacf1ab7e31014da68ffe757da9bff5c97d27be9b67effd4"
EXPECTED_INDEX_SHA = "52b3d01db27b10b4d9f54d6278a469ba7998a26057de93c8308b2b1fd50b67a4"


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["/usr/bin/git", "-C", str(repo), *args],
                            check=True, capture_output=True, text=True,
                            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"})
    return result.stdout.strip()


def _init_source_repo(root: Path, *, include_anchor: bool = False) -> str:
    root.mkdir(mode=0o700)
    (root / "教案生成器" / "lesson-plan-docx-generator").mkdir(parents=True, mode=0o700)
    skill = root / "教案生成器" / "lesson-plan-docx-generator"
    shutil.copytree(CONTROLLER / "scripts", skill / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    shutil.copytree(CONTROLLER / "schemas", skill / "schemas", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    if include_anchor:
        anchor = root / ".operator-trust" / "rq03-live"
        anchor.mkdir(parents=True, mode=0o700)
        (anchor / "authority-profile.json").write_bytes(b'{"synthetic":"profile"}\n')
        (anchor / "operation-index.json").write_bytes(b'{"synthetic":"index"}\n')
        (anchor / "authority-profile.json").chmod(0o444)
        (anchor / "operation-index.json").chmod(0o444)
    _run_git(root, "init", "--quiet")
    _run_git(root, "add", "--all")
    subprocess.run(["/usr/bin/git", "-C", str(root), "-c", "user.name=RQ03F C1 synthetic",
                    "-c", "user.email=c1@example.invalid", "commit", "--quiet", "-m", "synthetic source"],
                   check=True, capture_output=True)
    return _run_git(root, "rev-parse", "HEAD")


def _parent_pins(path: Path) -> tuple[int, int, int]:
    info = path.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino, operator_allocator._mount_id_for(str(path))


def _write_plan(directory: Path, plan: dict[str, object], name: str = "owner-plan.json") -> tuple[Path, str]:
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / name
    raw = _json_bytes(plan)
    path.write_bytes(raw)
    path.chmod(0o600)
    return path, hashlib.sha256(raw).hexdigest()


def _generation_plan(root: Path, source: Path, commit: str, target_id: str = "rq03f-gen-c1") -> dict[str, object]:
    parent = root / "protected-parent"
    parent.mkdir(mode=0o700, exist_ok=True)
    protected_trust_root = root / "formal-trust-placeholder"
    protected_trust_root.mkdir(mode=0o700, exist_ok=True)
    dev, ino, mount_id = _parent_pins(parent)
    return {
        "schema_version": "rq03f-exclusive-allocation-plan-1.0",
        "operation_kind": "generation",
        "operation_scope": "qualification_controller_generation",
        "target_id": target_id,
        "trusted_parent": str(parent),
        "protected_trust_root": str(protected_trust_root),
        "parent_device": dev,
        "parent_inode": ino,
        "parent_mount_id": mount_id,
        "operator_uid": os.geteuid(),
        "operator_gid": os.getegid(),
        "source_commit": commit,
        "source_checkout": str(source),
        "archive_sources": None,
    }


def _allocator_process(plan_path: str, plan_sha: str, queue: multiprocessing.Queue) -> None:
    try:
        result = operator_allocator.allocate(Path(plan_path), plan_sha)
        queue.put(("ok", result["record"]["target"]["inode"]))
    except BaseException as exc:
        queue.put(("error", type(exc).__name__, str(exc)))


class TestRQ03FExclusiveAllocator(unittest.TestCase):
    def setUp(self) -> None:
        temp_parent = Path(os.environ.get("RQ03F_C1_TEST_TMPDIR", str(REPO_ROOT)))
        self.temp = tempfile.TemporaryDirectory(prefix="rq03f-c1-", dir=temp_parent)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        (self.root / "formal-trust-placeholder").mkdir(mode=0o700)
        self.source = self.root / "source-checkout"
        self.commit = _init_source_repo(self.source, include_anchor=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_generation_is_new_and_record_is_candidate_only(self) -> None:
        plan = _generation_plan(self.root, self.source, self.commit)
        path, sha = _write_plan(self.root / "plan", plan)
        result = operator_allocator.allocate(path, sha)
        target = Path(result["path"])
        self.assertTrue(target.is_dir())
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)
        self.assertEqual(result["record"]["allocation_status"], "complete")
        self.assertEqual(result["record"]["authority_status"], "candidate_allocation_only")
        self.assertEqual(result["record"]["source_commit"], self.commit)
        self.assertEqual(result["record"]["files"], [])
        record_bytes = (target / ".rq03f-allocation-record.json").read_bytes()
        self.assertEqual(hashlib.sha256(record_bytes).hexdigest(), result["record_sha256"])
        with self.assertRaises(FileExistsError):
            operator_allocator.allocate(path, sha)
        self.assertEqual((target / ".rq03f-allocation-record.json").read_bytes(), record_bytes)

    def test_empty_dot_path_alias_and_wrong_owner_pin_fail_closed(self) -> None:
        for target_id in ("", ".", "..", "/tmp/escape", "rq03f-x/child", "rq03f-x\\child", "rq03f-x-"):
            with self.subTest(target_id=target_id):
                plan = _generation_plan(self.root, self.source, self.commit, target_id or "rq03f-valid")
                plan["target_id"] = target_id
                path, sha = _write_plan(self.root / f"plan-{hashlib.sha256(repr(target_id).encode()).hexdigest()[:8]}", plan)
                with self.assertRaises(operator_allocator.AllocationError):
                    operator_allocator.allocate(path, sha)
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-wrong-pin")
        path, sha = _write_plan(self.root / "wrong-pin", plan)
        with self.assertRaisesRegex(operator_allocator.AllocationError, "external SHA pin"):
            operator_allocator.allocate(path, "0" * 64)

    def test_archive_copies_two_exact_source_bytes_without_overwrite(self) -> None:
        parent = self.root / "protected-parent"
        parent.mkdir(mode=0o700)
        dev, ino, mount_id = _parent_pins(parent)
        plan: dict[str, object] = {
            "schema_version": "rq03f-exclusive-allocation-plan-1.0",
            "operation_kind": "legacy_archive",
            "operation_scope": "legacy_profile_index_archive",
            "target_id": "rq03f-archive-c1",
            "trusted_parent": str(parent),
            "protected_trust_root": str(self.root / "formal-trust-placeholder"),
            "parent_device": dev,
            "parent_inode": ino,
            "parent_mount_id": mount_id,
            "operator_uid": os.geteuid(),
            "operator_gid": os.getegid(),
            "source_commit": self.commit,
            "source_checkout": str(self.source),
            "archive_sources": [
                {"name": "authority-profile.json", "relative_path": ".operator-trust/rq03-live/authority-profile.json",
                 "sha256": hashlib.sha256(b'{"synthetic":"profile"}\n').hexdigest()},
                {"name": "operation-index.json", "relative_path": ".operator-trust/rq03-live/operation-index.json",
                 "sha256": hashlib.sha256(b'{"synthetic":"index"}\n').hexdigest()},
            ],
        }
        path, sha = _write_plan(self.root / "archive-plan", plan)
        result = operator_allocator.allocate(path, sha)
        target = Path(result["path"])
        self.assertEqual((target / "authority-profile.json").read_bytes(), b'{"synthetic":"profile"}\n')
        self.assertEqual((target / "operation-index.json").read_bytes(), b'{"synthetic":"index"}\n')
        for name, expected in (("authority-profile.json", plan["archive_sources"][0]["sha256"]),
                               ("operation-index.json", plan["archive_sources"][1]["sha256"])):
            self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), expected)
        with self.assertRaises(FileExistsError):
            operator_allocator.allocate(path, sha)

    def test_archive_hash_mismatch_fails_before_target_creation(self) -> None:
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-archive-bad")
        plan["operation_kind"] = "legacy_archive"
        plan["operation_scope"] = "legacy_profile_index_archive"
        plan["archive_sources"] = [
            {"name": "authority-profile.json", "relative_path": ".operator-trust/rq03-live/authority-profile.json",
             "sha256": "0" * 64},
            {"name": "operation-index.json", "relative_path": ".operator-trust/rq03-live/operation-index.json",
             "sha256": EXPECTED_INDEX_SHA},
        ]
        path, sha = _write_plan(self.root / "bad-archive-plan", plan)
        target = Path(plan["trusted_parent"]) / plan["target_id"]
        with self.assertRaisesRegex(operator_allocator.AllocationError, "SHA differs"):
            operator_allocator.allocate(path, sha)
        self.assertFalse(target.exists())

    def test_hardlinked_archive_source_and_dirty_checkout_are_rejected(self) -> None:
        profile = self.source / ".operator-trust/rq03-live/authority-profile.json"
        outside_link = self.root / "profile-hardlink"
        os.link(profile, outside_link)
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-archive-hardlink")
        plan["operation_kind"] = "legacy_archive"
        plan["operation_scope"] = "legacy_profile_index_archive"
        plan["archive_sources"] = [
            {"name": "authority-profile.json", "relative_path": ".operator-trust/rq03-live/authority-profile.json",
             "sha256": hashlib.sha256(profile.read_bytes()).hexdigest()},
            {"name": "operation-index.json", "relative_path": ".operator-trust/rq03-live/operation-index.json",
             "sha256": hashlib.sha256((self.source / ".operator-trust/rq03-live/operation-index.json").read_bytes()).hexdigest()},
        ]
        path, sha = _write_plan(self.root / "hardlink-plan", plan)
        with self.assertRaisesRegex(operator_allocator.AllocationError, "hard-linked"):
            operator_allocator.allocate(path, sha)
        outside_link.unlink()

    def test_incomplete_copy_is_marked_and_target_id_is_never_reused(self) -> None:
        parent = self.root / "protected-parent"
        parent.mkdir(mode=0o700)
        dev, ino, mount_id = _parent_pins(parent)
        plan: dict[str, object] = {
            "schema_version": "rq03f-exclusive-allocation-plan-1.0",
            "operation_kind": "legacy_archive", "operation_scope": "legacy_profile_index_archive",
            "target_id": "rq03f-archive-partial", "trusted_parent": str(parent),
            "protected_trust_root": str(self.root / "formal-trust-placeholder"),
            "parent_device": dev, "parent_inode": ino, "parent_mount_id": mount_id,
            "operator_uid": os.geteuid(), "operator_gid": os.getegid(),
            "source_commit": self.commit, "source_checkout": str(self.source),
            "archive_sources": [
                {"name": "authority-profile.json", "relative_path": ".operator-trust/rq03-live/authority-profile.json",
                 "sha256": hashlib.sha256((self.source / ".operator-trust/rq03-live/authority-profile.json").read_bytes()).hexdigest()},
                {"name": "operation-index.json", "relative_path": ".operator-trust/rq03-live/operation-index.json",
                 "sha256": hashlib.sha256((self.source / ".operator-trust/rq03-live/operation-index.json").read_bytes()).hexdigest()},
            ],
        }
        path, sha = _write_plan(self.root / "partial-plan", plan)
        original = operator_allocator._write_exclusive

        def fail_second(directory_fd: int, name: str, payload: bytes, mode: int = 0o600):
            if name == "operation-index.json":
                raise OSError("synthetic partial-write failure")
            return original(directory_fd, name, payload, mode)

        operator_allocator._write_exclusive = fail_second
        try:
            with self.assertRaisesRegex(OSError, "partial-write"):
                operator_allocator.allocate(path, sha)
        finally:
            operator_allocator._write_exclusive = original
        target = parent / str(plan["target_id"])
        self.assertTrue((target / ".rq03f-incomplete.json").is_file())
        state = json.loads((target / ".rq03f-incomplete.json").read_text())
        self.assertEqual(state["allocation_status"], "incomplete")
        self.assertFalse((target / ".rq03f-allocation-record.json").exists())
        with self.assertRaises(FileExistsError):
            operator_allocator.allocate(path, sha)

    def test_same_generation_race_has_exactly_one_winner(self) -> None:
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-race-c1")
        path, sha = _write_plan(self.root / "race-plan", plan)
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        processes = [context.Process(target=_allocator_process, args=(str(path), sha, queue)) for _ in range(2)]
        for process in processes:
            process.start()
        results = [queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(30)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(row[0] == "ok" for row in results), 1, results)
        self.assertEqual(sum(row[0] == "error" for row in results), 1, results)

    def test_parent_symlink_and_group_world_write_are_rejected(self) -> None:
        parent = self.root / "unsafe-parent"
        parent.mkdir(mode=0o700)
        os.chmod(parent, 0o777)
        dev, ino, mount_id = _parent_pins(parent)
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-unsafe-parent")
        plan.update(trusted_parent=str(parent), parent_device=dev, parent_inode=ino, parent_mount_id=mount_id)
        path, sha = _write_plan(self.root / "unsafe-parent-plan", plan)
        with self.assertRaisesRegex(operator_allocator.AllocationError, "writable"):
            operator_allocator.allocate(path, sha)

        os.chmod(parent, 0o700)
        alias = self.root / "parent-symlink"
        alias.symlink_to(parent, target_is_directory=True)
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-symlink-parent")
        dev, ino, mount_id = _parent_pins(alias)
        plan.update(trusted_parent=str(alias), parent_device=dev, parent_inode=ino, parent_mount_id=mount_id)
        path, sha = _write_plan(self.root / "symlink-parent-plan", plan)
        with self.assertRaises(OSError):
            operator_allocator.allocate(path, sha)

        dangling = self.root / "dangling-parent-symlink"
        dangling.symlink_to(self.root / "absent-parent", target_is_directory=True)
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-dangling-parent")
        dev, ino, mount_id = _parent_pins(dangling)
        plan.update(trusted_parent=str(dangling), parent_device=dev, parent_inode=ino, parent_mount_id=mount_id)
        path, sha = _write_plan(self.root / "dangling-parent-plan", plan)
        with self.assertRaises(OSError):
            operator_allocator.allocate(path, sha)

    def test_existing_file_and_dangling_symlink_targets_are_never_reused(self) -> None:
        parent = self.root / "protected-parent"
        parent.mkdir(mode=0o700)
        cases = ("rq03f-existing-file", "rq03f-existing-dangling-link")
        file_target = parent / cases[0]
        file_target.write_bytes(b"existing file is immutable to allocator\n")
        missing_target = self.root / "missing-target"
        symlink_target = parent / cases[1]
        symlink_target.symlink_to(missing_target)
        for target_id in cases:
            plan = _generation_plan(self.root, self.source, self.commit, target_id)
            path, sha = _write_plan(self.root / f"plan-{target_id}", plan)
            with self.subTest(target_id=target_id), self.assertRaises(FileExistsError):
                operator_allocator.allocate(path, sha)
        self.assertEqual(file_target.read_bytes(), b"existing file is immutable to allocator\n")
        self.assertTrue(symlink_target.is_symlink())
        self.assertFalse(missing_target.exists())

    def test_new_target_cannot_overlap_protected_trust_root(self) -> None:
        parent = self.root / "protected-parent"
        parent.mkdir(mode=0o700, exist_ok=True)
        target_id = "rq03f-protected-root"
        protected_root = parent / target_id
        protected_root.mkdir(mode=0o700)
        marker = protected_root / "existing-anchor.json"
        marker.write_bytes(b"synthetic anchor remains untouched\n")
        plan = _generation_plan(self.root, self.source, self.commit, target_id)
        plan["protected_trust_root"] = str(protected_root)
        path, sha = _write_plan(self.root / "overlap-plan", plan)
        with self.assertRaisesRegex(operator_allocator.AllocationError, "overlaps the protected Trust root"):
            operator_allocator.allocate(path, sha)
        self.assertEqual(marker.read_bytes(), b"synthetic anchor remains untouched\n")

    def test_parent_rename_and_replacement_race_is_detected_before_creation(self) -> None:
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-parent-race")
        path, sha = _write_plan(self.root / "parent-race-plan", plan)
        parent = Path(plan["trusted_parent"])
        moved = parent.with_name(parent.name + "-moved")
        original = operator_allocator._open_directory_chain
        changed = False

        def replace_parent_after_open(path_text: str, uid: int, gid: int):
            nonlocal changed
            fd, chain = original(path_text, uid, gid)
            if path_text == str(parent) and not changed:
                os.rename(parent, moved)
                parent.mkdir(mode=0o700)
                changed = True
            return fd, chain

        operator_allocator._open_directory_chain = replace_parent_after_open
        try:
            with self.assertRaisesRegex(operator_allocator.AllocationError, "canonical Owner path"):
                operator_allocator.allocate(path, sha)
        finally:
            operator_allocator._open_directory_chain = original
        self.assertTrue(changed)
        self.assertFalse((parent / str(plan["target_id"])).exists())
        self.assertFalse((moved / str(plan["target_id"])).exists())

    def test_named_posix_acl_is_rejected_when_hosted_acl_path_is_supplied(self) -> None:
        raw_parent = os.environ.get("RQ03F_C1_ACL_TEST_PARENT")
        if not raw_parent:
            self.skipTest("real POSIX ACL case runs in disposable hosted Linux job")
        parent = Path(raw_parent)
        plan = _generation_plan(self.root, self.source, self.commit, "rq03f-acl-parent")
        dev, ino, mount_id = _parent_pins(parent)
        plan.update(trusted_parent=str(parent), parent_device=dev, parent_inode=ino, parent_mount_id=mount_id)
        path, sha = _write_plan(self.root / "acl-plan", plan)
        with self.assertRaisesRegex(operator_allocator.AllocationError, "POSIX ACL"):
            operator_allocator.allocate(path, sha)


def _wheelhouse(root: Path) -> tuple[Path, Path, Path, str, str]:
    wheel_dir = root / "wheelhouse"
    wheel_dir.mkdir(mode=0o700)
    wheel_path = wheel_dir / "rq03f_synthetic_closure-1.0-py3-none-any.whl"
    members: dict[str, bytes] = {}
    for name in ("attr", "attrs", "jsonschema", "jsonschema_specifications", "referencing", "rpds"):
        members[f"{name}/__init__.py"] = f"SYNTHETIC_PACKAGE = {name!r}\n".encode()
    members["typing_extensions.py"] = b"SYNTHETIC_DEPENDENCY = True\n"
    dist = "rq03f_synthetic_closure-1.0.dist-info"
    members[f"{dist}/METADATA"] = b"Metadata-Version: 2.1\nName: rq03f-synthetic-closure\nVersion: 1.0\n\n"
    members[f"{dist}/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: synthetic-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    record_name = f"{dist}/RECORD"
    record_rows = []
    for name, payload in members.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        record_rows.append((name, f"sha256={encoded}", str(len(payload))))
    record_rows.append((record_name, "", ""))
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(record_rows)
    members[record_name] = buffer.getvalue().encode()
    with zipfile.ZipFile(wheel_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    wheel_path.chmod(0o444)
    wheel_sha = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    manifest_dir = root / "inputs"
    manifest_dir.mkdir(mode=0o700)
    requirements = manifest_dir / "requirements.lock"
    requirements.write_text(f"rq03f-synthetic-closure==1.0 --hash=sha256:{wheel_sha}\n", encoding="utf-8")
    requirements.chmod(0o444)
    manifest = manifest_dir / "wheelhouse-manifest.json"
    manifest.write_bytes(_json_bytes({"schema_version": "rq03f-wheelhouse-manifest-1.0",
                                     "files": [{"name": wheel_path.name, "sha256": wheel_sha}]}))
    manifest.chmod(0o444)
    return wheel_dir, requirements, manifest, hashlib.sha256(requirements.read_bytes()).hexdigest(), hashlib.sha256(manifest.read_bytes()).hexdigest()


class TestRQ03FCandidateBuildInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temp_parent = Path(os.environ.get("RQ03F_C1_TEST_TMPDIR", str(REPO_ROOT)))
        cls.temp = tempfile.TemporaryDirectory(prefix="rq03f-c1-build-", dir=temp_parent)
        cls.root = Path(cls.temp.name)
        cls.root.chmod(0o700)
        cls.source = cls.root / "trusted-source"
        cls.commit = _init_source_repo(cls.source)
        cls.generation_parent = cls.root / "generation-parent"
        cls.generation_parent.mkdir(mode=0o700)
        allocation_plan = _generation_plan(cls.root, cls.source, cls.commit, "rq03f-gen-build-test")
        allocation_plan["trusted_parent"] = str(cls.generation_parent)
        dev, ino, mount_id = _parent_pins(cls.generation_parent)
        allocation_plan.update(parent_device=dev, parent_inode=ino, parent_mount_id=mount_id)
        cls.allocation_plan_path, cls.allocation_plan_sha = _write_plan(cls.root / "allocation-plan", allocation_plan)
        allocated = operator_allocator.allocate(cls.allocation_plan_path, cls.allocation_plan_sha)
        cls.generation_root = Path(allocated["path"])
        cls.generation_id = allocation_plan["target_id"]
        cls.allocation_record_path = cls.generation_root / ".rq03f-allocation-record.json"
        cls.allocation_record_sha = hashlib.sha256(cls.allocation_record_path.read_bytes()).hexdigest()

        cls.wheelhouse_root, cls.requirements_lock, cls.wheelhouse_manifest, cls.lock_sha, cls.wheelhouse_sha = _wheelhouse(cls.root)
        cls.protected_root = cls.root / "formal-trust-placeholder"
        cls.protected_root.mkdir(mode=0o700, exist_ok=True)
        cls.output_root = cls.root / "candidate-output"
        cls.output_root.mkdir(mode=0o700)
        version = sys.version.split()[0]
        major_minor = ".".join(version.split(".")[:2])
        cls.plan = {
            "schema_version": "rq03f-build-inputs-1.0", "purpose": "candidate_inventory_only",
            "source_commit": cls.commit, "source_checkout": str(cls.source),
            "target_platform": f"linux-{platform.machine().lower()}",
            "operator_uid": os.geteuid(), "operator_gid": os.getegid(),
            "controller_id": "synthetic-c1-controller", "inventory_key": "c1-synthetic:key",
            "generation_id": cls.generation_id, "generation_root": str(cls.generation_root),
            "allocation_plan_sha256": cls.allocation_plan_sha,
            "allocation_record_path": str(cls.allocation_record_path),
            "allocation_record_sha256": cls.allocation_record_sha,
            "controller_root": str(cls.generation_root / "controller"),
            "protected_trust_root": str(cls.protected_root),
            "scripts_root": str(cls.generation_root / "controller" / "scripts"),
            "schemas_root": str(cls.generation_root / "controller" / "schemas"),
            "runtime_root": str(cls.generation_root / "runtime"),
            "build_python_executable": str(Path(sys.executable).resolve()),
            "python_executable": str(cls.generation_root / "runtime" / "bin" / f"python{major_minor}"),
            "python_version": version,
            "site_packages_root": str(cls.generation_root / "runtime" / "lib" / f"python{major_minor}" / "site-packages"),
            "requirements_lock": str(cls.requirements_lock), "requirements_lock_sha256": cls.lock_sha,
            "wheelhouse_root": str(cls.wheelhouse_root), "wheelhouse_manifest": str(cls.wheelhouse_manifest),
            "wheelhouse_manifest_sha256": cls.wheelhouse_sha,
            "inventory_output": str(cls.output_root / "controller-build-inventory.json"),
        }
        cls.build_plan_path, cls.build_plan_sha = _write_plan(cls.root / "build-plan", cls.plan)
        locked_install.prepare_install_roots(cls.build_plan_path, cls.build_plan_sha)
        locked_install.install_controller(cls.build_plan_path, cls.build_plan_sha)
        locked_install.install_runtime(cls.build_plan_path, cls.build_plan_sha)
        cls.inventory_path = Path(cls.plan["inventory_output"])
        cls._controller_snapshot = {
            path: (path.read_bytes(), path.stat().st_mode & 0o777)
            for path in Path(cls.plan["controller_root"]).rglob("*")
            if path.is_file()
        }
        cls._runtime_site_snapshot = {
            path: (path.read_bytes(), path.stat().st_mode & 0o777)
            for path in Path(cls.plan["site_packages_root"]).rglob("*") if path.is_file()
        }
        cls._requirements_snapshot = cls.requirements_lock.read_bytes()
        cls._wheel_manifest_snapshot = cls.wheelhouse_manifest.read_bytes()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def setUp(self) -> None:
        for path, (raw, mode) in self._controller_snapshot.items():
            path.chmod(0o644)
            path.write_bytes(raw)
            path.chmod(mode)
        for path, (raw, mode) in self._runtime_site_snapshot.items():
            path.chmod(0o644)
            path.write_bytes(raw)
            path.chmod(mode)
        self.requirements_lock.chmod(0o644)
        self.requirements_lock.write_bytes(self._requirements_snapshot)
        self.requirements_lock.chmod(0o444)
        self.wheelhouse_manifest.chmod(0o644)
        self.wheelhouse_manifest.write_bytes(self._wheel_manifest_snapshot)
        self.wheelhouse_manifest.chmod(0o444)
        if self.inventory_path.exists():
            self.inventory_path.unlink()
        result = build_inventory.build_candidate(self.build_plan_path, self.build_plan_sha)
        self.baseline_sha = result["inventory_sha256"]
        self.baseline_raw = self.inventory_path.read_bytes()

    def test_clean_candidate_build_passes_independent_and_legacy_runtime_verifiers(self) -> None:
        verified = verify_inventory.verify_candidate(self.inventory_path, self.baseline_sha,
                                                     self.build_plan_path, self.build_plan_sha)
        self.assertEqual(verified["verification_status"], "PASS")
        self.assertEqual(verified["authority_status"], "candidate_only_not_owner_approved")
        self.assertGreater(verified["components_verified"], 30)
        cmd = [str(self.plan["python_executable"]), "-I", "-S", "-B",
               str(Path(self.plan["controller_root"]) / "scripts" / "operator_controller_bootstrap.py"),
               "--build-inventory", str(self.inventory_path), "--build-sha256", self.baseline_sha,
               "--controller-root", str(self.plan["controller_root"])]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("controller_build=verified", result.stdout)

    def test_one_byte_controller_change_fails(self) -> None:
        path = Path(self.plan["scripts_root"]) / "source_truth.py"
        path.chmod(0o644)
        original = path.read_bytes()
        path.write_bytes(original + b"# drift\n")
        path.chmod(0o444)
        with self.assertRaisesRegex(verify_inventory.VerifyError, "source commit"):
            verify_inventory.verify_candidate(self.inventory_path, self.baseline_sha,
                                               self.build_plan_path, self.build_plan_sha)

    def test_changed_absolute_root_path_fails_even_with_rehashed_candidate(self) -> None:
        payload = json.loads(self.baseline_raw)
        payload["controller_root"] = str(self.generation_root / "controller-alias")
        raw = _json_bytes(payload)
        self.inventory_path.write_bytes(raw)
        with self.assertRaisesRegex(verify_inventory.VerifyError, "controller/path"):
            verify_inventory.verify_candidate(self.inventory_path, hashlib.sha256(raw).hexdigest(),
                                               self.build_plan_path, self.build_plan_sha)

    def test_python_version_or_executable_mismatch_fails(self) -> None:
        payload = json.loads(self.baseline_raw)
        payload["python_runtime"]["python_version"] = "99.99.99"
        raw = _json_bytes(payload)
        self.inventory_path.write_bytes(raw)
        with self.assertRaisesRegex(verify_inventory.VerifyError, "Python executable/version"):
            verify_inventory.verify_candidate(self.inventory_path, hashlib.sha256(raw).hexdigest(),
                                               self.build_plan_path, self.build_plan_sha)
        payload = json.loads(self.baseline_raw)
        payload["python_runtime"]["python_executable"] = str(self.generation_root / "wrong-python")
        raw = _json_bytes(payload)
        self.inventory_path.write_bytes(raw)
        with self.assertRaisesRegex(verify_inventory.VerifyError, "path differs"):
            verify_inventory.verify_candidate(self.inventory_path, hashlib.sha256(raw).hexdigest(),
                                               self.build_plan_path, self.build_plan_sha)

    def test_site_packages_one_byte_change_fails(self) -> None:
        path = Path(self.plan["site_packages_root"]) / "attrs" / "__init__.py"
        path.chmod(0o644)
        original = path.read_bytes()
        path.write_bytes(original + b"# changed\n")
        path.chmod(0o444)
        with self.assertRaisesRegex(verify_inventory.VerifyError, "site-packages tree SHA"):
            verify_inventory.verify_candidate(self.inventory_path, self.baseline_sha,
                                               self.build_plan_path, self.build_plan_sha)

    def test_missing_transitive_component_and_wrong_inventory_sha_fail(self) -> None:
        with self.assertRaisesRegex(verify_inventory.VerifyError, "raw SHA"):
            verify_inventory.verify_candidate(self.inventory_path, "0" * 64,
                                               self.build_plan_path, self.build_plan_sha)
        payload = json.loads(self.baseline_raw)
        payload["components"] = [row for row in payload["components"]
                                 if not (row["component_type"] == "python_package" and row["component_id"] == "referencing")]
        raw = _json_bytes(payload)
        self.inventory_path.write_bytes(raw)
        with self.assertRaisesRegex(verify_inventory.VerifyError, "omits or invents site-packages"):
            verify_inventory.verify_candidate(self.inventory_path, hashlib.sha256(raw).hexdigest(),
                                               self.build_plan_path, self.build_plan_sha)

    def test_locked_build_inputs_fail_closed_when_missing_or_changed(self) -> None:
        original = self.requirements_lock.read_bytes()
        self.requirements_lock.chmod(0o644)
        self.requirements_lock.write_bytes(original + b"# drift\n")
        self.requirements_lock.chmod(0o444)
        with self.assertRaisesRegex(build_inventory.BuildError, "raw SHA"):
            build_inventory._requirements_and_wheelhouse({
                **self.plan, "requirements_lock": self.requirements_lock,
                "requirements_lock_sha256": self.lock_sha,
            })

    def test_adoption_is_not_available_and_untrusted_pythonpath_is_ignored(self) -> None:
        script = TOOLS / "build_inventory.py"
        blocked = subprocess.run([sys.executable, str(script), "--plan", str(self.build_plan_path),
                                  "--expected-plan-sha256", self.build_plan_sha, "--adopt"],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("Owner-only", blocked.stderr)

        attacker = self.root / "attacker-path"
        attacker.mkdir(mode=0o700, exist_ok=True)
        marker = self.root / "sitecustomize-ran"
        (attacker / "sitecustomize.py").write_text(f"open({str(marker)!r}, 'w').write('bad')\n")
        env = {**os.environ, "PYTHONPATH": str(attacker)}
        isolated = subprocess.run([sys.executable, "-I", "-S", "-B", str(TOOLS / "verify_inventory.py"),
                                   "--inventory", str(self.inventory_path),
                                   "--expected-inventory-sha256", self.baseline_sha,
                                   "--plan", str(self.build_plan_path),
                                   "--expected-plan-sha256", self.build_plan_sha],
                                  env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(isolated.returncode, 0, isolated.stderr)
        self.assertFalse(marker.exists())

    def test_runtime_closure_is_candidate_only_and_independently_rechecked(self) -> None:
        evidence_dir = self.root / "runtime-closure-inputs"
        evidence_dir.mkdir(mode=0o700)
        os_release = evidence_dir / "os-release"
        os_release.write_bytes(b"ID=synthetic\nVERSION_ID=1\n")
        packages = evidence_dir / "packages.json"
        packages.write_bytes(b'{"packages":[]}\n')
        libraries = evidence_dir / "shared-libraries.json"
        libraries.write_bytes(b'{"libraries":[]}\n')
        for path in (os_release, packages, libraries):
            path.chmod(0o444)
        output = self.output_root / "runtime-closure-candidate.json"
        package_sha = hashlib.sha256(packages.read_bytes()).hexdigest()
        library_sha = hashlib.sha256(libraries.read_bytes()).hexdigest()
        base_digest = "sha256:" + "0" * 64
        capture_args = {
            "source_commit": self.commit,
            "inventory_sha256": self.baseline_sha,
            "base_image_digest_claim": base_digest,
            "os_release": os_release,
            "python_executable": Path(self.plan["python_executable"]),
            "runtime_root": Path(self.plan["runtime_root"]),
            "os_package_manifest": packages,
            "os_package_manifest_sha256": package_sha,
            "shared_libraries_manifest": libraries,
            "shared_libraries_manifest_sha256": library_sha,
            "protected_trust_root": self.protected_root,
            "output": output,
        }
        captured = runtime_closure.capture(**capture_args)
        self.assertEqual(captured["evidence"]["authority_status"],
                         "candidate_only_unverified_host_claims")
        checked = runtime_closure.verify(
            output, captured["evidence_sha256"], expected_base_image_digest=base_digest,
            expected_package_manifest_sha256=package_sha,
            expected_shared_libraries_manifest_sha256=library_sha,
            protected_trust_root=self.protected_root,
        )
        self.assertEqual(checked["verification_status"], "PASS_CANDIDATE_BYTES_ONLY")
        self.assertEqual(checked["authority_status"], "candidate_only_unverified_host_claims")
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        original_evidence = output.read_bytes()
        with self.assertRaises(FileExistsError):
            runtime_closure.capture(**capture_args)
        self.assertEqual(output.read_bytes(), original_evidence)


if __name__ == "__main__":
    unittest.main()
