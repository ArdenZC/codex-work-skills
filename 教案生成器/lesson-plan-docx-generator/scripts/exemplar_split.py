"""Deterministically assign qualified exemplar groups to Authoring and Holdout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from exemplar_contract import (
    ContractError,
    canonical_json_bytes,
    load_json,
    schema_errors,
    validate_catalog_payload,
)


def _split_identity(split: dict[str, Any]) -> dict[str, Any]:
    return {
        key: split[key]
        for key in (
            "split_contract_version",
            "catalog_id",
            "catalog_fingerprint",
            "benchmark_availability",
            "authoring_group_ids",
            "holdout_group_ids",
            "authoring_exemplar_ids",
            "holdout_exemplar_ids",
        )
    }


def _availability(group_count: int) -> str:
    if group_count < 2:
        return "UNAVAILABLE"
    if group_count == 2:
        return "PARTIAL"
    return "AVAILABLE"


def expected_split(catalog: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    qualified = [card for card in catalog["exemplars"] if card["qualification"]["status"] == "QUALIFIED"]
    group_ids = sorted({card["group_id"] for card in qualified})
    ranked_groups = sorted(
        group_ids,
        key=lambda group_id: hashlib.sha256(
            f"{catalog['catalog_fingerprint']}\n{group_id}".encode("utf-8")
        ).hexdigest(),
    )
    authoring_groups: list[str] = []
    holdout_groups: list[str] = []
    for index, group_id in enumerate(ranked_groups):
        # Fixed pattern A, B, B, A, B, B ...
        if index % 3 == 0:
            authoring_groups.append(group_id)
        else:
            holdout_groups.append(group_id)
    authoring_set = set(authoring_groups)
    holdout_set = set(holdout_groups)
    authoring_ids = sorted(card["exemplar_id"] for card in qualified if card["group_id"] in authoring_set)
    holdout_ids = sorted(card["exemplar_id"] for card in qualified if card["group_id"] in holdout_set)
    split = {
        "split_contract_version": "1.0",
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_id": "split-" + catalog["catalog_fingerprint"][:20].lower(),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "benchmark_availability": _availability(len(ranked_groups)),
        "authoring_group_ids": authoring_groups,
        "holdout_group_ids": holdout_groups,
        "authoring_exemplar_ids": authoring_ids,
        "holdout_exemplar_ids": holdout_ids,
    }
    split["split_fingerprint"] = hashlib.sha256(canonical_json_bytes(_split_identity(split))).hexdigest()
    return split


def validate_split_payload(split: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    errors = schema_errors(split, "teaching-exemplar-split.schema.json")
    if errors:
        return errors
    catalog_errors = validate_catalog_payload(catalog)
    if catalog_errors:
        return [f"catalog: {error}" for error in catalog_errors]
    if split["catalog_id"] != catalog["catalog_id"]:
        errors.append("split.catalog_id does not match catalog")
    if split["catalog_fingerprint"].casefold() != catalog["catalog_fingerprint"].casefold():
        errors.append("split.catalog_fingerprint does not match catalog")
    expected = expected_split(catalog, created_at=split["created_at"])
    for field in (
        "benchmark_availability",
        "authoring_group_ids",
        "holdout_group_ids",
        "authoring_exemplar_ids",
        "holdout_exemplar_ids",
        "split_id",
        "split_fingerprint",
    ):
        if split[field] != expected[field]:
            errors.append(f"split.{field} does not match deterministic split")
    authoring_groups = set(split["authoring_group_ids"])
    holdout_groups = set(split["holdout_group_ids"])
    if authoring_groups & holdout_groups:
        errors.append("Authoring and Holdout groups overlap")
    authoring_ids = set(split["authoring_exemplar_ids"])
    holdout_ids = set(split["holdout_exemplar_ids"])
    if authoring_ids & holdout_ids:
        errors.append("Authoring and Holdout exemplars overlap")
    card_by_id = {card["exemplar_id"]: card for card in catalog["exemplars"]}
    for side, exemplar_ids, group_ids in (
        ("authoring", authoring_ids, authoring_groups),
        ("holdout", holdout_ids, holdout_groups),
    ):
        for exemplar_id in exemplar_ids:
            card = card_by_id.get(exemplar_id)
            if card is None:
                errors.append(f"{side} contains unknown exemplar_id {exemplar_id}")
            elif card["group_id"] not in group_ids:
                errors.append(f"{side} exemplar {exemplar_id} is outside its assigned group set")
            elif card["qualification"]["status"] != "QUALIFIED":
                errors.append(f"{side} contains non-QUALIFIED exemplar {exemplar_id}")
    return errors


def build_split(catalog: dict[str, Any]) -> dict[str, Any]:
    errors = validate_catalog_payload(catalog)
    if errors:
        raise ContractError("catalog validation failed: " + "; ".join(errors))
    split = expected_split(catalog)
    split_errors = schema_errors(split, "teaching-exemplar-split.schema.json")
    if split_errors:
        raise ContractError("generated split violates schema: " + "; ".join(split_errors))
    return split


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--validate", action="store_true", help="validate an existing split at --output")
    args = parser.parse_args(argv)
    try:
        catalog = load_json(args.catalog, "catalog")
        if args.validate:
            split = load_json(args.output, "split")
            errors = validate_split_payload(split, catalog)
            if errors:
                raise ContractError("split validation failed: " + "; ".join(errors))
            print(json.dumps({"status": "PASS", "split_id": split["split_id"], "split_fingerprint": split["split_fingerprint"]}, ensure_ascii=False, indent=2))
        else:
            split = build_split(catalog)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(split, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": "PASS", "output": str(args.output), "split_id": split["split_id"], "benchmark_availability": split["benchmark_availability"]}, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
