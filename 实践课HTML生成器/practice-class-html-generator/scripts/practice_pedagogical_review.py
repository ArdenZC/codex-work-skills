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
from practice_time_reviewer import review_practice_time


def review_content(
    content: dict[str, Any],
    contract: dict[str, Any] | None = None,
    *,
    time_mode: str = "migration-trust",
) -> dict[str, Any]:
    normalized, migration = normalize_content(content)
    report = contract or validate_content(normalized)
    errors: list[str] = list(report.get("errors", [])) if report.get("status") != "pass" else []
    warnings: list[str] = []
    time_evidence = review_practice_time(normalized, mode=time_mode)
    if time_evidence["status"] == "FAIL":
        errors.extend(time_evidence.get("errors", []))
    else:
        warnings.extend(time_evidence.get("warnings", []))
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
    if not study:
        warnings.append("no study-guide route is provided; verify that students have a self-help path")
    if not kit:
        warnings.append("no foundation-kit route is provided; verify that no just-in-time prerequisite is needed")
    metrics = report.get("metrics", {}) if isinstance(report, dict) else {}
    if metrics.get("support_path_coverage", 0) < len(core):
        errors.append("not every core task has an effective support path")
    if metrics.get("task_minutes", 0) <= 0:
        errors.append("practice tasks have no usable time budget")
    if isinstance(normalized.get("duration_minutes"), int) and metrics.get("task_minutes", 0) > normalized["duration_minutes"] * 2:
        warnings.append("task estimates exceed twice the classroom duration; check optional/challenge pacing")
    task_steps = [len(task.get("steps", [])) if isinstance(task.get("steps"), list) else 0 for task in tasks]
    task_kinds = sorted({str(task.get("task_kind")) for task in tasks if task.get("task_kind")})
    structural_ok = bool(tasks) and all(count >= 1 for count in task_steps)
    scaffold_quality = bool(core) and all(task.get("scaffold") or task.get("starter_asset_ids") or task.get("help_refs") for task in core)
    modality_quality = bool(task_kinds) and any(task.get("capabilities") for task in tasks)
    interaction_quality = bool(centers) and all(center.get("task_ids") or center.get("knowledge_link_ids") for center in centers)
    reference_count = len(_reference_ids(normalized))
    value_quality = bool(tasks) and reference_count == len(tasks)
    self_help_quality = bool(study) and metrics.get("support_path_coverage", 0) >= len(core)
    checks = [
        {"name": "course_structure", "score": 5 if structural_ok else 0, "evidence": {"task_count": len(tasks), "step_counts": task_steps}, "finding": "任务步骤和课堂颗粒度可执行" if structural_ok else "至少一个任务缺少可执行步骤"},
        {"name": "difficulty_scaffold", "score": 5 if scaffold_quality else 0, "evidence": {"core_tasks": len(core), "task_kinds": task_kinds}, "finding": "核心任务有明确脚手架" if scaffold_quality else "核心任务脚手架覆盖不足"},
        {"name": "natural_modality", "score": 5 if modality_quality else 0, "evidence": {"task_kinds": task_kinds}, "finding": "任务能力与课程形式有可审计表达" if modality_quality else "任务能力/形式选择理由不足"},
        {"name": "interaction_fit", "score": 5 if interaction_quality else 0, "evidence": {"interaction_count": len(centers)}, "finding": "互动都回到任务或知识目标" if interaction_quality else "互动缺少明确目标回链"},
        {"name": "practice_value", "score": 5 if value_quality else 0, "evidence": {"tasks": len(tasks), "teacher_references": reference_count}, "finding": "每个任务都有可核对教师参考" if value_quality else "任务与教师参考成果未完整对齐"},
        {"name": "support_path", "score": 5 if self_help_quality else 0, "evidence": {"guide_sections": len(study), "support_path_coverage": metrics.get("support_path_coverage", 0)}, "finding": "核心任务有学生自助路径" if self_help_quality else "学生自助资料路径不足"},
    ]
    context = normalized.get('course_context', {})
    if context.get('delivery_environment') == 'computer-lab' and not normalized.get('paper_work_authorization'):
        import json
        text = json.dumps(normalized, ensure_ascii=False)
        if any(term in text for term in ('在纸上写', '手写提交')):
            warnings.append('COMPUTER_LAB_MODALITY_WARNING: 默认在工作表、网页工作区或文本文件记录；纸笔需来源/用户依据')
    if warnings or errors:
        checks[0]['score'] = min(checks[0]['score'], 4 if not errors else 0)
    for check in checks:
        check["pass"] = check["score"] == 5
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
            "task_kinds": task_kinds,
            "task_step_counts": task_steps,
            "checks": checks,
            "score": sum(item["score"] for item in checks),
            "score_max": 30,
            "time_evidence": time_evidence,
        },
        "migration": migration,
    }


def _reference_ids(content: dict[str, Any]) -> set[str]:
    references = content.get("teacher_reference", {}).get("task_references", []) if isinstance(content.get("teacher_reference"), dict) else []
    return {str(item.get("task_id")) for item in references if isinstance(item, dict) and item.get("task_id")}
