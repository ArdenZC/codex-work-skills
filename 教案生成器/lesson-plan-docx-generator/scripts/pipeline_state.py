"""Pipeline Contract 1.0 state evidence and dependency invalidation helpers.

This module records validated state claims. It does not execute workflow actions.
"""

from __future__ import annotations

import argparse
import copy
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from lifecycle_digest import (
    LifecycleContractError,
    assert_distinct_safe_paths,
    read_json_object,
    schema_errors,
    semantic_fingerprint,
    sha256_bytes,
    sha256_file,
    timezone_aware_timestamp,
    validation_status,
)


STATES = (
    "INTAKE_CONFIRMED",
    "SOURCE_TRUTH_FROZEN",
    "BENCHMARK_PREPARED",
    "AUTHORING_COMPLETE",
    "PREPRODUCTION_QA_PASSED",
    "BENCHMARK_REVIEW_COMPLETE",
    "READY_FOR_TEACHER_REVIEW",
    "TEACHER_REVIEW_APPROVED",
    "PRODUCTION_AUTHORIZED",
    "PRODUCTION_GENERATED",
    "ARTIFACT_QA_PASSED",
    "VISUAL_REVIEW_APPROVED",
    "ACCEPTED",
)
TRANSITIONS = {
    "INTAKE_CONFIRMED": {"SOURCE_TRUTH_FROZEN"},
    "SOURCE_TRUTH_FROZEN": {"BENCHMARK_PREPARED", "AUTHORING_COMPLETE"},
    "BENCHMARK_PREPARED": {"AUTHORING_COMPLETE"},
    "AUTHORING_COMPLETE": {"PREPRODUCTION_QA_PASSED"},
    "PREPRODUCTION_QA_PASSED": {"BENCHMARK_REVIEW_COMPLETE", "READY_FOR_TEACHER_REVIEW"},
    "BENCHMARK_REVIEW_COMPLETE": {"READY_FOR_TEACHER_REVIEW"},
    "READY_FOR_TEACHER_REVIEW": {"TEACHER_REVIEW_APPROVED"},
    "TEACHER_REVIEW_APPROVED": {"PRODUCTION_AUTHORIZED"},
    "PRODUCTION_AUTHORIZED": {"PRODUCTION_GENERATED"},
    "PRODUCTION_GENERATED": {"ARTIFACT_QA_PASSED"},
    "ARTIFACT_QA_PASSED": {"VISUAL_REVIEW_APPROVED"},
    "VISUAL_REVIEW_APPROVED": {"ACCEPTED"},
    "ACCEPTED": set(),
}
FINGERPRINT_EXCLUDED_FIELDS = {"state_fingerprint"}
ARTIFACT_FIELDS = {
    "source_truth_manifest_sha256": "source_truth",
    "content_sha256": "content",
    "benchmark_preparation_sha256": "benchmark_preparation",
    "benchmark_disposition_sha256": "benchmark_disposition",
    "preproduction_qa_sha256": "preproduction_qa",
    "teacher_review_sha256": "teacher_review",
    "production_authorization_sha256": "production_authorization",
    "artifact_manifest_sha256": "artifact_manifest",
    "artifact_qa_sha256": "artifact_qa",
    "visual_review_sha256": "visual_review",
    "acceptance_sha256": "acceptance",
}
REQUIRED_ARTIFACTS = {
    "INTAKE_CONFIRMED": (),
    "SOURCE_TRUTH_FROZEN": ("source_truth_manifest_sha256",),
    "BENCHMARK_PREPARED": ("source_truth_manifest_sha256", "benchmark_preparation_sha256"),
    "AUTHORING_COMPLETE": ("source_truth_manifest_sha256", "content_sha256"),
    "PREPRODUCTION_QA_PASSED": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256"),
    "BENCHMARK_REVIEW_COMPLETE": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256", "benchmark_disposition_sha256"),
    "READY_FOR_TEACHER_REVIEW": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256"),
    "TEACHER_REVIEW_APPROVED": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256", "teacher_review_sha256"),
    "PRODUCTION_AUTHORIZED": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256", "teacher_review_sha256", "production_authorization_sha256"),
    "PRODUCTION_GENERATED": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256", "teacher_review_sha256", "production_authorization_sha256", "artifact_manifest_sha256"),
    "ARTIFACT_QA_PASSED": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256", "teacher_review_sha256", "production_authorization_sha256", "artifact_manifest_sha256", "artifact_qa_sha256"),
    "VISUAL_REVIEW_APPROVED": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256", "teacher_review_sha256", "production_authorization_sha256", "artifact_manifest_sha256", "artifact_qa_sha256", "visual_review_sha256"),
    "ACCEPTED": ("source_truth_manifest_sha256", "content_sha256", "preproduction_qa_sha256", "teacher_review_sha256", "production_authorization_sha256", "artifact_manifest_sha256", "artifact_qa_sha256", "visual_review_sha256", "acceptance_sha256"),
}
DEPENDENCIES = {
    "source_truth": {"content", "benchmark_preparation", "teacher_review", "production_authorization"},
    "content": {"benchmark_review", "teacher_review", "production_authorization"},
    "benchmark_preparation": {"benchmark_review"},
    "benchmark_review": {"benchmark_authorization"},
    "benchmark_authorization": {"benchmark_disposition"},
    "benchmark_disposition": {
        "teacher_review", "production_authorization", "final_artifacts",
        "artifact_qa", "visual_review", "acceptance",
    },
    "teacher_review": {"production_authorization"},
    "production_authorization": {"final_artifacts"},
    "final_artifacts": {"artifact_qa"},
    "artifact_qa": {"visual_review", "acceptance"},
    "visual_review": {"acceptance"},
    "acceptance": set(),
}
SUPPORTED_DEPENDENCY_NODES = frozenset(DEPENDENCIES)
TRANSITION_EVIDENCE_FIELDS = {
    "SOURCE_TRUTH_FROZEN": "source_truth_manifest_sha256",
    "BENCHMARK_PREPARED": "benchmark_preparation_sha256",
    "AUTHORING_COMPLETE": "content_sha256",
    "PREPRODUCTION_QA_PASSED": "preproduction_qa_sha256",
    "BENCHMARK_REVIEW_COMPLETE": "benchmark_disposition_sha256",
    "READY_FOR_TEACHER_REVIEW": "preproduction_qa_sha256",
    "TEACHER_REVIEW_APPROVED": "teacher_review_sha256",
    "PRODUCTION_AUTHORIZED": "production_authorization_sha256",
    "PRODUCTION_GENERATED": "artifact_manifest_sha256",
    "ARTIFACT_QA_PASSED": "artifact_qa_sha256",
    "VISUAL_REVIEW_APPROVED": "visual_review_sha256",
    "ACCEPTED": "acceptance_sha256",
}


