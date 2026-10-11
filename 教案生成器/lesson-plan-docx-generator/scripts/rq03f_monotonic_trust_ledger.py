"""RQ-03F C3 monotonic trust ledger contracts and fail-closed verifier.

The module deliberately contains no file-backed or in-process High-Water
Authority implementation.  A local ledger is only a projection; the authority
adapter must authenticate a separately protected service/device and enforce
linearizable CAS/fencing.  C2's production-write guard remains unconditional.
The filesystem projection store is a local consistency helper, not an authority.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any, Callable, Protocol

from lifecycle_digest import canonical_json_bytes, schema_errors


LEDGER_VERSION = "rq03f-monotonic-trust-ledger-1.0"
TRANSITION_VERSION = "rq03f-trust-transition-1.0"
AUTHORITY_RESPONSE_VERSION = "rq03f-high-water-authority-response-1.0"
LEDGER_SCHEMA = "rq03f-monotonic-trust-ledger-v1.0.schema.json"
LEDGER_RECORD_SCHEMA = "rq03f-monotonic-trust-ledger-record-v1.0.schema.json"
TRANSITION_SCHEMA = "rq03f-trust-transition-v1.0.schema.json"
AUTHORITY_RESPONSE_SCHEMA = "rq03f-high-water-authority-response-v1.0.schema.json"
MAX_AUTHORITY_AGE_SECONDS = 30
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
TRANSITION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
PURPOSES = frozenset({
    "read_only_preflight",
    "qualification_corpus_intake",
    "qualification_review",
    "production_authoring",
    "teacher_approval",
    "pa_approval",
    "generation",
    "revocation",
    "epoch_transition",
})
DEFINITE_PREPARE_REJECTIONS = frozenset({
    "CAS_BUSY", "CAS_STALE", "AUTHORIZATION_REJECTED", "ACTOR_IDENTITY_REJECTED",
    "INDEX_SHA_MISMATCH", "TRANSITION_ID_REUSE",
})
INDEX_ARRAYS = (
    "receipts", "authors", "adjudications", "qualification_runs",
    "qualification_corpus_intakes",
)


class LedgerError(ValueError):
    """Stable, fail-closed C3 contract failure."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _fail(code: str, message: str) -> None:
    raise LedgerError(code, message)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("JSON_DUPLICATE_KEY", "duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    _fail("JSON_NONFINITE", f"non-finite JSON value is forbidden: {value}")


def _parse_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except LedgerError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LedgerError("JSON_INVALID", f"invalid {label} JSON") from exc
    if not isinstance(value, dict):
        _fail("JSON_OBJECT_REQUIRED", f"{label} must be an object")
    return value


def _schema(payload: dict[str, Any], name: str) -> None:
    errors = schema_errors(payload, name)
    if errors:
        _fail("SCHEMA_INVALID", "; ".join(errors))


def _digest(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _sha(value: Any, label: str) -> None:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail("SHA256_INVALID", f"{label} must be a lowercase SHA-256")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        _fail("TIME_NOT_UTC", "authority timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TrustState:
    """Exact state bound by each committed High-Water entry."""

    policy_identity: str
    policy_epoch: int
    profile_sha256: str
    build_inventory_sha256: str
    controller_id: str
    generation_id: str
    index_sha256: str
    index_revision: int
    revocation_state_sha256: str
    revoked_authority_ids: tuple[str, ...] = ()
    revoked_role_authorization_references: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        if not self.policy_identity or not self.controller_id or not self.generation_id:
            _fail("STATE_IDENTITY_INVALID", "policy, controller, and Generation identities are required")
        if type(self.policy_epoch) is not int or self.policy_epoch < 1:
            _fail("EPOCH_INVALID", "policy epoch must be a positive integer")
        if type(self.index_revision) is not int or self.index_revision < 0:
            _fail("REVISION_INVALID", "Index revision must be a non-negative integer")
        for label, value in (
            ("Profile SHA", self.profile_sha256),
            ("Build Inventory SHA", self.build_inventory_sha256),
            ("Index SHA", self.index_sha256),
            ("revocation digest", self.revocation_state_sha256),
        ):
            _sha(value, label)
        for label, values in (
            ("revoked_authority_ids", self.revoked_authority_ids),
            ("revoked_role_authorization_references", self.revoked_role_authorization_references),
        ):
            if any(not isinstance(value, str) or not value for value in values):
                _fail("REVOCATION_INVALID", f"{label} contains an empty or invalid identifier")
            if len(values) != len(set(values)):
                _fail("REVOCATION_DUPLICATE", f"{label} contains duplicate identifiers")
        return {
            "policy_identity": self.policy_identity,
            "policy_epoch": self.policy_epoch,
            "profile_sha256": self.profile_sha256,
            "build_inventory_sha256": self.build_inventory_sha256,
            "controller_id": self.controller_id,
            "generation_id": self.generation_id,
            "index_sha256": self.index_sha256,
            "index_revision": self.index_revision,
            "revocation_state_sha256": self.revocation_state_sha256,
            "revoked_authority_ids": sorted(self.revoked_authority_ids),
            "revoked_role_authorization_references": sorted(self.revoked_role_authorization_references),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TrustState":
        return cls(
            policy_identity=payload["policy_identity"],
            policy_epoch=payload["policy_epoch"],
            profile_sha256=payload["profile_sha256"],
            build_inventory_sha256=payload["build_inventory_sha256"],
            controller_id=payload["controller_id"],
            generation_id=payload["generation_id"],
            index_sha256=payload["index_sha256"],
            index_revision=payload["index_revision"],
            revocation_state_sha256=payload["revocation_state_sha256"],
            revoked_authority_ids=tuple(payload["revoked_authority_ids"]),
            revoked_role_authorization_references=tuple(payload["revoked_role_authorization_references"]),
        )


def revocation_state(profile: dict[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Hash the explicit Profile 1.1 revocation and role-validity fields."""
    revoked_ids = profile.get("revoked_authority_ids")
    roles = profile.get("roles")
    if not isinstance(revoked_ids, list) or not isinstance(roles, list):
        _fail("REVOCATION_PROFILE_INVALID", "Profile revocation fields are missing")
    revoked_references: list[str] = []
    role_state: list[dict[str, Any]] = []
    for role in roles:
        if not isinstance(role, dict):
            _fail("REVOCATION_PROFILE_INVALID", "Profile role row is malformed")
        reference = role.get("authorization_reference")
        if not isinstance(reference, str) or not reference:
            _fail("REVOCATION_PROFILE_INVALID", "Profile role authorization reference is missing")
        if role.get("revoked_at") is not None:
            revoked_references.append(reference)
        role_state.append({
            "principal_id": role.get("principal_id"),
            "authorization_reference": reference,
            "allowed_roles": role.get("allowed_roles"),
            "valid_from": role.get("valid_from"),
            "valid_until": role.get("valid_until"),
            "revoked_at": role.get("revoked_at"),
            "revocation_reason": role.get("revocation_reason"),
        })
    if any(not isinstance(value, str) or not value for value in revoked_ids):
        _fail("REVOCATION_PROFILE_INVALID", "Profile revoked authority identifiers are malformed")
    payload = {
        "revoked_authority_ids": sorted(set(revoked_ids)),
        "roles": sorted(role_state, key=lambda row: (row["principal_id"] or "", row["authorization_reference"])),
    }
    return _digest(payload), tuple(sorted(set(revoked_ids))), tuple(sorted(set(revoked_references)))


def validate_state_successor(previous: TrustState, current: TrustState, *,
                             authorization: "VerifiedTransitionAuthorization | None",
                             expected_authority_identity: str,
                             transition_id: str) -> None:
    """Enforce epoch, identity, revision, and monotonic revocation rules."""
    old, new = previous.payload(), current.payload()
    if new["index_revision"] != old["index_revision"] + 1:
        _fail("REVISION_NOT_CONTIGUOUS", "committed Index revision must increase by exactly one")
    if new["policy_epoch"] < old["policy_epoch"]:
        _fail("EPOCH_ROLLBACK", "policy epoch cannot decrease")
    if new["policy_epoch"] > old["policy_epoch"] + 1:
        _fail("EPOCH_SKIP", "policy epoch transitions must be one step at a time")
    old_revoked_ids = set(old["revoked_authority_ids"])
    old_revoked_roles = set(old["revoked_role_authorization_references"])
    if not old_revoked_ids.issubset(new["revoked_authority_ids"]):
        _fail("REVOCATION_ROLLBACK", "previously revoked authority IDs cannot become active again")
    if not old_revoked_roles.issubset(new["revoked_role_authorization_references"]):
        _fail("REVOCATION_ROLLBACK", "previously revoked role references cannot become active again")
    changed_fixed = any(new[key] != old[key] for key in (
        "policy_identity", "profile_sha256", "build_inventory_sha256", "controller_id",
        "generation_id", "revocation_state_sha256",
    ))
    if new["policy_epoch"] == old["policy_epoch"]:
        if changed_fixed:
            _fail("SAME_EPOCH_POLICY_CHANGE", "Profile, policy, Generation, build, and revocation state are fixed within an epoch")
    else:
        if (type(authorization) is not VerifiedTransitionAuthorization
                or authorization.authority_identity != expected_authority_identity
                or authorization.transition_id != transition_id
                or authorization.authorization_class != "owner_policy_transition"
                or authorization.approval_reference == ""):
            _fail("OWNER_APPROVAL_REQUIRED", "epoch changes require independently verified Owner approval")
        if new["profile_sha256"] == old["profile_sha256"]:
            _fail("PROFILE_NOT_ROTATED", "epoch change requires a newly approved Profile")
        if new["generation_id"] == old["generation_id"]:
            _fail("GENERATION_REPLAY", "new epoch must use a new Generation")


def _index_ids(index: dict[str, Any]) -> dict[str, set[str]]:
    ids: dict[str, set[str]] = {"operation_id": set(), "receipt_id": set(), "authoring_id": set(),
                                "run_id": set(), "intake_id": set()}
    for row in index["receipts"]:
        ids["operation_id"].add(row["operation_id"])
        ids["receipt_id"].add(row["receipt_id"])
    for row in index["authors"]:
        ids["operation_id"].add(row["operation_id"])
        ids["authoring_id"].add(row["authoring_id"])
    for row in index["adjudications"]:
        ids["operation_id"].add(row["operation_id"])
    for row in index["qualification_runs"]:
        ids["run_id"].add(row["run_id"])
        for operation in row["operations"]:
            ids["operation_id"].add(operation["review_operation_id"])
    for row in index["qualification_corpus_intakes"]:
        ids["operation_id"].add(row["operation_id"])
        ids["intake_id"].add(row["intake_id"])
    return ids


def validate_index_append(previous_raw: bytes, current_raw: bytes, *,
                          expected_epoch: int, expected_controller_id: str,
                          expected_previous_sha256: str,
                          expected_current_sha256: str,
                          allow_policy_transition: bool = False,
                          allow_empty_transition: bool = False) -> dict[str, Any]:
    """Validate exact Index 1.1 bytes, old prefixes, and non-reused IDs."""
    if hashlib.sha256(previous_raw).hexdigest() != expected_previous_sha256:
        _fail("INDEX_PREVIOUS_SHA", "previous Index bytes do not match the committed SHA")
    if hashlib.sha256(current_raw).hexdigest() != expected_current_sha256:
        _fail("INDEX_CURRENT_SHA", "candidate Index bytes do not match the proposed SHA")
    previous = _parse_object(previous_raw, "previous Index")
    current = _parse_object(current_raw, "candidate Index")
    _schema(previous, "protected-operation-index-v1.1.schema.json")
    _schema(current, "protected-operation-index-v1.1.schema.json")
    if (current["policy_epoch"] != expected_epoch
            or (previous["policy_epoch"] != current["policy_epoch"] and not allow_policy_transition)):
        _fail("INDEX_EPOCH_MISMATCH", "Index epoch differs from the committed Policy epoch")
    if ((previous["controller_id"] != current["controller_id"] and not allow_policy_transition)
            or current["controller_id"] != expected_controller_id):
        _fail("INDEX_CONTROLLER_MISMATCH", "Index Controller identity differs from the committed Controller")
    old_ids, new_ids = _index_ids(previous), _index_ids(current)
    for name in INDEX_ARRAYS:
        old_rows, new_rows = previous[name], current[name]
        if len(new_rows) < len(old_rows) or new_rows[:len(old_rows)] != old_rows:
            _fail("INDEX_PREFIX_MISMATCH", f"Index {name} is not an exact append-only extension")
        namespace = name_map[name]
        old_values = _index_id_values(previous, namespace)
        new_values = _index_id_values(current, namespace)
        if len(new_values) != len(set(new_values)):
            if namespace == "operation_id":
                _fail("OPERATION_ID_REUSE", "Index contains a duplicate protected operation ID")
            _fail("IDENTIFIER_DUPLICATE", f"Index {name} contains duplicate protected identifiers")
        added = new_ids[namespace] - old_ids[namespace]
        if not set(old_values).isdisjoint(added):
            _fail("IDENTIFIER_REUSE", f"Index {name} reuses a protected identifier")
    old_operation_values = _index_id_values(previous, "operation_id")
    new_operation_values = _index_id_values(current, "operation_id")
    if len(new_operation_values) != len(set(new_operation_values)):
        _fail("OPERATION_ID_REUSE", "a protected operation ID was repeated in the Index")
    added_operations = new_ids["operation_id"] - old_ids["operation_id"]
    if len(added_operations) != len(new_operation_values) - len(old_operation_values):
        _fail("OPERATION_ID_REUSE", "a protected operation ID was reused in the Index transition")
    added_rows = sum(len(current[name]) - len(previous[name]) for name in INDEX_ARRAYS)
    if added_rows < 1 and not allow_empty_transition:
        _fail("INDEX_NOOP", "an Index transition must append at least one protected record")
    return current


# Index identifier namespaces whose uniqueness is enforced across the whole history.
name_map = {
    "receipts": "receipt_id", "authors": "authoring_id", "adjudications": "operation_id",
    "qualification_runs": "run_id", "qualification_corpus_intakes": "intake_id",
}


def _index_id_values(index: dict[str, Any], namespace: str) -> list[str]:
    values: list[str] = []
    if namespace == "operation_id":
        values.extend(row["operation_id"] for row in index["receipts"])
        values.extend(row["operation_id"] for row in index["authors"])
        values.extend(row["operation_id"] for row in index["adjudications"])
        values.extend(row["review_operation_id"] for run in index["qualification_runs"]
                      for row in run["operations"])
        values.extend(row["operation_id"] for row in index["qualification_corpus_intakes"])
        return values
    field = {"receipt_id": ("receipts", "receipt_id"),
             "authoring_id": ("authors", "authoring_id"),
             "run_id": ("qualification_runs", "run_id"),
             "intake_id": ("qualification_corpus_intakes", "intake_id")}.get(namespace)
    if field is None:
        return values
    group, key = field
    return [row[key] for row in index[group]]


def build_ledger_record(*, authority_identity: str, sequence: int,
                        previous_state_digest: str | None,
                        previous_record_sha256: str | None, state: TrustState,
                        transition_id: str, operation_purpose: str,
                        owner_approval_reference: str, audit_timestamp: datetime) -> dict[str, Any]:
    state_payload = state.payload()
    if sequence == 0 and (previous_state_digest is not None or previous_record_sha256 is not None):
        _fail("GENESIS_INVALID", "initial committed state has no previous state digest")
    if sequence > 0:
        _sha(previous_state_digest, "previous committed state digest")
        _sha(previous_record_sha256, "previous record SHA")
    if not TRANSITION_RE.fullmatch(transition_id):
        _fail("TRANSITION_ID_INVALID", "transition ID has an invalid format")
    if operation_purpose not in PURPOSES:
        _fail("PURPOSE_INVALID", "operation purpose is not a closed C3 purpose")
    if not isinstance(owner_approval_reference, str) or not owner_approval_reference.strip():
        _fail("OWNER_APPROVAL_REFERENCE_MISSING", "Owner approval reference is required")
    timestamp = _utc(audit_timestamp).isoformat().replace("+00:00", "Z")
    record = {
        "ledger_version": LEDGER_VERSION,
        "authority_identity": authority_identity,
        "sequence": sequence,
        "previous_committed_state_digest": previous_state_digest,
        "previous_record_sha256": previous_record_sha256,
        "current_committed_state_digest": _digest(state_payload),
        "state": state_payload,
        "transition_id": transition_id,
        "operation_purpose": operation_purpose,
        "commitment_status": "committed",
        "owner_approval_reference": owner_approval_reference,
        "audit_timestamp": timestamp,
    }
    _schema(record, LEDGER_RECORD_SCHEMA)
    return record


def ledger_document(authority_identity: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    document = {"ledger_version": LEDGER_VERSION,
                "authority_identity": authority_identity,
                "records": records}
    _schema(document, LEDGER_SCHEMA)
    return document


def encode_ledger(authority_identity: str, records: list[dict[str, Any]]) -> bytes:
    return canonical_json_bytes(ledger_document(authority_identity, records)) + b"\n"


def verify_ledger(raw: bytes, *, expected_authority_identity: str,
                  expected_head_state_digest: str,
                  expected_head_record_sha256: str,
                  expected_sequence: int) -> tuple[dict[str, Any], ...]:
    document = _parse_object(raw, "Trust Ledger")
    _schema(document, LEDGER_SCHEMA)
    if document["authority_identity"] != expected_authority_identity:
        _fail("AUTHORITY_IDENTITY_MISMATCH", "Ledger source identity differs from the pinned Authority")
    records = document["records"]
    if len(records) != expected_sequence + 1:
        _fail("LEDGER_SEQUENCE_GAP", "Ledger history is missing or has extra committed records")
    seen_transitions: set[str] = set()
    previous_state: TrustState | None = None
    previous_digest: str | None = None
    previous_record_sha256: str | None = None
    for expected_sequence_number, record in enumerate(records):
        _schema(record, LEDGER_RECORD_SCHEMA)
        if record["sequence"] != expected_sequence_number:
            _fail("LEDGER_SEQUENCE_GAP", "Ledger sequence is not contiguous")
        if record["authority_identity"] != expected_authority_identity:
            _fail("AUTHORITY_IDENTITY_MISMATCH", "Ledger record changed Authority identity")
        if record["transition_id"] in seen_transitions:
            _fail("TRANSITION_ID_REUSE", "transition ID is duplicated in committed history")
        seen_transitions.add(record["transition_id"])
        state = TrustState.from_payload(record["state"])
        state_payload = state.payload()
        if _digest(state_payload) != record["current_committed_state_digest"]:
            _fail("STATE_DIGEST_MISMATCH", "Ledger state digest does not match its state payload")
        if record["previous_committed_state_digest"] != previous_digest:
            _fail("LEDGER_CHAIN_BROKEN", "Ledger state chain is broken or reordered")
        if record["previous_record_sha256"] != previous_record_sha256:
            _fail("LEDGER_RECORD_CHAIN_BROKEN", "Ledger record history is broken, altered, or reordered")
        if previous_state is not None:
            _validate_historical_successor(previous_state, state, record)
        previous_state = state
        previous_digest = record["current_committed_state_digest"]
        previous_record_sha256 = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    if not records:
        _fail("LEDGER_EMPTY", "Ledger has no committed genesis state")
    if previous_digest != expected_head_state_digest:
        _fail("WITNESS_HEAD_MISMATCH", "Ledger state is older or different from the independent High-Water head")
    if previous_record_sha256 != expected_head_record_sha256:
        _fail("WITNESS_RECORD_MISMATCH", "Ledger head record digest differs from the independent High-Water head")
    return tuple(records)


def verify_witness_snapshot(snapshot: "WitnessSnapshot", *,
                            expected_authority_identity: str,
                            now: datetime | None = None) -> tuple[dict[str, Any], ...]:
    """Validate typed Authority response bindings and its complete committed chain."""
    if type(snapshot) is not WitnessSnapshot:
        _fail("AUTHORITY_RESPONSE_TYPE", "Authority response is not an authenticated typed snapshot")
    if snapshot.authority_identity != expected_authority_identity:
        _fail("AUTHORITY_IDENTITY_MISMATCH", "Authority identity differs from the independent pin")
    current = _utc(now or datetime.now(timezone.utc))
    checked_at, valid_until = _utc(snapshot.checked_at), _utc(snapshot.valid_until)
    if (checked_at > current or valid_until < current
            or (valid_until - checked_at).total_seconds() > MAX_AUTHORITY_AGE_SECONDS):
        _fail("AUTHORITY_RESPONSE_STALE", "High-Water Authority response is stale")
    if not snapshot.fencing_token:
        _fail("FENCING_TOKEN_MISSING", "High-Water Authority response lacks a fencing token")
    response = {
        "authority_response_version": AUTHORITY_RESPONSE_VERSION,
        "authority_identity": snapshot.authority_identity,
        "sequence": snapshot.sequence,
        "head_state_digest": snapshot.head_state_digest,
        "head_record_sha256": snapshot.head_record_sha256,
        "state": snapshot.state.payload(),
        "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
        "valid_until": valid_until.isoformat().replace("+00:00", "Z"),
        "fencing_token": snapshot.fencing_token,
        "pending_transition_ids": list(snapshot.pending_transition_ids),
    }
    _schema(response, AUTHORITY_RESPONSE_SCHEMA)
    records = verify_ledger(
        encode_ledger(snapshot.authority_identity, list(snapshot.history)),
        expected_authority_identity=expected_authority_identity,
        expected_head_state_digest=snapshot.head_state_digest,
        expected_head_record_sha256=snapshot.head_record_sha256,
        expected_sequence=snapshot.sequence,
    )
    if records[-1]["state"] != snapshot.state.payload():
        _fail("WITNESS_STATE_MISMATCH", "Authority snapshot State differs from the latest committed Ledger record")
    if len(snapshot.pending_transition_ids) != len(set(snapshot.pending_transition_ids)):
        _fail("TRANSITION_ID_REUSE", "Authority reports duplicate unresolved transition IDs")
    return records


def _validate_historical_successor(previous: TrustState, current: TrustState,
                                   record: dict[str, Any]) -> None:
    old, new = previous.payload(), current.payload()
    if new["index_revision"] != old["index_revision"] + 1:
        _fail("REVISION_NOT_CONTIGUOUS", "committed Index revision must increase by exactly one")
    if new["policy_epoch"] < old["policy_epoch"]:
        _fail("EPOCH_ROLLBACK", "policy epoch cannot decrease")
    if new["policy_epoch"] > old["policy_epoch"] + 1:
        _fail("EPOCH_SKIP", "policy epoch transitions must be one step at a time")
    if not set(old["revoked_authority_ids"]).issubset(new["revoked_authority_ids"]):
        _fail("REVOCATION_ROLLBACK", "previously revoked authority IDs cannot become active again")
    if not set(old["revoked_role_authorization_references"]).issubset(new["revoked_role_authorization_references"]):
        _fail("REVOCATION_ROLLBACK", "previously revoked role references cannot become active again")
    changed = any(old[key] != new[key] for key in (
        "policy_identity", "profile_sha256", "build_inventory_sha256", "controller_id",
        "generation_id", "revocation_state_sha256",
    ))
    if new["policy_epoch"] == old["policy_epoch"] and changed:
        _fail("SAME_EPOCH_POLICY_CHANGE", "policy state changed without an epoch transition")
    if new["policy_epoch"] > old["policy_epoch"]:
        if new["profile_sha256"] == old["profile_sha256"] or new["generation_id"] == old["generation_id"]:
            _fail("EPOCH_TRANSITION_INVALID", "epoch transition must rotate Profile and Generation")
        if not record.get("owner_approval_reference"):
            _fail("OWNER_APPROVAL_REQUIRED", "historical epoch transition lacks an Owner approval reference")


@dataclass(frozen=True)
class LedgerRequest:
    policy_identity: str
    policy_epoch: int
    profile_sha256: str
    build_inventory_sha256: str
    controller_id: str
    generation_id: str
    index_sha256: str
    revocation_state_sha256: str
    operation_purpose: str


@dataclass(frozen=True)
class WitnessSnapshot:
    """An authenticated, typed Authority response; never construct from JSON alone."""

    authority_identity: str
    sequence: int
    head_state_digest: str
    head_record_sha256: str
    state: TrustState
    checked_at: datetime
    valid_until: datetime
    fencing_token: str
    history: tuple[dict[str, Any], ...]
    pending_transition_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransitionProposal:
    transition_id: str
    expected_sequence: int
    expected_state_digest: str
    previous_index_raw: bytes
    candidate_index_raw: bytes
    proposed_state: TrustState
    operation_purpose: str
    actor_principal: str
    owner_approval_reference: str


@dataclass(frozen=True)
class PreparedTransition:
    authority_identity: str
    transition_id: str
    status: str
    expected_sequence: int
    expected_state_digest: str
    proposed_state_digest: str
    proposed_index_sha256: str
    fencing_token: str
    approval_reference: str


@dataclass(frozen=True)
class TransitionStatus:
    authority_identity: str
    transition_id: str
    status: str
    expected_sequence: int
    expected_state_digest: str
    proposed_state_digest: str
    proposed_index_sha256: str
    prepared: PreparedTransition | None


@dataclass(frozen=True)
class VerifiedTransitionAuthorization:
    """Authority-verified purpose/actor approval bound to one exact transition."""

    authority_identity: str
    transition_id: str
    actor_principal: str
    approver_principal: str
    operation_purpose: str
    approval_reference: str
    authorization_class: str
    proposed_state_digest: str


class HighWaterAuthority(Protocol):
    """Future adapter to a separately protected, authenticated linearizable service."""

    def read_current(self) -> WitnessSnapshot: ...

    def prepare_transition(self, proposal: TransitionProposal) -> PreparedTransition: ...

    def verify_transition_authorization(self, proposal: TransitionProposal) -> VerifiedTransitionAuthorization: ...

    def commit_transition(self, prepared: PreparedTransition) -> WitnessSnapshot: ...

    def abort_transition(self, prepared: PreparedTransition, *, reason_code: str) -> None: ...

    def read_transition(self, transition_id: str) -> TransitionStatus | None: ...


@dataclass(frozen=True)
class GateResult:
    decision: str
    error_code: str | None
    authority_source_identity: str | None
    verified_policy_identity: str | None
    verified_epoch: int | None
    verified_profile_sha256: str | None
    verified_build_inventory_sha256: str | None
    verified_controller_id: str | None
    verified_generation_id: str | None
    verified_index_revision: int | None
    verified_index_sha256: str | None
    verified_revocation_state_sha256: str | None
    operation_purpose: str
    transition_id: str | None
    fencing_token: str | None
    checked_at: datetime
    expires_at: datetime
    invalidated_by: tuple[str, ...]


class AntiRollbackGate(Protocol):
    """C2-compatible Gate name with mandatory structured, state-complete result."""

    def check_current_state(self, *, policy_identity: str, policy_epoch: int,
                            index_sha256: str, operation_purpose: str,
                            profile_sha256: str, build_inventory_sha256: str,
                            controller_id: str, generation_id: str,
                            revocation_state_sha256: str) -> GateResult: ...


def _request_from_kwargs(kwargs: dict[str, Any]) -> LedgerRequest:
    required = (
        "policy_identity", "policy_epoch", "index_sha256", "operation_purpose",
        "profile_sha256", "build_inventory_sha256", "controller_id", "generation_id",
        "revocation_state_sha256",
    )
    missing = [name for name in required if name not in kwargs or kwargs[name] is None]
    if missing:
        _fail("GATE_REQUEST_INCOMPLETE", "Gate request lacks mandatory bindings: " + ", ".join(missing))
    request = LedgerRequest(**{name: kwargs[name] for name in required})
    if type(request.policy_epoch) is not int or request.policy_epoch < 1:
        _fail("EPOCH_INVALID", "Gate policy epoch is invalid")
    if request.operation_purpose not in PURPOSES:
        _fail("PURPOSE_INVALID", "Gate operation purpose is invalid")
    for label, value in (("Index SHA", request.index_sha256), ("Profile SHA", request.profile_sha256),
                         ("Build Inventory SHA", request.build_inventory_sha256),
                         ("revocation digest", request.revocation_state_sha256)):
        _sha(value, label)
    if any(not isinstance(value, str) or not value for value in
           (request.policy_identity, request.controller_id, request.generation_id)):
        _fail("GATE_REQUEST_INCOMPLETE", "Gate identity bindings must be non-empty strings")
    return request


def validate_gate_result(result: Any, *, request: LedgerRequest,
                         expected_authority_identity: str,
                         now: datetime | None = None) -> GateResult:
    """Reject booleans, Candidate JSON, stale decisions, and mismatched bindings."""
    if type(result) is not GateResult:
        _fail("GATE_RESULT_TYPE", "AntiRollbackGate must return the trusted structured GateResult type")
    if (not hasattr(result, "__dict__")
            or set(result.__dict__) != {field.name for field in fields(GateResult)}):
        _fail("GATE_RESULT_INVALID", "AntiRollbackGate returned an incomplete or malformed result object")
    current_time = _utc(now or datetime.now(timezone.utc))
    checked_at, expires_at = _utc(result.checked_at), _utc(result.expires_at)
    if result.decision != "verified" or result.error_code is not None:
        _fail(result.error_code or "GATE_NOT_VERIFIED", "AntiRollbackGate did not verify current state")
    if result.authority_source_identity != expected_authority_identity:
        _fail("AUTHORITY_IDENTITY_MISMATCH", "Gate result came from a different High-Water Authority")
    if (result.verified_policy_identity != request.policy_identity
            or result.verified_epoch != request.policy_epoch
            or result.verified_profile_sha256 != request.profile_sha256
            or result.verified_build_inventory_sha256 != request.build_inventory_sha256
            or result.verified_controller_id != request.controller_id
            or result.verified_generation_id != request.generation_id
            or result.verified_index_sha256 != request.index_sha256
            or result.verified_revocation_state_sha256 != request.revocation_state_sha256
            or result.operation_purpose != request.operation_purpose):
        _fail("GATE_BINDING_MISMATCH", "Gate result is not bound to the requested current operation state")
    if type(result.verified_index_revision) is not int or result.verified_index_revision < 0:
        _fail("REVISION_INVALID", "Gate result has no verified committed Index revision")
    if checked_at > current_time or expires_at < current_time:
        _fail("GATE_RESULT_STALE", "Gate result is expired or from the future")
    if (expires_at - checked_at).total_seconds() > MAX_AUTHORITY_AGE_SECONDS:
        _fail("GATE_RESULT_TTL", "Gate result exceeds the maximum verification age")
    if not result.fencing_token:
        _fail("FENCING_TOKEN_MISSING", "Gate result lacks a current Authority fencing token")
    return result


class MonotonicAntiRollbackGate:
    """Verify a local Index/Ledger projection against an independent Authority."""

    def __init__(self, *, authority: HighWaterAuthority,
                 expected_authority_identity: str,
                 ledger_reader: Callable[[], bytes],
                 index_reader: Callable[[], bytes],
                 recovery_reader: Callable[[], bool]):
        if not expected_authority_identity:
            _fail("AUTHORITY_IDENTITY_MISSING", "an independently pinned Authority identity is required")
        self._authority = authority
        self._authority_identity = expected_authority_identity
        self._ledger_reader = ledger_reader
        self._index_reader = index_reader
        self._recovery_reader = recovery_reader

    @property
    def authority_identity(self) -> str:
        """Identity fixed by the trusted Gate installation, not a request field."""
        return self._authority_identity

    def check_current_state(self, **kwargs: Any) -> GateResult:
        now = datetime.now(timezone.utc)
        try:
            request = _request_from_kwargs(kwargs)
            if self._recovery_reader():
                _fail("RECOVERY_REQUIRED", "local projection has an unresolved recovery marker")
            snapshot = self._authority.read_current()
            now = datetime.now(timezone.utc)
            now = datetime.now(timezone.utc)
            if type(snapshot) is not WitnessSnapshot:
                _fail("AUTHORITY_RESPONSE_TYPE", "High-Water Authority response is not an authenticated typed snapshot")
            if snapshot.authority_identity != self._authority_identity:
                _fail("AUTHORITY_IDENTITY_MISMATCH", "High-Water Authority identity differs from independent pin")
            records = verify_witness_snapshot(snapshot,
                                             expected_authority_identity=self._authority_identity,
                                             now=now)
            if snapshot.pending_transition_ids:
                _fail("RECOVERY_REQUIRED", "High-Water Authority has an unresolved transition")
            local_records = verify_ledger(
                self._ledger_reader(),
                expected_authority_identity=self._authority_identity,
                expected_head_state_digest=snapshot.head_state_digest,
                expected_head_record_sha256=snapshot.head_record_sha256,
                expected_sequence=snapshot.sequence,
            )
            if local_records != records:
                _fail("LEDGER_PROJECTION_MISMATCH", "local Ledger projection differs from independent Authority history")
            current_index_raw = self._index_reader()
            current_index = _parse_object(current_index_raw, "current Index")
            _schema(current_index, "protected-operation-index-v1.1.schema.json")
            if (hashlib.sha256(current_index_raw).hexdigest() != snapshot.state.index_sha256
                    or current_index["policy_epoch"] != snapshot.state.policy_epoch
                    or current_index["controller_id"] != snapshot.state.controller_id):
                _fail("CURRENT_INDEX_MISMATCH", "actual Index bytes or binding differ from High-Water state")
            checked_at, valid_until = _utc(snapshot.checked_at), _utc(snapshot.valid_until)
            state = snapshot.state
            expected = (
                state.policy_identity == request.policy_identity,
                state.policy_epoch == request.policy_epoch,
                state.profile_sha256 == request.profile_sha256,
                state.build_inventory_sha256 == request.build_inventory_sha256,
                state.controller_id == request.controller_id,
                state.generation_id == request.generation_id,
                state.index_sha256 == request.index_sha256,
                state.revocation_state_sha256 == request.revocation_state_sha256,
            )
            if not all(expected):
                _fail("CURRENT_STATE_MISMATCH", "current Profile, Build, Generation, Index, epoch, policy, or revocation differs from High-Water")
            return GateResult(
                decision="verified", error_code=None,
                authority_source_identity=self._authority_identity,
                verified_policy_identity=state.policy_identity,
                verified_epoch=state.policy_epoch,
                verified_profile_sha256=state.profile_sha256,
                verified_build_inventory_sha256=state.build_inventory_sha256,
                verified_controller_id=state.controller_id,
                verified_generation_id=state.generation_id,
                verified_index_revision=state.index_revision,
                verified_index_sha256=state.index_sha256,
                verified_revocation_state_sha256=state.revocation_state_sha256,
                operation_purpose=request.operation_purpose,
                transition_id=None, fencing_token=snapshot.fencing_token,
                checked_at=checked_at, expires_at=valid_until,
                invalidated_by=("policy/profile/build/index/revocation change",
                                "Authority fencing token advance", "verification expiry",
                                "Authority unavailability"),
            )
        except LedgerError as exc:
            decision = "recovery_required" if exc.code.startswith("RECOVERY") or exc.code.startswith("LEDGER_") else "blocked"
            return GateResult(
                decision=decision, error_code=exc.code,
                authority_source_identity=self._authority_identity,
                verified_policy_identity=None, verified_epoch=None,
                verified_profile_sha256=None, verified_build_inventory_sha256=None,
                verified_controller_id=None, verified_generation_id=None,
                verified_index_revision=None, verified_index_sha256=None,
                verified_revocation_state_sha256=None,
                operation_purpose=str(kwargs.get("operation_purpose", "unknown")),
                transition_id=None, fencing_token=None,
                checked_at=now, expires_at=now,
                invalidated_by=("verification failure",),
            )
        except Exception:
            return GateResult(
                decision="blocked", error_code="AUTHORITY_UNAVAILABLE",
                authority_source_identity=self._authority_identity,
                verified_policy_identity=None, verified_epoch=None,
                verified_profile_sha256=None, verified_build_inventory_sha256=None,
                verified_controller_id=None, verified_generation_id=None,
                verified_index_revision=None, verified_index_sha256=None,
                verified_revocation_state_sha256=None,
                operation_purpose=str(kwargs.get("operation_purpose", "unknown")),
                transition_id=None, fencing_token=None,
                checked_at=now, expires_at=now,
                invalidated_by=("verification failure",),
            )


def validate_transition_proposal(proposal: TransitionProposal,
                                 snapshot: WitnessSnapshot,
                                 *, authorization: VerifiedTransitionAuthorization,
                                 expected_authority_identity: str) -> dict[str, Any]:
    """Check CAS token inputs and append-only Index bytes before Authority prepare."""
    if proposal.expected_sequence != snapshot.sequence:
        _fail("CAS_SEQUENCE_STALE", "transition used a stale committed sequence")
    if proposal.expected_state_digest != snapshot.head_state_digest:
        _fail("CAS_HEAD_STALE", "transition used a stale committed state digest")
    if not TRANSITION_RE.fullmatch(proposal.transition_id):
        _fail("TRANSITION_ID_INVALID", "transition ID has an invalid format")
    if not proposal.actor_principal or not proposal.owner_approval_reference:
        _fail("AUTHORIZATION_MISSING", "actor and Owner approval reference are required")
    if proposal.operation_purpose not in PURPOSES:
        _fail("PURPOSE_INVALID", "operation purpose is not a closed C3 purpose")
    current_state = proposal.proposed_state
    if ((current_state.policy_epoch > snapshot.state.policy_epoch
         and proposal.operation_purpose not in {"epoch_transition", "revocation"})
            or (current_state.policy_epoch == snapshot.state.policy_epoch
                and proposal.operation_purpose in {"epoch_transition", "revocation"})):
        _fail("PURPOSE_STATE_MISMATCH", "epoch and revocation changes require the matching transition purpose")
    if (type(authorization) is not VerifiedTransitionAuthorization
            or authorization.authority_identity != expected_authority_identity
            or authorization.transition_id != proposal.transition_id
            or authorization.actor_principal != proposal.actor_principal
            or not authorization.approver_principal
            or authorization.approver_principal == authorization.actor_principal
            or authorization.operation_purpose != proposal.operation_purpose
            or authorization.approval_reference != proposal.owner_approval_reference
            or authorization.authorization_class not in {"operator_role_operation", "owner_policy_transition"}
            or authorization.proposed_state_digest != _digest(current_state.payload())):
        _fail("AUTHORIZATION_BINDING_MISMATCH", "independent Authority authorization is not bound to this exact transition")
    validate_state_successor(snapshot.state, current_state,
                             authorization=authorization,
                             expected_authority_identity=expected_authority_identity,
                             transition_id=proposal.transition_id)
    validate_index_append(
        proposal.previous_index_raw, proposal.candidate_index_raw,
        expected_epoch=current_state.policy_epoch,
        expected_controller_id=current_state.controller_id,
        expected_previous_sha256=snapshot.state.index_sha256,
        expected_current_sha256=current_state.index_sha256,
        allow_policy_transition=(current_state.policy_epoch > snapshot.state.policy_epoch),
        allow_empty_transition=(current_state.policy_epoch > snapshot.state.policy_epoch),
    )
    return {
        "transition_version": TRANSITION_VERSION,
        "transition_id": proposal.transition_id,
        "authority_identity": snapshot.authority_identity,
        "expected_sequence": proposal.expected_sequence,
        "expected_state_digest": proposal.expected_state_digest,
        "proposed_state_digest": _digest(current_state.payload()),
        "operation_purpose": proposal.operation_purpose,
        "actor_principal": proposal.actor_principal,
        "owner_approval_reference": proposal.owner_approval_reference,
        "status": "prepared",
        "fencing_token": snapshot.fencing_token,
        "audit_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "resolution_code": None,
    }


def validate_prepared_transition(prepared: Any, *, proposal: TransitionProposal,
                                 authority_identity: str, snapshot: WitnessSnapshot) -> PreparedTransition:
    if type(prepared) is not PreparedTransition:
        _fail("AUTHORITY_RESPONSE_TYPE", "Authority did not return a typed prepared transition")
    if (prepared.authority_identity != authority_identity
            or prepared.transition_id != proposal.transition_id
            or prepared.status != "prepared"
            or prepared.expected_sequence != snapshot.sequence
            or prepared.expected_state_digest != snapshot.head_state_digest
            or prepared.proposed_state_digest != _digest(proposal.proposed_state.payload())
            or prepared.proposed_index_sha256 != proposal.proposed_state.index_sha256
            or prepared.approval_reference != proposal.owner_approval_reference
            or not prepared.fencing_token):
        _fail("PREPARE_BINDING_MISMATCH", "Authority prepared a different or stale transition")
    return prepared


class ProjectionStore(Protocol):
    """Durable local projection with exclusive staging and atomic replace."""

    def read_index(self) -> bytes: ...

    def read_ledger(self) -> bytes: ...

    def stage_index(self, transition_id: str, raw: bytes) -> None: ...

    def staged_index(self, transition_id: str) -> bytes | None: ...

    def install_staged_index(self, transition_id: str) -> None: ...

    def install_ledger(self, raw: bytes) -> None: ...

    def mark_recovery_required(self, transition_id: str, code: str) -> None: ...

    def clear_recovery_required(self, transition_id: str) -> None: ...

    def recovery_required(self) -> bool: ...


class DirectoryProjectionStore:
    """Operator-owned atomic local projection; never a High-Water trust root.

    The directory must already exist. This class refuses path aliases, ACLs,
    links, unexpected owners, writable ancestors, and unprivileged callers.
    Its atomic renames protect local consistency only; a snapshot can still
    restore the complete directory and therefore requires an external Witness.
    """

    def __init__(self, root: Path, *, operator_uid: int,
                 max_bytes: int = 64 * 1024 * 1024):
        self.root = Path(root)
        self.operator_uid = operator_uid
        self.max_bytes = max_bytes
        if os.getuid() != operator_uid or os.geteuid() != operator_uid:
            _fail("OPERATOR_IDENTITY_MISMATCH", "projection store must run under the real Operator UID")
        if not self.root.is_absolute() or self.root.resolve(strict=True) != self.root:
            _fail("PROJECTION_PATH_ALIAS", "projection root must be a canonical existing absolute path")
        cursor = Path(self.root.anchor)
        for part in self.root.parts[1:]:
            cursor = cursor / part
            info = cursor.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                _fail("PROJECTION_PATH_UNSAFE", "projection ancestor is linked or not a directory")
            owners = {0, operator_uid} if cursor != self.root else {operator_uid}
            if info.st_uid not in owners or info.st_mode & 0o022:
                _fail("PROJECTION_ANCESTOR_UNSAFE", "projection ancestor ownership or mode is unsafe")
            if hasattr(os, "listxattr"):
                try:
                    attrs = set(os.listxattr(cursor, follow_symlinks=False))
                except OSError as exc:
                    raise LedgerError("PROJECTION_ACL_UNVERIFIED", "projection ACL inspection failed") from exc
                if {"system.posix_acl_access", "system.posix_acl_default"} & attrs:
                    _fail("PROJECTION_ACL_PRESENT", "extended ACLs are forbidden on projection ancestors")
        flags = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                 | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
        try:
            self._dir_fd = os.open(self.root, flags)
        except OSError as exc:
            raise LedgerError("PROJECTION_ROOT_OPEN", "projection root cannot be pinned safely") from exc
        info = os.fstat(self._dir_fd)
        if info.st_uid != operator_uid or info.st_mode & 0o077:
            os.close(self._dir_fd)
            _fail("PROJECTION_ROOT_MODE", "projection root must be Operator-owned and private")
        self._root_identity = (info.st_dev, info.st_ino)

    def close(self) -> None:
        if getattr(self, "_dir_fd", None) is not None:
            os.close(self._dir_fd)
            self._dir_fd = None

    def _check_root(self) -> None:
        info = os.fstat(self._dir_fd)
        current = self.root.lstat()
        if ((info.st_dev, info.st_ino) != self._root_identity
                or (current.st_dev, current.st_ino) != self._root_identity
                or current.st_uid != self.operator_uid or current.st_mode & 0o077):
            _fail("PROJECTION_ROOT_REPLACED", "Operator projection path changed after pinning")

    def _read_name(self, name: str) -> bytes:
        self._check_root()
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_CLOEXEC", 0), dir_fd=self._dir_fd)
        except OSError as exc:
            raise LedgerError("PROJECTION_FILE_OPEN", "projection file cannot be opened safely") from exc
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != self.operator_uid or before.st_mode & 0o022
                    or before.st_size > self.max_bytes):
                _fail("PROJECTION_FILE_UNSAFE", "projection file identity, owner, mode, link count, or size is unsafe")
            chunks: list[bytes] = []
            total = 0
            while total <= self.max_bytes:
                block = os.read(fd, min(1024 * 1024, self.max_bytes + 1 - total))
                if not block:
                    break
                chunks.append(block)
                total += len(block)
            after = os.fstat(fd)
            current = os.stat(name, dir_fd=self._dir_fd, follow_symlinks=False)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino)
                    or total > self.max_bytes):
                _fail("PROJECTION_FILE_CHANGED", "projection file changed during read")
            return b"".join(chunks)
        finally:
            os.close(fd)

    def _write_exclusive(self, name: str, raw: bytes) -> None:
        self._check_root()
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                         0o600, dir_fd=self._dir_fd)
        except OSError as exc:
            raise LedgerError("PROJECTION_NO_OVERWRITE", "exclusive projection file creation failed") from exc
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    _fail("PROJECTION_WRITE_FAILED", "projection write made no progress")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self._dir_fd)
        self._check_root()

    def read_index(self) -> bytes:
        return self._read_name("operation-index.json")

    def read_ledger(self) -> bytes:
        return self._read_name("ledger-projection.json")

    def stage_index(self, transition_id: str, raw: bytes) -> None:
        if not TRANSITION_RE.fullmatch(transition_id):
            _fail("TRANSITION_ID_INVALID", "invalid staged transition ID")
        if len(raw) > self.max_bytes:
            _fail("PROJECTION_TOO_LARGE", "staged Index exceeds configured maximum")
        self._write_exclusive(f"index.{transition_id}.staged", raw)

    def staged_index(self, transition_id: str) -> bytes | None:
        name = f"index.{transition_id}.staged"
        try:
            return self._read_name(name)
        except LedgerError as exc:
            try:
                os.stat(name, dir_fd=self._dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            raise exc

    def install_staged_index(self, transition_id: str) -> None:
        source = f"index.{transition_id}.staged"
        candidate = self._read_name(source)
        self._read_name("operation-index.json")
        self._check_root()
        os.replace(source, "operation-index.json", src_dir_fd=self._dir_fd,
                   dst_dir_fd=self._dir_fd)
        os.fsync(self._dir_fd)
        if self._read_name("operation-index.json") != candidate:
            _fail("PROJECTION_INSTALL_MISMATCH", "atomic Index install did not preserve exact staged bytes")

    def install_ledger(self, raw: bytes) -> None:
        if len(raw) > self.max_bytes:
            _fail("PROJECTION_TOO_LARGE", "Ledger projection exceeds configured maximum")
        name = f"ledger.{secrets.token_hex(16)}.staged"
        self._write_exclusive(name, raw)
        self._read_name("ledger-projection.json")
        self._check_root()
        os.replace(name, "ledger-projection.json", src_dir_fd=self._dir_fd,
                   dst_dir_fd=self._dir_fd)
        os.fsync(self._dir_fd)
        if self._read_name("ledger-projection.json") != raw:
            _fail("PROJECTION_INSTALL_MISMATCH", "atomic Ledger install did not preserve exact bytes")

    def mark_recovery_required(self, transition_id: str, code: str) -> None:
        if not TRANSITION_RE.fullmatch(transition_id) or not re.fullmatch(r"[A-Z0-9_]{1,64}", code):
            _fail("RECOVERY_MARKER_INVALID", "recovery marker identity or code is invalid")
        raw = canonical_json_bytes({"status": "recovery_required", "transition_id": transition_id,
                                    "error_code": code}) + b"\n"
        self._write_exclusive(f"recovery-required.{transition_id}.json", raw)

    def clear_recovery_required(self, transition_id: str) -> None:
        name = f"recovery-required.{transition_id}.json"
        try:
            info = os.stat(name, dir_fd=self._dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.operator_uid or info.st_nlink != 1:
            _fail("RECOVERY_MARKER_UNSAFE", "recovery marker has an unsafe filesystem identity")
        os.unlink(name, dir_fd=self._dir_fd)
        os.fsync(self._dir_fd)

    def recovery_required(self) -> bool:
        self._check_root()
        return any(name.startswith("recovery-required.") and name.endswith(".json")
                   for name in os.listdir(self._dir_fd))


class MonotonicTransitionCoordinator:
    """Witness-fenced transition engine; uncertain cross-domain state stops."""

    def __init__(self, *, authority: HighWaterAuthority,
                 authority_identity: str, store: ProjectionStore,
                 now: Callable[[], datetime] | None = None):
        self.authority = authority
        self.authority_identity = authority_identity
        self.store = store
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _snapshot(self) -> WitnessSnapshot:
        value = self.authority.read_current()
        if type(value) is not WitnessSnapshot or value.authority_identity != self.authority_identity:
            _fail("AUTHORITY_RESPONSE_TYPE", "independent Authority response failed identity/type validation")
        verify_witness_snapshot(value, expected_authority_identity=self.authority_identity,
                                now=self.now())
        return value

    def commit(self, proposal: TransitionProposal, *,
               failpoint: Callable[[str], None] | None = None) -> WitnessSnapshot:
        """Prepare, stage, Authority-CAS, install, and independently reread.

        The linearization point is the High-Water Authority's conditional
        ``commit_transition``.  A failure after it is committed never rolls the
        witness back; it records recovery-required locally and returns no success.
        """
        hit = failpoint or (lambda _stage: None)
        prepared: PreparedTransition | None = None
        committed = False
        prepare_attempted = False
        transition_id = proposal.transition_id
        try:
            snapshot = self._snapshot()
            prior_status = self.authority.read_transition(transition_id)
            if prior_status is not None and (type(prior_status) is not TransitionStatus
                                             or prior_status.authority_identity != self.authority_identity):
                _fail("AUTHORITY_RESPONSE_TYPE", "Authority transition lookup is not independently verifiable")
            if prior_status is not None and prior_status.status == "committed":
                if prior_status.proposed_state_digest != _digest(proposal.proposed_state.payload()):
                    _fail("TRANSITION_ID_REUSE", "committed transition ID cannot be rebound to different state")
                snapshot = self.recover(transition_id=transition_id)
                if _digest(snapshot.state.payload()) != prior_status.proposed_state_digest:
                    _fail("TRANSITION_ALREADY_SUPERSEDED", "committed transition is no longer the current state")
                return snapshot
            if prior_status is not None and prior_status.status in {"aborted", "unresolved", "prepared"}:
                _fail("RECOVERY_REQUIRED", "transition ID already has a non-new Authority state")
            if prior_status is not None and prior_status.status not in {"committed", "aborted", "unresolved", "prepared"}:
                _fail("TRANSITION_STATUS_INVALID", "Authority returned an unknown transition state")
            if self.store.recovery_required():
                _fail("RECOVERY_REQUIRED", "Operator projection is marked for another unresolved recovery")
            if snapshot.pending_transition_ids:
                _fail("RECOVERY_REQUIRED", "an unresolved Authority transition must be recovered first")
            local_records = verify_ledger(
                self.store.read_ledger(),
                expected_authority_identity=self.authority_identity,
                expected_head_state_digest=snapshot.head_state_digest,
                expected_head_record_sha256=snapshot.head_record_sha256,
                expected_sequence=snapshot.sequence,
            )
            if local_records != snapshot.history:
                _fail("LEDGER_PROJECTION_MISMATCH", "local Ledger history differs from independent Authority history")
            current_index = self.store.read_index()
            if hashlib.sha256(current_index).hexdigest() != snapshot.state.index_sha256:
                _fail("CURRENT_INDEX_MISMATCH", "local Index does not match independent committed state")
            if proposal.previous_index_raw != current_index:
                _fail("STALE_INDEX_BYTES", "transition source bytes differ from the current Index")
            validate_transition_proposal(proposal, snapshot,
                                         authorization=self.authority.verify_transition_authorization(proposal),
                                         expected_authority_identity=self.authority_identity)
            hit("validated")
            prepare_attempted = True
            prepared_value = self.authority.prepare_transition(proposal)
            prepared = validate_prepared_transition(
                prepared_value, proposal=proposal,
                authority_identity=self.authority_identity, snapshot=snapshot,
            )
            hit("prepared")
            self.store.stage_index(transition_id, proposal.candidate_index_raw)
            staged = self.store.staged_index(transition_id)
            if staged != proposal.candidate_index_raw:
                _fail("STAGED_INDEX_MISMATCH", "staged Index bytes differ from the approved candidate")
            hit("index_staged")
            committed_snapshot = self.authority.commit_transition(prepared)
            committed = True
            if type(committed_snapshot) is not WitnessSnapshot:
                _fail("AUTHORITY_RESPONSE_TYPE", "Authority commit did not return a typed snapshot")
            hit("authority_committed")
            self.store.install_staged_index(transition_id)
            hit("index_installed")
            self.store.install_ledger(encode_ledger(self.authority_identity,
                                                    list(committed_snapshot.history)))
            hit("ledger_projected")
            final_snapshot = self._snapshot()
            if (final_snapshot.sequence != committed_snapshot.sequence
                    or final_snapshot.head_state_digest != committed_snapshot.head_state_digest
                    or final_snapshot.head_record_sha256 != committed_snapshot.head_record_sha256
                    or final_snapshot.pending_transition_ids):
                _fail("FINAL_WITNESS_RECHECK", "independent High-Water state changed or remained unresolved")
            final_index = self.store.read_index()
            if hashlib.sha256(final_index).hexdigest() != final_snapshot.state.index_sha256:
                _fail("FINAL_INDEX_RECHECK", "installed Index does not match latest Authority state")
            verify_ledger(
                self.store.read_ledger(),
                expected_authority_identity=self.authority_identity,
                expected_head_state_digest=final_snapshot.head_state_digest,
                expected_head_record_sha256=final_snapshot.head_record_sha256,
                expected_sequence=final_snapshot.sequence,
            )
            hit("final_recheck")
            return final_snapshot
        except Exception as exc:
            code = getattr(exc, "code", None) or "TRANSITION_FAILED"
            uncertain = committed
            if prepared is not None and not committed:
                try:
                    # A prepared reservation can be aborted only while the local
                    # committed Index remains byte-identical to its old state.
                    local = self.store.read_index()
                    old_snapshot = self._snapshot()
                    if hashlib.sha256(local).hexdigest() == old_snapshot.state.index_sha256:
                        self.authority.abort_transition(prepared, reason_code=code)
                    else:
                        self.store.mark_recovery_required(transition_id, code)
                        uncertain = True
                except Exception:
                    self.store.mark_recovery_required(transition_id, "ABORT_UNCERTAIN")
                    uncertain = True
            elif prepare_attempted and not committed:
                if isinstance(exc, LedgerError) and exc.code in DEFINITE_PREPARE_REJECTIONS:
                    # A typed Authority rejection proves that this transition
                    # was not reserved. Another writer may have advanced the
                    # sequence; that does not make this writer unresolved.
                    uncertain = False
                else:
                    try:
                        current = self._snapshot()
                        if (transition_id in current.pending_transition_ids
                                or current.sequence != proposal.expected_sequence
                                or current.head_state_digest != proposal.expected_state_digest):
                            self.store.mark_recovery_required(transition_id, "PREPARE_ACK_UNCERTAIN")
                            uncertain = True
                    except Exception:
                        self.store.mark_recovery_required(transition_id, "PREPARE_STATUS_UNAVAILABLE")
                        uncertain = True
            elif committed:
                self.store.mark_recovery_required(transition_id, code)
            if (not uncertain and prepared is None and not prepare_attempted
                    and isinstance(exc, LedgerError)):
                raise
            raise LedgerError(
                "RECOVERY_REQUIRED" if uncertain else "TRANSITION_ABORTED",
                f"{code}: transition state is uncertain; explicit recovery is required" if uncertain
                else f"{code}: transition failed before commit and was not accepted",
            ) from exc

    def recover(self, *, transition_id: str) -> WitnessSnapshot:
        """Reconcile only against the Authority's latest committed state.

        The adapter may expose an outstanding prepared transition, but this
        generic foundation will not invent or restore bytes. Missing, conflicting,
        or ambiguous staged bytes remain RECOVERY_REQUIRED for an Owner-run recovery.
        """
        snapshot = self._snapshot()
        local_index = self.store.read_index()
        staged = self.store.staged_index(transition_id)
        if snapshot.pending_transition_ids:
            if snapshot.pending_transition_ids != (transition_id,):
                self.store.mark_recovery_required(transition_id, "PENDING_TRANSITION_ID_MISMATCH")
                _fail("RECOVERY_REQUIRED", "Authority reports a different or multiple pending transition")
            status = self.authority.read_transition(transition_id)
            if (type(status) is not TransitionStatus
                    or status.authority_identity != self.authority_identity
                    or status.transition_id != transition_id
                    or status.status != "prepared"
                    or type(status.prepared) is not PreparedTransition
                    or status.expected_sequence != snapshot.sequence
                    or status.expected_state_digest != snapshot.head_state_digest):
                self.store.mark_recovery_required(transition_id, "PREPARED_STATUS_INVALID")
                _fail("RECOVERY_REQUIRED", "pending Authority transition cannot be independently reconciled")
            local_sha = hashlib.sha256(local_index).hexdigest()
            if local_sha != snapshot.state.index_sha256:
                self.store.mark_recovery_required(transition_id, "LOCAL_INDEX_DIVERGED_DURING_PREPARE")
                _fail("RECOVERY_REQUIRED", "local committed Index changed before Authority linearization")
            if staged is None:
                self.authority.abort_transition(status.prepared,
                                                reason_code="RECOVERY_ABORT_UNSTAGED")
                current = self._snapshot()
                self.store.install_ledger(encode_ledger(self.authority_identity,
                                                        list(current.history)))
                self.store.clear_recovery_required(transition_id)
                return current
            if hashlib.sha256(staged).hexdigest() != status.proposed_index_sha256:
                self.store.mark_recovery_required(transition_id, "STAGED_INDEX_SHA_MISMATCH")
                _fail("RECOVERY_REQUIRED", "prepared transition staged bytes do not match Authority proposal")
            committed = self.authority.commit_transition(status.prepared)
            if type(committed) is not WitnessSnapshot:
                self.store.mark_recovery_required(transition_id, "COMMIT_STATUS_INVALID")
                _fail("RECOVERY_REQUIRED", "Authority commit status is not independently verifiable")
            snapshot = self._snapshot()
            if snapshot.sequence != committed.sequence or snapshot.head_state_digest != committed.head_state_digest:
                self.store.mark_recovery_required(transition_id, "RECOVERY_COMMIT_MISMATCH")
                _fail("RECOVERY_REQUIRED", "Authority state changed while resolving the prepared transition")
        if hashlib.sha256(local_index).hexdigest() != snapshot.state.index_sha256:
            if staged is None or hashlib.sha256(staged).hexdigest() != snapshot.state.index_sha256:
                self.store.mark_recovery_required(transition_id, "COMMITTED_INDEX_BYTES_UNAVAILABLE")
                _fail("RECOVERY_REQUIRED", "latest committed Index bytes are unavailable; no rollback or reset is permitted")
            self.store.install_staged_index(transition_id)
        self.store.install_ledger(encode_ledger(self.authority_identity,
                                                list(snapshot.history)))
        final = self._snapshot()
        if final.pending_transition_ids or final.head_state_digest != snapshot.head_state_digest:
            self.store.mark_recovery_required(transition_id, "RECOVERY_REREAD_MISMATCH")
            _fail("RECOVERY_REQUIRED", "Authority changed during recovery")
        if hashlib.sha256(self.store.read_index()).hexdigest() != final.state.index_sha256:
            self.store.mark_recovery_required(transition_id, "RECOVERY_INDEX_MISMATCH")
            _fail("RECOVERY_REQUIRED", "recovered Index does not match the latest committed state")
        verify_ledger(
            self.store.read_ledger(), expected_authority_identity=self.authority_identity,
            expected_head_state_digest=final.head_state_digest,
            expected_head_record_sha256=final.head_record_sha256,
            expected_sequence=final.sequence,
        )
        self.store.clear_recovery_required(transition_id)
        return final


def encode_transition(payload: dict[str, Any]) -> bytes:
    _schema(payload, TRANSITION_SCHEMA)
    return canonical_json_bytes(payload) + b"\n"
