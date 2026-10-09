"""Reviewer Qualification 1.0 deterministic evidence and independent approval."""

from __future__ import annotations
import base64
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from lifecycle_digest import canonical_json_bytes, sha256_bytes
from semantic_scope_records import (
    TrustContext,
    checked,
    parse,
    qualification_fingerprint,
    require,
    stamp,
    managed_service_identity_fingerprint,
    managed_service_identity_projection,
    managed_approver_report_view,
    validate_managed_service_observation,
    validate_configuration,
    validate_training,
)
from semantic_scope_review import validate_review
from operation_provenance import validate_receipt

GOLDEN_IDS = (
    "N01",
    "N02",
    "N03",
    "N04",
    "N05",
    "N06",
    "P07",
    "P08",
    "P09",
    "P10",
    "P11",
    "P12",
    "A13",
    "P14",
)
GOLDEN_TRUTH = {
    case: (
        "REVISION_REQUIRED"
        if case.startswith("N")
        else "HUMAN_REVIEW_REQUIRED" if case.startswith("A") else "PASS"
    )
    for case in GOLDEN_IDS
}
ORIGINAL_NC02_SHA = "878604a6afba0b50dd758290ac280386fc301a9c76ff263cbece667ac8447352"


def validate_corpus(context: TrustContext, key: str, *, golden: bool) -> dict[str, Any]:
    corpus = context.inventory.record(key, "qualification-corpus", protected=True)
    context.not_revoked(corpus["corpus_id"])
    ids = [r["case_id"] for r in corpus["cases"]]
    require(len(ids) == len(set(ids)), "duplicate corpus case IDs")
    if golden:
        require(ids == list(GOLDEN_IDS), "mandatory golden corpus coverage/order")
    else:
        require(
            len({c["course_context"] for c in corpus["cases"]}) >= 3,
            "blind holdout needs three course contexts",
        )
    for case in corpus["cases"]:
        if golden:
            require(
                case["expected_disposition"] == GOLDEN_TRUTH[case["case_id"]],
                "golden truth relabeled",
            )
        inputs = case["inputs"]
        for entry in (
            inputs["content"],
            inputs["outline"],
            inputs["source_truth_manifest"],
            *inputs["sources"],
        ):
            context.inventory.raw(
                entry["inventory_key"], entry["sha256"], protected=True
            )
        context.inventory.raw(
            case["critical_truth_inventory_key"],
            case["critical_truth_sha256"],
            protected=True,
        )
        content = parse(context.inventory.raw(inputs["content"]["inventory_key"]))
        if golden and case["case_id"] == "N01":
            require(
                inputs["content"]["sha256"] == ORIGINAL_NC02_SHA,
                "original NC-02 replaced",
            )
        if golden and case["case_id"] == "P12":
            require(len(content["lessons"]) >= 32, "P12 requires whole long course")
    return corpus


def _case_context(context: TrustContext, case: dict[str, Any]) -> TrustContext:
    """Namespace exact case input inventory entries for the shared review validator."""
    aliases = {
        name: entry["inventory_key"]
        for name, entry in case["inputs"].items()
        if name != "sources"
    }
    return replace(context, inventory=context.inventory.namespace(aliases))


