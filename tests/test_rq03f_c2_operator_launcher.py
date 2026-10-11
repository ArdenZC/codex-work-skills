from __future__ import annotations

import configparser
import copy
from contextlib import redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import stat
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch

CONTROLLER_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "教案生成器"
    / "lesson-plan-docx-generator"
    / "scripts"
)
if str(CONTROLLER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CONTROLLER_SCRIPTS))

from rq03f_operator_launch_policy import (
    LaunchPolicyError,
    PIN_VERSION,
    POLICY_VERSION,
    canonical_bytes,
    validate_pin_payload,
    validate_policy_payload,
)
from rq03f_operator_trust_provider import (
    ProviderError,
    ReadOnlyPreflightTrustContext,
    _verify_runtime_closure,
    _append_only,
    require_protected_write,
)
import rq03f_operator_trust_provider as trust_provider
import rq03f_operator_launch_policy as launch_policy
import rq03f_fixed_operator_launcher as fixed_launcher
from lifecycle_digest import schema_errors
from semantic_scope_records import RecordError, TrustContext


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "schemas"
UNIT = ROOT / "systemd" / "rq03f-operator-preflight.service"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def valid_policy() -> dict:
    generation = "/opt/rq03f/generations/rq03f-test-0001"
    controller_root = generation + "/controller"
    runtime_root = generation + "/runtime"
    protected = "/var/lib/rq03f/test-trust"
    roles = [
        ("scope-reviewer", "scope_reviewer"),
        ("content-author", "author"),
        ("qualification-approver", "qualification_approver"),
        ("operator-custodian", "qualification_corpus_custodian"),
    ]
    role_rows = [{
        "principal_id": principal,
        "authorization_reference": "auth-" + principal,
        "authorization_sha256": _sha("auth-" + principal),
        "allowed_roles": [role],
    } for principal, role in roles]
    return {
        "policy_version": POLICY_VERSION,
        "authority_status": "candidate_only_not_owner_authority",
        "owner_adopted_policy_source_identity": {
            "adoption_status": "candidate_only",
            "policy_identity": "rq03f-test-policy",
            "source_commit": "a" * 40,
        },
        "source_commit": "a" * 40,
        "generation": {
            "generation_id": "rq03f-test-0001",
            "final_path": generation,
            "operation_root": generation + "/operations",
        },
        "controller": {
            "controller_id": "rq03f-test-controller",
            "implementation": "fixed-operator-launcher",
            "version": "1.0",
            "root": controller_root,
            "runtime_root": runtime_root,
            "python_executable": runtime_root + "/bin/python",
            "build_inventory": {"key": "controller_build_inventory", "path": protected + "/build.json", "sha256": _sha("build")},
            "controller_allowlist": [{
                "controller_id": "rq03f-test-controller",
                "implementation": "fixed-operator-launcher",
                "version": "1.0",
            }],
            "fixed_entrypoint": {
                "entrypoint_id": "rq03f-operator-preflight-v1",
                "operation": "read_only_preflight",
                "module_path": controller_root + "/scripts/rq03f_fixed_operator_launcher.py",
                "module_sha256": _sha("launcher"),
            },
        },
        "profile": {"version": "1.1", "path": protected + "/authority-profile.json", "sha256": _sha("profile"), "policy_epoch": 1},
        "operation_index": {"version": "1.1", "path": protected + "/operation-index.json", "initial_adoption_sha256": _sha("index"), "consistency": "current_append_only_each_operation"},
        "runtime_closure": {
            "path": protected + "/runtime-closure.json",
            "sha256": _sha("runtime-closure"),
            "base_image_digest_claim": "sha256:" + "0" * 64,
            "os_package_manifest_sha256": _sha("packages"),
            "shared_libraries_manifest_sha256": _sha("libraries"),
            "authority_status": "candidate_only_unverified_host_claims",
        },
        "dependency_inventory": {
            "path": protected + "/dependency-inventory.json",
            "sha256": _sha("dependency-inventory"),
            "run_root": generation + "/operations",
            "protected_roots": [protected, "/etc/rq03f", controller_root, runtime_root],
        },
        "identities": {
            "operator": {"principal_id": "operator-custodian", "uid": 4601, "gid": 4601},
            "candidate": {"principal_id": "candidate-process", "uid": 4602, "gid": 4602},
            "author": {"principal_id": "content-author", "uid": 4603, "gid": 4603},
            "reviewer": {"principal_id": "scope-reviewer", "uid": 4604, "gid": 4604},
            "approver": {"principal_id": "qualification-approver", "uid": 4605, "gid": 4605},
        },
        "role_authorization_references": role_rows,
        "revocation_references": {
            "inventory_key": "authority_profile",
            "fields": ["revoked_authority_ids", "roles[].revoked_at", "roles[].revocation_reason"],
            "recheck_each_operation": True,
        },
        "anti_rollback": {
            "required": True,
            "interface": "rq03f-c3-anti-rollback-gate-v1",
            "production_writes_allowed": False,
            "absent_behavior": "block",
        },
        "service": {"disabled_by_default": True, "install_or_start_authorized": False},
    }


