"""External per-operation TrustContext provider for the fixed C2 launcher.

This provider consumes a policy loader installed by the fixed launcher. It
re-reads independent policy pins, Profile, current append-only Index, runtime
closure, dependency inventory, OS identity, and revocation material for every
call made through ``semantic_lifecycle.context()``. It deliberately has no C3
anti-rollback implementation and never authorizes protected production writes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sysconfig
import threading
from typing import Any, Callable, Protocol

from lifecycle_digest import canonical_json_bytes, sha256_bytes
from semantic_scope_records import Inventory, TrustContext, checked, parse, require

import rq03f_operator_launch_policy as launch_policy


class ProviderError(ValueError):
    """Stable provider error suitable for redacted launcher logs."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AntiRollbackGate(Protocol):
    """C3 contract only. C2 has no implementation that can satisfy it."""

    def check_current_state(self, *, policy_identity: str, policy_epoch: int,
                            index_sha256: str, operation_purpose: str) -> object: ...


class ReadOnlyPreflightTrustContext(TrustContext):
    """TrustContext view that cannot authorize any protected role in C2."""

    def role(self, principal: str, role: str, at: datetime | None = None,
             *, current_validity: bool = True) -> dict[str, Any]:
        del principal, role, at, current_validity
        require_protected_write(None, operation_purpose="role_authorization")


def require_protected_write(gate: AntiRollbackGate | None, *, operation_purpose: str) -> None:
    """Fail closed until C3 supplies a separately deployed monotonic ledger.

    Even an object returning ``True`` is insufficient: this C2 package has no
    trusted AntiRollbackGate implementation or protected high-water state.
    """
    del gate, operation_purpose
    raise ProviderError("C3_ANTI_ROLLBACK_GATE_REQUIRED",
                        "protected production writes are blocked until C3 is implemented and accepted")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderError("TRUST_JSON_INVALID", f"invalid {label} JSON") from exc
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def _read_file(path: Path, *, owner_uids: set[int], max_bytes: int = 64 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
    try:
        info = launch_policy.inspect_path(path, owner_uids=owner_uids, directory=False)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
    except (OSError, launch_policy.LaunchPolicyError) as exc:
        raise ProviderError("TRUST_FILE_UNSAFE", "protected trust file cannot be opened safely") from exc
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_uid in owner_uids and before.st_mode & 0o022 == 0
                and before.st_size <= max_bytes,
                "protected trust file identity or mode is unsafe")
        require((before.st_dev, before.st_ino) == (info.st_dev, info.st_ino),
                "protected trust file changed between path and descriptor inspection")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                and total <= max_bytes,
                "protected trust file changed while being read")
        current = path.lstat()
        require((current.st_dev, current.st_ino) == (after.st_dev, after.st_ino),
                "protected trust file path was replaced while being read")
        return b"".join(chunks), info
    finally:
        os.close(fd)


def _append_only(previous_raw: bytes, current_raw: bytes) -> None:
    previous = _json(previous_raw, "previous protected Index")
    current = _json(current_raw, "current protected Index")
    require(previous.get("index_version") == current.get("index_version") == "1.1",
            "protected Index version changed")
    require(previous.get("controller_id") == current.get("controller_id")
            and previous.get("policy_epoch") == current.get("policy_epoch"),
            "protected Index controller or epoch changed")
    for field in ("receipts", "authors", "adjudications", "qualification_runs", "qualification_corpus_intakes"):
        old_rows = previous.get(field)
        new_rows = current.get(field)
        require(isinstance(old_rows, list) and isinstance(new_rows, list)
                and len(new_rows) >= len(old_rows) and new_rows[:len(old_rows)] == old_rows,
                f"protected Index is not append-only: {field}")


