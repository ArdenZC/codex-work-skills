"""Opt-in deterministic Semantic Scope Review records; no production integration.

TrustContext must be supplied by an operator-controlled caller. These helpers
verify process records; they cannot establish filesystem ACLs or human identity.
Candidate metadata is never used to select the profile, pin or operation index.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
import unicodedata

from lifecycle_digest import (
    LifecycleContractError,
    assert_distinct_safe_paths,
    canonical_json_bytes,
    schema_errors,
    semantic_fingerprint,
    sha256_bytes,
    sha256_file,
)


class RecordError(LifecycleContractError):
    """Invalid evidence or authority (never a semantic judgment)."""


class StaleEvidence(RecordError):
    """Structurally valid evidence bound to changed input bytes."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def stamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RecordError("invalid date-time") from exc
    require(
        result.tzinfo is not None and result.utcoffset() is not None,
        "timezone required",
    )
    return result


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        normalized = unicodedata.normalize("NFC", key)
        require(normalized not in result, "duplicate/NFC-colliding JSON keys")
        result[normalized] = value
    return result


def _number(value: str) -> None:
    raise RecordError("floating/non-finite JSON numbers prohibited")


def parse(raw: bytes, *, allow_floats: bool = True) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=float if allow_floats else _number,
            parse_constant=_number,
        )
    except (UnicodeError, ValueError) as exc:
        raise RecordError(f"invalid JSON bytes: {exc}") from exc


@lru_cache(maxsize=1024)
def _schema_check(raw: bytes, schema: str, schema_digest: str) -> tuple[str, ...]:
    return tuple(schema_errors(parse(raw, allow_floats=False), schema + ".schema.json"))


def checked(raw: bytes, schema: str) -> dict[str, Any]:
    # Cache only validation of exact bytes under exact schema bytes. Authority,
    # file hashes and time are always reread; callers receive a new mutable DTO.
    schema_path = (
        Path(__file__).resolve().parents[1] / "schemas" / (schema + ".schema.json")
    )
    errors = _schema_check(raw, schema, sha256_bytes(schema_path.read_bytes()))
    require(not errors, "; ".join(errors))
    return parse(raw, allow_floats=False)


def review_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(
        payload, excluded_fields={"reviewed_at", "review_fingerprint"}
    )


def qualification_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(
        payload, excluded_fields={"qualified_at", "qualification_fingerprint"}
    )


def configuration_fingerprint(raw: bytes) -> str:
    parsed = parse(raw, allow_floats=False)
    require(isinstance(parsed, dict), "reviewer configuration must be an object")
    version = parsed.get("configuration_version")
    schema = {
        "1.0": "reviewer-configuration",
        "1.1": "reviewer-configuration-v1.1",
    }.get(version)
    require(schema is not None, "unsupported reviewer configuration version")
    payload = checked(raw, schema)
    require(
        raw == canonical_json_bytes(payload),
        "configuration bytes must be canonical UTF-8 NFC JSON",
    )
    return sha256_bytes(raw)


def receipt_fingerprint(raw: bytes) -> str:
    """Receipts bind raw bytes; the contract defines no excluded-field cache."""
    parsed = parse(raw, allow_floats=False)
    require(isinstance(parsed, dict), "operation receipt must be an object")
    schema = {
        "1.0": "operation-provenance-receipt",
        "1.1": "operation-provenance-receipt-v1.1",
    }.get(parsed.get("contract_version"))
    require(schema is not None, "unsupported operation receipt version")
    checked(raw, schema)
    return sha256_bytes(raw)


