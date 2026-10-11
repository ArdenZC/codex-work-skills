#!/usr/bin/env python3
"""Disposable, real-UID C3 witness/projection integration exercise.

All authority material generated here is synthetic. The witness runs as its own
Linux UID and persists outside the Operator projection directory. The workflow
and this test code are branch-controlled, so the result is hosted protocol
evidence only and never Production Operator Trust.
"""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import secrets
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lifecycle_digest import canonical_json_bytes
from rq03f_monotonic_trust_ledger import (
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
    validate_index_append,
    validate_state_successor,
)


AUTHORITY_ID = "rq03f-c3-hosted-witness-synthetic-only"
APPROVAL_REF = "synthetic-hosted-operator-role-approval"
OWNER_REF = "synthetic-hosted-owner-epoch-approval"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _state_from_wire(payload: dict[str, Any]) -> TrustState:
    return TrustState.from_payload(payload)


def _wire_snapshot(state_doc: dict[str, Any], *, fence: str) -> dict[str, Any]:
    records = state_doc["records"]
    last = records[-1]
    now = datetime.now(timezone.utc)
    return {
        "authority_identity": state_doc["authority_identity"],
        "sequence": last["sequence"],
        "head_state_digest": last["current_committed_state_digest"],
        "head_record_sha256": _sha(canonical_json_bytes(last)),
        "state": last["state"],
        "checked_at": now.isoformat().replace("+00:00", "Z"),
        "valid_until": (now + timedelta(seconds=12)).isoformat().replace("+00:00", "Z"),
        "fencing_token": fence,
        "history": records,
        "pending_transition_ids": sorted(state_doc["pending"]),
    }


def _typed_snapshot(payload: dict[str, Any]) -> WitnessSnapshot:
    return WitnessSnapshot(
        authority_identity=payload["authority_identity"],
        sequence=payload["sequence"],
        head_state_digest=payload["head_state_digest"],
        head_record_sha256=payload["head_record_sha256"],
        state=_state_from_wire(payload["state"]),
        checked_at=datetime.fromisoformat(payload["checked_at"].replace("Z", "+00:00")),
        valid_until=datetime.fromisoformat(payload["valid_until"].replace("Z", "+00:00")),
        fencing_token=payload["fencing_token"],
        history=tuple(payload["history"]),
        pending_transition_ids=tuple(payload["pending_transition_ids"]),
    )