def _tree_sha(root: Path, *, excluded_roots: tuple[Path, ...] = ()) -> str:
    """Match C1 Runtime Closure tree hashing while rejecting unsafe entries."""
    root = Path(root)
    launch_policy.inspect_path(root, owner_uids={0}, directory=True)
    rows: list[dict[str, str]] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            path = base / name
            if any(path.resolve(strict=True).is_relative_to(item.resolve(strict=True)) for item in excluded_roots):
                continue
            info = path.lstat()
            require(stat.S_ISDIR(info.st_mode), "runtime closure contains a symlink/special directory")
            require(info.st_uid == 0 and info.st_mode & 0o022 == 0,
                    "runtime directory is not root-owned and non-writable")
            retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            path = base / name
            if any(path.resolve(strict=True).is_relative_to(item.resolve(strict=True)) for item in excluded_roots):
                continue
            info = path.lstat()
            require(info.st_uid == 0 and info.st_mode & 0o022 == 0,
                    "runtime file is not root-owned and non-writable")
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                resolved = path.resolve(strict=True)
                require(resolved.is_file(), "runtime symlink target is not a file")
                rows.append({"path": path.relative_to(root).as_posix(), "kind": "symlink",
                             "target": target, "target_sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()})
            else:
                require(stat.S_ISREG(info.st_mode), "runtime closure contains a special file")
                rows.append({"path": path.relative_to(root).as_posix(), "kind": "file",
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _verify_runtime_closure(policy: dict[str, Any], build: dict[str, Any]) -> None:
    binding = policy["runtime_closure"]
    path = Path(binding["path"])
    raw, _ = _read_file(path, owner_uids={0})
    require(_sha(raw) == binding["sha256"], "Runtime Closure SHA differs from independent policy pin")
    evidence = _json(raw, "Runtime Closure")
    require(evidence.get("schema_version") == "rq03f-runtime-closure-candidate-1.0"
            and evidence.get("authority_status") == "candidate_only_unverified_host_claims",
            "Runtime Closure must remain candidate-only evidence")
    controller = policy["controller"]
    require(evidence.get("source_commit") == policy["source_commit"]
            and evidence.get("build_inventory_sha256") == controller["build_inventory"]["sha256"]
            and evidence.get("python_executable") == controller["python_executable"]
            and evidence.get("runtime_root") == controller["runtime_root"],
            "Runtime Closure does not bind the pinned source, Build Inventory, Python, and Runtime Root")
    require(evidence.get("base_image_digest_claim") == binding["base_image_digest_claim"]
            and evidence.get("os_package_manifest_sha256") == binding["os_package_manifest_sha256"]
            and evidence.get("shared_libraries_manifest_sha256") == binding["shared_libraries_manifest_sha256"],
            "Runtime Closure claims differ from the independently pinned policy")
    for path_field, digest_field in (("os_release_path", "os_release_sha256"),
                                     ("os_package_manifest_path", "os_package_manifest_sha256"),
                                     ("shared_libraries_manifest_path", "shared_libraries_manifest_sha256")):
        file_path = Path(evidence[path_field])
        raw_file, _ = _read_file(file_path, owner_uids={0})
        require(_sha(raw_file) == evidence[digest_field], f"Runtime Closure file changed: {path_field}")
    executable = Path(evidence["python_executable"])
    require(executable == Path(controller["python_executable"]), "Python executable path drift")
    runtime = build["python_runtime"]
    require(runtime["python_executable"] == str(executable),
            "Python executable path differs from the pinned Build Inventory")
    executable_raw, _ = _read_file(executable, owner_uids={0})
    require(_sha(executable_raw) == runtime["python_executable_sha256"],
            "Python executable bytes differ from the pinned Build Inventory")
    runtime_root = Path(controller["runtime_root"])
    require(_tree_sha(runtime_root) == evidence["runtime_root_tree_sha256"],
            "Runtime Root changed since Runtime Closure capture")
    stdlib_root = Path(evidence["python_stdlib_root"])
    paths = sysconfig.get_paths()
    site_paths = tuple(Path(value).resolve(strict=True) for value in
                       (paths.get("purelib"), paths.get("platlib")) if value)
    require(_tree_sha(stdlib_root, excluded_roots=site_paths) == evidence["python_stdlib_tree_sha256"],
            "Python standard-library tree changed since Runtime Closure capture")


class OperatorTrustContextProvider:
    """Callable Provider compatible with semantic_lifecycle.operator_context."""

    def __init__(self, *, policy_loader: Callable[[], Any], initial_state: Any):
        self._policy_loader = policy_loader
        self._initial = initial_state
        self._lock = threading.RLock()
        operator_uid = initial_state.policy["identities"]["operator"]["uid"]
        index_raw, index_info = _read_file(Path(initial_state.policy["operation_index"]["path"]),
                                           owner_uids={0, operator_uid})
        require(index_info.st_uid == operator_uid, "protected Index must be owned by the Operator UID")
        require(_sha(index_raw) == initial_state.policy["operation_index"]["initial_adoption_sha256"],
                "current Index is not the exact initial policy snapshot at C2 launcher startup")
        self._last_index_raw = index_raw
        self._last_index_sha256 = _sha(index_raw)
        self._fixed_identity = (
            initial_state.policy_sha256,
            initial_state.policy["profile"]["sha256"],
            initial_state.policy["profile"]["policy_epoch"],
            initial_state.policy["operation_index"]["initial_adoption_sha256"],
            initial_state.policy["owner_adopted_policy_source_identity"]["policy_identity"],
        )

    def _fresh_state(self) -> Any:
        try:
            state = self._policy_loader()
        except Exception as exc:
            raise ProviderError("POLICY_REVALIDATION", "independent policy pin revalidation failed") from exc
        policy = state.policy
        current_identity = (
            state.policy_sha256,
            policy["profile"]["sha256"],
            policy["profile"]["policy_epoch"],
            policy["operation_index"]["initial_adoption_sha256"],
            policy["owner_adopted_policy_source_identity"]["policy_identity"],
        )
        require(current_identity == self._fixed_identity,
                "Policy, epoch, Profile pin, Index snapshot, or adoption identity changed; fixed Launcher restart required")
        try:
            launch_policy.verify_os_identity(policy)
            launch_policy.validate_runtime_paths(policy)
            launch_policy.validate_schema_bytes(state.policy_raw, state.pin_raw)
        except launch_policy.LaunchPolicyError as exc:
            raise ProviderError(exc.code, "current policy or process identity is invalid") from exc
        except Exception as exc:
            raise ProviderError("POLICY_OR_IDENTITY_INVALID", "current policy or process identity is invalid") from exc
        return state

    def __call__(self) -> TrustContext:
        with self._lock:
            state = self._fresh_state()
            policy = state.policy
            operator = policy["identities"]["operator"]
            operator_uid = operator["uid"]
            # Confirm no long-lived context can outlive the raw current Index.
            index_path = Path(policy["operation_index"]["path"])
            index_raw, index_info = _read_file(index_path, owner_uids={0, operator_uid})
            require(index_info.st_uid == operator_uid, "protected Index owner changed")
            index_sha = _sha(index_raw)
            try:
                _append_only(self._last_index_raw, index_raw)
            except Exception as exc:
                raise ProviderError("INDEX_APPEND_ONLY", "current protected Index is not append-only") from exc
            if index_sha != self._last_index_sha256:
                self._last_index_raw = index_raw
                self._last_index_sha256 = index_sha
            index_payload = _json(index_raw, "protected Index")
            errors = []
            try:
                index_errors = checked(index_raw, "protected-operation-index-v1.1")
                del index_errors
            except Exception as exc:
                errors.append(exc)
            if errors:
                raise ProviderError("INDEX_SCHEMA", "current protected Index does not satisfy Index 1.1") from errors[0]
            require(index_payload.get("policy_epoch") == policy["profile"]["policy_epoch"]
                    and index_payload.get("controller_id") == policy["controller"]["controller_id"],
                    "current protected Index differs from policy epoch or Controller")
            build_binding = policy["controller"]["build_inventory"]
            build_raw, _ = _read_file(Path(build_binding["path"]), owner_uids={0})
            require(_sha(build_raw) == build_binding["sha256"],
                    "Owner-pinned Build Inventory changed")
            build = checked(build_raw, "operator-controller-build-inventory-v1.1")
            _verify_runtime_closure(policy, build)

            inventory_binding = policy["dependency_inventory"]
            manifest_raw, _ = _read_file(Path(inventory_binding["path"]), owner_uids={0})
            require(_sha(manifest_raw) == inventory_binding["sha256"],
                    "protected dependency Inventory SHA differs from Launch Policy")
            manifest = checked(manifest_raw, "semantic-dependency-inventory")
            entries = {row["inventory_key"]: dict(row) for row in manifest["entries"]}
            for key, path, digest in (
                ("authority_profile", policy["profile"]["path"], policy["profile"]["sha256"]),
                ("operation_index", policy["operation_index"]["path"], index_sha),
                (policy["controller"]["build_inventory"]["key"],
                 policy["controller"]["build_inventory"]["path"],
                 policy["controller"]["build_inventory"]["sha256"]),
            ):
                row = entries.get(key)
                require(row is not None and row["path"] == path
                        and row["storage_class"] == "protected_external",
                        f"protected dependency Inventory path or class mismatch: {key}")
                row["sha256"] = digest
            for component in build["components"]:
                key = component.get("inventory_key")
                if key is None:
                    continue
                row = entries.get(key)
                require(row is not None and row["path"] == component["runtime_path"]
                        and row["sha256"] == component["sha256"]
                        and row["storage_class"] == "protected_external",
                        f"protected Controller component binding mismatch: {component['component_id']}")

            inventory = Inventory(
                entries,
                Path(inventory_binding["run_root"]),
                tuple(Path(value) for value in inventory_binding["protected_roots"]),
            )
            context = TrustContext(
                inventory=inventory,
                profile_path=Path(policy["profile"]["path"]),
                profile_pin=policy["profile"]["sha256"],
                policy_epoch=policy["profile"]["policy_epoch"],
                operation_index_path=index_path,
                controller_allowlist=tuple(
                    (row["controller_id"], row["implementation"], row["version"])
                    for row in policy["controller"]["controller_allowlist"]
                ),
                now=datetime.now(timezone.utc),
                operator_principal=operator["principal_id"],
                operator_unix_uid=operator_uid,
                non_operator_process_unix_uids=tuple(
                    policy["identities"][role]["uid"]
                    for role in ("candidate", "author", "reviewer", "approver")
                ),
            )
            try:
                profile, _current_index = context.load()
                role = context.role(operator["principal_id"], "qualification_corpus_custodian")
            except Exception as exc:
                raise ProviderError("AUTHORITY_REVALIDATION", "Profile, Index, role, expiry, or revocation check failed") from exc
            require(profile["qualification_corpus_custodian_principal"] == operator["principal_id"]
                    and profile["operator_unix_uid"] == operator_uid,
                    "Operator identity differs from Profile 1.1")
            require(profile["non_operator_process_unix_uids"] == list(context.non_operator_process_unix_uids),
                    "non-Operator process UIDs differ from Profile 1.1")
            require(role["allowed_roles"] == ["qualification_corpus_custodian"],
                    "Operator must not gain author, reviewer, approver, PA, Teacher, or Generation roles")
            role_bindings = sorted(
                (row["principal_id"], row["authorization_reference"],
                 _sha(inventory.raw(row["authorization_reference"], protected=True)), tuple(row["allowed_roles"]))
                for row in profile["roles"]
            )
            policy_bindings = sorted(
                (row["principal_id"], row["authorization_reference"], row["authorization_sha256"], tuple(row["allowed_roles"]))
                for row in policy["role_authorization_references"]
            )
            require(role_bindings == policy_bindings,
                    "current role authorization references differ from Owner-pinned Launch Policy")
            require(policy["controller"]["fixed_entrypoint"]["operation"] == "read_only_preflight"
                    and policy["anti_rollback"]["production_writes_allowed"] is False,
                    "C2 Launcher purpose is not read-only or production write gate is not closed")
            # semantic_lifecycle.context() has no operation-purpose argument.
            # Return a TrustContext subclass that permits read-only loading but
            # cannot hand any authorization role to downstream production code.
            # Any future C3 write API must use a separately verified gate.
            return ReadOnlyPreflightTrustContext(
                inventory=context.inventory,
                profile_path=context.profile_path,
                profile_pin=context.profile_pin,
                policy_epoch=context.policy_epoch,
                operation_index_path=context.operation_index_path,
                controller_allowlist=context.controller_allowlist,
                now=context.now,
                operator_principal=context.operator_principal,
                operator_unix_uid=context.operator_unix_uid,
                non_operator_process_unix_uids=context.non_operator_process_unix_uids,
            )

    def context_for_operation(self, purpose: str) -> TrustContext:
        context = self()
        if purpose != "read_only_preflight":
            require_protected_write(None, operation_purpose=purpose)
        return context


def verify_policy_schema_against_contract(policy: dict[str, Any], pin: dict[str, Any]) -> None:
    """Convenient unit-test seam for validating both closed JSON Schemas."""
    from semantic_scope_records import schema_errors
    errors = schema_errors(policy, launch_policy.POLICY_SCHEMA)
    errors += schema_errors(pin, launch_policy.PIN_SCHEMA)
    if errors:
        raise ProviderError("SCHEMA_CONTRACT_MISMATCH", "; ".join(errors))
