"""Offline visual scope and external human authority; never performs visual judgment."""
from pathlib import Path

from benchmark_preparation import timestamp
from lifecycle_digest import LifecycleContractError, read_json_object, schema_errors, semantic_fingerprint, sha256_file, timezone_aware_timestamp
from final_artifacts import validate_run_artifacts
from visual_sampling import visual_sample_selection
from validate_visual_inspection import validate_visual_inspection

POLICY_VERSION = "1.0"


def required_pages(page_count):
    if type(page_count) is not int or page_count < 1:
        raise LifecycleContractError("page count must be a positive integer")
    return sorted({1, page_count, (page_count + 1) // 2})


def fingerprint(payload, field):
    return semantic_fingerprint(payload, excluded_fields={"created_at", field})


def checked(payload, schema, field):
    errors = schema_errors(payload, schema)
    if errors or not timezone_aware_timestamp(payload.get("created_at")):
        raise LifecycleContractError("invalid visual contract: " + "; ".join(errors))
    if payload[field] != fingerprint(payload, field):
        raise LifecycleContractError("invalid visual self fingerprint")


def context(run):
    from run_lesson_pipeline import validate_run_authorized, path_of
    from pipeline_state import STATES
    validate_run_authorized(run)
    if run["mode"] != "PRODUCTION" or STATES.index(run["state"]["current_state"]) < STATES.index("ARTIFACT_QA_PASSED"):
        raise LifecycleContractError("Visual scope requires PRODUCTION ARTIFACT_QA_PASSED or later")
    manifest, qa, inventory = validate_run_artifacts(run)
    content, _ = read_json_object(path_of(run, "content"), "Content")
    return manifest, qa, content


def build_visual_review_packet(run, *, created_at=None):
    from run_lesson_pipeline import path_of
    manifest, qa, content = context(run)
    names = [row["final_docx_path"] for row in manifest["artifacts"]]
    sample = visual_sample_selection(content, qa, {"docx_files": names}, manifest)
    records = {row["final_docx_path"]: row for row in manifest["artifacts"]}
    rows = []
    for item in sample["sample"]:
        record = records.get(item["file"])
        if record is None or record["lesson_id"] != item["lesson_id"]:
            raise LifecycleContractError("visual sample is not bound to Artifact manifest")
        rows.append({**item, "pdf_file": record["final_pdf_path"],
                     "page_count": record["actual_pdf_page_count"],
                     "required_pages": required_pages(record["actual_pdf_page_count"])})
    result = {"contract_version": "1.0", "pipeline_run_id": run["state"]["pipeline_run_id"],
        "content_sha256": sha256_file(path_of(run, "content")),
        "artifact_manifest_sha256": sha256_file(path_of(run, "artifact_manifest")),
        "artifact_qa_sha256": sha256_file(path_of(run, "artifact_qa")),
        "sampling_policy_version": POLICY_VERSION, "sampling_policy": sample["policy"],
        "required_sample": rows, "created_at": created_at or timestamp()}
    result["packet_fingerprint"] = fingerprint(result, "packet_fingerprint")
    checked(result, "visual-review-packet.schema.json", "packet_fingerprint")
    return result


def validate_visual_review_packet(path, run):
    payload, _ = read_json_object(path, "Visual Packet")
    checked(payload, "visual-review-packet.schema.json", "packet_fingerprint")
    if payload != build_visual_review_packet(run, created_at=payload["created_at"]):
        raise LifecycleContractError("Visual Packet does not match exact current rederivation")
    return payload


def inspection(run, packet, evidence_path):
    from run_lesson_pipeline import path_of
    # The existing inspector validates both PASSED and explicit failed evidence;
    # legacy callers retain their passed-only default.
    evidence = validate_visual_inspection(path_of(run, "final_output"), path_of(run, "artifact_qa"), evidence_path, require_passed=False)
    for row in packet["required_sample"]:
        if row["file"] not in evidence["inspected_files"] or not set(row["required_pages"]) <= set(evidence["inspected_pages"].get(row["file"], [])):
            raise LifecycleContractError("visual evidence omits required files/pages")
    return evidence


def build_visual_review_authority(run, *, evidence_path, decision, notes, created_at=None):
    from run_lesson_pipeline import path_of
    packet = validate_visual_review_packet(path_of(run, "visual_review_packet"), run)
    evidence = inspection(run, packet, evidence_path)
    if decision not in {"PASSED", "REVISION_REQUIRED"} or (decision == "PASSED") != (evidence["status"] == "passed"):
        raise LifecycleContractError("external visual decision is inconsistent with the eleven checks")
    result = {"contract_version": "1.0", "pipeline_run_id": packet["pipeline_run_id"],
        **{name: packet[name] for name in ("content_sha256", "artifact_manifest_sha256", "artifact_qa_sha256", "sampling_policy_version", "sampling_policy", "required_sample")},
        "visual_review_packet_sha256": sha256_file(path_of(run, "visual_review_packet")),
        "visual_inspection_evidence_sha256": sha256_file(evidence_path),
        "inspected_files": evidence["inspected_files"], "inspected_pages": evidence["inspected_pages"],
        "decision": decision, "notes": notes, "created_at": created_at or timestamp()}
    result["authority_fingerprint"] = fingerprint(result, "authority_fingerprint")
    checked(result, "visual-review-authority.schema.json", "authority_fingerprint")
    return result


def validate_visual_review_authority(path, run, evidence_path):
    payload, _ = read_json_object(path, "Visual Authority")
    checked(payload, "visual-review-authority.schema.json", "authority_fingerprint")
    fresh = build_visual_review_authority(run, evidence_path=evidence_path, decision=payload["decision"], notes=payload["notes"], created_at=payload["created_at"])
    if payload != fresh:
        raise LifecycleContractError("Visual Authority is stale or differs from actual inspection evidence")
    return payload


def main():
    import argparse
    from exemplar_split import _replace_bundle
    from benchmark_preparation import assert_external_outputs
    from exemplar_contract import assert_distinct_file_paths
    from run_lesson_pipeline import validate_run, path_of
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--decision", choices=("PASSED", "REVISION_REQUIRED"), required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run, _ = read_json_object(args.run, "run")
    validate_run(run, run_path=args.run)
    assert_external_outputs((args.output,))
    from source_truth import source_truth_local_file_paths
    from path_safety import assert_output_path_safe
    source_path = path_of(run, "source_truth")
    source, _ = read_json_object(source_path, "Source Truth")
    assert_output_path_safe(args.output, source_truth_local_file_paths(source, source_path).values())
    assert_distinct_file_paths({"run": args.run, "evidence": args.evidence, "output": args.output,
        **{name: path_of(run, name) for name in run["bindings"] if name != "final_output"}}, outputs={"output"})
    from path_safety import paths_overlap
    if paths_overlap(args.output, path_of(run, "final_output")) or paths_overlap(args.evidence, path_of(run, "final_output")):
        raise LifecycleContractError("human evidence and Authority must remain outside frozen final output")
    payload = build_visual_review_authority(run, evidence_path=args.evidence, decision=args.decision, notes=args.notes)
    _replace_bundle((args.output,), (payload,))


if __name__ == "__main__":
    main()