class LauncherFailureLogTests(unittest.TestCase):
    def test_failure_log_includes_bounded_exception_types_without_messages(self):
        cause = RuntimeError("sensitive /private/holdout/path")
        error = ValueError("candidate supplied secret-value")
        error.__cause__ = cause
        stream = io.StringIO()
        with redirect_stderr(stream):
            fixed_launcher._log(
                code="PREFLIGHT_BLOCKED",
                stage="provider_preflight",
                uid=4601,
                policy_sha256=_sha("policy"),
                build_sha256=_sha("build"),
                status="blocked",
                exception_type_chain=fixed_launcher._exception_type_chain(error),
                exception_sites=fixed_launcher._exception_sites(error),
            )
        row = json.loads(stream.getvalue())
        self.assertEqual(row["exception_type_chain"], ["ValueError", "RuntimeError"])
        self.assertLessEqual(len(row["exception_sites"]), 8)
        self.assertTrue(all(set(site) == {"module", "function", "line"}
                            for site in row["exception_sites"]))
        self.assertEqual(row["error_code"], "PREFLIGHT_BLOCKED")
        self.assertFalse(row["protected_operation_performed"])
        self.assertNotIn("sensitive", stream.getvalue())
        self.assertNotIn("holdout", stream.getvalue())
        self.assertNotIn("secret-value", stream.getvalue())
        self.assertNotIn("/private/", stream.getvalue())


