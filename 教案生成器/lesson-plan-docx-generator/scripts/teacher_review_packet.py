"""Deterministic human-review inputs, independent of Teacher Review Contract 1.0.

No judgments are produced here. The public builder/validator require the actual
run envelope so existing upstream validators verify all Benchmark linkage.
"""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal
import json
import math
from pathlib import Path
import unicodedata

from lifecycle_digest import (LifecycleContractError, canonical_json_bytes, read_json_object,
    schema_errors, semantic_fingerprint, sha256_file, timezone_aware_timestamp)
from package_common import DEFAULT_SCHEMA, validate_content_v2_input

POLICY_VERSION = "1.0"
REASONS = ("first_lesson", "last_lesson", "project_boundary_before", "project_boundary_after",
           "highest_content_density", "highest_practice_complexity", "benchmark_gap", "deterministic_supplemental")
DENSITY_FIELDS = ("teaching_content", "goals", "key_point", "difficult_point", "implementation", "evaluation", "reflection")
MAP_FIELDS = ("lesson_id", "unit", "task", "hours", "theory_hours", "practice_hours", "lesson_type")


def digest_projection(value):
    """Adapt legal Content decimal scalars to the existing integer-only helper.

    This is a structural payload projection, not a new canonical encoder/hash.
    Snapshots remain unchanged; raw-byte linkage and exact rederivation protect
    their original JSON types. Finite numbers use Python's round-trip spelling.
    """
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LifecycleContractError("Packet cannot represent non-finite Content numbers")
        return {"$packet_decimal": repr(value)}
    if isinstance(value, dict):
        return {key: digest_projection(item) for key, item in value.items()}
    if isinstance(value, list):
        return [digest_projection(item) for item in value]
    return value


def packet_fingerprint(packet):
    return semantic_fingerprint(digest_projection(packet), excluded_fields={"created_at", "packet_fingerprint"})


def normalized_unit(unit):
    return " ".join(unicodedata.normalize("NFC", unit).split())


def gap_summary(review):
    dimensions = review["dimensions"]
    return {
        **{severity + "_count": sum(row["severity"] == severity for row in dimensions)
           for severity in ("major", "minor", "advisory")},
        **{status + "_count": sum(row["status"] == status for row in dimensions) for status in ("GAP", "PARTIAL")},
        "gap_dimension_ids": sorted(row["dimension"] for row in dimensions if row["status"] in {"GAP", "PARTIAL"}),
    }


def gap_tuple(summary):
    return tuple(summary[field] for field in ("major_count", "GAP_count", "minor_count", "PARTIAL_count", "advisory_count"))


def practice_complexity(content, lesson):
    # 2.2 has no per-Lesson allocation authority. Separate work orders are not
    # an allocation to a Lesson, and must never be guessed into one.
    hours = int(Decimal(str(lesson.get("practice_hours", 0)))) if content["content_contract_version"] == "2.3" else 0
    task_ids = set(lesson.get("practice_task_ids", []))
    tasks = [task for task in content.get("practice_task_contract", {}).get("tasks", [])
             if task["task_id"] in task_ids or lesson["lesson_id"] in task.get("lesson_ids", [])]
    return [hours, len(tasks), *(sum(len(task[field]) for task in tasks)
            for field in ("steps", "deliverables", "acceptance_criteria", "tools_or_materials"))]


def _selection(content, reviews=None):
    """Pure mechanics; reviews are shards verified by the public artifact API.

    Private to prevent an unverified shard dictionary becoming Packet authority.
    All reason candidates are computed before any selection slots are filled.
    """
    validate_content_v2_input(content, DEFAULT_SCHEMA)
    lessons = content["lessons"]
    ids = [lesson["lesson_id"] for lesson in lessons]
    if not ids or len(ids) != len(set(ids)):
        raise LifecycleContractError("selection requires nonempty unique lesson IDs")
    if reviews is not None and set(reviews) != set(ids):
        raise LifecycleContractError("verified lesson reviews must cover the current course exactly")
    count = len(lessons)
    reasons = [set() for _ in lessons]
    reasons[0].add("first_lesson")
    reasons[-1].add("last_lesson")
    boundaries = []
    for after in range(1, count):
        if normalized_unit(lessons[after - 1]["unit"]) != normalized_unit(lessons[after]["unit"]):
            boundaries.append(after)
            reasons[after - 1].add("project_boundary_before")
            reasons[after].add("project_boundary_after")
    boundary = min(boundaries, key=lambda i: (abs(2 * (i + 1) - (count + 1)), i)) if boundaries else None
    densities = [len(canonical_json_bytes(digest_projection({field: row[field] for field in DENSITY_FIELDS}))) for row in lessons]
    density = max(range(count), key=lambda i: (densities[i], -i))
    reasons[density].add("highest_content_density")
    practices = [practice_complexity(content, row) for row in lessons]
    practice = max(range(count), key=lambda i: (practices[i], -i)) if any(row[0] > 0 for row in practices) else None
    if practice is not None:
        reasons[practice].add("highest_practice_complexity")
    gaps = [gap_summary(reviews[row["lesson_id"]]) if reviews is not None else None for row in lessons]
    gap = max(range(count), key=lambda i: (gap_tuple(gaps[i]), -i)) if reviews is not None else None
    if gap is not None and not any(gap_tuple(gaps[gap])):
        gap = None
    if gap is not None:
        reasons[gap].add("benchmark_gap")
    target = min(count, 6)
    if count <= 6:
        selected = set(range(count))
        for i in selected:
            if not reasons[i]:
                reasons[i].add("deterministic_supplemental")
    else:
        selected = {i for i in (0, count - 1, gap, boundary, practice, density) if i is not None}
        while len(selected) < target:
            i = max((i for i in range(count) if i not in selected),
                    key=lambda i: (min(abs(i - other) for other in selected), -i))
            selected.add(i)
            reasons[i].add("deterministic_supplemental")
    return [{
        "lesson_id": ids[i], "course_position": i + 1,
        "selection_reasons": [reason for reason in REASONS if reason in reasons[i]],
        "lesson_semantic_sha256": semantic_fingerprint(digest_projection(lessons[i])),
        "content_density_bytes": densities[i], "practice_complexity": practices[i],
        "benchmark_gap_summary": gaps[i], "lesson_snapshot": copy.deepcopy(lessons[i]),
    } for i in sorted(selected)]