@dataclass(frozen=True)
class Inventory:
    """Explicit controller-supplied dependency inventory and allowed roots.

    Roots and paths are configuration, never discovered in a candidate folder.
    The complete inventory is validated for ordinary, non-aliased files; raw
    hashes are reread whenever referenced. A shared dependency reuses one key.
    """

    entries: Mapping[str, Mapping[str, Any]]
    run_root: Path
    protected_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entries", {key: dict(row) for key, row in self.entries.items()}
        )
        errors = schema_errors(
            {"inventory_version": "1.0", "entries": list(self.entries.values())},
            "semantic-dependency-inventory.schema.json",
        )
        require(not errors, "; ".join(errors))
        require(
            all(key == row["inventory_key"] for key, row in self.entries.items()),
            "inventory key mismatch",
        )
        require(bool(self.protected_roots), "explicit protected repositories required")
        run = self.run_root.resolve(strict=True)
        for root in self.protected_roots:
            assert_distinct_safe_paths({"protected_root": root})
            protected = root.resolve(strict=True)
            require(
                not protected.is_relative_to(run) and not run.is_relative_to(protected),
                "protected repository overlaps candidate root",
            )
        paths: dict[str, Path] = {}
        for key, row in self.entries.items():
            path = Path(row["path"])
            require(
                path.is_absolute(),
                "inventory paths must be absolute controller-selected paths",
            )
            roots = (
                (self.run_root,)
                if row["storage_class"] == "run"
                else self.protected_roots
            )
            require(
                any(
                    path.resolve(strict=True).is_relative_to(r.resolve(strict=True))
                    for r in roots
                ),
                f"inventory path outside configured storage: {key}",
            )
            paths[key] = path
            sha256_file(path)  # ordinary file and existing path/alias protections
        assert_distinct_safe_paths(paths)
        object.__setattr__(
            self,
            "entries",
            MappingProxyType(
                {key: MappingProxyType(row) for key, row in self.entries.items()}
            ),
        )

    def namespace(self, aliases: Mapping[str, str]) -> Inventory:
        """A subset/rename view over already checked paths; introduce no new files.

        This avoids repeating quadratic alias checks for every evaluation case.
        Every subsequent read still performs ordinary-file checks and raw hashes.
        """
        require(
            all(key in self.entries for key in aliases.values()),
            "unknown case input key",
        )
        require(len(set(aliases.values())) == len(aliases), "aliased case inputs")
        entries = {
            key: dict(row)
            for key, row in self.entries.items()
            if key not in set(aliases) | set(aliases.values())
        }
        for canonical, original in aliases.items():
            entries[canonical] = {**self.entries[original], "inventory_key": canonical}
        view = object.__new__(Inventory)
        object.__setattr__(
            view,
            "entries",
            MappingProxyType(
                {key: MappingProxyType(row) for key, row in entries.items()}
            ),
        )
        object.__setattr__(view, "run_root", self.run_root)
        object.__setattr__(view, "protected_roots", self.protected_roots)
        return view

    def raw(
        self, key: str, expected: str | None = None, *, protected: bool = False
    ) -> bytes:
        require(key in self.entries, f"missing inventory entry: {key}")
        row = self.entries[key]
        require(
            not protected or row["storage_class"] == "protected_external",
            f"not protected evidence: {key}",
        )
        path = Path(row["path"])
        digest = sha256_file(path)
        raw = path.read_bytes()
        require(sha256_bytes(raw) == digest, f"file changed while reading: {key}")
        if digest != row["sha256"] or (expected is not None and digest != expected):
            raise StaleEvidence(f"changed raw-byte binding: {key}")
        return raw

    def by_sha(self, digest: str, *, protected: bool = False) -> bytes:
        keys = [
            k
            for k, row in self.entries.items()
            if row["sha256"] == digest
            and (not protected or row["storage_class"] == "protected_external")
        ]
        require(bool(keys), f"SHA has no actual inventory dependency: {digest}")
        return self.raw(keys[0], digest, protected=protected)

    def record(
        self, key: str, schema: str, *, protected: bool = False
    ) -> dict[str, Any]:
        return checked(self.raw(key, protected=protected), schema)