class RuntimeClosureBindingTests(unittest.TestCase):
    def test_python_executable_sha_comes_from_pinned_build_inventory(self):
        executable = b"synthetic pinned Python executable"
        os_release = b"synthetic os-release"
        packages = b"synthetic package manifest"
        libraries = b"synthetic shared-library manifest"
        executable_path = "/generation/runtime/bin/python"
        closure = {
            "schema_version": "rq03f-runtime-closure-candidate-1.0",
            "authority_status": "candidate_only_unverified_host_claims",
            "source_commit": "a" * 40,
            "build_inventory_sha256": _sha("build-inventory"),
            "base_image_digest_claim": "sha256:" + "0" * 64,
            "os_release_path": "/evidence/os-release",
            "os_release_sha256": hashlib.sha256(os_release).hexdigest(),
            "python_executable": executable_path,
            "python_version": "3.12.0",
            "python_stdlib_root": "/generation/runtime/lib/python3.12",
            "python_stdlib_tree_sha256": _sha("stdlib-tree"),
            "runtime_root": "/generation/runtime",
            "runtime_root_tree_sha256": _sha("runtime-tree"),
            "os_package_manifest_path": "/evidence/packages.txt",
            "os_package_manifest_sha256": hashlib.sha256(packages).hexdigest(),
            "shared_libraries_manifest_path": "/evidence/libraries.txt",
            "shared_libraries_manifest_sha256": hashlib.sha256(libraries).hexdigest(),
        }
        closure_raw = json.dumps(closure, sort_keys=True, separators=(",", ":")).encode()
        contents = {
            Path("/evidence/runtime-closure.json"): closure_raw,
            Path("/evidence/os-release"): os_release,
            Path("/evidence/packages.txt"): packages,
            Path("/evidence/libraries.txt"): libraries,
            Path(executable_path): executable,
        }
        policy = {
            "runtime_closure": {
                "path": "/evidence/runtime-closure.json",
                "sha256": hashlib.sha256(closure_raw).hexdigest(),
                "base_image_digest_claim": closure["base_image_digest_claim"],
                "os_package_manifest_sha256": closure["os_package_manifest_sha256"],
                "shared_libraries_manifest_sha256": closure["shared_libraries_manifest_sha256"],
            },
            "source_commit": closure["source_commit"],
            "controller": {
                "python_executable": executable_path,
                "runtime_root": closure["runtime_root"],
                "build_inventory": {"sha256": closure["build_inventory_sha256"]},
            },
        }
        build = {"python_runtime": {
            "python_executable": executable_path,
            "python_executable_sha256": hashlib.sha256(executable).hexdigest(),
        }}

        with patch("rq03f_operator_trust_provider._read_file",
                   side_effect=lambda path, **_kwargs: (contents[Path(path)], None)), \
                patch("rq03f_operator_trust_provider._tree_sha",
                      side_effect=lambda path, **_kwargs: {
                          "/generation/runtime": _sha("runtime-tree"),
                          "/generation/runtime/lib/python3.12": _sha("stdlib-tree"),
                      }[str(path)]):
            _verify_runtime_closure(policy, build)

            build["python_runtime"]["python_executable_sha256"] = _sha("wrong executable")
            with self.assertRaisesRegex(RecordError, "Python executable bytes differ"):
                _verify_runtime_closure(policy, build)

    def test_root_owned_runtime_file_symlink_hashes_target_not_link_mode_bits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            root.mkdir()
            target = Path(temporary) / "target.py"
            target.write_bytes(b"pinned runtime module")
            link = root / "module.py"
            link.symlink_to(target)
            original_lstat = Path.lstat

            class LinkInfo:
                st_mode = stat.S_IFLNK | 0o777
                st_uid = 0

            def lstat(path: Path):
                if path == link:
                    return LinkInfo()
                return original_lstat(path)

            with patch.object(launch_policy, "inspect_path"), \
                    patch.object(Path, "lstat", autospec=True, side_effect=lstat), \
                    patch.object(trust_provider, "_read_file",
                                 return_value=(b"pinned runtime module", None)):
                digest = trust_provider._tree_sha(root)

        expected = json.dumps([{
            "path": "module.py", "kind": "symlink", "target": str(target),
            "target_sha256": hashlib.sha256(b"pinned runtime module").hexdigest(),
        }], ensure_ascii=False, separators=(",", ":")).encode()
        self.assertEqual(digest, hashlib.sha256(expected).hexdigest())


