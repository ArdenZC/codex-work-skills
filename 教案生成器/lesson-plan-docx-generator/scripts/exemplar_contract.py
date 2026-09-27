"""Deterministic contracts for Lesson Teaching Exemplar sidecars.

This module validates structure and explicit policy combinations only. It does
not judge exemplar quality, relevance, or lesson quality.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_DIR = SKILL_DIR / "schemas"
HEX_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
IDENTITY_FIELDS = ("canonical_url", "title", "institution", "author_or_team", "recognition")


class ContractError(ValueError):
    """Raised when a sidecar violates its structural contract."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def canonical_source_identity(card: Mapping[str, Any]) -> dict[str, str]:
    """Return the normalized identity material used for source provenance."""
    source = card.get("source")
    if not isinstance(source, Mapping):
        raise ContractError("card.source must be an object")
    identity: dict[str, str] = {}
    for field in IDENTITY_FIELDS:
        value = source.get(field)
        if not isinstance(value, str):
            raise ContractError(f"card.source.{field} must be a string")
        identity[field] = normalize_identity_text(value)
    return identity


def source_identity_sha256(card: Mapping[str, Any]) -> str:
    return sha256_json(canonical_source_identity(card))


def catalog_fingerprint(exemplars: list[Mapping[str, Any]]) -> str:
    ordered = sorted(exemplars, key=lambda card: str(card.get("exemplar_id", "")))
    return sha256_json(ordered)