def _validate_case_exposures(
    inventory, qualification, index, all_cases, qualification_key
):
    """Check protected run/case/operation exposure before evaluating any report."""
    runs = qualification["qualification_runs"]
    by_case = {case["case_id"]: case for case in all_cases}
    forbidden_hashes = {
        qualification["corpus_sha256"],
        qualification["blind_holdout_sha256"],
        inventory.entries[qualification_key]["sha256"],
        *(case["critical_truth_sha256"] for case in all_cases),
        *(
            observation["adjudication_sha256"]
            for result in qualification["golden_results"]
            + qualification["holdout_results"]
            for observation in result["observations"]
        ),
        *(op["review_sha256"] for run in runs for op in run["operations"]),
    }
    if qualification["contract_version"] == "1.1":
        forbidden_hashes.update(
            op["service_observation_sha256"]
            for run in runs
            for op in run["operations"]
        )
    allowed_by_case = {}
    for case_id, case in by_case.items():
        inputs = case["inputs"]
        allowed = {"reviewer_configuration"} | {
            entry["inventory_key"]
            for entry in (
                inputs["content"],
                inputs["source_truth_manifest"],
                inputs["outline"],
                *inputs["sources"],
            )
        }
        require(
            not {inventory.entries[key]["sha256"] for key in allowed}.intersection(
                forbidden_hashes
            ),
            "truth/results exposed through an input alias",
        )
        allowed_by_case[case_id] = allowed
    for run in runs:
        require(
            [op["case_id"] for op in run["operations"]] == list(by_case),
            "incomplete/reordered evaluation run",
        )
        captures = [
            row for row in index["qualification_runs"] if row["run_id"] == run["run_id"]
        ]
        require(len(captures) == 1, "missing/duplicate protected run exposure evidence")
        exposures = captures[0]["operations"]
        require(
            [(row["case_id"], row["review_operation_id"]) for row in exposures]
            == [(op["case_id"], op["review_operation_id"]) for op in run["operations"]],
            "per-operation exposure binding/coverage/order mismatch",
        )
        for exposure in exposures:
            require(
                set(exposure["input_inventory_keys"])
                == allowed_by_case[exposure["case_id"]],
                "cross-case/label leakage or unrecorded per-operation input exposure",
            )


