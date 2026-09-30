"""Offline, group-level Benchmark Quality Eligibility Contract 1.0.

Humans/agents supply judgments and rationales. This module checks evidence
links and policy consistency; it neither scores teaching quality nor fetches
sources. Existing Split, generator and Authorization defaults are unchanged.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from exemplar_contract import (
    ContractError, PATTERN_FIELDS, QUALIFICATION_POLICY_VERSION,
    assert_distinct_file_paths, load_json, schema_errors,
    validate_catalog_payload, validate_pack_payload, write_json_atomic,
)
from exemplar_split import validate_split_payload
from lifecycle_digest import LifecycleContractError, semantic_fingerprint

QUALITY_POLICY_VERSION = "benchmark-quality-eligibility-v1"
DIMENSIONS = (
    "authority_excellence_basis", "course_relevance", "learner_relevance",
    "teaching_context_relevance", "pattern_evidence", "transferability",
)
SCOPE_FIELDS = (
    "education_level", "vocational_level", "domain", "course", "scope_mode",
    "topic", "learner_profile", "duration_minutes", "teaching_context",
)
REFERENCE_FIELDS = (
    "source.recognition_evidence", *PATTERN_FIELDS, "non_transferable_context",
    *(f"scope.{field}" for field in SCOPE_FIELDS),
)
ELIGIBLE_STATUSES = {
    "authority_excellence_basis": {"SUPPORTED"},
    "course_relevance": {"DIRECT_MATCH", "TRANSFERABLE"},
    "learner_relevance": {"MATCH", "ADJACENT"},
    "teaching_context_relevance": {"MATCH", "TRANSFERABLE"},
    "pattern_evidence": {"SUFFICIENT"},
    "transferability": {"SUFFICIENT"},
}
# Required evidence types for an eligible judgment, not an automated judgment
# of the cited prose. Other globally permitted fields may supplement them.
COURSE_MATCH_FIELDS = frozenset({
    "scope.course", "scope.domain", "scope.topic",
    "scope.education_level", "scope.vocational_level",
})
DIMENSION_EVIDENCE_FIELDS = {
    "authority_excellence_basis": frozenset({"source.recognition_evidence"}),
    "course_relevance": COURSE_MATCH_FIELDS | {"scope.scope_mode"},
    "learner_relevance": frozenset({
        "scope.learner_profile", "scope.education_level", "scope.vocational_level",
    }),
    "teaching_context_relevance": frozenset({
        "scope.teaching_context", "scope.scope_mode", "scope.duration_minutes",
    }),
    "pattern_evidence": frozenset(PATTERN_FIELDS),
    "transferability": frozenset({"transferable_principles"}),
}


def evidence_value_fingerprint(value: Any) -> str:
    return semantic_fingerprint({"value": value})


def quality_eligibility_fingerprint(payload: Mapping[str, Any]) -> str:
    """Reuse lifecycle NFC/no-float hashing with explicitly unordered sets."""
    material = copy.deepcopy(dict(payload))
    paths: list[tuple[str, ...]] = [("groups",)]
    for index, _ in enumerate(material.get("groups", [])):
        prefix = ("groups", str(index))
        paths.append((*prefix, "qualified_exemplar_ids"))
        paths.extend((*prefix, dimension, "evidence_refs") for dimension in DIMENSIONS)
    return semantic_fingerprint(
        material, excluded_fields=("created_at", "eligibility_fingerprint"),
        unordered_arrays=paths,
    )


def candidate_groups(catalog: Mapping[str, Any]) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for card in catalog["exemplars"]:
        if card["qualification"]["status"] == "QUALIFIED":
            groups.setdefault(card["group_id"], set()).add(card["exemplar_id"])
    return groups


def _reference_value(card: Mapping[str, Any], field: str, index: int | None) -> Any:
    value: Any = card
    for part in field.split("."):
        value = value[part]
    if isinstance(value, list):
        if index is None or index >= len(value):
            raise ContractError("evidence item_index is missing or out of range")
        value = value[index]
    elif index is not None:
        raise ContractError("scalar scope evidence requires item_index=null")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ContractError("evidence must reference a non-empty current value")
    return value


def validate_quality_eligibility_payload(
    payload: Mapping[str, Any], catalog: Mapping[str, Any],
) -> list[str]:
    errors = schema_errors(payload, "benchmark-quality-eligibility.schema.json")
    if errors:
        return errors
    catalog_errors = validate_catalog_payload(catalog)
    if catalog_errors:
        return [f"catalog: {error}" for error in catalog_errors]
    for field in ("catalog_id", "catalog_fingerprint", "qualification_policy_version"):
        actual, expected = payload[field], catalog[field]
        if (actual.lower() != expected.lower() if field.endswith("fingerprint") else actual != expected):
            errors.append(f"{field} does not match current Catalog")
    if catalog["qualification_policy_version"] != QUALIFICATION_POLICY_VERSION:
        errors.append("unsupported qualification policy")
    expected_groups = candidate_groups(catalog)
    group_ids = [row["group_id"] for row in payload["groups"]]
    if len(group_ids) != len(set(group_ids)):
        errors.append("duplicate group_id")
    if set(group_ids) != set(expected_groups):
        errors.append("manifest groups must exactly cover Catalog candidate groups")
    cards = {card["exemplar_id"]: card for card in catalog["exemplars"]}
    for row in payload["groups"]:
        group = row["group_id"]
        qualified_ids = expected_groups.get(group, set())
        if set(row["qualified_exemplar_ids"]) != qualified_ids:
            errors.append(f"{group}: qualified_exemplar_ids must exactly match all QUALIFIED group Cards")
        eligible = row["decision"] == "QUALITY_ELIGIBLE"
        if eligible and any(
            cards[item]["source"]["source_type"] == "private_user_provided"
            for item in qualified_ids
        ):
            errors.append(f"{group}: private source has no supported exemplary attestation; at most CONDITIONAL")
        for dimension in DIMENSIONS:
            assessment = row[dimension]
            if eligible and assessment["status"] not in ELIGIBLE_STATUSES[dimension]:
                errors.append(f"{group}: QUALITY_ELIGIBLE contradicts {dimension} status")
            refs = assessment["evidence_refs"]
            seen: set[tuple[str, str, int | None]] = set()
            for ref in refs:
                identity = (ref["exemplar_id"], ref["field"], ref["item_index"])
                if identity in seen:
                    errors.append(f"{group}: duplicate evidence reference in {dimension}")
                seen.add(identity)
                if ref["exemplar_id"] not in qualified_ids:
                    errors.append(f"{group}: evidence exemplar must belong to this qualified group")
                    continue
                try:
                    value = _reference_value(cards[ref["exemplar_id"]], ref["field"], ref["item_index"])
                    if evidence_value_fingerprint(value) != ref["value_sha256"].lower():
                        errors.append(f"{group}: evidence value_sha256 differs from current Card")
                except (ContractError, LifecycleContractError) as exc:
                    errors.append(f"{group}: {exc}")
            if eligible:
                if not refs:
                    errors.append(f"{group}: {dimension} requires evidence for QUALITY_ELIGIBLE")
                fields = {ref["field"] for ref in refs}
                required_fields = DIMENSION_EVIDENCE_FIELDS[dimension]
                if dimension == "course_relevance" and assessment["status"] == "DIRECT_MATCH":
                    required_fields = COURSE_MATCH_FIELDS
                if not fields.intersection(required_fields):
                    errors.append(
                        f"{group}: {dimension} requires dimension-appropriate evidence from "
                        + ", ".join(sorted(required_fields))
                    )
            if assessment["status"] == "TRANSFERABLE" and not refs:
                errors.append(f"{group}: TRANSFERABLE requires evidence and rationale")
    try:
        if quality_eligibility_fingerprint(payload) != payload["eligibility_fingerprint"].lower():
            errors.append("eligibility_fingerprint does not match semantic manifest")
    except LifecycleContractError as exc:
        errors.append(str(exc))
    return errors


def build_quality_eligibility(
    catalog: Mapping[str, Any], groups: list[dict[str, Any]], *, created_at: str | None = None,
) -> dict[str, Any]:
    """Bind supplied judgments; never infer or upgrade an eligibility decision."""
    errors = validate_catalog_payload(catalog)
    if errors:
        raise ContractError("catalog validation failed: " + "; ".join(errors))
    payload = {
        "quality_eligibility_contract_version": "1.0",
        "quality_policy_version": QUALITY_POLICY_VERSION,
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "qualification_policy_version": catalog["qualification_policy_version"],
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "groups": copy.deepcopy(groups),
    }
    payload["eligibility_fingerprint"] = quality_eligibility_fingerprint(payload)
    errors = validate_quality_eligibility_payload(payload, catalog)
    if errors:
        raise ContractError("quality eligibility validation failed: " + "; ".join(errors))
    return payload


def validate_quality_eligibility_file(path: Path, catalog_path: Path) -> dict[str, Any]:
    payload = load_json(path, "quality eligibility")
    errors = validate_quality_eligibility_payload(payload, load_json(catalog_path, "Catalog"))
    if errors:
        raise ContractError("quality eligibility validation failed: " + "; ".join(errors))
    return payload


def _quality_split_errors(payload: Mapping[str, Any], catalog: dict, split: dict) -> list[str]:
    errors = validate_quality_eligibility_payload(payload, catalog)
    errors.extend(validate_split_payload(split, catalog))
    return errors


def validate_split_quality_eligibility(
    split: dict, catalog: dict, eligibility: Mapping[str, Any], *,
    authoring_pack: Mapping[str, Any] | None = None,
    holdout_pack: Mapping[str, Any] | None = None,
) -> list[str]:
    """Explicit opt-in gate; reuse existing Split/Pack validation unchanged."""
    errors = _quality_split_errors(eligibility, catalog, split)
    if errors:
        return errors
    decisions = {row["group_id"]: row["decision"] for row in eligibility["groups"]}
    for role, pack in (("authoring", authoring_pack), ("holdout", holdout_pack)):
        for group in split[f"{role}_group_ids"]:
            if decisions[group] != "QUALITY_ELIGIBLE":
                errors.append(f"{role}: group {group} is not QUALITY_ELIGIBLE")
        if pack is not None:
            errors.extend(validate_pack_payload(pack, catalog, split, expected_role=role))
    return errors


def quality_aware_availability(split: dict, catalog: dict, eligibility: Mapping[str, Any]) -> dict[str, Any]:
    """Count eligible groups on their existing sides, without filtering Packs."""
    errors = _quality_split_errors(eligibility, catalog, split)
    if errors:
        raise ContractError("quality availability validation failed: " + "; ".join(errors))
    eligible = {row["group_id"] for row in eligibility["groups"] if row["decision"] == "QUALITY_ELIGIBLE"}
    result: dict[str, Any] = {}
    for role in ("authoring", "holdout"):
        count = len(set(split[f"{role}_group_ids"]) & eligible)
        result[f"{role}_quality_group_count"] = count
        result[f"{role}_quality_availability"] = "UNAVAILABLE" if count == 0 else "PARTIAL" if count == 1 else "AVAILABLE"
    result["benchmark_quality_availability"] = result["holdout_quality_availability"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="bind reviewed group records without judging quality")
    build.add_argument("--catalog", type=Path, required=True)
    build.add_argument("--records", type=Path, required=True, help='JSON object containing only {"groups": [...]}')
    build.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--eligibility", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            assert_distinct_file_paths(
                {"catalog": args.catalog, "records": args.records, "output": args.output}, outputs={"output"},
            )
            records = load_json(args.records, "reviewed records")
            if set(records) != {"groups"} or not isinstance(records["groups"], list):
                raise ContractError("records must contain only a groups array")
            payload = build_quality_eligibility(load_json(args.catalog, "Catalog"), records["groups"])
            write_json_atomic(args.output, payload)
        else:
            validate_quality_eligibility_file(args.eligibility, args.catalog)
    except (ContractError, LifecycleContractError, OSError, TypeError, KeyError) as exc:
        print(f"INVALID quality eligibility: {exc}")
        return 1
    print("VALID Benchmark Quality Eligibility 1.0 (offline policy/linkage; no online fact check)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
