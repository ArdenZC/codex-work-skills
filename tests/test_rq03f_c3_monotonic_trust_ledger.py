from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lifecycle_digest import canonical_json_bytes
from rq03f_monotonic_trust_ledger import (
    AUTHORITY_RESPONSE_SCHEMA,
    LEDGER_RECORD_SCHEMA,
    LEDGER_SCHEMA,
    TRANSITION_SCHEMA,
    GateResult,
    DirectoryProjectionStore,
    LedgerError,
    MonotonicAntiRollbackGate,
    MonotonicTransitionCoordinator,
    PreparedTransition,
    TransitionProposal,
    TransitionStatus,
    TrustState,
    VerifiedTransitionAuthorization,
    WitnessSnapshot,
    build_ledger_record,
    encode_ledger,
    revocation_state,
    validate_gate_result,
    validate_index_append,
    validate_state_successor,
    validate_transition_proposal,
    verify_ledger,
    verify_witness_snapshot,
)


AUTHORITY = "synthetic-c3-witness-test-only"


def sha(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def encode_json(value: dict) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def base_index(*, epoch: int = 1, controller: str = "controller-a") -> dict:
    return {
        "index_version": "1.1",
        "controller_id": controller,
        "policy_epoch": epoch,
        "receipts": [],
        "authors": [],
        "adjudications": [],
        "qualification_runs": [],
        "qualification_corpus_intakes": [],
    }


def initial_state(index_raw: bytes | None = None, *, epoch: int = 1,
                  profile_sha: str | None = None, generation: str = "generation-a",
                  revoked_ids: tuple[str, ...] = (),
                  revoked_roles: tuple[str, ...] = ()) -> TrustState:
    raw = index_raw if index_raw is not None else encode_json(base_index(epoch=epoch))
    return TrustState(
        policy_identity="policy-a",
        policy_epoch=epoch,
        profile_sha256=profile_sha or sha("profile-a"),
        build_inventory_sha256=sha("build-a"),
        controller_id="controller-a",
        generation_id=generation,
        index_sha256=sha(raw),
        index_revision=0,
        revocation_state_sha256=sha("revocation-state-a"),
        revoked_authority_ids=revoked_ids,
        revoked_role_authorization_references=revoked_roles,
    )


def genesis_record(state: TrustState) -> dict:
    return build_ledger_record(
        authority_identity=AUTHORITY,
        sequence=0,
        previous_state_digest=None,
        previous_record_sha256=None,
        state=state,
        transition_id="genesis-0001",
        operation_purpose="read_only_preflight",
        owner_approval_reference="synthetic-fixture-not-owner-approval",
        audit_timestamp=datetime(2026, 10, 11, tzinfo=timezone.utc),
    )


def append_intake(old_raw: bytes, *, intake_id: str = "intake-0001",
                  operation_id: str = "operation-0001",
                  epoch: int = 1, controller: str = "controller-a") -> bytes:
    index = json.loads(old_raw)
    index["policy_epoch"] = epoch
    index["controller_id"] = controller
    index["qualification_corpus_intakes"].append({
        "intake_id": intake_id,
        "operation_id": operation_id,
        "operator_principal": "synthetic-operator",
        "subject_inventory_key": "frozen-corpus",
        "subject_sha256": sha("corpus"),
    })
    return encode_json(index)


def append_state(previous: TrustState, index_raw: bytes, **changes) -> TrustState:
    return replace(previous, index_sha256=sha(index_raw),
                   index_revision=previous.index_revision + 1, **changes)


def state_digest(state: TrustState) -> str:
    return sha(canonical_json_bytes(state.payload()))


class MemoryProjection:
    def __init__(self, index_raw: bytes, records: list[dict]):
        self.index = index_raw
        self.ledger = encode_ledger(AUTHORITY, records)
        self.staged: dict[str, bytes] = {}
        self.recovery: list[tuple[str, str]] = []

    def read_index(self) -> bytes:
        return self.index

    def read_ledger(self) -> bytes:
        return self.ledger

    def stage_index(self, transition_id: str, raw: bytes) -> None:
        if transition_id in self.staged:
            raise LedgerError("STAGE_COLLISION", "staged transition already exists")
        self.staged[transition_id] = raw

    def staged_index(self, transition_id: str) -> bytes | None:
        return self.staged.get(transition_id)

    def install_staged_index(self, transition_id: str) -> None:
        raw = self.staged.get(transition_id)
        if raw is None:
            raise LedgerError("STAGE_MISSING", "staged Index does not exist")
        self.index = raw

    def install_ledger(self, raw: bytes) -> None:
        self.ledger = raw

    def mark_recovery_required(self, transition_id: str, code: str) -> None:
        self.recovery.append((transition_id, code))

    def clear_recovery_required(self, transition_id: str) -> None:
        self.recovery = [row for row in self.recovery if row[0] != transition_id]

    def recovery_required(self) -> bool:
        return bool(self.recovery)


class MemoryWitness:
    """In-process synthetic authority for deterministic protocol tests only."""

    def __init__(self, state: TrustState, *, approved_references: set[str] | None = None,
                 owner_policy_transition_refs: set[str] | None = None):
        self.records = [genesis_record(state)]
        self.pending: dict[str, tuple[TransitionProposal, PreparedTransition]] = {}
        self.statuses: dict[str, TransitionStatus] = {}
        self.approved_references = approved_references or {"role-approval-1", "owner-approval-1"}
        self.owner_policy_transition_refs = owner_policy_transition_refs or {"owner-approval-1"}
        self.unavailable = False
        self.lose_next_ack = False
        self.lock = threading.RLock()

    @property
    def state(self) -> TrustState:
        return TrustState.from_payload(self.records[-1]["state"])

    def read_current(self) -> WitnessSnapshot:
        if self.unavailable:
            raise OSError("synthetic witness unavailable")
        with self.lock:
            record = self.records[-1]
            now = datetime.now(timezone.utc)
            return WitnessSnapshot(
                authority_identity=AUTHORITY,
                sequence=record["sequence"],
                head_state_digest=record["current_committed_state_digest"],
                head_record_sha256=sha(canonical_json_bytes(record)),
                state=self.state,
                checked_at=now,
                valid_until=now + timedelta(seconds=10),
                fencing_token=f"synthetic-fence-{record['sequence']}",
                history=tuple(deepcopy(self.records)),
                pending_transition_ids=tuple(sorted(self.pending)),
            )

    def read_transition(self, transition_id: str) -> TransitionStatus | None:
        with self.lock:
            pending = self.pending.get(transition_id)
            if pending:
                proposal, prepared = pending
                return TransitionStatus(
                    AUTHORITY, transition_id, "prepared", prepared.expected_sequence,
                    prepared.expected_state_digest, prepared.proposed_state_digest,
                    prepared.proposed_index_sha256, prepared,
                )
            if transition_id in self.statuses:
                return self.statuses[transition_id]
            return None

    def verify_transition_authorization(self, proposal: TransitionProposal) -> VerifiedTransitionAuthorization:
        if proposal.owner_approval_reference not in self.approved_references:
            raise LedgerError("AUTHORIZATION_REJECTED", "synthetic witness rejected approval reference")
        auth_class = ("owner_policy_transition"
                      if proposal.owner_approval_reference in self.owner_policy_transition_refs
                      else "operator_role_operation")
        return VerifiedTransitionAuthorization(
            authority_identity=AUTHORITY,
            transition_id=proposal.transition_id,
            actor_principal=proposal.actor_principal,
            approver_principal="synthetic-independent-approver",
            operation_purpose=proposal.operation_purpose,
            approval_reference=proposal.owner_approval_reference,
            authorization_class=auth_class,
            proposed_state_digest=state_digest(proposal.proposed_state),
        )

    def prepare_transition(self, proposal: TransitionProposal) -> PreparedTransition:
        with self.lock:
            if self.pending:
                raise LedgerError("CAS_BUSY", "synthetic witness serializes outstanding transition")
            if proposal.transition_id in self.pending or proposal.transition_id in self.statuses:
                raise LedgerError("TRANSITION_ID_REUSE", "synthetic witness rejects duplicate transition ID")
            current = self.records[-1]
            if (proposal.expected_sequence != current["sequence"]
                    or proposal.expected_state_digest != current["current_committed_state_digest"]):
                raise LedgerError("CAS_STALE", "synthetic witness rejects stale CAS token")
            if proposal.owner_approval_reference not in self.approved_references:
                raise LedgerError("AUTHORIZATION_REJECTED", "synthetic witness rejects unapproved transition")
            snapshot = self.read_current()
            authorization = self.verify_transition_authorization(proposal)
            validate_transition_proposal(
                proposal, snapshot, authorization=authorization,
                expected_authority_identity=AUTHORITY,
            )
            prepared = PreparedTransition(
                authority_identity=AUTHORITY,
                transition_id=proposal.transition_id,
                status="prepared",
                expected_sequence=proposal.expected_sequence,
                expected_state_digest=proposal.expected_state_digest,
                proposed_state_digest=state_digest(proposal.proposed_state),
                proposed_index_sha256=proposal.proposed_state.index_sha256,
                fencing_token=f"synthetic-fence-{current['sequence']}-{proposal.transition_id}",
                approval_reference=proposal.owner_approval_reference,
            )
            self.pending[proposal.transition_id] = (proposal, prepared)
            return prepared

    def commit_transition(self, prepared: PreparedTransition) -> WitnessSnapshot:
        with self.lock:
            pending = self.pending.get(prepared.transition_id)
            if pending is None or pending[1] != prepared:
                raise LedgerError("FENCING_TOKEN_STALE", "synthetic witness rejects stale fencing token")
            proposal, _ = pending
            previous = self.records[-1]
            if (prepared.expected_sequence != previous["sequence"]
                    or prepared.expected_state_digest != previous["current_committed_state_digest"]):
                raise LedgerError("CAS_STALE", "synthetic witness rejects stale commit")
            record = build_ledger_record(
                authority_identity=AUTHORITY,
                sequence=previous["sequence"] + 1,
                previous_state_digest=previous["current_committed_state_digest"],
                previous_record_sha256=sha(canonical_json_bytes(previous)),
                state=proposal.proposed_state,
                transition_id=proposal.transition_id,
                operation_purpose=proposal.operation_purpose,
                owner_approval_reference=proposal.owner_approval_reference,
                audit_timestamp=datetime.now(timezone.utc),
            )
            self.records.append(record)
            del self.pending[proposal.transition_id]
            self.statuses[proposal.transition_id] = TransitionStatus(
                AUTHORITY, proposal.transition_id, "committed", prepared.expected_sequence,
                prepared.expected_state_digest, prepared.proposed_state_digest,
                prepared.proposed_index_sha256, None,
            )
            snapshot = self.read_current()
            if self.lose_next_ack:
                self.lose_next_ack = False
                raise TimeoutError("synthetic commit ACK lost after linearization")
            return snapshot

    def abort_transition(self, prepared: PreparedTransition, *, reason_code: str) -> None:
        with self.lock:
            pending = self.pending.get(prepared.transition_id)
            if pending is None:
                raise LedgerError("ABORT_STATUS_UNKNOWN", "synthetic witness has no prepared transition")
            if pending[1] != prepared or pending[1].fencing_token != prepared.fencing_token:
                raise LedgerError("FENCING_TOKEN_STALE", "synthetic witness rejects stale abort token")
            del self.pending[prepared.transition_id]
            self.statuses[prepared.transition_id] = TransitionStatus(
                AUTHORITY, prepared.transition_id, "aborted", prepared.expected_sequence,
                prepared.expected_state_digest, prepared.proposed_state_digest,
                prepared.proposed_index_sha256, None,
            )


class LedgerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = encode_json(base_index())
        self.state = initial_state(self.index)
        self.record = genesis_record(self.state)
        self.witness = MemoryWitness(self.state)
        self.store = MemoryProjection(self.index, [self.record])

    def request(self, state: TrustState | None = None, *, purpose: str = "qualification_review") -> dict:
        state = state or self.state
        return {
            "policy_identity": state.policy_identity,
            "policy_epoch": state.policy_epoch,
            "profile_sha256": state.profile_sha256,
            "build_inventory_sha256": state.build_inventory_sha256,
            "controller_id": state.controller_id,
            "generation_id": state.generation_id,
            "index_sha256": state.index_sha256,
            "revocation_state_sha256": state.revocation_state_sha256,
            "operation_purpose": purpose,
        }

    def gate(self, *, witness=None, store=None) -> MonotonicAntiRollbackGate:
        witness = witness or self.witness
        store = store or self.store
        return MonotonicAntiRollbackGate(
            authority=witness,
            expected_authority_identity=AUTHORITY,
            ledger_reader=store.read_ledger,
            index_reader=store.read_index,
            recovery_reader=store.recovery_required,
        )

    def proposal(self, *, transition_id: str = "tx-0001", old_raw: bytes | None = None,
                 intake_id: str = "intake-0001", operation_id: str = "operation-0001",
                 approval_ref: str = "role-approval-1") -> TransitionProposal:
        old_raw = old_raw or self.store.read_index()
        candidate = append_intake(old_raw, intake_id=intake_id, operation_id=operation_id)
        state = append_state(self.witness.state, candidate)
        snapshot = self.witness.read_current()
        return TransitionProposal(
            transition_id=transition_id,
            expected_sequence=snapshot.sequence,
            expected_state_digest=snapshot.head_state_digest,
            previous_index_raw=old_raw,
            candidate_index_raw=candidate,
            proposed_state=state,
            operation_purpose="qualification_corpus_intake",
            actor_principal="synthetic-operator",
            owner_approval_reference=approval_ref,
        )

    def coordinator(self, *, witness=None, store=None) -> MonotonicTransitionCoordinator:
        return MonotonicTransitionCoordinator(
            authority=witness or self.witness,
            authority_identity=AUTHORITY,
            store=store or self.store,
        )

    def test_all_three_versioned_schemas_accept_closed_records(self):
        from lifecycle_digest import schema_errors
        self.assertEqual(schema_errors(json.loads(encode_ledger(AUTHORITY, [self.record])), LEDGER_SCHEMA), [])
        self.assertEqual(schema_errors(self.record, LEDGER_RECORD_SCHEMA), [])
        response = self.witness.read_current()
        self.assertEqual(schema_errors({
            "authority_response_version": "rq03f-high-water-authority-response-1.0",
            "authority_identity": response.authority_identity,
            "sequence": response.sequence,
            "head_state_digest": response.head_state_digest,
            "head_record_sha256": response.head_record_sha256,
            "state": response.state.payload(),
            "checked_at": response.checked_at.isoformat().replace("+00:00", "Z"),
            "valid_until": response.valid_until.isoformat().replace("+00:00", "Z"),
            "fencing_token": response.fencing_token,
            "pending_transition_ids": [],
        }, AUTHORITY_RESPONSE_SCHEMA), [])

    def test_unknown_ledger_fields_fail_closed(self):
        doc = json.loads(encode_ledger(AUTHORITY, [self.record]))
        doc["authority_status"] = "trusted"
        with self.assertRaises(LedgerError):
            verify_ledger(encode_json(doc), expected_authority_identity=AUTHORITY,
                          expected_head_state_digest=self.record["current_committed_state_digest"],
                          expected_head_record_sha256=sha(canonical_json_bytes(self.record)),
                          expected_sequence=0)

    def test_duplicate_json_keys_fail_closed(self):
        raw = b'{"ledger_version":"x","ledger_version":"y","authority_identity":"a","records":[]}'
        with self.assertRaisesRegex(LedgerError, "duplicate"):
            verify_ledger(raw, expected_authority_identity=AUTHORITY,
                          expected_head_state_digest=sha("state"),
                          expected_head_record_sha256=sha("record"), expected_sequence=0)

    def test_genesis_has_no_previous_state_or_record_digest(self):
        self.assertIsNone(self.record["previous_committed_state_digest"])
        self.assertIsNone(self.record["previous_record_sha256"])

    def test_gate_returns_structured_current_state_and_revision(self):
        gate = self.gate()
        result = gate.check_current_state(**self.request())
        checked = validate_gate_result(result, request=gate_request(self.request()),
                                       expected_authority_identity=AUTHORITY)
        self.assertEqual(checked.decision, "verified")
        self.assertEqual(checked.verified_index_revision, 0)
        self.assertEqual(checked.verified_index_sha256, sha(self.index))
        self.assertEqual(checked.verified_profile_sha256, self.state.profile_sha256)
        self.assertTrue(checked.fencing_token)
        self.assertTrue(checked.invalidated_by)

    def test_gate_rejects_each_mismatched_current_state_binding(self):
        fields = {
            "policy_identity": "other-policy", "policy_epoch": 2,
            "profile_sha256": sha("other-profile"), "build_inventory_sha256": sha("other-build"),
            "controller_id": "other-controller", "generation_id": "other-generation",
            "index_sha256": sha("other-index"), "revocation_state_sha256": sha("other-revocation"),
        }
        for name, value in fields.items():
            request = self.request()
            request[name] = value
            with self.subTest(field=name):
                result = self.gate().check_current_state(**request)
                self.assertNotEqual(result.decision, "verified")
                with self.assertRaises(LedgerError):
                    validate_gate_result(result, request=gate_request(request),
                                          expected_authority_identity=AUTHORITY)

    def test_missing_legacy_gate_bindings_are_rejected(self):
        legacy = {"policy_identity": "policy-a", "policy_epoch": 1,
                  "index_sha256": sha(self.index), "operation_purpose": "production_authoring"}
        result = self.gate().check_current_state(**legacy)
        self.assertEqual(result.error_code, "GATE_REQUEST_INCOMPLETE")
        self.assertEqual(result.decision, "blocked")

    def test_candidate_json_and_boolean_cannot_mimic_gate_result(self):
        request = gate_request(self.request())
        for result in (True, {"decision": "verified", "authority_source_identity": AUTHORITY},
                       GateResult.__new__(GateResult)):
            with self.subTest(result_type=type(result).__name__), self.assertRaises(LedgerError):
                validate_gate_result(result, request=request,
                                      expected_authority_identity=AUTHORITY)

    def test_gate_rejects_authority_identity_mismatch(self):
        gate = MonotonicAntiRollbackGate(authority=self.witness,
                                         expected_authority_identity="other-witness",
                                         ledger_reader=self.store.read_ledger,
                                         index_reader=self.store.read_index,
                                         recovery_reader=self.store.recovery_required)
        result = gate.check_current_state(**self.request())
        self.assertEqual(result.error_code, "AUTHORITY_IDENTITY_MISMATCH")

    def test_gate_rejects_ledger_rollback_after_witness_advances(self):
        old_ledger = self.store.read_ledger()
        proposal = self.proposal()
        self.coordinator().commit(proposal)
        self.store.ledger = old_ledger
        result = self.gate().check_current_state(**self.request(self.witness.state))
        self.assertEqual(result.decision, "recovery_required")
        self.assertIn(result.error_code, {"LEDGER_SEQUENCE_GAP", "WITNESS_HEAD_MISMATCH"})

    def test_gate_rejects_local_history_altered_without_witness_change(self):
        doc = json.loads(self.store.read_ledger())
        doc["records"][0]["owner_approval_reference"] = "candidate-forged"
        self.store.ledger = encode_json(doc)
        result = self.gate().check_current_state(**self.request())
        self.assertNotEqual(result.decision, "verified")

    def test_gate_rejects_reordered_or_deleted_committed_history(self):
        proposal = self.proposal()
        self.coordinator().commit(proposal)
        doc = json.loads(self.store.read_ledger())
        doc["records"].reverse()
        self.store.ledger = encode_json(doc)
        result = self.gate().check_current_state(**self.request(self.witness.state))
        self.assertNotEqual(result.decision, "verified")

    def test_gate_fails_closed_when_authority_unavailable(self):
        self.witness.unavailable = True
        result = self.gate().check_current_state(**self.request())
        self.assertEqual(result.error_code, "AUTHORITY_UNAVAILABLE")
        self.assertNotEqual(result.decision, "verified")

    def test_gate_rechecks_authority_instead_of_reusing_an_old_context(self):
        gate = self.gate()
        self.assertEqual(gate.check_current_state(**self.request()).decision, "verified")
        proposal = self.proposal()
        self.coordinator().commit(proposal)
        stale_request = self.request()
        result = gate.check_current_state(**stale_request)
        self.assertNotEqual(result.decision, "verified")
        self.assertEqual(result.error_code, "CURRENT_STATE_MISMATCH")

    def test_authority_clock_window_is_bounded_and_not_the_monotonic_source(self):
        snapshot = self.witness.read_current()
        expired = replace(snapshot, valid_until=datetime.now(timezone.utc) - timedelta(seconds=1))

        class ExpiredWitness(MemoryWitness):
            def read_current(inner_self):
                return expired

        gate = self.gate(witness=ExpiredWitness(self.state))
        result = gate.check_current_state(**self.request())
        self.assertEqual(result.error_code, "AUTHORITY_RESPONSE_STALE")

    def test_state_transition_rejects_epoch_lowering_and_epoch_skip(self):
        with self.assertRaisesRegex(LedgerError, "positive integer"):
            validate_state_successor(self.state, replace(self.state, policy_epoch=0,
                                                          index_revision=1),
                                     authorization=None, expected_authority_identity=AUTHORITY,
                                     transition_id="tx")
        with self.assertRaisesRegex(LedgerError, "one step"):
            validate_state_successor(self.state, replace(self.state, policy_epoch=3,
                                                          index_revision=1),
                                     authorization=None, expected_authority_identity=AUTHORITY,
                                     transition_id="tx")

    def test_state_transition_rejects_unapproved_profile_or_policy_pin_change(self):
        candidate = replace(self.state, profile_sha256=sha("new-profile"), index_revision=1)
        with self.assertRaisesRegex(LedgerError, "fixed within an epoch"):
            validate_state_successor(self.state, candidate, authorization=None,
                                     expected_authority_identity=AUTHORITY, transition_id="tx")

    def test_epoch_transition_requires_typed_owner_authorization_and_new_generation(self):
        candidate = replace(self.state, policy_epoch=2, profile_sha256=sha("profile-b"),
                            generation_id="generation-b", index_revision=1,
                            revocation_state_sha256=sha("revocation-b"))
        authorization = VerifiedTransitionAuthorization(
            AUTHORITY, "epoch-tx", "operator", "owner", "epoch_transition", "owner-approval-1",
            "operator_role_operation", state_digest(candidate))
        with self.assertRaisesRegex(LedgerError, "Owner approval"):
            validate_state_successor(self.state, candidate, authorization=authorization,
                                     expected_authority_identity=AUTHORITY, transition_id="epoch-tx")
        owner_authorization = replace(authorization, authorization_class="owner_policy_transition")
        validate_state_successor(self.state, candidate, authorization=owner_authorization,
                                 expected_authority_identity=AUTHORITY, transition_id="epoch-tx")
        with self.assertRaisesRegex(LedgerError, "new Generation"):
            validate_state_successor(self.state, replace(candidate, generation_id=self.state.generation_id),
                                     authorization=owner_authorization,
                                     expected_authority_identity=AUTHORITY, transition_id="epoch-tx")

    def test_revoked_authority_and_role_cannot_reappear_after_epoch_change(self):
        previous = initial_state(self.index, revoked_ids=("authority-1",),
                                 revoked_roles=("authorization-1",))
        candidate = replace(previous, policy_epoch=2, profile_sha256=sha("profile-2"),
                            generation_id="generation-b", index_revision=1,
                            revocation_state_sha256=sha("revocation-2"),
                            revoked_authority_ids=(), revoked_role_authorization_references=())
        authorization = VerifiedTransitionAuthorization(
            AUTHORITY, "tx", "operator", "owner", "epoch_transition", "owner-approval-1",
            "owner_policy_transition", state_digest(candidate))
        with self.assertRaisesRegex(LedgerError, "cannot become active"):
            validate_state_successor(previous, candidate, authorization=authorization,
                                     expected_authority_identity=AUTHORITY, transition_id="tx")

    def test_index_prefix_append_is_valid_with_same_epoch(self):
        candidate = append_intake(self.index)
        result = validate_index_append(
            self.index, candidate, expected_epoch=1, expected_controller_id="controller-a",
            expected_previous_sha256=sha(self.index), expected_current_sha256=sha(candidate),
        )
        self.assertEqual(len(result["qualification_corpus_intakes"]), 1)

    def test_index_rewrite_and_old_index_new_profile_mixes_fail(self):
        prior = json.loads(append_intake(self.index, intake_id="intake-original",
                                         operation_id="operation-original"))
        prior_raw = encode_json(prior)
        rewritten = deepcopy(prior)
        rewritten["qualification_corpus_intakes"][0]["operator_principal"] = "rewritten-authority"
        rewritten["qualification_corpus_intakes"].append({
            "intake_id": "intake-new", "operation_id": "operation-new",
            "operator_principal": "operator", "subject_inventory_key": "corpus",
            "subject_sha256": sha("corpus"),
        })
        candidate = encode_json(rewritten)
        with self.assertRaisesRegex(LedgerError, "exact append-only"):
            validate_index_append(
                prior_raw, candidate, expected_epoch=1, expected_controller_id="controller-a",
                expected_previous_sha256=sha(prior_raw), expected_current_sha256=sha(candidate),
            )

    def test_index_wrong_sha_and_duplicate_operation_id_are_rejected(self):
        candidate = append_intake(self.index)
        with self.assertRaisesRegex(LedgerError, "previous Index bytes"):
            validate_index_append(
                self.index, candidate, expected_epoch=1, expected_controller_id="controller-a",
                expected_previous_sha256=sha("wrong"), expected_current_sha256=sha(candidate),
            )
        first = json.loads(candidate)
        first["qualification_corpus_intakes"].append({
            "intake_id": "intake-0002", "operation_id": "operation-0001",
            "operator_principal": "synthetic-operator", "subject_inventory_key": "frozen-corpus",
            "subject_sha256": sha("corpus"),
        })
        second = encode_json(first)
        with self.assertRaisesRegex(LedgerError, "operation ID"):
            validate_index_append(
                self.index, second, expected_epoch=1, expected_controller_id="controller-a",
                expected_previous_sha256=sha(self.index), expected_current_sha256=sha(second),
            )

    def test_operation_ids_cannot_be_reused_in_a_later_revision(self):
        first = append_intake(self.index, intake_id="intake-a", operation_id="op-a")
        second = append_intake(first, intake_id="intake-b", operation_id="op-a")
        with self.assertRaisesRegex(LedgerError, "duplicate protected operation"):
            validate_index_append(
                first, second, expected_epoch=1, expected_controller_id="controller-a",
                expected_previous_sha256=sha(first), expected_current_sha256=sha(second),
            )

    def test_same_epoch_different_index_sha_at_same_revision_is_not_committable(self):
        changed = append_intake(self.index)
        candidate = replace(self.state, index_sha256=sha(changed), index_revision=0)
        with self.assertRaisesRegex(LedgerError, "exactly one"):
            validate_state_successor(self.state, candidate, authorization=None,
                                     expected_authority_identity=AUTHORITY, transition_id="tx")

    def test_revocation_state_includes_expiry_and_role_authorization(self):
        profile = {
            "revoked_authority_ids": [],
            "roles": [{"principal_id": "reviewer", "authorization_reference": "role-1",
                       "allowed_roles": ["scope_reviewer"], "valid_from": "2026-01-01T00:00:00Z",
                       "valid_until": "2026-12-01T00:00:00Z", "revoked_at": None,
                       "revocation_reason": None}],
        }
        first = revocation_state(profile)[0]
        profile["roles"][0]["valid_until"] = "2026-11-01T00:00:00Z"
        self.assertNotEqual(first, revocation_state(profile)[0])
        profile["roles"][0]["revoked_at"] = "2026-10-01T00:00:00Z"
        self.assertIn("role-1", revocation_state(profile)[2])

    def test_committed_record_chain_is_contiguous_and_unique(self):
        proposal = self.proposal()
        final = self.coordinator().commit(proposal)
        self.assertEqual(final.sequence, 1)
        verified = verify_ledger(
            self.store.read_ledger(), expected_authority_identity=AUTHORITY,
            expected_head_state_digest=final.head_state_digest,
            expected_head_record_sha256=final.head_record_sha256,
            expected_sequence=1,
        )
        self.assertEqual(len(verified), 2)
        self.assertEqual(verified[1]["previous_record_sha256"], sha(canonical_json_bytes(verified[0])))

    def test_duplicate_transition_id_is_not_reused_after_commit(self):
        proposal = self.proposal()
        self.coordinator().commit(proposal)
        replay = self.coordinator().commit(proposal)
        self.assertEqual(replay.sequence, 1)
        rebound = replace(proposal, proposed_state=replace(proposal.proposed_state,
                                                           profile_sha256=sha("forged")))
        with self.assertRaisesRegex(LedgerError, "TRANSITION_ID_REUSE"):
            self.coordinator().commit(rebound)

    def test_successful_transition_is_witness_committed_then_projection_matches(self):
        proposal = self.proposal()
        snapshot = self.coordinator().commit(proposal)
        self.assertEqual(snapshot.state.index_sha256, sha(proposal.candidate_index_raw))
        self.assertEqual(self.store.read_index(), proposal.candidate_index_raw)
        result = self.gate().check_current_state(**self.request(snapshot.state))
        self.assertEqual(result.decision, "verified")

    def test_stale_cas_token_is_rejected(self):
        proposal = self.proposal()
        stale = replace(proposal, expected_sequence=proposal.expected_sequence - 1)
        with self.assertRaises(LedgerError):
            self.coordinator().commit(stale)
        self.assertEqual(self.witness.read_current().sequence, 0)

    def test_two_writers_cannot_prepare_the_same_revision(self):
        first = self.proposal(transition_id="writer-a")
        second = self.proposal(transition_id="writer-b", intake_id="intake-b", operation_id="operation-b")
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        def prepare(proposal):
            auth = self.witness.verify_transition_authorization(proposal)
            barrier.wait()
            try:
                self.witness.prepare_transition(proposal)
                outcomes.append("prepared")
            except LedgerError:
                outcomes.append("rejected")

        threads = [threading.Thread(target=prepare, args=(proposal,)) for proposal in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["prepared", "rejected"])

    def test_definite_cas_busy_after_competing_commit_does_not_mark_loser_unresolved(self):
        winner = self.proposal(transition_id="winner", intake_id="winner-intake",
                               operation_id="winner-operation")
        loser = self.proposal(transition_id="loser", intake_id="loser-intake",
                              operation_id="loser-operation")
        original_prepare = self.witness.prepare_transition

        def competing_commit(_loser_proposal):
            prepared = original_prepare(winner)
            self.witness.commit_transition(prepared)
            self.store.index = winner.candidate_index_raw
            self.store.ledger = encode_ledger(AUTHORITY, self.witness.records)
            raise LedgerError("CAS_BUSY", "a concurrent writer already reserved and committed this revision")

        self.witness.prepare_transition = competing_commit
        with self.assertRaisesRegex(LedgerError, "TRANSITION_ABORTED"):
            self.coordinator().commit(loser)
        self.assertFalse(self.store.recovery_required())
        self.assertEqual(self.store.read_index(), winner.candidate_index_raw)
        self.assertEqual(self.witness.read_current().sequence, 1)
        self.assertEqual(self.gate().check_current_state(**self.request(self.witness.state)).decision,
                         "verified")

    def test_actor_cannot_self_authorize_a_transition(self):
        proposal = self.proposal()
        snapshot = self.witness.read_current()
        authorization = self.witness.verify_transition_authorization(proposal)
        self_authorized = replace(authorization, approver_principal=proposal.actor_principal)
        with self.assertRaisesRegex(LedgerError, "AUTHORIZATION_BINDING_MISMATCH"):
            validate_transition_proposal(proposal, snapshot, authorization=self_authorized,
                                         expected_authority_identity=AUTHORITY)

    def test_stale_fencing_token_cannot_commit_another_transition(self):
        proposal = self.proposal()
        prepared = self.witness.prepare_transition(proposal)
        wrong = replace(prepared, fencing_token="stale-fence")
        with self.assertRaisesRegex(LedgerError, "stale fencing"):
            self.witness.commit_transition(wrong)
        self.assertEqual(self.witness.read_current().sequence, 0)

    def test_crash_before_prepare_leaves_committed_state_unchanged(self):
        proposal = self.proposal()
        with self.assertRaises(LedgerError):
            self.coordinator().commit(proposal, failpoint=fail_at("validated"))
        self.assertEqual(self.witness.read_current().sequence, 0)
        self.assertEqual(self.store.read_index(), self.index)

    def test_crash_after_prepare_aborts_only_when_local_index_is_still_old(self):
        proposal = self.proposal()
        with self.assertRaisesRegex(LedgerError, "TRANSITION_ABORTED"):
            self.coordinator().commit(proposal, failpoint=fail_at("prepared"))
        self.assertEqual(self.witness.read_current().sequence, 0)
        self.assertEqual(self.witness.read_current().pending_transition_ids, ())
        self.assertEqual(self.store.read_index(), self.index)

    def test_crash_after_index_staging_aborts_witness_reservation_without_promoting_index(self):
        proposal = self.proposal()
        with self.assertRaisesRegex(LedgerError, "TRANSITION_ABORTED"):
            self.coordinator().commit(proposal, failpoint=fail_at("index_staged"))
        self.assertEqual(self.witness.read_current().sequence, 0)
        self.assertEqual(self.store.read_index(), self.index)
        self.assertNotEqual(self.store.staged_index(proposal.transition_id), self.store.read_index())

    def test_crash_after_witness_commit_enters_recovery_and_replays_exact_staged_bytes(self):
        proposal = self.proposal()
        coordinator = self.coordinator()
        with self.assertRaisesRegex(LedgerError, "RECOVERY_REQUIRED"):
            coordinator.commit(proposal, failpoint=fail_at("authority_committed"))
        self.assertEqual(self.witness.read_current().sequence, 1)
        self.assertEqual(self.store.read_index(), self.index)
        recovered = coordinator.recover(transition_id=proposal.transition_id)
        self.assertEqual(self.store.read_index(), proposal.candidate_index_raw)
        self.assertEqual(recovered.state.index_sha256, sha(proposal.candidate_index_raw))

    def test_crash_after_index_install_repairs_only_ledger_projection(self):
        proposal = self.proposal()
        coordinator = self.coordinator()
        with self.assertRaisesRegex(LedgerError, "RECOVERY_REQUIRED"):
            coordinator.commit(proposal, failpoint=fail_at("index_installed"))
        self.assertEqual(self.store.read_index(), proposal.candidate_index_raw)
        self.assertEqual(json.loads(self.store.read_ledger())["records"][-1]["sequence"], 0)
        coordinator.recover(transition_id=proposal.transition_id)
        self.assertEqual(json.loads(self.store.read_ledger())["records"][-1]["sequence"], 1)

    def test_lost_commit_ack_is_idempotently_recovered_and_retried(self):
        proposal = self.proposal()
        coordinator = self.coordinator()
        self.witness.lose_next_ack = True
        with self.assertRaisesRegex(LedgerError, "RECOVERY_REQUIRED"):
            coordinator.commit(proposal)
        self.assertEqual(self.witness.read_current().sequence, 1)
        retried = coordinator.commit(proposal)
        self.assertEqual(retried.sequence, 1)
        self.assertEqual(self.store.read_index(), proposal.candidate_index_raw)

    def test_recovery_never_resets_when_committed_index_bytes_are_missing(self):
        proposal = self.proposal()
        coordinator = self.coordinator()
        with self.assertRaises(LedgerError):
            coordinator.commit(proposal, failpoint=fail_at("authority_committed"))
        self.store.staged.pop(proposal.transition_id)
        with self.assertRaisesRegex(LedgerError, "bytes are unavailable"):
            coordinator.recover(transition_id=proposal.transition_id)
        self.assertEqual(self.store.read_index(), self.index)

    def test_prepared_transition_recovers_to_abort_if_candidate_was_not_staged(self):
        proposal = self.proposal()
        prepared = self.witness.prepare_transition(proposal)
        self.assertEqual(prepared.status, "prepared")
        recovered = self.coordinator().recover(transition_id=proposal.transition_id)
        self.assertEqual(recovered.sequence, 0)
        self.assertEqual(self.witness.read_current().pending_transition_ids, ())

    def test_prepared_transition_recovers_to_commit_only_from_exact_staged_candidate(self):
        proposal = self.proposal()
        prepared = self.witness.prepare_transition(proposal)
        self.store.stage_index(proposal.transition_id, proposal.candidate_index_raw)
        recovered = self.coordinator().recover(transition_id=proposal.transition_id)
        self.assertEqual(recovered.sequence, 1)
        self.assertEqual(self.store.read_index(), proposal.candidate_index_raw)
        self.assertIsNone(self.store.staged_index("not-the-transition"))

    def test_prepared_transition_with_mismatched_staged_bytes_requires_recovery(self):
        proposal = self.proposal()
        self.witness.prepare_transition(proposal)
        self.store.stage_index(proposal.transition_id, self.index)
        with self.assertRaisesRegex(LedgerError, "do not match"):
            self.coordinator().recover(transition_id=proposal.transition_id)
        self.assertEqual(self.witness.read_current().sequence, 0)

    def test_epoch_transition_can_rebind_profile_index_and_generation_with_authority_approval(self):
        index = base_index(epoch=2, controller="controller-b")
        new_index = encode_json(index)
        new_state = append_state(
            self.state, new_index,
            policy_identity="policy-b", policy_epoch=2, profile_sha256=sha("profile-b"),
            build_inventory_sha256=sha("build-b"), controller_id="controller-b",
            generation_id="generation-b", revocation_state_sha256=sha("revocation-b"),
        )
        proposal = TransitionProposal(
            "epoch-tx", 0, self.witness.read_current().head_state_digest,
            self.index, new_index, new_state, "epoch_transition", "owner", "owner-approval-1")
        snap = self.coordinator().commit(proposal)
        self.assertEqual(snap.state.policy_epoch, 2)
        self.assertEqual(snap.state.generation_id, "generation-b")

    def test_owner_approval_reference_is_not_inferred_from_role_name(self):
        candidate_witness = MemoryWitness(self.state, approved_references={"operator-role"},
                                          owner_policy_transition_refs=set())
        proposal = self.proposal(approval_ref="operator-role")
        new_state = replace(proposal.proposed_state, policy_epoch=2,
                            profile_sha256=sha("profile-b"), generation_id="generation-b")
        epoch_index = json.loads(proposal.candidate_index_raw)
        epoch_index["policy_epoch"] = 2
        epoch_bytes = encode_json(epoch_index)
        proposal = replace(proposal, candidate_index_raw=epoch_bytes,
                           proposed_state=replace(new_state, index_sha256=sha(epoch_bytes)),
                           operation_purpose="epoch_transition")
        store = MemoryProjection(self.index, [genesis_record(self.state)])
        with self.assertRaisesRegex(LedgerError, "Owner approval"):
            MonotonicTransitionCoordinator(authority=candidate_witness, authority_identity=AUTHORITY,
                                           store=store).commit(proposal)

    def test_aba_old_index_is_rejected_after_witness_has_advanced(self):
        proposal = self.proposal()
        self.coordinator().commit(proposal)
        self.store.index = self.index
        result = self.gate().check_current_state(**self.request(self.witness.state))
        self.assertEqual(result.error_code, "CURRENT_INDEX_MISMATCH")

    def test_profile_and_index_from_different_epochs_are_rejected(self):
        proposal = self.proposal()
        self.coordinator().commit(proposal)
        request = self.request(self.witness.state)
        request["profile_sha256"] = sha("old-profile")
        result = self.gate().check_current_state(**request)
        self.assertEqual(result.error_code, "CURRENT_STATE_MISMATCH")

    def test_generation_replay_is_rejected_by_epoch_transition_contract(self):
        candidate = replace(self.state, policy_epoch=2, profile_sha256=sha("profile-b"),
                            index_revision=1, revocation_state_sha256=sha("revocation-b"))
        auth = VerifiedTransitionAuthorization(AUTHORITY, "tx", "operator", "owner", "epoch_transition",
                                               "owner-approval-1", "owner_policy_transition",
                                               state_digest(candidate))
        with self.assertRaisesRegex(LedgerError, "new Generation"):
            validate_state_successor(self.state, candidate, authorization=auth,
                                     expected_authority_identity=AUTHORITY, transition_id="tx")

    def test_invalid_transition_schema_state_and_unknown_fields_are_rejected(self):
        from lifecycle_digest import schema_errors
        transition = {
            "transition_version": "rq03f-trust-transition-1.0",
            "transition_id": "tx-0001", "authority_identity": AUTHORITY,
            "expected_sequence": 0, "expected_state_digest": sha("old"),
            "proposed_state_digest": sha("new"), "operation_purpose": "qualification_review",
            "actor_principal": "operator", "owner_approval_reference": "owner-approval-1",
            "status": "prepared", "fencing_token": "fence", "audit_timestamp": "2026-10-11T00:00:00Z",
            "resolution_code": None,
        }
        self.assertEqual(schema_errors(transition, TRANSITION_SCHEMA), [])
        transition["unreviewed"] = True
        self.assertTrue(schema_errors(transition, TRANSITION_SCHEMA))

    def test_filesystem_projection_uses_exclusive_staging_and_atomic_index_replace(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("dirfd projection tests require Linux")
        projection_test_root = os.environ.get("RQ03F_C3_PROJECTION_TEST_ROOT")
        with tempfile.TemporaryDirectory(
            dir=projection_test_root or Path.home()
        ) as directory:
            root = Path(directory)
            (root / "operation-index.json").write_bytes(self.index)
            (root / "operation-index.json").chmod(0o600)
            (root / "ledger-projection.json").write_bytes(self.store.read_ledger())
            (root / "ledger-projection.json").chmod(0o600)
            store = DirectoryProjectionStore(root, operator_uid=os.getuid())
            try:
                proposal = self.proposal()
                store.stage_index(proposal.transition_id, proposal.candidate_index_raw)
                with self.assertRaisesRegex(LedgerError, "exclusive projection"):
                    store.stage_index(proposal.transition_id, proposal.candidate_index_raw)
                store.install_staged_index(proposal.transition_id)
                self.assertEqual(store.read_index(), proposal.candidate_index_raw)
            finally:
                store.close()

    def test_filesystem_projection_rejects_symlink_and_hardlink_index(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("dirfd projection tests require Linux")
        projection_test_root = os.environ.get("RQ03F_C3_PROJECTION_TEST_ROOT")
        with tempfile.TemporaryDirectory(
            dir=projection_test_root or Path.home()
        ) as directory:
            root = Path(directory)
            outside = root.parent / (root.name + "-outside")
            outside.write_bytes(self.index)
            outside.chmod(0o600)
            (root / "operation-index.json").symlink_to(outside)
            (root / "ledger-projection.json").write_bytes(self.store.read_ledger())
            (root / "ledger-projection.json").chmod(0o600)
            store = DirectoryProjectionStore(root, operator_uid=os.getuid())
            try:
                with self.assertRaises(LedgerError):
                    store.read_index()
            finally:
                store.close()
            (root / "operation-index.json").unlink()
            (root / "operation-index.json").write_bytes(self.index)
            os.link(root / "operation-index.json", root / "index-hardlink")
            store = DirectoryProjectionStore(root, operator_uid=os.getuid())
            try:
                with self.assertRaisesRegex(LedgerError, "link count"):
                    store.read_index()
            finally:
                store.close()
                outside.unlink(missing_ok=True)

    def test_recovery_marker_blocks_gate_until_verified_recovery_clears_it(self):
        self.store.mark_recovery_required("recovery-0001", "SIMULATED_CRASH")
        result = self.gate().check_current_state(**self.request())
        self.assertEqual(result.decision, "recovery_required")
        self.assertEqual(result.error_code, "RECOVERY_REQUIRED")
        self.store.clear_recovery_required("recovery-0001")
        self.assertEqual(self.gate().check_current_state(**self.request()).decision, "verified")


class HostedIdentityNameContractTests(unittest.TestCase):
    def test_ephemeral_role_and_group_names_fit_linux_limit(self):
        from tools.rq03f_c3.hosted_linux_isolation import _hosted_identity_names

        api_group, role_names = _hosted_identity_names("0123456789abcd")
        self.assertEqual(set(role_names), {"operator", "candidate", "author", "reviewer", "approver", "witness"})
        self.assertEqual(len(set(role_names.values())), len(role_names))
        self.assertLessEqual(max(map(len, [api_group, *role_names.values()])), 32)
        self.assertEqual(len(role_names["candidate"]), 31)
        with self.assertRaisesRegex(RuntimeError, "14 lowercase hex"):
            _hosted_identity_names("0" * 16)


def gate_request(values: dict) -> object:
    from rq03f_monotonic_trust_ledger import LedgerRequest
    return LedgerRequest(**values)


def fail_at(stage: str):
    def injector(current: str) -> None:
        if current == stage:
            raise OSError(f"synthetic crash at {stage}")
    return injector


if __name__ == "__main__":
    unittest.main()
