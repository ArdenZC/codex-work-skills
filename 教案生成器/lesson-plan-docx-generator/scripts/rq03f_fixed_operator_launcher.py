"""Fixed, no-argument RQ-03F Operator preflight launcher.

The production path is installed root-owned and is started by a disabled
systemd unit. Candidate arguments, environment variables, executable/module
selection, and fallback authority files are never accepted. This C2 build
supports read-only preflight only; protected writes require the absent C3
AntiRollbackGate and therefore remain blocked.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


FIXED_MODULE = "rq03f_fixed_operator_launcher"
POLICY_MODULE = "rq03f_operator_launch_policy"
PROVIDER_MODULE = "rq03f_operator_trust_provider"
REQUIRED_PYTHON_FLAGS = ("isolated", "no_site", "dont_write_bytecode")
DANGEROUS_ENV = {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "PYTHONSTARTUP", "PYTHONINSPECT"}
ALLOWED_ENV = {"LANG", "LC_ALL", "TZ", "PATH", "HOME"}
PIN_PATH = Path("/etc/rq03f/launch-policy.pin.json")
POLICY_PATH = Path("/etc/rq03f/launch-policy.json")
POLICY_KEYS = {
    "policy_version", "authority_status", "owner_adopted_policy_source_identity",
    "source_commit", "generation", "controller", "profile", "operation_index",
    "runtime_closure", "dependency_inventory", "identities",
    "role_authorization_references", "revocation_references", "anti_rollback", "service",
}


class LauncherError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(value: bool, code: str, message: str) -> None:
    if not value:
        raise LauncherError(code, message)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "BUILD_JSON_DUPLICATE", "duplicate Build Inventory JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise LauncherError("BOOTSTRAP_JSON", "non-finite JSON is forbidden")


def _secure_fixed_read(path: Path, *, max_bytes: int = 64 * 1024 * 1024) -> bytes:
    """Safely read a fixed trust input before loading policy-selected code."""
    raw_path = str(path)
    if (not path.is_absolute() or raw_path != os.path.normpath(raw_path)
            or raw_path.startswith("//") or "//" in raw_path
            or "\\" in raw_path or "\x00" in raw_path
            or any(part in {".", ".."} for part in raw_path.split("/"))):
        raise LauncherError("BOOTSTRAP_PATH", "fixed bootstrap path is not canonical")
    cursor = Path(path.anchor)
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except OSError as exc:
            raise LauncherError("BOOTSTRAP_PATH", "fixed bootstrap path is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise LauncherError("BOOTSTRAP_PATH", "fixed bootstrap ownership or mode is unsafe")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise LauncherError("BOOTSTRAP_PATH", "fixed bootstrap ancestor is not a directory")
        if hasattr(os, "listxattr"):
            try:
                attrs = set(os.listxattr(cursor, follow_symlinks=False))
            except OSError as exc:
                raise LauncherError("BOOTSTRAP_ACL", "fixed bootstrap ACL state is unavailable") from exc
            if {"system.posix_acl_access", "system.posix_acl_default"} & attrs:
                raise LauncherError("BOOTSTRAP_ACL", "fixed bootstrap ACLs are forbidden")
    try:
        final = path.lstat()
        if not stat.S_ISREG(final.st_mode) or final.st_nlink != 1 or final.st_size > max_bytes:
            raise LauncherError("BOOTSTRAP_FILE", "fixed bootstrap file identity or size is unsafe")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    except LauncherError:
        raise
    except OSError as exc:
        raise LauncherError("BOOTSTRAP_FILE", "fixed bootstrap file could not be opened safely") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != 0
                or before.st_mode & 0o022 or before.st_size > max_bytes
                or (before.st_dev, before.st_ino) != (final.st_dev, final.st_ino)):
            raise LauncherError("BOOTSTRAP_FILE", "fixed bootstrap descriptor identity is unsafe")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            block = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
        after = os.fstat(fd)
        current = path.lstat()
        if (total > max_bytes
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino)):
            raise LauncherError("BOOTSTRAP_FILE_CHANGED", "fixed bootstrap file changed while being read")
        if path.resolve(strict=True) != path:
            raise LauncherError("BOOTSTRAP_PATH_ALIAS", "fixed bootstrap path resolves through an alias")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _read_build_inventory(state: Any) -> dict[str, Any]:
    build = state.policy["controller"]["build_inventory"]
    path = Path(build["path"])
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == build["sha256"],
             "BUILD_INVENTORY_SHA", "Build Inventory does not match the independently pinned policy")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LauncherError("BUILD_INVENTORY_JSON", "Build Inventory JSON is invalid") from exc
    _require(isinstance(payload, dict) and payload.get("build_inventory_version") == "1.1",
             "BUILD_INVENTORY_VERSION", "Build Inventory 1.1 is required")
    _require(payload.get("controller_id") == state.policy["controller"]["controller_id"],
             "BUILD_INVENTORY_CONTROLLER", "Build Inventory Controller ID mismatch")
    _require(Path(payload.get("controller_root", "")) == Path(state.policy["controller"]["root"]),
             "BUILD_INVENTORY_ROOT", "Build Inventory Controller Root mismatch")
    return payload


def _component(payload: dict[str, Any], path: Path, kind: str) -> dict[str, Any]:
    rows = [row for row in payload.get("components", [])
            if row.get("component_type") == kind and row.get("runtime_path") == str(path)]
    _require(len(rows) == 1, "BUILD_COMPONENT_MISSING", "fixed launcher dependency is not uniquely pinned")
    row = rows[0]
    _require(isinstance(row.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", row["sha256"]) is not None,
             "BUILD_COMPONENT_SHA", "fixed launcher dependency has an invalid SHA")
    return row


def _verify_component(payload: dict[str, Any], path: Path, kind: str) -> None:
    row = _component(payload, path, kind)
    _require(path.is_file() and _sha(path) == row["sha256"],
             "BUILD_COMPONENT_DRIFT", "fixed launcher dependency bytes differ from Build Inventory")


def _load_policy_module(controller_root: Path, payload: dict[str, Any]) -> Any:
    path = controller_root / "scripts" / f"{POLICY_MODULE}.py"
    _verify_component(payload, path, "python_module")
    spec = importlib.util.spec_from_file_location(POLICY_MODULE, path)
    _require(spec is not None and spec.loader is not None,
             "POLICY_MODULE_LOAD", "fixed Launch Policy validator cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[POLICY_MODULE] = module
    spec.loader.exec_module(module)
    return module


def _load_bootstrap(controller_root: Path, payload: dict[str, Any]) -> Any:
    path = controller_root / "scripts" / "operator_controller_bootstrap.py"
    _verify_component(payload, path, "python_module")
    spec = importlib.util.spec_from_file_location("operator_controller_bootstrap", path)
    _require(spec is not None and spec.loader is not None,
             "BOOTSTRAP_LOAD", "fixed isolated Bootstrap cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules["operator_controller_bootstrap"] = module
    spec.loader.exec_module(module)
    return module


def _preload_and_verify_closure(bootstrap: Any, payload: dict[str, Any]) -> None:
    """Load the complete pinned controller closure after Bootstrap narrows sys.path."""
    rows = {row["component_id"]: row for row in payload["components"]}
    for module_name in sorted(bootstrap.REQUIRED_MODULES):
        module = importlib.import_module(module_name)
        row = rows.get(module_name)
        _require(row is not None and row["component_type"] == "python_module",
                 "BUILD_MODULE_CLOSURE", "required controller module is absent from Build Inventory")
        _require(getattr(module, "__file__", None) is not None
                 and Path(module.__file__).resolve(strict=True) == Path(row["runtime_path"]).resolve(strict=True),
                 "MODULE_ORIGIN", "loaded controller module origin differs from pinned Build Inventory")
    for package_name in sorted(bootstrap.REQUIRED_PACKAGES):
        module = importlib.import_module(package_name)
        row = rows.get(package_name)
        _require(row is not None and row["component_type"] == "python_package",
                 "BUILD_PACKAGE_CLOSURE", "required Python package is absent from Build Inventory")
        loaded_path = Path(module.__file__).resolve(strict=True)
        expected_path = Path(row["runtime_path"]).resolve(strict=True)
        _require(loaded_path.is_relative_to(expected_path),
                 "PACKAGE_ORIGIN", "loaded validation package came from an unpinned path")
    for module_name in sorted(bootstrap.REQUIRED_DEPENDENCY_MODULES):
        module = importlib.import_module(module_name)
        row = rows.get(module_name)
        _require(row is not None and row["component_type"] == "python_dependency_module"
                 and Path(module.__file__).resolve(strict=True) == Path(row["runtime_path"]).resolve(strict=True),
                 "DEPENDENCY_ORIGIN", "loaded Python dependency module came from an unpinned path")


def _check_fixed_process(state: Any, policy_module: Any) -> None:
    _require(len(sys.argv) == 1, "ARGUMENTS_REFUSED", "fixed Operator Launcher accepts no arguments")
    _require(not (DANGEROUS_ENV & set(os.environ)),
             "PYTHON_ENV_REFUSED", "Python import and startup environment variables are forbidden")
    _require(set(os.environ) <= ALLOWED_ENV,
             "ENVIRONMENT_REFUSED", "unexpected process environment variable is forbidden")
    _require(all(getattr(sys.flags, flag) for flag in REQUIRED_PYTHON_FLAGS),
             "PYTHON_FLAGS", "Python must start with -I -S -B")
    policy_module.verify_os_identity(state.policy)
    policy_module.validate_runtime_paths(state.policy)
    # systemd service mode has no socket activation, notification, or inherited
    # trust descriptor. Readdir's short-lived descriptor may vanish before its
    # readlink; any descriptor that remains open beyond stdio is rejected.
    try:
        descriptors = os.listdir("/proc/self/fd")
    except OSError as exc:
        raise LauncherError("FD_INSPECTION", "inherited descriptor state is unavailable") from exc
    for name in descriptors:
        try:
            fd = int(name)
        except ValueError:
            continue
        if fd <= 2:
            continue
        try:
            os.readlink(f"/proc/self/fd/{fd}")
        except FileNotFoundError:
            continue
        _require(False, "INHERITED_FD", "unexpected inherited file descriptor is open")


def _validate_c2_component_closure(state: Any, payload: dict[str, Any]) -> None:
    controller_root = Path(state.policy["controller"]["root"])
    schema_dir = controller_root / "schemas"
    _verify_component(payload, controller_root / "scripts" / f"{FIXED_MODULE}.py", "python_module")
    _verify_component(payload, controller_root / "scripts" / f"{POLICY_MODULE}.py", "python_module")
    _verify_component(payload, controller_root / "scripts" / f"{PROVIDER_MODULE}.py", "python_module")
    for name in ("rq03f-operator-launch-policy-v1.0.schema.json",
                 "rq03f-operator-policy-pin-v1.0.schema.json"):
        _verify_component(payload, schema_dir / name, "json_schema")
    entrypoint_path = Path(state.policy["controller"]["fixed_entrypoint"]["module_path"])
    _require(_sha(entrypoint_path) == state.policy["controller"]["fixed_entrypoint"]["module_sha256"],
             "ENTRYPOINT_SHA", "fixed entrypoint SHA differs from Launch Policy")
    _require(Path(__file__).resolve(strict=True)
             == Path(state.policy["controller"]["fixed_entrypoint"]["module_path"]).resolve(strict=True),
             "LAUNCHER_PATH_DRIFT", "running launcher path differs from fixed policy")


def _log(*, code: str, stage: str, uid: int, policy_sha256: str | None,
         build_sha256: str | None, status: str) -> None:
    record = {
        "at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage": stage,
        "status": status,
        "error_code": code,
        "operator_uid": uid,
        "policy_sha256": policy_sha256,
        "build_inventory_sha256": build_sha256,
        "protected_operation_performed": False,
    }
    stream = sys.stdout if status == "preflight_pass" else sys.stderr
    print(json.dumps(record, sort_keys=True, separators=(",", ":")), file=stream)


def main() -> int:
    policy_sha: str | None = None
    build_sha: str | None = None
    stage = "fixed_launcher"
    state = None
    try:
        _require(len(sys.argv) == 1, "ARGUMENTS_REFUSED", "fixed Operator Launcher accepts no arguments")
        _require(not (DANGEROUS_ENV & set(os.environ)),
                 "PYTHON_ENV_REFUSED", "Python import and startup environment variables are forbidden")
        _require(set(os.environ) <= ALLOWED_ENV,
                 "ENVIRONMENT_REFUSED", "unexpected process environment variable is forbidden")
        # This script is the fixed root-owned bootstrap path. Its adjacent
        # standard-library-only policy validator is checked against the raw
        # Build Inventory before it is executed.
        controller_root = Path(__file__).resolve(strict=True).parent.parent
        initial = _load_policy_module(controller_root, _preparse_build_from_fixed_pin())
        state = initial.load_pinned_state(Path(__file__))
        policy_sha = state.policy_sha256
        build_sha = state.policy["controller"]["build_inventory"]["sha256"]
        _check_fixed_process(state, initial)
        stage = "build_inventory_preflight"
        payload = _read_build_inventory(state)
        _validate_c2_component_closure(state, payload)
        bootstrap = _load_bootstrap(controller_root, payload)
        bootstrap_payload = bootstrap.prepare_isolated_runtime(
            Path(state.policy["controller"]["build_inventory"]["path"]),
            state.policy["controller"]["build_inventory"]["sha256"],
            Path(state.policy["controller"]["root"]),
        )
        _preload_and_verify_closure(bootstrap, payload)
        stage = "schema_and_provider_preflight"
        initial.validate_schema_bytes(state.policy_raw, state.pin_raw)
        _require(bootstrap_payload["build_inventory_version"] == "1.1",
                 "BOOTSTRAP_RESULT", "isolated Bootstrap returned an unexpected inventory")
        provider_path = controller_root / "scripts" / f"{PROVIDER_MODULE}.py"
        _verify_component(payload, provider_path, "python_module")
        provider_module = importlib.import_module(PROVIDER_MODULE)
        _require(Path(provider_module.__file__).resolve(strict=True) == provider_path.resolve(strict=True),
                 "PROVIDER_IMPORT_PATH", "TrustContext Provider came from an unpinned path")
        provider = provider_module.OperatorTrustContextProvider(
            policy_loader=lambda: initial.load_pinned_state(Path(__file__)),
            initial_state=state,
        )
        import semantic_lifecycle
        from rq03f_operator_trust_provider import ProviderError
        with semantic_lifecycle.operator_context(provider):
            context = semantic_lifecycle.context()
            profile, _index = context.load()
            _require(profile["policy_epoch"] == state.policy["profile"]["policy_epoch"],
                     "PROVIDER_EPOCH", "TrustContext epoch differs from Launch Policy")
            # A second call demonstrates that lifecycle.context obtains a new
            # external TrustContext rather than reusing the first decision.
            _ = semantic_lifecycle.context()
        _log(code="PREFLIGHT_OK", stage="read_only_preflight", uid=os.getuid(),
             policy_sha256=policy_sha, build_sha256=build_sha, status="preflight_pass")
        return 0
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        code = getattr(exc, "code", None) or "PREFLIGHT_BLOCKED"
        _log(code=str(code), stage=stage, uid=getattr(os, "getuid", lambda: -1)(),
             policy_sha256=policy_sha, build_sha256=build_sha, status="blocked")
        return 2


def _preparse_build_from_fixed_pin() -> dict[str, Any]:
    """Read only enough pinned policy to locate and check this module.

    The real parser then performs all closed-schema/path/identity checks. The
    Policy Pin path itself is a compile-time constant in the validator module.
    """
    pin_path = PIN_PATH
    policy_path = POLICY_PATH
    try:
        pin_raw = _secure_fixed_read(pin_path)
        pin = json.loads(pin_raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                         parse_constant=_reject_constant)
        if (not isinstance(pin, dict)
                or set(pin) != {"pin_version", "policy_identity", "policy_sha256", "adoption_status"}
                or pin.get("pin_version") != "rq03f-operator-policy-pin-1.0"
                or pin.get("adoption_status") not in {"candidate_only", "owner_adopted"}
                or not isinstance(pin.get("policy_identity"), str) or not pin["policy_identity"].strip()
                or not isinstance(pin.get("policy_sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", pin["policy_sha256"]) is None):
            raise LauncherError("POLICY_PIN_INVALID", "fixed independent Policy Pin is malformed")
        policy_raw = _secure_fixed_read(policy_path)
        if hashlib.sha256(policy_raw).hexdigest() != pin.get("policy_sha256"):
            raise LauncherError("POLICY_PIN_MISMATCH", "independent policy pin mismatch")
        policy = json.loads(policy_raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                            parse_constant=_reject_constant)
        if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
            raise LauncherError("POLICY_FIELDS", "fixed Launch Policy fields are incomplete or unknown")
        identity = policy.get("owner_adopted_policy_source_identity")
        if (not isinstance(identity, dict) or identity.get("policy_identity") != pin["policy_identity"]
                or identity.get("adoption_status") != pin["adoption_status"]):
            raise LauncherError("POLICY_IDENTITY_PIN_MISMATCH", "fixed Policy identity differs from independent Pin")
        controller = policy.get("controller")
        if not isinstance(controller, dict):
            raise LauncherError("POLICY_CONTROLLER", "fixed Controller binding is malformed")
        controller_root_raw = controller.get("root")
        if (not isinstance(controller_root_raw, str) or not controller_root_raw
                or controller_root_raw != os.path.normpath(controller_root_raw)
                or controller_root_raw.startswith("//") or "//" in controller_root_raw
                or "\\" in controller_root_raw or "\x00" in controller_root_raw):
            raise LauncherError("CONTROLLER_ROOT_PATH", "fixed Controller Root is not canonical")
        controller_root = Path(controller_root_raw)
        expected_root = Path(__file__).resolve(strict=True).parent.parent
        if (not controller_root.is_absolute() or str(controller_root) != os.path.normpath(str(controller_root))
                or controller_root != expected_root):
            raise LauncherError("CONTROLLER_ROOT_PATH", "fixed Launcher is outside the pinned Controller Root")
        build = controller.get("build_inventory")
        if (not isinstance(build, dict) or set(build) != {"key", "path", "sha256"}
                or not isinstance(build.get("path"), str)
                or not isinstance(build.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", build["sha256"]) is None):
            raise LauncherError("BUILD_INVENTORY_FIELDS", "fixed Build Inventory binding is malformed")
        build_path = Path(build["path"])
        if (not build_path.is_absolute() or str(build_path) != build["path"]
                or str(build_path) != os.path.normpath(str(build_path))
                or str(build_path).startswith("//") or "//" in str(build_path)
                or "\\" in str(build_path) or "\x00" in str(build_path)):
            raise LauncherError("BUILD_INVENTORY_PATH", "fixed Build Inventory path is not canonical")
        raw = _secure_fixed_read(build_path)
        if hashlib.sha256(raw).hexdigest() != build["sha256"]:
            raise LauncherError("BUILD_INVENTORY_SHA", "Build Inventory pin mismatch")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                             parse_constant=_reject_constant)
        if (not isinstance(payload, dict) or payload.get("build_inventory_version") != "1.1"
                or payload.get("controller_id") != controller.get("controller_id")
                or Path(payload.get("controller_root", "")) != controller_root):
            raise LauncherError("BUILD_INVENTORY_CONTROLLER", "protected Build Inventory binding is invalid")
        helper_path = controller_root / "scripts" / f"{POLICY_MODULE}.py"
        helpers = [row for row in payload.get("components", [])
                   if isinstance(row, dict) and row.get("component_id") == POLICY_MODULE
                   and row.get("component_type") == "python_module"
                   and row.get("runtime_path") == str(helper_path)]
        if (len(helpers) != 1 or not isinstance(helpers[0].get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", helpers[0]["sha256"]) is None
                or hashlib.sha256(_secure_fixed_read(helper_path)).hexdigest() != helpers[0]["sha256"]):
            raise LauncherError("POLICY_MODULE_PIN", "Policy validator is not pinned by protected Build Inventory")
        launcher_path = Path(__file__)
        launchers = [row for row in payload.get("components", [])
                     if isinstance(row, dict) and row.get("component_id") == FIXED_MODULE
                     and row.get("component_type") == "python_module"
                     and row.get("runtime_path") == str(launcher_path)]
        if (len(launchers) != 1
                or hashlib.sha256(_secure_fixed_read(launcher_path)).hexdigest() != launchers[0].get("sha256")):
            raise LauncherError("LAUNCHER_BUILD_PIN", "running Launcher differs from protected Build Inventory")
        return payload
    except LauncherError:
        raise
    except BaseException as exc:
        raise LauncherError("POLICY_BOOTSTRAP_READ", "fixed policy or Build Inventory could not be read") from exc


if __name__ == "__main__":
    sys.modules[FIXED_MODULE] = sys.modules[__name__]
    raise SystemExit(main())
