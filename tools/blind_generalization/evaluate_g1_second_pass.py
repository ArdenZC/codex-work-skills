"""Evaluate the frozen G1 blind second pass without touching first-pass output.

The evaluator consumes runner QA, the two contracts, the public generation
decision, and the frozen source manifest.  It produces six-by-five objective
and pedagogical evidence, a non-scoring template-diversity signal, a human
review template, a first/second-pass comparison, and the required second-pass
ZIP.  It never authors or repairs a contract and never assigns Human /40.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


COURSES = ("python-web", "spreadsheet", "networking")


def _read(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(value or "").casefold())


def _parse_commands(base: Path) -> dict[str, Any]:
    raw = _read(base / "evidence" / "commands.json", {})
    result: dict[str, Any] = {}
    for name, item in raw.items() if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            result[name] = {"status": "not-run"}
            continue
        parsed = dict(item)
        stdout = str(parsed.get("stdout", ""))
        try:
            parsed["json"] = json.loads(stdout) if stdout.strip() else None
        except json.JSONDecodeError:
            parsed["json"] = None
        result[name] = parsed
    return result


def _pick(primary: Path, fallback: Path) -> tuple[dict[str, Any], str]:
    value = _read(primary)
    if isinstance(value, dict) and value:
        return value, str(primary)
    value = _read(fallback, {})
    return (value if isinstance(value, dict) else {}), str(fallback) if isinstance(value, dict) and value else str(primary)


def _freeze_status(base: Path) -> dict[str, Any]:
    manifest = _read(base / "output-freeze.json")
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return {"status": "fail", "errors": ["missing output-freeze.json"]}
    listed = {str(item.get("relative_path")) for item in manifest.get("files", []) if isinstance(item, dict)}
    for relative in sorted(listed):
        path = base / relative
        if not path.is_file():
            errors.append(f"frozen file missing: {relative}")
        else:
            expected = next((str(item.get("sha256", "")).lower() for item in manifest.get("files", []) if isinstance(item, dict) and item.get("relative_path") == relative), "")
            if _sha256(path) != expected:
                errors.append(f"frozen file hash mismatch: {relative}")
    actual = {path.relative_to(base).as_posix() for path in base.rglob("*") if path.is_file() and path.name != "output-freeze.json"}
    if actual != listed:
        errors.append(f"frozen file set differs: missing={sorted(listed - actual)} extra={sorted(actual - listed)}")
    return {"status": "pass" if not errors else "fail", "errors": errors, "file_count": len(listed), "frozen_at": manifest.get("frozen_at")}


def _record(root: Path, pass_name: str, course: str) -> dict[str, Any]:
    base = root / pass_name / course
    fallback = root / "agent-inputs" / course if pass_name == "first-pass" else base / "agent-inputs"
    courseware, cw_source = _pick(base / "courseware" / "courseware-content.json", fallback / "courseware-content.json")
    practice, practice_source = _pick(base / "practice" / "practice-content.json", fallback / "practice-content.json")
    if pass_name == "first-pass" and not practice:
        practice, practice_source = _pick(root / "agent-inputs" / course / "practice-content.json", fallback / "practice-content.json")
    run_report = _read(base / "run-report.json", {})
    commands = _parse_commands(base)
    courseware_qa = _read(base / "courseware" / "qa-report.json", {})
    practice_qa = _read(base / "practice" / "qa-report.json", {})
    tasks = [item for item in practice.get("tasks", []) if isinstance(item, dict)]
    core = [item for item in tasks if item.get("level") == "core"]
    centers = [item for item in practice.get("learning_center", []) if isinstance(item, dict)]
    slides = [item for item in courseware.get("slides", []) if isinstance(item, dict)]
    prepared = int(courseware.get("prepared_minutes", 0) or 0)
    planned = sum(int(item.get("suggested_minutes", 0) or 0) for item in slides)
    task_minutes = sum(int(item.get("estimated_minutes", 0) or 0) for item in tasks)
    decision = _read(base / "generation-decision.json", {})
    if not decision and pass_name == "first-pass":
        decision = _read(root / "agent-inputs" / course / "generation-decision.json", {})
    return {
        "id": course,
        "pass": pass_name,
        "root": str(base),
        "base": base,
        "courseware": courseware,
        "practice": practice,
        "decision": decision if isinstance(decision, dict) else {},
        "contract_sources": {"courseware": cw_source, "practice": practice_source},
        "run_report": run_report if isinstance(run_report, dict) else {},
        "commands": commands,
        "courseware_qa": courseware_qa if isinstance(courseware_qa, dict) else {},
        "practice_qa": practice_qa if isinstance(practice_qa, dict) else {},
        "output_freeze": _freeze_status(base),
        "tasks": tasks,
        "core": core,
        "centers": centers,
        "slides": slides,
        "metrics": {
            "slides": len(slides),
            "learning_units": len([item for item in courseware.get("learning_units", []) if isinstance(item, dict)]),
            "prepared_minutes": prepared,
            "planned_minutes": planned,
            "tasks": len(tasks),
            "core_tasks": len(core),
            "optional_tasks": sum(1 for item in tasks if item.get("level") == "optional"),
            "challenge_tasks": sum(1 for item in tasks if item.get("level") == "challenge"),
            "task_minutes": task_minutes,
            "interaction_types": [str(item.get("interaction", {}).get("type")) for item in centers if isinstance(item.get("interaction"), dict)],
            "guide_sections": len(practice.get("study_guide", [])) if isinstance(practice, dict) else 0,
            "foundation_topics": len(practice.get("foundation_kit", [])) if isinstance(practice, dict) else 0,
            "teacher_references": len(practice.get("teacher_reference", {}).get("task_references", [])) if isinstance(practice.get("teacher_reference"), dict) else 0,
            "task_step_counts": [len(item.get("steps", [])) if isinstance(item.get("steps"), list) else 0 for item in tasks],
            "starter_assets": len(practice.get("starter_assets", [])) if isinstance(practice, dict) else 0,
        },
    }


def _command(record: dict[str, Any], name: str) -> dict[str, Any]:
    item = record.get("commands", {}).get(name, {})
    return item if isinstance(item, dict) else {}


def _context_ok(record: dict[str, Any]) -> bool:
    cw, practice = record["courseware"], record["practice"]
    return isinstance(cw.get("course_context"), dict) and cw.get("course_context") == practice.get("course_context")


def _theory_ok(record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    cw, practice = record["courseware"], record["practice"]
    slide_ids = {str(item.get("id")) for item in record["slides"] if item.get("id")}
    refs = sorted({str(ref) for task in record["tasks"] for ref in task.get("source_slide_ids", [])})
    fact_ids = {str(item.get("id")) for item in cw.get("canonical_facts", []) if isinstance(item, dict) and item.get("id")}
    core_fact_refs = sorted({str(ref) for task in record["core"] for ref in task.get("canonical_fact_ids", [])})
    ok = bool(slide_ids) and bool(practice) and set(refs).issubset(slide_ids) and set(core_fact_refs).issubset(fact_ids)
    return ok, {"courseware_slide_ids": len(slide_ids), "practice_source_slide_refs": refs, "core_canonical_fact_refs": core_fact_refs, "canonical_fact_ids": sorted(fact_ids)}


def _isolation_ok(record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    base = Path(record["root"])
    manifest = _read(base / "practice" / "student-package" / "student-manifest.json", {})
    safe = _read(base / "practice" / "student-package" / "practice-content.json", {})
    flags = all(manifest.get(key) is False for key in ("teacher_answers_included", "replacement_metadata_included", "canonical_answers_included")) if isinstance(manifest, dict) else False
    safe_keys = sorted(key for key in ("teacher_guide", "teacher_reference", "canonical_facts") if key in safe) if isinstance(safe, dict) else ["invalid-safe-content"]
    ok = flags and not safe_keys
    return ok, {"manifest": manifest, "forbidden_safe_content_keys": safe_keys}


def _starter_ok(record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    base = Path(record["root"])
    assets = [item for item in record["practice"].get("starter_assets", []) if isinstance(item, dict)]
    missing = [str(item.get("path")) for item in assets if not (base / "practice" / "student" / "starter" / str(item.get("path", ""))).is_file()]
    ok = not missing and record["practice_qa"].get("outputs", {}).get("status") == "pass"
    return ok, {"declared_assets": len(assets), "missing_student_files": missing, "output_qa": record["practice_qa"].get("outputs", {}).get("status")}


def _objective(record: dict[str, Any], source_status: dict[str, Any]) -> dict[str, Any]:
    metrics = record["metrics"]
    cw_qa, practice_qa = record["courseware_qa"], record["practice_qa"]
    time_ok = metrics["prepared_minutes"] > 0 and metrics["prepared_minutes"] == metrics["planned_minutes"]
    theory_ok, theory_evidence = _theory_ok(record)
    isolation_ok, isolation_evidence = _isolation_ok(record)
    starter_ok, starter_evidence = _starter_ok(record)
    browser_ok = _command(record, "browser_smoke").get("status") == "pass" and practice_qa.get("outputs", {}).get("status") == "pass"
    canonical_ok = _context_ok(record) and theory_ok and source_status.get(record["id"], {}).get("status") == "pass"
    checks = [
        {"name": "time_consistency", "score": 5 if time_ok else 0, "pass": time_ok, "evidence": {"prepared_minutes": metrics["prepared_minutes"], "planned_minutes": metrics["planned_minutes"]}, "finding": "页级计划与准备容量一致" if time_ok else "页级计划未与准备容量一致"},
        {"name": "theory_alignment", "score": 5 if theory_ok else 0, "pass": theory_ok, "evidence": theory_evidence, "finding": "任务页引用均回到本轮理论" if theory_ok else "任务理论回链存在缺口"},
        {"name": "student_answer_isolation", "score": 5 if isolation_ok else 0, "pass": isolation_ok, "evidence": isolation_evidence, "finding": "学生包未包含教师答案元数据" if isolation_ok else "学生包隔离检查失败"},
        {"name": "starter_reference_integrity", "score": 5 if starter_ok else 0, "pass": starter_ok, "evidence": starter_evidence, "finding": "starter 声明与学生可取得文件一致" if starter_ok else "starter 文件或输出 QA 不完整"},
        {"name": "browser_layout_links", "score": 5 if browser_ok else 0, "pass": browser_ok, "evidence": {"browser_status": _command(record, "browser_smoke").get("status"), "practice_output_status": practice_qa.get("outputs", {}).get("status")}, "finding": "浏览器、pane、链接和布局 smoke 通过" if browser_ok else "浏览器或布局链接 smoke 未通过"},
        {"name": "canonical_context_consistency", "score": 5 if canonical_ok else 0, "pass": canonical_ok, "evidence": {"context_equal": _context_ok(record), "frozen_source_status": source_status.get(record["id"], {}).get("status")}, "finding": "课程上下文、canonical facts 与冻结来源一致" if canonical_ok else "上下文、事实或冻结来源存在不一致"},
    ]
    p0: list[str] = []
    if record["run_report"].get("status") != "pass":
        p0.append("runner generation did not pass")
    if cw_qa.get("status") != "pass" or practice_qa.get("status") != "pass":
        p0.append("Courseware or Practice QA failed")
    for check in checks:
        if not check["pass"] and check["name"] in {"time_consistency", "theory_alignment", "student_answer_isolation", "starter_reference_integrity", "browser_layout_links", "canonical_context_consistency"}:
            p0.append(check["name"] + " failed")
    if source_status.get(record["id"], {}).get("status") != "pass":
        p0.append("frozen source hash verification failed")
    if record["output_freeze"].get("status") != "pass":
        p0.append("second-pass output freeze verification failed")
    return {"score": sum(item["score"] for item in checks), "max_score": 30, "checks": checks, "p0": sorted(set(p0))}


def _pedagogical(record: dict[str, Any]) -> dict[str, Any]:
    cw_ped = record["courseware_qa"].get("pedagogical", {})
    practice_ped = record["practice_qa"].get("pedagogical", {})
    cw_status = str(cw_ped.get("status", "FAIL"))
    practice_status = str(practice_ped.get("status", "FAIL"))
    courseware_contract_pass = record["courseware_qa"].get("status") == "pass"
    practice_contract_pass = record["practice_qa"].get("status") == "pass" and record["practice_qa"].get("contract", {}).get("status") == "pass"
    if not courseware_contract_pass:
        return {
            "scoring_status": "NOT_SCORED",
            "reason": "Courseware Contract/QA failed; Courseware pedagogical is not scored, Practice is not run, and Human review remains not scored.",
            "courseware_status": "NOT_SCORED",
            "practice_status": "NOT_RUN",
            "non_fail": False,
            "score": None,
            "max_score": 30,
            "checks": [],
        }
    if not practice_contract_pass:
        return {
            "scoring_status": "COURSEWARE_ELIGIBLE_PRACTICE_NOT_SCORED",
            "reason": "Courseware passed and may be reviewed independently; Practice Contract/QA failed, so Practice pedagogical and the full-package Human review are not scored.",
            "courseware_status": cw_status,
            "practice_status": "NOT_SCORED",
            "non_fail": False,
            "score": None,
            "max_score": 30,
            "checks": [],
        }
    script_planning = cw_ped.get("metrics", {}).get("speaker_script_planning", {}) if isinstance(cw_ped, dict) else {}
    repetition = cw_ped.get("metrics", {}).get("speaker_script_repetition", {}) if isinstance(cw_ped, dict) else {}
    core = record["core"]
    steps_ok = bool(record["tasks"]) and all(count >= 1 for count in record["metrics"]["task_step_counts"])
    scaffold_ok = bool(core) and all(item.get("scaffold") or item.get("starter_asset_ids") or item.get("help_refs") for item in core)
    modality_ok = all(item.get("task_kind") and item.get("capabilities") for item in record["tasks"])
    script_ok = cw_status in {"PASS", "DEGRADED"} and not script_planning.get("errors") and repetition.get("status") != "FAIL"
    refs_ok = record["metrics"]["teacher_references"] == record["metrics"]["tasks"] and bool(record["tasks"])
    support_ok = bool(record["metrics"]["guide_sections"]) and bool(core) and all(item.get("help_refs") or item.get("scaffold") or item.get("starter_asset_ids") for item in core)
    checks = [
        {"name": "course_structure", "score": 5 if steps_ok and cw_status != "FAIL" else 0, "pass": steps_ok and cw_status != "FAIL", "evidence": {"slides": record["metrics"]["slides"], "task_step_counts": record["metrics"]["task_step_counts"], "courseware_status": cw_status}, "finding": "理论页序和实践动作均可推进" if steps_ok and cw_status != "FAIL" else "课程结构或任务步骤不足"},
        {"name": "difficulty_scaffold", "score": 5 if scaffold_ok else 0, "pass": scaffold_ok, "evidence": {"core_tasks": len(core), "core_support": [item.get("id") for item in core]}, "finding": "核心任务有起点和支架" if scaffold_ok else "核心任务支架覆盖不足"},
        {"name": "natural_modality_selection", "score": 5 if modality_ok else 0, "pass": modality_ok, "evidence": {"task_kinds": sorted({str(item.get("task_kind")) for item in record["tasks"]}), "interaction_types": record["metrics"]["interaction_types"]}, "finding": "能力、任务形式和互动选择有语义表达" if modality_ok else "任务能力或形式选择不完整"},
        {"name": "speaker_script_quality", "score": 5 if script_ok else 0, "pass": script_ok, "evidence": {"courseware_status": cw_status, "script_planning": script_planning, "repetition": repetition}, "finding": "讲稿可授课且未出现机械复制失败" if script_ok else "讲稿容量、教学意图或重复风险需修订"},
        {"name": "practice_task_value", "score": 5 if refs_ok and practice_status != "FAIL" else 0, "pass": refs_ok and practice_status != "FAIL", "evidence": {"tasks": record["metrics"]["tasks"], "teacher_references": record["metrics"]["teacher_references"], "practice_status": practice_status}, "finding": "任务均有可核对教师参考" if refs_ok and practice_status != "FAIL" else "任务价值或参考成果未完整对齐"},
        {"name": "support_and_self_help", "score": 5 if support_ok else 0, "pass": support_ok, "evidence": {"guide_sections": record["metrics"]["guide_sections"], "core_tasks": len(core)}, "finding": "学生有资料、起点或帮助路径" if support_ok else "学生自助路径不足"},
    ]
    return {
        "scoring_status": "SCORED",
        "reviewer_mode": "g1-deterministic-pedagogical-review",
        "requires_human_confirmation": True,
        "courseware_status": cw_status,
        "practice_status": practice_status,
        "non_fail": cw_status in {"PASS", "DEGRADED"} and practice_status in {"PASS", "DEGRADED"},
        "score": sum(item["score"] for item in checks),
        "max_score": 30,
        "checks": checks,
    }


def _pedagogical_label(value: dict[str, Any]) -> str:
    if value.get("scoring_status") == "SCORED" and isinstance(value.get("score"), int):
        return f"{value['score']}/{value.get('max_score', 30)}"
    return str(value.get("scoring_status", "NOT_SCORED"))


def _signature(record: dict[str, Any]) -> dict[str, Any]:
    practice = record["practice"]
    return {
        "task_levels": dict(Counter(str(item.get("level")) for item in record["tasks"])),
        "task_kinds": [str(item.get("task_kind")) for item in record["tasks"]],
        "interaction_types": record["metrics"]["interaction_types"],
        "guide_shape": [_compact(item.get("title"))[:28] for item in practice.get("study_guide", []) if isinstance(item, dict)],
        "kit_shape": [_compact(item.get("title"))[:28] for item in practice.get("foundation_kit", []) if isinstance(item, dict)],
        "step_shape": record["metrics"]["task_step_counts"],
        "prepared_minutes": record["metrics"]["prepared_minutes"],
    }


def _similar(left: Any, right: Any) -> float:
    return round(SequenceMatcher(None, json.dumps(left, ensure_ascii=False, sort_keys=True), json.dumps(right, ensure_ascii=False, sort_keys=True)).ratio(), 3)


def _diversity(records: list[dict[str, Any]]) -> dict[str, Any]:
    signatures = {record["id"]: _signature(record) for record in records}
    fields = tuple(next(iter(signatures.values())).keys()) if signatures else ()
    pairs: list[dict[str, Any]] = []
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            ls, rs = signatures[left["id"]], signatures[right["id"]]
            equal = [field for field in fields if ls[field] == rs[field]]
            similarities = {field: _similar(ls[field], rs[field]) for field in fields}
            pairs.append({"left": left["id"], "right": right["id"], "equal_fields": equal, "similarities": similarities})
    warning = bool(pairs) and all(len(item["equal_fields"]) >= max(1, len(fields) - 1) and sum(item["similarities"].values()) / max(1, len(fields)) >= 0.88 for item in pairs)
    explanation = "" if not warning else "三门课程在任务形状、互动序列和资料结构上高度同构；该信号只提示人工检查，不因数量相同自动扣分。"
    return {"status": "TEMPLATE_OVERFIT_WARNING" if warning else "diverse-enough-signal", "warning": warning, "explained": not warning or bool(explanation), "signatures": signatures, "pairs": pairs, "interpretation": explanation or "未发现三门课程在主要结构维度上异常同构。"}


def _verify_frozen_sources(root: Path, source_root: Path) -> dict[str, Any]:
    manifest = _read(source_root / "SOURCE-FREEZE.json", {})
    result: dict[str, Any] = {}
    for entry in manifest.get("holdouts", []) if isinstance(manifest, dict) else []:
        if not isinstance(entry, dict):
            continue
        course = str(entry.get("relative_dir") or entry.get("id", ""))
        errors: list[str] = []
        expected = {str(item.get("relative_path")): str(item.get("sha256", "")).lower() for item in entry.get("files", []) if isinstance(item, dict) and item.get("relative_path")}
        for relative, digest in expected.items():
            path = source_root / relative
            if not path.is_file():
                errors.append(f"missing {relative}")
            elif _sha256(path) != digest:
                errors.append(f"hash mismatch {relative}")
        actual = {path.relative_to(source_root).as_posix() for path in (source_root / course).rglob("*") if path.is_file()} if (source_root / course).is_dir() else set()
        expected_for_course = {relative for relative in expected if relative == course or relative.startswith(course + "/")}
        if actual != expected_for_course:
            errors.append(f"file set differs: missing={sorted(expected_for_course - actual)} extra={sorted(actual - expected_for_course)}")
        result[course] = {"status": "pass" if not errors else "fail", "errors": errors, "file_count": len(expected)}
    return result


def _comparison(first: list[dict[str, Any]], second: list[dict[str, Any]], first_obj: dict[str, Any], second_obj: dict[str, Any], first_ped: dict[str, Any], second_ped: dict[str, Any], diversity: dict[str, Any], source_status: dict[str, Any]) -> str:
    first_by = {item["id"]: item for item in first}
    second_by = {item["id"]: item for item in second}
    lines = [
        "# G1 Generalization Comparison",
        "",
        "First-pass directories are read-only evidence. Second-pass output is generated in a separate root after the adaptive planning and contract-repair update.",
        "",
        "| Course | First Objective | Second Objective | First Pedagogical | Second Pedagogical | First P0 | Second P0 | Courseware / Practice second QA |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for course in COURSES:
        fr, sr = first_by[course], second_by[course]
        so, sp = second_obj[course], second_ped[course]
        lines.append(f"| {course} | {first_obj[course]['score']}/30 | {so['score']}/30 | {_pedagogical_label(first_ped[course])} | {_pedagogical_label(sp)} | {'; '.join(first_obj[course]['p0']) or '0'} | {'; '.join(so['p0']) or '0'} | {sr['courseware_qa'].get('status')} / {sr['practice_qa'].get('status')} |")
    lines.extend([
        "",
        "## Second-pass design evidence",
        "",
        "- Blueprint validation, task semantics, and repair actions are preserved in each second-pass course root.",
        "- Counts and level distributions are descriptive only; they are not used as objective or pedagogical rewards.",
        f"- Frozen source verification: {json.dumps(source_status, ensure_ascii=False, sort_keys=True)}",
        f"- Template diversity: {diversity['status']}; warning={diversity['warning']}; explained={diversity['explained']}",
        "",
        "## Human Gold Review",
        "",
        "PENDING /40. A teacher must open the frozen second-pass HTML beside the copied raw source before a total score is assigned.",
        "",
        "## Decision",
        "",
        "The machine gate is recorded in second-pass/evaluation/gate.json. This comparison does not authorize merge, release, G2, or a third pass.",
    ])
    return "\n".join(lines) + "\n"


def _human_template() -> str:
    return """# G1 Second-pass Human Gold Review Template