@dataclass(frozen=True)
class TrustContext:
    inventory: Inventory
    profile_path: Path
    profile_pin: str
    policy_epoch: int
    operation_index_path: Path
    controller_allowlist: tuple[tuple[str, str, str], ...]
    now: datetime

    def load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        require(
            self.now.tzinfo is not None and self.now.utcoffset() is not None,
            "current check needs timezone",
        )
        for path in (self.profile_path, self.operation_index_path):
            require(
                any(
                    path.resolve(strict=True).is_relative_to(root.resolve(strict=True))
                    for root in self.inventory.protected_roots
                ),
                "authority input outside protected repository",
            )
        assert_distinct_safe_paths(
            {"profile": self.profile_path, "index": self.operation_index_path}
        )
        require(
            sha256_file(self.profile_path) == self.profile_pin,
            "operator profile pin changed: INVALID authority",
        )
        profile = checked(self.profile_path.read_bytes(), "operator-authority-profile")
        require(
            profile["policy_epoch"] == self.policy_epoch,
            "stale policy epoch: INVALID authority",
        )
        require(
            (
                profile["controller_id"],
                profile["controller_implementation"],
                profile["controller_version"],
            )
            in self.controller_allowlist,
            "controller implementation/version not operator-allowlisted",
        )
        require(
            self.inventory.raw("authority_profile", self.profile_pin, protected=True)
            == self.profile_path.read_bytes(),
            "inventory profile differs from launch policy",
        )
        index_raw = self.inventory.raw("operation_index", protected=True)
        require(
            index_raw == self.operation_index_path.read_bytes(),
            "protected index path mismatch",
        )
        index = checked(index_raw, "protected-operation-index")
        require(
            index["controller_id"] == profile["controller_id"]
            and index["policy_epoch"] == self.policy_epoch,
            "protected index controller/epoch mismatch",
        )
        for field in (
            "operator_reference",
            "ingress_procedure_reference",
            "evidence_repository_reference",
        ):
            self.inventory.raw(profile[field], protected=True)
        principals = [r["principal_id"] for r in profile["roles"]]
        require(len(principals) == len(set(principals)), "duplicate profile principals")
        for row in profile["roles"]:
            require(
                stamp(row["valid_from"]) < stamp(row["valid_until"]),
                "invalid role validity",
            )
            require(
                row["revoked_at"] is None or row["revocation_reason"] is not None,
                "revocation requires reason",
            )
            authorization = checked(
                self.inventory.raw(row["authorization_reference"], protected=True),
                "operator-role-authorization",
            )
            require(
                authorization["principal_id"] == row["principal_id"]
                and set(authorization["allowed_roles"]) == set(row["allowed_roles"]),
                "operator role authorization mismatch",
            )
        for field, id_field in (
            ("receipts", "receipt_id"),
            ("authors", "authoring_id"),
            ("adjudications", "operation_id"),
            ("qualification_runs", "run_id"),
        ):
            ids = [r[id_field] for r in index[field]]
            require(len(ids) == len(set(ids)), f"duplicate protected index {field}")
        operations = [
            r["operation_id"]
            for group in ("receipts", "authors", "adjudications")
            for r in index[group]
        ]
        require(
            len(operations) == len(set(operations)), "reused protected operation ID"
        )
        return profile, index

    def not_revoked(self, *identifiers: str) -> None:
        profile, _ = self.load()
        require(
            not set(identifiers).intersection(profile["revoked_authority_ids"]),
            "revoked authority ID",
        )

    def role(
        self,
        principal: str,
        role: str,
        at: datetime | None = None,
        *,
        current_validity: bool = True,
    ) -> dict[str, Any]:
        profile, _ = self.load()
        rows = [r for r in profile["roles"] if r["principal_id"] == principal]
        require(
            len(rows) == 1 and role in rows[0]["allowed_roles"],
            f"{principal} lacks {role} role",
        )
        row = rows[0]
        require(
            not {principal, row["authorization_reference"]}.intersection(
                profile["revoked_authority_ids"]
            ),
            "revoked authority ID",
        )
        require(row["revoked_at"] is None, "revoked principal role")
        checks = [at or self.now]
        if current_validity:
            checks.append(self.now)
        require(
            all(
                stamp(row["valid_from"]) <= t < stamp(row["valid_until"])
                for t in checks
            ),
            "expired/not-yet-valid role",
        )
        return row


