"""Build authorization only after validating the complete Lesson Benchmark linkage."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from benchmark_authorization import (
    authorization_fingerprint,
    derive_benchmark_authorization_claims,
    publication_eligibility_errors,
    validate_authorization_payload,
)
from exemplar_contract import (
    ContractError,
    assert_distinct_file_paths,
    write_json_atomic,
)
from package_common import DEFAULT_SCHEMA

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
    claims = derive_benchmark_authorization_claims(
        lesson_content_path=lesson_content_path,
        catalog_path=catalog_path,
        split_path=split_path,
        authoring_pack_path=authoring_pack_path,
        authoring_selection_path=authoring_selection_path,
        holdout_pack_path=holdout_pack_path,
        holdout_selection_path=holdout_selection_path,
        benchmark_review_path=benchmark_review_path,
        lesson_reviews_dir=lesson_reviews_dir,
        schema_path=schema_path,
        previous_lesson_content_path=previous_lesson_content_path,
        previous_review_path=previous_review_path,
        previous_lesson_reviews_dir=previous_lesson_reviews_dir,
        allow_test_fixture=allow_test_fixture,
    )
    eligibility_errors = publication_eligibility_errors(claims)
    if eligibility_errors:
        raise ContractError(" ".join(eligibility_errors))
    payload: dict[str, Any] = {
        **claims,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["authorization_fingerprint"] = authorization_fingerprint(payload)
    errors = validate_authorization_payload(
        payload,
        source_lesson_content_sha256=claims["source_lesson_content_sha256"],
        source_final_content_sha256=claims["source_final_content_sha256"],
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