def _agent_evidence(
    context: TrustContext,
    qualification: dict[str, Any],
    candidate: str,
    author_principal: str | None,
    qualification_key: str,
) -> tuple[bool, set[str]]:
    inventory = context.inventory
    corpus = validate_corpus(context, "qualification_corpus", golden=True)
    holdout = validate_corpus(context, "blind_holdout_truth", golden=False)
    require(
        qualification["corpus_contract_version"]
        == corpus["corpus_contract_version"]
        == holdout["corpus_contract_version"],
        "corpus contract version mismatch",
    )
    inventory.raw(
        "qualification_corpus", qualification["corpus_sha256"], protected=True
    )
    inventory.raw(
        "blind_holdout_truth", qualification["blind_holdout_sha256"], protected=True
    )
    require(
        not {c["case_id"] for c in corpus["cases"]}.intersection(
            c["case_id"] for c in holdout["cases"]
        ),
        "holdout overlaps golden case IDs",
    )
    approval = validate_receipt(
        context,
        "corpus_approval_receipt",
        expected_kind="corpus_approval",
        subject_key="qualification_corpus",
        excluded_principals={candidate, author_principal},
    )
    require(approval["decision"] == "APPROVED", "corpus not approved")
    all_cases = corpus["cases"] + holdout["cases"]
    by_case = {c["case_id"]: c for c in all_cases}
    _, index = context.load()
    runs = qualification["qualification_runs"]
    if qualification["contract_version"] == "1.1":
        require(len(runs) >= 3, "managed qualification needs three fresh repetitions")
    require(
        len({r["run_id"] for r in runs}) == len(runs), "duplicate evaluation run IDs"
    )
    require(
        [r["repetition"] for r in runs] == list(range(1, len(runs) + 1)),
        "repetition coverage/order mismatch",
    )
    _validate_case_exposures(
        inventory, qualification, index, all_cases, qualification_key
    )
    observations: dict[tuple[str, str], dict[str, Any]] = {}
    operation_ids: list[str] = []
    seen_review_hashes: list[str] = []
    authors: set[str] = {author_principal} if author_principal else set()
    service_identities: set[str] = set()
    # Only timestamps from evidence validated below may set managed freshness.
    managed_evidence_completion_times: list[datetime] = []
    for run in runs:
        run_started_at = stamp(run["started_at"])
        run_completed_at = stamp(run["completed_at"])
        require(
            stamp(approval["recorded_at"])
            <= run_started_at
            < run_completed_at
            <= stamp(qualification["qualified_at"]),
            "invalid evaluation chronology",
        )
        require(
            [o["case_id"] for o in run["operations"]] == list(by_case),
            "incomplete/reordered evaluation run",
        )
        for op in run["operations"]:
            review_raw = inventory.raw(
                op["review_inventory_key"], op["review_sha256"], protected=True
            )
            if qualification["contract_version"] == "1.1":
                observation = validate_managed_service_observation(
                    inventory,
                    op["service_observation_inventory_key"],
                    op["service_observation_sha256"],
                    validate_configuration(inventory),
                    op["review_operation_id"],
                    expected_principal=candidate,
                    expected_response_artifact_raw=review_raw,
                    expected_response_artifact_kind="semantic_scope_review",
                    started_at=stamp(run["started_at"]),
                    completed_at=stamp(run["completed_at"]),
                    now=context.now,
                )
                require(
                    op["case_id"] not in op["review_operation_id"],
                    "managed operation identifier leaks qualification case ID",
                )
                service_identities.add(
                    managed_service_identity_fingerprint(observation)
                )
            case = by_case[op["case_id"]]
            inventory.raw(
                op["receipt_inventory_key"], op["receipt_sha256"], protected=True
            )
            case_context = _case_context(context, case)
            content = parse(case_context.inventory.raw("content"))
            review = validate_review(
                case_context,
                review_key=op["review_inventory_key"],
                receipt_key=op["receipt_inventory_key"],
                frozen_lesson_ids=[r["lesson_id"] for r in content["outline"]],
                pipeline_run_id=run["run_id"],
            )
            require(
                review["review_purpose"] == "qualification",
                "cached/production review used for evaluation",
            )
            require(
                review["reviewer"]["identity"] == candidate
                and review["reviewer"]["operation_id"] == op["review_operation_id"],
                "evaluation candidate/operation mismatch",
            )
            require(
                stamp(run["started_at"])
                <= stamp(review["reviewed_at"])
                <= stamp(run["completed_at"]),
                "review outside evaluation interval",
            )
            receipt_raw = inventory.raw(
                op["receipt_inventory_key"], op["receipt_sha256"], protected=True
            )
            parsed_receipt = parse(receipt_raw, allow_floats=False)
            receipt = checked(
                receipt_raw,
                "operation-provenance-receipt"
                if parsed_receipt.get("contract_version") == "1.0"
                else "operation-provenance-receipt-v1.1",
            )
            if qualification["contract_version"] == "1.1":
                require(
                    receipt["input_bindings"]["managed_service_observation"]
                    == {
                        "inventory_key": op["service_observation_inventory_key"],
                        "sha256": op["service_observation_sha256"],
                    },
                    "qualification operation/receipt service observation mismatch",
                )
            require(
                stamp(receipt["recorded_at"]) <= stamp(run["completed_at"]),
                "receipt outside evaluation interval",
            )
            authors.add(receipt["author_principal"])
            operation_ids.append(op["review_operation_id"])
            seen_review_hashes.append(op["review_sha256"])
            observations[(run["run_id"], op["case_id"])] = {
                "operation": op,
                "review": review,
            }
        if qualification["contract_version"] == "1.1":
            managed_evidence_completion_times.append(run_completed_at)
    require(
        approval["actor_principal"] not in authors,
        "corpus adjudicator equals evaluation author",
    )
    passed = len(operation_ids) == len(set(operation_ids)) and len(
        seen_review_hashes
    ) == len(set(seen_review_hashes))
    if qualification["contract_version"] == "1.1":
        require(
            len(service_identities) == 1,
            "managed service identity changed during qualification",
        )
        require(
            next(iter(service_identities))
            == qualification["service_identity_fingerprint"],
            "qualification managed service identity fingerprint mismatch",
        )
    for field, manifest in (("golden_results", corpus), ("holdout_results", holdout)):
        results = qualification[field]
        require(
            [r["case_id"] for r in results]
            == [c["case_id"] for c in manifest["cases"]],
            "result coverage/order mismatch",
        )
        for result in results:
            case = by_case[result["case_id"]]
            require(
                result["expected_disposition"] == case["expected_disposition"]
                and result["expected_critical_truth_sha256"]
                == case["critical_truth_sha256"],
                "result truth forgery",
            )
            require(
                [o["run_id"] for o in result["observations"]]
                == [r["run_id"] for r in runs],
                "observation repetition coverage mismatch",
            )
            hard_miss = False
            for observed in result["observations"]:
                actual = observations[(observed["run_id"], result["case_id"])]
                require(
                    observed["review_operation_id"]
                    == actual["operation"]["review_operation_id"]
                    and observed["observed_disposition"]
                    == actual["review"]["whole_course_disposition"],
                    "observation does not match actual report",
                )
                raw = inventory.raw(
                    observed["adjudication_inventory_key"],
                    observed["adjudication_sha256"],
                    protected=True,
                )
                adjudication = checked(raw, "qualification-adjudication")
                expected = dict(
                    case_id=result["case_id"],
                    run_id=observed["run_id"],
                    review_operation_id=observed["review_operation_id"],
                    review_sha256=actual["operation"]["review_sha256"],
                    critical_truth_sha256=case["critical_truth_sha256"],
                    critical_truth_satisfied=observed["critical_truth_satisfied"],
                )
                require(
                    all(adjudication[k] == v for k, v in expected.items()),
                    "adjudication does not match exact evidence",
                )
                principal = adjudication["adjudicator_principal"]
                require(
                    principal not in {candidate, *authors},
                    "adjudicator self/author evaluation",
                )
                require(
                    stamp(actual["review"]["reviewed_at"])
                    <= stamp(adjudication["recorded_at"])
                    <= stamp(qualification["qualified_at"]),
                    "invalid adjudication chronology",
                )
                context.role(
                    principal, "corpus_adjudicator", stamp(adjudication["recorded_at"])
                )
                records = [
                    r
                    for r in index["adjudications"]
                    if r["subject_inventory_key"]
                    == observed["adjudication_inventory_key"]
                ]
                require(
                    len(records) == 1
                    and records[0]["subject_sha256"] == sha256_bytes(raw)
                    and records[0]["actor_principal"] == principal,
                    "adjudication not protected-index captured",
                )
                context.not_revoked(records[0]["operation_id"])
                if qualification["contract_version"] == "1.1":
                    managed_evidence_completion_times.append(
                        stamp(adjudication["recorded_at"])
                    )
                hard_miss |= (
                    observed["observed_disposition"] != case["expected_disposition"]
                    or not observed["critical_truth_satisfied"]
                )
            require(result["hard_miss"] == hard_miss, "cached hard_miss forgery")
            passed &= not hard_miss
    if qualification["contract_version"] == "1.1":
        require(
            bool(managed_evidence_completion_times),
            "managed qualification has no validated evidence completion",
        )
        require(
            stamp(qualification["qualified_at"])
            == max(managed_evidence_completion_times),
            "managed qualification qualified_at does not equal evidence completion",
        )
    # Every evaluation author, not just the caller's current author, is excluded.
    return passed, authors


