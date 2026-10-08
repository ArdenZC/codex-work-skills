"""Read-only lifecycle closure diagnostics and independently validated Acceptance 3.0."""
import copy
from pathlib import Path

from benchmark_preparation import timestamp
from lifecycle_digest import LifecycleContractError, read_json_object, schema_errors, semantic_fingerprint, sha256_file, skill_tree_fingerprint, timezone_aware_timestamp

GATES = {
    "pipeline_identity": (None, "Lifecycle", "1.0"),
    "source_truth": ("source_truth", "Source Truth", "1.0"),
    "content": ("content", "Content", "2.2/2.3"),
    "preproduction_qa": ("preproduction_qa", "Content QA", "1.0"),
    "benchmark_disposition": ("benchmark_disposition", "Benchmark", "1.0"),
    "teacher_review_packet": ("teacher_review_packet", "Teacher Review Packet", "1.0"),
    "teacher_review": ("teacher_review", "Teacher Review", "1.0"),
    "production_authorization": ("production_authorization", "Production Authorization", "1.0"),
    "artifact_manifest": ("artifact_manifest", "Artifact Manifest", "2.0"),
    "artifact_qa": ("artifact_qa", "Artifact QA", "2.3.1"),
    "visual_review": ("visual_review", "Visual Review Authority", "1.0"),
    "lifecycle_state": (None, "Pipeline State", "1.0"),
}
LINKS = {"source_truth_manifest_sha256": "source_truth", "content_sha256": "content",
    "preproduction_qa_sha256": "preproduction_qa", "benchmark_disposition_sha256": "benchmark_disposition",
    "benchmark_review_sha256": "benchmark_review", "teacher_review_packet_sha256": "teacher_review_packet",
    "teacher_review_sha256": "teacher_review", "production_authorization_sha256": "production_authorization",
    "artifact_manifest_sha256": "artifact_manifest", "artifact_qa_sha256": "artifact_qa",
    "visual_review_authority_sha256": "visual_review"}


def acceptance_fingerprint(payload):
    return semantic_fingerprint(payload, excluded_fields={"created_at", "acceptance_fingerprint"})



def final_status(mode, gates, revision, limitations):
    """Classify already-validated gate facts; integrity errors never reach here."""
    if mode == "PREVIEW": return "PENDING_REVIEW"
    if len(gates) != len(GATES): return "PENDING_REVIEW"
    if revision: return "REVISION_REQUIRED"
    if any(row["status"] == "FAIL" for row in gates): return "FAILED"
    if any(row["status"] != "PASS" for row in gates): return "PENDING_REVIEW"
    return "ACCEPTED_WITH_NOTES" if limitations else "ACCEPTED"