def pipeline_state_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(payload, excluded_fields=FINGERPRINT_EXCLUDED_FIELDS)


def initial_pipeline_state(pipeline_run_id: str) -> dict[str, Any]:
    state: dict[str, Any] = {
        "contract_version": "1.0",
        "pipeline_run_id": pipeline_run_id,
        "current_state": "INTAKE_CONFIRMED",
        "artifacts": {field: None for field in ARTIFACT_FIELDS},
        "transitions": [],
        "state_fingerprint": "",
    }
    state["state_fingerprint"] = pipeline_state_fingerprint(state)
    return state


def validate_pipeline_state_payload(payload: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(payload, "pipeline-state.schema.json")
    if errors:
        return errors
    if payload.get("state_fingerprint", "").casefold() != pipeline_state_fingerprint(payload):
        errors.append("state_fingerprint does not match canonical state content")
    if not str(payload.get("pipeline_run_id", "")).strip():
        errors.append("pipeline_run_id must contain non-whitespace text")
    current = "INTAKE_CONFIRMED"
    previous_time: datetime | None = None
    for index, transition in enumerate(payload.get("transitions", [])):
        from_state = transition.get("from_state")
        to_state = transition.get("to_state")
        if from_state == to_state:
            errors.append(f"transitions[{index}] must not be a same-state transition")
        if from_state != current:
            errors.append(f"transitions[{index}].from_state does not continue the recorded state history")
        if to_state not in TRANSITIONS.get(from_state, set()):
            errors.append(f"transitions[{index}] is not a legal forward transition: {from_state} -> {to_state}")
        evidence_field = TRANSITION_EVIDENCE_FIELDS.get(to_state)
        recorded_evidence = transition.get("evidence_sha256")
        indexed_evidence = payload.get("artifacts", {}).get(evidence_field) if evidence_field else None
        if evidence_field and not isinstance(indexed_evidence, str):
            errors.append(f"transitions[{index}] requires indexed artifacts.{evidence_field}")
        elif (
            isinstance(recorded_evidence, str)
            and isinstance(indexed_evidence, str)
            and recorded_evidence.casefold() != indexed_evidence.casefold()
        ):
            errors.append(f"transitions[{index}].evidence_sha256 does not match artifacts.{evidence_field}")
        current = to_state
        stamp = transition.get("recorded_at")
        if timezone_aware_timestamp(stamp):
            parsed = datetime.fromisoformat(stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp)
            if previous_time is not None and parsed < previous_time:
                errors.append(f"transitions[{index}].recorded_at precedes the previous transition")
            previous_time = parsed
    if payload.get("current_state") != current:
        errors.append("current_state does not match replayed transitions")
    artifacts = payload.get("artifacts", {})
    for field in REQUIRED_ARTIFACTS.get(payload.get("current_state"), ()):
        if artifacts.get(field) is None:
            errors.append(f"artifacts.{field} is required in state {payload.get('current_state')}")
    return errors


def advance_pipeline_state(
    payload: Mapping[str, Any],
    next_state: str,
    *,
    recorded_at: str,
    artifact_sha256_updates: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    errors = validate_pipeline_state_payload(payload)
    if errors:
        raise LifecycleContractError("cannot advance invalid Pipeline state: " + "; ".join(errors))
    current = payload["current_state"]
    if next_state not in TRANSITIONS.get(current, set()):
        raise LifecycleContractError(f"illegal Pipeline state transition: {current} -> {next_state}")
    if not timezone_aware_timestamp(recorded_at):
        raise LifecycleContractError("recorded_at must include a timezone")
    result = copy.deepcopy(dict(payload))
    result["current_state"] = next_state
    for field, digest in (artifact_sha256_updates or {}).items():
        if field not in ARTIFACT_FIELDS or not isinstance(digest, str) or len(digest) != 64:
            raise LifecycleContractError(f"invalid Pipeline artifact digest update: {field}")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise LifecycleContractError(f"invalid SHA-256 digest for {field}") from exc
        result["artifacts"][field] = digest.lower()
    evidence_field = TRANSITION_EVIDENCE_FIELDS[next_state]
    evidence_sha256 = result["artifacts"].get(evidence_field)
    if not isinstance(evidence_sha256, str):
        raise LifecycleContractError(f"transition to {next_state} requires artifacts.{evidence_field}")
    result["transitions"].append({
        "from_state": current, "to_state": next_state,
        "evidence_sha256": evidence_sha256,
        "recorded_at": recorded_at,
    })
    result["state_fingerprint"] = pipeline_state_fingerprint(result)
    errors = validate_pipeline_state_payload(result)
    if errors:
        raise LifecycleContractError("advanced Pipeline state is invalid: " + "; ".join(errors))
    return result


def stale_downstream(changed_nodes: str | set[str] | tuple[str, ...] | list[str]) -> set[str]:
    """Return every transitive downstream node invalidated by changed evidence."""
    pending = [changed_nodes] if isinstance(changed_nodes, str) else list(changed_nodes)
    stale: set[str] = set()
    while pending:
        node = pending.pop()
        if node not in SUPPORTED_DEPENDENCY_NODES:
            raise LifecycleContractError(f"unknown lifecycle dependency node: {node}")
        for downstream in DEPENDENCIES[node]:
            if downstream not in stale:
                stale.add(downstream)
                pending.append(downstream)
    return stale


def _required_evidence_fields(state: Mapping[str, Any]) -> set[str]:
    """Return every artifact claimed by the current state or its recorded history."""
    artifacts = state.get("artifacts", {})
    required = set(REQUIRED_ARTIFACTS.get(state.get("current_state"), ()))
    required.update(field for field, digest in artifacts.items() if digest is not None)
    for transition in state.get("transitions", []):
        field = TRANSITION_EVIDENCE_FIELDS.get(transition.get("to_state"))
        if field is not None:
            required.add(field)
    return required


def validate_pipeline_artifact_bytes(
    payload: Mapping[str, Any],
    artifact_paths: Mapping[str, str | Path],
) -> list[str]:
    """Verify byte-layer evidence separately from schema/state semantics."""
    errors: list[str] = []
    artifacts = payload.get("artifacts", {})
    for field, path in artifact_paths.items():
        if field not in ARTIFACT_FIELDS:
            errors.append(f"unknown Pipeline artifact field: {field}")
            continue
        try:
            actual = sha256_file(path)
        except LifecycleContractError as exc:
            errors.append(f"cannot verify {field} bytes: {exc}")
            continue
        expected = artifacts.get(field)
        if not isinstance(expected, str) or expected.casefold() != actual:
            errors.append(f"artifacts.{field} does not match the supplied artifact bytes")
    return errors


def validate_pipeline_state_files(
    state_path: str | Path,
    *,
    artifact_paths: Mapping[str, str | Path] | None = None,
    source_truth_path: str | Path | None = None,
    content_path: str | Path | None = None,
    teacher_review_path: str | Path | None = None,
    production_authorization_path: str | Path | None = None,
    benchmark_authorization_path: str | Path | None = None,
    benchmark_review_path: str | Path | None = None,
    benchmark_evidence_path: str | Path | None = None,
    skill_root: str | Path | None = None,
    template_manifest_path: str | Path | None = None,
    template_path: str | Path | None = None,
) -> tuple[dict[str, Any], bytes, list[str]]:
    path_set: dict[str, str | Path] = {"pipeline_state": state_path}
    errors: list[str] = []
    direct_fields = {
        "source_truth_manifest_sha256": source_truth_path,
        "content_sha256": content_path,
        "teacher_review_sha256": teacher_review_path,
        "production_authorization_sha256": production_authorization_path,
    }
    supplied_artifacts = dict(artifact_paths or {})
    for key in supplied_artifacts:
        if key in direct_fields and direct_fields[key] is not None:
            errors.append(f"Pipeline artifact {key} was supplied both directly and through artifact_paths")
    for key, value in (artifact_paths or {}).items():
        if key not in direct_fields or direct_fields[key] is None:
            path_set[f"artifact_{key}"] = value
    for label, value in (
        ("source_truth", source_truth_path),
        ("content", content_path),
        ("teacher_review", teacher_review_path),
        ("production_authorization", production_authorization_path),
        ("benchmark_authorization", benchmark_authorization_path),
        ("benchmark_review", benchmark_review_path),
        ("benchmark_evidence", benchmark_evidence_path),
    ):
        if value is not None:
            path_set[label] = value
    assert_distinct_safe_paths(path_set)
    state, raw = read_json_object(state_path, "pipeline_state")
    structural_errors = schema_errors(state, "pipeline-state.schema.json")
    if structural_errors:
        return state, raw, structural_errors
    errors.extend(validate_pipeline_state_payload(state))
    direct_paths = {
        "source_truth_manifest_sha256": source_truth_path,
        "content_sha256": content_path,
        "teacher_review_sha256": teacher_review_path,
        "production_authorization_sha256": production_authorization_path,
    }
    supplied_artifacts.update({
        key: value for key, value in direct_paths.items()
        if value is not None and key not in supplied_artifacts
    })
    for field in sorted(_required_evidence_fields(state)):
        if field not in supplied_artifacts:
            errors.append(f"state evidence requires an artifact file for artifacts.{field}")
    errors.extend(validate_pipeline_artifact_bytes(state, supplied_artifacts))

    state_rank = STATES.index(state.get("current_state")) if state.get("current_state") in STATES else -1
    if state_rank >= STATES.index("SOURCE_TRUTH_FROZEN") and source_truth_path is None:
        errors.append("state requires --source-truth for authority linkage")
    if state_rank >= STATES.index("AUTHORING_COMPLETE") and content_path is None:
        errors.append("state requires --content for authority linkage")
    if source_truth_path is not None and state_rank >= STATES.index("SOURCE_TRUTH_FROZEN"):
        try:
            from source_truth import source_truth_content_verified, validate_source_truth_file

            manifest, _manifest_raw, source_errors = validate_source_truth_file(source_truth_path, verify_source_bytes=True)
            errors.extend(source_errors)
            if (
                state_rank >= STATES.index("PRODUCTION_AUTHORIZED")
                and not source_errors
                and not source_truth_content_verified(manifest, verify_source_bytes=True)
            ):
                errors.append("Source Truth source bytes are unverified; Pipeline authority requires offline byte verification")
        except LifecycleContractError as exc:
            errors.append(f"cannot validate Source Truth authority: {exc}")
    if state_rank >= STATES.index("TEACHER_REVIEW_APPROVED"):
        if teacher_review_path is None or source_truth_path is None or content_path is None:
            errors.append("approved Teacher Review state requires Source Truth, Content and Teacher Review files")
        else:
            try:
                from teacher_review import validate_teacher_review_files

                review, review_raw, review_errors = validate_teacher_review_files(
                    teacher_review_path,
                    source_truth_path=source_truth_path,
                    content_path=content_path,
                    benchmark_authorization_path=benchmark_authorization_path,
                    benchmark_review_path=benchmark_review_path,
                    benchmark_evidence_path=benchmark_evidence_path,
                    require_approved=True,
                )
                errors.extend(review_errors)
                if review.get("pipeline_run_id") != state.get("pipeline_run_id"):
                    errors.append("Teacher Review pipeline_run_id does not match Pipeline state")
                recorded_review_sha = state.get("artifacts", {}).get("teacher_review_sha256")
                if not isinstance(recorded_review_sha, str) or recorded_review_sha.casefold() != sha256_bytes(review_raw):
                    errors.append("Pipeline teacher_review_sha256 does not match Teacher Review bytes")
            except LifecycleContractError as exc:
                errors.append(f"cannot validate Teacher Review authority: {exc}")
    if state_rank >= STATES.index("PRODUCTION_AUTHORIZED"):
        if production_authorization_path is None or source_truth_path is None or content_path is None or teacher_review_path is None:
            errors.append("Production Authorized state requires Source Truth, Content, Teacher Review and Authorization files")
        else:
            try:
                from production_authorization import validate_production_authorization_files

                authorization, auth_raw, auth_errors = validate_production_authorization_files(
                    production_authorization_path,
                    source_truth_path=source_truth_path,
                    content_path=content_path,
                    teacher_review_path=teacher_review_path,
                    benchmark_authorization_path=benchmark_authorization_path,
                    benchmark_review_path=benchmark_review_path,
                    benchmark_evidence_path=benchmark_evidence_path,
                    skill_root=skill_root or Path(__file__).resolve().parents[1],
                    template_manifest_path=template_manifest_path,
                    template_path=template_path,
                    verify_runtime_environment=False,
                )
                errors.extend(auth_errors)
                if authorization.get("pipeline_run_id") != state.get("pipeline_run_id"):
                    errors.append("Production Authorization pipeline_run_id does not match Pipeline state")
                recorded_authorization_sha = state.get("artifacts", {}).get("production_authorization_sha256")
                if not isinstance(recorded_authorization_sha, str) or recorded_authorization_sha.casefold() != sha256_bytes(auth_raw):
                    errors.append("Pipeline production_authorization_sha256 does not match Authorization bytes")
            except LifecycleContractError as exc:
                errors.append(f"cannot validate Production Authorization: {exc}")
    return state, raw, errors


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("state", type=Path)
    validate.add_argument("--source-truth", type=Path)
    validate.add_argument("--content", type=Path)
    validate.add_argument("--teacher-review", type=Path)
    validate.add_argument("--authorization", type=Path)
    validate.add_argument("--benchmark-authorization", type=Path)
    validate.add_argument("--benchmark-review", type=Path)
    validate.add_argument("--benchmark-evidence", type=Path)
    validate.add_argument("--skill-root", type=Path)
    validate.add_argument("--template-manifest", type=Path)
    validate.add_argument("--template", type=Path)
    validate.add_argument("--artifact", action="append", default=[], metavar="FIELD=PATH")
    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("state", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "fingerprint":
            payload, _raw = read_json_object(args.state, "pipeline_state")
            print(pipeline_state_fingerprint(payload))
            return 0
        artifacts: dict[str, Path] = {}
        for item in args.artifact:
            field, separator, value = item.partition("=")
            if not separator or not field or not value or field in artifacts:
                raise LifecycleContractError(f"invalid or duplicate --artifact value: {item}")
            artifacts[field] = Path(value)
        state, raw, errors = validate_pipeline_state_files(
            args.state,
            artifact_paths=artifacts,
            source_truth_path=args.source_truth,
            content_path=args.content,
            teacher_review_path=args.teacher_review,
            production_authorization_path=args.authorization,
            benchmark_authorization_path=args.benchmark_authorization,
            benchmark_review_path=args.benchmark_review,
            benchmark_evidence_path=args.benchmark_evidence,
            skill_root=args.skill_root,
            template_manifest_path=args.template_manifest,
            template_path=args.template,
        )
        self_errors = validate_pipeline_state_payload(state)
        status = validation_status(self_errors, errors)
    except LifecycleContractError as exc:
        errors = [str(exc)]
        raw = b""
        status = "INVALID"
    if errors:
        print(status)
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"VALID pipeline_state_sha256={sha256_bytes(raw)} state={state['current_state']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
