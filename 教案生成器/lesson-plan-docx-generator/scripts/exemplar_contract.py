"""Deterministic contracts for Lesson Teaching Exemplar sidecars.

This module validates structure and explicit provenance only. It does not
judge exemplar relevance, teaching quality, or lesson quality.
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
from urllib.parse import urlsplit, urlunsplit

SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_DIR = SKILL_DIR / "schemas"
HEX_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
IDENTITY_FIELDS = ("canonical_url", "title", "institution", "author_or_team", "recognition")
PATTERN_FIELDS = (
    "design_patterns",
    "difficulty_breakthrough_patterns",
    "student_activity_patterns",
    "learning_evidence_patterns",
    "assessment_patterns",
    "differentiation_patterns",
    "reflection_patterns",
    "transferable_principles",
)


class ContractError(ValueError):
    """Raised when a sidecar violates its structural contract."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def normalize_canonical_url(value: str) -> str:
    normalized = normalize_identity_text(value)
    try:
        parts = urlsplit(normalized)
        hostname = parts.hostname
        if not parts.scheme or not parts.netloc or not hostname:
            return normalized
        scheme = parts.scheme.lower()
        host = hostname.encode("idna").decode("ascii").lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        userinfo = f"{parts.netloc.rpartition('@')[0]}@" if "@" in parts.netloc else ""
        port = parts.port
        if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            host = f"{host}:{port}"
        return urlunsplit((scheme, userinfo + host, parts.path, parts.query, parts.fragment))
    except (UnicodeError, ValueError):
        return normalized


def canonical_source_identity(card: Mapping[str, Any]) -> dict[str, str]:
    """Return conservative normalized provenance identity material."""
    source = card.get("source")
    if not isinstance(source, Mapping):
        raise ContractError("card.source must be an object")
    identity: dict[str, str] = {}
    for field in IDENTITY_FIELDS:
        value = source.get(field)
        if not isinstance(value, str):
            raise ContractError(f"card.source.{field} must be a string")
        identity[field] = normalize_canonical_url(value) if field == "canonical_url" else normalize_identity_text(value)
    return identity


def source_identity_sha256(card: Mapping[str, Any]) -> str:
    return sha256_json(canonical_source_identity(card))


def catalog_fingerprint(exemplars: list[Mapping[str, Any]]) -> str:
    ordered = sorted(exemplars, key=lambda card: str(card.get("exemplar_id", "")))
    return sha256_json(ordered)


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {label} JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{label} must be a JSON object")
    return data


def load_json_bytes(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {label} JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"{label} must be a JSON object")
    return data, raw


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
    card_schema = _load_schema("teaching-exemplar-card.schema.json")
    if schema_name in {
        "teaching-exemplar-catalog.schema.json",
        "teaching-exemplar-pack.schema.json",
    }:
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
    for field in ("title", "institution", "author_or_team", "recognition"):
        if not normalize_identity_text(source[field]):
            errors.append(f"source.{field} must not be blank")
    if source_identity_sha256(card).casefold() != source["source_identity_sha256"].casefold():
        errors.append("source.source_identity_sha256 does not match canonical_source_identity(card)")
    tier = source["authority_tier"]
    visibility = source["visibility"]
    status = card["qualification"]["status"]
    source_type = source["source_type"]
    if tier == "C" and status == "QUALIFIED":
        errors.append("authority_tier C cannot have qualification.status QUALIFIED")
    if tier == "PRIVATE" and visibility != "private_session":
        errors.append("authority_tier PRIVATE requires visibility private_session")
    if source_type == "private_user_provided" and (tier != "PRIVATE" or visibility != "private_session"):
        errors.append("private_user_provided requires authority_tier PRIVATE and visibility private_session")
    if source_type == "discovery_source" and status == "QUALIFIED":
        errors.append("source_type discovery_source cannot have qualification.status QUALIFIED")
    if status == "QUALIFIED":
        if not any(any(normalize_identity_text(item) for item in card[field]) for field in PATTERN_FIELDS):
            errors.append("QUALIFIED Card requires at least one non-empty benchmark pattern")
        if not any(normalize_identity_text(item) for item in card["do_not_copy"]):
            errors.append("QUALIFIED Card requires at least one do_not_copy item")
    return errors


