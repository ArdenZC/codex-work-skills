"""Source Truth Manifest Contract 1.0 validation for Lesson lifecycle sidecars."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import re
from pathlib import Path, PurePosixPath
import sys
from typing import Any
import unicodedata
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from lifecycle_digest import (
    LifecycleContractError,
    is_sha256,
    read_json_object,
    schema_errors,
    semantic_fingerprint,
    sha256_bytes,
    sha256_file,
    timezone_aware_timestamp,
)


SOURCE_TYPES = {
    "confirmed_course_profile", "curriculum_standard", "textbook", "textbook_toc",
    "whole_course_outline", "capability_map", "reference_pool", "user_attachment",
    "other_authoritative_source",
}
FINGERPRINT_EXCLUDED_FIELDS = {"created_at", "manifest_fingerprint"}
SECRET_QUERY_KEYS = {"token", "access_token", "auth", "apikey", "api_key", "signature", "sig"}


def source_truth_fingerprint(payload: Mapping[str, Any]) -> str:
    return semantic_fingerprint(
        payload,
        excluded_fields=FINGERPRINT_EXCLUDED_FIELDS,
        unordered_arrays={"sources"},
    )


def _canonical_https_locator(value: str) -> str:
    if value != value.strip() or any(character.isspace() for character in value):
        raise LifecycleContractError("source URL locators must not contain whitespace")
    parts = urlsplit(value)
    if parts.scheme.casefold() != "https" or not parts.hostname:
        raise LifecycleContractError("source URL locators must use HTTPS")
    if parts.username is not None or parts.password is not None:
        raise LifecycleContractError("source URL locators must not contain credentials")
    if parts.fragment:
        raise LifecycleContractError("source URL locators must not contain fragments")
    if any(key.casefold() in SECRET_QUERY_KEYS for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        raise LifecycleContractError("source URL locators must not contain credential-like query parameters")
    try:
        host = parts.hostname.encode("idna").decode("ascii").lower()
        port = parts.port
    except (UnicodeError, ValueError) as exc:
        raise LifecycleContractError(f"invalid HTTPS source locator: {exc}") from exc
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port is not None and port != 443:
        host = f"{host}:{port}"
    normalized = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    from exemplar_contract import normalize_canonical_url

    return normalize_canonical_url(normalized)


def _local_source_path(locator: str, manifest_path: Path) -> Path:
    if "\\" in locator or locator.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", locator):
        raise LifecycleContractError("local source locator must be a relative POSIX path")
    components = locator.split("/")
    reserved_names = {"con", "prn", "aux", "nul", *(f"com{index}" for index in range(1, 10)), *(f"lpt{index}" for index in range(1, 10))}
    if any(
        component in {"", ".", ".."}
        or ":" in component
        or "?" in component
        or "#" in component
        or component.endswith((".", " "))
        or component.split(".", 1)[0].casefold() in reserved_names
        for component in components
    ):
        raise LifecycleContractError("local source locator must not contain empty, '.' or '..' components")
    pure = PurePosixPath(locator)
    if pure.is_absolute() or pure.as_posix() != locator:
        raise LifecycleContractError("local source locator must be a normalized relative POSIX path")
    base = manifest_path.absolute().parent
    candidate = base.joinpath(*components)
    try:
        resolved_base = base.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise LifecycleContractError(f"local source path escapes the manifest directory or is missing: {locator}") from exc
    from exemplar_contract import assert_distinct_file_paths

    try:
        assert_distinct_file_paths({"manifest": manifest_path, "source": candidate})
    except (OSError, ValueError) as exc:
        raise LifecycleContractError(f"unsafe local source path {locator}: {exc}") from exc
    return resolved_candidate


def source_truth_local_file_paths(payload: Mapping[str, Any], manifest_path: str | Path) -> dict[str, Path]:
    """Resolve and safety-check every local source locator in a validated manifest."""
    base = Path(manifest_path).expanduser()
    paths: dict[str, Path] = {}
    for index, source in enumerate(payload.get("sources", [])):
        locator = source.get("locator") if isinstance(source, Mapping) else None
        if not isinstance(locator, str) or "://" in locator:
            continue
        paths[f"source_truth_source_{index}"] = _local_source_path(locator, base)
    return paths


def validate_source_truth_payload(
    payload: Mapping[str, Any],
    *,
    manifest_path: str | Path | None = None,
    verify_source_bytes: bool = True,
) -> list[str]:
    errors = schema_errors(payload, "source-truth-manifest.schema.json")
    if errors:
        return errors
    if not timezone_aware_timestamp(payload.get("created_at")):
        errors.append("created_at must include a timezone")
    for field in ("source_truth_id",):
        if not str(payload.get(field, "")).strip():
            errors.append(f"{field} must contain non-whitespace text")
    for field in ("course_name", "major", "audience"):
        if not str(payload.get("course_identity", {}).get(field, "")).strip():
            errors.append(f"course_identity.{field} must contain non-whitespace text")
    expected = source_truth_fingerprint(payload)
    if payload.get("manifest_fingerprint", "").casefold() != expected:
        errors.append("manifest_fingerprint does not match canonical semantic content")

    source_ids: set[str] = set()
    semantic_sources: set[str] = set()
    local_paths: dict[str, Path] = {}
    source_types: set[str] = set()
    base = Path(manifest_path).expanduser() if manifest_path is not None else None
    for index, source in enumerate(payload.get("sources", [])):
        if not isinstance(source, Mapping):
            continue
        source_id = source.get("source_id")
        if isinstance(source_id, str):
            normalized_id = unicodedata.normalize("NFC", source_id).strip()
            if not normalized_id:
                errors.append(f"sources[{index}].source_id must contain non-whitespace text")
            if normalized_id in source_ids:
                errors.append(f"sources[{index}].source_id is duplicated: {normalized_id}")
            source_ids.add(normalized_id)
        for field in ("label", "locator", "provenance"):
            if not str(source.get(field, "")).strip():
                errors.append(f"sources[{index}].{field} must contain non-whitespace text")
        source_type = source.get("source_type")
        locator = source.get("locator")
        source_types.add(str(source_type))
        if not isinstance(locator, str):
            continue
        try:
            if "://" in locator:
                canonical_locator = _canonical_https_locator(locator)
                identity_locator = canonical_locator
            else:
                if base is None:
                    if verify_source_bytes:
                        errors.append(f"sources[{index}] local locator cannot be checked without manifest_path")
                    identity_locator = PurePosixPath(locator).as_posix()
                else:
                    source_path = _local_source_path(locator, base)
                    identity_locator = source_path.as_posix().casefold()
                    local_paths[f"source_{index}"] = source_path
                    if verify_source_bytes:
                        actual = sha256_file(source_path)
                        if actual.casefold() != str(source.get("sha256", "")).casefold():
                            errors.append(f"sources[{index}].sha256 does not match local source bytes")
            if identity_locator in semantic_sources:
                errors.append(f"sources[{index}] duplicates a semantic source locator")
            semantic_sources.add(identity_locator)
        except LifecycleContractError as exc:
            errors.append(f"sources[{index}].locator is unsafe: {exc}")
    for critical in ("confirmed_course_profile", "whole_course_outline"):
        if critical not in source_types:
            errors.append(f"sources must include critical source_type {critical}")

    if base is not None and local_paths:
        try:
            from exemplar_contract import assert_distinct_file_paths

            assert_distinct_file_paths({"manifest": base, **local_paths})
        except (OSError, ValueError) as exc:
            errors.append(f"manifest and local source paths must be distinct, ordinary paths: {exc}")
    return errors


def validate_source_truth_file(path: str | Path, *, verify_source_bytes: bool = True) -> tuple[dict[str, Any], bytes, list[str]]:
    payload, raw = read_json_object(path, "source_truth_manifest")
    errors = validate_source_truth_payload(payload, manifest_path=path, verify_source_bytes=verify_source_bytes)
    return payload, raw, errors


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "fingerprint"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("manifest", type=Path)
        if command == "validate":
            command_parser.add_argument("--skip-source-bytes", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload, raw = read_json_object(args.manifest, "source_truth_manifest")
        if args.command == "fingerprint":
            print(source_truth_fingerprint(payload))
            return 0
        errors = validate_source_truth_payload(
            payload,
            manifest_path=args.manifest,
            verify_source_bytes=not args.skip_source_bytes,
        )
    except LifecycleContractError as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"VALID source_truth_manifest_sha256={sha256_bytes(raw)}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
