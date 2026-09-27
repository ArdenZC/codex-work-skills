"""Deterministically assign qualified exemplar groups to Authoring and Holdout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from exemplar_contract import (
    ContractError,
    SPLIT_POLICY_VERSION,
    assert_distinct_file_paths,
    build_exemplar_pack,
    canonical_json_bytes,
    load_json,
    schema_errors,
    validate_catalog_payload,
    validate_pack_payload,
    write_json_atomic,
)


def _split_identity(split: dict[str, Any]) -> dict[str, Any]:
    return {
        key: split[key]
        for key in (
            "split_contract_version",
            "split_policy_version",
            "catalog_id",
            "catalog_fingerprint",
            "authoring_group_count",
            "holdout_group_count",
            "authoring_availability",
            "holdout_availability",
            "benchmark_availability",
            "authoring_group_ids",
            "holdout_group_ids",
            "authoring_exemplar_ids",
            "holdout_exemplar_ids",
        )
    }


def _availability(group_count: int) -> str:
    if group_count == 0:
        return "UNAVAILABLE"
    if group_count == 1:
        return "PARTIAL"
    return "AVAILABLE"


def expected_split(catalog: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    qualified = [card for card in catalog["exemplars"] if card["qualification"]["status"] == "QUALIFIED"]
    group_ids = sorted({card["group_id"] for card in qualified})
    authoring_groups: list[str] = []
    holdout_groups: list[str] = []
    course_domain_key = hashlib.sha256(canonical_json_bytes(catalog["course_context"])).hexdigest()
    for group_id in sorted(group_ids):
        assignment = hashlib.sha256(
            f"{SPLIT_POLICY_VERSION}\n{course_domain_key}\n{group_id}".encode("utf-8")
        ).digest()[0] & 1
        if assignment == 0:
            authoring_groups.append(group_id)
        else:
            holdout_groups.append(group_id)
    authoring_set = set(authoring_groups)
    holdout_set = set(holdout_groups)
    authoring_ids = sorted(card["exemplar_id"] for card in qualified if card["group_id"] in authoring_set)
    holdout_ids = sorted(card["exemplar_id"] for card in qualified if card["group_id"] in holdout_set)
    split = {
        "split_contract_version": "1.0",
        "split_policy_version": SPLIT_POLICY_VERSION,
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_id": "split-" + catalog["catalog_fingerprint"][:20].lower(),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "authoring_group_count": len(authoring_groups),
        "holdout_group_count": len(holdout_groups),
        "authoring_availability": _availability(len(authoring_groups)),
        "holdout_availability": _availability(len(holdout_groups)),
        "benchmark_availability": _availability(len(holdout_groups)),
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
        "authoring_group_count",
        "holdout_group_count",
        "authoring_availability",
        "holdout_availability",
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


def _replace_bundle(destinations: tuple[Path, ...], payloads: tuple[dict[str, Any], ...]) -> None:
    originals = {path: path.read_bytes() if path.exists() else None for path in destinations}
    staged: dict[Path, Path] = {}
    committed: list[Path] = []
    try:
        for path, payload in zip(destinations, payloads, strict=True):
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".candidate", dir=str(path.parent))
            temp_path = Path(name)
            staged[path] = temp_path
            with os.fdopen(fd, "wb") as stream:
                stream.write((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            parsed = json.loads(temp_path.read_text(encoding="utf-8"))
            if parsed != payload:
                raise ContractError(f"staged bundle validation failed for {path.name}")
        for path in destinations:
            os.replace(staged[path], path)
            committed.append(path)
        staged.clear()
    except BaseException as exc:
        rollback_errors: list[str] = []
        for path in reversed(committed):
            original = originals[path]
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".rollback", dir=str(path.parent))
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(original)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(name, path)
            except OSError as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        detail = f"sidecar bundle commit failed: {exc}"
        if rollback_errors:
            detail += "; rollback failed: " + "; ".join(rollback_errors)
        raise ContractError(detail) from exc
    finally:
        for temp_path in staged.values():
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--authoring-pack", type=Path)
    parser.add_argument("--holdout-pack", type=Path)
    parser.add_argument("--validate", action="store_true", help="validate an existing split at --output")
    args = parser.parse_args(argv)
    try:
        catalog = load_json(args.catalog, "catalog")
        if bool(args.authoring_pack) != bool(args.holdout_pack):
            raise ContractError("--authoring-pack and --holdout-pack must be supplied together")
        if args.validate:
            split = load_json(args.output, "split")
            errors = validate_split_payload(split, catalog)
            if errors:
                raise ContractError("split validation failed: " + "; ".join(errors))
            if args.authoring_pack:
                authoring_pack = load_json(args.authoring_pack, "authoring Pack")
                holdout_pack = load_json(args.holdout_pack, "holdout Pack")
                errors.extend(validate_pack_payload(authoring_pack, catalog, split, expected_role="authoring"))
                errors.extend(validate_pack_payload(holdout_pack, catalog, split, expected_role="holdout"))
                if errors:
                    raise ContractError("split/Pack validation failed: " + "; ".join(errors))
            print(json.dumps({
                "status": "PASS",
                "split_id": split["split_id"],
                "split_fingerprint": split["split_fingerprint"],
                "authoring_pack_fingerprint": authoring_pack["pack_fingerprint"] if args.authoring_pack else None,
                "holdout_pack_fingerprint": holdout_pack["pack_fingerprint"] if args.holdout_pack else None,
            }, ensure_ascii=False, indent=2))
        else:
            if not args.authoring_pack:
                raise ContractError("split generation requires both --authoring-pack and --holdout-pack")
            split = build_split(catalog)
            authoring_pack = build_exemplar_pack(catalog, split, "authoring")
            holdout_pack = build_exemplar_pack(catalog, split, "holdout")
            destinations = (args.output, args.authoring_pack, args.holdout_pack)
            assert_distinct_file_paths(
                {
                    "catalog": args.catalog,
                    "split": args.output,
                    "authoring Pack": args.authoring_pack,
                    "holdout Pack": args.holdout_pack,
                },
                outputs={"split", "authoring Pack", "holdout Pack"},
            )
            payloads = (split, authoring_pack, holdout_pack)
            _replace_bundle(destinations, payloads)
            print(json.dumps({
                "status": "PASS",
                "split": str(args.output),
                "authoring_pack": str(args.authoring_pack),
                "holdout_pack": str(args.holdout_pack),
                "split_id": split["split_id"],
                "benchmark_availability": split["benchmark_availability"],
                "authoring_pack_fingerprint": authoring_pack["pack_fingerprint"],
                "holdout_pack_fingerprint": holdout_pack["pack_fingerprint"],
            }, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
