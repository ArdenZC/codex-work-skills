"""Shared authority checks for Lifecycle's completed Benchmark sidecars."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lifecycle_digest import LifecycleContractError, read_json_object, sha256_bytes


def validate_completed_benchmark_evidence(
    benchmark: Mapping[str, Any],
    *,
    benchmark_authorization_path: str | Path | None,
    benchmark_review_path: str | Path | None,
    content: Mapping[str, Any],
    content_raw: bytes,
) -> list[str]:
    """Validate bounded Benchmark authority semantics and Lifecycle byte bindings."""

    if benchmark_authorization_path is None or benchmark_review_path is None:
        return ["BENCHMARK_REVIEW_COMPLETE requires Benchmark Authorization and Review files for semantic validation"]

    try:
        import benchmark_authorization as benchmark_authorization_module
        from validate_benchmark_review import validate_benchmark_review_file

        authorization, authorization_raw = read_json_object(
            benchmark_authorization_path, "benchmark_authorization"
        )
        review_path = Path(benchmark_review_path)
        review, review_errors = validate_benchmark_review_file(
            review_path,
            require_full_linkage=False,
        )
        review_raw = review_path.read_bytes()
    except (ImportError, LifecycleContractError, OSError, ValueError) as exc:
        return [f"cannot load Benchmark Authorization/Review evidence: {exc}"]

    content_sha = sha256_bytes(content_raw)
    provenance = content.get("authoring_provenance")
    final_content_sha = provenance.get("final_content_sha256") if isinstance(provenance, Mapping) else None
    provenance_errors: list[str] = []
    if (
        not isinstance(final_content_sha, str)
        or len(final_content_sha) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in final_content_sha)
    ):
        provenance_errors.append(
            "Lesson Content authoring_provenance.final_content_sha256 is required for completed Benchmark authority"
        )
        final_content_sha = None

    errors = provenance_errors + benchmark_authorization_module.validate_authorization_payload(
        authorization,
        source_lesson_content_sha256=content_sha,
        source_final_content_sha256=final_content_sha,
    )
    errors.extend(benchmark_authorization_module.publication_eligibility_errors(authorization))
    errors.extend(f"Benchmark Review: {item}" for item in review_errors)

    authorization_sha = sha256_bytes(authorization_raw)
    review_sha = sha256_bytes(review_raw)
    if str(benchmark.get("authorization_sha256", "")).casefold() != authorization_sha:
        errors.append("lifecycle benchmark.authorization_sha256 does not match Benchmark Authorization bytes")
    if str(benchmark.get("review_sha256", "")).casefold() != review_sha:
        errors.append("lifecycle benchmark.review_sha256 does not match Benchmark Review bytes")
    if str(authorization.get("benchmark_review_sha256", "")).casefold() != review_sha:
        errors.append("Benchmark Authorization benchmark_review_sha256 does not match Benchmark Review bytes")
    if authorization.get("content_contract_version") != content.get("content_contract_version"):
        errors.append("Benchmark Authorization content_contract_version does not match Lesson Content")
    if str(review.get("source_lesson_content_sha256", "")).casefold() != content_sha:
        errors.append("Benchmark Review source_lesson_content_sha256 does not match Lesson Content bytes")

    summary = review.get("course_summary", {})
    isolation = review.get("isolation", {})
    if authorization.get("benchmark_run_id") != review.get("benchmark_run_id"):
        errors.append("Benchmark Authorization and Review benchmark_run_id do not match")
    if authorization.get("review_round") != review.get("review_round"):
        errors.append("Benchmark Authorization and Review review_round do not match")
    if authorization.get("context_mode") != isolation.get("context_mode"):
        errors.append("Benchmark Authorization context_mode does not match Benchmark Review isolation")
    if authorization.get("context_mode") != summary.get("context_mode"):
        errors.append("Benchmark Authorization context_mode does not match Benchmark Review course summary")
    if authorization.get("benchmark_status") != review.get("status"):
        errors.append("Benchmark Authorization benchmark_status does not match Benchmark Review status")
    if authorization.get("benchmark_status") != summary.get("status"):
        errors.append("Benchmark Authorization benchmark_status does not match Benchmark Review course summary")
    if authorization.get("benchmark_decision") != summary.get("decision"):
        errors.append("Benchmark Authorization benchmark_decision does not match Benchmark Review course summary")
    return errors
