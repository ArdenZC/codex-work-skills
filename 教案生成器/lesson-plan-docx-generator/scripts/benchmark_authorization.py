"""Validation helpers for the Lesson 2.3 Benchmark authorization sidecar."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import hashlib
import re
from typing import Any

from exemplar_contract import canonical_json_bytes, schema_errors

SKILL_VERSION = "2.3.0"
CONTENT_CONTRACT_VERSION = "2.2"
AUTHORIZATION_CONTRACT_VERSION = "1.0"
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
_STATUS_DECISIONS = {
    "BENCHMARK_REVIEW_COMPLETE": {"NO_REVISION_REQUIRED"},
    "BENCHMARK_GAPS_FOUND": {"REVISION_REQUIRED"},
    "BENCHMARK_PARTIAL": {"BENCHMARK_PARTIAL", "HUMAN_REVIEW_REQUIRED"},
    "BENCHMARK_UNAVAILABLE": {"BENCHMARK_UNAVAILABLE"},
    "HUMAN_REVIEW_REQUIRED": {"HUMAN_REVIEW_REQUIRED"},
}


def authorization_fingerprint(payload: Mapping[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "authorization_fingerprint"}
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def _timezone_aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_authorization_payload(
    payload: Mapping[str, Any],
    *,
    source_lesson_content_sha256: str | None = None,
    source_final_content_sha256: str | None = None,
) -> list[str]:
    errors = schema_errors(payload, "benchmark-authorization.schema.json")
    if errors:
        return errors
    if not _timezone_aware_timestamp(payload.get("created_at")):
        errors.append("created_at must be a valid timezone-aware timestamp")
    if payload.get("authorization_fingerprint", "").casefold() != authorization_fingerprint(payload).casefold():
        errors.append("authorization_fingerprint does not match canonical authorization fields")
    if payload.get("benchmark_decision") not in _STATUS_DECISIONS.get(payload.get("benchmark_status"), set()):
        errors.append("benchmark_status and benchmark_decision are inconsistent")
    if source_lesson_content_sha256 is not None and str(payload.get("source_lesson_content_sha256", "")).casefold() != source_lesson_content_sha256.casefold():
        errors.append("source_lesson_content_sha256 does not match the supplied Lesson Content bytes")
    if source_final_content_sha256 is not None and str(payload.get("source_final_content_sha256", "")).casefold() != source_final_content_sha256.casefold():
        errors.append("source_final_content_sha256 does not match reviewed Lesson content")
    return errors


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))
