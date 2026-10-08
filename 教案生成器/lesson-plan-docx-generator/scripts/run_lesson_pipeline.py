"""Opt-in Lesson Lifecycle orchestrator 1.0; final artifact / visual / Acceptance 3.0 authority chain.

Commands bind external judgments; this engine neither authors lessons nor grants
human approval. A run envelope contains the unchanged Pipeline State Contract 1.0.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path

from course_scope_grounding import format_scope_failures, validate_course_scope_grounding
from benchmark_preparation import (
    ARTIFACT_NAMES, assert_external_outputs, json_bytes, preparation_bundle, timestamp, validate_preparation_files,
)
from exemplar_contract import ContractError, assert_distinct_file_paths
from exemplar_split import _replace_bundle
from lifecycle_digest import (
    LifecycleContractError, read_json_object, semantic_fingerprint, sha256_bytes,
    sha256_file, skill_tree_fingerprint,
)
from pipeline_state import (
    ARTIFACT_FIELDS, STATES, advance_pipeline_state, initial_pipeline_state,
    validate_pipeline_artifact_bytes, validate_pipeline_state_payload,
)
from lesson_lifecycle_applicability import require_lesson_lifecycle_applicable
from source_truth import validate_source_truth_file, source_truth_content_verified
from teacher_review import validate_teacher_review_files
from production_authorization import validate_production_authorization_files

SKILL_ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION_VERSION = "1.0"


def require(condition, message):
    if not condition:
        raise LifecycleContractError(message)


def checked(errors):
    require(not errors, "; ".join(errors))


def inventory(path):
    path = Path(path)
    assert_distinct_file_paths({"evidence": path})
    if not path.is_dir():
        return sha256_file(path)
    entries = {}
    for child in sorted(path.rglob("*")):
        require(not child.is_symlink(), "evidence directory contains symlink")
        if child.is_file():
            entries[child.relative_to(path).as_posix()] = sha256_file(child)
        else:
            require(child.is_dir(), "evidence directory contains special file")
    require(entries, "evidence directory is empty")
    return semantic_fingerprint(entries)


def bind(run, name, path):
    value = Path(path).absolute()
    # sha256_file checks ordinary files and all path components; directory entries
    # are checked individually and distinct-path checks reject directory aliases.
    binding = {"path": str(value), "sha256": inventory(value)}
    require(name not in run["bindings"] or run["bindings"][name] == binding,
            "existing upstream binding is immutable; create a new run: " + name)
    run["bindings"][name] = binding


def path_of(run, name):
    require(name in run["bindings"], f"missing actual {name} artifact")
    return Path(run["bindings"][name]["path"])


def envelope_fingerprint(run):
    return semantic_fingerprint(run, excluded_fields={"run_fingerprint"})


def content_qa(content_path, source_truth_path, *, require_local_outline, implementation_version=IMPLEMENTATION_VERSION):
    from package_common import DEFAULT_SCHEMA, DEFAULT_MANIFEST, load_manifest, validate_content_v2_input
    from content_quality import validate_content_quality
    content, raw = read_json_object(content_path, "Content")
    validate_content_v2_input(content, DEFAULT_SCHEMA)
    quality = validate_content_quality(
        content,
        load_manifest(DEFAULT_MANIFEST),
        source_truth_path=str(source_truth_path),
        content_path=str(content_path),
        require_local_outline=require_local_outline,
    )
    # Persist the existing machine report, rather than reimplementing its gates.
    result = {
        "qa_evidence_version": "1.0", "content_sha256": sha256_bytes(raw),
        "content_contract_version": content["content_contract_version"],
        "content_validation": "PASS", "content_quality": {
            "status": quality["status"], "errors": quality["errors"],
            "report_json": json.dumps(quality, ensure_ascii=False, sort_keys=True),
        },
        "hour_ledger": {"lesson_count": len(content["lessons"]),
                        "lesson_hours": str(sum(row["hours"] for row in content["lessons"])),
                        "delivery_plan": content["delivery_plan"]},
        "validator": {"skill_version": "2.3.1", "implementation_version": implementation_version,
                      "installed_skill_fingerprint": skill_tree_fingerprint(SKILL_ROOT)},
        "created_at": timestamp(),
    }
    result["qa_fingerprint"] = semantic_fingerprint(result, excluded_fields={"created_at", "qa_fingerprint"})
    return result


def evidence_kwargs(run):
    return {key + "_path": path_of(run, key) for key in
            ("benchmark_authorization", "benchmark_review", "benchmark_evidence") if key in run["bindings"]}


def validate_waiver(run):
    evidence, _ = read_json_object(path_of(run, "benchmark_evidence"), "user waiver evidence")
    require(evidence.get("decision") == "WAIVED_BY_USER"
            and isinstance(evidence.get("user_identity"), str) and evidence["user_identity"].strip()
            and isinstance(evidence.get("waiver_reference"), str) and evidence["waiver_reference"].strip(),
            "waiver requires explicit externally supplied user consent evidence")
    require(evidence.get("pipeline_run_id") == run["state"]["pipeline_run_id"], "waiver run mismatch")
    for field, name in (("source_truth_manifest_sha256", "source_truth"), ("content_sha256", "content")):
        require(evidence.get(field) == inventory(path_of(run, name)), "STALE waiver " + field)
    return evidence


def benchmark_claims(run):
    from benchmark_authorization import (
        derive_benchmark_authorization_claims, validate_authorization_matches_claims,
    )
    from package_common import DEFAULT_SCHEMA
    inputs = {
        "lesson_content_path": path_of(run, "content"),
        "catalog_path": path_of(run, "projected_catalog"),
        "split_path": path_of(run, "split"),
        "authoring_pack_path": path_of(run, "authoring_pack"),
        "holdout_pack_path": path_of(run, "holdout_pack"),
        "schema_path": DEFAULT_SCHEMA,
    }
    for name in ("authoring_selection", "holdout_selection", "benchmark_review", "lesson_reviews_dir"):
        inputs[name + "_path" if name != "lesson_reviews_dir" else name] = path_of(run, name)
    for name in ("previous_lesson_content", "previous_review", "previous_lesson_reviews_dir"):
        if name in run["bindings"]:
            inputs[name + "_path" if name != "previous_lesson_reviews_dir" else name] = path_of(run, name)
    claims = derive_benchmark_authorization_claims(**inputs)
    return claims


def full_benchmark(run, benchmark):
    from benchmark_authorization import validate_authorization_matches_claims
    claims = benchmark_claims(run)
    require(claims["benchmark_decision"] != "REVISION_REQUIRED", "Benchmark REVISION_REQUIRED blocks advancement")
    if benchmark["disposition"] == "BENCHMARK_REVIEW_COMPLETE":
        authorization, _ = read_json_object(path_of(run, "benchmark_authorization"), "Benchmark Authorization")
        checked(validate_authorization_matches_claims(authorization, claims))
    else:
        require(claims["benchmark_status"] == benchmark["disposition"], "final disposition differs from full Review")


def validate_disposition(run):
    disposition, _ = read_json_object(path_of(run, "benchmark_disposition"), "Benchmark disposition")
    require(set(disposition) == {"pipeline_run_id", "source_truth_manifest_sha256", "content_sha256", "benchmark"},
            "disposition requires explicit binding envelope")
    require(disposition["pipeline_run_id"] == run["state"]["pipeline_run_id"], "disposition run mismatch")
    for field, name in (("source_truth_manifest_sha256", "source_truth"), ("content_sha256", "content")):
        require(disposition[field] == inventory(path_of(run, name)), "STALE disposition " + field)
    benchmark = disposition["benchmark"]
    require(isinstance(benchmark, dict) and set(benchmark) == {
        "disposition", "authorization_sha256", "review_sha256", "evidence_sha256", "waiver_reference"},
        "explicit Lifecycle Benchmark fields required")
    final = benchmark["disposition"]
    require(final in {"BENCHMARK_REVIEW_COMPLETE", "BENCHMARK_PARTIAL", "BENCHMARK_UNAVAILABLE", "BENCHMARK_WAIVED_BY_USER"},
            "BENCHMARK_NOT_EXECUTED or implicit Benchmark is forbidden")
    require(("benchmark_review" in run["bindings"]) == (benchmark["review_sha256"] is not None),
            "final disposition must bind the actual Benchmark Review")
    if final == "BENCHMARK_WAIVED_BY_USER":
        require(benchmark["review_sha256"] is None, "waiver is not a Benchmark Review")
    for field, name in (("authorization_sha256", "benchmark_authorization"),
                        ("review_sha256", "benchmark_review"), ("evidence_sha256", "benchmark_evidence")):
        if benchmark[field] is not None:
            require(benchmark[field] == inventory(path_of(run, name)), "STALE Benchmark " + field)
    if final == "BENCHMARK_REVIEW_COMPLETE":
        require(benchmark["authorization_sha256"] is not None and benchmark["review_sha256"] is not None,
                "completed Benchmark requires real Authorization and Review")
        require("benchmark_preparation" in run["bindings"], "completed Benchmark requires quality preparation")
        full_benchmark(run, benchmark)
    else:
        require(benchmark["evidence_sha256"] is not None, "disposition requires immutable external evidence")
        evidence, _ = read_json_object(path_of(run, "benchmark_evidence"), "disposition evidence")
        for field in ("pipeline_run_id", "source_truth_manifest_sha256", "content_sha256"):
            require(evidence.get(field) == disposition[field], "STALE evidence " + field)
        if final == "BENCHMARK_WAIVED_BY_USER":
            validate_waiver(run)
            require(benchmark["waiver_reference"] == evidence["waiver_reference"], "waiver reference mismatch")
        else:
            preparation, _ = read_json_object(path_of(run, "benchmark_preparation"), "preparation")
            require(evidence.get("benchmark_preparation_sha256") == inventory(path_of(run, "benchmark_preparation")),
                    "disposition evidence must bind quality-gated preparation bytes")
            require(evidence.get("disposition") == final and isinstance(evidence.get("notes"), str)
                    and evidence["notes"].strip(), "explicit partial/unavailable evidence notes required")
            if "benchmark_review" in run["bindings"]:
                full_benchmark(run, benchmark)
            else:
                require(preparation["disposition"] == final,
                        "available preparation requires full Review before partial disposition")
    return benchmark


def validate_run_upstream(run, *, run_path=None):
    core = {"orchestrator_version", "mode", "state", "bindings", "run_fingerprint"}
    extras = {"output_workspace", "semantic_dependency_inventory"}
    require(isinstance(run, dict) and core <= set(run) <= core | extras, "invalid run envelope")
    require("semantic_dependency_inventory" not in run or run["orchestrator_version"] == "2.0", "legacy run cannot carry O2 authority")
    require(run["orchestrator_version"] in {"1.0", "2.0"} and run["mode"] in {"PREVIEW", "PRODUCTION"},
            "invalid implementation or mode")
    require(run["state"]["contract_version"] == run["orchestrator_version"], "state/envelope version downgrade")
    require(run["run_fingerprint"] == envelope_fingerprint(run), "invalid run fingerprint")
    checked(validate_pipeline_state_payload(run["state"]))
    state = run["state"]
    rank = STATES.index(state["current_state"])
    require(run["mode"] != "PREVIEW" or rank < STATES.index("PRODUCTION_AUTHORIZED"),
            "PREVIEW cannot authorize production")
    require(isinstance(run["bindings"], dict), "invalid bindings")
    paths = {}
    for name, binding in run["bindings"].items():
        require(isinstance(binding, dict) and set(binding) == {"path", "sha256"}, "invalid artifact binding")
        paths[name] = path_of(run, name)
        require(binding["sha256"] == inventory(paths[name]), "STALE upstream bytes: " + name)
    assert_distinct_file_paths({**{name: path for name, path in paths.items() if name != "final_output"}, **({"run": run_path} if run_path else {})},
                              outputs={"run"} if run_path else set())
    if "final_output" in paths:
        from final_artifacts import output_path
        # The output directory necessarily contains the two bound machine files;
        # all other aliases still use the existing strict overlap validator.
        require(isinstance(run.get("output_workspace"), str), "final output requires its frozen workspace root")
        if run_path is not None:
            from path_safety import paths_equal
            require(paths_equal(run["output_workspace"], Path(run_path).absolute().parent), "run workspace differs from frozen output workspace")
        output_path(run, Path(run["output_workspace"]) / "run.json", paths["final_output"])
    source, _, errors = validate_source_truth_file(path_of(run, "source_truth"), verify_source_bytes=True)
    checked(errors)
    if run["mode"] == "PRODUCTION":
        require(source_truth_content_verified(source, verify_source_bytes=True), "Source Truth source bytes are unverified")
    field_paths = {field: paths[name] for field, name in ARTIFACT_FIELDS.items()
                   if state["artifacts"].get(field) is not None and name in paths}
    require(all(state["artifacts"].get(field) is None or name in paths for field, name in ARTIFACT_FIELDS.items()),
            "state contains naked artifact digest without actual file")
    checked(validate_pipeline_artifact_bytes(state, field_paths))
    if "benchmark_preparation" in paths:
        preparation, errors = validate_preparation_files(paths["benchmark_preparation"],
                                                        **{name: path_of(run, name) for name in ARTIFACT_NAMES})
        checked(errors)
        require(preparation["pipeline_run_id"] == state["pipeline_run_id"], "preparation run mismatch")
        catalog, _ = read_json_object(paths["source_catalog"], "source Catalog")
        require(catalog["course_context"] == source["course_identity"], "Catalog / Source Truth course identity mismatch")
    elif rank >= STATES.index("BENCHMARK_PREPARED") and state["current_state"] == "BENCHMARK_PREPARED":
        raise LifecycleContractError("BENCHMARK_PREPARED requires actual quality preparation")
    if rank >= STATES.index("AUTHORING_COMPLETE"):
        content, _ = read_json_object(path_of(run, "content"), "Content")
        require_lesson_lifecycle_applicable(content)
        require(all(content.get(field) == source["course_identity"][field] for field in source["course_identity"]),
                "Content / Source Truth course identity mismatch")
        from course_scope_grounding import format_scope_failures, validate_course_scope_grounding
        scope = validate_course_scope_grounding(
            content,
            path_of(run, "source_truth"),
            content_path=path_of(run, "content"),
            require_local_outline=run["mode"] == "PRODUCTION",
        )
        require(
            scope["status"] not in {"failed", "unverified"} if run["mode"] == "PRODUCTION" else scope["status"] != "failed",
            "course-scope grounding failed: " + "; ".join(format_scope_failures(scope)[:8]),
        )
        if run["mode"] == "PRODUCTION" and "benchmark_preparation" not in paths:
            validate_waiver(run)
    if rank >= STATES.index("PREPRODUCTION_QA_PASSED"):
        qa, _ = read_json_object(path_of(run, "preproduction_qa"), "Preproduction QA")
        fresh = content_qa(
            path_of(run, "content"),
            path_of(run, "source_truth"),
            require_local_outline=run["mode"] == "PRODUCTION",
            implementation_version=run["orchestrator_version"],
        )
        fresh["created_at"] = qa.get("created_at")
        require(qa == fresh, "STALE or fabricated Preproduction QA evidence")
    benchmark = None
    review_completed = any(row["to_state"] == "BENCHMARK_REVIEW_COMPLETE" for row in state["transitions"])
    final_disposition_required = rank >= STATES.index("READY_FOR_TEACHER_REVIEW")
    if review_completed or final_disposition_required:
        require(state["artifacts"]["benchmark_disposition_sha256"] is not None,
                "final Benchmark disposition must be indexed in state artifacts")
        benchmark = validate_disposition(run)
        require(benchmark["disposition"] == "BENCHMARK_WAIVED_BY_USER" or "benchmark_preparation" in paths,
                "non-waived lifecycle requires quality-gated preparation")
        if review_completed:
            require(benchmark["review_sha256"] is not None,
                    "BENCHMARK_REVIEW_COMPLETE history requires actual Benchmark Review evidence")
        else:
            require(benchmark["review_sha256"] is None,
                    "actual Benchmark Review requires BENCHMARK_REVIEW_COMPLETE history")
    if run["orchestrator_version"] == "2.0":
        from semantic_lifecycle import scope
        if "semantic_scope_review" in paths or rank >= STATES.index("READY_FOR_TEACHER_REVIEW"):
            _, report = scope(run)
            if rank >= STATES.index("READY_FOR_TEACHER_REVIEW"):
                require(report["whole_course_disposition"] in {"PASS", "HUMAN_REVIEW_REQUIRED"}, "semantic REVISION_REQUIRED blocks READY")
    return benchmark


def validate_run_authorized(run, *, run_path=None):
    benchmark = validate_run_upstream(run, run_path=run_path)
    paths = {name: path_of(run, name) for name in run["bindings"]}
    state = run["state"]
    rank = STATES.index(state["current_state"])
    from teacher_review_packet import validate_teacher_review_packet, validate_teacher_review_against_packet
    packet = None
    if "teacher_review_packet" in paths:
        packet = validate_teacher_review_packet(paths["teacher_review_packet"], run)
    if rank >= STATES.index("TEACHER_REVIEW_APPROVED"):
        require(packet is not None, "canonical Teacher approval requires teacher_review_packet")
        review, _, errors = validate_teacher_review_files(path_of(run, "teacher_review"),
            source_truth_path=paths["source_truth"], content_path=paths["content"],
            require_approved=True, semantic_run=run, **evidence_kwargs(run))
        checked(errors)
        require(review["pipeline_run_id"] == state["pipeline_run_id"] and review["benchmark"] == benchmark,
                "Teacher Review does not match pipeline / final Benchmark disposition")
        validate_teacher_review_against_packet(review, packet)
        if run["orchestrator_version"] == "2.0":
            from semantic_lifecycle import teacher
            teacher(run, review)
    if rank >= STATES.index("PRODUCTION_AUTHORIZED"):
        authorization, _, errors = validate_production_authorization_files(path_of(run, "production_authorization"),
            source_truth_path=paths["source_truth"], content_path=paths["content"],
            teacher_review_path=paths["teacher_review"], skill_root=SKILL_ROOT,
            verify_runtime_environment=True, semantic_run=run, **evidence_kwargs(run))
        checked(errors)
        require(authorization["pipeline_run_id"] == state["pipeline_run_id"], "Authorization run mismatch")
        require(authorization["contract_version"] == run["orchestrator_version"], "PA cannot downgrade O2 authority")


def validate_run(run, *, run_path=None, validate_acceptance=True):
    validate_run_authorized(run, run_path=run_path)
    rank = STATES.index(run["state"]["current_state"])
    from final_artifacts import validate_run_artifacts
    from visual_review_authority import validate_visual_review_packet, validate_visual_review_authority
    if rank >= STATES.index("PRODUCTION_GENERATED"):
        validate_run_artifacts(run)
    if "visual_review_packet" in run["bindings"]:
        validate_visual_review_packet(path_of(run, "visual_review_packet"), run)
    if "visual_review" in run["bindings"]:
        authority = validate_visual_review_authority(path_of(run, "visual_review"), run, path_of(run, "visual_evidence"))
        if rank >= STATES.index("VISUAL_REVIEW_APPROVED"):
            require(authority["decision"] == "PASSED", "Visual REVISION_REQUIRED blocks advancement")
    if rank >= STATES.index("VISUAL_REVIEW_APPROVED"):
        require("visual_review" in run["bindings"] and "visual_review_packet" in run["bindings"], "Visual approval requires actual Authority and Packet")
    if rank >= STATES.index("ACCEPTED") and validate_acceptance:
        from acceptance_v3 import validate_acceptance_file
        validate_acceptance_file(path_of(run, "acceptance"), run)


@contextmanager
def run_lock(run_path):
    lock = Path(str(run_path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def commit_run(run_path, run):
    run["run_fingerprint"] = envelope_fingerprint(run)
    validate_run(run, run_path=run_path)
    _replace_bundle((Path(run_path),), (run,))


def advance(run, next_state, artifact=None):
    updates = {}
    if artifact:
        field, name = artifact
        updates[field] = inventory(path_of(run, name))
    run["state"] = advance_pipeline_state(run["state"], next_state,
                                           recorded_at=timestamp(), artifact_sha256_updates=updates)



def publish_sidecar(run, run_path, name, destination, payload, *, next_state=None, artifact_field=None):
    """Validate actual candidate bytes, then publish sidecar and state as one bundle."""
    import tempfile
    from path_safety import paths_overlap
    assert_external_outputs((destination,))
    from source_truth import source_truth_local_file_paths
    source_path = path_of(run, "source_truth")
    source, _ = read_json_object(source_path, "Source Truth")
    from path_safety import assert_output_path_safe
    assert_output_path_safe(destination, source_truth_local_file_paths(source, source_path).values())
    assert_distinct_file_paths({"run": run_path, "candidate": destination,
        **{key: path_of(run, key) for key in run["bindings"] if key != "final_output"}}, outputs={"candidate"})
    if "final_output" in run["bindings"]:
        require(not paths_overlap(destination, path_of(run, "final_output")), "sidecar must remain outside frozen final output")
    with tempfile.TemporaryDirectory(prefix="lesson-final-sidecar-", dir=run_path.parent) as directory:
        staged = Path(directory) / (name + ".json")
        staged.write_bytes(json_bytes(payload))
        bind(run, name, staged)
        if next_state:
            advance(run, next_state, (artifact_field, name))
        run["run_fingerprint"] = envelope_fingerprint(run)
        validate_run(run)
        run["bindings"][name]["path"] = str(destination)
        run["run_fingerprint"] = envelope_fingerprint(run)
        _replace_bundle((destination, run_path), (payload, run))
    return run


def execute(command, run_path, **options):
    """Most commands advance one transition; Packet preparation only freezes evidence."""
    run_path = Path(run_path).absolute()
    assert_external_outputs((run_path,))
    if command == "evaluate-acceptance":
        from acceptance_v3 import evaluate
        original, _ = read_json_object(run_path, "pipeline run")
        inputs = {name: options[name] for name in ("teacher_review", "visual_review", "visual_evidence", "benchmark_review", "authoring_selection", "holdout_selection", "lesson_reviews_dir", "previous_lesson_content", "previous_review", "previous_lesson_reviews_dir") if options.get(name)}
        return evaluate(original, diagnostic_inputs=inputs, run_path=run_path)
    with run_lock(run_path):
        if command == "init":
            require(not run_path.exists(), "run is immutable; use a separate new run to iterate")
            version = options.get("orchestrator_version", "1.0")
            require(version in {"1.0", "2.0"}, "unsupported orchestrator version")
            run = {"orchestrator_version": version, "mode": options["mode"],
                   "state": initial_pipeline_state(options["run_id"], contract_version=version), "bindings": {}, "run_fingerprint": ""}
            bind(run, "source_truth", options["source_truth"])
            commit_run(run_path, run)
            return run
        original, _ = read_json_object(run_path, "pipeline run")
        validate_run(original, run_path=run_path)
        run = copy.deepcopy(original)
        if command == "status":
            return run
        if command == "freeze-source-truth":
            advance(run, "SOURCE_TRUTH_FROZEN", ("source_truth_manifest_sha256", "source_truth"))
        elif command == "prepare-benchmark":
            require(run["state"]["current_state"] == "SOURCE_TRUTH_FROZEN", "prepare requires frozen Source Truth")
            bind(run, "source_catalog", options["source_catalog"])
            bind(run, "quality_eligibility", options["quality_eligibility"])
            # Generated bundle and run state commit together, restoring old bytes on failure.
            bundle = preparation_bundle(path_of(run, "source_catalog"), path_of(run, "quality_eligibility"),
                                        pipeline_run_id=run["state"]["pipeline_run_id"])
            names = (*ARTIFACT_NAMES[2:], "benchmark_preparation")
            destinations = tuple(run_path.parent / (run_path.stem + "-artifacts") / (name + ".json") for name in names)
            assert_distinct_file_paths({"run": run_path, **{name: path_of(run, name) for name in run["bindings"]},
                                       **dict(zip(names, destinations))}, outputs=set(names))
            # Stage in an independent sibling directory, validate using real staged bytes,
            # then convert only path locators to the final immutable bundle destinations.
            import tempfile
            with tempfile.TemporaryDirectory(prefix="lesson-preparation-", dir=run_path.parent) as directory:
                staged = tuple(Path(directory) / (name + ".json") for name in names)
                for name, path, payload in zip(names, staged, bundle):
                    path.write_bytes(json_bytes(payload))
                    bind(run, name, path)
                advance(run, "BENCHMARK_PREPARED", ("benchmark_preparation_sha256", "benchmark_preparation"))
                run["run_fingerprint"] = envelope_fingerprint(run)
                validate_run(run)
                for name, path in zip(names, destinations):
                    run["bindings"][name]["path"] = str(path)
                run["run_fingerprint"] = envelope_fingerprint(run)
                _replace_bundle((*destinations, run_path), (*bundle, run))
            return run
        elif command == "bind-content":
            content, _ = read_json_object(options["content"], "Content")
            require_lesson_lifecycle_applicable(content)
            from package_common import DEFAULT_SCHEMA, validate_content_v2_input
            from course_scope_grounding import format_scope_failures, validate_course_scope_grounding
            validate_content_v2_input(content, DEFAULT_SCHEMA)
            scope = validate_course_scope_grounding(
                content,
                path_of(run, "source_truth"),
                content_path=options["content"],
                require_local_outline=run["mode"] == "PRODUCTION",
                )
            require(
                scope["status"] not in {"failed", "unverified"} if run["mode"] == "PRODUCTION" else scope["status"] != "failed",
                "course-scope grounding failed before Content binding: "
                + "; ".join(format_scope_failures(scope)[:8]),
            )
            if run["mode"] == "PRODUCTION" and run["state"]["current_state"] == "SOURCE_TRUTH_FROZEN":
                require(options.get("waiver_evidence"), "PRODUCTION requires preparation or explicit user waiver evidence")
                bind(run, "benchmark_evidence", options["waiver_evidence"])
            bind(run, "content", options["content"])
            advance(run, "AUTHORING_COMPLETE", ("content_sha256", "content"))
        elif command == "validate-preproduction":
            require(run["state"]["current_state"] == "AUTHORING_COMPLETE", "QA requires completed authoring")
            qa = content_qa(
                path_of(run, "content"),
                path_of(run, "source_truth"),
                require_local_outline=run["mode"] == "PRODUCTION",
                implementation_version=run["orchestrator_version"],
            )
            qa_path = run_path.parent / (run_path.stem + "-preproduction-qa.json")
            assert_distinct_file_paths({"run": run_path, **{name: path_of(run, name) for name in run["bindings"]},
                                       "qa": qa_path}, outputs={"qa"})
            import tempfile
            with tempfile.TemporaryDirectory(prefix="lesson-qa-", dir=run_path.parent) as directory:
                staged = Path(directory) / "qa.json"
                staged.write_bytes(json_bytes(qa))
                bind(run, "preproduction_qa", staged)
                advance(run, "PREPRODUCTION_QA_PASSED", ("preproduction_qa_sha256", "preproduction_qa"))
                run["run_fingerprint"] = envelope_fingerprint(run)
                validate_run(run)
                run["bindings"]["preproduction_qa"]["path"] = str(qa_path)
                run["run_fingerprint"] = envelope_fingerprint(run)
                _replace_bundle((qa_path, run_path), (qa, run))
            return run
        elif command in {"bind-benchmark-disposition", "bind-benchmark-review"}:
            require(run["state"]["current_state"] == "PREPRODUCTION_QA_PASSED", "Benchmark binding requires passed QA")
            review_inputs = ("benchmark_authorization", "benchmark_review", "authoring_selection",
                             "holdout_selection", "lesson_reviews_dir", "previous_lesson_content",
                             "previous_review", "previous_lesson_reviews_dir")
            if command == "bind-benchmark-review":
                require(options.get("benchmark_review"), "bind-benchmark-review requires an actual Benchmark Review artifact")
            else:
                require(not any(options.get(name) or name in run["bindings"] for name in review_inputs),
                        "use bind-benchmark-review for actual Benchmark Review evidence")
            bind(run, "benchmark_disposition", options["disposition"])
            for name in ("benchmark_evidence", *review_inputs):
                if options.get(name):
                    bind(run, name, options[name])
            validate_disposition(run)
            next_state = "BENCHMARK_REVIEW_COMPLETE" if command == "bind-benchmark-review" else "READY_FOR_TEACHER_REVIEW"
            if run["orchestrator_version"] == "2.0" and command == "bind-benchmark-disposition":
                run["state"]["artifacts"]["benchmark_disposition_sha256"] = run["bindings"]["benchmark_disposition"]["sha256"]
                from pipeline_state import pipeline_state_fingerprint
                run["state"]["state_fingerprint"] = pipeline_state_fingerprint(run["state"])
            else:
                advance(run, next_state, ("benchmark_disposition_sha256", "benchmark_disposition"))
        elif command == "bind-semantic-scope-review":
            require(run["orchestrator_version"] == "2.0", "semantic binding requires explicit O2 run")
            require(run["state"]["current_state"] in {"PREPRODUCTION_QA_PASSED", "BENCHMARK_REVIEW_COMPLETE"}, "semantic binding requires pre-READY QA")
            from semantic_lifecycle import context, FIELDS, LATER_ENTRIES
            from pipeline_state import pipeline_state_fingerprint
            ctx = context()
            run["semantic_dependency_inventory"] = [dict(row) for key, row in ctx.inventory.entries.items()
                if key not in LATER_ENTRIES]
            for field, key in FIELDS.items():
                if key != "teacher_approval_receipt":
                    bind(run, key, ctx.inventory.entries[key]["path"])
                    run["state"]["artifacts"][field] = run["bindings"][key]["sha256"]
            run["state"]["state_fingerprint"] = pipeline_state_fingerprint(run["state"])
        elif command == "ready-for-teacher-review":
            allowed = {"BENCHMARK_REVIEW_COMPLETE", "PREPRODUCTION_QA_PASSED"} if run["orchestrator_version"] == "2.0" else {"BENCHMARK_REVIEW_COMPLETE"}
            require(run["state"]["current_state"] in allowed, "explicit final Benchmark disposition required")
            advance(run, "READY_FOR_TEACHER_REVIEW")
        elif command == "prepare-teacher-review":
            require(run["state"]["current_state"] == "READY_FOR_TEACHER_REVIEW",
                    "prepare-teacher-review requires READY_FOR_TEACHER_REVIEW")
            require("teacher_review_packet" not in run["bindings"], "Packet is already frozen; use status or create a new run")
            from teacher_review_packet import build_teacher_review_packet
            packet = build_teacher_review_packet(run)
            packet_path = run_path.parent / (run_path.stem + "-teacher-review-packet.json")
            assert_distinct_file_paths({"run": run_path, **{name: path_of(run, name) for name in run["bindings"]},
                                       "teacher_review_packet": packet_path}, outputs={"teacher_review_packet"})
            import tempfile
            with tempfile.TemporaryDirectory(prefix="lesson-teacher-packet-", dir=run_path.parent) as directory:
                staged = Path(directory) / "packet.json"
                staged.write_bytes(json_bytes(packet))
                bind(run, "teacher_review_packet", staged)
                run["run_fingerprint"] = envelope_fingerprint(run)
                validate_run(run)
                run["bindings"]["teacher_review_packet"]["path"] = str(packet_path)
                run["run_fingerprint"] = envelope_fingerprint(run)
                _replace_bundle((packet_path, run_path), (packet, run))
            return run
        elif command == "bind-teacher-review":
            require("teacher_review_packet" in run["bindings"], "canonical Teacher Review requires a prepared Packet")
            bind(run, "teacher_review", options["teacher_review"])
            if run["orchestrator_version"] == "2.0":
                from semantic_lifecycle import context
                from pipeline_state import pipeline_state_fingerprint
                ctx = context()
                bind(run, "teacher_approval_receipt", ctx.inventory.entries["teacher_approval_receipt"]["path"])
                run["state"]["artifacts"]["teacher_approval_receipt_sha256"] = run["bindings"]["teacher_approval_receipt"]["sha256"]
                run["state"]["state_fingerprint"] = pipeline_state_fingerprint(run["state"])
            advance(run, "TEACHER_REVIEW_APPROVED", ("teacher_review_sha256", "teacher_review"))
        elif command == "authorize-production":
            require(run["mode"] == "PRODUCTION", "PREVIEW cannot authorize production")
            bind(run, "production_authorization", options["authorization"])
            advance(run, "PRODUCTION_AUTHORIZED", ("production_authorization_sha256", "production_authorization"))
        elif command == "generate-production":
            require(run["mode"] == "PRODUCTION", "PREVIEW cannot generate production")
            require(run["state"]["current_state"] == "PRODUCTION_AUTHORIZED", "generation requires current Production Authorization")
            from final_artifacts import output_path, validate_artifact_files
            from package_common import DEFAULT_MANIFEST, manifest_template_path, load_manifest
            import subprocess
            import sys
            output = output_path(run, run_path, options.get("output_dir") or run_path.parent / (run_path.stem + "-final"))
            require(not output.exists(), "canonical generation needs a new output directory; old authorized artifacts are immutable")
            args = [sys.executable, "-B", str(SKILL_ROOT / "scripts/generate_lesson_plans.py"),
                    "--tasks-json", str(path_of(run, "content")), "--output-dir", str(output),
                    "--source-truth", str(path_of(run, "source_truth")),
                    "--render", "--run-id", run["state"]["pipeline_run_id"],
                    "--template", str(manifest_template_path(load_manifest(DEFAULT_MANIFEST))),
                    "--manifest", str(DEFAULT_MANIFEST)]
            disposition = validate_disposition(run)
            if disposition["disposition"] == "BENCHMARK_REVIEW_COMPLETE":
                args += ["--benchmark-mode", "required", "--benchmark-authorization", str(path_of(run, "benchmark_authorization"))]
                inputs = {"projected_catalog": "catalog", "split": "split", "authoring_pack": "authoring-pack",
                    "authoring_selection": "authoring-selection", "holdout_pack": "holdout-pack", "holdout_selection": "holdout-selection",
                    "benchmark_review": "review", "lesson_reviews_dir": "lesson-reviews-dir", "previous_review": "previous-review",
                    "previous_lesson_reviews_dir": "previous-lesson-reviews-dir", "previous_lesson_content": "previous-content"}
                for name, flag in inputs.items():
                    if name in run["bindings"]:
                        args += ["--benchmark-" + flag, str(path_of(run, name))]
            else:
                args += ["--benchmark-mode", "none"]
            try:
                if run["orchestrator_version"] == "2.0":
                    from generate_lesson_plans import main as generate
                    generate(args[3:], o2_run=original)
                    result = subprocess.CompletedProcess(args, 0, "", "")
                else:
                    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
                require(result.returncode == 0, "canonical generator failed: " + result.stdout[-3000:] + result.stderr[-3000:])
                auth, _ = read_json_object(path_of(run, "production_authorization"), "Authorization")
                validate_artifact_files(output, path_of(run, "content"), auth, run["state"]["pipeline_run_id"])
                run["output_workspace"] = str(run_path.parent)
                bind(run, "final_output", output)
                bind(run, "artifact_manifest", output / "artifact-manifest.json")
                bind(run, "artifact_qa", output / "qa-report.json")
                advance(run, "PRODUCTION_GENERATED", ("artifact_manifest_sha256", "artifact_manifest"))
            except BaseException:
                if run["orchestrator_version"] == "2.0" and output.exists():
                    import shutil
                    shutil.rmtree(output)
                raise
        elif command == "validate-artifacts":
            require(run["mode"] == "PRODUCTION" and run["state"]["current_state"] == "PRODUCTION_GENERATED", "Artifact QA requires PRODUCTION_GENERATED")
            from final_artifacts import validate_run_artifacts
            validate_run_artifacts(run)
            advance(run, "ARTIFACT_QA_PASSED", ("artifact_qa_sha256", "artifact_qa"))
        elif command == "prepare-visual-review":
            require(run["mode"] == "PRODUCTION" and run["state"]["current_state"] == "ARTIFACT_QA_PASSED", "Visual Packet requires ARTIFACT_QA_PASSED")
            require("visual_review_packet" not in run["bindings"], "Visual Packet is already frozen")
            from visual_review_authority import build_visual_review_packet
            packet = build_visual_review_packet(run)
            destination = run_path.parent / (run_path.stem + "-visual-review-packet.json")
            return publish_sidecar(run, run_path, "visual_review_packet", destination, packet)
        elif command == "bind-visual-review":
            require(run["mode"] == "PRODUCTION" and run["state"]["current_state"] == "ARTIFACT_QA_PASSED", "Visual binding requires ARTIFACT_QA_PASSED")
            bind(run, "visual_evidence", options["visual_evidence"])
            bind(run, "visual_review", options["visual_review"])
            run["run_fingerprint"] = envelope_fingerprint(run)
            from visual_review_authority import validate_visual_review_authority
            authority = validate_visual_review_authority(path_of(run, "visual_review"), run, path_of(run, "visual_evidence"))
            require(authority["decision"] == "PASSED", "Visual REVISION_REQUIRED does not advance state")
            advance(run, "VISUAL_REVIEW_APPROVED", ("visual_review_sha256", "visual_review"))
        elif command == "finalize-acceptance":
            require(run["mode"] == "PRODUCTION" and run["state"]["current_state"] == "VISUAL_REVIEW_APPROVED", "finalization requires PRODUCTION VISUAL_REVIEW_APPROVED")
            from acceptance_v3 import evaluate
            report = evaluate(run)
            require(report["final_status"] in {"ACCEPTED", "ACCEPTED_WITH_NOTES"}, "Acceptance gates are not complete")
            destination = run_path.parent / (run_path.stem + "-lesson-acceptance-v3.json")
            return publish_sidecar(run, run_path, "acceptance", destination, report, next_state="ACCEPTED", artifact_field="acceptance_sha256")
        else:
            raise LifecycleContractError("unknown command; direct string state updates are forbidden")
        try:
            commit_run(run_path, run)
        except BaseException:
            if command == "generate-production" and run["orchestrator_version"] == "2.0":
                import shutil
                shutil.rmtree(output)
            raise
        return run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "freeze-source-truth", "prepare-benchmark", "bind-content",
        "validate-preproduction", "bind-benchmark-disposition", "bind-benchmark-review", "bind-semantic-scope-review", "ready-for-teacher-review", "prepare-teacher-review", "bind-teacher-review",
        "authorize-production", "generate-production", "validate-artifacts", "prepare-visual-review", "bind-visual-review", "evaluate-acceptance", "finalize-acceptance", "status"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--mode", choices=("PREVIEW", "PRODUCTION"))
    parser.add_argument("--orchestrator-version", choices=("1.0", "2.0"), default="1.0")
    for name in ("source_truth", "source_catalog", "quality_eligibility", "content", "waiver_evidence", "disposition",
                 "benchmark_evidence", "benchmark_authorization", "benchmark_review", "authoring_selection", "holdout_selection",
                 "lesson_reviews_dir", "previous_lesson_content", "previous_review", "previous_lesson_reviews_dir",
                 "teacher_review", "authorization", "output_dir", "visual_review", "visual_evidence"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path)
    args = vars(parser.parse_args(argv))
    try:
        result = execute(args.pop("command"), args.pop("run"), **args)
        if "final_status" in result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["final_status"] == "FAILED" else 0
        source, _, _ = validate_source_truth_file(path_of(result, "source_truth"), verify_source_bytes=True)
        source_status = ("VALID" if source_truth_content_verified(source, verify_source_bytes=True)
                         else "STRUCTURALLY_VALID_SOURCE_BYTES_UNVERIFIED")
        diagnostics = {}
        if result["orchestrator_version"] == "2.0":
            diagnostics["production_authorized"] = result["mode"] == "PRODUCTION" and STATES.index(result["state"]["current_state"]) >= STATES.index("PRODUCTION_AUTHORIZED")
            diagnostics["semantic_review_status"] = "VALID" if "semantic_scope_review" in result["bindings"] else "MISSING"
            diagnostics["semantic_disposition"] = read_json_object(path_of(result, "semantic_scope_review"), "semantic report")[0]["whole_course_disposition"] if "semantic_scope_review" in result["bindings"] else None
        print(json.dumps({"status": "VALID", "mode": result["mode"], "state": result["state"]["current_state"],
                          "source_truth_status": source_status, **diagnostics}))
        return 0
    except (LifecycleContractError, ContractError, ValueError, RuntimeError, OSError, TypeError, KeyError) as exc:
        parser.exit(1, f"STALE/INVALID: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
