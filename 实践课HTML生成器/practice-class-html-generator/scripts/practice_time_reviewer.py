"""Lightweight evidence review for Practice task time estimates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TIME_MODES = {"strict", "migration-trust"}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _review_breakdown(task: dict[str, Any], location: str) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    estimated = task.get("estimated_minutes")
    breakdown = task.get("time_breakdown")
    result: dict[str, Any] = {
        "task_id": task.get("id"),
        "level": task.get("level"),
        "estimated_minutes": estimated,
        "breakdown_minutes": 0,
        "status": "not-required",
        "steps": [],
    }
    if not _positive_int(estimated):
        return errors, warnings, result
    if breakdown is None:
        result["status"] = "missing"
        # Core tasks get a review warning, not a failure: the purpose is to
        # catch implausible inflation while keeping unusual workshop formats.
        if task.get("level") == "core" and (len(_list(task.get("steps"))) <= 2 or estimated >= 10):
            warnings.append(f"{location}.time_breakdown is missing for a core task estimated at {estimated} minutes")
            result["status"] = "degraded"
        return errors, warnings, result
    if not isinstance(breakdown, list) or not breakdown:
        errors.append(f"{location}.time_breakdown must be a non-empty list when present")
        result["status"] = "fail"
        return errors, warnings, result
    total = 0
    for index, step in enumerate(breakdown):
        step_location = f"{location}.time_breakdown[{index}]"
        if not isinstance(step, dict) or not _text(step.get("step")).strip():
            errors.append(f"{step_location} needs a non-empty step and positive minutes")
            continue
        minutes = step.get("minutes")
        if not _positive_int(minutes):
            errors.append(f"{step_location}.minutes must be a positive integer")
            continue
        total += minutes
        result["steps"].append({"step": step["step"], "minutes": minutes})
    result["breakdown_minutes"] = total
    if abs(total - estimated) > 1:
        errors.append(f"{location}.time_breakdown total {total} must approximately equal estimated_minutes {estimated}")
    result["status"] = "fail" if errors else "pass"
    return errors, warnings, result


def review_practice_time(content: dict[str, Any], *, mode: str = "strict") -> dict[str, Any]:
    """Review core task time evidence without imposing a fixed task shape."""

    if mode not in TIME_MODES:
        raise ValueError(f"unsupported time mode: {mode}")
    errors: list[str] = []
    warnings: list[str] = []
    tasks = _list(content.get("tasks"))
    reports: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            continue
        task_errors, task_warnings, report = _review_breakdown(task, f"tasks[{index}]")
        errors.extend(task_errors)
        warnings.extend(task_warnings)
        reports.append(report)
    return {
        "status": "FAIL" if errors else ("DEGRADED" if warnings else "PASS"),
        "mode": mode,
        "errors": errors,
        "warnings": warnings,
        "tasks": reports,
        "core_tasks": sum(1 for item in reports if item.get("level") == "core"),
        "breakdown_tasks": sum(1 for item in reports if item.get("status") == "pass"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-json", required=True, type=Path)
    parser.add_argument("--mode", choices=sorted(TIME_MODES), default="strict")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    try:
        content = json.loads(args.practice_json.expanduser().resolve().read_text(encoding="utf-8"))
        report = review_practice_time(content, mode=args.mode)
    except Exception as exc:  # noqa: BLE001 - keep CLI evidence machine-readable
        report = {"status": "FAIL", "mode": args.mode, "errors": [str(exc)], "warnings": [], "tasks": []}
    if args.output_json:
        target = args.output_json.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # DEGRADED is a deliberate warning state, not a failed generation.
    return 0 if report["status"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
