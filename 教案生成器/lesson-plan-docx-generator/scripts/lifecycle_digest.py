"""Shared canonical digests and safe artifact I/O for Lesson lifecycle contracts.

This module is deliberately independent of the production generator. It defines
the byte identity used by opt-in Lifecycle 1.0 sidecars and never writes files.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_DIR = SKILL_DIR / "schemas"
SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[a-fA-F0-9]{40}$")


class LifecycleContractError(ValueError):
    """Raised when lifecycle evidence cannot be read or canonicalized safely."""


def _canonical_value(
    value: Any,
    *,
    path: tuple[str, ...],
    unordered_arrays: frozenset[tuple[str, ...]],
) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise LifecycleContractError("floating-point values are not allowed in lifecycle canonical JSON")
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        field_name = path[-1] if path else ""
        if (
            field_name == "sha256"
            or field_name.endswith("_sha256")
            or field_name.endswith("_fingerprint")
        ) and SHA256_PATTERN.fullmatch(normalized):
            return normalized.lower()
        if field_name.endswith("_commit") and re.fullmatch(r"[A-Fa-f0-9]{40}", normalized):
            return normalized.lower()
        return normalized
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise LifecycleContractError("canonical JSON object keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized:
                raise LifecycleContractError(f"duplicate object key after NFC normalization: {key!r}")
            normalized[key] = _canonical_value(
                raw_value,
                path=(*path, key),
                unordered_arrays=unordered_arrays,
            )
        return normalized
    if isinstance(value, (list, tuple)):
        items = [
            _canonical_value(item, path=(*path, str(index)), unordered_arrays=unordered_arrays)
            for index, item in enumerate(value)
        ]
        if path in unordered_arrays:
            items.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return items
    raise LifecycleContractError(f"unsupported canonical JSON value: {type(value).__name__}")


def _parse_paths(paths: Iterable[str | tuple[str, ...]]) -> frozenset[tuple[str, ...]]:
    parsed: set[tuple[str, ...]] = set()
    for item in paths:
        parts = tuple(item.split(".")) if isinstance(item, str) else tuple(item)
        if not parts or any(not isinstance(part, str) or not part for part in parts):
            raise LifecycleContractError("canonical path declarations must be non-empty field paths")
        parsed.add(parts)
    return frozenset(parsed)


def canonical_json_bytes(
    value: Any,
    *,
    unordered_arrays: Iterable[str | tuple[str, ...]] = (),
) -> bytes:
    """Encode JSON deterministically: NFC strings, sorted keys, no floats.

    Arrays preserve order unless their exact object path is declared unordered.
    Unordered arrays are sorted by each normalized element's canonical JSON.
    """

    normalized = _canonical_value(
        value,
        path=(),
        unordered_arrays=_parse_paths(unordered_arrays),
    )
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise LifecycleContractError(f"cannot encode canonical lifecycle JSON: {exc}") from exc


def semantic_fingerprint(
    payload: Mapping[str, Any],
    *,
    excluded_fields: Iterable[str] = (),
    unordered_arrays: Iterable[str | tuple[str, ...]] = (),
) -> str:
    """Hash a contract payload while excluding only declared top-level fields."""

    if not isinstance(payload, Mapping):
        raise LifecycleContractError("fingerprint payload must be an object")
    excluded = frozenset(excluded_fields)
    semantic = {key: value for key, value in payload.items() if key not in excluded}
    return hashlib.sha256(canonical_json_bytes(semantic, unordered_arrays=unordered_arrays)).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_PATTERN.fullmatch(value))


def is_git_commit(value: Any) -> bool:
    return isinstance(value, str) and bool(GIT_COMMIT_PATTERN.fullmatch(value))


def _assert_distinct_safe_paths(paths: Mapping[str, Path]) -> None:
    try:
        from exemplar_contract import assert_distinct_file_paths

        assert_distinct_file_paths(paths)
    except (ImportError, OSError, ValueError) as exc:
        raise LifecycleContractError(str(exc)) from exc


def assert_distinct_safe_paths(paths: Mapping[str, str | Path]) -> None:
    """Reject aliased paths and any input that traverses a symlink component."""
    _assert_distinct_safe_paths({label: Path(path).expanduser() for label, path in paths.items()})


def sha256_file(path: Path | str) -> str:
    """Hash one ordinary file without following a symlinked path component."""

    file_path = Path(path).expanduser()
    _assert_distinct_safe_paths({"artifact": file_path})
    try:
        info = file_path.stat()
        if not stat.S_ISREG(info.st_mode) or file_path.is_symlink():
            raise LifecycleContractError(f"artifact is not a regular non-symlink file: {file_path}")
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except LifecycleContractError:
        raise
    except OSError as exc:
        raise LifecycleContractError(f"cannot hash artifact {file_path}: {exc}") from exc


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        normalized = unicodedata.normalize("NFC", key)
        if normalized in result:
            raise LifecycleContractError(f"duplicate JSON property after NFC normalization: {normalized!r}")
        result[normalized] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise LifecycleContractError(f"non-standard JSON numeric constant is not allowed: {value}")


def read_json_object(path: Path | str, label: str) -> tuple[dict[str, Any], bytes]:
    """Read a JSON object and raw bytes, rejecting duplicate keys and symlinks."""

    file_path = Path(path).expanduser()
    _assert_distinct_safe_paths({label: file_path})
    try:
        raw = file_path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except LifecycleContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LifecycleContractError(f"cannot read {label} JSON at {file_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LifecycleContractError(f"{label} must be a JSON object")
    return value, raw


def schema_errors(payload: Any, schema_name: str) -> list[str]:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover - dependency is declared in Lesson requirements
        raise LifecycleContractError("jsonschema is required for lifecycle contract validation") from exc
    schema_path = SCHEMA_DIR / schema_name
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LifecycleContractError(f"cannot read lifecycle schema {schema_path}: {exc}") from exc
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: (list(error.absolute_path), error.message))
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    ]


def timezone_aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def skill_tree_inventory(root: Path | str) -> dict[str, str]:
    """Hash a Skill tree's regular files, excluding only Python cache trees.

    Symlinks, special files, and ordinary scripts-directory .pyc/.pyo files fail
    closed. Paths in the inventory are relative POSIX names, never machine paths.
    """

    root_path = Path(root).expanduser()
    _assert_distinct_safe_paths({"skill_root": root_path})
    if root_path.is_symlink() or not root_path.is_dir():
        raise LifecycleContractError(f"skill_root must be an ordinary directory: {root_path}")
    inventory: dict[str, str] = {}
    for current, directories, files in os.walk(root_path, topdown=True, followlinks=False):
        current_path = Path(current)
        retained_directories: list[str] = []
        for name in directories:
            child = current_path / name
            if child.is_symlink():
                raise LifecycleContractError(f"skill tree contains a symbolic link: {child}")
            if name == "__pycache__":
                continue
            if not child.is_dir():
                raise LifecycleContractError(f"skill tree contains a non-directory entry: {child}")
            retained_directories.append(name)
        directories[:] = retained_directories
        for name in files:
            file_path = current_path / name
            if file_path.is_symlink():
                raise LifecycleContractError(f"skill tree contains a symbolic link: {file_path}")
            if file_path.suffix.casefold() in {".pyc", ".pyo"}:
                raise LifecycleContractError(f"Python bytecode outside __pycache__ is not allowed: {file_path}")
            try:
                mode = file_path.stat().st_mode
            except OSError as exc:
                raise LifecycleContractError(f"cannot stat skill file {file_path}: {exc}") from exc
            if not stat.S_ISREG(mode):
                raise LifecycleContractError(f"skill tree contains a special file: {file_path}")
            relative = file_path.relative_to(root_path).as_posix()
            inventory[relative] = sha256_file(file_path)
    return dict(sorted(inventory.items()))


def skill_tree_fingerprint(root: Path | str) -> str:
    return semantic_fingerprint({"files": skill_tree_inventory(root)})