def validate_catalog_payload(catalog: Mapping[str, Any]) -> list[str]:
    errors = schema_errors(catalog, "teaching-exemplar-catalog.schema.json")
    if errors:
        return errors
    exemplars = catalog["exemplars"]
    seen: set[str] = set()
    source_groups: dict[str, set[str]] = {}
    url_groups: dict[str, set[str]] = {}
    for index, card in enumerate(exemplars):
        if not isinstance(card, Mapping):
            errors.append(f"exemplars[{index}] must be an object")
            continue
        exemplar_id = card.get("exemplar_id")
        if exemplar_id in seen:
            errors.append(f"duplicate exemplar_id: {exemplar_id}")
        if isinstance(exemplar_id, str):
            seen.add(exemplar_id)
        group_id = card.get("group_id")
        if not isinstance(group_id, str) or not normalize_identity_text(group_id):
            errors.append(f"exemplars[{index}].group_id must be non-empty")
        card_errors = validate_card_payload(card)
        errors.extend(f"exemplars[{index}].{error}" for error in card_errors)
        if card_errors or not isinstance(group_id, str):
            continue
        source = card["source"]
        source_groups.setdefault(source["source_identity_sha256"].casefold(), set()).add(group_id)
        url_groups.setdefault(normalize_canonical_url(source["canonical_url"]), set()).add(group_id)
    for identity, groups in sorted(source_groups.items()):
        if len(groups) > 1:
            errors.append(f"source_identity_sha256 {identity} maps to multiple group_id values")
    for canonical_url, groups in sorted(url_groups.items()):
        if len(groups) > 1:
            errors.append(f"normalized canonical_url {canonical_url} maps to multiple group_id values")
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


def _pack_material(pack: Mapping[str, Any]) -> dict[str, Any]:
    exemplars = pack.get("exemplars", [])
    return {
        "role": pack.get("role"),
        "catalog_id": pack.get("catalog_id"),
        "catalog_fingerprint": pack.get("catalog_fingerprint"),
        "split_id": pack.get("split_id"),
        "split_fingerprint": pack.get("split_fingerprint"),
        "exemplar_ids": sorted(pack.get("exemplar_ids", [])),
        "exemplars": sorted(exemplars, key=lambda card: str(card.get("exemplar_id", ""))),
    }


def pack_fingerprint(pack: Mapping[str, Any]) -> str:
    return sha256_json(_pack_material(pack))


def build_exemplar_pack(
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    role: str,
) -> dict[str, Any]:
    """Create the deterministic A-only or B-only projection from Catalog and Split."""
    from exemplar_split import validate_split_payload

    if role not in {"authoring", "holdout"}:
        raise ContractError("role must be authoring or holdout")
    catalog_errors = validate_catalog_payload(catalog)
    if catalog_errors:
        raise ContractError("catalog validation failed: " + "; ".join(catalog_errors))
    split_errors = validate_split_payload(dict(split), dict(catalog))
    if split_errors:
        raise ContractError("split validation failed: " + "; ".join(split_errors))
    id_field = f"{role}_exemplar_ids"
    exemplar_ids = sorted(split[id_field])
    cards_by_id = {card["exemplar_id"]: card for card in catalog["exemplars"]}
    pack: dict[str, Any] = {
        "pack_contract_version": "1.0",
        "role": role,
        "catalog_id": catalog["catalog_id"],
        "catalog_fingerprint": catalog["catalog_fingerprint"],
        "split_id": split["split_id"],
        "split_fingerprint": split["split_fingerprint"],
        "exemplar_ids": exemplar_ids,
        "exemplars": [cards_by_id[exemplar_id] for exemplar_id in exemplar_ids],
    }
    pack["pack_fingerprint"] = pack_fingerprint(pack)
    pack_errors = validate_pack_payload(pack, catalog, split, expected_role=role)
    if pack_errors:
        raise ContractError("generated Pack validation failed: " + "; ".join(pack_errors))
    return pack