def validate_configuration(
    inventory: Inventory, key: str = "reviewer_configuration"
) -> dict[str, Any]:
    raw = inventory.raw(key)
    configuration_fingerprint(raw)
    parsed = parse(raw, allow_floats=False)
    managed = parsed["configuration_version"] == "1.1"
    if managed:
        require(
            inventory.entries[key]["storage_class"] == "protected_external",
            "managed reviewer configuration must be protected",
        )
    config = checked(
        raw,
        "reviewer-configuration-v1.1" if managed else "reviewer-configuration",
    )
    build_raw = inventory.by_sha(
        config["implementation_build_sha256"], protected=managed
    )
    build = checked(build_raw, "reviewer-build-inventory")
    for entry in build["files"]:
        if managed:
            require(
                inventory.entries[entry["inventory_key"]]["storage_class"]
                == "protected_external",
                "managed reviewer build files must be protected",
            )
        inventory.raw(entry["inventory_key"], entry["sha256"], protected=managed)
    inventory.by_sha(config["context_policy"]["policy_sha256"], protected=managed)
    if config["reviewer_type"] == "agent":
        agent = config["agent"]
        if managed:
            require(
                agent["agent_identity_mode"] == "managed_alias"
                and agent["model_revision"] is None
                and agent["fallback_policy"] == "deny",
                "invalid managed alias identity/fallback policy",
            )
        else:
            # Mutable aliases are not immutable revisions. Other revisions are
            # opaque, provider-neutral pins; their service meaning belongs to
            # controlled setup. This 1.0 rule is unchanged.
            require(
                agent["model_revision"].strip().casefold()
                not in {"latest", "default", "current", "auto", "unversioned"},
                "unpinned mutable model revision",
            )
        names = [p["name"] for p in agent["decoding"]["additional_parameters"]]
        require(len(names) == len(set(names)), "duplicate decoding parameter")
        fields = (
            "semantic_prompt_sha256",
            "system_instructions_sha256",
            "tool_permissions_sha256",
        )
        if managed:
            fields += (
                "service_observation_policy_sha256",
                "qualification_approver_prompt_sha256",
            )
    else:
        require(not managed, "managed alias configuration must be an agent")
        agent = config["human"]
        fields = ("procedure_sha256", "interface_policy_sha256")
    for field in fields:
        inventory.by_sha(agent[field], protected=managed)
    return config


