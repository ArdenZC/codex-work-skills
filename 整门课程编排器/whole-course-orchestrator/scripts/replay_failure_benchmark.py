"""Replay a normalized real failure snapshot with expect-fail semantics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from extract_failure_benchmark_evidence import _sha256
from orchestrator_core import canonical_hash, dump_json, load_json
from review_whole_course import review_failure_benchmark


def verify_snapshot(snapshot: dict[str, Any], benchmark_path: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if snapshot.get("snapshot_type") != "REAL_FROZEN_FAILURE_EVIDENCE":
        errors.append("snapshot_type is not REAL_FROZEN_FAILURE_EVIDENCE")
    if snapshot.get("extracted_from_real_output") is not True:
        errors.append("snapshot does not declare extracted_from_real_output=true")
    if not snapshot.get("source_benchmark_id") or not snapshot.get("source_benchmark_sha256"):
        errors.append("snapshot provenance is missing source benchmark identity/hash")
    expected_hash = canonical_hash({key: value for key, value in snapshot.items() if key not in {"snapshot_sha256", "extraction_timestamp"}})
    if snapshot.get("snapshot_sha256") != expected_hash:
        errors.append("snapshot_sha256 does not match normalized snapshot content")
    if not snapshot.get("relevant_original_file_hashes", {}).get("source_files"):
        errors.append("snapshot has no frozen source file hashes")
    if not snapshot.get("theory_sessions") or not snapshot.get("practice_sessions"):
        errors.append("snapshot is missing normalized theory/practice sessions")
    if benchmark_path:
        benchmark_path = benchmark_path.expanduser().resolve()
        if not benchmark_path.is_file():
            errors.append(f"benchmark manifest does not exist: {benchmark_path}")
        elif _sha256(benchmark_path) != snapshot.get("source_benchmark_sha256"):
            errors.append("source benchmark manifest hash changed")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "snapshot_sha256": snapshot.get("snapshot_sha256")}


def replay(snapshot_path: Path, *, benchmark_path: Path | None = None, output_path: Path | None = None, expect_fail: bool = False) -> dict[str, Any]:
    snapshot = load_json(snapshot_path)
    integrity = verify_snapshot(snapshot, benchmark_path)
    review = review_failure_benchmark(snapshot) if integrity["status"] == "PASS" else {"status": "NOT_RUN", "findings": []}
    finding_codes = sorted({str(item.get("code")) for item in review.get("findings", []) if item.get("code")})
    expected = sorted(set(str(item) for item in snapshot.get("expected_findings", [])))
    missing_expected = sorted(set(expected) - set(finding_codes))
    replay_status = "PASS" if integrity["status"] == "PASS" and not missing_expected and review.get("status") == "FAIL" else "FAIL"
    result = {
        "schema_version": "1.1",
        "report_type": "whole_course_failure_benchmark_replay",
        "status": replay_status,
        "replay_semantics": "EXPECT_FAIL" if expect_fail else "REPORT_ONLY",
        "integrity": integrity,
        "review": review,
        "expected_finding_codes": expected,
        "observed_finding_codes": finding_codes,
        "missing_expected_findings": missing_expected,
        "source_benchmark_id": snapshot.get("source_benchmark_id"),
        "snapshot_sha256": snapshot.get("snapshot_sha256"),
    }
    if output_path:
        dump_json(result, output_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--benchmark-json", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--expect-fail", action="store_true", help="exit 0 only when the snapshot is correctly classified as FAIL")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = replay(args.snapshot, benchmark_path=args.benchmark_json, output_path=args.output_json, expect_fail=args.expect_fail)
    if args.json:
        print(json.dumps({"status": result["status"], "review_status": result["review"].get("status"), "findings": result["observed_finding_codes"], "snapshot_sha256": result["snapshot_sha256"]}, ensure_ascii=False))
    if args.expect_fail:
        raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
