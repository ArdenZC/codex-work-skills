"""Practice Class Pedagogical Integrity Review.

Structural contract validation answers whether the JSON is usable.  This
review answers whether the practice route still joins theory, action, support,
and evidence in a teachable sequence.  It deliberately reports DEGRADED for
thin but legal material so the generator does not turn every unusual workshop
format into a schema failure.
"""

from __future__ import annotations

from typing import Any

from practice_contract import normalize_content, validate_content


def review_content(content: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized, migration = normalize_content(content)
    report = contract or validate_content(normalized)
    errors: list[str] = list(report.get("errors", [])) if report.get("status") != "pass" else []
    warnings: list[str] = []
    tasks = [item for item in normalized.get("tasks", []) if isinstance(item, dict)]
    core = [item for item in tasks if item.get("level") == "core"]
    if not core:
        errors.append("practice route must contain at least one core task")
    for task in core:
        task_id = task.get("id", "unknown")
        if not task.get("source_slide_ids"):
            errors.append(f"core task {task_id} has no theory source")
        if not task.get("learning_unit_ids"):
            errors.append(f"core task {task_id} has no learning-unit bridge")
        if not task.get("canonical_fact_ids"):
            errors.append(f"core task {task_id} has no canonical-fact bridge")
        if not (task.get("starter_asset_ids") or task.get("scaffold") or task.get("help_refs")):
            errors.append(f"core task {task_id} has no self-help route")
    centers = [item for item in normalized.get("learning_center", []) if isinstance(item, dict)]
    if not centers:
        warnings.append("no learning-center interaction is provided; verify that the task/foundation route is sufficient")
    for center in centers:
        if not center.get("task_ids") and not center.get("knowledge_link_ids"):
            warnings.append(f"learning center {center.get('id', 'unknown')} has no explicit task or theory target")
    study = [item for item in normalized.get("study_guide", []) if isinstance(item, dict)]
    kit = [item for item in normalized.get("foundation_kit", []) if isinstance(item, dict)]
    if len(core) >= 3 and not study:
        warnings.append("three or more core tasks have no study-guide route")
    if len(core) >= 3 and not kit:
        warnings.append("three or more core tasks have no foundation-kit route")
    metrics = report.get("metrics", {}) if isinstance(report, dict) else {}
    if metrics.get("support_path_coverage", 0) < len(core):
        errors.append("not every core task has an effective support path")
    if metrics.get("task_minutes", 0) <= 0:
        errors.append("practice tasks have no usable time budget")
    if isinstance(normalized.get("duration_minutes"), int) and metrics.get("task_minutes", 0) > normalized["duration_minutes"] * 2:
        warnings.append("task estimates exceed twice the classroom duration; check optional/challenge pacing")
    status = "FAIL" if errors else ("DEGRADED" if warnings else "PASS")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "tasks": len(tasks),
            "core_tasks": len(core),
            "study_guide_sections": len(study),
            "foundation_topics": len(kit),
            "source_slide_refs": len({ref for task in tasks for ref in task.get("source_slide_ids", []) if isinstance(ref, str)}),
            "learning_unit_bridges": len({ref for task in tasks for ref in task.get("learning_unit_ids", []) if isinstance(ref, str)}),
            "canonical_fact_bridges": len({ref for task in tasks for ref in task.get("canonical_fact_ids", []) if isinstance(ref, str)}),
        },
        "migration": migration,
    }