def validate_pack_payload(
    pack: Mapping[str, Any],
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    *,
    expected_role: str | None = None,
) -> list[str]:
    from exemplar_split import validate_split_payload

    errors = schema_errors(pack, "teaching-exemplar-pack.schema.json")
    if errors:
        return errors
    catalog_errors = validate_catalog_payload(catalog)
    if catalog_errors:
        return [f"catalog: {error}" for error in catalog_errors]
    split_errors = validate_split_payload(dict(split), dict(catalog))
    if split_errors:
        return [f"split: {error}" for error in split_errors]
    role = pack["role"]
    if expected_role is not None and role != expected_role:
        errors.append(f"Pack role must be {expected_role}")
    for field in ("catalog_id", "catalog_fingerprint", "split_id", "split_fingerprint"):
        expected = {
            "catalog_id": catalog["catalog_id"],
            "catalog_fingerprint": catalog["catalog_fingerprint"],
            "split_id": split["split_id"],
            "split_fingerprint": split["split_fingerprint"],
        }[field]
        if str(pack[field]).casefold() != str(expected).casefold():
            errors.append(f"Pack {field} does not match supplied provenance")
    expected_ids = set(split[f"{role}_exemplar_ids"])
    observed_ids = list(pack["exemplar_ids"])
    if set(observed_ids) != expected_ids or len(observed_ids) != len(expected_ids):
        errors.append(f"{role} Pack exemplar_ids must exactly match the corresponding Split side")
    cards_by_id = {card["exemplar_id"]: card for card in catalog["exemplars"]}
    pack_cards: dict[str, Mapping[str, Any]] = {}
    for index, card in enumerate(pack["exemplars"]):
        card_errors = validate_card_payload(card)
        errors.extend(f"Pack exemplars[{index}].{error}" for error in card_errors)
        exemplar_id = card.get("exemplar_id") if isinstance(card, Mapping) else None
        if not isinstance(exemplar_id, str):
            continue
        if exemplar_id in pack_cards:
            errors.append(f"Pack contains duplicate Card {exemplar_id}")
        pack_cards[exemplar_id] = card
    if set(pack_cards) != expected_ids or len(pack_cards) != len(expected_ids):
        errors.append(f"{role} Pack Cards must exactly match the corresponding Split side")
    for exemplar_id, card in pack_cards.items():
        canonical = cards_by_id.get(exemplar_id)
        if canonical is None:
            errors.append(f"Pack contains unknown Card {exemplar_id}")
        elif canonical_json_bytes(card) != canonical_json_bytes(canonical):
            errors.append(f"Pack Card {exemplar_id} differs from the Catalog Card")
    expected_fingerprint = pack_fingerprint(pack)
    if expected_fingerprint.casefold() != pack["pack_fingerprint"].casefold():
        errors.append("pack_fingerprint does not match the canonical role-scoped Pack payload")
    return errors


def holdout_selection_sha256(selection: Mapping[str, Any]) -> str:
    """Hash the full canonical Holdout Selection payload."""
    return sha256_json(selection)


def validate_catalog_course_context(catalog: Mapping[str, Any], lesson_content: Mapping[str, Any]) -> list[str]:
    context = catalog.get("course_context")
    if not isinstance(context, Mapping):
        return ["catalog.course_context must be an object"]
    errors: list[str] = []
    for field in ("course_name", "major", "audience"):
        catalog_value = context.get(field)
        lesson_value = lesson_content.get(field)
        if not isinstance(catalog_value, str) or not isinstance(lesson_value, str):
            errors.append(f"{field} must be a string in Catalog and Lesson Content")
        elif normalize_identity_text(catalog_value) != normalize_identity_text(lesson_value):
            errors.append(f"catalog.course_context.{field} does not match Lesson Content")
    return errors


