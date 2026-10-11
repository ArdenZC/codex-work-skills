"""Closed Launch Policy loader for the fixed RQ-03F Operator entrypoint.

This module is imported only from the fixed, root-owned launcher path. The
policy file is not an authority source by itself: its raw SHA must match a
separate protected pin file at the compile-time path below on every load.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


POLICY_PATH = Path("/etc/rq03f/launch-policy.json")
PIN_PATH = Path("/etc/rq03f/launch-policy.pin.json")
POLICY_SCHEMA = "rq03f-operator-launch-policy-v1.0.schema.json"
PIN_SCHEMA = "rq03f-operator-policy-pin-v1.0.schema.json"
POLICY_VERSION = "rq03f-operator-launch-policy-1.0"
PIN_VERSION = "rq03f-operator-policy-pin-1.0"
FIXED_ENTRYPOINT_ID = "rq03f-operator-preflight-v1"
FIXED_OPERATION = "read_only_preflight"
_SHA = re.compile(r"^[a-f0-9]{64}$")
_COMMIT = re.compile(r"^[a-f0-9]{40}$")

POLICY_KEYS = {
    "policy_version", "authority_status", "owner_adopted_policy_source_identity",
    "source_commit", "generation", "controller", "profile", "operation_index",
    "runtime_closure", "dependency_inventory", "identities",
    "role_authorization_references", "revocation_references", "anti_rollback", "service",
}


class LaunchPolicyError(ValueError):
    """Stable, fail-closed Launch Policy error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LaunchState:
    policy: dict[str, Any]
    policy_raw: bytes
    policy_sha256: str
    pin: dict[str, Any]
    pin_raw: bytes