def holdout_selection_material(selection: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the holdout digest independent of authoring IDs and rationale."""
    lessons = selection.get("lessons")
    if not isinstance(lessons, list):
        raise ContractError("selection.lessons must be an array")
    rows: list[dict[str, Any]] = []
    for lesson in sorted(lessons, key=lambda item: str(item.get("lesson_id", "")) if isinstance(item, Mapping) else ""):
        if not isinstance(lesson, Mapping) or not isinstance(lesson.get("holdout"), Mapping):
            raise ContractError("each selection lesson must contain a holdout object")
        holdout = lesson["holdout"]
        rows.append(
            {
                "lesson_id": lesson.get("lesson_id"),
                "status": holdout.get("status"),
                "exemplar_ids": sorted(holdout.get("exemplar_ids", [])),
            }
        )
    return {
        "catalog_id": selection.get("catalog_id"),
        "split_id": selection.get("split_id"),
        "lessons": rows,
    }


def holdout_selection_sha256(selection: Mapping[str, Any]) -> str:
    return sha256_json(holdout_selection_material(selection))


def review_holdout_selection_sha256(review_lessons: list[Mapping[str, Any]], catalog_id: str, split_id: str) -> str:
    rows: list[dict[str, Any]] = []
    for lesson in sorted(review_lessons, key=lambda item: str(item.get("lesson_id", ""))):
        holdout = lesson.get("holdout_selection")
        if not isinstance(holdout, Mapping):
            raise ContractError("each review lesson must contain holdout_selection")
        rows.append(
            {
                "lesson_id": lesson.get("lesson_id"),
                "status": holdout.get("status"),
                "exemplar_ids": sorted(holdout.get("exemplar_ids", [])),
            }
        )
    return sha256_json({"catalog_id": catalog_id, "split_id": split_id, "lessons": rows})


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {label} JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{label} must be a JSON object")
    return data


def _load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / schema_name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read schema {path}: {exc}") from exc


def schema_errors(payload: Any, schema_name: str) -> list[str]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource
    except ImportError as exc:
        raise ContractError("jsonschema and referencing are required for sidecar validation") from exc
    schema = _load_schema(schema_name)
    registry = Registry()
    if schema_name == "teaching-exemplar-catalog.schema.json":
        card_schema = _load_schema("teaching-exemplar-card.schema.json")
        registry = registry.with_resource(card_schema["$id"], Resource.from_contents(card_schema))
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: (list(error.absolute_path), error.message))
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    ]


def validate_card_payload(card: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(card, "teaching-exemplar-card.schema.json")
    if errors:
        return errors
    source = card["source"]
    tier = source["authority_tier"]
    visibility = source["visibility"]
    status = card["qualification"]["status"]
    source_type = source["source_type"]
    if source_identity_sha256(card).casefold() != source["source_identity_sha256"].casefold():
        errors.append("source.source_identity_sha256 does not match canonical_source_identity(card)")
    if tier == "C" and status == "QUALIFIED":
        errors.append("authority_tier C cannot have qualification.status QUALIFIED")
    if tier == "PRIVATE" and visibility != "private_session":
        errors.append("authority_tier PRIVATE requires visibility private_session")
    if source_type == "private_user_provided" and (tier != "PRIVATE" or visibility != "private_session"):
        errors.append("private_user_provided requires authority_tier PRIVATE and visibility private_session")
    return errors


def validate_catalog_payload(catalog: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(catalog, "teaching-exemplar-catalog.schema.json")
    if errors:
        return errors
    exemplars = catalog["exemplars"]
    seen: set[str] = set()
    for index, card in enumerate(exemplars):
        if not isinstance(card, Mapping):
            errors.append(f"exemplars[{index}] must be an object")
            continue
        exemplar_id = card.get("exemplar_id")
        if exemplar_id in seen:
            errors.append(f"duplicate exemplar_id: {exemplar_id}")
        if isinstance(exemplar_id, str):
            seen.add(exemplar_id)
        if not isinstance(card.get("group_id"), str) or not card["group_id"].strip():
            errors.append(f"exemplars[{index}].group_id must be non-empty")
        errors.extend(f"exemplars[{index}].{error}" for error in validate_card_payload(card))
    expected = catalog_fingerprint(exemplars)
    if expected.casefold() != catalog["catalog_fingerprint"].casefold():
        errors.append("catalog_fingerprint does not match canonical exemplars sorted by exemplar_id")
    return errors


def validate_catalog_file(path: Path) -> dict[str, Any]:
    catalog = load_json(path, "catalog")
    errors = validate_catalog_payload(catalog)
    if errors:
        raise ContractError("catalog validation failed: " + "; ".join(errors))
    return catalog


def validate_selection_payload(
    selection: Mapping[str, Any],
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
) -> list[str]:
    from exemplar_split import validate_split_payload

    errors = schema_errors(selection, "teaching-exemplar-selection.schema.json")
    if errors:
        return errors
    split_errors = validate_split_payload(split, catalog)
    if split_errors:
        return [f"split: {error}" for error in split_errors]
    if selection["catalog_id"] != catalog["catalog_id"]:
        errors.append("selection.catalog_id does not match catalog")
    if selection["split_id"] != split["split_id"]:
        errors.append("selection.split_id does not match split")
    ids = [lesson.get("lesson_id") for lesson in selection["lessons"]]
    if len(ids) != len(set(ids)):
        errors.append("selection lesson_id values must be unique")
    cards = {card["exemplar_id"]: card for card in catalog["exemplars"]}
    authoring = set(split["authoring_exemplar_ids"])
    holdout = set(split["holdout_exemplar_ids"])
    for index, lesson in enumerate(selection["lessons"]):
        for side, allowed, maximum in (("authoring", authoring, 5), ("holdout", holdout, 4)):
            selected = lesson[side]
            selected_ids = selected["exemplar_ids"]
            prefix = f"lessons[{index}].{side}"
            if len(selected_ids) > maximum:
                errors.append(f"{prefix}.exemplar_ids exceeds maxItems {maximum}")
            if selected["status"] == "SELECTED" and not selected_ids:
                errors.append(f"{prefix} SELECTED requires non-empty exemplar_ids")
            if selected["status"] != "SELECTED" and selected_ids:
                errors.append(f"{prefix} {selected['status']} requires empty exemplar_ids")
            if not allowed and selected["status"] != "UNAVAILABLE":
                errors.append(f"{prefix} must be UNAVAILABLE because its split side has no exemplars")
            if allowed and selected["status"] == "UNAVAILABLE":
                errors.append(f"{prefix} cannot be UNAVAILABLE while its split side has exemplars")
            for exemplar_id in selected_ids:
                if exemplar_id not in cards:
                    errors.append(f"{prefix} contains unknown exemplar_id {exemplar_id}")
                elif exemplar_id not in allowed:
                    errors.append(f"{prefix} exemplar_id {exemplar_id} is outside its split side")
                elif cards[exemplar_id]["qualification"]["status"] != "QUALIFIED":
                    errors.append(f"{prefix} exemplar_id {exemplar_id} is not QUALIFIED")
    return errors


def context_size_report(catalog: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, Any]:
    card_by_id = {card["exemplar_id"]: card for card in catalog["exemplars"]}
    authoring_bytes: dict[str, int] = {}
    holdout_bytes: dict[str, int] = {}
    for lesson in selection.get("lessons", []):
        lesson_id = lesson["lesson_id"]
        authoring_bytes[lesson_id] = sum(
            len(canonical_json_bytes(card_by_id[card_id]))
            for card_id in lesson["authoring"]["exemplar_ids"]
            if card_id in card_by_id
        )
        holdout_bytes[lesson_id] = sum(
            len(canonical_json_bytes(card_by_id[card_id]))
            for card_id in lesson["holdout"]["exemplar_ids"]
            if card_id in card_by_id
        )
    return {
        "catalog_total_bytes": len(canonical_json_bytes(catalog)),
        "selected_authoring_card_bytes_per_lesson": authoring_bytes,
        "selected_holdout_card_bytes_per_lesson": holdout_bytes,
    }


def _validate_command(args: argparse.Namespace) -> int:
    if args.command == "catalog":
        catalog = validate_catalog_file(args.path)
        print(json.dumps({"status": "PASS", "catalog_id": catalog["catalog_id"], "exemplar_count": len(catalog["exemplars"])}, ensure_ascii=False, indent=2))
        return 0
    catalog = validate_catalog_file(args.catalog)
    split = load_json(args.split, "split")
    selection = load_json(args.selection, "selection")
    errors = validate_selection_payload(selection, catalog, split)
    if errors:
        raise ContractError("selection validation failed: " + "; ".join(errors))
    result = {"status": "PASS", "selection_contract_version": selection["selection_contract_version"], **context_size_report(catalog, selection)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    catalog_parser = subparsers.add_parser("catalog", help="validate an exemplar catalog")
    catalog_parser.add_argument("path", type=Path)
    selection_parser = subparsers.add_parser("selection", help="validate per-Lesson selections and report context size")
    selection_parser.add_argument("--catalog", required=True, type=Path)
    selection_parser.add_argument("--split", required=True, type=Path)
    selection_parser.add_argument("--selection", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return _validate_command(args)
    except (ContractError, OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