def _managed_approval(
    context: TrustContext,
    qualification: dict[str, Any],
    qualification_key: str,
    candidate_principal: str,
    excluded_principals: set[str],
    approval_receipt: dict[str, Any],
) -> None:
    """Verify the protected, label-blind operation by managed logical principal B."""
    inventory = context.inventory
    config = validate_configuration(inventory)
    binding = approval_receipt["input_bindings"][
        "managed_qualification_approval_evidence"
    ]
    evidence = checked(
        inventory.raw(binding["inventory_key"], binding["sha256"], protected=True),
        "managed-qualification-approval-evidence",
    )
    q_sha = inventory.entries[qualification_key]["sha256"]
    config_sha = inventory.entries["reviewer_configuration"]["sha256"]
    require(
        evidence["qualification_sha256"] == q_sha
        and evidence["reviewer_configuration_sha256"] == config_sha,
        "managed approval evidence qualification/config binding mismatch",
    )
    approver = evidence["approver_principal"]
    require(
        evidence["reviewer_principal"] == candidate_principal
        and approver == approval_receipt["actor_principal"]
        and evidence["operation_id"] == approval_receipt["operation_id"],
        "managed qualification approver is not the protected second principal/operation",
    )
    evaluation_operations = {
        operation["review_operation_id"]
        for run in qualification["qualification_runs"]
        for operation in run["operations"]
    }
    require(
        evidence["operation_id"] not in evaluation_operations,
        "managed qualification approver reuses a reviewer operation",
    )
    require(approver not in excluded_principals, "managed qualification approver equals reviewer/author/evaluator")
    context.role(approver, "qualification_approver", stamp(evidence["reviewed_at"]))
    require(
        stamp(qualification["qualified_at"])
        <= stamp(evidence["reviewed_at"])
        < stamp(qualification["valid_until"])
        and stamp(evidence["reviewed_at"]) <= context.now,
        "managed approver operation outside qualification validity",
    )
    require(
        evidence["approval_prompt_sha256"]
        == config["agent"]["qualification_approver_prompt_sha256"],
        "managed qualification approver prompt changed",
    )
    inventory.by_sha(evidence["approval_prompt_sha256"], protected=True)
    response_raw = inventory.raw(
        evidence["response_inventory_key"],
        evidence["response_sha256"],
        protected=True,
    )
    observation = validate_managed_service_observation(
        inventory,
        evidence["service_observation_inventory_key"],
        evidence["service_observation_sha256"],
        config,
        evidence["operation_id"],
        expected_principal=approver,
        expected_response_artifact_raw=response_raw,
        expected_response_artifact_kind="managed_qualification_approver_response",
        completed_at=stamp(evidence["reviewed_at"]),
        now=context.now,
    )
    require(
        managed_service_identity_fingerprint(observation)
        == qualification["service_identity_fingerprint"],
        "managed qualification approver service identity changed",
    )
    packet = checked(
        inventory.raw(
            evidence["review_packet_inventory_key"],
            evidence["review_packet_sha256"],
            protected=True,
        ),
        "managed-qualification-review-packet",
    )
    require(
        packet["qualification_sha256"] == q_sha
        and packet["reviewer_configuration_sha256"] == config_sha
        and packet["service_identity_fingerprint"]
        == qualification["service_identity_fingerprint"],
        "managed qualification review packet subject/identity mismatch",
    )
    require(
        packet["exposure"]
        == {
            "expected_labels": False,
            "critical_truth": False,
            "blind_holdout_truth": False,
            "adjudication_results": False,
            "case_identifiers": False,
            "review_outputs_included": True,
            "fresh_context": True,
        },
        "managed qualification approver packet exposes truth or reuses context",
    )
    expected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for run in qualification["qualification_runs"]:
        for operation in run["operations"]:
            key = (
                operation["review_sha256"],
                operation["receipt_sha256"],
                operation["service_observation_sha256"],
            )
            require(key not in expected, "duplicate managed qualification evidence tuple")
            expected[key] = operation
    actual: dict[tuple[str, str, str], str] = {}
    refs: set[str] = set()
    case_ids = {
        row["case_id"]
        for row in qualification["golden_results"]
        + qualification["holdout_results"]
    }
    for row in packet["operations"]:
        ref = row["operation_ref"]
        require(ref not in refs, "duplicate managed approval operation ref")
        refs.add(ref)
        key = (
            row["review_sha256"],
            row["receipt_sha256"],
            row["service_observation_sha256"],
        )
        require(key not in actual, "duplicate managed approval evidence row")
        operation = expected.get(key)
        require(operation is not None, "managed approval packet has unknown operation evidence")
        raw_report = inventory.raw(
            operation["review_inventory_key"],
            operation["review_sha256"],
            protected=True,
        )
        operation_observation = validate_managed_service_observation(
            inventory,
            operation["service_observation_inventory_key"],
            operation["service_observation_sha256"],
            config,
            operation["review_operation_id"],
            expected_principal=candidate_principal,
            expected_response_artifact_raw=raw_report,
            expected_response_artifact_kind="semantic_scope_review",
            now=context.now,
        )
        service_identity = managed_service_identity_projection(operation_observation)
        service_identity["service_identity_fingerprint"] = (
            managed_service_identity_fingerprint(operation_observation)
        )
        require(
            row["service_identity"] == service_identity
            and service_identity["service_identity_fingerprint"]
            == qualification["service_identity_fingerprint"],
            "managed approval packet service identity projection mismatch",
        )
        try:
            decoded = base64.b64decode(row["review_report_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("managed approval report is not valid base64") from exc
        expected_view = managed_approver_report_view(raw_report, case_ids)
        require(decoded == expected_view, "managed approval packet report view changed")
        actual[key] = ref
    require(set(actual) == set(expected), "managed approver packet omits evaluation operations")
    response = checked(
        response_raw,
        "managed-qualification-approver-response",
    )
    require(
        set(response["reviewed_operation_refs"]) == refs
        and len(response["reviewed_operation_refs"]) == len(refs),
        "managed approver did not review exact operation coverage",
    )
    checks = {row["check_id"]: row for row in response["checks"]}
    expected_checks = {
        "operation_coverage",
        "artifact_binding",
        "service_identity_consistency",
        "truth_blindness",
        "separate_authority",
    }
    require(set(checks) == expected_checks, "managed approver check coverage mismatch")
    require(all(row["passed"] for row in checks.values()), "managed approver rejected qualification checks")
    require(
        all(set(row["supporting_operation_refs"]) == refs for row in checks.values()),
        "managed approver check omitted operation evidence",
    )
    require(
        response["decision"] == evidence["decision"] == approval_receipt["decision"]
        and response["rationale"] == evidence["rationale"]
        and response["decision"] == "APPROVED",
        "managed approval response/evidence/receipt disagreement",
    )


def validate_qualification(
    context: TrustContext,
    *,
    candidate_principal: str,
    author_principal: str | None = None,
    qualification_key: str = "reviewer_qualification",
    approval_key: str = "qualification_approval_receipt",
    require_approval: bool = True,
) -> dict[str, Any]:
    """Validate evidence, then independent approval (acyclic two-stage capture).

    require_approval=False is only a controller's pre-capture evidence check; it
    never grants current authority. Default and production consumers require it.
    """
    inventory = context.inventory
    raw_qualification = inventory.raw(qualification_key, protected=True)
    parsed_qualification = parse(raw_qualification, allow_floats=False)
    require(isinstance(parsed_qualification, dict), "reviewer qualification must be an object")
    version = parsed_qualification.get("contract_version")
    require(version in {"1.0", "1.1"}, "unsupported reviewer qualification version")
    qualification = checked(
        raw_qualification,
        "reviewer-qualification" if version == "1.0" else "reviewer-qualification-v1.1",
    )
    require(
        qualification["qualification_fingerprint"]
        == qualification_fingerprint(qualification),
        "qualification fingerprint mismatch",
    )
    config = validate_configuration(inventory)
    managed = config["configuration_version"] == "1.1"
    require(
        managed == (qualification["contract_version"] == "1.1"),
        "managed reviewer configuration/qualification versions differ",
    )
    inventory.raw(
        "reviewer_configuration", qualification["reviewer_configuration_sha256"]
    )
    for qfield, cfield in (
        ("reviewer_implementation", "implementation"),
        ("reviewer_version", "version"),
    ):
        require(
            qualification[qfield] == config[cfield],
            "qualification configuration mismatch",
        )
    require(
        stamp(qualification["qualified_at"])
        <= context.now
        < stamp(qualification["valid_until"]),
        "qualification expired/not-yet-valid",
    )
    if managed:
        require(
            stamp(qualification["valid_until"])
            <= stamp(qualification["qualified_at"]) + timedelta(hours=24),
            "managed reviewer qualification exceeds 24-hour maximum",
        )
    context.not_revoked(qualification["qualification_id"])
    if qualification["qualification_purpose"] == "human_scope_authority":
        require(
            config["reviewer_type"] == "human"
            and qualification["human_authority"]["principal_id"] == candidate_principal,
            "human qualification principal/type mismatch",
        )
        validate_training(
            context, qualification, config, author_principal=author_principal
        )
        passed = True
        excluded = {candidate_principal, author_principal}
    else:
        require(
            config["reviewer_type"] == "agent",
            "agent qualification configuration type mismatch",
        )
        context.role(candidate_principal, "scope_reviewer")
        passed, authors = _agent_evidence(
            context,
            qualification,
            candidate_principal,
            author_principal,
            qualification_key,
        )
        excluded = {
            candidate_principal,
            author_principal,
            *authors,
        }
    require(
        qualification["disposition"] == ("QUALIFIED" if passed else "NOT_QUALIFIED"),
        "qualification disposition forgery",
    )
    if require_approval:
        require(passed, "NOT_QUALIFIED cannot grant current authority")
        receipt = validate_receipt(
            context,
            approval_key,
            expected_kind="qualification",
            subject_key=qualification_key,
            excluded_principals=excluded,
        )
        require(
            receipt["decision"] == "APPROVED",
            "missing independent APPROVED qualification receipt",
        )
        if managed:
            _managed_approval(
                context,
                qualification,
                qualification_key,
                candidate_principal,
                excluded,
                receipt,
            )
    return qualification


def build_managed_qualification_review_packet(
    context: TrustContext,
    *,
    candidate_principal: str,
    qualification_key: str = "reviewer_qualification",
) -> bytes:
    """Build the label-blind evidence packet for the independent managed approver.

    The packet contains all candidate reports in opaque-reference order, with
    case identifiers and corpus-linkable hashes removed from the display copy.
    Exact source report/receipt/observation hashes remain bound for controller
    verification; expected labels and holdout truth are never serialized.
    """
    inventory = context.inventory
    qualification = validate_qualification(
        context,
        candidate_principal=candidate_principal,
        qualification_key=qualification_key,
        require_approval=False,
    )
    require(
        qualification["contract_version"] == "1.1",
        "managed approver packet requires Reviewer Qualification 1.1",
    )
    config = validate_configuration(inventory)
    q_sha = inventory.entries[qualification_key]["sha256"]
    config_sha = inventory.entries["reviewer_configuration"]["sha256"]
    case_ids = {
        row["case_id"]
        for row in qualification["golden_results"]
        + qualification["holdout_results"]
    }
    operations = []
    for run in qualification["qualification_runs"]:
        for operation in run["operations"]:
            review_sha = operation["review_sha256"]
            receipt_sha = operation["receipt_sha256"]
            observation_sha = operation["service_observation_sha256"]
            report_raw = inventory.raw(
                operation["review_inventory_key"], review_sha, protected=True
            )
            observation = validate_managed_service_observation(
                inventory,
                operation["service_observation_inventory_key"],
                observation_sha,
                config,
                operation["review_operation_id"],
                expected_principal=candidate_principal,
                expected_response_artifact_raw=report_raw,
                expected_response_artifact_kind="semantic_scope_review",
                started_at=stamp(run["started_at"]),
                completed_at=stamp(run["completed_at"]),
                now=context.now,
            )
            identity = managed_service_identity_projection(observation)
            identity["service_identity_fingerprint"] = (
                managed_service_identity_fingerprint(observation)
            )
            operation_ref = "op-" + sha256_bytes(
                canonical_json_bytes(
                    {
                        "review_sha256": review_sha,
                        "receipt_sha256": receipt_sha,
                        "service_observation_sha256": observation_sha,
                    }
                )
            )[:32]
            operations.append(
                {
                    "operation_ref": operation_ref,
                    "review_sha256": review_sha,
                    "receipt_sha256": receipt_sha,
                    "service_observation_sha256": observation_sha,
                    "service_identity": identity,
                    "review_report_base64": base64.b64encode(
                        managed_approver_report_view(report_raw, case_ids)
                    ).decode("ascii"),
                }
            )
    operations.sort(key=lambda row: row["operation_ref"])
    packet = {
        "packet_version": "1.0",
        "qualification_sha256": q_sha,
        "reviewer_configuration_sha256": config_sha,
        "service_identity_fingerprint": qualification[
            "service_identity_fingerprint"
        ],
        "operations": operations,
        "exposure": {
            "expected_labels": False,
            "critical_truth": False,
            "blind_holdout_truth": False,
            "adjudication_results": False,
            "case_identifiers": False,
            "review_outputs_included": True,
            "fresh_context": True,
        },
    }
    raw = canonical_json_bytes(packet)
    checked(raw, "managed-qualification-review-packet")
    return raw


def qualification_status(context: TrustContext, **kwargs: Any):
    """Current authority status; no record is deleted on stale/revoked evidence."""
    from semantic_scope_records import RecordError, StaleEvidence
    from semantic_scope_review import ValidationResult

    try:
        validate_qualification(context, **kwargs)
    except StaleEvidence as exc:
        return ValidationResult("STALE", (str(exc),))
    except (RecordError, ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        return ValidationResult("INVALID", (str(exc),))
    return ValidationResult("VALID")