def evaluate(run, *, created_at=None, validate_acceptance=True, diagnostic_inputs=None, run_path=None):
    """No writes, state changes, negative controls, or human decisions."""
    from run_lesson_pipeline import validate_run, validate_run_upstream, bind, path_of, envelope_fingerprint, evidence_kwargs, benchmark_claims, SKILL_ROOT
    from pipeline_state import STATES
    from teacher_review import validate_teacher_review_files
    from teacher_review_packet import validate_teacher_review_packet, validate_teacher_review_against_packet
    from visual_review_authority import validate_visual_review_authority
    from final_artifacts import validate_run_artifacts
    working = copy.deepcopy(run)
    gates = [{"name": name, "status": "PENDING", "evidence_sha256": None, "contract": contract,
              "version": version, "notes": "required evidence is not yet available"}
             for name, (_, contract, version) in GATES.items()]
    indexed = {row["name"]: row for row in gates}
    if run.get("orchestrator_version") == "2.0":
        for name in ("pipeline_identity", "teacher_review_packet", "teacher_review", "production_authorization", "lifecycle_state"):
            indexed[name]["version"] = "2.0"
    # Diagnostic metadata must itself remain valid even when the envelope is
    # malformed. The original, unsanitized run is still validated below.
    state = run.get("state") if isinstance(run, dict) else None
    run_id = state.get("pipeline_run_id") if isinstance(state, dict) else None
    mode = run.get("mode") if isinstance(run, dict) else None
    result = {"contract_version": "3.0", "pipeline_run_id": run_id if isinstance(run_id, str) and run_id.strip() else "INVALID",
        "mode": mode if isinstance(mode, str) and mode in {"PRODUCTION", "PREVIEW"} else "PRODUCTION",
        "final_status": "PENDING_REVIEW", "gate_matrix": gates,
        "evidence": {name: None for name in LINKS}, "final_artifact_inventory": None,
        "skill_fingerprint": None, "template": None, "limitations": [], "created_at": created_at or timestamp()}
    revision = False
    try:
        # Validate the original envelope before adding optional, external diagnostic
        # judgments to a private copy. Forged states/hashes take precedence over revision.
        validate_run(run, run_path=run_path, validate_acceptance=False)
        if run["state"]["current_state"] == "ACCEPTED" and validate_acceptance:
            validate_acceptance_file(path_of(run, "acceptance"), run)
        for name, path in (diagnostic_inputs or {}).items():
            if name not in {"teacher_review", "visual_review", "visual_evidence", "benchmark_review", "authoring_selection", "holdout_selection", "lesson_reviews_dir", "previous_lesson_content", "previous_review", "previous_lesson_reviews_dir"}:
                raise LifecycleContractError("unsupported diagnostic evidence: " + name)
            bind(working, name, path)
        working["run_fingerprint"] = envelope_fingerprint(working)
        validate_run_upstream(working)
        rank = STATES.index(run["state"]["current_state"])
        indexed["pipeline_identity"].update(status="PASS", evidence_sha256=semantic_fingerprint({
            "pipeline_run_id": result["pipeline_run_id"], "mode": result["mode"], "orchestrator_version": run["orchestrator_version"]}), notes="valid immutable run identity")
        minimum = {"source_truth": 0, "content": STATES.index("AUTHORING_COMPLETE"),
            "preproduction_qa": STATES.index("PREPRODUCTION_QA_PASSED"),
            "benchmark_disposition": STATES.index("READY_FOR_TEACHER_REVIEW"),
            "teacher_review_packet": STATES.index("READY_FOR_TEACHER_REVIEW"),
            "teacher_review": STATES.index("TEACHER_REVIEW_APPROVED"),
            "production_authorization": STATES.index("PRODUCTION_AUTHORIZED"),
            "artifact_manifest": STATES.index("PRODUCTION_GENERATED"),
            "artifact_qa": STATES.index("ARTIFACT_QA_PASSED"),
            "visual_review": STATES.index("VISUAL_REVIEW_APPROVED")}
        for name, (binding, _, _) in GATES.items():
            if binding and binding in working["bindings"] and rank >= minimum[name]:
                indexed[name].update(status="PASS", evidence_sha256=sha256_file(path_of(working, binding)), notes="current linked evidence validated")
        for field, binding in LINKS.items():
            if binding in working["bindings"]:
                result["evidence"][field] = sha256_file(path_of(working, binding))
        content = None
        if "content" in working["bindings"]:
            content, _ = read_json_object(path_of(working, "content"), "Content")
            indexed["content"]["version"] = content["content_contract_version"]
            if not content.get("lessons"):
                raise LifecycleContractError("valid zero-Lesson Content is outside the canonical Lesson lifecycle; not eligible for Lesson Acceptance 3.0")
        if "benchmark_review" in working["bindings"]:
            claims = benchmark_claims(working)
            if claims["benchmark_decision"] == "REVISION_REQUIRED":
                revision = True
                indexed["benchmark_disposition"].update(status="FAIL", evidence_sha256=result["evidence"]["benchmark_review_sha256"], notes="valid Benchmark authority requires revision")
        teacher = None
        if "teacher_review_packet" in working["bindings"]:
            validate_teacher_review_packet(path_of(working, "teacher_review_packet"), working)
        if "teacher_review" in working["bindings"]:
            teacher, _, errors = validate_teacher_review_files(path_of(working, "teacher_review"),
                source_truth_path=path_of(working, "source_truth"), content_path=path_of(working, "content"),
                require_approved=working["orchestrator_version"] == "2.0", semantic_run=working, **evidence_kwargs(working))
            if errors: raise LifecycleContractError("; ".join(errors))
            if teacher["pipeline_run_id"] != result["pipeline_run_id"]:
                raise LifecycleContractError("diagnostic Teacher Review run mismatch")
            disposition, _ = read_json_object(path_of(working, "benchmark_disposition"), "Benchmark disposition")
            if teacher["benchmark"] != disposition["benchmark"]:
                raise LifecycleContractError("diagnostic Teacher Review disposition mismatch")
            packet = validate_teacher_review_packet(path_of(working, "teacher_review_packet"), working)
            validate_teacher_review_against_packet(teacher, packet)
            indexed["teacher_review"].update(status="PASS", evidence_sha256=result["evidence"]["teacher_review_sha256"], notes="current exact-sample external Teacher authority validated")
            if teacher["decision"] == "REVISION_REQUIRED":
                revision = True
                indexed["teacher_review"].update(status="FAIL", notes="valid Teacher authority requires revision")
        if "final_output" in working["bindings"]:
            _, _, result["final_artifact_inventory"] = validate_run_artifacts(working)
        if "visual_review" in working["bindings"]:
            visual = validate_visual_review_authority(path_of(working, "visual_review"), working, path_of(working, "visual_evidence"))
            indexed["visual_review"].update(status="PASS", evidence_sha256=result["evidence"]["visual_review_authority_sha256"], notes="current exact-scope external Visual authority validated")
            if visual["decision"] == "REVISION_REQUIRED":
                revision = True
                indexed["visual_review"].update(status="FAIL", notes="valid Visual authority requires revision")
        if rank >= STATES.index("VISUAL_REVIEW_APPROVED"):
            # Exclude the final self-referential ACCEPTED transition/evidence; the
            # approved prefix is identical before and after finalization.
            prefix = copy.deepcopy(run["state"])
            prefix.pop("state_fingerprint")
            prefix["current_state"] = "VISUAL_REVIEW_APPROVED"
            prefix["artifacts"]["acceptance_sha256"] = None
            prefix["transitions"] = [row for row in prefix["transitions"] if row["to_state"] != "ACCEPTED"]
            indexed["lifecycle_state"].update(status="PASS", evidence_sha256=semantic_fingerprint(prefix), notes="valid complete visual-approved transition prefix")
        if "production_authorization" in working["bindings"]:
            auth, _ = read_json_object(path_of(working, "production_authorization"), "Authorization")
            result["template"] = {**auth["template"],
                "manifest_sha256": auth["template"]["manifest_sha256"].lower(),
                "template_sha256": auth["template"]["template_sha256"].lower()}
            result["skill_fingerprint"] = skill_tree_fingerprint(SKILL_ROOT)
        if "benchmark_disposition" in working["bindings"]:
            disposition, _ = read_json_object(path_of(working, "benchmark_disposition"), "disposition")
            value = disposition["benchmark"]["disposition"]
            if value in {"BENCHMARK_PARTIAL", "BENCHMARK_UNAVAILABLE", "BENCHMARK_WAIVED_BY_USER"}:
                result["limitations"].append(value)
        if teacher and teacher["decision"] == "APPROVED_WITH_NOTES":
            result["limitations"].append("TEACHER_APPROVED_WITH_NOTES")
        if result["mode"] == "PREVIEW":
            indexed["lifecycle_state"].update(status="PENDING", evidence_sha256=None, notes="PREVIEW cannot hold final production authority")
        result["final_status"] = final_status(result["mode"], gates, revision, result["limitations"])
    except (ValueError, RuntimeError, OSError, TypeError, KeyError, AttributeError, IndexError) as exc:
        result["final_status"] = "FAILED"
        indexed["pipeline_identity"].update(status="FAIL", notes="integrity/linkage validation failed: " + str(exc))
    result["acceptance_fingerprint"] = acceptance_fingerprint(result)
    return result


def validate_acceptance_file(path, run):
    payload, _ = read_json_object(path, "Acceptance 3.0")
    errors = schema_errors(payload, "lesson-acceptance-v3.schema.json")
    if errors or not timezone_aware_timestamp(payload.get("created_at")):
        raise LifecycleContractError("invalid Acceptance schema/timestamp: " + "; ".join(errors))
    if payload["acceptance_fingerprint"] != acceptance_fingerprint(payload):
        raise LifecycleContractError("invalid Acceptance self fingerprint")
    if payload["mode"] != "PRODUCTION" or payload["final_status"] not in {"ACCEPTED", "ACCEPTED_WITH_NOTES"}:
        raise LifecycleContractError("formal Acceptance must be a successful PRODUCTION authority")
    expected = evaluate(run, created_at=payload["created_at"], validate_acceptance=False)
    if payload != expected:
        raise LifecycleContractError("Acceptance is stale or differs from exact chain rederivation")
    return payload


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    run, _ = read_json_object(args.run, "run")
    payload = evaluate(run, run_path=args.run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["final_status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
