"""Build authorization only after validating the complete Lesson Benchmark linkage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from benchmark_authorization import authorization_fingerprint, validate_authorization_payload
from exemplar_contract import (
    ContractError,
    assert_distinct_file_paths,
    load_json,
    load_json_bytes,
    sha256_json,
    validate_authoring_selection_payload,
    validate_catalog_payload,
    validate_pack_payload,
    write_json_atomic,
)
from exemplar_split import validate_split_payload
from package_common import DEFAULT_SCHEMA, apply_reviewed_lesson_content, validate_content_v2_input
from validate_benchmark_review import validate_benchmark_review_file

TEST_FIXTURE_AUTHORING_ENV = "LESSON_ALLOW_TEST_FIXTURE_AUTHORING"


def build_authorization(
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
    schema_path: Path = DEFAULT_SCHEMA,
    previous_lesson_content_path: Path | None = None,
    previous_review_path: Path | None = None,
    previous_lesson_reviews_dir: Path | None = None,
    allow_test_fixture: bool = False,
) -> dict[str, Any]:
    lesson_content, lesson_content_bytes = load_json_bytes(lesson_content_path, "Lesson Content")
    if lesson_content.get("content_contract_version") != "2.2":
        raise ContractError("Benchmark authorization requires Lesson Content Contract 2.2")
    validate_content_v2_input(lesson_content, schema_path, allow_test_fixture=allow_test_fixture)
    # This enforces the reviewed-content overlay contract before provenance is issued.
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
    if not isinstance(semantic_digest, str) or len(semantic_digest) != 64:
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
    payload: dict[str, Any] = {
        "benchmark_authorization_version": "1.0",
        "skill_version": "2.3.0",
        "content_contract_version": "2.2",
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["authorization_fingerprint"] = authorization_fingerprint(payload)
    errors = validate_authorization_payload(
        payload,
        source_lesson_content_sha256=hashlib.sha256(lesson_content_bytes).hexdigest(),
        source_final_content_sha256=semantic_digest,
    )
    if errors:
        raise ContractError("generated Benchmark Authorization failed schema validation: " + "; ".join(errors))
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lesson-content", required=True, type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--split", required=True, type=Path)
    parser.add_argument("--authoring-pack", required=True, type=Path)
    parser.add_argument("--authoring-selection", required=True, type=Path)
    parser.add_argument("--holdout-pack", required=True, type=Path)
    parser.add_argument("--holdout-selection", required=True, type=Path)
    parser.add_argument("--benchmark-review", required=True, type=Path)
    parser.add_argument("--lesson-reviews-dir", required=True, type=Path)
    parser.add_argument("--previous-lesson-content", type=Path)
    parser.add_argument("--previous-review", type=Path)
    parser.add_argument("--previous-lesson-reviews-dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-test-fixture-authoring", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.allow_test_fixture_authoring and os.environ.get(TEST_FIXTURE_AUTHORING_ENV) != "1":
            raise ContractError("test-fixture authoring bypass is disabled")
        input_paths = {
            "Lesson Content": args.lesson_content,
            "schema": args.schema,
            "Catalog": args.catalog,
            "Split": args.split,
            "Authoring Pack": args.authoring_pack,
            "Authoring Selection": args.authoring_selection,
            "Holdout Pack": args.holdout_pack,
            "Holdout Selection": args.holdout_selection,
            "Benchmark Review": args.benchmark_review,
            "per-Lesson Reviews": args.lesson_reviews_dir,
        }
        if args.previous_lesson_content:
            input_paths["Round 1 Lesson Content"] = args.previous_lesson_content
        if args.previous_review:
            input_paths["Round 1 Review"] = args.previous_review
        if args.previous_lesson_reviews_dir:
            input_paths["Round 1 per-Lesson Reviews"] = args.previous_lesson_reviews_dir
        assert_distinct_file_paths(input_paths)
        assert_distinct_file_paths({**input_paths, "output": args.output}, outputs={"output"})
        payload = build_authorization(
            lesson_content_path=args.lesson_content,
            catalog_path=args.catalog,
            split_path=args.split,
            authoring_pack_path=args.authoring_pack,
            authoring_selection_path=args.authoring_selection,
            holdout_pack_path=args.holdout_pack,
            holdout_selection_path=args.holdout_selection,
            benchmark_review_path=args.benchmark_review,
            lesson_reviews_dir=args.lesson_reviews_dir,
            schema_path=args.schema,
            previous_lesson_content_path=args.previous_lesson_content,
            previous_review_path=args.previous_review,
            previous_lesson_reviews_dir=args.previous_lesson_reviews_dir,
            allow_test_fixture=args.allow_test_fixture_authoring,
        )
        write_json_atomic(args.output, payload)
    except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": "PASS", "authorization": str(args.output), "authorization_fingerprint": payload["authorization_fingerprint"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
