"""Validation helpers for the Lesson 2.3 Benchmark authorization sidecar."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import re
from pathlib import Path
from typing import Any

from exemplar_contract import canonical_json_bytes, schema_errors

SKILL_VERSION = "2.3.1"
CONTENT_CONTRACT_VERSION = "2.3"
COMPATIBLE_CONTENT_CONTRACT_VERSIONS = {"2.2", "2.3"}
AUTHORIZATION_CONTRACT_VERSION = "1.0"
# Keep in lockstep with the explicit provenance enum in
# schemas/benchmark-authorization.schema.json. Authorization 1.0 accepts only
# the released 2.3.0 and 2.3.1 skill versions.
SUPPORTED_AUTHORIZATION_SKILL_VERSIONS = frozenset({"2.3.0", "2.3.1"})
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_STATUS_DECISIONS = {
    "BENCHMARK_REVIEW_COMPLETE": {"NO_REVISION_REQUIRED"},
    "BENCHMARK_GAPS_FOUND": {"REVISION_REQUIRED"},
    "BENCHMARK_PARTIAL": {"BENCHMARK_PARTIAL", "HUMAN_REVIEW_REQUIRED"},
    "BENCHMARK_UNAVAILABLE": {"BENCHMARK_UNAVAILABLE"},
    "HUMAN_REVIEW_REQUIRED": {"HUMAN_REVIEW_REQUIRED"},
}


def authorization_fingerprint(payload: Mapping[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "authorization_fingerprint"}
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def derive_benchmark_authorization_claims(
    *,
    lesson_content_path: Path,
    catalog_path: Path,
    split_path: Path,
    authoring_pack_path: Path,
    authoring_selection_path: Path,
    holdout_pack_path: Path,
    holdout_selection_path: Path,
    benchmark_review_path: Path,
    lesson_reviews_dir: Path,
    schema_path: Path,
    previous_lesson_content_path: Path | None = None,
    previous_review_path: Path | None = None,
    previous_lesson_reviews_dir: Path | None = None,
    allow_test_fixture: bool = False,
) -> dict[str, Any]:
    """Validate the complete evidence chain and derive timestamp-free claims."""

    from exemplar_contract import (
        ContractError,
        assert_distinct_file_paths,
        load_json,
        load_json_bytes,
        sha256_json,
        validate_authoring_selection_payload,
        validate_catalog_payload,
        validate_pack_payload,
    )
    from exemplar_split import validate_split_payload
    from package_common import apply_reviewed_lesson_content, validate_content_v2_input
    from validate_benchmark_review import validate_benchmark_review_file

    evidence_paths = {
        "Lesson Content": lesson_content_path,
        "schema": schema_path,
        "Catalog": catalog_path,
        "Split": split_path,
        "Authoring Pack": authoring_pack_path,
        "Authoring Selection": authoring_selection_path,
        "Holdout Pack": holdout_pack_path,
        "Holdout Selection": holdout_selection_path,
        "Benchmark Review": benchmark_review_path,
        "per-Lesson Reviews": lesson_reviews_dir,
    }
    if previous_lesson_content_path is not None:
        evidence_paths["Round 1 Lesson Content"] = previous_lesson_content_path
    if previous_review_path is not None:
        evidence_paths["Round 1 Benchmark Review"] = previous_review_path
    if previous_lesson_reviews_dir is not None:
        evidence_paths["Round 1 per-Lesson Reviews"] = previous_lesson_reviews_dir
    assert_distinct_file_paths(evidence_paths)

    lesson_content, lesson_content_bytes = load_json_bytes(lesson_content_path, "Lesson Content")
    content_contract_version = str(lesson_content.get("content_contract_version") or "")
    if content_contract_version not in COMPATIBLE_CONTENT_CONTRACT_VERSIONS:
        raise ContractError("Benchmark authorization requires Lesson Content Contract 2.2 or 2.3")
    validate_content_v2_input(lesson_content, schema_path, allow_test_fixture=allow_test_fixture)
    # This enforces pedagogical-review and provenance contracts before claims are issued.
    reviewed_content = apply_reviewed_lesson_content(lesson_content)
    semantic_digest = str((lesson_content.get("authoring_provenance") or {}).get("final_content_sha256", ""))

    catalog = load_json(catalog_path, "Catalog")
    split = load_json(split_path, "Split")
    authoring_pack = load_json(authoring_pack_path, "Authoring Pack")
    authoring_selection = load_json(authoring_selection_path, "Authoring Selection")
    holdout_pack = load_json(holdout_pack_path, "Holdout Pack")
    holdout_selection = load_json(holdout_selection_path, "Holdout Selection")
    catalog_errors = validate_catalog_payload(catalog)
    if catalog_errors:
        raise ContractError("Catalog validation failed: " + "; ".join(catalog_errors))
    split_errors = validate_split_payload(split, catalog)
    if split_errors:
        raise ContractError("Split validation failed: " + "; ".join(split_errors))
    authoring_pack_errors = validate_pack_payload(authoring_pack, catalog, split, expected_role="authoring")
    if authoring_pack_errors:
        raise ContractError("Authoring Pack validation failed: " + "; ".join(authoring_pack_errors))
    authoring_errors = validate_authoring_selection_payload(
        authoring_selection, catalog, split, authoring_pack, reviewed_content
    )
    if authoring_errors:
        raise ContractError("Authoring Selection validation failed: " + "; ".join(authoring_errors))
    if not re.fullmatch(r"[a-fA-F0-9]{64}", semantic_digest):
        raise ContractError("authoring_provenance.final_content_sha256 is missing or invalid")

    review, review_errors = validate_benchmark_review_file(
        benchmark_review_path,
        catalog_path=catalog_path,
        split_path=split_path,
        authoring_pack_path=authoring_pack_path,
        authoring_selection_path=authoring_selection_path,
        holdout_pack_path=holdout_pack_path,
        holdout_selection_path=holdout_selection_path,
        lesson_content_path=lesson_content_path,
        lesson_reviews_dir=lesson_reviews_dir,
        previous_review_path=previous_review_path,
        previous_lesson_reviews_dir=previous_lesson_reviews_dir,
        previous_lesson_content_path=previous_lesson_content_path,
        require_full_linkage=True,
    )
    if review_errors:
        raise ContractError("Benchmark Review full-linkage validation failed: " + "; ".join(review_errors))

    summary = review["course_summary"]
    return {
        "benchmark_authorization_version": AUTHORIZATION_CONTRACT_VERSION,
        "skill_version": SKILL_VERSION,
        "content_contract_version": content_contract_version,
        "benchmark_run_id": review["benchmark_run_id"],
        "review_round": review["review_round"],
        "benchmark_status": review["status"],
        "benchmark_decision": summary["decision"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_fingerprint": split["split_fingerprint"],
        "authoring_pack_fingerprint": authoring_pack["pack_fingerprint"],
        "authoring_selection_sha256": sha256_json(authoring_selection),
        "holdout_pack_fingerprint": holdout_pack["pack_fingerprint"],
        "holdout_selection_sha256": review["holdout_selection_sha256"],
        "benchmark_review_sha256": hashlib.sha256(benchmark_review_path.read_bytes()).hexdigest(),
        "source_lesson_content_sha256": hashlib.sha256(lesson_content_bytes).hexdigest(),
        "source_final_content_sha256": semantic_digest,
        "context_mode": summary["context_mode"],
    }


def publication_eligibility_errors(claims: Mapping[str, Any]) -> list[str]:
    if claims.get("benchmark_decision") == "REVISION_REQUIRED":
        return ["Benchmark requires revision before final production authorization."]
    return []


def validate_authorization_matches_claims(
    payload: Mapping[str, Any], claims: Mapping[str, Any]
) -> list[str]:
    errors = validate_authorization_payload(
        payload,
        source_lesson_content_sha256=str(claims.get("source_lesson_content_sha256", "")),
        source_final_content_sha256=str(claims.get("source_final_content_sha256", "")),
    )
    if payload.get("skill_version") not in SUPPORTED_AUTHORIZATION_SKILL_VERSIONS:
        errors.append("skill_version is not a supported Authorization 1.0 provenance version")
    ignored_claims = {"created_at", "authorization_fingerprint", "skill_version"}
    actual_claims = {
        key: value for key, value in payload.items()
        if key not in ignored_claims
    }
    expected_claims = {key: value for key, value in claims.items() if key not in ignored_claims}
    if actual_claims != expected_claims:
        mismatched = sorted(set(actual_claims) | set(expected_claims))
        mismatched = [key for key in mismatched if actual_claims.get(key) != expected_claims.get(key)]
        errors.append(
            "Benchmark Authorization claims do not match full evidence"
            + (": " + ", ".join(mismatched) if mismatched else "")
        )
    errors.extend(publication_eligibility_errors(claims))
    return errors


def authorization_manifest_block(payload: Mapping[str, Any], authorization_sha256: str) -> dict[str, Any]:
    return {
        "status": payload["benchmark_status"],
        "decision": payload["benchmark_decision"],
        "contract_version": payload["benchmark_authorization_version"],
        "benchmark_run_id": payload["benchmark_run_id"],
        "review_round": payload["review_round"],
        "context_mode": payload["context_mode"],
        "catalog_fingerprint": payload["catalog_fingerprint"],
        "split_fingerprint": payload["split_fingerprint"],
        "authoring_pack_fingerprint": payload["authoring_pack_fingerprint"],
        "authoring_selection_sha256": payload["authoring_selection_sha256"],
        "holdout_pack_fingerprint": payload["holdout_pack_fingerprint"],
        "holdout_selection_sha256": payload["holdout_selection_sha256"],
        "benchmark_review_sha256": payload["benchmark_review_sha256"],
        "benchmark_authorization_sha256": authorization_sha256.lower(),
        "source_lesson_content_sha256": payload["source_lesson_content_sha256"],
        "source_final_content_sha256": payload["source_final_content_sha256"],
    }


def validate_manifest_benchmark_binding(
    manifest: Mapping[str, Any], payload: Mapping[str, Any], authorization_sha256: str
) -> list[str]:
    errors: list[str] = []
    if manifest.get("lesson_skill_capability") != "2.3-benchmark-linked":
        errors.append("Benchmark Authorization requires lesson_skill_capability=2.3-benchmark-linked")
    benchmark = manifest.get("teaching_exemplar_benchmark")
    if not isinstance(benchmark, Mapping):
        errors.append("artifact manifest teaching_exemplar_benchmark must be an object")
        return errors
    expected = authorization_manifest_block(payload, authorization_sha256)
    if dict(benchmark) != expected:
        mismatched = sorted(
            key for key in set(benchmark) | set(expected)
            if benchmark.get(key) != expected.get(key)
        )
        errors.append("artifact manifest Benchmark block does not match the Authorization: " + ", ".join(mismatched))
    return errors


def _timezone_aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_authorization_payload(
    payload: Mapping[str, Any],
    *,
    source_lesson_content_sha256: str | None = None,
    source_final_content_sha256: str | None = None,
) -> list[str]:
    errors = schema_errors(payload, "benchmark-authorization.schema.json")
    if errors:
        return errors
    if not _timezone_aware_timestamp(payload.get("created_at")):
        errors.append("created_at must be a valid timezone-aware timestamp")
    if payload.get("authorization_fingerprint", "").casefold() != authorization_fingerprint(payload).casefold():
        errors.append("authorization_fingerprint does not match canonical authorization fields")
    if payload.get("benchmark_decision") not in _STATUS_DECISIONS.get(payload.get("benchmark_status"), set()):
        errors.append("benchmark_status and benchmark_decision are inconsistent")
    if source_lesson_content_sha256 is not None and str(payload.get("source_lesson_content_sha256", "")).casefold() != source_lesson_content_sha256.casefold():
        errors.append("source_lesson_content_sha256 does not match the supplied Lesson Content bytes")
    if source_final_content_sha256 is not None and str(payload.get("source_final_content_sha256", "")).casefold() != source_final_content_sha256.casefold():
        errors.append("source_final_content_sha256 does not match reviewed Lesson content")
    return errors


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))
