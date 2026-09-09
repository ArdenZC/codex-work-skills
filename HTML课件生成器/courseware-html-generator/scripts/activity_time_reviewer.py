"""Review whether Courseware time claims have executable activity evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TIME_MODES = {"strict", "migration-trust"}
ACTIVITY_TYPES = {
    "question-discussion",
    "guided-practice",
    "demonstration-observation",
    "individual-exercise",
    "pair-check",
    "tool-operation",
    "code-run",
    "model-analysis",
    "case-analysis",
    "mini-quiz",
}
ACTIVITY_ROLES = {
    "teacher-led-demonstration",
    "guided-whole-class-reasoning",
    "short-student-check",
    "student-independent-practice",
}
ACTIVITY_ROLE_LABELS = {
    "teacher-led-demonstration": "教师带领演示",
    "guided-whole-class-reasoning": "全班引导推理",
    "short-student-check": "学生短检查",
    "student-independent-practice": "学生独立练习",
}
ROLE_BY_ACTIVITY_TYPE = {
    "demonstration-observation": "teacher-led-demonstration",
    "question-discussion": "guided-whole-class-reasoning",
    "model-analysis": "guided-whole-class-reasoning",
    "case-analysis": "guided-whole-class-reasoning",
    "mini-quiz": "short-student-check",
    "pair-check": "short-student-check",
    "guided-practice": "guided-whole-class-reasoning",
    "individual-exercise": "student-independent-practice",
    "tool-operation": "student-independent-practice",
    "code-run": "student-independent-practice",
}
ACTION_MARKERS = re.compile(
    r"(?i)(独立|个人|同伴|同桌|小组|讨论|展示|讲评|核对|计算|填写|修改|运行|操作|观察|记录|分类|比较|判断|绘制|验证|复核|选择|追踪|解释|提交)"
)


def _text(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def resolve_activity_role(plan: dict[str, Any]) -> tuple[str | None, str]:
    """Resolve a declared role, or provide a compatibility inference for 1.1."""

    declared = plan.get("activity_role")
    if declared in ACTIVITY_ROLES:
        return declared, "declared"
    inferred = ROLE_BY_ACTIVITY_TYPE.get(plan.get("type"))
    if inferred:
        return inferred, "inferred"
    return None, "missing"


def _minutes(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _plan_quality(
    plan: dict[str, Any],
    minutes: int,
    location: str,
    *,
    strict: bool,
    require_activity_role: bool = False,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    required = ("type", "teacher_prompt", "student_action", "expected_artifact_or_response", "check_method")
    for field in required:
        if not _non_empty(plan.get(field)):
            errors.append(f"{location}.{field} must be a non-empty string")
    activity_type = plan.get("type")
    if activity_type not in ACTIVITY_TYPES:
        errors.append(f"{location}.type must be one of {sorted(ACTIVITY_TYPES)}")
    activity_role, activity_role_status = resolve_activity_role(plan)
    if require_activity_role and activity_role_status == "missing":
        errors.append(f"{location}.activity_role is required for explicit session_delivery_mode planning")
    elif activity_role is None and plan.get("activity_role") is not None:
        errors.append(f"{location}.activity_role must be one of {sorted(ACTIVITY_ROLES)}")
    segments = plan.get("segments")
    segment_total = 0
    if not isinstance(segments, list) or not segments:
        errors.append(f"{location}.segments must contain at least one segment")
    else:
        for index, segment in enumerate(segments):
            segment_location = f"{location}.segments[{index}]"
            if not isinstance(segment, dict) or not _non_empty(segment.get("label")):
                errors.append(f"{segment_location} needs a non-empty label and positive minutes")
                continue
            segment_minutes = segment.get("minutes")
            if not isinstance(segment_minutes, int) or isinstance(segment_minutes, bool) or segment_minutes <= 0:
                errors.append(f"{segment_location}.minutes must be a positive integer")
            else:
                segment_total += segment_minutes
        if isinstance(minutes, int) and abs(segment_total - minutes) > 1:
            errors.append(f"{location}.segments total {segment_total} must approximately equal activity_minutes {minutes}")
    plan_text = " ".join(_text(plan.get(field)) for field in required)
    has_action_evidence = bool(ACTION_MARKERS.search(plan_text))
    if minutes >= 5 and not has_action_evidence:
        message = f"{location} has {minutes} activity minutes but no observable student action evidence"
        (errors if strict else warnings).append(message)
    if minutes >= 6 and isinstance(segments, list) and len(segments) < 2:
        message = f"{location} has {minutes} activity minutes but only one activity segment"
        (warnings if not strict else errors).append(message)
    if minutes >= 4 and _text(plan.get("student_action")).strip() in {"请思考", "思考一下", "请回答问题", "回答问题"}:
        message = f"{location}.student_action is too small to support {minutes} minutes without a process"
        (errors if strict else warnings).append(message)
    return errors, warnings, {
        "type": activity_type,
        "activity_role": activity_role,
        "activity_role_status": activity_role_status,
        "segments": segments if isinstance(segments, list) else [],
        "segment_minutes": segment_total,
        "has_observable_action": has_action_evidence,
    }


def _extension_report(content: dict[str, Any], *, strict: bool) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    declared = _minutes(content.get("extension_minutes"))
    extensions = content.get("extensions", [])
    if not isinstance(extensions, list):
        errors.append("extensions must be a list")
        extensions = []
    total = 0
    items: list[dict[str, Any]] = []
    for index, item in enumerate(extensions):
        location = f"extensions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{location} must be an object")
            continue
        for field in ("id", "title", "content", "activity", "use_when"):
            if not _non_empty(item.get(field)):
                errors.append(f"{location}.{field} must be a non-empty string")
        minutes = item.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
            errors.append(f"{location}.minutes must be a positive integer")
        else:
            total += minutes
        items.append({"id": item.get("id"), "title": item.get("title"), "minutes": minutes, "status": "pass"})
    if declared is not None and total != declared:
        errors.append(f"extension content total {total} must equal extension_minutes {declared}")
    if isinstance(declared, int) and declared > 0 and not extensions:
        errors.append("extension_minutes is positive but no extension content is present")
    if isinstance(declared, int) and declared == 0 and extensions:
        errors.append("extensions are present but extension_minutes is zero")
    return errors, warnings, {"declared_minutes": declared, "content_minutes": total, "items": items}


def review_courseware_time(content: dict[str, Any], *, mode: str = "strict") -> dict[str, Any]:
    """Return a strict evidence-backed time gate or a legacy diagnostic."""

    if mode not in TIME_MODES:
        raise ValueError(f"unsupported time mode: {mode}")
    strict = mode == "strict"
    errors: list[str] = []
    warnings: list[str] = []
    slides = [item for item in _list(content.get("slides")) if isinstance(item, dict)]
    session_delivery_mode = content.get("session_delivery_mode", "theory-led")
    require_activity_role = "session_delivery_mode" in content
    slide_reports: list[dict[str, Any]] = []
    core_slide_total = 0
    extension_slide_total = 0
    lecture_total = 0
    activity_total = 0
    for index, slide in enumerate(slides):
        location = f"slides[{index}]"
        lecture = _minutes(slide.get("lecture_minutes"))
        activity = _minutes(slide.get("activity_minutes"))
        suggested = _minutes(slide.get("suggested_minutes"))
        track = slide.get("delivery_track", "core")
        lecture_total += lecture or 0
        activity_total += activity or 0
        report: dict[str, Any] = {
            "index": index,
            "id": slide.get("id"),
            "delivery_track": track,
            "lecture_minutes": lecture,
            "activity_minutes": activity,
            "suggested_minutes": suggested,
            "activity_type": None,
            "activity_segments": [],
            "activity_evidence_status": "not-required",
        }
        if track == "extension":
            extension_slide_total += suggested or 0
        else:
            core_slide_total += suggested or 0
        if isinstance(activity, int) and activity > 0:
            plan = slide.get("activity_plan")
            if not isinstance(plan, dict):
                message = f"{location}.activity_minutes={activity} requires activity_plan"
                (errors if strict else warnings).append(message)
                report["activity_evidence_status"] = "fail" if strict else "degraded"
            else:
                plan_errors, plan_warnings, plan_metrics = _plan_quality(
                    plan,
                    activity,
                    f"{location}.activity_plan",
                    strict=strict,
                    require_activity_role=require_activity_role,
                )
                errors.extend(plan_errors)
                warnings.extend(plan_warnings)
                report.update({"activity_type": plan_metrics["type"], "activity_role": plan_metrics["activity_role"], "activity_segments": plan_metrics["segments"], "activity_evidence_status": "pass" if not plan_errors else "fail", "activity_plan_metrics": plan_metrics})
        elif slide.get("activity_plan") is not None:
            warnings.append(f"{location}.activity_plan is present while activity_minutes is zero")
            report["activity_evidence_status"] = "unused"
        slide_reports.append(report)

    session = _minutes(content.get("session_minutes"))
    prepared = _minutes(content.get("prepared_minutes"))
    core = _minutes(content.get("core_minutes"))
    extension = _minutes(content.get("extension_minutes"))
    tolerance = max(1, round((prepared or session or 0) * 0.10))
    if isinstance(session, int) and isinstance(core, int) and abs(core - session) > tolerance:
        errors.append(f"core path {core} is not close to session_minutes {session} within ±{tolerance}")
    if isinstance(core, int) and abs(core_slide_total - core) > tolerance:
        errors.append(f"core slide time {core_slide_total} does not support core_minutes {core} within ±{tolerance}")
    if isinstance(prepared, int) and isinstance(core, int) and isinstance(extension, int) and prepared != core + extension:
        errors.append("prepared_minutes must equal core_minutes + extension_minutes")
    extension_errors, extension_warnings, extension_report = _extension_report(content, strict=strict)
    errors.extend(extension_errors)
    warnings.extend(extension_warnings)
    prepared_evidence_total = core_slide_total + extension_report["content_minutes"]
    if isinstance(prepared, int) and abs(prepared_evidence_total - prepared) > tolerance:
        errors.append(f"evidence-backed prepared time {prepared_evidence_total} does not support prepared_minutes {prepared} within ±{tolerance}")
    if extension_slide_total and extension_report["content_minutes"] and abs(extension_slide_total - extension_report["content_minutes"]) > tolerance:
        warnings.append("extension slide time and extension reserve item time differ; confirm they are not double-counted")
    return {
        "status": "FAIL" if errors else ("DEGRADED" if warnings else "PASS"),
        "mode": mode,
        "session_delivery_mode": session_delivery_mode,
        "errors": errors,
        "warnings": warnings,
        "slides": slide_reports,
        "core": {
            "declared_minutes": core,
            "slide_minutes": core_slide_total,
            "lecture_minutes": lecture_total,
            "activity_minutes": activity_total,
        },
        "extension": extension_report,
        "prepared": {
            "declared_minutes": prepared,
            "evidence_minutes": prepared_evidence_total,
            "session_minutes": session,
            "core_minutes": core,
            "extension_minutes": extension,
            "tolerance": tolerance,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-json", required=True, type=Path)
    parser.add_argument("--mode", choices=sorted(TIME_MODES), default="strict")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    try:
        content = json.loads(args.content_json.expanduser().resolve().read_text(encoding="utf-8"))
        report = review_courseware_time(content, mode=args.mode)
    except Exception as exc:  # noqa: BLE001 - CLI keeps review evidence machine-readable
        report = {"status": "FAIL", "mode": args.mode, "errors": [str(exc)], "warnings": []}
    if args.output_json:
        target = args.output_json.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