def _fail(code: str, message: str) -> None:
    raise LaunchPolicyError(code, message)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("JSON_DUPLICATE_KEY", "duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _fail("JSON_NONFINITE", "non-finite JSON value")


def _parse(raw: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                             parse_constant=_reject_constant)
    except LaunchPolicyError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LaunchPolicyError("JSON_INVALID", f"invalid {label} JSON") from exc
    if not isinstance(payload, dict):
        _fail("JSON_OBJECT_REQUIRED", f"{label} must be a JSON object")
    return payload


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _is_commit(value: Any) -> bool:
    return isinstance(value, str) and _COMMIT.fullmatch(value) is not None


def _canonical_absolute(raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
        _fail("PATH_INVALID", f"invalid absolute path: {label}")
    path = Path(raw)
    if not path.is_absolute() or str(path) != raw or os.path.normpath(raw) != raw:
        _fail("PATH_NOT_CANONICAL", f"path is not canonical and absolute: {label}")
    if "//" in raw or any(part in {".", ".."} for part in raw.split("/")):
        _fail("PATH_ALIAS", f"path alias is forbidden: {label}")
    return path


def _no_acl(path: Path) -> None:
    if not hasattr(os, "listxattr"):
        _fail("ACL_UNVERIFIED", "filesystem ACL inspection is unavailable")
    try:
        attrs = set(os.listxattr(path, follow_symlinks=False))
    except OSError as exc:
        raise LaunchPolicyError("ACL_UNVERIFIED", "filesystem ACL inspection failed") from exc
    if {"system.posix_acl_access", "system.posix_acl_default"} & attrs:
        _fail("ACL_PRESENT", "extended POSIX ACL is not permitted on trusted paths")


def inspect_path(path: Path, *, owner_uids: set[int], owner_gids: set[int] | None = None,
                 directory: bool | None = None, reject_writable: bool = True) -> os.stat_result:
    """Check every path component without following symlinks or trusting aliases."""
    if not path.is_absolute() or str(path) != os.path.normpath(str(path)):
        _fail("PATH_NOT_CANONICAL", "trusted path is not canonical and absolute")
    cursor = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as exc:
            raise LaunchPolicyError("PATH_MISSING", "trusted path component is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            _fail("PATH_SYMLINK", "symlink in trusted path")
        is_final = index == len(path.parts[1:]) - 1
        if not is_final and not stat.S_ISDIR(info.st_mode):
            _fail("PATH_PARENT_NOT_DIRECTORY", "trusted path ancestor is not a directory")
        if info.st_uid not in owner_uids:
            _fail("PATH_OWNER", "trusted path has an unexpected owner")
        if owner_gids is not None and info.st_gid not in owner_gids:
            _fail("PATH_GROUP", "trusted path has an unexpected group")
        if reject_writable and info.st_mode & 0o022:
            _fail("PATH_WRITABLE", "trusted path is group/world writable")
        _no_acl(cursor)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LaunchPolicyError("PATH_MISSING", "trusted path cannot be resolved") from exc
    if resolved != path:
        _fail("PATH_ALIAS", "trusted path resolves through an alias")
    info = path.lstat()
    if directory is True and not stat.S_ISDIR(info.st_mode):
        _fail("PATH_TYPE", "trusted path is not a directory")
    if directory is False and not stat.S_ISREG(info.st_mode):
        _fail("PATH_TYPE", "trusted path is not a regular file")
    if not stat.S_ISDIR(info.st_mode) and info.st_nlink != 1:
        _fail("PATH_HARDLINK", "hard-linked trusted file is not permitted")
    return info


def read_trusted_file(path: Path, *, owner_uids: set[int], owner_gids: set[int] | None = None,
                      max_bytes: int = 8 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
    inspect_path(path, owner_uids=owner_uids, owner_gids=owner_gids, directory=False)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise LaunchPolicyError("FILE_OPEN", "trusted file could not be opened safely") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_uid not in owner_uids or before.st_mode & 0o022
                or before.st_size > max_bytes):
            _fail("FILE_IDENTITY", "trusted file identity or mode is unsafe")
        if owner_gids is not None and before.st_gid not in owner_gids:
            _fail("FILE_GROUP", "trusted file group is unsafe")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(fd)
        stable_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        stable_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if stable_before != stable_after or total > max_bytes:
            _fail("FILE_CHANGED", "trusted file changed while being read")
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
            _fail("FILE_REPLACED", "trusted file path was replaced while being read")
        return b"".join(chunks), before
    finally:
        os.close(fd)


def validate_policy_payload(policy: dict[str, Any]) -> None:
    """Reject missing, unknown, malformed, ambiguous, or unsafe policy fields."""
    if set(policy) != POLICY_KEYS:
        _fail("POLICY_FIELDS", "Launch Policy has missing or unknown fields")
    if policy["policy_version"] != POLICY_VERSION or policy["authority_status"] != "candidate_only_not_owner_authority":
        _fail("POLICY_VERSION", "unsupported Launch Policy version or authority status")
    if not _is_commit(policy["source_commit"]):
        _fail("POLICY_SOURCE_COMMIT", "source commit pin must be 40 lowercase hex characters")
    owner_identity = policy["owner_adopted_policy_source_identity"]
    if (not isinstance(owner_identity, dict)
            or set(owner_identity) != {"adoption_status", "policy_identity", "source_commit"}
            or owner_identity.get("adoption_status") not in {"candidate_only", "owner_adopted"}
            or not isinstance(owner_identity.get("policy_identity"), str)
            or not owner_identity["policy_identity"].strip()
            or not _is_commit(owner_identity.get("source_commit"))
            or owner_identity["source_commit"] != policy["source_commit"]):
        _fail("POLICY_IDENTITY", "Owner policy source identity is incomplete or inconsistent")
    generation = policy["generation"]
    controller = policy["controller"]
    profile = policy["profile"]
    index = policy["operation_index"]
    runtime = policy["runtime_closure"]
    inventory = policy["dependency_inventory"]
    if not isinstance(generation, dict) or set(generation) != {"generation_id", "final_path", "operation_root"}:
        _fail("GENERATION_FIELDS", "Generation policy fields are incomplete")
    generation_root = _canonical_absolute(generation.get("final_path"), "Generation final path")
    operation_root = _canonical_absolute(generation.get("operation_root"), "operation root")
    if (not isinstance(generation.get("generation_id"), str)
            or re.fullmatch(r"rq03f-(?:[a-z0-9]|[a-z0-9][a-z0-9-]{0,54}[a-z0-9])", generation["generation_id"]) is None
            or not operation_root.is_relative_to(generation_root)
            or operation_root == generation_root):
        _fail("GENERATION_BINDING", "Generation ID or operation root binding is invalid")
    controller_fields = {"controller_id", "implementation", "version", "root", "runtime_root",
                         "python_executable", "build_inventory", "controller_allowlist", "fixed_entrypoint"}
    if not isinstance(controller, dict) or set(controller) != controller_fields:
        _fail("CONTROLLER_FIELDS", "Controller policy fields are incomplete")
    controller_root = _canonical_absolute(controller.get("root"), "Controller Root")
    runtime_root = _canonical_absolute(controller.get("runtime_root"), "Runtime Root")
    python_executable = _canonical_absolute(controller.get("python_executable"), "Python executable")
    if controller_root != generation_root / "controller" or runtime_root != generation_root / "runtime":
        _fail("CONTROLLER_ROOT_BINDING", "Controller or Runtime Root differs from the final Generation")
    if not python_executable.is_relative_to(runtime_root):
        _fail("PYTHON_RUNTIME_BINDING", "Python executable is outside the final Runtime Root")
    if any(not isinstance(controller.get(key), str) or not controller[key].strip()
           for key in ("controller_id", "implementation", "version")):
        _fail("CONTROLLER_IDENTITY", "Controller identity is incomplete")
    build = controller["build_inventory"]
    if (not isinstance(build, dict) or set(build) != {"key", "path", "sha256"}
            or not isinstance(build.get("key"), str) or not build["key"].strip()
            or not _is_sha(build.get("sha256"))):
        _fail("BUILD_INVENTORY_FIELDS", "Build Inventory pin is incomplete")
    build_path = _canonical_absolute(build.get("path"), "Build Inventory path")
    entrypoint = controller["fixed_entrypoint"]
    if (not isinstance(entrypoint, dict)
            or set(entrypoint) != {"entrypoint_id", "operation", "module_path", "module_sha256"}
            or entrypoint.get("entrypoint_id") != FIXED_ENTRYPOINT_ID
            or entrypoint.get("operation") != FIXED_OPERATION
            or not _is_sha(entrypoint.get("module_sha256"))):
        _fail("ENTRYPOINT", "only the fixed read-only Operator preflight entrypoint is supported")
    entrypoint_path = _canonical_absolute(entrypoint.get("module_path"), "fixed entrypoint path")
    if entrypoint_path != controller_root / "scripts" / "rq03f_fixed_operator_launcher.py":
        _fail("ENTRYPOINT_PATH", "fixed entrypoint path differs from the installed controller")
    allowlist = controller.get("controller_allowlist")
    if not isinstance(allowlist, list) or not allowlist:
        _fail("CONTROLLER_ALLOWLIST", "controller allowlist is required")
    triples = []
    for row in allowlist:
        if not isinstance(row, dict) or set(row) != {"controller_id", "implementation", "version"}:
            _fail("CONTROLLER_ALLOWLIST", "controller allowlist entry is malformed")
        triple = (row["controller_id"], row["implementation"], row["version"])
        if any(not isinstance(value, str) or not value.strip() for value in triple):
            _fail("CONTROLLER_ALLOWLIST", "controller allowlist entry is incomplete")
        triples.append(triple)
    if len(triples) != len(set(triples)) or (controller["controller_id"], controller["implementation"], controller["version"]) not in triples:
        _fail("CONTROLLER_ALLOWLIST", "fixed Controller is not exactly allowlisted")
    if (not isinstance(profile, dict) or set(profile) != {"version", "path", "sha256", "policy_epoch"}
            or profile.get("version") != "1.1" or not _is_sha(profile.get("sha256"))
            or type(profile.get("policy_epoch")) is not int or profile["policy_epoch"] < 1):
        _fail("PROFILE_FIELDS", "Profile 1.1 pin is malformed")
    profile_path = _canonical_absolute(profile.get("path"), "Profile 1.1 path")
    if (not isinstance(index, dict)
            or set(index) != {"version", "path", "initial_adoption_sha256", "consistency"}
            or index.get("version") != "1.1"
            or index.get("consistency") != "current_append_only_each_operation"
            or not _is_sha(index.get("initial_adoption_sha256"))):
        _fail("INDEX_FIELDS", "Index 1.1 current-state binding is malformed")
    index_path = _canonical_absolute(index.get("path"), "Index 1.1 path")
    if profile_path == index_path or profile_path.parent != index_path.parent:
        _fail("AUTHORITY_PATHS", "Profile and Index must be distinct siblings in one protected root")
    if (not isinstance(runtime, dict)
            or set(runtime) != {"path", "sha256", "base_image_digest_claim", "os_package_manifest_sha256",
                               "shared_libraries_manifest_sha256", "authority_status"}
            or not _is_sha(runtime.get("sha256"))
            or not isinstance(runtime.get("base_image_digest_claim"), str)
            or re.fullmatch(r"sha256:[a-f0-9]{64}", runtime["base_image_digest_claim"]) is None
            or not _is_sha(runtime.get("os_package_manifest_sha256"))
            or not _is_sha(runtime.get("shared_libraries_manifest_sha256"))
            or runtime.get("authority_status") != "candidate_only_unverified_host_claims"):
        _fail("RUNTIME_CLOSURE_FIELDS", "Runtime Closure pin is malformed or claims authority")
    _canonical_absolute(runtime.get("path"), "Runtime Closure path")
    if (not isinstance(inventory, dict)
            or set(inventory) != {"path", "sha256", "run_root", "protected_roots"}
            or not _is_sha(inventory.get("sha256"))):
        _fail("DEPENDENCY_INVENTORY_FIELDS", "protected dependency inventory pin is malformed")
    _canonical_absolute(inventory.get("path"), "dependency inventory path")
    inventory_run_root = _canonical_absolute(inventory.get("run_root"), "dependency inventory run root")
    if inventory_run_root != operation_root:
        _fail("OPERATION_ROOT_BINDING", "fixed dependency Inventory run root differs from Generation policy")
    if (inventory_run_root.is_relative_to(controller_root) or controller_root.is_relative_to(inventory_run_root)
            or inventory_run_root.is_relative_to(runtime_root) or runtime_root.is_relative_to(inventory_run_root)):
        _fail("OPERATION_ROOT_OVERLAP", "operation data cannot overlap Controller or Runtime paths")
    roots = inventory.get("protected_roots")
    if not isinstance(roots, list) or not roots or len(roots) != len(set(roots)):
        _fail("PROTECTED_ROOTS", "distinct protected roots are required")
    root_paths = [_canonical_absolute(value, "protected root") for value in roots]
    if any(root_path == inventory_run_root or root_path.is_relative_to(inventory_run_root)
           or inventory_run_root.is_relative_to(root_path) for root_path in root_paths):
        _fail("ROOT_OVERLAP", "Candidate run root and protected roots must be disjoint")
    if not any(profile_path.is_relative_to(root) and index_path.is_relative_to(root) for root in root_paths):
        _fail("AUTHORITY_ROOT", "Profile and Index are outside the declared protected roots")
    if not any(build_path.is_relative_to(root) for root in root_paths):
        _fail("BUILD_ROOT", "Build Inventory is outside the declared protected roots")
    identities = policy.get("identities")
    if not isinstance(identities, dict) or set(identities) != {"operator", "candidate", "author", "reviewer", "approver"}:
        _fail("IDENTITIES", "all five independent process identities are required")
    seen_uids: set[int] = set()
    seen_gids: set[int] = set()
    seen_principals: set[str] = set()
    for role_name, identity in identities.items():
        if (not isinstance(identity, dict) or set(identity) != {"principal_id", "uid", "gid"}
                or not isinstance(identity.get("principal_id"), str) or not identity["principal_id"].strip()
                or type(identity.get("uid")) is not int or identity["uid"] < 1
                or type(identity.get("gid")) is not int or identity["gid"] < 1):
            _fail("IDENTITY_ENTRY", f"{role_name} identity is malformed")
        if identity["uid"] in seen_uids or identity["gid"] in seen_gids:
            _fail("IDENTITY_COLLISION", "Operator and business principals require unique UIDs and GIDs")
        seen_uids.add(identity["uid"])
        seen_gids.add(identity["gid"])
        if identity["principal_id"] in seen_principals:
            _fail("IDENTITY_COLLISION", "Operator and business principal IDs must be distinct")
        seen_principals.add(identity["principal_id"])
    bindings = policy.get("role_authorization_references")
    if not isinstance(bindings, list) or not bindings:
        _fail("ROLE_BINDINGS", "role authorization references are required")
    binding_principals: set[str] = set()
    for binding in bindings:
        if (not isinstance(binding, dict)
                or set(binding) != {"principal_id", "authorization_reference", "authorization_sha256", "allowed_roles"}
                or not isinstance(binding.get("principal_id"), str)
                or not isinstance(binding.get("authorization_reference"), str)
                or not _is_sha(binding.get("authorization_sha256"))
                or not isinstance(binding.get("allowed_roles"), list)
                or not binding["allowed_roles"]):
            _fail("ROLE_BINDING", "role authorization reference is malformed")
        if binding["principal_id"] in binding_principals:
            _fail("ROLE_BINDING_DUPLICATE", "duplicate role authorization principal")
        binding_principals.add(binding["principal_id"])
        if any(role not in {"author", "scope_reviewer", "qualification_approver", "corpus_adjudicator",
                            "teacher_approver", "qualification_corpus_custodian"}
               for role in binding["allowed_roles"]):
            _fail("ROLE_BINDING_ROLE", "unknown Profile role")
        if len(binding["allowed_roles"]) != len(set(binding["allowed_roles"])):
            _fail("ROLE_BINDING_ROLE", "duplicate Profile role")
    operator = identities["operator"]
    operator_binding = next((row for row in bindings if row["principal_id"] == operator["principal_id"]), None)
    if operator_binding is None or operator_binding["allowed_roles"] != ["qualification_corpus_custodian"]:
        _fail("OPERATOR_LEAST_PRIVILEGE", "Operator must have only qualification corpus custodian authority")
    revocations = policy.get("revocation_references")
    if (not isinstance(revocations, dict)
            or set(revocations) != {"inventory_key", "fields", "recheck_each_operation"}
            or revocations != {"inventory_key": "authority_profile",
                               "fields": ["revoked_authority_ids", "roles[].revoked_at", "roles[].revocation_reason"],
                               "recheck_each_operation": True}):
        _fail("REVOCATION_BINDING", "revocation state must be re-read from the current Profile on every operation")
    if policy.get("anti_rollback") != {"required": True,
                                        "interface": "rq03f-c3-anti-rollback-gate-v1",
                                        "production_writes_allowed": False,
                                        "absent_behavior": "block"}:
        _fail("ANTI_ROLLBACK_POLICY", "C3 AntiRollbackGate must be mandatory and production writes blocked")
    if policy.get("service") != {"disabled_by_default": True, "install_or_start_authorized": False}:
        _fail("SERVICE_POLICY", "C2 Service must remain disabled and uninstalled")


def validate_pin_payload(pin: dict[str, Any]) -> None:
    if (set(pin) != {"pin_version", "policy_identity", "policy_sha256", "adoption_status"}
            or pin.get("pin_version") != PIN_VERSION
            or not isinstance(pin.get("policy_identity"), str) or not pin["policy_identity"].strip()
            or not _is_sha(pin.get("policy_sha256"))
            or pin.get("adoption_status") not in {"candidate_only", "owner_adopted"}):
        _fail("PIN_FIELDS", "independent Launch Policy pin is malformed")


def load_pinned_state(controller_script_path: Path) -> LaunchState:
    """Load only the fixed external policy/pin pair; callers cannot choose either path."""
    script_path = _canonical_absolute(str(controller_script_path), "running fixed launcher")
    script_info = inspect_path(script_path, owner_uids={0}, directory=False)
    del script_info
    pin_raw, _ = read_trusted_file(PIN_PATH, owner_uids={0})
    pin = _parse(pin_raw, "independent policy pin")
    validate_pin_payload(pin)
    policy_raw, _ = read_trusted_file(POLICY_PATH, owner_uids={0})
    digest = hashlib.sha256(policy_raw).hexdigest()
    if digest != pin["policy_sha256"]:
        _fail("POLICY_PIN_MISMATCH", "Launch Policy bytes do not match the independent protected pin")
    policy = _parse(policy_raw, "Launch Policy")
    validate_policy_payload(policy)
    identity = policy["owner_adopted_policy_source_identity"]
    if (identity["policy_identity"] != pin["policy_identity"]
            or identity["adoption_status"] != pin["adoption_status"]):
        _fail("POLICY_IDENTITY_PIN_MISMATCH", "Launch Policy source identity differs from independent pin")
    expected_script = Path(policy["controller"]["fixed_entrypoint"]["module_path"])
    if script_path != expected_script:
        _fail("FIXED_LAUNCHER_PATH", "running launcher is not the policy-pinned fixed entrypoint")
    if Path(policy["controller"]["root"]) != script_path.parent.parent:
        _fail("CONTROLLER_ROOT_PATH", "running launcher is outside pinned Controller Root")
    return LaunchState(policy, policy_raw, digest, pin, pin_raw)


def validate_schema_bytes(policy_raw: bytes, pin_raw: bytes) -> None:
    """Run the installed JSON Schemas after the isolated Bootstrap has succeeded."""
    try:
        from semantic_scope_records import schema_errors
    except ImportError as exc:
        raise LaunchPolicyError("SCHEMA_VALIDATOR_UNAVAILABLE", "pinned JSON Schema validator is unavailable") from exc
    policy = _parse(policy_raw, "Launch Policy")
    pin = _parse(pin_raw, "independent policy pin")
    errors = schema_errors(policy, POLICY_SCHEMA) + schema_errors(pin, PIN_SCHEMA)
    if errors:
        _fail("SCHEMA_INVALID", "Launch Policy or pin does not satisfy its pinned closed schema")


def verify_os_identity(policy: dict[str, Any]) -> None:
    if not sys.platform.startswith("linux") or os.name != "posix":
        _fail("PLATFORM_UNSUPPORTED", "fixed Operator launcher requires Linux POSIX identity checks")
    operator = policy["identities"]["operator"]
    if (os.getuid() != os.geteuid() or os.getuid() != operator["uid"]
            or os.getgid() != os.getegid() or os.getgid() != operator["gid"]):
        _fail("PROCESS_IDENTITY", "real/effective UID or GID differs from the pinned Operator")
    if set(os.getgroups()) - {operator["gid"]}:
        _fail("SUPPLEMENTARY_GROUPS", "unexpected supplementary group is present")
    try:
        status = Path("/proc/self/status").read_text(encoding="ascii")
    except OSError as exc:
        raise LaunchPolicyError("PROCESS_STATUS", "Linux process identity evidence is unavailable") from exc
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if fields.get("NoNewPrivs", "").strip() != "1":
        _fail("NO_NEW_PRIVS", "NoNewPrivileges must be active for the fixed Operator process")
    for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        value = fields.get(key, "").strip()
        if not value or int(value, 16) != 0:
            _fail("CAPABILITIES", "unexpected Linux capability is present or unverifiable")


def validate_runtime_paths(policy: dict[str, Any]) -> None:
    operator_uid = policy["identities"]["operator"]["uid"]
    trusted_owners = {0}
    controller = policy["controller"]
    for raw, is_dir in ((controller["root"], True), (controller["runtime_root"], True),
                        (controller["python_executable"], False),
                        (controller["build_inventory"]["path"], False),
                        (policy["runtime_closure"]["path"], False),
                        (policy["dependency_inventory"]["path"], False),
                        (controller["fixed_entrypoint"]["module_path"], False)):
        info = inspect_path(Path(raw), owner_uids=trusted_owners, directory=is_dir)
        if info.st_uid != 0 or info.st_mode & 0o022:
            _fail("TRUSTED_RUNTIME_OWNER", "Controller and Runtime must be root-owned and non-writable")
    for raw in policy["dependency_inventory"]["protected_roots"]:
        path = Path(raw)
        info = inspect_path(path, owner_uids={0, operator_uid}, directory=True)
        if info.st_mode & 0o022:
            _fail("PROTECTED_ROOT_MODE", "protected root is group/world writable")
    # The profile/index repository is Operator-owned for the existing append-only
    # controller contract. The parent chain remains root-owned or Operator-owned.
    for raw in (policy["profile"]["path"], policy["operation_index"]["path"]):
        path = Path(raw)
        info = inspect_path(path, owner_uids={0, operator_uid}, directory=False)
        if info.st_uid != operator_uid or info.st_mode & 0o022:
            _fail("AUTHORITY_FILE_MODE", "Profile/Index is group/world writable")