def _upstream(run):
    # Shared orchestrator validators exclude downstream Packet/Teacher authority;
    # this avoids recursion and reuses full Review/round/shard linkage validation.
    from run_lesson_pipeline import validate_run_upstream, path_of
    validate_run_upstream(run)
    from pipeline_state import STATES
    if STATES.index(run["state"]["current_state"]) < STATES.index("READY_FOR_TEACHER_REVIEW"):
        raise LifecycleContractError("Packet requires final READY-or-later upstream evidence")
    content, _ = read_json_object(path_of(run, "content"), "Content")
    disposition, _ = read_json_object(path_of(run, "benchmark_disposition"), "final disposition")
    reviews = None
    if disposition["benchmark"]["review_sha256"] is not None:
        from validate_benchmark_review import _load_lesson_reviews
        shards, _ = _load_lesson_reviews(path_of(run, "lesson_reviews_dir"))
        reviews = {row["lesson_id"]: row for row in shards}
    return content, disposition["benchmark"], reviews


def build_teacher_review_packet(run, *, created_at=None):
    from benchmark_preparation import timestamp
    from run_lesson_pipeline import path_of
    content, benchmark, reviews = _upstream(run)
    result = {
        "contract_version": "1.0", "packet_id": "TRP-" + semantic_fingerprint({"pipeline_run_id": run["state"]["pipeline_run_id"]}),
        "pipeline_run_id": run["state"]["pipeline_run_id"],
        "source_truth_manifest_sha256": sha256_file(path_of(run, "source_truth")),
        "content_sha256": sha256_file(path_of(run, "content")),
        "benchmark": copy.deepcopy(benchmark),
        "benchmark_disposition_sha256": sha256_file(path_of(run, "benchmark_disposition")),
        "benchmark_review_sha256": benchmark["review_sha256"],
        "selection_policy_version": POLICY_VERSION, "target_count": min(6, len(content["lessons"])),
        "selected_lessons": _selection(content, reviews),
        "course_map": [{"course_position": i + 1, **{field: copy.deepcopy(row[field]) for field in MAP_FIELDS if field in row}}
                       for i, row in enumerate(content["lessons"])],
        "created_at": created_at if created_at is not None else timestamp(),
    }
    result["packet_fingerprint"] = packet_fingerprint(result)
    if run["orchestrator_version"] == "2.0":
        from semantic_lifecycle import packet_scope
        result["contract_version"] = "2.0"
        result["semantic_scope"] = packet_scope(run)
        result["packet_fingerprint"] = packet_fingerprint(result)
    errors = schema_errors(result, "teacher-review-packet-v2.schema.json" if result["contract_version"] == "2.0" else "teacher-review-packet.schema.json")
    if errors or not timezone_aware_timestamp(result["created_at"]):
        raise LifecycleContractError("invalid Packet: " + "; ".join(errors))
    return result


def validate_teacher_review_packet(packet_path, run):
    packet, _ = read_json_object(packet_path, "Teacher Review Packet")
    errors = schema_errors(packet, "teacher-review-packet-v2.schema.json" if packet.get("contract_version") == "2.0" else "teacher-review-packet.schema.json")
    if errors:
        raise LifecycleContractError("invalid Packet schema: " + "; ".join(errors))
    if packet["packet_fingerprint"] != packet_fingerprint(packet):
        raise LifecycleContractError("invalid Packet self fingerprint")
    expected = build_teacher_review_packet(run, created_at=packet["created_at"])
    # Exact object comparison also protects snapshots beyond NFC hash equivalence.
    if packet != expected:
        raise LifecycleContractError("STALE/INVALID Teacher Review Packet differs from rederived upstream selection")
    return packet


def validate_teacher_review_against_packet(review, packet):
    """Lock ordered IDs/reasons only. Human assessments remain external."""
    fields = ("lesson_id", "selection_reasons")
    if [{field: row[field] for field in fields} for row in review["selected_lessons"]] != [
            {field: row[field] for field in fields} for row in packet["selected_lessons"]]:
        raise LifecycleContractError("Teacher Review selected lessons/reasons must exactly match Packet order")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run, _ = read_json_object(args.run, "pipeline run")
        packet = validate_teacher_review_packet(args.packet, run)
        print(json.dumps({"status": "VALID", "contract_version": packet["contract_version"]}))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(1, f"STALE/INVALID: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
