"""Opt-in Lesson Lifecycle orchestrator 1.0; stops at PRODUCTION_AUTHORIZED.

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


def content_qa(content_path):
    from package_common import DEFAULT_SCHEMA, DEFAULT_MANIFEST, load_manifest, validate_content_v2_input
    from content_quality import validate_content_quality
    content, raw = read_json_object(content_path, "Content")
    validate_content_v2_input(content, DEFAULT_SCHEMA)
    quality = validate_content_quality(content, load_manifest(DEFAULT_MANIFEST))
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
        "validator": {"skill_version": "2.3.1", "implementation_version": IMPLEMENTATION_VERSION,
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


def full_benchmark(run, benchmark):
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


def validate_run(run, *, run_path=None):
    require(isinstance(run, dict) and set(run) == {
        "orchestrator_version", "mode", "state", "bindings", "run_fingerprint"}, "invalid run envelope")
    require(run["orchestrator_version"] == IMPLEMENTATION_VERSION and run["mode"] in {"PREVIEW", "PRODUCTION"},
            "invalid implementation or mode")
    require(run["run_fingerprint"] == envelope_fingerprint(run), "invalid run fingerprint")
    checked(validate_pipeline_state_payload(run["state"]))
    state = run["state"]
    rank = STATES.index(state["current_state"])
    require(rank <= STATES.index("PRODUCTION_AUTHORIZED"), "LIF-03 stops at PRODUCTION_AUTHORIZED")
    require(run["mode"] != "PREVIEW" or rank < STATES.index("PRODUCTION_AUTHORIZED"),
            "PREVIEW cannot authorize production")
    require(isinstance(run["bindings"], dict), "invalid bindings")
    paths = {}
    for name, binding in run["bindings"].items():
        require(isinstance(binding, dict) and set(binding) == {"path", "sha256"}, "invalid artifact binding")
        paths[name] = path_of(run, name)
        require(binding["sha256"] == inventory(paths[name]), "STALE upstream bytes: " + name)
    assert_distinct_file_paths({**paths, **({"run": run_path} if run_path else {})},
                              outputs={"run"} if run_path else set())
    source, _, errors = validate_source_truth_file(path_of(run, "source_truth"), verify_source_bytes=True)
    checked(errors)
    if run["mode"] == "PRODUCTION":
        require(source_truth_content_verified(source, verify_source_bytes=True), "Source Truth source bytes are unverified")
    field_paths = {field: paths[name] for field, name in ARTIFACT_FIELDS.items()
                   if state["artifacts"][field] is not None and name in paths}
    require(all(state["artifacts"][field] is None or name in paths for field, name in ARTIFACT_FIELDS.items()),
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
        from package_common import DEFAULT_SCHEMA, validate_content_v2_input
        content, _ = read_json_object(path_of(run, "content"), "Content")
        validate_content_v2_input(content, DEFAULT_SCHEMA)
        require(all(content.get(field) == source["course_identity"][field] for field in source["course_identity"]),
                "Content / Source Truth course identity mismatch")
        if run["mode"] == "PRODUCTION" and "benchmark_preparation" not in paths:
            validate_waiver(run)
    if rank >= STATES.index("PREPRODUCTION_QA_PASSED"):
        qa, _ = read_json_object(path_of(run, "preproduction_qa"), "Preproduction QA")
        fresh = content_qa(path_of(run, "content"))
        fresh["created_at"] = qa.get("created_at")
        require(qa == fresh, "STALE or fabricated Preproduction QA evidence")
    review_completed = any(row["to_state"] == "BENCHMARK_REVIEW_COMPLETE" for row in state["transitions"])
    final_disposition_required = state["current_state"] in {
        "READY_FOR_TEACHER_REVIEW", "TEACHER_REVIEW_APPROVED", "PRODUCTION_AUTHORIZED",
    }
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
    if rank >= STATES.index("TEACHER_REVIEW_APPROVED"):
        review, _, errors = validate_teacher_review_files(path_of(run, "teacher_review"),
            source_truth_path=paths["source_truth"], content_path=paths["content"],
            require_approved=True, **evidence_kwargs(run))
        checked(errors)
        require(review["pipeline_run_id"] == state["pipeline_run_id"] and review["benchmark"] == benchmark,
                "Teacher Review does not match pipeline / final Benchmark disposition")
    if rank >= STATES.index("PRODUCTION_AUTHORIZED"):
        authorization, _, errors = validate_production_authorization_files(path_of(run, "production_authorization"),
            source_truth_path=paths["source_truth"], content_path=paths["content"],
            teacher_review_path=paths["teacher_review"], skill_root=SKILL_ROOT,
            verify_runtime_environment=True, **evidence_kwargs(run))
        checked(errors)
        require(authorization["pipeline_run_id"] == state["pipeline_run_id"], "Authorization run mismatch")


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


def execute(command, run_path, **options):
    """One command, one state transition; failed candidates leave state unchanged."""
    run_path = Path(run_path).absolute()
    assert_external_outputs((run_path,))
    with run_lock(run_path):
        if command == "init":
            require(not run_path.exists(), "run is immutable; use a separate new run to iterate")
            run = {"orchestrator_version": IMPLEMENTATION_VERSION, "mode": options["mode"],
                   "state": initial_pipeline_state(options["run_id"]), "bindings": {}, "run_fingerprint": ""}
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
            if run["mode"] == "PRODUCTION" and run["state"]["current_state"] == "SOURCE_TRUTH_FROZEN":
                require(options.get("waiver_evidence"), "PRODUCTION requires preparation or explicit user waiver evidence")
                bind(run, "benchmark_evidence", options["waiver_evidence"])
            bind(run, "content", options["content"])
            advance(run, "AUTHORING_COMPLETE", ("content_sha256", "content"))
        elif command == "validate-preproduction":
            require(run["state"]["current_state"] == "AUTHORING_COMPLETE", "QA requires completed authoring")
            qa = content_qa(path_of(run, "content"))
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
            advance(run, next_state, ("benchmark_disposition_sha256", "benchmark_disposition"))
        elif command == "ready-for-teacher-review":
            require(run["state"]["current_state"] == "BENCHMARK_REVIEW_COMPLETE", "explicit final Benchmark disposition required")
            advance(run, "READY_FOR_TEACHER_REVIEW")
        elif command == "bind-teacher-review":
            bind(run, "teacher_review", options["teacher_review"])
            advance(run, "TEACHER_REVIEW_APPROVED", ("teacher_review_sha256", "teacher_review"))
        elif command == "authorize-production":
            require(run["mode"] == "PRODUCTION", "PREVIEW cannot authorize production")
            bind(run, "production_authorization", options["authorization"])
            advance(run, "PRODUCTION_AUTHORIZED", ("production_authorization_sha256", "production_authorization"))
        else:
            raise LifecycleContractError("unknown command; direct string state updates are forbidden")
        commit_run(run_path, run)
        return run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "freeze-source-truth", "prepare-benchmark", "bind-content",
        "validate-preproduction", "bind-benchmark-disposition", "bind-benchmark-review", "ready-for-teacher-review", "bind-teacher-review",
        "authorize-production", "status"))
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--mode", choices=("PREVIEW", "PRODUCTION"))
    for name in ("source_truth", "source_catalog", "quality_eligibility", "content", "waiver_evidence", "disposition",
                 "benchmark_evidence", "benchmark_authorization", "benchmark_review", "authoring_selection", "holdout_selection",
                 "lesson_reviews_dir", "previous_lesson_content", "previous_review", "previous_lesson_reviews_dir",
                 "teacher_review", "authorization"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path)
    args = vars(parser.parse_args(argv))
    try:
        result = execute(args.pop("command"), args.pop("run"), **args)
        source, _, _ = validate_source_truth_file(path_of(result, "source_truth"), verify_source_bytes=True)
        source_status = ("VALID" if source_truth_content_verified(source, verify_source_bytes=True)
                         else "STRUCTURALLY_VALID_SOURCE_BYTES_UNVERIFIED")
        print(json.dumps({"status": "VALID", "mode": result["mode"], "state": result["state"]["current_state"],
                          "source_truth_status": source_status}))
        return 0
    except (LifecycleContractError, ContractError, ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(1, f"STALE/INVALID: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