class WitnessServer:
    """Small synthetic CAS service owned by the independent test UID."""

    def __init__(self, *, state_path: Path, socket_path: Path,
                 operator_uid: int, api_gid: int):
        self.state_path = state_path
        self.socket_path = socket_path
        self.operator_uid = operator_uid
        self.api_gid = api_gid
        self.stop = threading.Event()
        self.lock = threading.RLock()
        parent = state_path.parent
        parent_info = parent.lstat()
        state_info = state_path.lstat()
        if (stat.S_ISLNK(parent_info.st_mode) or stat.S_ISLNK(state_info.st_mode)
                or parent_info.st_uid != os.getuid() or parent_info.st_mode & 0o077
                or state_info.st_uid != os.getuid() or state_info.st_nlink != 1
                or state_info.st_mode & 0o077):
            raise RuntimeError("synthetic Witness store owner/mode verification failed")
        if socket_path.exists() or socket_path.is_symlink():
            raise RuntimeError("new synthetic Witness socket path already exists")

    def _load(self) -> dict[str, Any]:
        raw = self.state_path.read_bytes()
        return _json(raw)

    def _persist(self, payload: dict[str, Any]) -> None:
        raw = canonical_json_bytes(payload) + b"\n"
        temp_name = f".{self.state_path.name}.{secrets.token_hex(12)}.stage"
        temp_path = self.state_path.parent / temp_name
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            view = memoryview(raw)
            while view:
                size = os.write(fd, view)
                if size <= 0:
                    raise OSError("Witness persistence write made no progress")
                view = view[size:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp_path, self.state_path)
        dir_fd = os.open(self.state_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _peer_uid(self, conn: socket.socket) -> int:
        raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", raw)
        return uid

    def _status(self, payload: dict[str, Any], transition_id: str) -> dict[str, Any] | None:
        if transition_id in payload["pending"]:
            pending = payload["pending"][transition_id]
            prepared = pending["prepared"]
            return {
                "authority_identity": AUTHORITY_ID,
                "transition_id": transition_id,
                "status": "prepared",
                "expected_sequence": prepared["expected_sequence"],
                "expected_state_digest": prepared["expected_state_digest"],
                "proposed_state_digest": prepared["proposed_state_digest"],
                "proposed_index_sha256": prepared["proposed_index_sha256"],
                "prepared": prepared,
            }
        return payload["transitions"].get(transition_id)

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        payload = self._load()
        if action == "read_current":
            last = payload["records"][-1]
            return {"ok": True, "snapshot": _wire_snapshot(payload, fence=f"witness-{last['sequence']}")}
        if action == "read_transition":
            status = self._status(payload, request["transition_id"])
            return {"ok": True, "status": status}
        if action == "verify_transition_authorization":
            proposal = request["proposal"]
            reference = proposal["owner_approval_reference"]
            if reference not in payload["approved_references"]:
                return {"ok": False, "code": "AUTHORIZATION_REJECTED"}
            if proposal["actor_principal"] != "synthetic-hosted-operator":
                return {"ok": False, "code": "ACTOR_IDENTITY_REJECTED"}
            authorization_class = ("owner_policy_transition" if reference in payload["owner_policy_refs"]
                                   else "operator_role_operation")
            return {"ok": True, "authorization": {
                "authority_identity": AUTHORITY_ID,
                "transition_id": proposal["transition_id"],
                "actor_principal": proposal["actor_principal"],
                "approver_principal": "synthetic-independent-approver",
                "operation_purpose": proposal["operation_purpose"],
                "approval_reference": reference,
                "authorization_class": authorization_class,
                "proposed_state_digest": _sha(canonical_json_bytes(proposal["proposed_state"])),
            }}
        if action == "prepare_transition":
            if payload["pending"]:
                return {"ok": False, "code": "CAS_BUSY"}
            proposal_wire = request["proposal"]
            transition_id = proposal_wire["transition_id"]
            if transition_id in payload["transitions"]:
                return {"ok": False, "code": "TRANSITION_ID_REUSE"}
            last = payload["records"][-1]
            if (proposal_wire["expected_sequence"] != last["sequence"]
                    or proposal_wire["expected_state_digest"] != last["current_committed_state_digest"]):
                return {"ok": False, "code": "CAS_STALE"}
            if proposal_wire["owner_approval_reference"] not in payload["approved_references"]:
                return {"ok": False, "code": "AUTHORIZATION_REJECTED"}
            old_raw = base64.b64decode(proposal_wire["previous_index_b64"], validate=True)
            new_raw = base64.b64decode(proposal_wire["candidate_index_b64"], validate=True)
            old_state = _state_from_wire(last["state"])
            proposed_state = _state_from_wire(proposal_wire["proposed_state"])
            if _sha(old_raw) != old_state.index_sha256 or _sha(new_raw) != proposed_state.index_sha256:
                return {"ok": False, "code": "INDEX_SHA_MISMATCH"}
            validate_index_append(
                old_raw, new_raw,
                expected_epoch=proposed_state.policy_epoch,
                expected_controller_id=proposed_state.controller_id,
                expected_previous_sha256=old_state.index_sha256,
                expected_current_sha256=proposed_state.index_sha256,
                allow_policy_transition=proposed_state.policy_epoch > old_state.policy_epoch,
                allow_empty_transition=proposed_state.policy_epoch > old_state.policy_epoch,
            )
            reference = proposal_wire["owner_approval_reference"]
            authorization = VerifiedTransitionAuthorization(
                authority_identity=AUTHORITY_ID,
                transition_id=transition_id,
                actor_principal=proposal_wire["actor_principal"],
                approver_principal="synthetic-independent-approver",
                operation_purpose=proposal_wire["operation_purpose"],
                approval_reference=reference,
                authorization_class=("owner_policy_transition" if reference in payload["owner_policy_refs"]
                                     else "operator_role_operation"),
                proposed_state_digest=_sha(canonical_json_bytes(proposed_state.payload())),
            )
            validate_state_successor(
                old_state, proposed_state, authorization=authorization,
                expected_authority_identity=AUTHORITY_ID, transition_id=transition_id,
            )
            token = f"witness-fence-{last['sequence']}-{secrets.token_hex(12)}"
            prepared = {
                "authority_identity": AUTHORITY_ID,
                "transition_id": transition_id,
                "status": "prepared",
                "expected_sequence": last["sequence"],
                "expected_state_digest": last["current_committed_state_digest"],
                "proposed_state_digest": _sha(canonical_json_bytes(proposed_state.payload())),
                "proposed_index_sha256": proposed_state.index_sha256,
                "fencing_token": token,
                "approval_reference": reference,
            }
            payload["pending"][transition_id] = {
                "proposal": proposal_wire,
                "prepared": prepared,
            }
            self._persist(payload)
            return {"ok": True, "prepared": prepared}
        if action == "commit_transition":
            transition_id = request["prepared"]["transition_id"]
            pending = payload["pending"].get(transition_id)
            if not pending or pending["prepared"] != request["prepared"]:
                return {"ok": False, "code": "FENCING_TOKEN_STALE"}
            last = payload["records"][-1]
            if (request["prepared"]["expected_sequence"] != last["sequence"]
                    or request["prepared"]["expected_state_digest"] != last["current_committed_state_digest"]):
                return {"ok": False, "code": "CAS_STALE"}
            proposal = pending["proposal"]
            proposed_state = _state_from_wire(proposal["proposed_state"])
            record = build_ledger_record(
                authority_identity=AUTHORITY_ID,
                sequence=last["sequence"] + 1,
                previous_state_digest=last["current_committed_state_digest"],
                previous_record_sha256=_sha(canonical_json_bytes(last)),
                state=proposed_state,
                transition_id=transition_id,
                operation_purpose=proposal["operation_purpose"],
                owner_approval_reference=proposal["owner_approval_reference"],
                audit_timestamp=datetime.now(timezone.utc),
            )
            payload["records"].append(record)
            payload["pending"].pop(transition_id)
            payload["transitions"][transition_id] = {
                "authority_identity": AUTHORITY_ID,
                "transition_id": transition_id,
                "status": "committed",
                "expected_sequence": request["prepared"]["expected_sequence"],
                "expected_state_digest": request["prepared"]["expected_state_digest"],
                "proposed_state_digest": request["prepared"]["proposed_state_digest"],
                "proposed_index_sha256": request["prepared"]["proposed_index_sha256"],
                "prepared": None,
            }
            lose_ack = payload.get("lose_next_commit_ack") is True
            payload["lose_next_commit_ack"] = False
            self._persist(payload)
            if lose_ack:
                # Persist the committed high-water state, then close without
                # an acknowledgement to exercise client-side uncertainty.
                return {"ok": True, "drop_response": True}
            last = payload["records"][-1]
            return {"ok": True, "snapshot": _wire_snapshot(payload, fence=f"witness-{last['sequence']}")}
        if action == "abort_transition":
            prepared = request["prepared"]
            transition_id = prepared["transition_id"]
            pending = payload["pending"].get(transition_id)
            if not pending or pending["prepared"] != prepared:
                return {"ok": False, "code": "FENCING_TOKEN_STALE"}
            payload["pending"].pop(transition_id)
            payload["transitions"][transition_id] = {
                "authority_identity": AUTHORITY_ID,
                "transition_id": transition_id,
                "status": "aborted",
                "expected_sequence": prepared["expected_sequence"],
                "expected_state_digest": prepared["expected_state_digest"],
                "proposed_state_digest": prepared["proposed_state_digest"],
                "proposed_index_sha256": prepared["proposed_index_sha256"],
                "prepared": None,
            }
            self._persist(payload)
            return {"ok": True}
        return {"ok": False, "code": "UNKNOWN_ACTION"}

    def _client(self, conn: socket.socket) -> None:
        try:
            if self._peer_uid(conn) != self.operator_uid:
                conn.sendall(b'{"ok":false,"code":"PEER_UID_REJECTED"}\n')
                return
            raw = bytearray()
            while len(raw) <= 2 * 1024 * 1024:
                block = conn.recv(65536)
                if not block:
                    break
                raw.extend(block)
                if b"\n" in block:
                    break
            request = _json(bytes(raw).split(b"\n", 1)[0])
            with self.lock:
                response = self._handle(request)
            if response.get("drop_response") is True:
                return
            conn.sendall(canonical_json_bytes(response) + b"\n")
        except Exception as exc:
            code = getattr(exc, "code", None) or type(exc).__name__.upper()
            try:
                conn.sendall(canonical_json_bytes({"ok": False, "code": str(code)[:100]}) + b"\n")
            except OSError:
                pass
        finally:
            conn.close()

    def serve(self) -> None:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chown(self.socket_path, os.getuid(), self.api_gid)
        os.chmod(self.socket_path, 0o660)
        server.listen(16)
        server.settimeout(0.2)
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        try:
            while not self.stop.is_set():
                try:
                    conn, _ = server.accept()
                except TimeoutError:
                    continue
                worker = threading.Thread(target=self._client, args=(conn,), daemon=True)
                worker.start()
        finally:
            server.close()
            self.socket_path.unlink(missing_ok=True)


class UnixWitnessAdapter:
    """Synthetic test adapter that pins the real server peer UID."""

    def __init__(self, socket_path: Path, *, witness_uid: int, operator_uid: int):
        self.socket_path = socket_path
        self.witness_uid = witness_uid
        self.operator_uid = operator_uid
        self.authority_identity = AUTHORITY_ID

    def _call(self, body: dict[str, Any]) -> dict[str, Any]:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(self.socket_path))
        peer = struct.unpack("3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
        if peer[1] != self.witness_uid:
            client.close()
            raise LedgerError("AUTHORITY_PEER_UID", "connected Unix server UID differs from the pinned synthetic Witness")
        client.sendall(canonical_json_bytes(body) + b"\n")
        response = bytearray()
        while len(response) <= 2 * 1024 * 1024:
            block = client.recv(65536)
            if not block:
                break
            response.extend(block)
            if b"\n" in block:
                break
        client.close()
        value = _json(bytes(response).split(b"\n", 1)[0])
        if value.get("ok") is not True:
            raise LedgerError(value.get("code", "WITNESS_REJECTED"), "synthetic Witness rejected the request")
        return value

    def read_current(self) -> WitnessSnapshot:
        return _typed_snapshot(self._call({"action": "read_current"})["snapshot"])

    def read_transition(self, transition_id: str) -> TransitionStatus | None:
        payload = self._call({"action": "read_transition", "transition_id": transition_id})["status"]
        if payload is None:
            return None
        prepared_data = payload.get("prepared")
        prepared = PreparedTransition(**prepared_data) if prepared_data else None
        return TransitionStatus(
            authority_identity=payload["authority_identity"],
            transition_id=payload["transition_id"], status=payload["status"],
            expected_sequence=payload["expected_sequence"],
            expected_state_digest=payload["expected_state_digest"],
            proposed_state_digest=payload["proposed_state_digest"],
            proposed_index_sha256=payload["proposed_index_sha256"], prepared=prepared,
        )

    @staticmethod
    def _proposal_wire(proposal: TransitionProposal) -> dict[str, Any]:
        return {
            "transition_id": proposal.transition_id,
            "expected_sequence": proposal.expected_sequence,
            "expected_state_digest": proposal.expected_state_digest,
            "previous_index_b64": base64.b64encode(proposal.previous_index_raw).decode("ascii"),
            "candidate_index_b64": base64.b64encode(proposal.candidate_index_raw).decode("ascii"),
            "proposed_state": proposal.proposed_state.payload(),
            "operation_purpose": proposal.operation_purpose,
            "actor_principal": proposal.actor_principal,
            "owner_approval_reference": proposal.owner_approval_reference,
        }

    def verify_transition_authorization(self, proposal: TransitionProposal) -> VerifiedTransitionAuthorization:
        result = self._call({"action": "verify_transition_authorization",
                             "proposal": self._proposal_wire(proposal)})["authorization"]
        return VerifiedTransitionAuthorization(**result)

    def prepare_transition(self, proposal: TransitionProposal) -> PreparedTransition:
        result = self._call({"action": "prepare_transition",
                             "proposal": self._proposal_wire(proposal)})["prepared"]
        return PreparedTransition(**result)

    def commit_transition(self, prepared: PreparedTransition) -> WitnessSnapshot:
        result = self._call({"action": "commit_transition",
                             "prepared": prepared.__dict__})["snapshot"]
        return _typed_snapshot(result)

    def abort_transition(self, prepared: PreparedTransition, *, reason_code: str) -> None:
        self._call({"action": "abort_transition", "prepared": prepared.__dict__,
                    "reason_code": reason_code})


def _initial_material() -> tuple[bytes, TrustState, dict[str, Any]]:
    index = {
        "index_version": "1.1", "controller_id": "hosted-controller",
        "policy_epoch": 1, "receipts": [], "authors": [], "adjudications": [],
        "qualification_runs": [], "qualification_corpus_intakes": [],
    }
    index_raw = canonical_json_bytes(index) + b"\n"
    state = TrustState(
        policy_identity="hosted-synthetic-policy", policy_epoch=1,
        profile_sha256=_sha(b"hosted-synthetic-profile"),
        build_inventory_sha256=_sha(b"hosted-synthetic-build"),
        controller_id="hosted-controller", generation_id="hosted-generation-0",
        index_sha256=_sha(index_raw), index_revision=0,
        revocation_state_sha256=_sha(b"hosted-synthetic-revocations"),
    )
    genesis = build_ledger_record(
        authority_identity=AUTHORITY_ID, sequence=0,
        previous_state_digest=None, previous_record_sha256=None, state=state,
        transition_id="hosted-genesis", operation_purpose="read_only_preflight",
        owner_approval_reference="synthetic-fixture-not-owner-approval",
        audit_timestamp=datetime.now(timezone.utc),
    )
    witness_state = {
        "authority_identity": AUTHORITY_ID,
        "records": [genesis], "pending": {}, "transitions": {},
        "lose_next_commit_ack": True,
        "approved_references": [APPROVAL_REF, OWNER_REF],
        "owner_policy_refs": [OWNER_REF],
    }
    return index_raw, state, witness_state


def _request(state: TrustState, operation_purpose: str) -> dict[str, Any]:
    return {
        "policy_identity": state.policy_identity,
        "policy_epoch": state.policy_epoch,
        "profile_sha256": state.profile_sha256,
        "build_inventory_sha256": state.build_inventory_sha256,
        "controller_id": state.controller_id,
        "generation_id": state.generation_id,
        "index_sha256": state.index_sha256,
        "revocation_state_sha256": state.revocation_state_sha256,
        "operation_purpose": operation_purpose,
    }


def _operator_gate_probe(args: argparse.Namespace, *, commit: bool) -> int:
    operator_uid = os.getuid()
    store = DirectoryProjectionStore(Path(args.operator_dir), operator_uid=operator_uid)
    authority = UnixWitnessAdapter(Path(args.socket), witness_uid=args.witness_uid,
                                   operator_uid=operator_uid)
    gate = MonotonicAntiRollbackGate(
        authority=authority, expected_authority_identity=AUTHORITY_ID,
        ledger_reader=store.read_ledger, index_reader=store.read_index,
        recovery_reader=store.recovery_required,
    )
    initial_index, initial_state, _ = _initial_material()
    before = gate.check_current_state(**_request(initial_state, "qualification_review"))
    result: dict[str, Any] = {
        "uid": os.getuid(), "euid": os.geteuid(), "gid": os.getgid(),
        "cap_effective": _process_capability("CapEff"),
        "cap_permitted": _process_capability("CapPrm"),
        "initial_gate_decision": before.decision,
        "initial_gate_error": before.error_code,
        "witness_peer_uid": args.witness_uid,
    }
    if commit:
        if before.decision != "verified":
            raise RuntimeError("synthetic Operator preflight did not verify initial state")
        old_index = store.read_index()
        index = _json(old_index)
        index["qualification_corpus_intakes"].append({
            "intake_id": "hosted-intake-1", "operation_id": "hosted-operation-1",
            "operator_principal": "synthetic-hosted-operator",
            "subject_inventory_key": "synthetic-corpus",
            "subject_sha256": _sha(b"synthetic-corpus"),
        })
        new_index = canonical_json_bytes(index) + b"\n"
        new_state = TrustState(
            policy_identity=initial_state.policy_identity,
            policy_epoch=initial_state.policy_epoch,
            profile_sha256=initial_state.profile_sha256,
            build_inventory_sha256=initial_state.build_inventory_sha256,
            controller_id=initial_state.controller_id,
            generation_id=initial_state.generation_id,
            index_sha256=_sha(new_index), index_revision=1,
            revocation_state_sha256=initial_state.revocation_state_sha256,
        )
        snapshot = authority.read_current()
        proposal = TransitionProposal(
            transition_id="hosted-transition-1",
            expected_sequence=snapshot.sequence,
            expected_state_digest=snapshot.head_state_digest,
            previous_index_raw=old_index,
            candidate_index_raw=new_index,
            proposed_state=new_state,
            operation_purpose="qualification_corpus_intake",
            actor_principal="synthetic-hosted-operator",
            owner_approval_reference=APPROVAL_REF,
        )
        coordinator = MonotonicTransitionCoordinator(
            authority=authority, authority_identity=AUTHORITY_ID, store=store,
        )
        try:
            coordinator.commit(proposal)
            raise RuntimeError("synthetic Witness did not drop the first commit acknowledgement")
        except LedgerError as exc:
            if exc.code != "RECOVERY_REQUIRED":
                raise
            first_failure_code = exc.code
        recovered = coordinator.recover(transition_id=proposal.transition_id)
        committed = coordinator.commit(proposal)
        if recovered.sequence != 1 or committed.sequence != recovered.sequence:
            raise RuntimeError("lost-ack recovery and idempotent retry did not return the exact committed state")
        result["lost_ack_recovery"] = {
            "uid": os.getuid(), "first_result": "RECOVERY_REQUIRED",
            "first_error_code": first_failure_code,
            "recovered_sequence": recovered.sequence,
            "retry_sequence": committed.sequence,
            "recovery_marker_cleared": not store.recovery_required(),
        }
        post = gate.check_current_state(**_request(new_state, "qualification_review"))
        if post.decision != "verified" or committed.sequence != 1:
            raise RuntimeError("synthetic post-commit Gate verification failed")
        result.update({
            "commit_sequence": committed.sequence,
            "commit_index_sha256": committed.state.index_sha256,
            "post_commit_gate_decision": post.decision,
            "post_commit_revision": post.verified_index_revision,
        })
        # Race two real Operator threads against one Authority revision. The
        # Authority CAS must admit exactly one transition; the loser remains
        # uncommitted and the resulting projection must still verify.
        race_snapshot = authority.read_current()
        race_base = _json(store.read_index())
        race_proposals: list[TransitionProposal] = []
        for number in (1, 2):
            race_index = deepcopy(race_base)
            race_index["qualification_corpus_intakes"].append({
                "intake_id": f"hosted-race-intake-{number}",
                "operation_id": f"hosted-race-operation-{number}",
                "operator_principal": "synthetic-hosted-operator",
                "subject_inventory_key": "synthetic-race-corpus",
                "subject_sha256": _sha(f"synthetic-race-{number}".encode()),
            })
            race_raw = canonical_json_bytes(race_index) + b"\n"
            race_state = TrustState(
                policy_identity=initial_state.policy_identity,
                policy_epoch=initial_state.policy_epoch,
                profile_sha256=initial_state.profile_sha256,
                build_inventory_sha256=initial_state.build_inventory_sha256,
                controller_id=initial_state.controller_id,
                generation_id=initial_state.generation_id,
                index_sha256=_sha(race_raw), index_revision=2,
                revocation_state_sha256=initial_state.revocation_state_sha256,
            )
            race_proposals.append(TransitionProposal(
                transition_id=f"hosted-race-transition-{number}",
                expected_sequence=race_snapshot.sequence,
                expected_state_digest=race_snapshot.head_state_digest,
                previous_index_raw=store.read_index(), candidate_index_raw=race_raw,
                proposed_state=race_state, operation_purpose="qualification_corpus_intake",
                actor_principal="synthetic-hosted-operator",
                owner_approval_reference=APPROVAL_REF,
            ))
        race_barrier = threading.Barrier(2)
        race_results: list[dict[str, Any]] = []
        race_lock = threading.Lock()

        def race_commit(proposal: TransitionProposal) -> None:
            race_barrier.wait(timeout=10)
            try:
                committed_snapshot = MonotonicTransitionCoordinator(
                    authority=authority, authority_identity=AUTHORITY_ID, store=store,
                ).commit(proposal)
                item = {"transition_id": proposal.transition_id, "result": "committed",
                        "sequence": committed_snapshot.sequence}
            except Exception as exc:
                item = {"transition_id": proposal.transition_id, "result": "rejected",
                        "error_code": getattr(exc, "code", type(exc).__name__)}
            with race_lock:
                race_results.append(item)

        race_threads = [threading.Thread(target=race_commit, args=(proposal,))
                        for proposal in race_proposals]
        for thread in race_threads:
            thread.start()
        for thread in race_threads:
            thread.join(timeout=20)
        if any(thread.is_alive() for thread in race_threads):
            raise TimeoutError("concurrent Authority CAS probe did not finish")
        after_race = authority.read_current()
        race_gate = gate.check_current_state(**_request(after_race.state, "qualification_review"))
        committed_races = [item for item in race_results if item["result"] == "committed"]
        rejected_races = [item for item in race_results if item["result"] == "rejected"]
        if (len(committed_races) != 1 or len(rejected_races) != 1
                or after_race.sequence != 2 or after_race.state.index_revision != 2
                or race_gate.decision != "verified" or store.recovery_required()):
            raise RuntimeError("concurrent same-revision CAS did not produce one clean committed winner")
        result["concurrent_same_revision_cas"] = {
            "uid": os.getuid(), "outcomes": sorted(race_results, key=lambda row: row["transition_id"]),
            "authority_sequence": after_race.sequence,
            "verified_index_revision": race_gate.verified_index_revision,
            "gate_decision": race_gate.decision,
            "recovery_required": store.recovery_required(),
        }
        # Rotate the synthetic Profile/Generation and revoke the old role
        # reference at a new epoch; the previously valid request must stop.
        old_state = after_race.state
        candidate_index = _json(store.read_index())
        candidate_index["policy_epoch"] = 2
        revoked_profile = {
            "policy_epoch": 2,
            "revoked_authority_ids": ["synthetic-hosted-operator-authority"],
            "roles": [{
                "principal_id": "synthetic-hosted-operator",
                "authorization_reference": "synthetic-hosted-operator-role-auth",
                "allowed_roles": ["qualification_corpus_custodian"],
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
                "revoked_at": "2026-10-11T00:00:00Z",
                "revocation_reason": "synthetic hosted revocation check",
            }],
        }
        revocation_sha, revoked_ids, revoked_role_refs = revocation_state(revoked_profile)
        candidate_index_raw = canonical_json_bytes(candidate_index) + b"\n"
        new_state = TrustState(
            policy_identity=old_state.policy_identity, policy_epoch=2,
            profile_sha256=_sha(canonical_json_bytes(revoked_profile)),
            build_inventory_sha256=old_state.build_inventory_sha256,
            controller_id=old_state.controller_id,
            generation_id="synthetic-generation-epoch-2",
            index_sha256=_sha(candidate_index_raw), index_revision=3,
            revocation_state_sha256=revocation_sha,
            revoked_authority_ids=revoked_ids,
            revoked_role_authorization_references=revoked_role_refs,
        )
        epoch_snapshot = authority.read_current()
        epoch_proposal = TransitionProposal(
            transition_id="hosted-epoch-transition-2",
            expected_sequence=epoch_snapshot.sequence,
            expected_state_digest=epoch_snapshot.head_state_digest,
            previous_index_raw=store.read_index(),
            candidate_index_raw=candidate_index_raw,
            proposed_state=new_state,
            operation_purpose="epoch_transition",
            actor_principal="synthetic-hosted-operator",
            owner_approval_reference=OWNER_REF,
        )
        epoch_committed = MonotonicTransitionCoordinator(
            authority=authority, authority_identity=AUTHORITY_ID, store=store,
        ).commit(epoch_proposal)
        stale_after_revocation = gate.check_current_state(**_request(old_state, "qualification_review"))
        current_after_revocation = gate.check_current_state(**_request(new_state, "qualification_review"))
        if (epoch_committed.sequence != 3 or stale_after_revocation.decision == "verified"
                or current_after_revocation.decision != "verified"):
            raise RuntimeError("old role authorization survived synthetic Epoch/revocation transition")
        result["epoch_and_revocation_transition"] = {
            "uid": os.getuid(), "sequence": epoch_committed.sequence,
            "epoch": epoch_committed.state.policy_epoch,
            "revoked_authority_ids": list(revoked_ids),
            "revoked_role_authorization_references": list(revoked_role_refs),
            "stale_old_request_decision": stale_after_revocation.decision,
            "stale_old_request_error": stale_after_revocation.error_code,
            "new_state_decision": current_after_revocation.decision,
            "new_state_revision": current_after_revocation.verified_index_revision,
        }
    else:
        result["rollback_gate_decision"] = before.decision
        result["rollback_gate_error"] = before.error_code
        if before.decision == "verified":
            store.close()
            print(json.dumps(result, sort_keys=True))
            return 1
    store.close()
    print(json.dumps(result, sort_keys=True))
    return 0


def _serve(args: argparse.Namespace) -> int:
    WitnessServer(state_path=Path(args.state_file), socket_path=Path(args.socket),
                  operator_uid=args.operator_uid, api_gid=args.api_gid).serve()
    return 0


def _demote(uid: int, gid: int, groups: list[int]):
    def demote_process() -> None:
        os.setgroups(groups)
        os.setgid(gid)
        os.setuid(uid)
    return demote_process


def _run_as(identity: pwd.struct_passwd, argv: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    groups = os.getgrouplist(identity.pw_name, identity.pw_gid)
    return subprocess.run(
        argv, cwd="/", env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False, close_fds=True,
        preexec_fn=_demote(identity.pw_uid, identity.pw_gid, groups),
    )


def _add_user(name: str) -> None:
    subprocess.run(["useradd", "--system", "--no-create-home", "--user-group",
                    "--shell", "/usr/sbin/nologin", name], check=True)


def _hosted_identity_names(token: str) -> tuple[str, dict[str, str]]:
    if len(token) != 14 or any(character not in "0123456789abcdef" for character in token):
        raise RuntimeError("synthetic hosted identity token must be 14 lowercase hex characters")
    prefix = f"rq03c3-{token}"
    api_group = f"{prefix}-api"
    role_names = {role: f"{prefix}-{role}" for role in
                  ("operator", "candidate", "author", "reviewer", "approver", "witness")}
    if max(len(api_group), *(len(name) for name in role_names.values())) > 32:
        raise RuntimeError("synthetic hosted identity name exceeds Linux login-name limit")
    return api_group, role_names


def _ensure_denied(label: str, action) -> dict[str, Any]:
    try:
        action()
    except (PermissionError, FileNotFoundError, ConnectionRefusedError) as exc:
        return {"check": label, "result": "denied", "exception": type(exc).__name__}
    except OSError as exc:
        if exc.errno in {1, 13, 2, 111}:
            return {"check": label, "result": "denied", "exception": type(exc).__name__}
        raise
    raise RuntimeError(f"negative filesystem/network test unexpectedly succeeded: {label}")


def _process_capability(name: str) -> str:
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if line.startswith(name + ":"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"Linux process status lacks {name}")


def _child_process_identity(pid: int) -> dict[str, Any]:
    fields: dict[str, str] = {}
    for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
        if line.startswith(("Uid:", "Gid:", "Groups:", "CapEff:", "CapPrm:")):
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    uids = [int(value) for value in fields["Uid"].split()]
    gids = [int(value) for value in fields["Gid"].split()]
    return {
        "pid": pid, "uid_real_effective_saved_fs": uids,
        "gid_real_effective_saved_fs": gids,
        "supplementary_groups": [int(value) for value in fields.get("Groups", "").split()],
        "cap_effective": fields.get("CapEff"), "cap_permitted": fields.get("CapPrm"),
    }


def _role_negative_probe(identity: pwd.struct_passwd, *, operator_dir: Path,
                         witness_file: Path, socket_path: Path,
                         env: dict[str, str], is_operator: bool) -> dict[str, Any]:
    role = identity.pw_name.rsplit("-", 1)[-1]
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "--role-negative-probe",
               "--operator-dir", str(operator_dir), "--witness-file", str(witness_file),
               "--socket", str(socket_path), "--role", role]
    completed = _run_as(identity, command, env=env)
    try:
        evidence = json.loads(completed.stdout.strip())
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"{role} negative probe did not produce structured evidence: {completed.stdout}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"{role} negative probe failed under UID {identity.pw_uid}: {completed.stdout}")
    if (evidence.get("uid") != identity.pw_uid or evidence.get("euid") != identity.pw_uid
            or len(evidence.get("checks", [])) < (2 if is_operator or role == "witness" else 4)
            or int(evidence.get("cap_effective", "-1"), 16) != 0
            or int(evidence.get("cap_permitted", "-1"), 16) != 0
            or any(check.get("result") != "denied" for check in evidence.get("checks", []))):
        raise RuntimeError(f"{role} negative probe did not prove each expected denial")
    return {"check": f"{role} real-UID negative probes", "exit_code": completed.returncode,
            "command": command, "evidence": evidence}


def _role_negative_probe_child(args: argparse.Namespace) -> int:
    role = args.role
    operator_dir, witness_file, socket_path = (Path(args.operator_dir),
                                                 Path(args.witness_file), Path(args.socket))
    evidence: dict[str, Any] = {"role": role, "uid": os.getuid(),
                                "euid": os.geteuid(), "gid": os.getgid(),
                                "cap_effective": _process_capability("CapEff"),
                                "cap_permitted": _process_capability("CapPrm"),
                                "privileged_fds_inherited": False,
                                "exit_code": 0, "checks": []}
    if role == "operator":
        evidence["checks"].append(_ensure_denied(
            "operator cannot directly read Witness history file",
            lambda: witness_file.read_bytes(),
        ))
        evidence["checks"].append(_ensure_denied(
            "operator cannot directly overwrite Witness history file",
            lambda: witness_file.write_bytes(b"candidate-forged"),
        ))
    else:
        evidence["checks"].append(_ensure_denied(
            f"{role} cannot read protected Operator Index",
            lambda: (operator_dir / "operation-index.json").read_bytes(),
        ))
        evidence["checks"].append(_ensure_denied(
            f"{role} cannot modify protected Operator Index",
            lambda: (operator_dir / "operation-index.json").write_bytes(b"forged"),
        ))
        if role != "witness":
            evidence["checks"].append(_ensure_denied(
                f"{role} cannot open the Operator-only Witness API",
                lambda: _connect_and_close(socket_path),
            ))
        if role in {"candidate", "author", "reviewer", "approver"}:
            evidence["checks"].append(_ensure_denied(
                f"{role} cannot read Witness history file",
                lambda: witness_file.read_bytes(),
            ))
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


def _connect_and_close(path: Path) -> None:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))
    finally:
        client.close()