class LaunchPolicyContractTests(unittest.TestCase):
    def test_policy_schema_and_pin_schema_are_closed_json_schemas(self):
        policy_schema = json.loads((SCHEMAS / "rq03f-operator-launch-policy-v1.0.schema.json").read_text())
        pin_schema = json.loads((SCHEMAS / "rq03f-operator-policy-pin-v1.0.schema.json").read_text())
        self.assertFalse(policy_schema["additionalProperties"])
        self.assertFalse(pin_schema["additionalProperties"])
        self.assertEqual(policy_schema["properties"]["policy_version"]["const"], POLICY_VERSION)
        self.assertEqual(pin_schema["properties"]["pin_version"]["const"], PIN_VERSION)
        self.assertIn("authorization_sha256", policy_schema["properties"]["role_authorization_references"]["items"]["required"])

    def test_prebootstrap_reader_rejects_candidate_writable_ancestors(self):
        with self.assertRaisesRegex(fixed_launcher.LauncherError, "fixed bootstrap ownership or mode"):
            fixed_launcher._secure_fixed_read(Path("/tmp/candidate-controlled-pin.json"))

    def test_bootstrap_policy_and_pin_locations_are_compile_time_constants(self):
        self.assertEqual(fixed_launcher.PIN_PATH, Path("/etc/rq03f/launch-policy.pin.json"))
        self.assertEqual(fixed_launcher.POLICY_PATH, Path("/etc/rq03f/launch-policy.json"))

    def test_valid_policy_satisfies_manual_closed_contract(self):
        policy = valid_policy()
        validate_policy_payload(policy)
        self.assertEqual(schema_errors(policy, "rq03f-operator-launch-policy-v1.0.schema.json"), [])
        pin = {"pin_version": PIN_VERSION, "policy_identity": "rq03f-test-policy",
               "policy_sha256": _sha("policy"), "adoption_status": "candidate_only"}
        self.assertEqual(schema_errors(pin, "rq03f-operator-policy-pin-v1.0.schema.json"), [])

    def test_missing_and_unknown_top_level_fields_are_rejected(self):
        missing = valid_policy()
        del missing["service"]
        with self.assertRaisesRegex(LaunchPolicyError, "missing or unknown"):
            validate_policy_payload(missing)
        unknown = valid_policy()
        unknown["candidate_override"] = True
        with self.assertRaisesRegex(LaunchPolicyError, "missing or unknown"):
            validate_policy_payload(unknown)

    def test_dot_dot_empty_and_noncanonical_paths_are_rejected(self):
        for raw in ("", ".", "..", "/opt/rq03f/../escape", "/opt/rq03f//alias"):
            with self.subTest(raw=raw):
                payload = valid_policy()
                payload["generation"]["final_path"] = raw
                with self.assertRaises(LaunchPolicyError):
                    validate_policy_payload(payload)

    def test_generation_and_fixed_operation_roots_cannot_alias(self):
        payload = valid_policy()
        payload["generation"]["operation_root"] = payload["generation"]["final_path"] + "/controller"
        with self.assertRaisesRegex(LaunchPolicyError, "run root differs"):
            validate_policy_payload(payload)

    def test_final_controller_runtime_and_executable_paths_are_bound(self):
        payload = valid_policy()
        payload["controller"]["root"] = "/opt/rq03f/elsewhere"
        with self.assertRaisesRegex(LaunchPolicyError, "differs from the final Generation"):
            validate_policy_payload(payload)
        payload = valid_policy()
        payload["controller"]["python_executable"] = "/usr/bin/python3"
        with self.assertRaisesRegex(LaunchPolicyError, "outside the final Runtime Root"):
            validate_policy_payload(payload)

    def test_controller_entrypoint_is_fixed_and_read_only(self):
        payload = valid_policy()
        payload["controller"]["fixed_entrypoint"]["operation"] = "intake"
        with self.assertRaisesRegex(LaunchPolicyError, "only the fixed read-only"):
            validate_policy_payload(payload)
        payload = valid_policy()
        payload["controller"]["fixed_entrypoint"]["module_path"] = "/tmp/candidate.py"
        with self.assertRaises(LaunchPolicyError):
            validate_policy_payload(payload)

    def test_unpinned_controller_tuple_is_rejected(self):
        payload = valid_policy()
        payload["controller"]["controller_allowlist"][0]["version"] = "9.9"
        with self.assertRaisesRegex(LaunchPolicyError, "not exactly allowlisted"):
            validate_policy_payload(payload)

    def test_unique_os_and_principal_identity_is_required(self):
        payload = valid_policy()
        payload["identities"]["candidate"]["uid"] = payload["identities"]["operator"]["uid"]
        with self.assertRaisesRegex(LaunchPolicyError, "unique UIDs and GIDs"):
            validate_policy_payload(payload)
        payload = valid_policy()
        payload["identities"]["candidate"]["principal_id"] = payload["identities"]["operator"]["principal_id"]
        with self.assertRaisesRegex(LaunchPolicyError, "principal IDs must be distinct"):
            validate_policy_payload(payload)

    def test_operator_role_is_custodian_only(self):
        payload = valid_policy()
        operator_row = next(row for row in payload["role_authorization_references"]
                            if row["principal_id"] == "operator-custodian")
        operator_row["allowed_roles"] = ["qualification_corpus_custodian", "author"]
        with self.assertRaisesRegex(LaunchPolicyError, "only qualification corpus custodian"):
            validate_policy_payload(payload)

    def test_role_authorization_hash_is_required(self):
        payload = valid_policy()
        del payload["role_authorization_references"][0]["authorization_sha256"]
        with self.assertRaisesRegex(LaunchPolicyError, "reference is malformed"):
            validate_policy_payload(payload)

    def test_profile_and_index_contracts_are_versioned_and_index_current_is_append_only(self):
        payload = valid_policy()
        payload["profile"]["version"] = "1.0"
        with self.assertRaisesRegex(LaunchPolicyError, "Profile 1.1"):
            validate_policy_payload(payload)
        payload = valid_policy()
        payload["operation_index"]["consistency"] = "immutable_snapshot"
        with self.assertRaisesRegex(LaunchPolicyError, "Index 1.1 current-state"):
            validate_policy_payload(payload)

    def test_runtime_closure_remains_candidate_only(self):
        payload = valid_policy()
        payload["runtime_closure"]["authority_status"] = "production_verified"
        with self.assertRaisesRegex(LaunchPolicyError, "Runtime Closure pin"):
            validate_policy_payload(payload)

    def test_c3_gate_is_mandatory_and_cannot_be_replaced_by_boolean(self):
        payload = valid_policy()
        payload["anti_rollback"]["production_writes_allowed"] = True
        with self.assertRaisesRegex(LaunchPolicyError, "C3 AntiRollbackGate"):
            validate_policy_payload(payload)

        class FakeGate:
            def check_current_state(self, **_kwargs):
                return True

        for gate in (None, FakeGate()):
            with self.subTest(gate=gate), self.assertRaisesRegex(ProviderError, "until C3"):
                require_protected_write(gate, operation_purpose="production_authoring")

    def test_even_a_verified_c3_gate_does_not_enable_c2_protected_writes(self):
        from tests.test_rq03f_c3_monotonic_trust_ledger import (
            AUTHORITY as TEST_AUTHORITY,
            MemoryProjection,
            MemoryWitness,
            base_index,
            encode_json,
            genesis_record,
            initial_state,
        )
        from rq03f_monotonic_trust_ledger import (
            LedgerRequest,
            MonotonicAntiRollbackGate,
        )

        index_raw = encode_json(base_index())
        state = initial_state(index_raw)
        witness = MemoryWitness(state)
        projection = MemoryProjection(index_raw, [genesis_record(state)])
        gate = MonotonicAntiRollbackGate(
            authority=witness,
            expected_authority_identity=TEST_AUTHORITY,
            ledger_reader=projection.read_ledger,
            index_reader=projection.read_index,
            recovery_reader=projection.recovery_required,
        )

        class CandidateProviderFixture(trust_provider.OperatorTrustContextProvider):
            def __call__(self):
                return "read-only-context"

            def _gate_request(self, purpose):
                return LedgerRequest(**(self.request_values | {"operation_purpose": purpose}))

        provider = object.__new__(CandidateProviderFixture)
        provider._anti_rollback_gate = gate
        provider.request_values = {
            "policy_identity": state.policy_identity,
            "policy_epoch": state.policy_epoch,
            "profile_sha256": state.profile_sha256,
            "build_inventory_sha256": state.build_inventory_sha256,
            "controller_id": state.controller_id,
            "generation_id": state.generation_id,
            "index_sha256": state.index_sha256,
            "revocation_state_sha256": state.revocation_state_sha256,
        }
        result = gate.check_current_state(**provider._gate_request("production_authoring").__dict__)
        self.assertEqual(result.decision, "verified")
        with self.assertRaises(ProviderError) as raised:
            provider.context_for_operation("production_authoring")
        self.assertEqual(raised.exception.code, "C3_ANTI_ROLLBACK_GATE_REQUIRED")

    def test_read_only_provider_context_cannot_issue_any_protected_role(self):
        context = ReadOnlyPreflightTrustContext(
            inventory=None,
            profile_path=Path("/protected/profile.json"),
            profile_pin=_sha("profile"),
            policy_epoch=1,
            operation_index_path=Path("/protected/index.json"),
            controller_allowlist=(),
            now=datetime.now(timezone.utc),
        )
        self.assertIsInstance(context, TrustContext)
        refreshed = replace(context, now=datetime.now(timezone.utc))
        self.assertIsInstance(refreshed, ReadOnlyPreflightTrustContext)
        for role in ("qualification_corpus_custodian", "author", "scope_reviewer", "qualification_approver"):
            with self.subTest(role=role), self.assertRaises(ProviderError) as raised:
                refreshed.role("operator", role)
            self.assertEqual(raised.exception.code, "C3_ANTI_ROLLBACK_GATE_REQUIRED")

    def test_service_must_remain_disabled_and_uninstalled(self):
        payload = valid_policy()
        payload["service"]["install_or_start_authorized"] = True
        with self.assertRaisesRegex(LaunchPolicyError, "disabled and uninstalled"):
            validate_policy_payload(payload)

    def test_independent_pin_rejects_missing_unknown_and_invalid_sha(self):
        pin = {"pin_version": PIN_VERSION, "policy_identity": "candidate", "policy_sha256": _sha("p"), "adoption_status": "candidate_only"}
        validate_pin_payload(pin)
        malformed = copy.deepcopy(pin)
        malformed["policy_sha256"] = "placeholder"
        with self.assertRaisesRegex(LaunchPolicyError, "malformed"):
            validate_pin_payload(malformed)
        malformed = copy.deepcopy(pin)
        malformed["untrusted_owner_input"] = True
        with self.assertRaisesRegex(LaunchPolicyError, "malformed"):
            validate_pin_payload(malformed)

    def test_index_append_is_accepted_but_rewrite_delete_reorder_or_version_change_is_rejected(self):
        initial = {
            "index_version": "1.1", "controller_id": "c", "policy_epoch": 1,
            "receipts": [], "authors": [], "adjudications": [],
            "qualification_runs": [], "qualification_corpus_intakes": [],
        }
        appended = copy.deepcopy(initial)
        appended["qualification_runs"].append({"run_id": "run-1", "operations": []})
        _append_only(canonical_bytes(initial), canonical_bytes(appended))
        mutated = copy.deepcopy(appended)
        mutated["qualification_runs"][0]["run_id"] = "rewritten"
        with self.assertRaises(Exception):
            _append_only(canonical_bytes(appended), canonical_bytes(mutated))
        with self.assertRaises(Exception):
            _append_only(canonical_bytes(appended), canonical_bytes(initial))
        wrong_version = copy.deepcopy(appended)
        wrong_version["index_version"] = "1.0"
        with self.assertRaises(Exception):
            _append_only(canonical_bytes(appended), canonical_bytes(wrong_version))

    def test_systemd_candidate_unit_is_disabled_fixed_and_write_restricted(self):
        raw = UNIT.read_text(encoding="utf-8")
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read_string(raw)
        service = parser["Service"]
        self.assertNotIn("Install", parser)
        self.assertEqual(service["User"], "rq03f-operator")
        self.assertEqual(service["Group"], "rq03f-operator")
        self.assertIn(" -I -S -B ", " " + service["ExecStart"] + " ")
        self.assertNotIn("EnvironmentFile", service)
        self.assertEqual(service["NoNewPrivileges"], "yes")
        self.assertTrue({"PYTHONPATH", "PYTHONHOME", "USER", "LOGNAME", "INVOCATION_ID", "JOURNAL_STREAM"}
                        <= set(service["UnsetEnvironment"].split()))
        self.assertEqual(service["CapabilityBoundingSet"], "")
        self.assertEqual(service["ProtectSystem"], "strict")
        self.assertEqual(service["RestrictAddressFamilies"], "AF_UNIX")
        self.assertEqual(service["Restart"], "no")
        self.assertRegex(service["ExecStart"], r"^/opt/rq03f/generations/rq03f-candidate-0001/runtime/bin/python -I -S -B /opt/rq03f/generations/rq03f-candidate-0001/controller/scripts/rq03f_fixed_operator_launcher\.py$")


