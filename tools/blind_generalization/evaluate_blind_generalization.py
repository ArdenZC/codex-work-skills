"""Create objective/pedagogical/manual reports for a frozen blind first pass.

The evaluator reads Agent outputs and QA evidence; it never edits a contract and
never assigns the 40-point human review. Its structural comparison is a warning
signal for template overfit, not a requirement that courses look identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


COURSES = ("python-web", "spreadsheet", "networking")


def _read_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value or "").casefold())


def _output_freeze_status(course_root: Path) -> dict[str, Any]:
    freeze_path = course_root / "output-freeze.json"
    manifest = _read_json(freeze_path)
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return {"status": "fail", "errors": ["missing or invalid output-freeze.json"]}
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            continue
        relative = str(item.get("relative_path", ""))
        target = course_root / relative
        if not target.is_file():
            errors.append(f"frozen output file is missing: {relative}")
            continue
        if _sha256(target) != str(item.get("sha256", "")).lower():
            errors.append(f"frozen output hash mismatch: {relative}")
    listed = {str(item.get("relative_path")) for item in manifest.get("files", []) if isinstance(item, dict)}
    actual = {path.relative_to(course_root).as_posix() for path in course_root.rglob("*") if path.is_file() and path.name != "output-freeze.json"}
    if listed != actual:
        errors.append(f"output freeze file set differs: missing={sorted(listed - actual)} extra={sorted(actual - listed)}")
    return {"status": "pass" if not errors else "fail", "errors": errors, "frozen_at": manifest.get("frozen_at"), "file_count": len(listed)}


def _parse_command_output(commands: dict[str, Any], name: str) -> dict[str, Any]:
    item = commands.get(name, {}) if isinstance(commands, dict) else {}
    if not isinstance(item, dict):
        return {"status": "not-run"}
    parsed = dict(item)
    stdout = str(parsed.get("stdout", ""))
    try:
        parsed["json"] = json.loads(stdout) if stdout.strip() else None
    except json.JSONDecodeError:
        parsed["json"] = None
    return parsed


def _context_consistent(courseware: dict[str, Any], practice: dict[str, Any]) -> bool:
    return isinstance(courseware.get("course_context"), dict) and courseware.get("course_context") == practice.get("course_context")


def _pick_contract(primary: Path, fallback: Path) -> tuple[dict[str, Any], str]:
    value = _read_json(primary)
    if isinstance(value, dict) and value:
        return value, str(primary)
    value = _read_json(fallback, {})
    return (value if isinstance(value, dict) else {}), str(fallback) if isinstance(value, dict) and value else str(primary)


def _course_record(root: Path, course: str) -> dict[str, Any]:
    course_root = root / "first-pass" / course
    courseware, courseware_source = _pick_contract(course_root / "courseware" / "courseware-content.json", root / "agent-inputs" / course / "courseware-content.json")
    practice, practice_source = _pick_contract(course_root / "practice" / "practice-content.json", root / "agent-inputs" / course / "practice-content.json")
    run_report = _read_json(course_root / "run-report.json", {})
    commands = _read_json(course_root / "evidence" / "commands.json", {})
    courseware_qa = _read_json(course_root / "courseware" / "qa-report.json", {})
    practice_qa = _read_json(course_root / "practice" / "qa-report.json", {})
    tasks = [item for item in practice.get("tasks", []) if isinstance(item, dict)] if isinstance(practice, dict) else []
    centers = [item for item in practice.get("learning_center", []) if isinstance(item, dict)] if isinstance(practice, dict) else []
    core = [item for item in tasks if item.get("level") == "core"]
    starter_assets = [item for item in practice.get("starter_assets", []) if isinstance(item, dict)] if isinstance(practice, dict) else []
    task_steps = [len(item.get("steps", [])) for item in tasks]
    levels = Counter(str(item.get("level")) for item in tasks)
    interaction_types = [str(item.get("interaction", {}).get("type")) for item in centers if isinstance(item.get("interaction"), dict)]
    prepared = int(courseware.get("prepared_minutes", 0) or 0) if isinstance(courseware, dict) else 0
    planned = sum(int(item.get("suggested_minutes", 0) or 0) for item in courseware.get("slides", []) if isinstance(item, dict)) if isinstance(courseware, dict) else 0
    practice_minutes = sum(int(item.get("estimated_minutes", 0) or 0) for item in tasks)
    courseware_ped = courseware_qa.get("pedagogical", {}) if isinstance(courseware_qa, dict) else {}
    repetition = courseware_ped.get("metrics", {}).get("speaker_script_repetition", {}) if isinstance(courseware_ped, dict) else {}
    safe_manifest = _read_json(course_root / "practice" / "student-package" / "student-manifest.json", {})
    return {
        "id": course,
        "root": str(course_root),
        "courseware": courseware,
        "practice": practice,
        "contract_sources": {"courseware": courseware_source, "practice": practice_source},
        "run_report": run_report,
        "courseware_qa": courseware_qa,
        "practice_qa": practice_qa,
        "output_freeze": _output_freeze_status(course_root),
        "commands": {
            "courseware_render": _parse_command_output(commands, "courseware_render"),
            "courseware_validate": _parse_command_output(commands, "courseware_validate"),
            "practice_render": _parse_command_output(commands, "practice_render"),
            "practice_validate": _parse_command_output(commands, "practice_validate"),
            "browser_smoke": _parse_command_output(commands, "browser_smoke"),
        },
        "metrics": {
            "slides": len(courseware.get("slides", [])) if isinstance(courseware, dict) else 0,
            "prepared_minutes": prepared,
            "planned_minutes": planned,
            "tasks": len(tasks),
            "levels": dict(levels),
            "core_tasks": len(core),
            "task_kinds": sorted({str(item.get("task_kind")) for item in tasks}),
            "scaffold_levels": sorted({str(item.get("scaffold_level")) for item in tasks}),
            "interactions": len(centers),
            "interaction_types": interaction_types,
            "guide_sections": len(practice.get("study_guide", [])) if isinstance(practice, dict) else 0,
            "foundation_topics": len(practice.get("foundation_kit", [])) if isinstance(practice, dict) else 0,
            "teacher_references": len(practice.get("teacher_reference", {}).get("task_references", [])) if isinstance(practice, dict) and isinstance(practice.get("teacher_reference"), dict) else 0,
            "practice_estimated_minutes": practice_minutes,
            "task_step_counts": task_steps,
            "starter_assets": len(starter_assets),
            "source_slide_refs": sorted({str(ref) for item in tasks for ref in item.get("source_slide_ids", [])}),
            "speaker_script_repetition": repetition,
            "course_context_consistent": _context_consistent(courseware, practice) if isinstance(courseware, dict) and isinstance(practice, dict) else False,
            "student_manifest": safe_manifest,
        },
    }


def _objective_score(record: dict[str, Any]) -> dict[str, Any]:
    cw = record["courseware"]
    practice = record["practice"]
    metrics = record["metrics"]
    commands = record["commands"]
    qa_pass = record["courseware_qa"].get("status") == "pass" and record["practice_qa"].get("status") == "pass"
    time_ok = metrics["prepared_minutes"] > 0 and metrics["prepared_minutes"] == metrics["planned_minutes"]
    source_ids = {str(item.get("id")) for item in cw.get("slides", []) if isinstance(item, dict)}
    refs_ok = bool(source_ids) and set(metrics["source_slide_refs"]).issubset(source_ids)
    safe_manifest = metrics["student_manifest"]
    safe_content = _read_json(Path(record["root"]) / "practice" / "student-package" / "practice-content.json", {})
    isolation_ok = (
        isinstance(safe_manifest, dict)
        and safe_manifest.get("teacher_answers_included") is False
        and safe_manifest.get("replacement_metadata_included") is False
        and safe_manifest.get("canonical_answers_included") is False
        and not any(key in safe_content for key in ("teacher_guide", "teacher_reference", "canonical_facts"))
    )
    starter_required = metrics["starter_assets"] > 0
    starter_dir = Path(record["root"]) / "practice" / "student" / "starter"
    starter_ok = record["practice_qa"].get("outputs", {}).get("status") == "pass" and (not starter_required or any(starter_dir.rglob("*")))
    browser_ok = commands["browser_smoke"].get("status") == "pass" and record["practice_qa"].get("outputs", {}).get("status") == "pass"
    cross_material_ok = metrics["course_context_consistent"] and refs_ok and qa_pass
    checks = [
        {"name": "time_consistency", "points": 5 if time_ok else 0, "pass": time_ok, "evidence": {"prepared_minutes": metrics["prepared_minutes"], "planned_minutes": metrics["planned_minutes"]}},
        {"name": "theory_boundary", "points": 5 if refs_ok and record["practice_qa"].get("contract", {}).get("status") == "pass" else 0, "pass": refs_ok and record["practice_qa"].get("contract", {}).get("status") == "pass", "evidence": {"courseware_slide_count": len(source_ids), "practice_source_refs": metrics["source_slide_refs"]}},
        {"name": "answer_leakage_and_distribution_isolation", "points": 5 if isolation_ok else 0, "pass": isolation_ok, "evidence": safe_manifest},
        {"name": "starter_real_and_usable", "points": 5 if starter_ok else 0, "pass": starter_ok, "evidence": {"starter_assets": metrics["starter_assets"]}},
        {"name": "browser_links_overflow", "points": 5 if browser_ok else 0, "pass": browser_ok, "evidence": {"browser_status": commands["browser_smoke"].get("status"), "practice_output_status": record["practice_qa"].get("outputs", {}).get("status")}},
        {"name": "cross_material_fact_consistency", "points": 5 if cross_material_ok else 0, "pass": cross_material_ok, "evidence": {"course_context_consistent": metrics["course_context_consistent"], "references_valid": refs_ok}},
    ]
    p0: list[str] = []
    if commands["courseware_render"].get("status") != "pass" or commands["practice_render"].get("status") != "pass":
        p0.append("renderer generation failed")
    if not qa_pass:
        p0.append("courseware or practice QA failed")
    if not time_ok:
        p0.append("prepared time is inconsistent with page plan")
    if not refs_ok:
        p0.append("practice references a slide outside the generated theory")
    if not isolation_ok:
        p0.append("student package isolation or answer leakage check failed")
    if not starter_ok:
        p0.append("starter output is missing or unusable")
    if metrics["speaker_script_repetition"].get("status") == "FAIL":
        p0.append("speaker script repetition review failed")
    return {"score": sum(item["points"] for item in checks), "max_score": 30, "checks": checks, "p0": p0}


def _pedagogical_score(record: dict[str, Any]) -> dict[str, Any]:
    courseware_contract_pass = record["courseware_qa"].get("status") == "pass"
    practice_contract_pass = record["practice_qa"].get("status") == "pass" and record["practice_qa"].get("contract", {}).get("status") == "pass"
    if not courseware_contract_pass:
        return {
            "scoring_status": "NOT_SCORED",
            "reason": "Courseware Contract/QA failed; Courseware pedagogical is not scored, Practice is not run, and Human review is not scored.",
            "courseware_status": "NOT_SCORED",
            "practice_status": "NOT_RUN",
            "score": None,
            "max_score": 30,
            "checks": [],
        }
    if not practice_contract_pass:
        return {
            "scoring_status": "COURSEWARE_ELIGIBLE_PRACTICE_NOT_SCORED",
            "reason": "Courseware passed and may be reviewed independently; Practice Contract/QA failed, so Practice pedagogical and full-package Human review are not scored.",
            "courseware_status": record["courseware_qa"].get("pedagogical", {}).get("status", "FAIL"),
            "practice_status": "NOT_SCORED",
            "score": None,
            "max_score": 30,
            "checks": [],
        }
    practice = record["practice"]
    metrics = record["metrics"]
    decision = _read_json(Path(record["root"]) / "generation-decision.json", {})
    task_support = all(item.get("starter_asset_ids") or item.get("scaffold") or item.get("help_refs") for item in practice.get("tasks", []) if isinstance(item, dict) and item.get("level") == "core")
    reference_count = metrics["teacher_references"] == metrics["tasks"] and metrics["tasks"] > 0
    interactions_linked = all((item.get("task_ids") or item.get("knowledge_link_ids")) and isinstance(item.get("interaction"), dict) for item in practice.get("learning_center", []) if isinstance(item, dict))
    decision_reason = bool(decision.get("why_these_interactions_fit")) if isinstance(decision, dict) else False
    task_steps = metrics["task_step_counts"]
    duration = int(practice.get("duration_minutes", 0) or 0) if isinstance(practice, dict) else 0
    tasks_natural = bool(task_steps) and all(step_count >= 1 for step_count in task_steps) and metrics["practice_estimated_minutes"] <= max(1, duration) * 2
    scaffold_ok = bool(metrics["core_tasks"]) and task_support and len(metrics["scaffold_levels"]) >= 1
    interaction_ok = bool(metrics["interactions"]) and interactions_linked and decision_reason
    script_status = metrics["speaker_script_repetition"].get("status")
    script_ok = record["courseware_qa"].get("pedagogical", {}).get("status") in {"PASS", "DEGRADED"} and script_status != "FAIL"
    practice_value = reference_count and tasks_natural
    self_help = metrics["guide_sections"] > 0 and all(item.get("help_refs") or item.get("scaffold") or item.get("starter_asset_ids") for item in practice.get("tasks", []) if isinstance(item, dict) and item.get("level") == "core")
    checks = [
        {"name": "natural_course_structure", "points": 5 if tasks_natural else 0, "pass": tasks_natural},
        {"name": "difficulty_and_scaffold", "points": 5 if scaffold_ok else 0, "pass": scaffold_ok},
        {"name": "course_fit_of_interactions", "points": 5 if interaction_ok else 0, "pass": interaction_ok, "requires_manual_confirmation": True},
        {"name": "speaker_script_teachability_signal", "points": 5 if script_ok else 0, "pass": script_ok},
        {"name": "practice_task_value", "points": 5 if practice_value else 0, "pass": practice_value},
        {"name": "self_help_path", "points": 5 if self_help else 0, "pass": self_help},
    ]
    return {
        "scoring_status": "SCORED",
        "reviewer_mode": "deterministic-pedagogical-review-provisional",
        "requires_human_confirmation": True,
        "score": sum(item["points"] for item in checks),
        "max_score": 30,
        "checks": checks,
        "signals": {"task_step_counts": task_steps, "interaction_types": metrics["interaction_types"], "decision_reason_present": decision_reason, "speaker_script_repetition": metrics["speaker_script_repetition"]},
    }


def _pedagogical_label(value: dict[str, Any]) -> str:
    if value.get("scoring_status") == "SCORED" and isinstance(value.get("score"), int):
        return f"{value['score']}/{value.get('max_score', 30)}"
    return str(value.get("scoring_status", "NOT_SCORED"))


def _scored_average(values: dict[str, dict[str, Any]]) -> float | str:
    scores = [item["score"] for item in values.values() if isinstance(item.get("score"), int)]
    if not scores:
        return "NOT_SCORED"
    return round(sum(scores) / len(scores), 1)


def _signature(record: dict[str, Any]) -> dict[str, Any]:
    practice = record["practice"]
    tasks = [item for item in practice.get("tasks", []) if isinstance(item, dict)]
    centers = [item for item in practice.get("learning_center", []) if isinstance(item, dict)]
    teacher = practice.get("teacher_guide", {}) if isinstance(practice.get("teacher_guide"), dict) else {}
    timing = [item.get("minutes") for item in teacher.get("timing", []) if isinstance(item, dict)]
    return {
        "task_count": len(tasks),
        "level_distribution": dict(Counter(str(item.get("level")) for item in tasks)),
        "task_kinds": [str(item.get("task_kind")) for item in tasks],
        "interaction_sequence": [str(item.get("interaction", {}).get("type")) for item in centers if isinstance(item.get("interaction"), dict)],
        "guide_count": len(practice.get("study_guide", [])),
        "kit_count": len(practice.get("foundation_kit", [])),
        "title_shape": [_compact(item.get("title"))[:24] for item in tasks],
        "step_shape": [_compact((item.get("steps") or [""])[0])[:28] for item in tasks],
        "teacher_timing": timing,
    }


def _similarity(left: Any, right: Any) -> float:
    return round(SequenceMatcher(None, json.dumps(left, ensure_ascii=False, sort_keys=True), json.dumps(right, ensure_ascii=False, sort_keys=True)).ratio(), 3)


def _template_diversity(records: list[dict[str, Any]]) -> dict[str, Any]:
    if any(not isinstance(record.get("courseware"), dict) or not record.get("courseware") or not isinstance(record.get("practice"), dict) or not record.get("practice") for record in records):
        return {
            "status": "INCOMPLETE_OUTPUT",
            "warning": False,
            "signatures": {record["id"]: _signature(record) for record in records},
            "pairs": [],
            "interpretation": "至少一门首轮没有完整的 Courseware/Practice 合同；模板化比较不判定，先处理首轮失败证据。",
        }
    signatures = {record["id"]: _signature(record) for record in records}
    pairs: list[dict[str, Any]] = []
    fields = ("task_count", "level_distribution", "task_kinds", "interaction_sequence", "guide_count", "kit_count", "title_shape", "step_shape", "teacher_timing")
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            left_sig, right_sig = signatures[left["id"]], signatures[right["id"]]
            equal_fields = [field for field in fields if left_sig[field] == right_sig[field]]
            similarities = {field: _similarity(left_sig[field], right_sig[field]) for field in fields}
            pairs.append({"left": left["id"], "right": right["id"], "equal_fields": equal_fields, "similarities": similarities})
    exact_overfit = bool(pairs) and all(len(item["equal_fields"]) >= 7 for item in pairs)
    high_similarity = bool(pairs) and all(sum(item["similarities"].values()) / len(fields) >= 0.84 for item in pairs)
    canonical_interactions = {"choice", "state-simulator", "stepper", "diagnose", "multi-question", "classify", "reorder"}
    common_interactions = sorted(set.intersection(*(set(signatures[record["id"]]["interaction_sequence"]) for record in records))) if records else []
    same_task_shape = len({signatures[record["id"]]["task_count"] for record in records}) == 1 and len({json.dumps(signatures[record["id"]]["level_distribution"], sort_keys=True) for record in records}) == 1
    common_interaction_signal = same_task_shape and len(set(common_interactions) & canonical_interactions) >= 5
    warning = exact_overfit or high_similarity or common_interaction_signal
    return {
        "status": "TEMPLATE_OVERFIT_WARNING" if warning else "diverse-enough-signal",
        "warning": warning,
        "signatures": signatures,
        "pairs": pairs,
        "common_interaction_types": common_interactions,
        "canonical_interaction_coverage": sorted(set(common_interactions) & canonical_interactions),
        "common_interaction_signal": common_interaction_signal,
        "interpretation": "警报只提示异常同构，课程不因任务数量或互动数量不同而自动得分；需人工检查设计理由。" if warning else "未发现三门课程在全部结构维度上异常同构。",
    }


def _human_template(evaluation: dict[str, Any]) -> str:
    lines = [
        "# Human Gold Review Template",
        "",
        "Human review is intentionally PENDING / 40 until a real teacher opens the frozen HTML beside the raw source.",
        "",
        "| Dimension | Max | H1 Python Web | H2 Excel / 数据处理 | H3 计算机网络 | Evidence / reviewer note |",
        "|---|---:|---:|---:|---:|---|",
        "| 老师是否愿意直接用 | 10 | PENDING | PENDING | PENDING | |",
        "| 学生是否真正做得出来 | 8 | PENDING | PENDING | PENDING | |",
        "| 理论课是否能讲满且不水 | 8 | PENDING | PENDING | PENDING | |",
        "| 实践是否像真实机房课 | 6 | PENDING | PENDING | PENDING | |",
        "| 视觉与信息密度 | 4 | PENDING | PENDING | PENDING | |",
        "| 教师参考是否足够 | 4 | PENDING | PENDING | PENDING | |",
        "| 合计 | 40 | PENDING | PENDING | PENDING | |",
        "",
        "## Required manual checks",
        "",
        "- 从 raw-source/ 对照本次真实资料，确认没有超出理论范围。",
        "- 真实打开三门 Courseware 的 student/teacher HTML，以及实践课六个主页面。",
        "- 核对讲稿开头页、核心概念页、代码/公式/图页、互动页和收尾页。",
        "- 核对任务是否能在本课程工具环境中完成，尤其是 CSV/Excel、Wireshark/Packet Tracer、Flask/浏览器。",
        "- 记录 P0/P1/P2、真实打开的页面、浏览器和人工观察者；不要把自动分数改写成人工分数。",
        "",
        "## Provisional automated evidence",
        "",
        f"- Objective reports: {evaluation['objective_path']}",
        f"- Pedagogical reports: {evaluation['pedagogical_path']}",
        f"- Template diversity: {evaluation['diversity_path']}",
    ]
    return "\n".join(lines) + "\n"


def _comparison(records: list[dict[str, Any]], objective: dict[str, Any], pedagogical: dict[str, Any], diversity: dict[str, Any]) -> str:
    lines = [
        "# First-pass Generalization Comparison",
        "",
        "Second-pass: not-run. First-pass is frozen before any course-specific repair.",
        "",
        "| Holdout | Slides | Prepared min | Tasks | Levels | Interactions | Guides | Kits | Objective /30 | Pedagogical /30 | P0 |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for record in records:
        metric = record["metrics"]
        lines.append("| {id} | {slides} | {prepared_minutes} | {tasks} | {levels} | {interactions} | {guide_sections} | {foundation_topics} | {objective} | {pedagogical} | {p0} |".format(
            id=record["id"],
            **metric,
            objective=objective[record["id"]]["score"],
            pedagogical=_pedagogical_label(pedagogical[record["id"]]),
            p0="; ".join(objective[record["id"]]["p0"]) or "none",
        ))
    lines.extend([
        "",
        "## Decisions preserved",
        "",
        "Task quantity, level distribution, interaction sequence, guide/kit counts and support paths above are the Agent's first decisions. They are evidence for review, not fixed acceptance targets.",
        "",
        "## Template diversity",
        "",
        f"- Status: {diversity['status']}",
        f"- Warning: {diversity['warning']}",
        "- Compared fields: task count, level distribution, task kinds, interaction sequence, guide/kit count, title/step shape and teacher timing.",
        "",
        "## Score boundary",
        "",
        "Objective and pedagogical numbers are automated/provisional evidence. Human review remains PENDING /40; no total is presented as a final generalization pass.",
    ])
    return "\n".join(lines) + "\n"


def _failure_evidence(record: dict[str, Any]) -> str:
    details: list[str] = []
    for name, item in record.get("commands", {}).items():
        if not isinstance(item, dict) or item.get("status") != "fail":
            continue
        raw = str(item.get("stderr") or item.get("stdout") or item.get("reason") or "").strip()
        compact = " ".join(line.strip() for line in raw.splitlines() if line.strip())
        if len(compact) > 260:
            compact = compact[-260:]
        details.append(f"{name}: {compact or 'failed without text'}")
    return " | ".join(details) or "none"


def _final_report(root: Path, records: list[dict[str, Any]], objective: dict[str, Any], pedagogical: dict[str, Any], diversity: dict[str, Any], baseline: dict[str, Any]) -> str:
    invalid = any(item["p0"] for item in objective.values()) or any(record["output_freeze"].get("status") != "pass" for record in records)
    status = "BLIND_TEST_INVALID" if invalid else "READY_FOR_MANUAL_BLIND_REVIEW"
    lines = [
        "# BLIND-GENERALIZATION-EVALUATION",
        "",
        f"Status: {status}",
        "",
        "本报告只覆盖三门 Blind First-pass；没有运行 Second-pass，也没有 merge。Human Gold Review 完成前不宣布 GENERALIZATION PASS。",
        "",
        "## A. Raw source freeze",
        "",
        f"- Freeze manifest: {root / 'source-freeze' / 'SOURCE-FREEZE.json'}",
        "- Frozen holdouts: H1 Python Web, H2 Excel / 数据处理, H3 计算机网络",
        "- Source files are checked by SHA-256 before each generation; generated outputs carry an output freeze manifest.",
        "",
        "## Baseline",
        "",
        f"- Branch: {baseline.get('branch')}",
        f"- HEAD: {baseline.get('head')}",
        "- Merge: No merge performed.",
        "",
        "## B-C. Agent generation and preserved decisions",
        "",
        "All three records must report generation_method=agent-skill; a builder result is invalid. Each course root contains the Agent-authored decision summary and the original contracts used for rendering.",
        "",
        "| Holdout | Courseware | Practice | Tasks | Levels | Chosen interactions | Scaffold levels | QA |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for record in records:
        metric = record["metrics"]
        qa_status = f"courseware={record['courseware_qa'].get('status')}; practice={record['practice_qa'].get('status')}; browser={record['commands']['browser_smoke'].get('status')}"
        lines.append(f"| {record['id']} | {Path(record['root']) / 'courseware'} | {Path(record['root']) / 'practice'} | {metric['tasks']} | {metric['levels']} | {', '.join(metric['interaction_types']) or 'none'} | {', '.join(metric['scaffold_levels']) or 'none'} | {qa_status} |")
    lines.extend(["", "## D. Template diversity", "", f"- Status: {diversity['status']}", f"- Warning: {diversity['warning']}", "- Differences are reported in evaluation/generalization-comparison.md; identical structure is a review signal, not a mandatory failure.", "", "## E. Objective score", ""])
    for record in records:
        lines.append(f"- {record['id']}: {objective[record['id']]['score']}/30")
    objective_avg = round(sum(item["score"] for item in objective.values()) / max(1, len(objective)), 1)
    lines.append(f"- Average: {objective_avg}/30")
    lines.extend(["", "## F. Pedagogical reviewer score", "", "These are deterministic/provisional pedagogical-review signals and require manual confirmation; they are not Human Gold Review."])
    for record in records:
        lines.append(f"- {record['id']}: {_pedagogical_label(pedagogical[record['id']])}")
    pedagogical_avg = _scored_average(pedagogical)
    pedagogical_average_label = f"{pedagogical_avg}/30" if isinstance(pedagogical_avg, (int, float)) else str(pedagogical_avg)
    lines.append(f"- Average: {pedagogical_average_label}")
    lines.extend(["", "## G. Human Gold Review", "", "PENDING /40. Complete only after a real teacher opens the frozen HTML beside raw-source/.", "", "## H. First-pass final score", "", f"- Automated objective: {objective_avg}/30", f"- Provisional pedagogical: {pedagogical_average_label}", "- Human: PENDING /40", "- Total: PENDING /100", "", "## I. Known findings", ""])
    for record in records:
        p0 = objective[record["id"]]["p0"]
        lines.append(f"- {record['id']}: P0 = {('; '.join(p0)) if p0 else '0'}; runner evidence = {_failure_evidence(record)}; P1/P2 = pending manual review")
    lines.extend(["", "## J. Artifacts", "", f"- First-pass ZIP: {root / 'blind-generalization-first-pass.zip'}", f"- Human review template: {root / 'evaluation' / 'human-review-template.md'}", "- Raw source copy: raw-source/", "- No second-pass directory was generated.", "", "## K. Merge", "", "No merge performed."])
    return "\n".join(lines) + "\n"


def _baseline(repo_root: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=str(repo_root), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return result.stdout.strip()
    return {
        "repo_root": str(repo_root),
        "branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "status_porcelain": git("status", "--porcelain"),
        "upstream_branch": "feature/html-courseware-generator",
        "merge_performed": False,
    }


def _copy_sources(root: Path, source_root: Path) -> None:
    target_root = root / "raw-source"
    target_root.mkdir(parents=True, exist_ok=True)
    for course in COURSES:
        source = source_root / course
        target = target_root / course
        if not source.is_dir():
            raise FileNotFoundError(f"missing frozen source pack: {source}")
        if not target.exists():
            shutil.copytree(source, target)
    freeze_dir = root / "source-freeze"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / "SOURCE-FREEZE.json", freeze_dir / "SOURCE-FREEZE.json")


def _write_zip(root: Path, zip_path: Path) -> None:
    # The first-pass directories remain immutable.  This report bundle may be
    # regenerated when the evaluator itself is corrected (for example, when a
    # missing contract must not be interpreted as an empty common template).
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative_root in ("first-pass", "agent-inputs", "raw-source", "source-freeze", "evaluation"):
            base = root / relative_root
            if not base.exists():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
        for name in ("BLIND-GENERALIZATION-EVALUATION.md", "baseline.json"):
            path = root / name
            if path.is_file():
                archive.write(path, name)


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    root = args.output_root.expanduser().resolve()
    source_root = args.source_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    records = [_course_record(root, course) for course in COURSES]
    baseline = _baseline(args.repo_root.expanduser().resolve())
    _copy_sources(root, source_root)
    evaluation_dir = root / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    objective = {record["id"]: _objective_score(record) for record in records}
    pedagogical = {record["id"]: _pedagogical_score(record) for record in records}
    diversity = _template_diversity(records)
    _write_json(root / "baseline.json", baseline)
    _write_json(evaluation_dir / "first-pass-objective.json", {"pass": "first-pass", "rubric_max": 30, "courses": objective})
    _write_json(evaluation_dir / "first-pass-pedagogical.json", {"pass": "first-pass", "rubric_max": 30, "courses": pedagogical})
    _write_json(evaluation_dir / "template-diversity.json", diversity)
    evaluation = {
        "objective_path": str(evaluation_dir / "first-pass-objective.json"),
        "pedagogical_path": str(evaluation_dir / "first-pass-pedagogical.json"),
        "diversity_path": str(evaluation_dir / "template-diversity.json"),
    }
    (evaluation_dir / "human-review-template.md").write_text(_human_template(evaluation), encoding="utf-8", newline="\n")
    (evaluation_dir / "generalization-comparison.md").write_text(_comparison(records, objective, pedagogical, diversity), encoding="utf-8", newline="\n")
    final = _final_report(root, records, objective, pedagogical, diversity, baseline)
    (root / "BLIND-GENERALIZATION-EVALUATION.md").write_text(final, encoding="utf-8", newline="\n")
    _write_zip(root, root / "blind-generalization-first-pass.zip")
    return {"status": "BLIND_TEST_INVALID" if any(item["p0"] for item in objective.values()) else "READY_FOR_MANUAL_BLIND_REVIEW", "objective": objective, "pedagogical": pedagogical, "template_diversity": diversity, "baseline": baseline, "zip": str(root / "blind-generalization-first-pass.zip"), "report": str(root / "BLIND-GENERALIZATION-EVALUATION.md")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(args)
    except Exception as exc:  # noqa: BLE001 - retain a machine-readable invalid state
        report = {"status": "BLIND_TEST_INVALID", "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "READY_FOR_MANUAL_BLIND_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