def _acl_evidence(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        ["getfacl", "-cpn", "--", str(path)], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"could not inspect POSIX ACL for {path}: {completed.stdout.strip()}")
    entries = [line for line in completed.stdout.splitlines() if line]
    for entry in entries:
        if entry.startswith("default:") or entry.startswith("mask::"):
            raise RuntimeError(f"extended/default POSIX ACL is not permitted on {path}: {entry}")
        if entry.startswith("user:") and not entry.startswith("user::"):
            raise RuntimeError(f"named POSIX user ACL is not permitted on {path}: {entry}")
        if entry.startswith("group:") and not entry.startswith("group::"):
            raise RuntimeError(f"named POSIX group ACL is not permitted on {path}: {entry}")
    info = path.lstat()
    return {
        "path": str(path), "uid": info.st_uid, "gid": info.st_gid,
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "kind": stat.filemode(info.st_mode), "nlink": info.st_nlink,
        "posix_acl_entries": entries,
    }


def _launch_witness(*, script: Path, state_file: Path, socket_path: Path,
                    witness: pwd.struct_passwd, operator_uid: int,
                    api_gid: int) -> subprocess.Popen[str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/", "PYTHONUTF8": "1"}
    groups = os.getgrouplist(witness.pw_name, witness.pw_gid)
    return subprocess.Popen(
        [sys.executable, "-I", str(script), "--serve",
         "--state-file", str(state_file), "--socket", str(socket_path),
         "--operator-uid", str(operator_uid), "--api-gid", str(api_gid)],
        cwd="/", env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        close_fds=True, start_new_session=True,
        preexec_fn=_demote(witness.pw_uid, witness.pw_gid, groups),
    )


def _wait_socket(proc: subprocess.Popen[str], path: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(f"synthetic Witness exited before listen: {output}")
        if path.exists() and stat.S_ISSOCK(path.lstat().st_mode):
            return
        time.sleep(0.05)
    raise TimeoutError("synthetic Witness socket was not created")


def _run_root(args: argparse.Namespace) -> int:
    if os.geteuid() != 0 or not sys.platform.startswith("linux"):
        raise RuntimeError("hosted C3 isolation must run as root on disposable Linux")
    for _attempt in range(32):
        token = secrets.token_hex(7)
        prefix = f"rq03c3-{token}"
        api_group, role_names = _hosted_identity_names(token)
        base = Path("/var/lib") / f"rq03f-c3-hosted-{token}"
        users_or_groups_exist = any(
            subprocess.run(["getent", kind, name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL).returncode == 0
            for kind, names in (("passwd", role_names.values()),
                                ("group", [*role_names.values(), api_group]))
            for name in names
        )
        if not users_or_groups_exist and not base.exists() and not base.is_symlink():
            break
    else:
        raise RuntimeError("could not allocate collision-free temporary Linux identities and root")
    identities: dict[str, pwd.struct_passwd] = {}
    primary_groups: list[str] = []
    created_users: list[str] = []
    api_created = False
    base_created = False
    server: subprocess.Popen[str] | None = None
    report: dict[str, Any] = {
        "authority_status": "synthetic_hosted_only",
        "production_trust_established": False,
        "orchestrator_uid": os.getuid(), "orchestrator_euid": os.geteuid(),
        "invoker_uid": int(os.environ.get("SUDO_UID", os.getuid())),
        "roles": {}, "checks": [], "cleanup": {},
    }
    try:
        for name in role_names.values():
            _add_user(name)
            created_users.append(name)
            identities[name.rsplit("-", 1)[-1]] = pwd.getpwnam(name)
            primary_groups.append(name)
        subprocess.run(["groupadd", "--system", api_group], check=True)
        api_created = True
        subprocess.run(["usermod", "-a", "-G", api_group, role_names["operator"]], check=True)
        subprocess.run(["usermod", "-a", "-G", api_group, role_names["witness"]], check=True)

        operator = identities["operator"]
        witness = identities["witness"]
        api_gid = grp.getgrnam(api_group).gr_gid
        uid_values = [pwd.getpwnam(name).pw_uid for name in role_names.values()]
        if len(uid_values) != len(set(uid_values)):
            raise RuntimeError("temporary role UIDs are not unique")
        report["roles"] = {
            role: {"principal": role_names[role], "uid": pwd.getpwnam(role_names[role]).pw_uid,
                   "gid": pwd.getpwnam(role_names[role]).pw_gid}
            for role in role_names
        }

        base.mkdir(mode=0o711)
        base_created = True
        os.chown(base, 0, 0)
        os.chmod(base, 0o711)
        operator_dir = base / "operator-projection"
        operator_dir.mkdir(mode=0o700)
        os.chown(operator_dir, operator.pw_uid, operator.pw_gid)
        os.chmod(operator_dir, 0o700)
        witness_dir = base / "witness-state"
        witness_dir.mkdir(mode=0o700)
        os.chown(witness_dir, witness.pw_uid, witness.pw_gid)
        os.chmod(witness_dir, 0o700)
        socket_dir = base / "witness-api"
        socket_dir.mkdir(mode=0o710)
        os.chown(socket_dir, witness.pw_uid, api_gid)
        os.chmod(socket_dir, 0o710)
        socket_path = socket_dir / "high-water.sock"

        initial_index, initial_state, witness_state = _initial_material()
        initial_ledger = encode_ledger(AUTHORITY_ID, witness_state["records"])
        index_file = operator_dir / "operation-index.json"
        ledger_file = operator_dir / "ledger-projection.json"
        index_file.write_bytes(initial_index)
        ledger_file.write_bytes(initial_ledger)
        os.chown(index_file, operator.pw_uid, operator.pw_gid)
        os.chown(ledger_file, operator.pw_uid, operator.pw_gid)
        os.chmod(index_file, 0o600)
        os.chmod(ledger_file, 0o600)
        witness_file = witness_dir / "high-water-state.json"
        witness_file.write_bytes(canonical_json_bytes(witness_state) + b"\n")
        os.chown(witness_file, witness.pw_uid, witness.pw_gid)
        os.chmod(witness_file, 0o600)

        script = Path(__file__).resolve()
        server = _launch_witness(script=script, state_file=witness_file,
                                 socket_path=socket_path, witness=witness,
                                 operator_uid=operator.pw_uid, api_gid=api_gid)
        _wait_socket(server, socket_path)
        witness_process_identity = _child_process_identity(server.pid)
        if (witness_process_identity["uid_real_effective_saved_fs"] != [witness.pw_uid] * 4
                or int(witness_process_identity["cap_effective"] or "-1", 16) != 0
                or int(witness_process_identity["cap_permitted"] or "-1", 16) != 0):
            raise RuntimeError(f"Witness service did not run as the dedicated unprivileged UID: {witness_process_identity}")
        report["witness_process_identity"] = witness_process_identity
        report["filesystem_permissions"] = {
            "base": _acl_evidence(base),
            "operator_directory": _acl_evidence(operator_dir),
            "operator_index": _acl_evidence(index_file),
            "operator_ledger_projection": _acl_evidence(ledger_file),
            "witness_directory": _acl_evidence(witness_dir),
            "witness_state": _acl_evidence(witness_file),
            "witness_api_directory": _acl_evidence(socket_dir),
            "witness_api_socket": _acl_evidence(socket_path),
            "extended_acl_present": False,
        }
        expected_permissions = {
            "base": (0, 0, "0711"),
            "operator_directory": (operator.pw_uid, operator.pw_gid, "0700"),
            "operator_index": (operator.pw_uid, operator.pw_gid, "0600"),
            "operator_ledger_projection": (operator.pw_uid, operator.pw_gid, "0600"),
            "witness_directory": (witness.pw_uid, witness.pw_gid, "0700"),
            "witness_state": (witness.pw_uid, witness.pw_gid, "0600"),
            "witness_api_directory": (witness.pw_uid, api_gid, "0710"),
            "witness_api_socket": (witness.pw_uid, api_gid, "0660"),
        }
        for label, (expected_uid, expected_gid, expected_mode) in expected_permissions.items():
            evidence = report["filesystem_permissions"][label]
            if (evidence["uid"], evidence["gid"], evidence["mode"]) != (
                    expected_uid, expected_gid, expected_mode):
                raise RuntimeError(f"protected OS ownership/mode differs for {label}: {evidence}")
        safe_env = {"PATH": "/usr/bin:/bin", "HOME": "/", "PYTHONUTF8": "1"}
        operator_run = _run_as(
            operator,
            [sys.executable, "-I", str(script), "--operator-commit",
             "--operator-dir", str(operator_dir), "--socket", str(socket_path),
             "--witness-uid", str(witness.pw_uid)],
            env=safe_env,
        )
        try:
            operator_evidence = json.loads(operator_run.stdout.strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Operator process did not emit structured evidence: {operator_run.stdout}") from exc
        if (operator_evidence.get("uid") != operator.pw_uid
                or operator_evidence.get("euid") != operator.pw_uid
                or int(operator_evidence.get("cap_effective", "-1"), 16) != 0
                or int(operator_evidence.get("cap_permitted", "-1"), 16) != 0):
            raise RuntimeError(f"Operator subprocess did not drop privileged identity/capabilities: {operator_evidence}")
        report["checks"].append({"check": "Operator CAS commit through separate UID Witness",
                                 "uid": operator.pw_uid, "exit_code": operator_run.returncode,
                                 "process_identity": {key: operator_evidence[key] for key in
                                                      ("uid", "euid", "gid", "cap_effective", "cap_permitted")},
                                 "privileged_fds_inherited": False,
                                 "output": operator_run.stdout.strip()})
        if operator_run.returncode != 0:
            raise RuntimeError("Operator synthetic C3 CAS transition failed")

        # The Operator can change its own projection, but it cannot mutate the
        # independently owned Witness high-water state.
        report["checks"].append(_role_negative_probe(
            operator, operator_dir=operator_dir, witness_file=witness_file,
            socket_path=socket_path, env=safe_env, is_operator=True,
        ))
        for role in ("candidate", "author", "reviewer", "approver"):
            report["checks"].append(_role_negative_probe(
                identities[role], operator_dir=operator_dir, witness_file=witness_file,
                socket_path=socket_path, env=safe_env, is_operator=False,
            ))
        report["checks"].append(_role_negative_probe(
            identities["witness"], operator_dir=operator_dir, witness_file=witness_file,
            socket_path=socket_path, env=safe_env, is_operator=False,
        ))

        # Make a candidate-owned import shadow and pass it through PYTHONPATH.
        # Isolated Python plus the Owner-controlled installed script path must
        # keep the loaded C3 module inside the pinned checkout copy.
        shadow = base / "candidate-python-shadow"
        shadow.mkdir(mode=0o755)
        os.chown(shadow, identities["candidate"].pw_uid, identities["candidate"].pw_gid)
        os.chmod(shadow, 0o755)
        fake_module = shadow / "rq03f_monotonic_trust_ledger.py"
        fake_module.write_text("raise RuntimeError('candidate module shadow loaded')\n", encoding="utf-8")
        os.chown(fake_module, identities["candidate"].pw_uid, identities["candidate"].pw_gid)
        os.chmod(fake_module, 0o644)
        shadow_env = dict(safe_env, PYTHONPATH=str(shadow))
        shadow_run = _run_as(
            operator,
            [sys.executable, "-I", str(script), "--import-path-probe",
             "--shadow", str(shadow)], env=shadow_env,
        )
        report["checks"].append({"check": "candidate PYTHONPATH/module shadow rejected by isolated import",
                                 "uid": operator.pw_uid, "exit_code": shadow_run.returncode,
                                 "output": shadow_run.stdout.strip()})
        if shadow_run.returncode != 0:
            raise RuntimeError("isolated C3 import-path check failed")

        # Simulate restoring every Operator projection byte from an old backup.
        # The Witness UID's independent sequence remains at three after the
        # intake commit, one-winner CAS race, and epoch/revocation transition.
        index_file.write_bytes(initial_index)
        ledger_file.write_bytes(initial_ledger)
        os.chown(index_file, operator.pw_uid, operator.pw_gid)
        os.chown(ledger_file, operator.pw_uid, operator.pw_gid)
        os.chmod(index_file, 0o600)
        os.chmod(ledger_file, 0o600)
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=10)
        server_output = server.stdout.read() if server.stdout else ""
        if server.returncode not in (0, -signal.SIGTERM):
            report["checks"].append({"check": "Witness first shutdown", "exit_code": server.returncode,
                                     "output": server_output.strip()})
            raise RuntimeError("synthetic Witness failed to stop cleanly")
        server = _launch_witness(script=script, state_file=witness_file,
                                 socket_path=socket_path, witness=witness,
                                 operator_uid=operator.pw_uid, api_gid=api_gid)
        _wait_socket(server, socket_path)
        rollback_run = _run_as(
            operator,
            [sys.executable, "-I", str(script), "--operator-rollback-probe",
             "--operator-dir", str(operator_dir), "--socket", str(socket_path),
             "--witness-uid", str(witness.pw_uid)],
            env=safe_env,
        )
        report["checks"].append({"check": "old complete Operator snapshot rejected after Witness process restart",
                                 "uid": operator.pw_uid, "exit_code": rollback_run.returncode,
                                 "output": rollback_run.stdout.strip()})
        if rollback_run.returncode != 0:
            raise RuntimeError("old Operator snapshot was accepted or rollback probe failed")

        # Authority is unavailable => no verified Gate result.
        server.send_signal(signal.SIGTERM)
        server.wait(timeout=10)
        unavailable_run = _run_as(
            operator,
            [sys.executable, "-I", str(script), "--authority-unavailable-probe",
             "--operator-dir", str(operator_dir), "--socket", str(socket_path),
             "--witness-uid", str(witness.pw_uid)],
            env=safe_env,
        )
        report["checks"].append({"check": "missing Witness fails closed",
                                 "uid": operator.pw_uid, "exit_code": unavailable_run.returncode,
                                 "output": unavailable_run.stdout.strip()})
        if unavailable_run.returncode != 0:
            raise RuntimeError("missing-Witness fail-closed probe failed")
        report["hosted_os_isolation_pass"] = True
        report["synthetic_witness_sequence_after_operator_restore"] = 3
        report["witness_state_owner_uid"] = witness.pw_uid
        report["operator_could_not_directly_write_witness"] = True
        report["candidate_author_reviewer_approver_denied"] = True
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
    finally:
        if server is not None and server.poll() is None:
            server.send_signal(signal.SIGTERM)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        report["cleanup"]["server_stopped"] = server is None or server.poll() is not None
        for name in created_users:
            if subprocess.run(["getent", "passwd", name], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0:
                removed = subprocess.run(["userdel", "-f", name], check=False,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if removed.returncode != 0:
                    report["cleanup"][f"userdel_{name}"] = removed.stdout.strip()
        if api_created:
            subprocess.run(["groupdel", api_group], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for name in primary_groups:
            if subprocess.run(["getent", "group", name], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0:
                subprocess.run(["groupdel", name], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if base_created and (base.exists() or base.is_symlink()):
            try:
                shutil.rmtree(base, ignore_errors=False)
            except OSError as exc:
                report["cleanup"]["temporary_root_removal_error"] = f"{type(exc).__name__}: {exc}"
        leftovers = [name for name in created_users
                     if subprocess.run(["getent", "passwd", name], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL).returncode == 0]
        group_names = [*primary_groups, api_group]
        remaining_groups = [name for name in group_names
                            if subprocess.run(["getent", "group", name], stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL).returncode == 0]
        report["cleanup"]["remaining_users"] = leftovers
        report["cleanup"]["remaining_groups"] = remaining_groups
        report["cleanup"]["temporary_root_removed"] = not base.exists()
        report["cleanup"]["pass"] = (not leftovers and not remaining_groups and not base.exists()
                                      and report["cleanup"]["server_stopped"])
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report.get("hosted_os_isolation_pass") and report["cleanup"]["pass"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--root-test", action="store_true")
    parser.add_argument("--operator-commit", action="store_true")
    parser.add_argument("--operator-rollback-probe", action="store_true")
    parser.add_argument("--role-negative-probe", action="store_true")
    parser.add_argument("--authority-unavailable-probe", action="store_true")
    parser.add_argument("--import-path-probe", action="store_true")
    parser.add_argument("--state-file")
    parser.add_argument("--socket")
    parser.add_argument("--operator-dir")
    parser.add_argument("--shadow")
    parser.add_argument("--witness-file")
    parser.add_argument("--role")
    parser.add_argument("--operator-uid", type=int)
    parser.add_argument("--witness-uid", type=int)
    parser.add_argument("--api-gid", type=int)
    args = parser.parse_args()
    if args.serve:
        return _serve(args)
    if args.operator_commit:
        return _operator_gate_probe(args, commit=True)
    if args.operator_rollback_probe:
        result = _operator_gate_probe(args, commit=False)
        # The expected result is a denial by the independent post-restart
        # witness. Report its typed Gate evidence and return success only when
        # the stale projection is rejected.
        return result
    if args.role_negative_probe:
        return _role_negative_probe_child(args)
    if args.authority_unavailable_probe:
        operator_uid = os.getuid()
        store = DirectoryProjectionStore(Path(args.operator_dir), operator_uid=operator_uid)
        authority = UnixWitnessAdapter(Path(args.socket), witness_uid=args.witness_uid,
                                       operator_uid=operator_uid)
        gate = MonotonicAntiRollbackGate(
            authority=authority, expected_authority_identity=AUTHORITY_ID,
            ledger_reader=store.read_ledger, index_reader=store.read_index,
            recovery_reader=store.recovery_required,
        )
        _index, initial_state, _doc = _initial_material()
        result = gate.check_current_state(**_request(initial_state, "qualification_review"))
        store.close()
        print(json.dumps({"uid": os.getuid(), "decision": result.decision,
                          "error_code": result.error_code}, sort_keys=True))
        return 0 if result.decision != "verified" else 1
    if args.import_path_probe:
        import rq03f_monotonic_trust_ledger as loaded
        origin = Path(loaded.__file__).resolve()
        trusted = origin.is_relative_to(SCRIPTS.resolve())
        fake = Path(args.shadow) / "rq03f_monotonic_trust_ledger.py"
        print(json.dumps({"uid": os.getuid(), "module_origin": str(origin),
                          "candidate_shadow_exists": fake.is_file(), "trusted_origin": trusted}, sort_keys=True))
        return 0 if trusted and fake.is_file() else 1
    if args.root_test:
        return _run_root(args)
    parser.error("select one hosted C3 execution mode")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
