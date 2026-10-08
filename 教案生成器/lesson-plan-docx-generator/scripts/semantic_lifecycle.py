"""O2 lifecycle authority; all semantic judgments remain externally supplied.

The embedding controller installs a fresh TrustContext factory. A candidate or
installed Skill cannot provision it. The factory must re-read protected launch
policy/index, enforce ingress and supply current UTC time on every invocation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from lifecycle_digest import schema_errors, sha256_bytes
from semantic_scope_records import TrustContext, parse, require, stamp
from semantic_scope_review import validate_review, _references, derive_disposition
from operation_provenance import validate_receipt

_provider = ContextVar("operator_trust_context_provider", default=None)


@contextmanager
def operator_context(provider):
    """Controller API, never a candidate-supplied authority locator.

    ``provider()`` must return the external operator's current TrustContext.
    Protection/authentication is the operator's responsibility (Option B).
    A constant fixture provider is suitable only for deterministic tests.
    """
    require(callable(provider), "external TrustContext provider required")
    token = _provider.set(provider)
    try:
        yield
    finally:
        _provider.reset(token)


def context():
    provider = _provider.get()
    require(provider is not None, "UNAVAILABLE: external operator authority is unprovisioned")
    result = provider()
    require(isinstance(result, TrustContext), "external provider must return TrustContext")
    # The caller cannot freeze validity checks at capture time.
    result = replace(result, now=datetime.now(timezone.utc))
    result.load()
    for key in result.inventory.entries:
        result.inventory.raw(key)
    return result


FIELDS = {
    "outline_sha256": "outline",
    "semantic_scope_review_sha256": "semantic_scope_review",
    "semantic_scope_operation_receipt_sha256": "semantic_scope_operation_receipt",
    "reviewer_configuration_sha256": "reviewer_configuration",
    "reviewer_qualification_sha256": "reviewer_qualification",
    "qualification_approval_receipt_sha256": "qualification_approval_receipt",
    "authority_profile_sha256": "authority_profile",
    "teacher_approval_receipt_sha256": "teacher_approval_receipt",
}
LATER_ENTRIES = {"operation_index", "teacher_review", "teacher_approval_receipt", "teacher_packet", "production_authorization"}


def scope(run):
    from run_lesson_pipeline import path_of
    ctx = context()
    inventory = ctx.inventory
    require(isinstance(run.get("semantic_dependency_inventory"), list), "missing immutable O2 dependency closure")
    keys = [entry["inventory_key"] for entry in run["semantic_dependency_inventory"]]
    require(len(keys) == len(set(keys)) and set(keys) == set(inventory.entries) - LATER_ENTRIES,
            "incomplete or duplicated immutable semantic dependency closure")
    for entry in run["semantic_dependency_inventory"]:
        key = entry["inventory_key"]
        require(key in inventory.entries and dict(inventory.entries[key]) == entry, "STALE semantic dependency: " + key)
        inventory.raw(key, entry["sha256"])
    for key, name in (("source_truth_manifest", "source_truth"), ("content", "content")):
        require(path_of(run, name).resolve() == Path(inventory.entries[key]["path"]).resolve(),
                "foreign semantic inventory path: " + key)
        inventory.raw(key, run["bindings"][name]["sha256"])
    for field, key in FIELDS.items():
        if key == "teacher_approval_receipt":
            continue
        require(key in run["bindings"], "missing O2 binding: " + key)
        require(path_of(run, key).resolve() == Path(inventory.entries[key]["path"]).resolve(),
                "foreign O2 evidence path: " + key)
        inventory.raw(key, run["bindings"][key]["sha256"])
        require(run["state"]["artifacts"].get(field) == run["bindings"][key]["sha256"],
                "missing indexed O2 binding: " + field)
    content = parse(inventory.raw("content"))
    report = validate_review(ctx, frozen_lesson_ids=[row["lesson_id"] for row in content["lessons"]],
                             pipeline_run_id=run["state"]["pipeline_run_id"])
    require(report["review_purpose"] == "production_candidate", "qualification report cannot authorize a candidate")
    return ctx, report


def issue_index(report):
    return [{"lesson_id": row["lesson_id"], **issue} for row in report["lessons"] for issue in row["issues"]]


def packet_scope(run):
    ctx, report = scope(run)
    return dict(contract_version="1.0", review_sha256=sha256_bytes(ctx.inventory.raw("semantic_scope_review")),
                operation_receipt_sha256=sha256_bytes(ctx.inventory.raw("semantic_scope_operation_receipt")),
                outline_sha256=sha256_bytes(ctx.inventory.raw("outline")), issue_index=issue_index(report))


def teacher(run, review):
    ctx, report = scope(run)
    inventory = ctx.inventory
    require(review["contract_version"] == "2.0", "O2 cannot downgrade to Teacher Review 1.0")
    errors = schema_errors(review, "teacher-review-v2.schema.json")
    require(not errors, "; ".join(errors))
    semantic = review["semantic_scope"]
    for field, key in (("review_sha256", "semantic_scope_review"),
                       ("operation_receipt_sha256", "semantic_scope_operation_receipt"), ("outline_sha256", "outline")):
        inventory.raw(key, semantic[field])
    inventory.raw("teacher_review", run["bindings"]["teacher_review"]["sha256"])
    require(run["bindings"]["teacher_review"]["path"] == inventory.entries["teacher_review"]["path"], "foreign Teacher Review")
    require("teacher_approval_receipt" in run["bindings"], "missing separate teacher approval receipt")
    require(run["bindings"]["teacher_approval_receipt"]["path"] == inventory.entries["teacher_approval_receipt"]["path"], "candidate-selected teacher receipt path")
    require(run["state"]["artifacts"].get("teacher_approval_receipt_sha256") == run["bindings"]["teacher_approval_receipt"]["sha256"], "teacher receipt is not indexed")
    inventory.raw("teacher_approval_receipt", run["bindings"]["teacher_approval_receipt"]["sha256"], protected=True)
    receipt = validate_receipt(ctx, "teacher_approval_receipt", expected_kind="teacher_approval", subject_key="teacher_review")
    require(review["decision"] in {"APPROVED", "APPROVED_WITH_NOTES"}, "Teacher Review requests revision")
    issues = issue_index(report)
    require(not any(row["disposition"] == "REVISION_REQUIRED" for row in issues), "definite revision cannot be waived")
    ambiguities = {row["issue_id"] for row in issues if row["disposition"] == "HUMAN_REVIEW_REQUIRED"}
    resolutions = semantic["resolutions"]
    ids = [row["issue_id"] for row in resolutions]
    require(len(ids) == len(set(ids)) and set(ids) == ambiguities, "resolve every ambiguity exactly once across the entire course")
    manifest = parse(inventory.raw("source_truth_manifest"))
    sources = {row["source_id"]: (row, inventory.by_sha(row["sha256"])) for row in manifest["sources"]}
    for row in resolutions:
        require(row["bounded_rationale"].strip(), "resolution rationale required")
        require(stamp(report["reviewed_at"]) <= stamp(row["resolved_at"]) <= stamp(review["reviewed_at"]) <= stamp(receipt["recorded_at"]),
                "resolution/review/approval chronology invalid")
        _references(row["source_references"], sources)
    effective = derive_disposition([row["decision"] for row in resolutions])
    require(effective == "PASS", "effective whole-course disposition is REVISION_REQUIRED")
    return ctx, report


def authorization_scope(run, review):
    ctx, _ = teacher(run, review)
    inventory = ctx.inventory
    pairs = {"review_sha256": "semantic_scope_review", "operation_receipt_sha256": "semantic_scope_operation_receipt",
             "outline_sha256": "outline", "reviewer_configuration_sha256": "reviewer_configuration",
             "reviewer_qualification_sha256": "reviewer_qualification", "qualification_approval_receipt_sha256": "qualification_approval_receipt",
             "authority_profile_sha256": "authority_profile", "human_authority_receipt_sha256": "teacher_approval_receipt"}
    return {"contract_version": "1.0", **{field: sha256_bytes(inventory.raw(key)) for field, key in pairs.items()},
            "effective_whole_course_disposition": "PASS"}
