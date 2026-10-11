from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import base64
import json
import os
import threading
import unittest
from unittest.mock import patch

from google.cloud import spanner
from google.cloud.spanner_v1 import param_types

from authority_service import (
    AUTHORITY_ID, AuthorityError, CommitOutcomeUnknown, FaultPlan,
    OperatorClient, SpannerAuthorityService, SyntheticPeerAuthenticator,
    create_authority_database, install_synthetic_role, require_local_emulator,
    schema_ddl, sha256,
    c3,
)


PROJECT = "rq03f-d1a-synthetic"
INSTANCE_ID = "d1a-emulator"
BASE_TIME = datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)
OPERATOR = "synthetic-operator:qualification-custodian"
AUTHOR = "synthetic-author:author-a"
OWNER = "synthetic-owner:policy-admin"
APPROVER = "synthetic-owner:independent-approver"
INTAKE_REF = "synthetic-role-ref-intake"
AUTHOR_REF = "synthetic-role-ref-author"
OWNER_REF = "synthetic-role-ref-owner"


class TestClock:
    def __init__(self):
        self.value = BASE_TIME

    def now(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


def base_index(epoch: int = 1) -> dict:
    return {
        "index_version": "1.1",
        "controller_id": "synthetic-controller",
        "policy_epoch": epoch,
        "receipts": [],
        "authors": [],
        "adjudications": [],
        "qualification_runs": [],
        "qualification_corpus_intakes": [],
    }


def initial_state(index_raw: bytes, epoch: int = 1) -> c3.TrustState:
    return c3.TrustState(
        policy_identity="synthetic-policy",
        policy_epoch=epoch,
        profile_sha256=sha256(b"synthetic-profile-v1"),
        build_inventory_sha256=sha256(b"synthetic-build-inventory"),
        controller_id="synthetic-controller",
        generation_id="synthetic-generation-v1",
        index_sha256=sha256(index_raw),
        index_revision=0,
        revocation_state_sha256=sha256(b"synthetic-revocation-state-v1"),
    )


def append_row(raw: bytes, category: str, row: dict, *, epoch: int | None = None) -> bytes:
    value = json.loads(raw)
    if epoch is not None:
        value["policy_epoch"] = epoch
    value[category].append(row)
    return c3.canonical_json_bytes(value) + b"\n"


def intake_row(transition_id: str, principal: str = OPERATOR) -> dict:
    return {
        "intake_id": "intake-" + transition_id,
        "operation_id": transition_id,
        "operator_principal": principal,
        "subject_inventory_key": "synthetic-frozen-corpus",
        "subject_sha256": sha256(b"synthetic-corpus-only"),
    }


def author_row(transition_id: str, principal: str = AUTHOR) -> dict:
    return {
        "authoring_id": "authoring-" + transition_id,
        "operation_id": transition_id,
        "principal_id": principal,
        "content_sha256": sha256(b"synthetic-content-only"),
    }


def receipt_row(transition_id: str) -> dict:
    return {
        "receipt_id": "receipt-" + transition_id,
        "operation_id": transition_id,
        "actor_principal": OPERATOR,
        "subject_inventory_key": "synthetic-subject",
        "subject_sha256": sha256(b"subject"),
        "receipt_inventory_key": "synthetic-receipt",
        "receipt_sha256": sha256(b"receipt"),
    }


def run_row(transition_id: str) -> dict:
    return {
        "run_id": "run-" + transition_id,
        "operations": [{
            "case_id": "N01",
            "review_operation_id": transition_id,
            "input_inventory_keys": ["synthetic-input"],
            "labels_hidden": True,
            "prior_reasoning_hidden": True,
            "fresh_context": True,
        }],
    }


class SpannerAuthorityServiceTests(unittest.TestCase):
    _client = None
    _instance = None
    _database_counter = 0
    _counter_lock = threading.Lock()

    @classmethod
    def setUpClass(cls):
        require_local_emulator()
        cls._client = spanner.Client(project=PROJECT)
        cls._instance = cls._client.instance(
            INSTANCE_ID, configuration_name="emulator-config",
        )
        if not cls._instance.exists():
            cls._instance.create().result()

    def setUp(self):
        with self._counter_lock:
            type(self)._database_counter += 1
            database_id = f"d1a{type(self)._database_counter:04d}"
        self.database = self._instance.database(database_id, ddl_statements=schema_ddl())
        self.clock = TestClock()
        self.index_raw = c3.canonical_json_bytes(base_index()) + b"\n"
        self.state = initial_state(self.index_raw)
        self.checkpoint = create_authority_database(self.database, self.state, self.index_raw)
        self.faults = FaultPlan()
        self.service = SpannerAuthorityService(
            self.database, self.checkpoint, clock=self.clock.now, faults=self.faults,
        )
        self.authenticator = SyntheticPeerAuthenticator({
            "operator-token": OPERATOR,
            "author-token": AUTHOR,
            "owner-token": OWNER,
        })
        self.operator = OperatorClient(self.service, self.authenticator, "operator-token")
        self.author_client = OperatorClient(self.service, self.authenticator, "author-token")
        self.owner_client = OperatorClient(self.service, self.authenticator, "owner-token")
        self._role(INTAKE_REF, OPERATOR, "qualification_corpus_custodian",
                   "operator_role_operation", "qualification_corpus_intake")
        self._role(AUTHOR_REF, AUTHOR, "author",
                   "operator_role_operation", "production_authoring")
        self._role(OWNER_REF, OWNER, "owner_policy_transition",
                   "owner_policy_transition", "epoch_transition")
        self._role("synthetic-role-ref-revocation", OWNER, "owner_policy_transition",
                   "owner_policy_transition", "revocation")

    def _role(self, ref: str, principal: str, role: str, auth_class: str,
              purpose: str, *, valid_until: datetime | None = None,
              revoked: bool = False, epoch: int = 1) -> None:
        install_synthetic_role(
            self.database, reference=ref, principal=principal, role=role,
            authorization_class=auth_class, operation_purpose=purpose,
            epoch=epoch, valid_from=self.clock.now() - timedelta(minutes=1),
            valid_until=valid_until or self.clock.now() + timedelta(hours=1),
            approver=APPROVER, revoked=revoked,
        )

    def _request(self, transition_id: str, *, category: str = "qualification_corpus_intakes",
                 row: dict | None = None, purpose: str = "qualification_corpus_intake",
                 reference: str = INTAKE_REF, old_raw: bytes | None = None,
                 state_changes: dict | None = None, epoch: int | None = None) -> dict:
        old = self.index_raw if old_raw is None else old_raw
        if row is None and category == "qualification_corpus_intakes":
            row = intake_row(transition_id)
        elif row is None and category == "authors":
            row = author_row(transition_id)
        candidate = append_row(old, category, row, epoch=epoch)
        proposed = replace(
            self.state,
            policy_epoch=epoch if epoch is not None else self.state.policy_epoch,
            index_sha256=sha256(candidate),
            index_revision=self.state.index_revision + 1,
            **(state_changes or {}),
        )
        return {
            "transition_id": transition_id,
            "expected_sequence": 0,
            "expected_state_digest": c3._digest(self.state.payload()),
            "operation_purpose": purpose,
            "approval_reference": reference,
            "proposed_state": proposed.payload(),
            "candidate_index_b64": base64.b64encode(candidate).decode("ascii"),
        }

    def _request_with_candidate(self, transition_id: str, candidate: bytes,
                                *, purpose: str = "qualification_corpus_intake",
                                reference: str = INTAKE_REF, actor_row: str = OPERATOR,
                                epoch: int = 1, changes: dict | None = None) -> dict:
        proposed = replace(
            self.state, policy_epoch=epoch, index_sha256=sha256(candidate),
            index_revision=self.state.index_revision + 1, **(changes or {}),
        )
        return {
            "transition_id": transition_id, "expected_sequence": 0,
            "expected_state_digest": c3._digest(self.state.payload()),
            "operation_purpose": purpose, "approval_reference": reference,
            "proposed_state": proposed.payload(),
            "candidate_index_b64": base64.b64encode(candidate).decode("ascii"),
        }

    def _query(self, sql: str, params=None, types=None) -> list:
        with self.database.snapshot() as snapshot:
            return list(snapshot.execute_sql(sql, params=params or {}, param_types=types or {}))

    def _read_head(self) -> tuple:
        rows = self._query(
            "SELECT Sequence, StateDigest, IndexRevision, IndexSHA256, IndexBytesB64, "
            "FencingToken, PendingTransitionId FROM AuthorityHead WHERE HeadId='authority-head'",
        )
        self.assertEqual(len(rows), 1)
        return rows[0]

    def _current_intake_request(self, transition_id: str) -> dict:
        head = self.service._read_head(self.database)
        candidate = append_row(
            head.index_raw, "qualification_corpus_intakes", intake_row(transition_id),
        )
        proposed = replace(
            head.state, index_sha256=sha256(candidate),
            index_revision=head.state.index_revision + 1,
        )
        return {
            "transition_id": transition_id,
            "expected_sequence": head.sequence,
            "expected_state_digest": head.state_digest,
            "operation_purpose": "qualification_corpus_intake",
            "approval_reference": INTAKE_REF,
            "proposed_state": proposed.payload(),
            "candidate_index_b64": base64.b64encode(candidate).decode("ascii"),
        }

    def _commit_intake_history(self, count: int = 1) -> list[str]:
        transition_ids = []
        for number in range(count):
            transition_id = f"history-commit-{number:04d}"
            self.operator.prepare_transition(self._current_intake_request(transition_id))
            self.operator.commit_transition(transition_id)
            transition_ids.append(transition_id)
        return transition_ids

    def _assert_history_tamper_blocks_new_write(self, attempt_id: str) -> None:
        head_before = self._read_head()
        checkpoint_before = self.checkpoint.current()
        with self.assertRaises(AuthorityError) as read_error:
            self.service.read_current()
        self.assertEqual(read_error.exception.code, "RECOVERY_REQUIRED")
        with self.assertRaises(AuthorityError) as prepare_error:
            self.operator.prepare_transition(self._current_intake_request(attempt_id))
        self.assertEqual(prepare_error.exception.code, "RECOVERY_REQUIRED")
        self.assertEqual(self._read_head(), head_before)
        self.assertEqual(self.checkpoint.current(), checkpoint_before)
        self.assertIsNone(self.service._read_transition(self.database, attempt_id))

    def _assert_head_mirror_tamper_rejected(
        self, field: str, value: object, value_type: object, attempt_id: str,
    ) -> None:
        request = self._current_intake_request(attempt_id)
        original = self._read_head()
        count = self.database.run_in_transaction(lambda transaction: transaction.execute_update(
            f"UPDATE AuthorityHead SET {field}=@value WHERE HeadId=@head_id",
            params={"value": value, "head_id": "authority-head"},
            param_types={"value": value_type, "head_id": param_types.STRING},
        ))
        self.assertEqual(count, 1)
        with self.assertRaises(AuthorityError) as read_error:
            self.service.read_current()
        self.assertEqual(read_error.exception.code, "AUTHORITY_HEAD_CORRUPT")
        with self.assertRaises(AuthorityError) as prepare_error:
            self.operator.prepare_transition(request)
        self.assertEqual(prepare_error.exception.code, "AUTHORITY_HEAD_CORRUPT")
        after = self._read_head()
        self.assertEqual(after[0], original[0])
        self.assertEqual(after[1], original[1])
        self.assertEqual(after[3], original[3])
        self.assertEqual(after[4], original[4])
        self.assertIsNone(self.service._read_transition(self.database, attempt_id))

    def _events(self, transition_id: str) -> list:
        return self._query(
            "SELECT EventNumber, EventType, EventSHA256 FROM TransitionEvents "
            "WHERE TransitionId=@id ORDER BY EventNumber",
            {"id": transition_id},
            {"id": param_types.STRING},
        )

    def _assert_uncommitted(self, transition_id: str, expected_status: str | None = None) -> None:
        head = self._read_head()
        self.assertEqual(int(head[0]), 0)
        self.assertEqual(head[3], sha256(self.index_raw))
        self.assertEqual(base64.b64decode(head[4]), self.index_raw)
        if expected_status is not None:
            status = self.service._read_transition(self.database, transition_id)
            self.assertIsNotNone(status)
            self.assertEqual(status["status"], expected_status)

    def test_atomic_prepare_commit_advances_head_index_and_event_together(self):
        request = self._request("atomic-0001")
        prepared = self.operator.prepare_transition(request)
        self.assertEqual(prepared["status"], "prepared")
        before = self.service.read_current()
        self.assertEqual(before.sequence, 0)
        self.assertEqual(before.fencing_token, 1)
        committed = self.operator.commit_transition("atomic-0001")
        self.assertEqual(committed.sequence, 1)
        self.assertEqual(committed.index_revision, 1)
        self.assertEqual(committed.index_sha256, request["proposed_state"]["index_sha256"])
        status = self.operator.transition_status("atomic-0001")
        self.assertEqual(status["status"], "committed")
        self.assertEqual(status["result_sequence"], 1)
        events = self._events("atomic-0001")
        self.assertEqual([(int(row[0]), row[1]) for row in events],
                         [(0, "prepared"), (1, "committed")])
        self.assertTrue(all(len(row[2]) == 64 for row in events))

    def test_policy_epoch_mirror_tamper_is_rejected_without_new_transition(self):
        self._assert_head_mirror_tamper_rejected(
            "PolicyEpoch", 2, param_types.INT64, "mirror-policy-0001",
        )

    def test_index_revision_mirror_tamper_is_rejected_without_new_transition(self):
        self._assert_head_mirror_tamper_rejected(
            "IndexRevision", 1, param_types.INT64, "mirror-revision-0001",
        )

    def test_revocation_sha_mirror_tamper_is_rejected_without_new_transition(self):
        self._assert_head_mirror_tamper_rejected(
            "RevocationStateSHA256", sha256(b"different-revocation-state"),
            param_types.STRING, "mirror-revocation-0001",
        )

    def test_modified_committed_event_is_rejected_and_does_not_advance_head(self):
        transition_id, _ = self._commit_intake_history(2)
        altered = base64.b64encode(b'{"tampered":true}').decode("ascii")
        count = self.database.run_in_transaction(lambda transaction: transaction.execute_update(
            "UPDATE TransitionEvents SET EventJSONB64=@event "
            "WHERE TransitionId=@id AND EventNumber=1",
            params={"event": altered, "id": transition_id},
            param_types={"event": param_types.STRING, "id": param_types.STRING},
        ))
        self.assertEqual(count, 1)
        self._assert_history_tamper_blocks_new_write("history-event-modified-deny")

    def test_rehashed_but_rebound_committed_event_is_rejected(self):
        transition_id, _ = self._commit_intake_history(2)
        rows = self._query(
            "SELECT EventJSONB64 FROM TransitionEvents "
            "WHERE TransitionId=@id AND EventNumber=1",
            {"id": transition_id}, {"id": param_types.STRING},
        )
        payload = json.loads(base64.b64decode(rows[0][0]))
        payload["state_digest"] = sha256(b"coherently forged event only")
        event_raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        count = self.database.run_in_transaction(lambda transaction: transaction.execute_update(
            "UPDATE TransitionEvents SET EventJSONB64=@event, EventSHA256=@digest "
            "WHERE TransitionId=@id AND EventNumber=1",
            params={"event": base64.b64encode(event_raw).decode("ascii"),
                    "digest": sha256(event_raw), "id": transition_id},
            param_types={"event": param_types.STRING, "digest": param_types.STRING,
                         "id": param_types.STRING},
        ))
        self.assertEqual(count, 1)
        self._assert_history_tamper_blocks_new_write("history-event-rebound-deny")

    def test_deleted_committed_event_is_rejected_and_does_not_advance_head(self):
        transition_id, _ = self._commit_intake_history(2)
        count = self.database.run_in_transaction(lambda transaction: transaction.execute_update(
            "DELETE FROM TransitionEvents WHERE TransitionId=@id AND EventNumber=1",
            params={"id": transition_id}, param_types={"id": param_types.STRING},
        ))
        self.assertEqual(count, 1)
        self._assert_history_tamper_blocks_new_write("history-event-deleted-deny")

    def test_reordered_committed_events_are_rejected_and_do_not_advance_head(self):
        transition_id, _ = self._commit_intake_history(2)
        rows = self._query(
            "SELECT EventType, EventJSONB64, EventSHA256, OccurredAt "
            "FROM TransitionEvents WHERE TransitionId=@id AND EventNumber=1",
            {"id": transition_id}, {"id": param_types.STRING},
        )
        self.assertEqual(len(rows), 1)
        event_type, event_b64, event_sha, occurred_at = rows[0]
        def reorder_event(transaction):
            deleted = transaction.execute_update(
                "DELETE FROM TransitionEvents WHERE TransitionId=@id AND EventNumber=1",
                params={"id": transition_id}, param_types={"id": param_types.STRING},
            )
            transaction.insert(
                "TransitionEvents",
                columns=("TransitionId", "EventNumber", "EventType", "EventJSONB64", "EventSHA256", "OccurredAt"),
                values=[(transition_id, 2, event_type, event_b64, event_sha, occurred_at)],
            )
            return deleted
        self.assertEqual(self.database.run_in_transaction(reorder_event), 1)
        self._assert_history_tamper_blocks_new_write("history-event-reordered-deny")

    def test_modified_prior_index_history_bytes_and_valid_sha_are_rejected(self):
        self._commit_intake_history(2)
        altered = b"{" + b'"synthetic":"different prior Index"' + b"}\n"
        count = self.database.run_in_transaction(lambda transaction: transaction.execute_update(
            "UPDATE IndexHistory SET IndexBytesB64=@bytes, IndexSHA256=@digest "
            "WHERE IndexRevision=1",
            params={"bytes": base64.b64encode(altered).decode("ascii"),
                    "digest": sha256(altered)},
            param_types={"bytes": param_types.STRING, "digest": param_types.STRING},
        ))
        self.assertEqual(count, 1)
        self._assert_history_tamper_blocks_new_write("history-index-modified-deny")

    def test_deleted_prior_index_history_revision_is_rejected(self):
        self._commit_intake_history(2)
        count = self.database.run_in_transaction(lambda transaction: transaction.execute_update(
            "DELETE FROM IndexHistory WHERE IndexRevision=1",
        ))
        self.assertEqual(count, 1)
        self._assert_history_tamper_blocks_new_write("history-index-deleted-deny")

    def test_reordered_prior_index_history_revision_is_rejected(self):
        self._commit_intake_history(2)
        rows = self._query(
            "SELECT IndexSHA256, IndexBytesB64, TransitionId FROM IndexHistory WHERE IndexRevision=1",
        )
        self.assertEqual(len(rows), 1)
        index_sha, index_b64, transition_id = rows[0]
        def reorder_index_history(transaction):
            deleted = transaction.execute_update(
                "DELETE FROM IndexHistory WHERE IndexRevision=1",
            )
            transaction.insert(
                "IndexHistory",
                columns=("IndexRevision", "IndexSHA256", "IndexBytesB64", "TransitionId"),
                values=[(99, index_sha, index_b64, transition_id)],
            )
            return deleted
        self.assertEqual(self.database.run_in_transaction(reorder_index_history), 1)
        self._assert_history_tamper_blocks_new_write("history-index-reordered-deny")

    def test_prepared_transition_can_be_aborted_without_index_change(self):
        request = self._request("abort-0001")
        self.operator.prepare_transition(request)
        self.operator.abort_transition("abort-0001", "OPERATOR_CANCELLED")
        self._assert_uncommitted("abort-0001", "aborted")
        self.assertEqual([row[1] for row in self._events("abort-0001")],
                         ["prepared", "aborted"])

    def test_known_abort_is_distinct_from_unknown_and_same_id_can_be_resubmitted(self):
        request = self._request("known-abort-0001")
        self.operator.prepare_transition(request)
        self.faults.abort_commit_before_transaction = True
        with self.assertRaises(AuthorityError) as raised:
            self.operator.commit_transition("known-abort-0001")
        self.assertEqual(raised.exception.code, "SPANNER_ABORTED")
        self._assert_uncommitted("known-abort-0001", "prepared")
        self.assertEqual([row[1] for row in self._events("known-abort-0001")],
                         ["prepared"])
        committed = self.operator.commit_transition("known-abort-0001")
        self.assertEqual(committed.sequence, 1)
        self.assertEqual(self.operator.transition_status("known-abort-0001")["status"],
                         "committed")
        self.assertEqual([row[1] for row in self._events("known-abort-0001")],
                         ["prepared", "committed"])

    def test_intake_purpose_cannot_append_author_record(self):
        candidate = append_row(self.index_raw, "authors", author_row("bad-author-0001"))
        request = self._request_with_candidate("bad-author-0001", candidate)
        with self.assertRaises(c3.LedgerError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "PURPOSE_INDEX_SCOPE_MISMATCH")
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "bad-author-0001"))

    def test_intake_purpose_cannot_append_receipt_record(self):
        candidate = append_row(self.index_raw, "receipts", receipt_row("bad-receipt-0001"))
        request = self._request_with_candidate("bad-receipt-0001", candidate)
        with self.assertRaises(c3.LedgerError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "PURPOSE_INDEX_SCOPE_MISMATCH")
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "bad-receipt-0001"))

    def test_intake_purpose_cannot_append_qualification_run(self):
        candidate = append_row(self.index_raw, "qualification_runs", run_row("bad-run-0001"))
        request = self._request_with_candidate("bad-run-0001", candidate)
        with self.assertRaises(c3.LedgerError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "PURPOSE_INDEX_SCOPE_MISMATCH")
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "bad-run-0001"))

    def test_mixed_intake_and_author_delta_is_rejected(self):
        candidate = append_row(self.index_raw, "qualification_corpus_intakes",
                               intake_row("mixed-0001"))
        candidate = append_row(candidate, "authors", author_row("mixed-author-0001"))
        request = self._request_with_candidate("mixed-0001", candidate)
        with self.assertRaises(c3.LedgerError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "PURPOSE_INDEX_SCOPE_MISMATCH")
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "mixed-0001"))

    def test_row_actor_must_match_authenticated_server_peer(self):
        candidate = append_row(self.index_raw, "qualification_corpus_intakes",
                               intake_row("actor-mismatch-0001", principal="forged-client-actor"))
        request = self._request_with_candidate("actor-mismatch-0001", candidate)
        with self.assertRaises(c3.LedgerError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "INDEX_OPERATION_BINDING_MISMATCH")
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "actor-mismatch-0001"))

    def test_caller_cannot_supply_actor_role_or_fencing_fields(self):
        request = self._request("caller-actor-0001")
        request["actor_principal"] = "forged-actor"
        with self.assertRaises(AuthorityError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "REQUEST_FIELDS_INVALID")
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "caller-actor-0001"))

    def test_authorization_class_and_registered_purpose_must_match(self):
        self._role("synthetic-role-wrong-class", OPERATOR,
                   "qualification_corpus_custodian", "owner_policy_transition",
                   "qualification_corpus_intake")
        request = self._request("bad-class-0001", reference="synthetic-role-wrong-class")
        with self.assertRaises(c3.LedgerError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "AUTHORIZATION_REJECTED")
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "bad-class-0001"))

    def test_wrong_authorization_reference_purpose_is_rejected(self):
        request = self._request("bad-purpose-ref-0001", reference=AUTHOR_REF)
        with self.assertRaises(c3.LedgerError):
            self.operator.prepare_transition(request)
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "bad-purpose-ref-0001"))

    def test_authorized_production_author_append_remains_in_its_exact_scope(self):
        candidate = append_row(self.index_raw, "authors", author_row("author-op-0001"))
        request = self._request_with_candidate(
            "author-op-0001", candidate, purpose="production_authoring",
            reference=AUTHOR_REF, actor_row=AUTHOR,
        )
        prepared = self.author_client.prepare_transition(request)
        self.assertEqual(prepared["operation_purpose"], "production_authoring")
        committed = self.author_client.commit_transition("author-op-0001")
        self.assertEqual(committed.sequence, 1)
        self.assertEqual(committed.index_sha256, sha256(candidate))

    def test_expiry_after_prepare_durably_aborts_and_preserves_index(self):
        until = self.clock.now() + timedelta(seconds=20)
        self._role("short-lived-intake", OPERATOR, "qualification_corpus_custodian",
                   "operator_role_operation", "qualification_corpus_intake",
                   valid_until=until)
        request = self._request("expired-after-prepare-0001", reference="short-lived-intake")
        self.operator.prepare_transition(request)
        self.clock.advance(timedelta(seconds=21))
        with self.assertRaises(AuthorityError) as raised:
            self.operator.commit_transition("expired-after-prepare-0001")
        self.assertIn(raised.exception.code, {"RESERVATION_EXPIRED_OR_STALE", "AUTHORIZATION_REJECTED"})
        self._assert_uncommitted("expired-after-prepare-0001", "aborted")
        self.assertEqual([row[1] for row in self._events("expired-after-prepare-0001")],
                         ["prepared", "aborted"])

    def test_role_revocation_after_prepare_durably_aborts(self):
        request = self._request("revoked-after-prepare-0001")
        self.operator.prepare_transition(request)
        def revoke(transaction):
            transaction.update(
                "OwnerRoleRegistry", columns=("AuthorizationReference", "Revoked"),
                values=[(INTAKE_REF, True)],
            )
        self.database.run_in_transaction(revoke)
        with self.assertRaises(AuthorityError) as raised:
            self.operator.commit_transition("revoked-after-prepare-0001")
        self.assertEqual(raised.exception.code, "AUTHORIZATION_REJECTED")
        self._assert_uncommitted("revoked-after-prepare-0001", "aborted")

    def test_epoch_transition_requires_owner_scope_and_rotated_state(self):
        candidate = c3.canonical_json_bytes(base_index(epoch=2)) + b"\n"
        request = self._request_with_candidate(
            "epoch-0001", candidate, purpose="epoch_transition",
            reference=OWNER_REF, epoch=2,
            changes={
                "profile_sha256": sha256(b"synthetic-profile-v2"),
                "generation_id": "synthetic-generation-v2",
            },
        )
        prepared = self.owner_client.prepare_transition(request)
        self.assertEqual(prepared["operation_purpose"], "epoch_transition")
        committed = self.owner_client.commit_transition("epoch-0001")
        self.assertEqual(committed.policy_epoch, 2)
        self.assertEqual(committed.index_revision, 1)

    def test_revocation_transition_advances_epoch_and_adds_monotonic_revocation(self):
        candidate = c3.canonical_json_bytes(base_index(epoch=2)) + b"\n"
        request = self._request_with_candidate(
            "revoke-0001", candidate, purpose="revocation",
            reference="synthetic-role-ref-revocation", epoch=2,
            changes={
                "profile_sha256": sha256(b"synthetic-profile-revoked"),
                "generation_id": "synthetic-generation-revoked",
                "revocation_state_sha256": sha256(b"synthetic-revocation-state-v2"),
                "revoked_role_authorization_references": ("revoked-role-reference",),
            },
        )
        prepared = self.owner_client.prepare_transition(request)
        self.assertEqual(prepared["operation_purpose"], "revocation")
        committed = self.owner_client.commit_transition("revoke-0001")
        self.assertEqual(committed.policy_epoch, 2)
        self.assertEqual(committed.index_revision, 1)

    def test_old_epoch_and_old_index_revision_fail_without_transition(self):
        request = self._request("stale-epoch-0001")
        request["proposed_state"]["policy_epoch"] = 0
        with self.assertRaises(AuthorityError):
            self.operator.prepare_transition(request)
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "stale-epoch-0001"))
        request2 = self._request("stale-revision-0001")
        request2["proposed_state"]["index_revision"] = 2
        request2["proposed_state"]["index_sha256"] = sha256(
            base64.b64decode(request2["candidate_index_b64"])
        )
        with self.assertRaises(c3.LedgerError):
            self.operator.prepare_transition(request2)
        self.assertEqual(self._read_head()[0], 0)
        self.assertIsNone(self.service._read_transition(self.database, "stale-revision-0001"))

    def test_duplicate_transition_id_cannot_create_second_commit(self):
        request = self._request("duplicate-0001")
        self.operator.prepare_transition(request)
        self.operator.commit_transition("duplicate-0001")
        with self.assertRaises(AuthorityError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "TRANSITION_ID_REUSE")
        with self.assertRaises(AuthorityError):
            self.operator.commit_transition("duplicate-0001")
        self.assertEqual(int(self._read_head()[0]), 1)
        self.assertEqual(self.service._read_transition(self.database, "duplicate-0001")["status"],
                         "committed")
        self.assertEqual([row[1] for row in self._events("duplicate-0001")],
                         ["prepared", "committed"])

    def test_two_concurrent_writers_with_same_head_yield_one_prepare_and_commit(self):
        clients = [self.operator, self.operator]
        requests = [
            self._request("race-0001"),
            self._request("race-0002"),
        ]
        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, str]] = []
        lock = threading.Lock()
        def submit(index: int) -> None:
            barrier.wait()
            try:
                clients[index].prepare_transition(requests[index])
                result = ("prepared", requests[index]["transition_id"])
            except AuthorityError as exc:
                result = (exc.code, requests[index]["transition_id"])
            except c3.LedgerError as exc:
                result = (exc.code, requests[index]["transition_id"])
            with lock:
                outcomes.append(result)
        threads = [threading.Thread(target=submit, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        prepared_ids = [item[1] for item in outcomes if item[0] == "prepared"]
        self.assertEqual(len(prepared_ids), 1, outcomes)
        rejected = [item for item in outcomes if item[0] != "prepared"]
        # During the DB-commit / external-checkpoint gap the loser must fail
        # closed as RECOVERY_REQUIRED; once the checkpoint is current it reports
        # the ordinary busy/stale CAS outcome. It must never prepare as well.
        self.assertEqual(len(rejected), 1, outcomes)
        self.assertIn(rejected[0][0], {"CAS_BUSY", "CAS_STALE", "RECOVERY_REQUIRED"}, outcomes)
        self.operator.commit_transition(prepared_ids[0])
        self.assertEqual(int(self._read_head()[0]), 1)
        self.assertEqual(self.service.read_current().sequence, 1)
        statuses = [
            self.service._read_transition(self.database, item[1])
            for item in outcomes
        ]
        self.assertEqual(sum(1 for status in statuses if status and status["status"] == "committed"), 1)
        self.assertEqual(sum(status is None for status in statuses), 1)

    def test_commit_ack_loss_is_resolved_by_transition_id_without_retry(self):
        request = self._request("lost-ack-0001")
        self.operator.prepare_transition(request)
        self.faults.lose_commit_ack = True
        with self.assertRaises(CommitOutcomeUnknown):
            self.operator.commit_transition("lost-ack-0001")
        status = self.operator.transition_status("lost-ack-0001")
        self.assertEqual(status["status"], "committed")
        self.assertEqual(status["result_sequence"], 1)
        self.assertEqual(int(self._read_head()[0]), 1)
        self.assertEqual(len(self._events("lost-ack-0001")), 2)

    def test_unknown_commit_blocks_retry_until_checkpoint_reconciliation(self):
        request = self._request("unknown-commit-0001")
        self.operator.prepare_transition(request)
        self.faults.hide_checkpoint_after_commit = True
        with self.assertRaises(CommitOutcomeUnknown):
            self.operator.commit_transition("unknown-commit-0001")
        self.assertEqual(int(self._read_head()[0]), 1)
        with self.assertRaises(AuthorityError) as unavailable:
            self.operator.transition_status("unknown-commit-0001")
        self.assertEqual(unavailable.exception.code, "CHECKPOINT_UNAVAILABLE")
        self.checkpoint.available = True
        self.assertEqual(self.operator.transition_status("unknown-commit-0001")["status"],
                         "committed")
        with self.assertRaises(AuthorityError) as recovery_required:
            self.service.read_current()
        self.assertEqual(recovery_required.exception.code, "RECOVERY_REQUIRED")
        with self.assertRaises(AuthorityError):
            self.operator.commit_transition("unknown-commit-0001")
        self.assertEqual(int(self._read_head()[0]), 1)
        self.assertEqual(self.checkpoint.current().sequence, 0)

    def test_external_checkpoint_detects_old_database_snapshot(self):
        before = self.service._read_head(self.database)
        request = self._request("snapshot-restore-0001")
        self.operator.prepare_transition(request)
        self.operator.commit_transition("snapshot-restore-0001")
        self.assertEqual(self.checkpoint.current().sequence, 1)
        self.service.test_only_restore_head(before)
        with self.assertRaises(AuthorityError) as raised:
            self.service.read_current()
        self.assertEqual(raised.exception.code, "ROLLBACK_DETECTED")
        self.assertEqual(int(self._read_head()[0]), 0)
        self.assertEqual(self.checkpoint.current().sequence, 1)

    def test_checkpoint_unavailable_fails_closed_before_prepare(self):
        self.checkpoint.available = False
        request = self._request("checkpoint-down-0001")
        with self.assertRaises(AuthorityError) as raised:
            self.operator.prepare_transition(request)
        self.assertEqual(raised.exception.code, "CHECKPOINT_UNAVAILABLE")
        self.assertEqual(int(self._read_head()[0]), 0)
        self.assertIsNone(self.service._read_transition(self.database, "checkpoint-down-0001"))

    def test_operator_rpc_has_no_database_handle_and_emulator_exposes_iam_gap(self):
        self.assertFalse(any("database" in name.lower() for name in vars(self.operator)))
        self.assertFalse(hasattr(self.operator, "database"))
        # The following is deliberately an emulator limitation test, not a
        # security pass: the emulator accepts direct DML because it has no IAM.
        direct_client = self._client
        direct_database = direct_client.instance(
            INSTANCE_ID, configuration_name="emulator-config",
        ).database(self.database.database_id)
        def unauthorized_dml(transaction):
            transaction.execute_update(
                "UPDATE AuthorityHead SET Sequence=99 WHERE HeadId='authority-head'"
            )
        direct_database.run_in_transaction(unauthorized_dml)
        self.assertEqual(int(self._read_head()[0]), 99)
        with self.assertRaises(AuthorityError) as raised:
            self.service.read_current()
        self.assertEqual(raised.exception.code, "RECOVERY_REQUIRED")

    def test_research_adapter_refuses_non_emulator_endpoint(self):
        with patch.dict(os.environ, {"SPANNER_EMULATOR_HOST": "spanner.googleapis.com"}):
            with self.assertRaises(AuthorityError) as raised:
                require_local_emulator()
        self.assertEqual(raised.exception.code, "EMULATOR_ONLY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
