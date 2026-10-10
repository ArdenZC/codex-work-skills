"""Qualification-only present-custody intake for the frozen RQ-03F corpus.

This module never writes historical author rows. Intake capture is an external
operator operation requiring a dedicated custodian role and a distinct OS UID.
The current repository checkout and candidate metadata cannot supply that trust.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping
import uuid

from lifecycle_digest import canonical_json_bytes, sha256_bytes, sha256_file
from semantic_scope_records import RecordError, TrustContext, checked, parse, require, stamp


FROZEN_GOLDEN_SHA256 = "96f5044f8b009d77c386e8acb414dface173bd5738354ae740d2361e0e52561a"
FROZEN_HOLDOUT_SHA256 = "268e95379a15e0c4a848332e8b3a33618d05cb889991730e23ff8e693a59b57a"
ORIGINAL_NC02_SHA256 = "878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352"

FROZEN_GOLDEN_CASE_IDS = (
    "N01", "N02", "N03", "N04", "N05", "N06",
    "P07", "P08", "P09", "P10", "P11", "P12", "A13", "P14",
)
FROZEN_HOLDOUT_CASE_IDS = ("H01", "H02", "H03")
FROZEN_CASE_CONTENT_SHA256 = {
    "N01": ORIGINAL_NC02_SHA256,
    "N02": "1151b44b2be3e43530f7ca47178aa92d30366e96673c10fc68deb2c7375916a7",
    "N03": "e02c519ebb837790760bd76b62667605a7c2916c7f561ba4ec120c195e0331e2",
    "N04": "47094b26a926afc0ae2761109f1814a00f7ceb0bb222684a8ba6e93b266f597c",
    "N05": "57a6efee6021248ded80d831564f5287c1315231cc08759e9f9d6ab223a3e2a1",
    "N06": "f491c68aeda4bdfa5430ab5c024327da181726fcfd1e835eeafa8ca813dc218b",
    "P07": "6b21514f15c4e0b287f3a999dd475604b7d0f1f94f7d3b669433adf952be7fa3",
    "P08": "be75ec999322fc7985dcbd6cb7692d2bbe3bac0499e27fd5bc8cf879a260e867",
    "P09": "9da74d20e240e77ec207ca6a5fadc539c409dbaac16bf6d99f6cdd9ee02583a5",
    "P10": "dd6e94df2a37c3fbfe0f29c873496e272498ab4c67ec557ae62c1591e26eb5ae",
    "P11": "769d72f7adbae5e617ac2c9a2a504b658a142d40304d535ef04d34766e8f6512",
    "P12": "06ca333e97f9ad40e44d9e7b13a5dfa9b31d44986da43209d503fe1145738a2c",
    "A13": "6438cdd391f5a2482e62b3be5e821daa860b09664aa0fb1b0f149d5e4786ab92",
    "P14": "c2163bbbd0d0d3f7cf65275185cda051a488c872fb2e3a8b798e05e135008000",
    "H01": "4cc354b058a6a0dc79eeff0907863594030eddbb2c50e294e3a8db6a444b8924",
    "H02": "f31c794c2f624f5e8cc7154f30fb3dcb69ec25378e94bd92c55b3fba5c159d41",
    "H03": "85f75c14e687737fc95e5cec89f5ad67c5e977d49e6d4112dc0f2d3bead7b113",
}
FROZEN_AUTHORING_IDS = {
    case_id: (
        "synthetic-fixture-contract-test" if case_id == "N01"
        else f"semantic-case-{case_id}"
    )
    for case_id in FROZEN_CASE_CONTENT_SHA256
}


def _binding(row: Mapping[str, Any]) -> dict[str, str]:
    return {"inventory_key": row["inventory_key"], "sha256": row["sha256"]}


def _schema_payload(raw: bytes, name: str) -> dict[str, Any]:
    value = checked(raw, name)
    require(raw.strip().startswith(b"{"), f"{name} must be a JSON object")
    return value


def _frozen_json_payload(raw: bytes, name: str) -> dict[str, Any]:
    """Parse hash-pinned corpus bytes without the contract parser's no-float rule."""
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key in frozen {name}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                RecordError(f"non-finite JSON number in frozen {name}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecordError(f"invalid frozen {name} JSON bytes: {exc}") from exc
    require(isinstance(value, dict), f"frozen {name} must be a JSON object")
    return value


def _frozen_manifests(context: TrustContext, corpus_key: str, holdout_key: str):
    inventory = context.inventory
    corpus_raw = inventory.raw(corpus_key, protected=True)
    holdout_raw = inventory.raw(holdout_key, protected=True)
    require(sha256_bytes(corpus_raw) == FROZEN_GOLDEN_SHA256, "frozen golden corpus SHA mismatch")
    require(sha256_bytes(holdout_raw) == FROZEN_HOLDOUT_SHA256, "frozen blind holdout SHA mismatch")
    corpus = _schema_payload(corpus_raw, "qualification-corpus")
    holdout = _schema_payload(holdout_raw, "qualification-corpus")
    require(
        [row["case_id"] for row in corpus["cases"]] == list(FROZEN_GOLDEN_CASE_IDS),
        "frozen golden case IDs/order changed",
    )
    require(
        [row["case_id"] for row in holdout["cases"]] == list(FROZEN_HOLDOUT_CASE_IDS),
        "frozen holdout case IDs/order changed",
    )
    require(
        set(FROZEN_CASE_CONTENT_SHA256)
        == {row["case_id"] for row in corpus["cases"] + holdout["cases"]},
        "frozen 17-case coverage changed",
    )
    require(
        not ({row["case_id"] for row in corpus["cases"]}
             & {row["case_id"] for row in holdout["cases"]}),
        "frozen golden/holdout cases overlap",
    )
    return corpus_raw, corpus, holdout_raw, holdout


def _bound_protected_raw(inventory, binding: Mapping[str, str]) -> bytes:
    """Resolve a full-inventory key or a case namespace alias by exact SHA."""
    key = binding["inventory_key"]
    digest = binding["sha256"]
    if key in inventory.entries:
        return inventory.raw(key, digest, protected=True)
    # Per-case validation namespaces replace that case's original input keys
    # with `content`, `outline` and `source_truth_manifest`; SHA lookup keeps
    # full-corpus intake verification possible without widening reviewer input.
    return inventory.by_sha(digest, protected=True)


def _check_case_bytes(context: TrustContext, corpus: dict[str, Any], holdout: dict[str, Any]):
    inventory = context.inventory
    rows: list[dict[str, Any]] = []
    for cohort, manifest in (("golden", corpus), ("blind_holdout", holdout)):
        for case in manifest["cases"]:
            case_id = case["case_id"]
            content_binding = case["inputs"]["content"]
            require(
                content_binding["sha256"] == FROZEN_CASE_CONTENT_SHA256[case_id],
                f"frozen {case_id} Content SHA declaration changed",
            )
            content_raw = _bound_protected_raw(inventory, content_binding)
            content = _frozen_json_payload(content_raw, f"{case_id} Content")
            authoring_id = content["authoring_provenance"]["authoring_id"]
            require(
                authoring_id == FROZEN_AUTHORING_IDS[case_id],
                f"frozen {case_id} authoring_id changed",
            )
            if case_id == "N01":
                require(sha256_bytes(content_raw) == ORIGINAL_NC02_SHA256,
                        "original NC-02 bytes changed")
            source_manifest = case["inputs"]["source_truth_manifest"]
            outline = case["inputs"]["outline"]
            _bound_protected_raw(inventory, source_manifest)
            _bound_protected_raw(inventory, outline)
            sources = case["inputs"]["sources"]
            require(bool(sources), f"frozen {case_id} source closure is empty")
            for source in sources:
                _bound_protected_raw(inventory, source)
            rows.append({
                "case_id": case_id,
                "cohort": cohort,
                "content": _binding(content_binding),
                "authoring_id": authoring_id,
                "source_truth_manifest": _binding(source_manifest),
                "outline": _binding(outline),
                "sources": [_binding(source) for source in sources],
            })
    return rows


def _profile_and_custodian(context: TrustContext):
    profile, index = context.load()
    require(profile["profile_version"] == "1.1", "Qualification Corpus Intake requires Operator Profile 1.1")
    require(index["index_version"] == "1.1", "Qualification Corpus Intake requires Protected Operation Index 1.1")
    require(context.operator_principal, "external Operator principal is not provisioned")
    require(context.operator_unix_uid is not None, "external Operator UID is not provisioned")
    require(context.non_operator_process_unix_uids, "non-Operator process UIDs are not provisioned")
    require(
        context.operator_unix_uid not in set(context.non_operator_process_unix_uids),
        "Operator and candidate process UIDs must differ",
    )
    require(
        os.geteuid() == os.getuid() == context.operator_unix_uid,
        "intake capture must run as the externally provisioned Operator UID",
    )
    roles = [row for row in profile["roles"] if row["principal_id"] == context.operator_principal]
    require(len(roles) == 1, "missing/duplicate Qualification Corpus Custodian principal")
    role = context.role(context.operator_principal, "qualification_corpus_custodian")
    require(
        role["allowed_roles"] == ["qualification_corpus_custodian"],
        "custodian principal has authority outside qualification-only intake",
    )
    auth_raw = context.inventory.raw(role["authorization_reference"], protected=True)
    auth = checked(auth_raw, "operator-role-authorization-v1.1")
    require(auth["allowed_roles"] == ["qualification_corpus_custodian"],
            "intake authorization is not least-privilege")
    root = Path(context.operation_index_path).resolve(strict=True).parent
    require(Path(context.profile_path).resolve(strict=True).parent == root,
            "authority profile and index must share the protected operator root")
    expected_uid = context.operator_unix_uid
    for path in (root, context.profile_path, context.operation_index_path):
        info = path.stat(follow_symlinks=False)
        require(stat.S_ISDIR(info.st_mode) if path == root else stat.S_ISREG(info.st_mode),
                "protected operator inputs must be ordinary filesystem objects")
        require(info.st_uid == expected_uid, "protected operator root/profile/index owner mismatch")
        require(not (info.st_mode & 0o022), "protected operator root/profile/index is group/world writable")
    require(context.operation_index_path.stat().st_mode & stat.S_IWUSR,
            "Operator index is not writable by its owner")
    return profile, index, role, sha256_bytes(auth_raw), root


def _assert_protected_root_owner(context: TrustContext, intake: Mapping[str, Any]) -> Path:
    root = Path(context.operation_index_path).resolve(strict=True).parent
    require(Path(context.profile_path).resolve(strict=True).parent == root,
            "authority profile and index must share the protected operator root")
    expected_uid = intake["operator_unix_uid"]
    require(
        context.operator_unix_uid == expected_uid
        == intake["protected_repository_owner_unix_uid"],
        "intake OS writer identity is not the external TrustContext owner",
    )
    for path in (root, context.profile_path, context.operation_index_path):
        info = path.stat(follow_symlinks=False)
        require(stat.S_ISDIR(info.st_mode) if path == root else stat.S_ISREG(info.st_mode),
                "protected operator inputs must be ordinary filesystem objects")
        require(info.st_uid == expected_uid,
                "protected operator root/profile/index owner mismatch")
        require(not (info.st_mode & 0o022),
                "protected operator root/profile/index is group/world writable")
    return root


def _case_rows(context: TrustContext, corpus: dict[str, Any], holdout: dict[str, Any], origins):
    rows = _check_case_bytes(context, corpus, holdout)
    origins = origins or {}
    require(set(origins).issubset(FROZEN_CASE_CONTENT_SHA256), "unknown Git-origin case")
    for row in rows:
        origin = origins.get(row["case_id"])
        if origin is not None:
            row["origin"] = {
                "origin_metadata_only": True,
                "git_commit": origin["git_commit"],
                "content_path": origin["content_path"],
            }
        else:
            row["origin"] = None
    return rows


def append_intake_index(index: Mapping[str, Any], row: Mapping[str, Any]) -> bytes:
    """Return the canonical Index 1.1 append, preserving all existing entries."""
    require(index.get("index_version") == "1.1",
            "qualification corpus intake requires Protected Operation Index 1.1")
    intake_rows = index["qualification_corpus_intakes"]
    require(not any(item["intake_id"] == row["intake_id"] for item in intake_rows),
            "duplicate qualification corpus intake ID")
    old_operations = {
        item["operation_id"]
        for field in ("receipts", "authors", "adjudications", "qualification_corpus_intakes")
        for item in index[field]
    }
    require(row["operation_id"] not in old_operations,
            "duplicate protected operation ID")
    new_index = deepcopy(index)
    new_index["qualification_corpus_intakes"].append(dict(row))
    for field in ("receipts", "authors", "adjudications", "qualification_runs"):
        require(new_index[field] == index[field], f"intake must not modify existing {field}")
    raw = canonical_json_bytes(new_index)
    checked(raw, "protected-operation-index-v1.1")
    return raw


def capture_qualification_corpus_intake(
    context: TrustContext,
    *,
    git_origins: Mapping[str, Mapping[str, str]] | None = None,
    corpus_key: str = "qualification_corpus",
    holdout_key: str = "blind_holdout_truth",
) -> dict[str, Any]:
    """Perform one protected operator intake and append exactly one Index 1.1 row.

    The caller must be the separately installed, allowlisted operator controller.
    This function refuses candidate execution, absent operator policy, shared UIDs,
    non-protected inputs, an Index 1.0 trust root, duplicate IDs, and writable
    group/world trust paths. It does not write to the repository Git branch.
    """
    profile, index, role, auth_sha, root = _profile_and_custodian(context)
    lock_path = root / ".qualification-corpus-intake.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Reload under the lock so a concurrent capture cannot reuse IDs or drop rows.
        profile, index, role, auth_sha, root = _profile_and_custodian(context)
        corpus_raw, corpus, holdout_raw, holdout = _frozen_manifests(
            context, corpus_key, holdout_key
        )
        cases = _case_rows(context, corpus, holdout, git_origins)
        ids = {row["intake_id"] for row in index["qualification_corpus_intakes"]}
        operations = {
            row["operation_id"]
            for group in ("receipts", "authors", "adjudications", "qualification_corpus_intakes")
            for row in index[group]
        }
        while True:
            intake_id = "qci-" + uuid.uuid4().hex
            operation_id = "qci-op-" + uuid.uuid4().hex
            if intake_id not in ids and operation_id not in operations:
                break
        recorded_at = context.now.astimezone(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        intake = {
            "intake_version": "1.0",
            "intake_id": intake_id,
            "operation_id": operation_id,
            "controller_id": profile["controller_id"],
            "operator_principal": context.operator_principal,
            "operator_authorization_reference": role["authorization_reference"],
            "operator_authorization_sha256": auth_sha,
            "authority_profile_sha256": context.profile_pin,
            "controller_build_inventory_sha256": profile["controller_build_inventory_sha256"],
            "policy_epoch": context.policy_epoch,
            "operator_identity_basis": "dedicated_os_account_option_b",
            "operator_unix_uid": os.geteuid(),
            "protected_repository_owner_unix_uid": root.stat().st_uid,
            "qualification_corpus": {
                **_binding(context.inventory.entries[corpus_key]),
                "corpus_contract_version": corpus["corpus_contract_version"],
                "corpus_id": corpus["corpus_id"],
                "corpus_version": corpus["corpus_version"],
            },
            "blind_holdout_truth": {
                **_binding(context.inventory.entries[holdout_key]),
                "corpus_contract_version": holdout["corpus_contract_version"],
                "corpus_id": holdout["corpus_id"],
                "corpus_version": holdout["corpus_version"],
            },
            "cases": cases,
            "purpose": "qualification_only",
            "historical_author_claim": "not_made",
            "intake_is_historical_authoring_operation": False,
            "recorded_at": recorded_at,
        }
        del corpus_raw, holdout_raw
        intake_raw = canonical_json_bytes(intake)
        intake = checked(intake_raw, "qualification-corpus-intake-v1.0")
        require(intake_raw == canonical_json_bytes(intake), "intake bytes are not canonical")

        capture_dir = root / "qualification-corpus-intakes"
        capture_dir.mkdir(mode=0o700, exist_ok=True)
        capture_info = capture_dir.stat(follow_symlinks=False)
        require(stat.S_ISDIR(capture_info.st_mode) and capture_info.st_uid == os.geteuid(),
                "intake evidence directory is not Operator-owned")
        require(not (capture_info.st_mode & 0o077), "intake evidence directory must be private")
        artifact_path = capture_dir / (intake_id + ".json")
        fd = os.open(artifact_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=True) as stream:
                stream.write(intake_raw)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            artifact_path.unlink(missing_ok=True)
            raise

        key = "qualification_corpus_intake:" + intake_id
        intake_sha = sha256_bytes(intake_raw)
        row = {
            "intake_id": intake_id,
            "operation_id": operation_id,
            "operator_principal": context.operator_principal,
            "subject_inventory_key": key,
            "subject_sha256": intake_sha,
        }
        index_raw = append_intake_index(index, row)
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=".operation-index-", suffix=".tmp", dir=root)
        tmp_path = Path(tmp_name)
        try:
            os.fchmod(tmp_fd, 0o600)
            with os.fdopen(tmp_fd, "wb", closefd=True) as stream:
                stream.write(index_raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_path, context.operation_index_path)
            dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            # The record remains unindexed and therefore has no protected authority.
            raise
        require(sha256_file(artifact_path) == intake_sha, "protected intake capture changed after write")
        require(sha256_file(context.operation_index_path) == sha256_bytes(index_raw),
                "protected operation index append did not persist exact bytes")
        return {
            "intake_id": intake_id,
            "operation_id": operation_id,
            "operator_principal": context.operator_principal,
            "inventory_key": key,
            "path": str(artifact_path),
            "sha256": intake_sha,
            "operation_index_sha256": sha256_bytes(index_raw),
            "recorded_at": recorded_at,
        }
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def validate_qualification_corpus_intake(
    context: TrustContext,
    inventory_key: str,
    intake_sha256: str,
    *,
    content_sha256: str,
    authoring_id: str,
    reviewer_principal: str,
    reviewer_operation_id: str,
    reviewed_at: str,
) -> dict[str, Any]:
    """Verify Owner-index adoption, current custodian authority, and exact case bytes."""
    inventory = context.inventory
    raw = inventory.raw(inventory_key, intake_sha256, protected=True)
    intake = checked(raw, "qualification-corpus-intake-v1.0")
    require(raw == canonical_json_bytes(intake), "intake bytes must be canonical")
    profile, index = context.load()
    require(index["index_version"] == "1.1", "qualification intake absent from Index 1.1")
    require(profile["profile_version"] == "1.1", "qualification intake requires Operator Profile 1.1")
    require(intake["controller_id"] == profile["controller_id"], "intake controller mismatch")
    require(intake["authority_profile_sha256"] == context.profile_pin,
            "intake uses an obsolete authority profile")
    require(
        intake["controller_build_inventory_sha256"]
        == profile["controller_build_inventory_sha256"],
        "intake controller build pin mismatch",
    )
    require(intake["policy_epoch"] == context.policy_epoch == profile["policy_epoch"],
            "intake policy epoch mismatch")
    require(intake["operator_principal"] == context.operator_principal,
            "intake Operator principal is not from external TrustContext")
    _assert_protected_root_owner(context, intake)
    require(context.non_operator_process_unix_uids and intake["operator_unix_uid"] not in context.non_operator_process_unix_uids,
            "intake Operator UID overlaps a candidate process UID")
    role = context.role(intake["operator_principal"], "qualification_corpus_custodian",
                        stamp(intake["recorded_at"]))
    require(role["allowed_roles"] == ["qualification_corpus_custodian"],
            "intake custodian has non-intake authority")
    require(role["authorization_reference"] == intake["operator_authorization_reference"],
            "intake authorization reference mismatch")
    authorization_raw = inventory.raw(role["authorization_reference"], protected=True)
    require(sha256_bytes(authorization_raw) == intake["operator_authorization_sha256"],
            "intake authorization bytes changed")
    authorization = checked(authorization_raw, "operator-role-authorization-v1.1")
    require(authorization["principal_id"] == intake["operator_principal"]
            and authorization["allowed_roles"] == ["qualification_corpus_custodian"],
            "intake authorization is not least-privilege")
    records = [row for row in index["qualification_corpus_intakes"]
               if row["intake_id"] == intake["intake_id"]]
    require(len(records) == 1, "intake is not uniquely adopted in protected index")
    record = records[0]
    require(record == {
        "intake_id": intake["intake_id"],
        "operation_id": intake["operation_id"],
        "operator_principal": intake["operator_principal"],
        "subject_inventory_key": inventory_key,
        "subject_sha256": sha256_bytes(raw),
    }, "protected index does not capture exact intake bytes")
    context.not_revoked(intake["intake_id"], intake["operation_id"],
                        intake["operator_authorization_reference"])
    require(reviewer_principal != intake["operator_principal"],
            "reviewer equals qualification corpus custodian")
    require(reviewer_operation_id != intake["operation_id"],
            "review operation reuses intake controller operation")
    require(
        stamp(intake["recorded_at"]) <= stamp(reviewed_at),
        "qualification review predates corpus intake",
    )
    require(stamp(intake["recorded_at"]) <= context.now, "intake recorded in future")
    require(intake["historical_author_claim"] == "not_made"
            and intake["intake_is_historical_authoring_operation"] is False,
            "intake falsely claims historical authorship")
    require(intake["purpose"] == "qualification_only", "intake purpose mismatch")

    _, corpus, _, holdout = _frozen_manifests(
        context,
        intake["qualification_corpus"]["inventory_key"],
        intake["blind_holdout_truth"]["inventory_key"],
    )
    require(intake["qualification_corpus"]["sha256"] == FROZEN_GOLDEN_SHA256
            and intake["blind_holdout_truth"]["sha256"] == FROZEN_HOLDOUT_SHA256,
            "intake frozen corpus manifest binding changed")
    require(
        intake["qualification_corpus"]["corpus_contract_version"]
        == corpus["corpus_contract_version"]
        and intake["qualification_corpus"]["corpus_id"] == corpus["corpus_id"]
        and intake["qualification_corpus"]["corpus_version"] == corpus["corpus_version"],
        "intake golden manifest identity mismatch",
    )
    require(
        intake["blind_holdout_truth"]["corpus_contract_version"]
        == holdout["corpus_contract_version"]
        and intake["blind_holdout_truth"]["corpus_id"] == holdout["corpus_id"]
        and intake["blind_holdout_truth"]["corpus_version"] == holdout["corpus_version"],
        "intake blind holdout manifest identity mismatch",
    )
    # Check the held record against actual protected byte inventory, not its claims.
    origins = {row["case_id"]: row["origin"] for row in intake["cases"]}
    expected_cases = _case_rows(context, corpus, holdout, {
        case_id: origin for case_id, origin in origins.items() if origin is not None
    })
    require(intake["cases"] == expected_cases, "intake case/source closure differs from frozen raw bytes")
    matches = [row for row in intake["cases"]
               if row["content"]["sha256"] == content_sha256]
    require(len(matches) == 1, "Content bytes are not uniquely enrolled")
    case = matches[0]
    require(case["authoring_id"] == authoring_id, "Content authoring_id differs from intake")
    require(content_sha256 == FROZEN_CASE_CONTENT_SHA256[case["case_id"]],
            "Content SHA is outside the frozen 17-case set")
    context.not_revoked(intake["operator_principal"])
    return intake