def managed_service_identity_projection(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Return stable identity metadata without request-specific data."""
    if observation.get("observation_version") == "1.1":
        return {
            field: observation[field]
            for field in (
                "observation_version",
                "provider_service_reference",
                "requested_alias",
                "reported_model_identifier",
                "reported_model_revision",
                "service_fingerprint",
                "service_api_version",
                "codex_cli_version",
                "observation_policy_sha256",
                "provider_visibility_mode",
            )
        } | {
            "client_build_sha256": observation["controller_build_sha256"]
        }
    return {
        field: observation[field]
        for field in (
            "provider_service_reference",
            "requested_alias",
            "reported_model_identifier",
            "reported_model_revision",
            "service_fingerprint",
            "service_api_version",
            "client_build_sha256",
            "observation_policy_sha256",
        )
    }


def managed_service_identity_fingerprint(observation: Mapping[str, Any]) -> str:
    """Hash only the stable observed service identity, never claim a snapshot."""
    projection = managed_service_identity_projection(observation)
    return sha256_bytes(canonical_json_bytes(projection))


def managed_approver_report_view(raw: bytes, case_ids: set[str]) -> bytes:
    """Make a label-blind view without case IDs or corpus-linkable provenance refs."""
    report = parse(raw, allow_floats=False)
    require(isinstance(report, dict), "managed reviewer report must be an object")
    ordered_ids = sorted(case_ids, key=len, reverse=True)
    redacted_fields = {
        "review_id",
        "pipeline_run_id",
        "authoring_id",
        "content_sha256",
        "outline_sha256",
        "source_truth_manifest_sha256",
        "configuration_sha256",
        "qualification_sha256",
        "identity",
        "operation_id",
        "source_id",
    }

    def redact(value: Any, field: str | None = None) -> Any:
        if field in redacted_fields or (field and field.endswith("_sha256")) or field == "sha256":
            return "[REDACTED]"
        if isinstance(value, str):
            for case_id in ordered_ids:
                value = value.replace(case_id, "[CASE]")
            return value
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, dict):
            return {key: redact(item, key) for key, item in value.items()}
        return value

    view = redact(report)
    encoded = canonical_json_bytes(view)
    require(
        not any(case_id.encode("utf-8") in encoded for case_id in case_ids),
        "managed approver report view still contains a corpus case identifier",
    )
    return encoded


def validate_managed_service_observation(
    inventory: Inventory,
    key: str,
    digest: str,
    config: Mapping[str, Any],
    operation_id: str,
    *,
    expected_principal: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate one controller-protected, operation-bound service observation."""
    require(
        config["configuration_version"] == "1.1"
        and config["reviewer_type"] == "agent",
        "managed observation requires Reviewer Configuration 1.1",
    )
    raw = inventory.raw(key, digest, protected=True)
    parsed = parse(raw, allow_floats=False)
    require(isinstance(parsed, dict), "managed service observation must be an object")
    version = parsed.get("observation_version")
    schemas = {
        "1.0": "managed-reviewer-service-observation",
        "1.1": "managed-reviewer-service-observation-v1.1",
    }
    require(version in schemas, "unsupported managed service observation version")
    observation = checked(raw, schemas[version])
    require(
        raw == canonical_json_bytes(observation),
        "managed service observation bytes must be canonical",
    )
    agent = config["agent"]
    require(observation["operation_id"] == operation_id, "service operation mismatch")
    require(
        observation["provider_service_reference"] == agent["provider_reference"]
        and observation["requested_alias"] == agent["model_reference"],
        "managed service/provider alias changed",
    )
    require(
        observation["observation_policy_sha256"]
        == agent["service_observation_policy_sha256"],
        "managed observation policy changed",
    )
    requested = stamp(observation["requested_at"])
    observed = stamp(observation["observed_at"])
    if version == "1.0":
        require(
            observation["client_build_sha256"]
            == config["implementation_build_sha256"],
            "managed observation client/policy changed",
        )
        require(observation["fallback_detected"] is False, "managed service fallback")
        policy_raw = inventory.by_sha(
            agent["service_observation_policy_sha256"], protected=True
        )
        try:
            policy = parse(policy_raw, allow_floats=False)
        except RecordError:
            policy = None
        require(
            not (isinstance(policy, dict) and policy.get("policy_version") == "1.1"),
            "managed observation 1.0 cannot use observation policy 1.1",
        )
        require(requested <= observed, "invalid managed observation chronology")
        if started_at is not None:
            require(started_at <= requested, "service request predates operation")
        if completed_at is not None:
            require(observed <= completed_at, "service observation exceeds operation")
    else:
        require(
            expected_principal is not None
            and observation["logical_principal"] == expected_principal,
            "managed observation principal mismatch",
        )
        require(
            observation["controller_build_sha256"]
            == config["implementation_build_sha256"],
            "managed observation controller build changed",
        )
        policy_raw = inventory.by_sha(
            agent["service_observation_policy_sha256"], protected=True
        )
        policy = checked(policy_raw, "managed-service-observation-policy-v1.1")
        require(
            policy_raw == canonical_json_bytes(policy),
            "managed observation policy bytes must be canonical",
        )
        require(
            policy["provider_service_reference"] == agent["provider_reference"]
            and policy["requested_alias"] == agent["model_reference"]
            and policy["provider_visibility_mode"]
            == observation["provider_visibility_mode"],
            "managed observation policy identity changed",
        )
        require(
            observation["provider_fallback_status"] != "reported_true",
            "provider reported internal fallback",
        )
        capture_raw = inventory.raw(
            observation["capture_manifest_inventory_key"],
            observation["capture_manifest_sha256"],
            protected=True,
        )
        capture = checked(capture_raw, "managed-service-capture-manifest-v1.1")
        require(
            capture_raw == canonical_json_bytes(capture),
            "managed capture manifest bytes must be canonical",
        )
        argv = [
            observation["requested_alias"]
            if arg == "{{requested_alias}}"
            else arg
            for arg in policy["codex_exec_argv_template"]
        ]
        require(
            capture["operation_id"] == observation["operation_id"]
            and capture["logical_principal"] == observation["logical_principal"]
            and capture["requested_alias"] == observation["requested_alias"]
            and capture["codex_exec_argv"] == argv
            and capture["codex_version_argv"] == policy["codex_version_argv"],
            "managed capture invocation identity changed",
        )
        capture_bindings = (
            ("request_inventory_key", "request_inventory_key"),
            ("request_sha256", "request_sha256"),
            ("response_trace_inventory_key", "response_trace_inventory_key"),
            ("response_sha256", "response_trace_sha256"),
            ("codex_cli_version_inventory_key", "codex_cli_version_inventory_key"),
            ("codex_cli_version_sha256", "codex_cli_version_sha256"),
        )
        for observation_field, capture_field in capture_bindings:
            require(
                observation[observation_field] == capture[capture_field],
                f"managed capture {observation_field} mismatch",
            )
        timestamp_fields = (
            "operation_started_at",
            "request_captured_at",
            "requested_at",
            "observed_at",
            "operation_completed_at",
        )
        capture_times = {field: stamp(capture[field]) for field in timestamp_fields}
        observation_times = {
            field: stamp(observation[field]) for field in timestamp_fields
        }
        require(
            capture_times == observation_times,
            "managed capture operation timestamps mismatch",
        )
        require(
            capture_times["operation_started_at"]
            <= capture_times["request_captured_at"]
            <= capture_times["requested_at"]
            <= capture_times["observed_at"]
            <= capture_times["operation_completed_at"],
            "invalid managed observation chronology",
        )
        if started_at is not None:
            require(
                started_at <= capture_times["operation_started_at"],
                "managed service operation predates evaluation run",
            )
        if completed_at is not None:
            require(
                capture_times["operation_completed_at"] <= completed_at,
                "managed service operation exceeds evaluation run",
            )
        request_raw = inventory.raw(
            observation["request_inventory_key"],
            observation["request_sha256"],
            protected=True,
        )
        response_raw = inventory.raw(
            observation["response_trace_inventory_key"],
            observation["response_sha256"],
            protected=True,
        )
        # Reading these bytes through Inventory proves their hashes and protected roots.
        del request_raw
        version_raw = inventory.raw(
            observation["codex_cli_version_inventory_key"],
            observation["codex_cli_version_sha256"],
            protected=True,
        )
        try:
            version_text = version_raw.decode("utf-8").rstrip("\r\n")
        except UnicodeError as exc:
            raise RecordError("Codex CLI version evidence is not UTF-8") from exc
        require(
            version_text
            and "\n" not in version_text
            and "\r" not in version_text
            and version_text == observation["codex_cli_version"],
            "Codex CLI version does not match captured bytes",
        )
        events = _codex_jsonl_events(response_raw)
        _validate_reported_provider_metadata(observation, policy, events)
        _validate_provider_fallback(observation, policy, events)
    if now is not None:
        require(observed <= now, "managed service observation is from the future")
    return observation


def _codex_jsonl_events(raw: bytes) -> list[dict[str, Any]]:
    """Parse a successful codex exec --json stdout trace without normalizing it."""
    lines = raw.splitlines()
    require(bool(lines) and all(line.strip() for line in lines), "empty Codex JSONL trace")
    events: list[dict[str, Any]] = []
    for line in lines:
        event = parse(line, allow_floats=True)
        require(
            isinstance(event, dict) and isinstance(event.get("type"), str),
            "Codex JSONL trace contains a non-event row",
        )
        events.append(event)
    types = [event["type"] for event in events]
    require("thread.started" in types, "Codex JSONL trace lacks thread.started")
    require(
        types[-1] == "turn.completed"
        and "turn.failed" not in types
        and "error" not in types,
        "Codex JSONL trace is not a successful completed turn",
    )
    require(
        any(
            event.get("type") == "item.completed"
            and isinstance(event.get("item"), dict)
            and event["item"].get("type") == "agent_message"
            and isinstance(event["item"].get("text"), str)
            and bool(event["item"]["text"].strip())
            for event in events
        ),
        "Codex JSONL trace lacks a completed agent message",
    )
    return events


_TRACE_MISSING = object()


def _json_pointer_value(value: Any, pointer: str) -> Any:
    require(pointer.startswith("/"), "metadata source is not a JSON Pointer")
    current = value
    for encoded in pointer[1:].split("/"):
        require(
            not any(
                encoded[index] == "~"
                and (index + 1 == len(encoded) or encoded[index + 1] not in "01")
                for index in range(len(encoded))
            ),
            "metadata JSON Pointer has invalid escape",
        )
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return _TRACE_MISSING
    return current


_PROVIDER_METADATA_FIELDS = (
    "reported_model_identifier",
    "reported_model_revision",
    "service_fingerprint",
    "service_api_version",
    "request_id",
)


def _matching_trace_sources(
    events: list[dict[str, Any]], pointers: list[str]
) -> list[tuple[int, str, Any]]:
    values: list[tuple[int, str, Any]] = []
    for line_index, event in enumerate(events):
        for pointer in pointers:
            value = _json_pointer_value(event, pointer)
            if value is not _TRACE_MISSING:
                values.append((line_index, pointer, value))
    return values


def _validate_reported_provider_metadata(
    observation: Mapping[str, Any],
    policy: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> None:
    for field in _PROVIDER_METADATA_FIELDS:
        observed = _matching_trace_sources(
            events, policy["provider_metadata_json_pointers"][field]
        )
        evidence = observation["metadata_evidence"][field]
        value = observation[field]
        if not observed:
            require(value is None and evidence is None, f"unreported provider metadata: {field}")
            continue
        require(
            all(isinstance(row[2], str) and row[2] for row in observed),
            f"invalid provider metadata type: {field}",
        )
        reported_values = {row[2] for row in observed}
        require(len(reported_values) == 1, f"inconsistent provider metadata: {field}")
        require(value == next(iter(reported_values)), f"provider metadata is not trace-derived: {field}")
        require(isinstance(evidence, dict), f"provider metadata source missing: {field}")
        require(
            (evidence["line_index"], evidence["json_pointer"], value)
            in observed,
            f"provider metadata source mismatch: {field}",
        )


def _validate_provider_fallback(
    observation: Mapping[str, Any],
    policy: Mapping[str, Any],
    events: list[dict[str, Any]],
) -> None:
    values = _matching_trace_sources(
        events, policy["provider_fallback_json_pointers"]
    )
    evidence = observation["provider_fallback_evidence"]
    if not values:
        require(
            observation["provider_fallback_status"] == "not_observable"
            and evidence is None,
            "provider fallback must be not_observable when no provider signal exists",
        )
        return
    require(
        all(isinstance(row[2], bool) for row in values),
        "provider fallback metadata has invalid type",
    )
    require(not any(row[2] for row in values), "provider reported internal fallback")
    require(
        observation["provider_fallback_status"] == "reported_false"
        and isinstance(evidence, dict),
        "provider-reported no-fallback evidence is missing",
    )
    require(
        (evidence["line_index"], evidence["json_pointer"], False) in values,
        "provider fallback evidence does not match raw trace",
    )


def validate_training(
    context: TrustContext,
    qualification: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    author_principal: str | None = None,
) -> dict[str, Any]:
    human = qualification["human_authority"]
    raw = context.inventory.raw(
        "human_training_authorization",
        human["training_authorization_sha256"],
        protected=True,
    )
    training = checked(raw, "human-training-authorization")
    principal = human["principal_id"]
    require(training["principal_id"] == principal, "training subject mismatch")
    role = context.role(
        principal, "scope_reviewer", stamp(qualification["qualified_at"])
    )
    require(
        human["teacher_authority_reference"] == role["authorization_reference"],
        "human authorization reference mismatch",
    )
    context.inventory.raw(human["teacher_authority_reference"], protected=True)
    for field in ("procedure_id", "procedure_version", "procedure_sha256"):
        require(
            training[field] == human[field] == config["human"][field],
            f"training {field} mismatch",
        )
    context.inventory.raw(
        "human_procedure", training["procedure_sha256"], protected=True
    )
    require(
        stamp(training["issued_at"])
        <= stamp(training["valid_from"])
        < stamp(training["valid_until"]),
        "training validity order",
    )
    require(
        stamp(training["valid_from"]) <= context.now < stamp(training["valid_until"]),
        "training expired/not-yet-valid",
    )
    require(
        stamp(training["valid_from"])
        <= stamp(qualification["qualified_at"])
        < stamp(training["valid_until"]),
        "training not valid at qualification completion",
    )
    require(training["revoked_at"] is None, "training revoked")
    require(
        training["issuer_principal"] not in {principal, author_principal},
        "training self/author issuance",
    )
    context.role(
        training["issuer_principal"],
        "qualification_approver",
        stamp(training["issued_at"]),
        current_validity=False,
    )
    context.not_revoked(
        training["authorization_id"], training["authorization_reference"]
    )
    context.inventory.raw(training["authorization_reference"], protected=True)
    return training
