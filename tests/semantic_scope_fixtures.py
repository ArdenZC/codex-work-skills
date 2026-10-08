"""Synthetic linkage fixtures, never evidence of reviewer semantic performance.

freeze_original_outline preserves the helper semantics from commit
b7bf79a64201f9cec9699605127b6b543fddfe82, tests/test_lesson_course_scope.py.
"""

from pathlib import Path
from tests.test_lesson_lifecycle_contracts import _write_json
from lifecycle_digest import sha256_bytes
from source_truth import source_truth_fingerprint


def freeze_original_outline(folder: Path, content: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    evidence = folder / "evidence"
    profile = {field: content[field] for field in ("course_name", "major", "audience")}
    profile_raw = _write_json(evidence / "confirmed-profile.json", profile)
    outline_raw = _write_json(
        evidence / "whole-course-outline.json", content["outline"]
    )
    payload = {
        "contract_version": "1.0",
        "source_truth_id": "ST-SCOPE-001",
        "course_identity": profile,
        "sources": [
            {
                "source_id": "confirmed-profile",
                "source_type": "confirmed_course_profile",
                "label": "Confirmed course facts",
                "locator": "evidence/confirmed-profile.json",
                "sha256": sha256_bytes(profile_raw),
                "provenance": "Synthetic regression fixture",
            },
            {
                "source_id": "frozen-outline",
                "source_type": "whole_course_outline",
                "label": "Frozen whole-course outline",
                "locator": "evidence/whole-course-outline.json",
                "sha256": sha256_bytes(outline_raw),
                "provenance": "Synthetic regression fixture",
            },
        ],
        "created_at": "2026-10-01T10:00:00Z",
        "manifest_fingerprint": "",
    }
    payload["manifest_fingerprint"] = source_truth_fingerprint(payload)
    path = folder / "source-truth.json"
    _write_json(path, payload)
    return path