Human review remains PENDING /40 until a teacher opens the frozen HTML beside `raw-source/`.

| Dimension | Max | Python Web | Spreadsheet | Networking | Evidence / reviewer note |
|---|---:|---:|---:|---:|---|
| 老师是否愿意直接用 | 10 | PENDING | PENDING | PENDING | |
| 学生是否真正做得出来 | 8 | PENDING | PENDING | PENDING | |
| 理论课是否能讲满且不水 | 8 | PENDING | PENDING | PENDING | |
| 实践是否像真实机房课 | 6 | PENDING | PENDING | PENDING | |
| 视觉与信息密度 | 4 | PENDING | PENDING | PENDING | |
| 教师参考是否足够 | 4 | PENDING | PENDING | PENDING | |
| 合计 | 40 | PENDING | PENDING | PENDING | |

检查真实资料边界、核心/扩展路径、讲稿可讲性、任务起点、工具可操作性、互动反馈、学生答案隔离和教师参考成果。自动分数不能替代人工分数。
"""


def _zip(root: Path, destination: Path) -> None:
    def add_tree(base: Path, archive_prefix: str) -> None:
        if not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file():
                relative = path.relative_to(base).as_posix()
                archive.write(path, f"{archive_prefix}/{relative}")

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        # The second-pass root may contain quarantined failed attempts from
        # bounded reruns.  They remain available on disk for audit, but the
        # deliverable must contain only the final three course packages and
        # the declared evidence roots.
        trees = (
            ("second-pass/python-web", "python-web"),
            ("second-pass/spreadsheet", "spreadsheet"),
            ("second-pass/networking", "networking"),
            ("second-pass/evaluation", "evaluation"),
            ("second-pass/generation-decision", "generation-decision"),
            ("second-pass/objective-report", "objective-report"),
            ("second-pass/pedagogical-report", "pedagogical-report"),
            ("raw-source", "raw-source"),
            ("source-freeze", "source-freeze"),
        )
        for relative_root, archive_prefix in trees:
            add_tree(root / relative_root, archive_prefix)
        for name in ("G1-GENERALIZATION-COMPARISON.md", "baseline.json"):
            path = root / name
            if path.is_file():
                archive.write(path, name)


def evaluate(root: Path, source_root: Path) -> dict[str, Any]:
    first = [_record(root, "first-pass", course) for course in COURSES]
    second = [_record(root, "second-pass", course) for course in COURSES]
    source_status = _verify_frozen_sources(root, source_root)
    first_obj = {record["id"]: _objective(record, source_status) for record in first}
    second_obj = {record["id"]: _objective(record, source_status) for record in second}
    first_ped = {record["id"]: _pedagogical(record) for record in first}
    second_ped = {record["id"]: _pedagogical(record) for record in second}
    diversity = _diversity(second)
    second_dir = root / "second-pass" / "evaluation"
    second_dir.mkdir(parents=True, exist_ok=True)
    _write(second_dir / "objective-report.json", {"pass": "second-pass", "rubric_max": 30, "courses": second_obj})
    _write(second_dir / "pedagogical-report.json", {"pass": "second-pass", "rubric_max": 30, "courses": second_ped})
    _write(second_dir / "template-diversity.json", diversity)
    _write(second_dir / "frozen-source-verification.json", source_status)
    (second_dir / "human-review-template.md").write_text(_human_template(), encoding="utf-8", newline="\n")
    for course in COURSES:
        _write(root / "second-pass" / "generation-decision" / f"{course}.json", second[COURSES.index(course)]["decision"])
        _write(root / "second-pass" / "objective-report" / f"{course}.json", second_obj[course])
        _write(root / "second-pass" / "pedagogical-report" / f"{course}.json", second_ped[course])
    gate: dict[str, Any] = {}
    for course in COURSES:
        record = second[COURSES.index(course)]
        gate[course] = {
            "courseware_contract_pass": record["courseware_qa"].get("status") == "pass",
            "courseware_pedagogical_non_fail": second_ped[course]["courseware_status"] in {"PASS", "DEGRADED"},
            "practice_contract_pass": record["practice_qa"].get("contract", {}).get("status") == "pass",
            "practice_pedagogical_non_fail": second_ped[course]["practice_status"] in {"PASS", "DEGRADED"},
            "p0": second_obj[course]["p0"],
            "output_freeze": record["output_freeze"],
            "frozen_output_verified": record["output_freeze"].get("status") == "pass",
            "runner_status": record["run_report"].get("status"),
        }
    gate["template_warning_false_or_explained"] = not diversity["warning"] or diversity["explained"]
    gate["source_frozen"] = all(item.get("status") == "pass" for item in source_status.values()) and bool(source_status)
    gate["all_required_checks"] = all(
        value.get("courseware_contract_pass") and value.get("courseware_pedagogical_non_fail") and value.get("practice_contract_pass") and value.get("practice_pedagogical_non_fail") and value.get("frozen_output_verified") and not value.get("p0")
        for key, value in gate.items() if key in COURSES
    )
    gate["status"] = "READY_FOR_BLIND_SECOND_PASS_MANUAL_REVIEW" if gate["all_required_checks"] and gate["template_warning_false_or_explained"] and gate["source_frozen"] else "G1_SECOND_PASS_FAILED"
    _write(second_dir / "gate.json", gate)
    comparison = _comparison(first, second, first_obj, second_obj, first_ped, second_ped, diversity, source_status)
    (root / "G1-GENERALIZATION-COMPARISON.md").write_text(comparison, encoding="utf-8", newline="\n")
    (second_dir / "G1-GENERALIZATION-COMPARISON.md").write_text(comparison, encoding="utf-8", newline="\n")
    _zip(root, root / "blind-generalization-second-pass.zip")
    return {
        "status": gate["status"],
        "gate": gate,
        "objective": second_obj,
        "pedagogical": second_ped,
        "template_diversity": diversity,
        "comparison": str(root / "G1-GENERALIZATION-COMPARISON.md"),
        "zip": str(root / "blind-generalization-second-pass.zip"),
        "human_review": str(second_dir / "human-review-template.md"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = evaluate(args.output_root.expanduser().resolve(), args.source_root.expanduser().resolve())
    except Exception as exc:  # noqa: BLE001 - preserve machine-readable gate failure
        result = {"status": "G1_SECOND_PASS_FAILED", "errors": [str(exc)]}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY_FOR_BLIND_SECOND_PASS_MANUAL_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
