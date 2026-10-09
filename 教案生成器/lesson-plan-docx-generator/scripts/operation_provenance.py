"""Operation Provenance Receipt 1.0: operator-controlled process evidence."""

from __future__ import annotations
from typing import Any, Iterable

from semantic_scope_records import (
    TrustContext,
    checked,
    parse,
    require,
    stamp,
    validate_configuration,
    validate_managed_service_observation,
)

ROLES = {
    "semantic_scope": "scope_reviewer",
    "teacher_approval": "teacher_approver",
    "qualification": "qualification_approver",
    "corpus_approval": "corpus_adjudicator",
}
SUBJECTS = {
    "semantic_scope": "semantic-scope-review",
    "qualification": "reviewer-qualification",
    "corpus_approval": "qualification-corpus",
}


def validate_receipt(
    context: TrustContext,
    key: str,
    *,
    expected_kind: str,
    subject_key: str,
    excluded_principals: Iterable[str] = (),
) -> dict[str, Any]:
    """Capture requires an exact protected index entry, never filename discovery.

    Teacher kind validates future subject operation bindings only. This does not
    validate or activate Teacher Review 2.0, resolve issues or issue authorization.
    """
    inventory = context.inventory
    raw = inventory.raw(key, protected=True)
    parsed_receipt = parse(raw, allow_floats=False)
    require(isinstance(parsed_receipt, dict), "operation receipt must be an object")
    receipt_version = parsed_receipt.get("contract_version")
    require(receipt_version in {"1.0", "1.1"}, "unsupported operation receipt version")
    receipt = checked(
        raw,
        "operation-provenance-receipt"
        if receipt_version == "1.0"
        else "operation-provenance-receipt-v1.1",
    )
    require(receipt["review_kind"] == expected_kind, "receipt kind mismatch")
    require(
        receipt["subject_inventory_key"] == subject_key, "receipt subject key mismatch"
    )
    profile, index = context.load()
    require(
        receipt["authority_profile_sha256"] == context.profile_pin,
        "receipt old profile pin: INVALID authority",
    )
    require(
        receipt["controller_id"] == profile["controller_id"],
        "receipt controller mismatch",
    )
    records = [r for r in index["receipts"] if r["receipt_id"] == receipt["receipt_id"]]
    require(len(records) == 1, "receipt not captured in protected operation index")
    record = records[0]
    from lifecycle_digest import sha256_bytes

    require(
        record["receipt_inventory_key"] == key
        and record["receipt_sha256"] == sha256_bytes(raw),
        "protected index does not match exact receipt bytes",
    )
    for field in (
        "operation_id",
        "actor_principal",
        "subject_inventory_key",
        "subject_sha256",
    ):
        require(record[field] == receipt[field], f"protected index {field} mismatch")
    at = stamp(receipt["recorded_at"])
    require(at <= context.now, "receipt recorded in future")
    context.role(receipt["actor_principal"], ROLES[expected_kind], at)
    context.not_revoked(receipt["receipt_id"], receipt["operation_id"])
    require(
        receipt["actor_principal"] not in set(excluded_principals),
        "receipt self/author approval",
    )
    inventory.raw(receipt["approval_procedure_reference"], protected=True)
    context.not_revoked(receipt["approval_procedure_reference"])
    subject_raw = inventory.raw(
        subject_key,
        receipt["subject_sha256"],
        protected=expected_kind in {"qualification", "corpus_approval"},
    )
    if expected_kind == "qualification":
        parsed_subject = parse(subject_raw, allow_floats=False)
        require(isinstance(parsed_subject, dict), "qualification must be an object")
        qualification_version = parsed_subject.get("contract_version")
        require(
            qualification_version in {"1.0", "1.1"},
            "unsupported reviewer qualification version",
        )
        subject = checked(
            subject_raw,
            "reviewer-qualification"
            if qualification_version == "1.0"
            else "reviewer-qualification-v1.1",
        )
    else:
        subject = (
            checked(subject_raw, SUBJECTS[expected_kind])
            if expected_kind in SUBJECTS
            else parse(subject_raw)
        )
    for binding_key, digest in receipt["input_bindings"].items():
        if isinstance(digest, str):
            inventory.raw(binding_key, digest)
    if expected_kind in {"semantic_scope", "teacher_approval"}:
        content = parse(inventory.raw("content"))
        authoring_id = content["authoring_provenance"]["authoring_id"]
        authors = [r for r in index["authors"] if r["authoring_id"] == authoring_id]
        require(
            len(authors) == 1, "Content author operation not protected-index captured"
        )
        author = authors[0]
        require(
            author["content_sha256"] == receipt["input_bindings"]["content"],
            "author Content binding mismatch",
        )
        require(
            author["principal_id"] == receipt["author_principal"]
            and author["operation_id"] == receipt["author_operation_id"],
            "forged author separation",
        )
        context.role(author["principal_id"], "author", at)
        require(
            receipt["actor_principal"] != author["principal_id"],
            "reviewer equals author principal",
        )
        require(
            receipt["operation_id"] != author["operation_id"],
            "review operation equals author operation",
        )
        require(
            subject["pipeline_run_id"] == receipt["pipeline_run_id"],
            "receipt pipeline run mismatch",
        )
        for field, binding in (
            ("content_sha256", "content"),
            ("source_truth_manifest_sha256", "source_truth_manifest"),
        ):
            require(
                subject[field] == receipt["input_bindings"][binding],
                f"subject {field} mismatch",
            )
    if expected_kind == "semantic_scope":
        reviewer = subject["reviewer"]
        require(
            reviewer["identity"] == receipt["actor_principal"]
            and reviewer["operation_id"] == receipt["operation_id"],
            "scope actor/operation mismatch",
        )
        require(subject["authoring_id"] == authoring_id, "review authoring ID mismatch")
        for field, binding in (("outline_sha256", "outline"),):
            require(
                subject[field] == receipt["input_bindings"][binding],
                f"scope {field} mismatch",
            )
        require(
            reviewer["configuration_sha256"]
            == receipt["input_bindings"]["reviewer_configuration"],
            "scope config binding mismatch",
        )
        require(
            reviewer["qualification_sha256"]
            == receipt["input_bindings"]["reviewer_qualification"],
            "scope qualification binding mismatch",
        )
        require(
            (subject["review_purpose"] == "qualification")
            == (reviewer["qualification_sha256"] is None),
            "qualification-purpose/null binding mismatch",
        )
        require(stamp(subject["reviewed_at"]) <= at, "receipt predates review")
        config = validate_configuration(inventory)
        managed = config["configuration_version"] == "1.1"
        require(
            managed == (receipt_version == "1.1"),
            "managed reviewer and operation receipt versions differ",
        )
        if managed:
            binding = receipt["input_bindings"]["managed_service_observation"]
            observation = validate_managed_service_observation(
                inventory,
                binding["inventory_key"],
                binding["sha256"],
                config,
                receipt["operation_id"],
                expected_principal=receipt["actor_principal"],
                now=context.now,
            )
            require(
                stamp(observation["observed_at"])
                <= stamp(subject["reviewed_at"]),
                "service observation postdates managed reviewer response",
            )
    elif expected_kind == "teacher_approval":
        require(
            subject.get("contract_version") == "2.0",
            "teacher receipt requires future bound human subject",
        )
        human = subject["semantic_scope"]["human_reviewer"]
        require(
            human["authority_reference"] == receipt["receipt_id"],
            "teacher authority receipt ID mismatch",
        )
        require(
            subject["semantic_scope"]["outline_sha256"]
            == receipt["input_bindings"]["outline"],
            "teacher outline mismatch",
        )
        require(
            human["identity"] == receipt["actor_principal"]
            and human["review_operation_id"] == receipt["operation_id"],
            "teacher actor/operation mismatch",
        )
        require(subject["decision"] == receipt["decision"], "teacher decision mismatch")
        scope = parse(inventory.raw("semantic_scope_review"))
        require(
            receipt["operation_id"] != scope["reviewer"]["operation_id"],
            "teacher reuses semantic operation",
        )
        semantic_receipt = validate_receipt(
            context,
            "semantic_scope_operation_receipt",
            expected_kind="semantic_scope",
            subject_key="semantic_scope_review",
        )
        require(
            semantic_receipt["review_kind"] == "semantic_scope",
            "teacher has wrong scope receipt kind",
        )
        require(
            subject["semantic_scope"]["review_sha256"]
            == receipt["input_bindings"]["semantic_scope_review"]
            and subject["semantic_scope"]["operation_receipt_sha256"]
            == receipt["input_bindings"]["semantic_scope_operation_receipt"],
            "teacher semantic bindings mismatch",
        )
    elif expected_kind == "qualification":
        require(
            stamp(subject["qualified_at"]) <= at,
            "receipt predates qualification completion",
        )
        if receipt["decision"] == "APPROVED":
            require(
                subject["disposition"] == "QUALIFIED", "cannot approve NOT_QUALIFIED"
            )
        if subject["qualification_purpose"] == "agent_corpus_evaluation":
            expected_keys = {
                "reviewer_configuration",
                "qualification_corpus",
                "blind_holdout_truth",
                "corpus_approval_receipt",
            }
            if subject["contract_version"] == "1.1":
                expected_keys.add("managed_qualification_approval_evidence")
            require(set(receipt["input_bindings"]) == expected_keys,
                    "agent qualification receipt branch mismatch")
            expected = {
                "reviewer_configuration": subject["reviewer_configuration_sha256"],
                "qualification_corpus": subject["corpus_sha256"],
                "blind_holdout_truth": subject["blind_holdout_sha256"],
            }
        else:
            require(
                set(receipt["input_bindings"])
                == {"human_training_authorization", "human_procedure"},
                "human qualification receipt branch mismatch",
            )
            require(
                receipt["actor_principal"]
                != subject["human_authority"]["principal_id"],
                "human self-approval",
            )
            expected = {
                "human_training_authorization": subject["human_authority"][
                    "training_authorization_sha256"
                ],
                "human_procedure": subject["human_authority"]["procedure_sha256"],
            }
        for binding, digest in expected.items():
            require(
                receipt["input_bindings"][binding] == digest,
                f"qualification {binding} mismatch",
            )
        config = validate_configuration(inventory)
        managed = config["configuration_version"] == "1.1"
        require(
            managed == (subject["contract_version"] == "1.1")
            and managed == (receipt_version == "1.1"),
            "managed qualification receipt/configuration versions differ",
        )
        if managed:
            binding = receipt["input_bindings"][
                "managed_qualification_approval_evidence"
            ]
            evidence_raw = inventory.raw(
                binding["inventory_key"], binding["sha256"], protected=True
            )
            evidence = checked(
                evidence_raw, "managed-qualification-approval-evidence"
            )
            require(
                evidence["qualification_sha256"] == receipt["subject_sha256"]
                and evidence["reviewer_configuration_sha256"]
                == receipt["input_bindings"]["reviewer_configuration"],
                "managed qualification approval subject/config mismatch",
            )
            require(
                evidence["approver_principal"] == receipt["actor_principal"]
                and evidence["operation_id"] == receipt["operation_id"]
                and evidence["reviewer_principal"] != evidence["approver_principal"],
                "managed qualification reviewer/approver identity mismatch",
            )
            require(
                evidence["decision"] == receipt["decision"]
                and stamp(evidence["reviewed_at"]) <= at,
                "managed approval evidence decision/time mismatch",
            )
    elif expected_kind == "corpus_approval":
        require(
            receipt["input_bindings"]["qualification_corpus"]
            == receipt["subject_sha256"],
            "corpus subject mismatch",
        )
        require(stamp(subject["created_at"]) <= at, "corpus approval predates truth")
        holdout = checked(
            inventory.raw("blind_holdout_truth", protected=True), "qualification-corpus"
        )
        require(stamp(holdout["created_at"]) <= at, "approval predates holdout truth")
    return receipt