@unittest.skipUnless(sys.platform.startswith("linux"), "secure source copier requires Linux dirfd flags")
class HostedSourceCopyTests(unittest.TestCase):
    def _copy(self, source: Path, destination: Path) -> None:
        from tools.rq03f_c2.hosted_linux_isolation import copy_source_tree

        copy_source_tree(source, destination)

    def test_source_copy_preserves_only_exact_regular_file_bytes(self):
        with tempfile.TemporaryDirectory(prefix="rq03f-c2-copy-") as temp:
            root = Path(temp)
            source = root / "source"
            (source / "nested").mkdir(parents=True)
            (source / "nested" / "module.py").write_bytes(b"trusted fixture bytes\n")
            destination = root / "destination"
            self._copy(source, destination)
            self.assertEqual((destination / "nested" / "module.py").read_bytes(), b"trusted fixture bytes\n")

    def test_source_copy_refuses_symlink_without_reading_target(self):
        with tempfile.TemporaryDirectory(prefix="rq03f-c2-copy-") as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "outside-link").symlink_to("/etc/passwd")
            with self.assertRaisesRegex(RuntimeError, "symlink or special"):
                self._copy(source, root / "destination")

    def test_source_copy_refuses_hardlinked_file(self):
        with tempfile.TemporaryDirectory(prefix="rq03f-c2-copy-") as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            outside = root / "outside.py"
            outside.write_bytes(b"candidate content\n")
            os.link(outside, source / "module.py")
            with self.assertRaisesRegex(RuntimeError, "hard-linked file"):
                self._copy(source, root / "destination")

    def test_hosted_venv_removes_only_the_standard_lib64_alias(self):
        from tools.rq03f_c2.hosted_linux_isolation import remove_generated_venv_lib64_alias

        with tempfile.TemporaryDirectory(prefix="rq03f-c2-venv-") as temp:
            runtime = Path(temp) / "runtime"
            (runtime / "lib").mkdir(parents=True)
            (runtime / "lib64").symlink_to("lib", target_is_directory=True)
            self.assertTrue(remove_generated_venv_lib64_alias(runtime))
            self.assertFalse((runtime / "lib64").exists())
            self.assertFalse(remove_generated_venv_lib64_alias(runtime))

            (runtime / "lib64").symlink_to("unexpected", target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "exact generated lib alias"):
                remove_generated_venv_lib64_alias(runtime)

            (runtime / "lib64").unlink()
            (runtime / "lib64").mkdir()
            with self.assertRaisesRegex(RuntimeError, "exact generated lib alias"):
                remove_generated_venv_lib64_alias(runtime)

    def test_git_blob_manifest_copies_only_exact_committed_source_bytes(self):
        from tools.rq03f_c2.hosted_linux_isolation import (
            GIT_ENV,
            _git_readonly_args,
            _git_source_blob_manifest,
            copy_source_tree,
        )

        git_args = _git_readonly_args("rev-parse", "--verify", "HEAD^{commit}")
        self.assertEqual(git_args[:4], ["/usr/bin/git", "-c", f"safe.directory={ROOT}", "-C"])
        commit = subprocess.run(
            git_args,
            env=GIT_ENV,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        source = ROOT / "tools" / "rq03f_c1"
        expected = _git_source_blob_manifest(source, commit)
        self.assertIn("operator_allocator.py", expected)
        with tempfile.TemporaryDirectory(prefix="rq03f-c2-git-copy-") as temp:
            destination = Path(temp) / "copy"
            copy_source_tree(source, destination, expected_blobs=expected)
            self.assertEqual(
                (destination / "operator_allocator.py").read_bytes(),
                (source / "operator_allocator.py").read_bytes(),
            )


class HostedWorkflowFailurePropagationTests(unittest.TestCase):
    def test_root_harness_pipeline_propagates_python_failure(self):
        workflow = (ROOT / ".github" / "workflows" / "rq03f-b3c2-launcher-provider.yml").read_text(encoding="utf-8")
        step = workflow.split("- name: Run C2 synthetic Policy/Index with real Linux identities and filesystem permissions", 1)[1]
        step = step.split("\n      - name:", 1)[0]
        self.assertIn("set -euo pipefail", step)
        self.assertLess(step.index("set -euo pipefail"), step.index("python tools/rq03f_c2/hosted_linux_isolation.py"))
        self.assertIn("| tee \"$RUNNER_TEMP/rq03f-c2-evidence/rq03f-b3c2-hosted-evidence.json\"", step)


if __name__ == "__main__":
    unittest.main()
