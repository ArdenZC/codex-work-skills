"""Synthetic Spanner Authority research prototype.

This module is research-only. It is never imported by a shipped Controller.
The emulator path deliberately uses a synthetic peer authenticator and an
in-memory external checkpoint; neither is a production trust root.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

from google.cloud import spanner
from google.cloud.spanner_v1 import param_types


REPO_ROOT = Path(__file__).resolve().parents[2]
C3_SCRIPTS = REPO_ROOT / "教案生成器" / "lesson-plan-docx-generator" / "scripts"
sys.path.insert(0, str(C3_SCRIPTS))
import rq03f_monotonic_trust_ledger as c3  # noqa: E402


AUTHORITY_ID = "synthetic-spanner-authority-only"
HEAD_ID = "authority-head"
TRANSITION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
REQUEST_KEYS = frozenset({
    "transition_id", "expected_sequence", "expected_state_digest",
    "operation_purpose", "approval_reference", "proposed_state",
    "candidate_index_b64",
})
HEAD_COLUMNS = (
    "HeadId", "Sequence", "StateJSONB64", "StateDigest", "PolicyEpoch",
    "IndexRevision", "IndexSHA256", "IndexBytesB64", "RevocationStateSHA256",
    "FencingToken", "PendingTransitionId",
)
TRANSITION_COLUMNS = (
    "TransitionId", "Status", "RequestJSONB64", "RequestSHA256",
    "ActorPrincipal", "OperationPurpose", "ApprovalReference",
    "AuthorizedRole", "AuthorizationClass", "AuthorizationEpoch",
    "RevocationSHA256", "ExpectedSequence", "ExpectedStateDigest",
    "ProposedStateDigest", "ProposedIndexRevision", "ProposedIndexSHA256",
    "CandidateIndexB64", "ReservationExpiresAt", "FencingToken",
    "ResolutionCode", "ResultSequence", "ResultStateDigest",
)
ROLE_COLUMNS = (
    "AuthorizationReference", "Principal", "Role", "AuthorizationClass",
    "OperationPurpose", "Epoch", "ValidFrom", "ValidUntil", "Revoked",
    "ApproverPrincipal",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _encode_bytes(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode_bytes(encoded: str) -> bytes:
    return base64.b64decode(encoded.encode("ascii"), validate=True)


def require_local_emulator() -> None:
    if os.environ.get("SPANNER_EMULATOR_HOST") not in {
        "127.0.0.1:9010", "localhost:9010",
    }:
        raise AuthorityError(
            "EMULATOR_ONLY",
            "research adapter refuses every endpoint except the local Spanner Emulator",
        )


class AuthorityError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class CommitOutcomeUnknown(AuthorityError):
    """The caller cannot safely infer whether the Authority committed."""

    def __init__(self, message: str):
        super().__init__("COMMIT_STATUS_UNKNOWN", message)


@dataclass(frozen=True)
class AuthenticatedPeer:
    principal: str
    synthetic_channel: str = "emulator-test-only"


class SyntheticPeerAuthenticator:
    """Test stub. Real transport identity and TLS are not exercised here."""

    def __init__(self, tokens: dict[str, str]):
        self._tokens = dict(tokens)

    def authenticate(self, token: str) -> AuthenticatedPeer:
        principal = self._tokens.get(token)
        if not principal:
            raise AuthorityError("ACTOR_IDENTITY_REJECTED", "synthetic peer token is unknown")
        return AuthenticatedPeer(principal)


@dataclass(frozen=True)
class OperatorRequest:
    transition_id: str
    expected_sequence: int
    expected_state_digest: str
    operation_purpose: str
    approval_reference: str
    proposed_state: dict[str, Any]
    candidate_index_raw: bytes

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> "OperatorRequest":
        if not isinstance(payload, dict) or set(payload) != REQUEST_KEYS:
            raise AuthorityError(
                "REQUEST_FIELDS_INVALID",
                "request fields are closed; caller-supplied actor, role, fence, or timestamps are forbidden",
            )
        transition_id = payload["transition_id"]
        if not isinstance(transition_id, str) or not TRANSITION_ID_RE.fullmatch(transition_id):
            raise AuthorityError("TRANSITION_ID_INVALID", "Transition ID format is invalid")
        if type(payload["expected_sequence"]) is not int or payload["expected_sequence"] < 0:
            raise AuthorityError("CAS_SEQUENCE_INVALID", "expected sequence must be a non-negative integer")
        if (not isinstance(payload["expected_state_digest"], str)
                or not c3.SHA256_RE.fullmatch(payload["expected_state_digest"])):
            raise AuthorityError("CAS_DIGEST_INVALID", "expected state digest must be lowercase SHA-256")
        if payload["operation_purpose"] not in c3.PURPOSES:
            raise AuthorityError("PURPOSE_INVALID", "operation purpose is outside the closed C3 set")
        if not isinstance(payload["approval_reference"], str) or not payload["approval_reference"]:
            raise AuthorityError("AUTHORIZATION_MISSING", "Owner authorization reference is required")
        if not isinstance(payload["proposed_state"], dict):
            raise AuthorityError("STATE_INVALID", "proposed state must be an object")
        try:
            state = c3.TrustState.from_payload(payload["proposed_state"])
            state.payload()
        except Exception as exc:
            raise AuthorityError("STATE_INVALID", "proposed state failed the C3 state contract") from exc
        encoded = payload["candidate_index_b64"]
        if not isinstance(encoded, str):
            raise AuthorityError("INDEX_BYTES_INVALID", "candidate Index must be exact base64 bytes")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise AuthorityError("INDEX_BYTES_INVALID", "candidate Index is not valid base64") from exc
        if not raw:
            raise AuthorityError("INDEX_BYTES_INVALID", "candidate Index bytes are empty")
        return cls(
            transition_id, payload["expected_sequence"],
            payload["expected_state_digest"], payload["operation_purpose"],
            payload["approval_reference"], state.payload(), raw,
        )

    def wire(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "expected_sequence": self.expected_sequence,
            "expected_state_digest": self.expected_state_digest,
            "operation_purpose": self.operation_purpose,
            "approval_reference": self.approval_reference,
            "proposed_state": self.proposed_state,
            "candidate_index_b64": base64.b64encode(self.candidate_index_raw).decode("ascii"),
        }


@dataclass(frozen=True)
class Head:
    sequence: int
    state: c3.TrustState
    state_digest: str
    index_raw: bytes
    index_sha256: str
    fencing_token: int
    pending_transition_id: str | None


@dataclass(frozen=True)
class Snapshot:
    sequence: int
    state_digest: str
    policy_epoch: int
    index_revision: int
    index_sha256: str
    fencing_token: int


class InMemoryExternalCheckpoint:
    """A deliberately non-durable stand-in for an independent Owner domain."""

    def __init__(self, initial: Snapshot):
        self._snapshot = initial
        self.available = True

    def current(self) -> Snapshot:
        if not self.available:
            raise AuthorityError("CHECKPOINT_UNAVAILABLE", "synthetic external checkpoint is unavailable")
        return self._snapshot

    def advance(self, candidate: Snapshot) -> None:
        if not self.available:
            raise AuthorityError("CHECKPOINT_UNAVAILABLE", "synthetic external checkpoint is unavailable")
        current = self._snapshot
        if (candidate.sequence < current.sequence
                or candidate.fencing_token < current.fencing_token):
            raise AuthorityError("CHECKPOINT_ROLLBACK", "checkpoint cannot move backward")
        if candidate.sequence == current.sequence and (
            candidate.state_digest != current.state_digest
            or candidate.index_revision != current.index_revision
            or candidate.index_sha256 != current.index_sha256
        ):
            raise AuthorityError("CHECKPOINT_DIVERGENCE", "same-sequence state differs from checkpoint")
        self._snapshot = candidate


class FaultPlan:
    """One-shot post-transaction faults; never invoked inside a retryable callback."""

    def __init__(self):
        self.abort_commit_before_transaction = False
        self.lose_commit_ack = False
        self.hide_checkpoint_after_commit = False


class SpannerAuthorityService:
    """Research-only server wrapper; only this object holds the DB handle."""

    def __init__(
        self,
        database: spanner.database.Database,
        checkpoint: InMemoryExternalCheckpoint,
        *,
        clock: Callable[[], datetime] | None = None,
        faults: FaultPlan | None = None,
        reservation_ttl: timedelta = timedelta(minutes=5),
    ):
        require_local_emulator()
        self.__database = database
        self.__checkpoint = checkpoint
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.faults = faults or FaultPlan()
        self._reservation_ttl = reservation_ttl

    @staticmethod
    def _read_sql(source: Any, sql: str, params: dict[str, Any] | None = None,
                  types: dict[str, Any] | None = None) -> list[Any]:
        if (
            callable(getattr(source, "snapshot", None))
            and not callable(getattr(source, "execute_sql", None))
        ):
            with source.snapshot() as reader:
                return list(reader.execute_sql(
                    sql, params=params or {}, param_types=types or {},
                ))
        return list(source.execute_sql(
            sql, params=params or {}, param_types=types or {},
        ))

    @classmethod
    def _read_head(cls, transaction: Any) -> Head:
        rows = cls._read_sql(
            transaction,
            "SELECT Sequence, StateJSONB64, StateDigest, PolicyEpoch, IndexRevision, "
            "IndexBytesB64, IndexSHA256, RevocationStateSHA256, FencingToken, "
            "PendingTransitionId FROM AuthorityHead WHERE HeadId=@head_id",
            {"head_id": HEAD_ID}, {"head_id": param_types.STRING},
        )
        if len(rows) != 1:
            raise AuthorityError("AUTHORITY_HEAD_MISSING", "Authority head is absent or duplicated")
        row = rows[0]
        try:
            state_raw = _decode_bytes(row[1])
            index_raw = _decode_bytes(row[5])
            state = c3.TrustState.from_payload(json.loads(state_raw))
            sequence = int(row[0])
            policy_epoch = int(row[3])
            index_revision = int(row[4])
            fencing_token = int(row[8])
            computed_state = c3._digest(state.payload())
            computed_index = sha256(index_raw)
            if (not isinstance(row[2], str) or not c3.SHA256_RE.fullmatch(row[2])
                    or not isinstance(row[6], str) or not c3.SHA256_RE.fullmatch(row[6])
                    or not isinstance(row[7], str) or not c3.SHA256_RE.fullmatch(row[7])
                    or computed_state != row[2] or computed_index != row[6]):
                raise ValueError("stored state or Index bytes fail their SHA binding")
            if (sequence < 0 or fencing_token < 0 or policy_epoch < 1 or index_revision < 0
                    or state.policy_epoch != policy_epoch
                    or state.index_revision != index_revision
                    or state.revocation_state_sha256 != row[7]
                    or state.index_sha256 != computed_index):
                raise ValueError("AuthorityHead mirror columns disagree with validated TrustState")
        except Exception as exc:
            if isinstance(exc, AuthorityError) and exc.code == "AUTHORITY_HEAD_CORRUPT":
                raise
            raise AuthorityError(
                "AUTHORITY_HEAD_CORRUPT",
                "AuthorityHead bytes, SHA values, or PolicyEpoch/IndexRevision/RevocationStateSHA256 mirrors disagree",
            ) from exc
        return Head(sequence, state, row[2], index_raw, row[6], fencing_token, row[9])

    @staticmethod
    def _history_failure(message: str, cause: Exception | None = None) -> None:
        error = AuthorityError("RECOVERY_REQUIRED", f"Authority committed history is incomplete or inconsistent: {message}")
        if cause is None:
            raise error
        raise error from cause

    @classmethod
    def _verify_history(cls, source: Any, head: Head) -> None:
        """Check that stored transition/event/index rows form the current service history.

        These checks detect missing or independently altered rows. They are not an
        administrator-resistant audit log: an administrator able to rewrite all
        related rows can recompute ordinary hashes and may produce a consistent
        replacement history. A production deployment needs an independent Owner
        checkpoint over the history itself or an independently administered log.
        """
        try:
            record_rows = cls._read_sql(
                source,
                "SELECT TransitionId, Status, RequestJSONB64, RequestSHA256, ActorPrincipal, "
                "OperationPurpose, ApprovalReference, AuthorizedRole, AuthorizationClass, "
                "AuthorizationEpoch, RevocationSHA256, ExpectedSequence, ExpectedStateDigest, "
                "ProposedStateDigest, ProposedIndexRevision, ProposedIndexSHA256, CandidateIndexB64, "
                "FencingToken, ResolutionCode, ResultSequence, ResultStateDigest "
                "FROM TransitionRecords ORDER BY TransitionId",
            )
            event_rows = cls._read_sql(
                source,
                "SELECT TransitionId, EventNumber, EventType, EventJSONB64, EventSHA256, OccurredAt "
                "FROM TransitionEvents ORDER BY TransitionId, EventNumber",
            )
            index_rows = cls._read_sql(
                source,
                "SELECT IndexRevision, IndexSHA256, IndexBytesB64, TransitionId "
                "FROM IndexHistory ORDER BY IndexRevision",
            )
            if head.sequence < 0 or head.state.index_revision < 0:
                cls._history_failure("negative Authority sequence or Index revision")
            if head.sequence != head.state.index_revision:
                cls._history_failure("Authority sequence and Index revision do not advance together")

            records: dict[str, dict[str, Any]] = {}
            for row in record_rows:
                (transition_id, status, request_b64, request_sha, actor, purpose,
                 approval_reference, authorized_role, authorization_class,
                 authorization_epoch, revocation_sha, expected_sequence,
                 expected_state_digest, proposed_state_digest, proposed_index_revision,
                 proposed_index_sha, candidate_b64, fencing_token, resolution_code,
                 result_sequence, result_state_digest) = row
                if transition_id in records:
                    cls._history_failure("duplicate Transition ID")
                request_raw = _decode_bytes(request_b64)
                if (not isinstance(request_sha, str) or not c3.SHA256_RE.fullmatch(request_sha)
                        or sha256(request_raw) != request_sha):
                    cls._history_failure(f"Transition {transition_id} request SHA mismatch")
                request_payload = json.loads(request_raw)
                request = OperatorRequest.parse(request_payload)
                if canonical_bytes(request.wire()) != request_raw:
                    cls._history_failure(f"Transition {transition_id} request is not canonical")
                candidate_raw = _decode_bytes(candidate_b64)
                scope = c3.PURPOSE_INDEX_SCOPES.get(purpose)
                if scope is None:
                    cls._history_failure(f"Transition {transition_id} has an unknown purpose")
                proposed = c3.TrustState.from_payload(request.proposed_state)
                if (
                    request.transition_id != transition_id
                    or request.operation_purpose != purpose
                    or request.approval_reference != approval_reference
                    or request.expected_sequence != int(expected_sequence)
                    or request.expected_state_digest != expected_state_digest
                    or request.candidate_index_raw != candidate_raw
                    or c3._digest(proposed.payload()) != proposed_state_digest
                    or proposed.index_revision != int(proposed_index_revision)
                    or proposed.index_sha256 != proposed_index_sha
                    or sha256(candidate_raw) != proposed_index_sha
                    or authorized_role != scope.authorized_role
                    or authorization_class != scope.authorization_class
                    or int(authorization_epoch) < 1
                    or not isinstance(revocation_sha, str)
                    or not c3.SHA256_RE.fullmatch(revocation_sha)
                    or not isinstance(expected_state_digest, str)
                    or not c3.SHA256_RE.fullmatch(expected_state_digest)
                    or not isinstance(proposed_state_digest, str)
                    or not c3.SHA256_RE.fullmatch(proposed_state_digest)
                ):
                    cls._history_failure(f"Transition {transition_id} record/request bindings disagree")
                records[transition_id] = {
                    "status": status, "actor": actor, "purpose": purpose,
                    "approval_reference": approval_reference,
                    "expected_sequence": int(expected_sequence),
                    "expected_state_digest": expected_state_digest,
                    "proposed_state_digest": proposed_state_digest,
                    "proposed_index_revision": int(proposed_index_revision),
                    "proposed_index_sha": proposed_index_sha,
                    "candidate_raw": candidate_raw,
                    "proposed_state": proposed,
                    "authorization_epoch": int(authorization_epoch),
                    "revocation_sha": revocation_sha,
                    "fencing_token": int(fencing_token),
                    "resolution_code": resolution_code,
                    "result_sequence": None if result_sequence is None else int(result_sequence),
                    "result_state_digest": result_state_digest,
                }

                if int(fencing_token) < 1:
                    cls._history_failure("Transition fencing token is invalid")

            events: dict[str, list[dict[str, Any]]] = {}
            for row in event_rows:
                transition_id, number, event_type, event_b64, event_sha, occurred_at = row
                raw = _decode_bytes(event_b64)
                payload = json.loads(raw)
                if (not isinstance(event_sha, str) or not c3.SHA256_RE.fullmatch(event_sha)
                        or sha256(raw) != event_sha or canonical_bytes(payload) != raw):
                    cls._history_failure(f"Transition {transition_id} event bytes/hash are invalid")
                events.setdefault(transition_id, []).append({
                    "number": int(number), "type": event_type, "payload": payload,
                    "occurred_at": occurred_at,
                })
            if set(events) - set(records):
                cls._history_failure("event row has no Transition record")

            index_history: dict[int, dict[str, Any]] = {}
            for revision, index_sha, index_b64, transition_id in index_rows:
                revision = int(revision)
                if revision in index_history:
                    cls._history_failure("duplicate IndexHistory revision")
                raw = _decode_bytes(index_b64)
                if (revision < 0 or not isinstance(index_sha, str)
                        or not c3.SHA256_RE.fullmatch(index_sha) or sha256(raw) != index_sha):
                    cls._history_failure(f"IndexHistory revision {revision} bytes/hash are invalid")
                index_history[revision] = {
                    "sha": index_sha, "raw": raw, "transition_id": transition_id,
                }
            expected_revisions = set(range(head.state.index_revision + 1))
            if set(index_history) != expected_revisions:
                cls._history_failure("IndexHistory has a missing, extra, or reordered revision")
            genesis = index_history.get(0)
            if genesis is None or genesis["transition_id"] != "genesis-only":
                cls._history_failure("IndexHistory genesis row is missing or misbound")

            committed_by_revision: dict[int, str] = {}
            prepared_ids: list[str] = []
            for transition_id, record in records.items():
                state = record["status"]
                rows = events.get(transition_id, [])
                rows.sort(key=lambda item: item["number"])
                if state == "committed":
                    expected_numbers = [0, 1]
                    if (record["result_sequence"] != record["expected_sequence"] + 1
                            or record["result_sequence"] != record["proposed_index_revision"]
                            or record["result_state_digest"] != record["proposed_state_digest"]
                            or record["proposed_index_revision"] in committed_by_revision):
                        cls._history_failure(f"committed Transition {transition_id} result is inconsistent")
                    committed_by_revision[record["proposed_index_revision"]] = transition_id
                    expected_events = [
                        ("prepared", {
                            "transition_id": transition_id, "purpose": record["purpose"],
                            "actor": record["actor"],
                            "authorization_reference": record["approval_reference"],
                            "expected_sequence": record["expected_sequence"],
                            "fencing_token": record["fencing_token"],
                        }),
                        ("committed", {
                            "transition_id": transition_id,
                            "sequence": record["result_sequence"],
                            "state_digest": record["result_state_digest"],
                            "index_revision": record["proposed_index_revision"],
                            "index_sha256": record["proposed_index_sha"],
                            "fencing_token": record["fencing_token"],
                        }),
                    ]
                elif state == "aborted":
                    expected_numbers = [0, 1]
                    if (record["result_sequence"] is not None
                            or record["result_state_digest"] is not None
                            or not isinstance(record["resolution_code"], str)
                            or not re.fullmatch(r"[A-Z0-9_]{1,64}", record["resolution_code"])):
                        cls._history_failure(f"aborted Transition {transition_id} result is inconsistent")
                    expected_events = [
                        ("prepared", {
                            "transition_id": transition_id, "purpose": record["purpose"],
                            "actor": record["actor"],
                            "authorization_reference": record["approval_reference"],
                            "expected_sequence": record["expected_sequence"],
                            "fencing_token": record["fencing_token"],
                        }),
                        ("aborted", {
                            "transition_id": transition_id,
                            "reason_code": record["resolution_code"],
                            "actor": record["actor"],
                        }),
                    ]
                elif state == "prepared":
                    expected_numbers = [0]
                    prepared_ids.append(transition_id)
                    if (record["result_sequence"] is not None
                            or record["result_state_digest"] is not None
                            or record["resolution_code"] is not None
                            or record["expected_sequence"] != head.sequence
                            or record["proposed_index_revision"] != head.state.index_revision + 1
                            or record["fencing_token"] != head.fencing_token
                            or head.pending_transition_id != transition_id):
                        cls._history_failure(f"prepared Transition {transition_id} is not the current reservation")
                    expected_events = [
                        ("prepared", {
                            "transition_id": transition_id, "purpose": record["purpose"],
                            "actor": record["actor"],
                            "authorization_reference": record["approval_reference"],
                            "expected_sequence": record["expected_sequence"],
                            "fencing_token": record["fencing_token"],
                        }),
                    ]
                else:
                    cls._history_failure(f"Transition {transition_id} has unknown status {state!r}")
                if [event["number"] for event in rows] != expected_numbers:
                    cls._history_failure(f"Transition {transition_id} event sequence is missing, duplicated, or reordered")
                if len(rows) != len(expected_events):
                    cls._history_failure(f"Transition {transition_id} has an unexpected event count")
                for actual, (expected_type, expected_payload) in zip(rows, expected_events):
                    if actual["type"] != expected_type or actual["payload"] != expected_payload:
                        cls._history_failure(f"Transition {transition_id} event does not bind to its record")
                if len(rows) == 2 and rows[0]["occurred_at"] > rows[1]["occurred_at"]:
                    cls._history_failure(f"Transition {transition_id} event timestamps are out of order")

            if prepared_ids != ([head.pending_transition_id] if head.pending_transition_id else []):
                cls._history_failure("prepared Transition set does not match AuthorityHead pending ID")
            if set(committed_by_revision) != set(range(1, head.state.index_revision + 1)):
                cls._history_failure("committed Transition set does not cover the Index revision sequence")
            for revision in range(1, head.state.index_revision + 1):
                history = index_history[revision]
                transition_id = committed_by_revision[revision]
                record = records[transition_id]
                if (history["transition_id"] != transition_id
                        or history["sha"] != record["proposed_index_sha"]
                        or history["raw"] != record["candidate_raw"]):
                    cls._history_failure(f"IndexHistory revision {revision} is not bound to its committed Transition")
                previous_history = index_history[revision - 1]
                if revision > 1:
                    previous_record = records[committed_by_revision[revision - 1]]
                    previous_state = previous_record["proposed_state"]
                    if (record["expected_state_digest"] != previous_record["result_state_digest"]
                            or record["authorization_epoch"] != previous_state.policy_epoch
                            or record["revocation_sha"] != previous_state.revocation_state_sha256):
                        cls._history_failure(f"Transition {transition_id} does not bind to the prior committed state/authorization epoch")
                try:
                    c3.validate_index_append(
                        previous_history["raw"], history["raw"],
                        expected_epoch=record["proposed_state"].policy_epoch,
                        expected_controller_id=record["proposed_state"].controller_id,
                        expected_previous_sha256=previous_history["sha"],
                        expected_current_sha256=history["sha"],
                        operation_purpose=record["purpose"],
                        actor_principal=record["actor"],
                        operation_id=transition_id,
                    )
                except c3.LedgerError as exc:
                    cls._history_failure(f"Transition {transition_id} Index delta violates its C3 purpose/Actor contract", exc)
            current = index_history[head.state.index_revision]
            if (current["raw"] != head.index_raw or current["sha"] != head.index_sha256):
                cls._history_failure("current IndexHistory row does not match AuthorityHead")
            if head.sequence > 0:
                latest = records[committed_by_revision[head.sequence]]
                if (latest["result_sequence"] != head.sequence
                        or latest["result_state_digest"] != head.state_digest
                        or latest["proposed_state"].payload() != head.state.payload()):
                    cls._history_failure("latest committed Transition does not match the current AuthorityHead state")
        except AuthorityError as exc:
            if exc.code == "RECOVERY_REQUIRED":
                raise
            cls._history_failure("stored rows could not be validated", exc)
        except Exception as exc:
            cls._history_failure("stored rows could not be validated", exc)

    @classmethod
    def _read_role(cls, transaction: Any, reference: str) -> dict[str, Any] | None:
        rows = cls._read_sql(
            transaction,
            "SELECT Principal, Role, AuthorizationClass, OperationPurpose, Epoch, "
            "ValidFrom, ValidUntil, Revoked, ApproverPrincipal "
            "FROM OwnerRoleRegistry WHERE AuthorizationReference=@ref",
            {"ref": reference}, {"ref": param_types.STRING},
        )
        if len(rows) > 1:
            raise AuthorityError("ROLE_REGISTRY_CORRUPT", "authorization reference is not unique")
        if not rows:
            return None
        row = rows[0]
        return {
            "principal": row[0], "role": row[1], "authorization_class": row[2],
            "operation_purpose": row[3], "epoch": int(row[4]),
            "valid_from": row[5], "valid_until": row[6],
            "revoked": bool(row[7]), "approver": row[8],
        }

    @classmethod
    def _read_transition(cls, transaction: Any, transition_id: str) -> dict[str, Any] | None:
        rows = cls._read_sql(
            transaction,
            "SELECT Status, RequestJSONB64, RequestSHA256, ActorPrincipal, OperationPurpose, "
            "ApprovalReference, ExpectedSequence, ExpectedStateDigest, ProposedStateDigest, "
            "ProposedIndexRevision, ProposedIndexSHA256, CandidateIndexB64, "
            "ReservationExpiresAt, FencingToken, ResolutionCode, ResultSequence, ResultStateDigest "
            "FROM TransitionRecords WHERE TransitionId=@transition_id",
            {"transition_id": transition_id},
            {"transition_id": param_types.STRING},
        )
        if len(rows) > 1:
            raise AuthorityError("TRANSITION_ID_REUSE", "Transition ID is not unique")
        if not rows:
            return None
        row = rows[0]
        return {
            "status": row[0], "request_json": _decode_bytes(row[1]),
            "request_sha256": row[2], "actor": row[3], "purpose": row[4],
            "approval_reference": row[5], "expected_sequence": int(row[6]),
            "expected_state_digest": row[7], "proposed_state_digest": row[8],
            "proposed_index_revision": int(row[9]), "proposed_index_sha256": row[10],
            "candidate_index_raw": _decode_bytes(row[11]), "reservation_expires_at": row[12],
            "fencing_token": int(row[13]), "resolution_code": row[14],
            "result_sequence": row[15], "result_state_digest": row[16],
        }

    def _snapshot(self, head: Head) -> Snapshot:
        return Snapshot(
            head.sequence, head.state_digest, head.state.policy_epoch,
            head.state.index_revision, head.index_sha256, head.fencing_token,
        )

    def _reconcile_checkpoint(self, head: Head) -> None:
        candidate = self._snapshot(head)
        checkpoint = self.__checkpoint.current()
        if candidate.sequence < checkpoint.sequence:
            raise AuthorityError("ROLLBACK_DETECTED", "Spanner head is older than the independent high-water checkpoint")
        if (candidate.fencing_token < checkpoint.fencing_token
                or (candidate.sequence == checkpoint.sequence and (
                    candidate.state_digest != checkpoint.state_digest
                    or candidate.index_revision != checkpoint.index_revision
                    or candidate.index_sha256 != checkpoint.index_sha256
                ))):
            raise AuthorityError("CHECKPOINT_DIVERGENCE", "Spanner head conflicts with the independent checkpoint")
        if (candidate.sequence > checkpoint.sequence
                or candidate.fencing_token > checkpoint.fencing_token):
            raise AuthorityError(
                "RECOVERY_REQUIRED",
                "Spanner is ahead of the separate checkpoint; status must be reconciled without automatic re-authorization",
            )

    def read_current(self) -> Snapshot:
        with self.__database.snapshot(multi_use=True) as snapshot:
            head = self._read_head(snapshot)
            self._reconcile_checkpoint(head)
            self._verify_history(snapshot, head)
        return self._snapshot(head)

    def _proposal_and_authorization(
        self,
        request: OperatorRequest,
        peer: AuthenticatedPeer,
        head: Head,
        role: dict[str, Any] | None,
        now: datetime,
    ) -> tuple[Any, Any]:
        if role is None:
            raise c3.LedgerError("AUTHORIZATION_REJECTED", "Owner Role Registry has no matching grant")
        scope = c3.PURPOSE_INDEX_SCOPES.get(request.operation_purpose)
        if scope is None:
            raise c3.LedgerError("PURPOSE_INDEX_SCOPE_UNDEFINED", "purpose has no approved Index mutation contract")
        if (role["principal"] != peer.principal
                or role["role"] != scope.authorized_role
                or role["authorization_class"] != scope.authorization_class
                or role["operation_purpose"] != request.operation_purpose
                or role["epoch"] != head.state.policy_epoch
                or role["revoked"]
                or role["valid_from"] > now
                or now >= role["valid_until"]
                or not role["approver"]
                or role["approver"] == peer.principal
                or request.approval_reference in head.state.revoked_role_authorization_references):
            raise c3.LedgerError("AUTHORIZATION_REJECTED", "current Owner role grant is expired, revoked, or mismatched")
        proposal = c3.TransitionProposal(
            transition_id=request.transition_id,
            expected_sequence=request.expected_sequence,
            expected_state_digest=request.expected_state_digest,
            previous_index_raw=head.index_raw,
            candidate_index_raw=request.candidate_index_raw,
            proposed_state=c3.TrustState.from_payload(request.proposed_state),
            operation_purpose=request.operation_purpose,
            actor_principal=peer.principal,
            owner_approval_reference=request.approval_reference,
        )
        authorization = c3.VerifiedTransitionAuthorization(
            authority_identity=AUTHORITY_ID,
            transition_id=request.transition_id,
            actor_principal=peer.principal,
            approver_principal=role["approver"],
            operation_purpose=request.operation_purpose,
            approval_reference=request.approval_reference,
            authorization_class=role["authorization_class"],
            proposed_state_digest=c3._digest(proposal.proposed_state.payload()),
            authorized_role=role["role"],
            role_authorization_reference=request.approval_reference,
            authorization_epoch=role["epoch"],
            revocation_state_sha256=head.state.revocation_state_sha256,
            authority_fencing_token=str(head.fencing_token),
            checked_at=now,
            valid_until=role["valid_until"],
        )
        snapshot = c3.WitnessSnapshot(
            authority_identity=AUTHORITY_ID,
            sequence=head.sequence,
            head_state_digest=head.state_digest,
            head_record_sha256=head.state_digest,
            state=head.state,
            checked_at=now,
            valid_until=now + timedelta(seconds=c3.MAX_AUTHORITY_AGE_SECONDS),
            fencing_token=str(head.fencing_token),
            history=(),
            pending_transition_ids=(head.pending_transition_id,) if head.pending_transition_id else (),
        )
        c3.validate_transition_proposal(
            proposal, snapshot, authorization=authorization,
            expected_authority_identity=AUTHORITY_ID, now=now,
        )
        return proposal, authorization

    @staticmethod
    def _event(transaction: Any, transition_id: str, number: int,
               event_type: str, payload: dict[str, Any], now: datetime) -> None:
        raw = canonical_bytes(payload)
        transaction.insert(
            "TransitionEvents",
            columns=("TransitionId", "EventNumber", "EventType", "EventJSONB64", "EventSHA256", "OccurredAt"),
            values=[(transition_id, number, event_type, _encode_bytes(raw), sha256(raw), now)],
        )

    def prepare_transition(self, payload: dict[str, Any], peer: AuthenticatedPeer) -> dict[str, Any]:
        request = OperatorRequest.parse(payload)
        self.read_current()
        def prepare_tx(transaction: Any) -> dict[str, Any]:
            now = self._clock().astimezone(timezone.utc)
            head = self._read_head(transaction)
            self._verify_history(transaction, head)
            existing = self._read_transition(transaction, request.transition_id)
            if existing is not None:
                raise AuthorityError("TRANSITION_ID_REUSE", "Transition ID already exists and is never reusable")
            if head.pending_transition_id:
                raise AuthorityError("CAS_BUSY", "another prepared transition currently holds the Authority head")
            if (head.sequence != request.expected_sequence
                    or head.state_digest != request.expected_state_digest):
                raise AuthorityError("CAS_STALE", "request does not match current committed sequence and head digest")
            role = self._read_role(transaction, request.approval_reference)
            proposal, authorization = self._proposal_and_authorization(request, peer, head, role, now)
            proposed_digest = c3._digest(proposal.proposed_state.payload())
            request_raw = canonical_bytes(request.wire())
            next_fence = head.fencing_token + 1
            reservation_expiry = min(now + self._reservation_ttl, authorization.valid_until)
            if reservation_expiry <= now:
                raise AuthorityError("AUTHORIZATION_EXPIRED", "reservation expires before it can be prepared")
            transaction.insert(
                "TransitionRecords", columns=TRANSITION_COLUMNS,
                values=[(
                    request.transition_id, "prepared", _encode_bytes(request_raw), sha256(request_raw),
                    peer.principal, request.operation_purpose, request.approval_reference,
                    authorization.authorized_role, authorization.authorization_class,
                    authorization.authorization_epoch, authorization.revocation_state_sha256,
                    head.sequence, head.state_digest, proposed_digest,
                    proposal.proposed_state.index_revision, proposal.proposed_state.index_sha256,
                    _encode_bytes(request.candidate_index_raw), reservation_expiry, next_fence,
                    None, None, None,
                )],
            )
            self._event(transaction, request.transition_id, 0, "prepared", {
                "transition_id": request.transition_id, "purpose": request.operation_purpose,
                "actor": peer.principal, "authorization_reference": request.approval_reference,
                "expected_sequence": head.sequence, "fencing_token": next_fence,
            }, now)
            transaction.update(
                "AuthorityHead",
                columns=("HeadId", "FencingToken", "PendingTransitionId"),
                values=[(HEAD_ID, next_fence, request.transition_id)],
            )
            return {
                "transition_id": request.transition_id, "status": "prepared",
                "expected_sequence": head.sequence, "expected_state_digest": head.state_digest,
                "proposed_state_digest": proposed_digest,
                "proposed_index_sha256": proposal.proposed_state.index_sha256,
                "fencing_token": next_fence, "reservation_expires_at": reservation_expiry,
                "actor_principal": peer.principal, "operation_purpose": request.operation_purpose,
            }
        prepared = self.__database.run_in_transaction(prepare_tx)
        try:
            self.__checkpoint.advance(self._snapshot(self._read_head(self.__database)))
        except Exception as exc:
            raise AuthorityError("PREPARE_STATUS_UNKNOWN", "Prepare may be durable but checkpoint acknowledgment is unavailable") from exc
        return prepared

    @staticmethod
    def _abort_in_transaction(transaction: Any, head: Head, transition: dict[str, Any],
                              transition_id: str, code: str, now: datetime) -> None:
        transaction.update(
            "TransitionRecords",
            columns=("TransitionId", "Status", "ResolutionCode"),
            values=[(transition_id, "aborted", code)],
        )
        if head.pending_transition_id == transition_id:
            transaction.update(
                "AuthorityHead",
                columns=("HeadId", "PendingTransitionId"),
                values=[(HEAD_ID, None)],
            )
        SpannerAuthorityService._event(transaction, transition_id, 1, "aborted", {
            "transition_id": transition_id, "reason_code": code,
            "actor": transition["actor"],
        }, now)

    def commit_transition(self, transition_id: str, peer: AuthenticatedPeer) -> Snapshot:
        if not isinstance(transition_id, str) or not TRANSITION_ID_RE.fullmatch(transition_id):
            raise AuthorityError("TRANSITION_ID_INVALID", "Transition ID format is invalid")
        self.read_current()
        if self.faults.abort_commit_before_transaction:
            self.faults.abort_commit_before_transaction = False
            raise AuthorityError(
                "SPANNER_ABORTED",
                "deterministic known-abort injection before a commit transaction was sent",
            )
        def commit_tx(transaction: Any) -> tuple[str, Any]:
            now = self._clock().astimezone(timezone.utc)
            head = self._read_head(transaction)
            self._verify_history(transaction, head)
            transition = self._read_transition(transaction, transition_id)
            if transition is None:
                return ("rejected", "TRANSITION_NOT_FOUND")
            if transition["status"] != "prepared":
                return ("rejected", "TRANSITION_NOT_PREPARED")
            if transition["actor"] != peer.principal:
                self._abort_in_transaction(transaction, head, transition, transition_id,
                                            "ACTOR_IDENTITY_REJECTED", now)
                return ("aborted", "ACTOR_IDENTITY_REJECTED")
            if (transition["reservation_expires_at"] <= now
                    or head.pending_transition_id != transition_id
                    or head.fencing_token != transition["fencing_token"]
                    or head.sequence != transition["expected_sequence"]
                    or head.state_digest != transition["expected_state_digest"]):
                code = "RESERVATION_EXPIRED_OR_STALE"
                self._abort_in_transaction(transaction, head, transition, transition_id, code, now)
                return ("aborted", code)
            request_obj = json.loads(transition["request_json"])
            request = OperatorRequest.parse(request_obj)
            role = self._read_role(transaction, transition["approval_reference"])
            try:
                proposal, _authorization = self._proposal_and_authorization(request, peer, head, role, now)
            except c3.LedgerError as exc:
                self._abort_in_transaction(transaction, head, transition, transition_id, exc.code, now)
                return ("aborted", exc.code)
            if (sha256(transition["request_json"]) != transition["request_sha256"]
                    or request.candidate_index_raw != transition["candidate_index_raw"]
                    or proposal.proposed_state.index_sha256 != transition["proposed_index_sha256"]
                    or c3._digest(proposal.proposed_state.payload()) != transition["proposed_state_digest"]):
                self._abort_in_transaction(transaction, head, transition, transition_id,
                                            "PREPARED_BINDING_MISMATCH", now)
                return ("aborted", "PREPARED_BINDING_MISMATCH")
            next_sequence = head.sequence + 1
            proposed = proposal.proposed_state
            transaction.update(
                "AuthorityHead",
                columns=(
                    "HeadId", "Sequence", "StateJSONB64", "StateDigest", "PolicyEpoch",
                    "IndexRevision", "IndexSHA256", "IndexBytesB64", "RevocationStateSHA256",
                    "FencingToken", "PendingTransitionId",
                ),
                values=[(
                    HEAD_ID, next_sequence, _encode_bytes(canonical_bytes(proposed.payload())),
                    transition["proposed_state_digest"], proposed.policy_epoch,
                    proposed.index_revision, proposed.index_sha256,
                    _encode_bytes(request.candidate_index_raw), proposed.revocation_state_sha256,
                    head.fencing_token, None,
                )],
            )
            transaction.insert(
                "IndexHistory",
                columns=("IndexRevision", "IndexSHA256", "IndexBytesB64", "TransitionId"),
                values=[(proposed.index_revision, proposed.index_sha256,
                         _encode_bytes(request.candidate_index_raw), transition_id)],
            )
            transaction.update(
                "TransitionRecords",
                columns=("TransitionId", "Status", "ResultSequence", "ResultStateDigest"),
                values=[(transition_id, "committed", next_sequence,
                         transition["proposed_state_digest"])],
            )
            self._event(transaction, transition_id, 1, "committed", {
                "transition_id": transition_id, "sequence": next_sequence,
                "state_digest": transition["proposed_state_digest"],
                "index_revision": proposed.index_revision,
                "index_sha256": proposed.index_sha256,
                "fencing_token": head.fencing_token,
            }, now)
            return ("committed", None)
        outcome = self.__database.run_in_transaction(commit_tx)
        if outcome[0] == "aborted":
            raise AuthorityError(outcome[1], "Commit reauthorization failed and the prepared transition was durably aborted")
        if outcome[0] != "committed":
            raise AuthorityError(outcome[1], "transition was not committed")
        if self.faults.hide_checkpoint_after_commit:
            self.faults.hide_checkpoint_after_commit = False
            self.__checkpoint.available = False
        try:
            head = self._read_head(self.__database)
            self.__checkpoint.advance(self._snapshot(head))
        except Exception as exc:
            raise CommitOutcomeUnknown("Spanner committed or may have committed, but the external checkpoint is not confirmed") from exc
        if self.faults.lose_commit_ack:
            self.faults.lose_commit_ack = False
            raise CommitOutcomeUnknown("injected response loss after a confirmed commit")
        return self._snapshot(head)

    def abort_transition(self, transition_id: str, peer: AuthenticatedPeer, reason_code: str) -> None:
        if not re.fullmatch(r"[A-Z0-9_]{1,64}", reason_code):
            raise AuthorityError("REASON_CODE_INVALID", "abort reason is not a closed code")
        def abort_tx(transaction: Any) -> None:
            now = self._clock().astimezone(timezone.utc)
            transition = self._read_transition(transaction, transition_id)
            if transition is None or transition["status"] != "prepared":
                raise AuthorityError("TRANSITION_NOT_PREPARED", "only a prepared transition can be aborted")
            head = self._read_head(transaction)
            self._verify_history(transaction, head)
            if peer.principal != transition["actor"]:
                raise AuthorityError("ACTOR_IDENTITY_REJECTED", "only the bound actor can cancel its reservation")
            self._abort_in_transaction(transaction, head, transition, transition_id, reason_code, now)
        self.__database.run_in_transaction(abort_tx)

    def read_transition(self, transition_id: str, peer: AuthenticatedPeer) -> dict[str, Any] | None:
        if not self.__checkpoint.available:
            raise AuthorityError("CHECKPOINT_UNAVAILABLE", "status reads are blocked while checkpoint is unavailable")
        row = self._read_transition(self.__database, transition_id)
        if row is not None and row["actor"] != peer.principal:
            raise AuthorityError("ACTOR_IDENTITY_REJECTED", "transition status is scoped to its authenticated actor")
        return row

    def test_only_restore_head(self, old: Head) -> None:
        """Unsafe administrator helper used solely to model an old DB snapshot."""
        self.__database.run_in_transaction(lambda transaction: transaction.update(
            "AuthorityHead",
            columns=HEAD_COLUMNS,
            values=[(
                HEAD_ID, old.sequence, _encode_bytes(canonical_bytes(old.state.payload())),
                old.state_digest, old.state.policy_epoch, old.state.index_revision,
                old.index_sha256, _encode_bytes(old.index_raw), old.state.revocation_state_sha256,
                old.fencing_token, old.pending_transition_id,
            )],
        ))


class OperatorClient:
    """Constrained RPC-shaped client; intentionally has no Spanner handle."""

    def __init__(self, service: SpannerAuthorityService,
                 authenticator: SyntheticPeerAuthenticator, token: str):
        self.__service = service
        self.__authenticator = authenticator
        self.__token = token

    def prepare_transition(self, payload: dict[str, Any]) -> dict[str, Any]:
        peer = self.__authenticator.authenticate(self.__token)
        return self.__service.prepare_transition(payload, peer)

    def commit_transition(self, transition_id: str) -> Snapshot:
        peer = self.__authenticator.authenticate(self.__token)
        return self.__service.commit_transition(transition_id, peer)

    def abort_transition(self, transition_id: str, reason_code: str) -> None:
        peer = self.__authenticator.authenticate(self.__token)
        self.__service.abort_transition(transition_id, peer, reason_code)

    def transition_status(self, transition_id: str) -> dict[str, Any] | None:
        peer = self.__authenticator.authenticate(self.__token)
        return self.__service.read_transition(transition_id, peer)


def create_authority_database(
    database: spanner.database.Database,
    state: c3.TrustState,
    index_raw: bytes,
) -> InMemoryExternalCheckpoint:
    require_local_emulator()
    if sha256(index_raw) != state.index_sha256:
        raise AuthorityError("GENESIS_INDEX_SHA_MISMATCH", "synthetic Genesis Index SHA is invalid")
    if not database.ddl_statements:
        raise AuthorityError("RESEARCH_SCHEMA_REQUIRED", "Database must be created with the research-only schema")
    database.create().result()
    def seed(transaction: Any) -> None:
        transaction.insert(
            "AuthorityHead", columns=HEAD_COLUMNS,
            values=[(
                HEAD_ID, 0, _encode_bytes(canonical_bytes(state.payload())), c3._digest(state.payload()),
                state.policy_epoch, state.index_revision, state.index_sha256,
                _encode_bytes(index_raw), state.revocation_state_sha256, 0, None,
            )],
        )
        transaction.insert(
            "IndexHistory",
            columns=("IndexRevision", "IndexSHA256", "IndexBytesB64", "TransitionId"),
            values=[(state.index_revision, state.index_sha256, _encode_bytes(index_raw), "genesis-only")],
        )
    database.run_in_transaction(seed)
    return InMemoryExternalCheckpoint(Snapshot(
        0, c3._digest(state.payload()), state.policy_epoch,
        state.index_revision, state.index_sha256, 0,
    ))


def schema_ddl() -> list[str]:
    ddl_path = Path(__file__).with_name("schema.sql")
    return [statement.strip() for statement in ddl_path.read_text().split(";") if statement.strip()]


def install_synthetic_role(
    database: spanner.database.Database,
    *,
    reference: str,
    principal: str,
    role: str,
    authorization_class: str,
    operation_purpose: str,
    epoch: int,
    valid_from: datetime,
    valid_until: datetime,
    approver: str,
    revoked: bool = False,
) -> None:
    """Test-only Owner provisioning. This is not an Operator endpoint."""
    require_local_emulator()
    database.run_in_transaction(lambda transaction: transaction.insert(
        "OwnerRoleRegistry", columns=ROLE_COLUMNS,
        values=[(
            reference, principal, role, authorization_class, operation_purpose,
            epoch, valid_from, valid_until, revoked, approver,
        )],
    ))
