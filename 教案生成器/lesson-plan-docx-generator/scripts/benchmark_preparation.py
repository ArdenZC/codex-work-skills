"""Offline Quality-Gated Benchmark Preparation Contract 1.0.

The source Catalog remains the eligibility authority. The derived Catalog is an
ordinary Catalog 1.0 consumed by the unchanged Split/Pack/Review validators.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from benchmark_quality_eligibility import validate_quality_eligibility_payload
from exemplar_contract import (
    ContractError, assert_distinct_file_paths, build_exemplar_pack,
    catalog_fingerprint, validate_catalog_payload, validate_pack_payload,
)
from exemplar_split import build_split, validate_split_payload, _replace_bundle
from lifecycle_digest import (
    read_json_object, schema_errors, semantic_fingerprint, sha256_bytes,
    timezone_aware_timestamp,
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def json_bytes(payload):
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def preparation_fingerprint(payload):
    return semantic_fingerprint(payload, excluded_fields={"created_at", "preparation_fingerprint"},
                                unordered_arrays={"eligible_group_ids"})


def project_catalog(source, eligibility, *, created_at=None):
    errors = validate_quality_eligibility_payload(eligibility, source)
    if errors:
        raise ContractError("Quality Eligibility: " + "; ".join(errors))
    groups = {row["group_id"] for row in eligibility["groups"]
              if row["decision"] == "QUALITY_ELIGIBLE"}
    projected = copy.deepcopy(source)
    projected["exemplars"] = [copy.deepcopy(card) for card in source["exemplars"]
                              if card["group_id"] in groups
                              and card["qualification"]["status"] == "QUALIFIED"]
    identity = semantic_fingerprint({"source": source["catalog_fingerprint"],
                                     "quality": eligibility["eligibility_fingerprint"]})
    projected["catalog_id"] = "quality-catalog-" + identity
    if projected["catalog_id"] == source["catalog_id"]:
        raise ContractError("derived Catalog identity must differ from source Catalog")
    projected["created_at"] = created_at or timestamp()
    projected["catalog_fingerprint"] = catalog_fingerprint(
        projected["exemplars"], qualification_policy_version=projected["qualification_policy_version"],
        course_context=projected["course_context"],
        exemplar_contract_version=projected["exemplar_contract_version"],
    )
    errors = validate_catalog_payload(projected)
    if errors:
        raise ContractError("projected Catalog: " + "; ".join(errors))
    # Policy assertion, rather than a second assignment implementation.
    original_split = build_split(source)
    filtered_split = build_split(projected)
    for side in ("authoring", "holdout"):
        if set(filtered_split[side + "_group_ids"]) != set(original_split[side + "_group_ids"]) & groups:
            raise ContractError("STOP: quality filtering changed stable A/B assignment")
    return projected


def preparation_disposition(split):
    # Ready requires both sides AVAILABLE. Benchmark availability still follows B.
    if split["authoring_availability"] == split["holdout_availability"] == "AVAILABLE":
        return "BENCHMARK_READY"
    return "BENCHMARK_UNAVAILABLE" if split["benchmark_availability"] == "UNAVAILABLE" else "BENCHMARK_PARTIAL"


def build_preparation(source, eligibility, projected, split, authoring, holdout,
                      raw, *, pipeline_run_id, created_at=None):
    payload = {
        "preparation_contract_version": "1.0", "pipeline_run_id": pipeline_run_id,
        "source_catalog_id": source["catalog_id"],
        "source_catalog_fingerprint": source["catalog_fingerprint"],
        "source_catalog_file_sha256": sha256_bytes(raw["source_catalog"]),
        "quality_eligibility_fingerprint": eligibility["eligibility_fingerprint"],
        "quality_eligibility_file_sha256": sha256_bytes(raw["quality_eligibility"]),
        "projected_catalog_id": projected["catalog_id"],
        "projected_catalog_fingerprint": projected["catalog_fingerprint"],
        "projected_catalog_file_sha256": sha256_bytes(raw["projected_catalog"]),
        "split_id": split["split_id"], "split_fingerprint": split["split_fingerprint"],
        "split_file_sha256": sha256_bytes(raw["split"]),
        "authoring_pack_sha256": sha256_bytes(raw["authoring_pack"]),
        "holdout_pack_sha256": sha256_bytes(raw["holdout_pack"]),
        "eligible_group_ids": sorted(row["group_id"] for row in eligibility["groups"]
                                     if row["decision"] == "QUALITY_ELIGIBLE"),
        "authoring_quality_availability": split["authoring_availability"],
        "holdout_quality_availability": split["holdout_availability"],
        "benchmark_quality_availability": split["benchmark_availability"],
        "disposition": preparation_disposition(split),
        "created_at": created_at or timestamp(),
    }
    payload["preparation_fingerprint"] = preparation_fingerprint(payload)
    return payload


def validate_preparation_payload(payload, artifacts, raw):
    errors = schema_errors(payload, "benchmark-preparation.schema.json")
    if errors:
        return errors
    if not timezone_aware_timestamp(payload["created_at"]):
        errors.append("created_at requires timezone")
    if not payload["pipeline_run_id"].strip():
        errors.append("pipeline_run_id must contain non-whitespace text")
    source = artifacts["source_catalog"]
    eligibility = artifacts["quality_eligibility"]
    projected = artifacts["projected_catalog"]
    split = artifacts["split"]
    try:
        expected = project_catalog(source, eligibility, created_at=projected.get("created_at"))
        if projected != expected:
            errors.append("projected Catalog differs from canonical quality-only projection")
        errors.extend(validate_catalog_payload(projected))
        errors.extend(validate_split_payload(split, projected))
        for role in ("authoring", "holdout"):
            errors.extend(validate_pack_payload(artifacts[role + "_pack"], projected, split, expected_role=role))
        expected_preparation = build_preparation(
            source, eligibility, projected, split, artifacts["authoring_pack"], artifacts["holdout_pack"], raw,
            pipeline_run_id=payload["pipeline_run_id"], created_at=payload["created_at"],
        )
        if payload != expected_preparation:
            errors.append("STALE preparation: lineage, bytes, availability or fingerprint differs")
    except (ContractError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return errors


ARTIFACT_NAMES = ("source_catalog", "quality_eligibility", "projected_catalog",
                  "split", "authoring_pack", "holdout_pack")


def assert_external_outputs(paths):
    skill_root = Path(__file__).resolve().parents[1]
    # Installed full engines do not necessarily have the repository's Chinese
    # directory layout. Protect their Skill tree without claiming its parent
    # workspace is a repository.
    protected = skill_root.parent.parent if skill_root.parent.name == "教案生成器" else skill_root
    for path in paths:
        path = Path(path).absolute()
        for candidate in (path, path.resolve()):
            if candidate.is_relative_to(protected):
                raise ContractError("lifecycle artifacts require an independent external workspace")


def validate_preparation_files(preparation_path, **paths):
    assert_distinct_file_paths({"preparation": preparation_path, **paths})
    payload, _ = read_json_object(preparation_path, "preparation")
    artifacts, raw = {}, {}
    for name in ARTIFACT_NAMES:
        artifacts[name], raw[name] = read_json_object(paths[name], name)
    return payload, validate_preparation_payload(payload, artifacts, raw)


def preparation_bundle(source_catalog, quality_eligibility, *, pipeline_run_id):
    source, source_raw = read_json_object(source_catalog, "source Catalog")
    eligibility, eligibility_raw = read_json_object(quality_eligibility, "Quality Eligibility")
    projected = project_catalog(source, eligibility)
    split = build_split(projected)
    authoring = build_exemplar_pack(projected, split, "authoring")
    holdout = build_exemplar_pack(projected, split, "holdout")
    artifacts = dict(zip(ARTIFACT_NAMES, (source, eligibility, projected, split, authoring, holdout)))
    raw = {name: json_bytes(value) for name, value in artifacts.items()}
    raw.update(source_catalog=source_raw, quality_eligibility=eligibility_raw)
    preparation = build_preparation(source, eligibility, projected, split, authoring, holdout, raw,
                                    pipeline_run_id=pipeline_run_id)
    errors = validate_preparation_payload(preparation, artifacts, raw)
    if errors:
        raise ContractError("preparation failed: " + "; ".join(errors))
    return projected, split, authoring, holdout, preparation


def prepare_benchmark(preparation_path, *, pipeline_run_id, **paths):
    outputs = {"projected_catalog", "split", "authoring_pack", "holdout_pack", "preparation"}
    assert_distinct_file_paths({"preparation": preparation_path, **paths}, outputs=outputs)
    bundle = preparation_bundle(paths["source_catalog"], paths["quality_eligibility"], pipeline_run_id=pipeline_run_id)
    destinations = tuple(Path(paths[name]) for name in ARTIFACT_NAMES[2:]) + (Path(preparation_path),)
    assert_external_outputs(destinations)
    _replace_bundle(destinations, bundle)
    return bundle[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "validate"))
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--run-id")
    for name in ARTIFACT_NAMES:
        parser.add_argument("--" + name.replace("_", "-"), required=True, type=Path)
    args = parser.parse_args(argv)
    paths = {name: getattr(args, name) for name in ARTIFACT_NAMES}
    try:
        if args.command == "prepare":
            if not args.run_id or not args.run_id.strip():
                raise ContractError("--run-id is required")
            result = prepare_benchmark(args.preparation, pipeline_run_id=args.run_id, **paths)
        else:
            result, errors = validate_preparation_files(args.preparation, **paths)
            if errors:
                raise ContractError("; ".join(errors))
        print(json.dumps({"status": "VALID", "disposition": result["disposition"]}))
        return 0
    except (ValueError, OSError, ContractError) as exc:
        parser.exit(1, f"INVALID: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