def _selection_link_errors(
    selection: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    pack: Mapping[str, Any],
    lesson_content: Mapping[str, Any],
    role: str,
    schema_name: str,
    content_lesson_ids: list[str],
    source_digest: str,
    digest_field: str,
    maximum: int,
) -> list[str]:
    errors = schema_errors(selection, schema_name)
    if errors:
        return errors
    catalog_errors = validate_catalog_payload(catalog)
    errors.extend(f"catalog: {error}" for error in catalog_errors)
    if catalog_errors:
        return errors
    from exemplar_split import validate_split_payload

    split_errors = validate_split_payload(dict(split), dict(catalog))
    errors.extend(f"split: {error}" for error in split_errors)
    if split_errors:
        return errors
    pack_errors = validate_pack_payload(pack, catalog, split, expected_role=role)
    errors.extend(f"pack: {error}" for error in pack_errors)
    if pack_errors:
        return errors
    errors.extend(validate_catalog_course_context(catalog, lesson_content))
    for field, expected in (
        ("catalog_id", catalog["catalog_id"]),
        ("catalog_fingerprint", catalog["catalog_fingerprint"]),
        ("split_id", split["split_id"]),
        ("split_fingerprint", split["split_fingerprint"]),
        ("pack_fingerprint", pack["pack_fingerprint"]),
    ):
        if str(selection[field]).casefold() != str(expected).casefold():
            errors.append(f"selection.{field} does not match supplied provenance")
    if selection[digest_field].casefold() != source_digest.casefold():
        errors.append(f"selection.{digest_field} does not match supplied source")
    rows = selection["lessons"]
    ids = [row["lesson_id"] for row in rows]
    if len(ids) != len(set(ids)):
        errors.append("selection lesson_id values must be unique")
    if set(ids) != set(content_lesson_ids) or len(ids) != len(content_lesson_ids):
        errors.append("selection lesson IDs must exactly match source Lesson IDs")
    allowed_ids = set(pack["exemplar_ids"])
    for index, row in enumerate(rows):
        exemplar_ids = row["exemplar_ids"]
        status = row["status"]
        if len(exemplar_ids) > maximum:
            errors.append(f"lessons[{index}].exemplar_ids exceeds maxItems {maximum}")
        if status == "SELECTED" and not exemplar_ids:
            errors.append(f"lessons[{index}] SELECTED requires non-empty exemplar_ids")
        if status != "SELECTED" and exemplar_ids:
            errors.append(f"lessons[{index}] {status} requires empty exemplar_ids")
        if not allowed_ids and status != "UNAVAILABLE":
            errors.append(f"lessons[{index}] must be UNAVAILABLE because the {role} Pack is empty")
        if allowed_ids and status == "UNAVAILABLE":
            errors.append(f"lessons[{index}] cannot be UNAVAILABLE while the {role} Pack has exemplars")
        for exemplar_id in exemplar_ids:
            if exemplar_id not in allowed_ids:
                errors.append(f"lessons[{index}] cites exemplar outside the {role} Pack: {exemplar_id}")
    return errors


def validate_authoring_selection_payload(
    selection: Mapping[str, Any],
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    pack: Mapping[str, Any],
    lesson_content: Mapping[str, Any],
) -> list[str]:
    outline = lesson_content.get("outline")
    if not isinstance(outline, list):
        return ["Lesson Content outline must be an array"]
    lesson_ids = [row.get("lesson_id") for row in outline if isinstance(row, Mapping)]
    if len(lesson_ids) != len(outline) or not all(isinstance(value, str) and value for value in lesson_ids):
        return ["Lesson Content outline must have a non-empty lesson_id on every row"]
    provenance = lesson_content.get("authoring_provenance")
    snapshot = provenance.get("source_snapshot") if isinstance(provenance, Mapping) else None
    outline_digest = snapshot.get("whole_course_outline_sha256") if isinstance(snapshot, Mapping) else None
    if not isinstance(outline_digest, str) or not HEX_SHA256.fullmatch(outline_digest):
        return ["Lesson Content authoring_provenance.source_snapshot.whole_course_outline_sha256 must be a SHA-256 digest"]
    return _selection_link_errors(
        selection,
        catalog=catalog,
        split=split,
        pack=pack,
        lesson_content=lesson_content,
        role="authoring",
        schema_name="teaching-exemplar-authoring-selection.schema.json",
        content_lesson_ids=lesson_ids,
        source_digest=outline_digest,
        digest_field="source_outline_sha256",
        maximum=5,
    )


