"""Synthetic B3 entrypoint installed only on the disposable hosted runner.

The fixed context path and entrypoint are part of the temporary Owner-only
launcher. This file is never installed into, or used by, the formal Trust
Anchor. The GH workflow must report this test as hosted-only evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import attr
import attrs
import exemplar_contract
import exemplar_split
from lifecycle_digest import sha256_bytes
import operation_provenance
from qualification_corpus_intake import (
    FROZEN_GOLDEN_SHA256,
    FROZEN_HOLDOUT_SHA256,
    capture_qualification_corpus_intake,
    validate_qualification_corpus_intake,
)
import jsonschema
import jsonschema_specifications
import path_safety
import referencing
import reviewer_qualification
import rpds
import semantic_scope_review
from semantic_scope_records import Inventory, RecordError, TrustContext
import source_truth
import typing_extensions


CONTEXT_PATH = Path(
    "/var/lib/rq03f-operator/rq03f-b3-data/operator/trust/b3-context.json"
)


def _context(payload: dict) -> TrustContext:
    inventory = Inventory(
        payload["entries"],
        Path(payload["run_root"]),
        tuple(Path(root) for root in payload["protected_roots"]),
    )
    return TrustContext(
        inventory,
        Path(payload["profile_path"]),
        payload["profile_sha256"],
        payload["policy_epoch"],
        Path(payload["operation_index_path"]),
        tuple(tuple(row) for row in payload["controller_allowlist"]),
        datetime.now(timezone.utc),
        operator_principal=payload["operator_principal"],
        operator_unix_uid=payload["operator_unix_uid"],
        non_operator_process_unix_uids=tuple(payload["non_operator_process_unix_uids"]),
    )


def _wait_for_test_barrier() -> None:
    barrier = os.environ.get("RQ03F_B3_RELEASE_BARRIER")
    ready = os.environ.get("RQ03F_B3_READY_FILE")
    if not barrier and not ready:
        return
    if not barrier or not ready:
        raise RecordError("B3 concurrency barrier configuration is incomplete")
    ready_path = Path(ready)
    fd = os.open(ready_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(f"uid={os.geteuid()}\n")
        stream.flush()
        os.fsync(stream.fileno())
    deadline = time.monotonic() + 20
    while not Path(barrier).exists():
        if time.monotonic() >= deadline:
            raise RecordError("B3 concurrency barrier timed out")
        time.sleep(0.02)


def _persist_refreshed_inventory(payload: dict) -> None:
    """Refresh only the synthetic harness's external Index byte binding."""
    parent = CONTEXT_PATH.parent
    fd, tmp_name = tempfile.mkstemp(prefix=".b3-context-", suffix=".tmp", dir=parent)
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_path, CONTEXT_PATH)
        dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def capture() -> None:
    """Capture and validate one present-custody intake as the real Operator UID."""
    if os.name != "posix" or not hasattr(os, "geteuid"):
        raise RecordError("B3 hosted Operator capture requires POSIX effective-UID support")
    raw_context = CONTEXT_PATH.read_bytes()
    payload = json.loads(raw_context.decode("utf-8"))
    context = _context(payload)
    profile, index_before = context.load()
    if os.geteuid() != profile["operator_unix_uid"]:
        raise RecordError("B3 hosted probe is not running as the pinned Operator UID")
    if index_before["authors"]:
        raise RecordError("synthetic initial index unexpectedly contains author rows")
    _wait_for_test_barrier()

    result = capture_qualification_corpus_intake(context)
    index_raw = context.operation_index_path.read_bytes()
    index_after = json.loads(index_raw.decode("utf-8"))
    intake_raw = Path(result["path"]).read_bytes()
    intake_payload = json.loads(intake_raw.decode("utf-8"))
    if index_after["authors"] != index_before["authors"]:
        raise RecordError("qualification intake modified historical authors")
    if len(index_after["qualification_corpus_intakes"]) != len(
        index_before["qualification_corpus_intakes"]
    ) + 1:
        raise RecordError("expected exactly one protected qualification-only intake append")
    for field in ("receipts", "authors", "adjudications", "qualification_runs"):
        if index_after[field] != index_before[field]:
            raise RecordError(f"qualification intake modified existing {field}")
    n01 = next(
        row for row in intake_payload["cases"]
        if row["content"]["sha256"]
        == "878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352"
    )

    entries = {key: dict(row) for key, row in payload["entries"].items()}
    entries["operation_index"]["sha256"] = sha256_bytes(index_raw)
    entries[result["inventory_key"]] = {
        "inventory_key": result["inventory_key"],
        "path": result["path"],
        "sha256": result["sha256"],
        "storage_class": "protected_external",
    }
    payload["entries"] = entries
    updated_context = _context(payload)
    intake = validate_qualification_corpus_intake(
        updated_context,
        result["inventory_key"],
        result["sha256"],
        content_sha256="878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352",
        authoring_id=n01["authoring_id"],
        reviewer_principal="managed-agent:scope-reviewer-a",
        reviewer_operation_id="b3-synthetic-review-operation",
        reviewed_at=result["recorded_at"],
    )
    if len(intake["cases"]) != 17:
        raise RecordError("B3 intake does not contain all 17 frozen qualification cases")
    if intake["qualification_corpus"]["sha256"] != FROZEN_GOLDEN_SHA256:
        raise RecordError("B3 intake Golden Corpus bytes differ from the frozen SHA")
    if intake["blind_holdout_truth"]["sha256"] != FROZEN_HOLDOUT_SHA256:
        raise RecordError("B3 intake Blind Holdout bytes differ from the frozen SHA")
    if intake["historical_author_claim"] != "not_made" or intake["intake_is_historical_authoring_operation"]:
        raise RecordError("intake asserted historical authoring provenance")
    if "authors" in intake:
        raise RecordError("intake artifact contains a historical authors collection")
    _persist_refreshed_inventory(payload)

    module_paths = {
        name: str(Path(sys.modules[name].__file__).resolve(strict=True))
        for name in (
            "semantic_scope_records",
            "qualification_corpus_intake",
            "operator_controller_bootstrap",
            "lifecycle_digest",
        )
    }
    safe_result = {
        "result": "OPERATOR_INTAKE_PASS",
        "effective_uid": os.geteuid(),
        "real_uid": os.getuid(),
        "operator_principal": result["operator_principal"],
        "intake_id": result["intake_id"],
        "operation_id": result["operation_id"],
        "intake_sha256": result["sha256"],
        "index_sha256": result["operation_index_sha256"],
        "author_rows_before": len(index_before["authors"]),
        "author_rows_after": len(index_after["authors"]),
        "qualification_intake_rows_after": len(index_after["qualification_corpus_intakes"]),
        "frozen_case_count": len(intake["cases"]),
        "golden_corpus_sha256": intake["qualification_corpus"]["sha256"],
        "blind_holdout_sha256": intake["blind_holdout_truth"]["sha256"],
        "original_nc02_content_sha256": n01["content"]["sha256"],
        "historical_author_claim": intake["historical_author_claim"],
        "controller_modules": module_paths,
        "provider_truth_or_golden_labels_emitted": False,
    }
    print(json.dumps(safe_result, sort_keys=True))
    return None


if __name__ == "__main__":
    try:
        capture()
    except (OSError, KeyError, TypeError, ValueError, RecordError) as exc:
        print(f"B3 hosted Operator probe blocked: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
