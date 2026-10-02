"""Bind Lesson Content to a locally verifiable, frozen course outline.

This module owns one domain-agnostic scope gate shared by Content QA, the
canonical pipeline, Production Authorization, and the generator.  It treats
the frozen outline as the course authority and reuses Content QA's existing
substantive anchor and intra-Lesson coherence checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from exemplar_contract import assert_distinct_file_paths
from lifecycle_digest import LifecycleContractError, sha256_bytes
from package_common import canonical_json_sha256
from source_truth import source_truth_local_file_paths, validate_source_truth_file


SHARED_PLANNING_FIELDS = (
    "lesson_id",
    "unit",
    "task",
    "lesson_type",
    "hours",
    "theory_hours",
    "practice_hours",
    "practice_task_ids",
)
PROGRESSION_TO_OUTLINE_FIELDS = {
    "prior_learning": "prior_learning",
    "capability_stage": "capability_stage",
    "deliverable": "deliverable",
    "next_bridge": "next_bridge",
}
SCOPE_ANCHOR_FIELDS = ("unit", "task", "prior_learning", "deliverable", "next_bridge")
SCOPE_SEMANTIC_ANCHOR_FIELDS = ("task", "deliverable", "next_bridge")
OUTLINE_REQUIRED_FIELDS = (
    "lesson_id",
    "unit",
    "task",
    "lesson_type",
    "hours",
    "theory_hours",
    "practice_hours",
    "prior_learning",
    "capability_stage",
    "deliverable",
    "next_bridge",
    "practice_task_ids",
)


class CourseScopeGroundingError(ValueError):
    """A stable, user-safe failure from the frozen-outline authority chain."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FrozenCourseOutline:
    source_truth: dict[str, Any]
    source_truth_manifest_sha256: str
    source_id: str
    source_sha256: str
    path: Path | None
    outline: list[dict[str, Any]] | None


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _canonical_equal(left: Any, right: Any) -> bool:
    try:
        return _canonical_json(left) == _canonical_json(right)
    except (TypeError, ValueError, UnicodeError):
        return False


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _outline_schema_errors(outline: Any) -> list[str]:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "lesson-plan-input.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        from jsonschema import Draft202012Validator
    except (OSError, UnicodeError, json.JSONDecodeError, ImportError) as exc:
        raise CourseScopeGroundingError("outline_schema_unavailable", "The canonical Content outline schema could not be loaded.") from exc
    outline_schema = {
        "$schema": schema.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "$defs": schema.get("$defs", {}),
        "type": "array",
        "items": {"$ref": "#/$defs/outlineItem"},
    }
    errors = sorted(
        Draft202012Validator(outline_schema).iter_errors(outline),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    return [
        f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in errors[:24]
    ]


def load_frozen_course_outline(
    source_truth_path: str | Path,
    *,
    require_local_bytes: bool = True,
    content_path: str | Path | None = None,
) -> FrozenCourseOutline:
    """Read and verify the single Source Truth whole-course-outline source.

    No network retrieval is attempted. A remote outline can be classified as
    unverified for PREVIEW, but strict Production callers require local bytes.
    """

    manifest_path = Path(source_truth_path).expanduser()
    try:
        source_truth, manifest_raw, errors = validate_source_truth_file(
            manifest_path,
            verify_source_bytes=True,
        )
    except (LifecycleContractError, OSError, ValueError) as exc:
        raise CourseScopeGroundingError("source_truth_invalid", "Source Truth or its local source bytes failed validation.") from exc
    if errors:
        raise CourseScopeGroundingError("source_truth_invalid", "Source Truth or its local source bytes failed validation.")

    sources = source_truth.get("sources", [])
    if not isinstance(sources, list):
        raise CourseScopeGroundingError("outline_source_missing", "Source Truth must contain one whole-course outline source.")
    matching = [
        (index, source)
        for index, source in enumerate(sources)
        if isinstance(source, Mapping) and source.get("source_type") == "whole_course_outline"
    ]
    if len(matching) != 1:
        code = "outline_source_missing" if not matching else "outline_source_ambiguous"
        raise CourseScopeGroundingError(code, "Source Truth must contain exactly one whole-course outline authority.")

    index, source = matching[0]
    locator = source.get("locator")
    source_id = source.get("source_id")
    source_sha = str(source.get("sha256", "")).lower()
    if not isinstance(locator, str) or not isinstance(source_id, str) or len(source_sha) != 64:
        raise CourseScopeGroundingError("outline_source_invalid", "The whole-course outline source entry is invalid.")

    manifest_sha = sha256_bytes(manifest_raw)
    if "://" in locator:
        if require_local_bytes:
            raise CourseScopeGroundingError(
                "outline_bytes_unverified",
                "Production requires locally verifiable whole-course outline bytes; remote locators are not fetched.",
            )
        return FrozenCourseOutline(source_truth, manifest_sha, source_id, source_sha, None, None)

    try:
        local_paths = source_truth_local_file_paths(source_truth, manifest_path)
        outline_path = local_paths[f"source_truth_source_{index}"]
        path_inventory: dict[str, Path] = {
            "source_truth_manifest": manifest_path,
            "frozen_course_outline": outline_path,
        }
        if content_path is not None:
            path_inventory["lesson_content"] = Path(content_path).expanduser()
        assert_distinct_file_paths(path_inventory)
        outline_raw = outline_path.read_bytes()
    except (LifecycleContractError, OSError, KeyError, ValueError) as exc:
        raise CourseScopeGroundingError(
            "outline_path_unsafe",
            "The whole-course outline path is missing, aliased, symlinked, or otherwise unsafe.",
        ) from exc
    actual_sha = hashlib.sha256(outline_raw).hexdigest()
    if actual_sha != source_sha:
        raise CourseScopeGroundingError("outline_sha256_mismatch", "Frozen outline bytes do not match the Source Truth SHA-256.")
    try:
        outline = json.loads(
            outline_raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CourseScopeGroundingError("outline_json_invalid", "Frozen outline bytes are not valid UTF-8 JSON.") from exc
    if not isinstance(outline, list):
        raise CourseScopeGroundingError("outline_shape_invalid", "Frozen whole-course outline JSON must have an array at the top level.")
    schema_errors = _outline_schema_errors(outline)
    if schema_errors:
        raise CourseScopeGroundingError("outline_schema_invalid", "Frozen outline rows do not match the formal Content outline schema.")
    seen_ids: set[str] = set()
    for row in outline:
        if not isinstance(row, Mapping):  # Defensive: the formal schema already rejects this.
            raise CourseScopeGroundingError("outline_schema_invalid", "Every frozen outline row must be an object.")
        lesson_id = row.get("lesson_id")
        if lesson_id in seen_ids:
            raise CourseScopeGroundingError("outline_duplicate_lesson_id", "Frozen outline lesson_id values must be unique.")
        seen_ids.add(str(lesson_id))
        if any(field not in row for field in OUTLINE_REQUIRED_FIELDS):
            raise CourseScopeGroundingError("outline_schema_invalid", "Frozen outline rows are missing required planning fields.")
    return FrozenCourseOutline(source_truth, manifest_sha, source_id, actual_sha, outline_path, outline)


def _body_nodes(lesson: Mapping[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for field in ("teaching_content",):
        sequence = lesson.get(field, [])
        if isinstance(sequence, list):
            values.extend((f"{field}[{index}]", value) for index, value in enumerate(sequence) if isinstance(value, str) and value.strip())
    for field in ("key_point", "difficult_point"):
        block = lesson.get(field, {})
        sequence = block.get("content", []) if isinstance(block, Mapping) else []
        if isinstance(sequence, list):
            values.extend((f"{field}.content[{index}]", value) for index, value in enumerate(sequence) if isinstance(value, str) and value.strip())
    return values


def _lesson_outline_alignment(lesson: Mapping[str, Any], outline_row: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for field in SHARED_PLANNING_FIELDS:
        if not _canonical_equal(lesson.get(field), outline_row.get(field)):
            mismatches.append(field)
    progression = lesson.get("progression", {})
    if not isinstance(progression, Mapping):
        return [*mismatches, *PROGRESSION_TO_OUTLINE_FIELDS]
    for lesson_field, outline_field in PROGRESSION_TO_OUTLINE_FIELDS.items():
        if not _canonical_equal(progression.get(lesson_field), outline_row.get(outline_field)):
            mismatches.append(f"progression.{lesson_field}")
    return mismatches


def _report_failure(code: str, message: str, lesson_id: str | None = None) -> dict[str, Any]:
    failure: dict[str, Any] = {"code": code, "message": message}
    if lesson_id is not None:
        failure["lesson_id"] = lesson_id
    return failure


def validate_course_scope_grounding(
    content: Mapping[str, Any],
    source_truth_path: str | Path | None = None,
    *,
    content_path: str | Path | None = None,
    require_local_outline: bool = False,
    intra_lesson_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded report for outline binding, alignment, and scope anchors."""

    lessons_value = content.get("lessons", [])
    lessons = [lesson for lesson in lessons_value if isinstance(lesson, Mapping)] if isinstance(lessons_value, list) else []
    lesson_ids = [str(lesson.get("lesson_id", "")) for lesson in lessons]
    outline_value = content.get("outline")
    content_outline_hash = None
    try:
        if isinstance(outline_value, list):
            content_outline_hash = canonical_json_sha256(outline_value).lower()
    except (TypeError, ValueError, UnicodeError):
        pass

    if intra_lesson_report is None or source_truth_path is not None:
        try:
            try:
                from content_quality import _intra_lesson_coherence
            except ModuleNotFoundError:
                from .content_quality import _intra_lesson_coherence

            intra = _intra_lesson_coherence(
                lessons,
                lesson_ids,
                require_body_scope_anchors=source_truth_path is not None,
            )
        except Exception:
            intra = {"status": "failed", "lessons": [], "failures": []}
    else:
        intra = dict(intra_lesson_report)
    intra_by_id = {
        str(item.get("lesson_id")): item
        for item in intra.get("lessons", [])
        if isinstance(item, Mapping)
    }
    report: dict[str, Any] = {
        "status": "not_provided" if source_truth_path is None else "failed",
        "source_truth_manifest_sha256": None,
        "source_truth_outline_sha256": None,
        "content_outline_sha256": content_outline_hash,
        "lesson_count": len(lessons),
        "lessons": [
            {
                "lesson_id": lesson_id,
                "outline_alignment": "not_checked",
                "scope_anchor_status": "not_checked",
                "intra_lesson_status": "passed" if intra.get("status") == "passed" else "failed",
            }
            for lesson_id in lesson_ids
        ],
        "failures": [],
    }
    if source_truth_path is None:
        if require_local_outline:
            report["failures"].append(_report_failure(
                "source_truth_missing",
                "Canonical Production scope grounding requires a Source Truth outline authority.",
            ))
            report["status"] = "failed"
            return report
        if intra.get("status") != "passed":
            report["failures"].append(_report_failure("intra_lesson_coherence", "Existing intra-Lesson coherence validation failed."))
        return report

    try:
        frozen = load_frozen_course_outline(
            source_truth_path,
            require_local_bytes=require_local_outline,
            content_path=content_path,
        )
    except CourseScopeGroundingError as exc:
        report["failures"].append(_report_failure(exc.code, exc.message))
        report["status"] = "failed"
        return report
    except Exception:
        report["failures"].append(_report_failure("scope_validation_error", "Course-scope grounding could not be completed safely."))
        report["status"] = "failed"
        return report

    report["source_truth_manifest_sha256"] = frozen.source_truth_manifest_sha256
    report["source_truth_outline_sha256"] = frozen.source_sha256
    course_identity = frozen.source_truth.get("course_identity", {})
    confirmed = content.get("confirmed_course_info", {})
    for field in ("course_name", "major", "audience"):
        if not isinstance(course_identity, Mapping) or content.get(field) != course_identity.get(field) or (
            not isinstance(confirmed, Mapping) or confirmed.get(field) != course_identity.get(field)
        ):
            report["failures"].append(_report_failure("course_identity_mismatch", f"Source Truth course identity {field} does not match Content."))

    snapshot = (content.get("authoring_provenance") or {}).get("source_snapshot", {})
    snapshot_outline_hash = snapshot.get("whole_course_outline_sha256") if isinstance(snapshot, Mapping) else None
    if not isinstance(snapshot_outline_hash, str) or not content_outline_hash or snapshot_outline_hash.casefold() != content_outline_hash:
        report["failures"].append(_report_failure(
            "content_outline_snapshot_mismatch",
            "Content outline does not match authoring_provenance.source_snapshot.whole_course_outline_sha256.",
        ))

    if frozen.outline is None:
        report["status"] = "failed" if report["failures"] else "unverified"
        report["warnings"] = ["whole-course outline bytes are not locally verifiable; Production Authorization is unavailable"]
        for row in report["lessons"]:
            row["outline_alignment"] = "unverified"
            row["scope_anchor_status"] = "unverified"
        if intra.get("status") != "passed":
            report["failures"].append(_report_failure("intra_lesson_coherence", "Existing intra-Lesson coherence validation failed."))
            report["status"] = "failed"
        return report

    frozen_outline = frozen.outline
    if not isinstance(outline_value, list) or not _canonical_equal(outline_value, frozen_outline):
        report["failures"].append(_report_failure(
            "content_outline_frozen_mismatch",
            "Content.outline does not canonically equal the frozen Source Truth whole-course outline.",
        ))

    outline_ids = [str(row.get("lesson_id", "")) for row in frozen_outline]
    if len(lesson_ids) != len(set(lesson_ids)):
        report["failures"].append(_report_failure("duplicate_lesson_id", "Content lessons must have unique lesson_id values."))
    if len(outline_ids) != len(set(outline_ids)):
        report["failures"].append(_report_failure("duplicate_outline_lesson_id", "Frozen outline lesson_id values must be unique."))
    if set(lesson_ids) != set(outline_ids):
        report["failures"].append(_report_failure("lesson_set_mismatch", "Content lessons must cover exactly the frozen outline lesson_id set."))
    if lesson_ids != outline_ids:
        report["failures"].append(_report_failure("lesson_order_mismatch", "Content lesson order must match frozen outline order."))
    outline_by_id = {str(row.get("lesson_id", "")): row for row in frozen_outline}
    report_rows = {row["lesson_id"]: row for row in report["lessons"]}
    mismatch_by_id: dict[str, list[str]] = {}
    for lesson in lessons:
        lesson_id = str(lesson.get("lesson_id", ""))
        outline_row = outline_by_id.get(lesson_id)
        if outline_row is None:
            mismatch_by_id[lesson_id] = ["missing_outline_row"]
            report["failures"].append(_report_failure(
                "lesson_out_of_frozen_outline_scope",
                "Lesson has no unique matching frozen outline row.",
                lesson_id,
            ))
            continue
        mismatches = _lesson_outline_alignment(lesson, outline_row)
        mismatch_by_id[lesson_id] = mismatches
        if mismatches:
            report["failures"].append(_report_failure(
                "lesson_out_of_frozen_outline_scope",
                "Lesson planning fields do not exactly match the frozen outline row.",
                lesson_id,
            ))
        row_report = report_rows.get(lesson_id)
        if row_report is not None:
            row_report["outline_alignment"] = "failed" if mismatches else "passed"

        intra_record = intra_by_id.get(lesson_id, {})
        core_members = set((intra_record.get("main_component") or {}).get("members", [])) if isinstance(intra_record, Mapping) else set()
        body_nodes = _body_nodes(lesson)
        connected_body = [(node_id, value) for node_id, value in body_nodes if node_id in core_members]
        if not connected_body:
            if row_report is not None:
                row_report["scope_anchor_status"] = "failed"
            report["failures"].append(_report_failure(
                "lesson_out_of_frozen_outline_scope",
                "Task-connected instructional body is empty.",
                lesson_id,
            ))
            continue
        anchors = {field: outline_row.get(field, "") for field in SCOPE_ANCHOR_FIELDS}
        matches: list[tuple[str, str, dict[str, Any]]] = []
        context_matches: list[tuple[str, str, dict[str, Any]]] = []
        try:
            try:
                from content_quality import _intra_anchor_evidence
            except ModuleNotFoundError:
                from .content_quality import _intra_anchor_evidence

            for node_id, value in connected_body:
                for anchor_field, anchor_value in anchors.items():
                    evidence = _intra_anchor_evidence(value, anchor_value)
                    if evidence.get("status") == "passed":
                        match = (node_id, anchor_field, evidence)
                        if anchor_field in SCOPE_SEMANTIC_ANCHOR_FIELDS:
                            matches.append(match)
                        else:
                            context_matches.append(match)
        except Exception:
            matches = []
        if matches:
            if row_report is not None:
                row_report["scope_anchor_status"] = "passed"
                row_report["scope_anchor"] = {
                    "body_node": matches[0][0],
                    "outline_field": matches[0][1],
                    "evidence": {
                        key: matches[0][2][key]
                        for key in ("status", "score", "matched_fragments", "longest_substantive_match", "acronym_matches")
                        if key in matches[0][2]
                    },
                }
                if context_matches:
                    row_report["scope_context_anchor"] = {
                        "body_node": context_matches[0][0],
                        "outline_field": context_matches[0][1],
                    }
        else:
            if row_report is not None:
                row_report["scope_anchor_status"] = "failed"
            report["failures"].append(_report_failure(
                "lesson_out_of_frozen_outline_scope",
                "Task-connected instructional content has no substantive anchor to frozen task, deliverable, or next_bridge.",
                lesson_id,
            ))

    if intra.get("status") != "passed":
        report["failures"].append(_report_failure(
            "intra_lesson_coherence",
            "Existing intra-Lesson coherence validation failed.",
        ))
    report["status"] = "failed" if report["failures"] else "passed"
    return report


def format_scope_failures(report: Mapping[str, Any]) -> list[str]:
    """Return concise gate messages without copying teaching body text."""

    return [
        f"{item.get('code', 'course_scope_grounding')}: {item.get('message', 'validation failed')}"
        for item in report.get("failures", [])
        if isinstance(item, Mapping)
    ]