def validate_holdout_selection_payload(
    selection: Mapping[str, Any],
    catalog: Mapping[str, Any],
    split: Mapping[str, Any],
    pack: Mapping[str, Any],
    lesson_content: Mapping[str, Any],
    *,
    lesson_content_sha256: str,
) -> list[str]:
    lessons = lesson_content.get("lessons")
    if not isinstance(lessons, list):
        return ["Lesson Content lessons must be an array"]
    lesson_ids = [
        row.get("lesson_id", row.get("id"))
        for row in lessons
        if isinstance(row, Mapping)
    ]
    if len(lesson_ids) != len(lessons) or not all(isinstance(value, str) and value for value in lesson_ids):
        return ["Lesson Content must have a non-empty lesson_id on every lesson"]
    return _selection_link_errors(
        selection,
        catalog=catalog,
        split=split,
        pack=pack,
        lesson_content=lesson_content,
        role="holdout",
        schema_name="teaching-exemplar-holdout-selection.schema.json",
        content_lesson_ids=lesson_ids,
        source_digest=lesson_content_sha256,
        digest_field="source_lesson_content_sha256",
        maximum=4,
    )


def selection_size_report(catalog: Mapping[str, Any], pack: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, Any]:
    cards = {card["exemplar_id"]: card for card in pack["exemplars"]}
    sizes = {
        row["lesson_id"]: sum(
            len(canonical_json_bytes(cards[exemplar_id]))
            for exemplar_id in row["exemplar_ids"]
            if exemplar_id in cards
        )
        for row in selection["lessons"]
    }
    return {
        "catalog_total_bytes": len(canonical_json_bytes(catalog)),
        "pack_total_bytes": len(canonical_json_bytes(pack)),
        "selected_card_bytes_per_lesson": sizes,
    }


def _read_source(args: argparse.Namespace) -> tuple[dict[str, Any], bytes]:
    return load_json_bytes(args.lesson_content, "Lesson Content")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    catalog_parser = subparsers.add_parser("catalog", help="validate an exemplar catalog")
    catalog_parser.add_argument("path", type=Path)
    pack_parser = subparsers.add_parser("pack", help="validate a role-scoped exemplar Pack")
    pack_parser.add_argument("--catalog", required=True, type=Path)
    pack_parser.add_argument("--split", required=True, type=Path)
    pack_parser.add_argument("--pack", required=True, type=Path)
    for name, label in (("authoring-selection", "Authoring"), ("holdout-selection", "Holdout")):
        selection_parser = subparsers.add_parser(name, help=f"validate {label} Selection and report context size")
        selection_parser.add_argument("--catalog", required=True, type=Path)
        selection_parser.add_argument("--split", required=True, type=Path)
        selection_parser.add_argument("--pack", required=True, type=Path)
        selection_parser.add_argument("--selection", required=True, type=Path)
        selection_parser.add_argument("--lesson-content", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            catalog = validate_catalog_file(args.path)
            result = {"status": "PASS", "catalog_id": catalog["catalog_id"], "exemplar_count": len(catalog["exemplars"])}
        elif args.command == "pack":
            catalog = load_json(args.catalog, "catalog")
            split = load_json(args.split, "split")
            pack = load_json(args.pack, "pack")
            errors = validate_pack_payload(pack, catalog, split)
            if errors:
                raise ContractError("Pack validation failed: " + "; ".join(errors))
            result = {"status": "PASS", "role": pack["role"], "pack_fingerprint": pack["pack_fingerprint"], "exemplar_count": len(pack["exemplar_ids"])}
        else:
            catalog = load_json(args.catalog, "catalog")
            split = load_json(args.split, "split")
            pack = load_json(args.pack, "pack")
            selection = load_json(args.selection, "selection")
            lesson_content, raw_content = _read_source(args)
            if args.command == "authoring-selection":
                errors = validate_authoring_selection_payload(selection, catalog, split, pack, lesson_content)
                role = "authoring"
            else:
                errors = validate_holdout_selection_payload(
                    selection, catalog, split, pack, lesson_content,
                    lesson_content_sha256=hashlib.sha256(raw_content).hexdigest(),
                )
                role = "holdout"
            if errors:
                raise ContractError(f"{role} Selection validation failed: " + "; ".join(errors))
            result = {
                "status": "PASS",
                "selection_role": role,
                "pack_fingerprint": pack["pack_fingerprint"],
                **selection_size_report(catalog, pack, selection),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
