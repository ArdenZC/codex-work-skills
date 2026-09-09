"""Render and audit the five course-neutral generalization holdouts.

This audit is deliberately metric-driven but does not treat a green schema or
browser run as content acceptance.  It records structural, interaction,
student-completion, teacher-usability, and pacing evidence separately, then
leaves the final Gold-quality sign-off to human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
HOLDOUT_ROOT = SKILL_ROOT / "holdouts"
SOURCE_ROOT = HOLDOUT_ROOT / "source-packs"
PRACTICE_ROOT = HOLDOUT_ROOT / "practice-contracts"
MANIFEST_PATH = HOLDOUT_ROOT / "SOURCE-FREEZE.json"
COURSEWARE_ROOT = SKILL_ROOT.parents[1] / "HTML课件生成器" / "courseware-html-generator"
COURSEWARE_RENDER = COURSEWARE_ROOT / "scripts" / "render_courseware.py"
COURSEWARE_VALIDATE = COURSEWARE_ROOT / "scripts" / "validate_courseware.py"
COURSEWARE_SMOKE = COURSEWARE_ROOT / "tests" / "browser_smoke.mjs"
PRACTICE_RENDER = SKILL_ROOT / "scripts" / "render_practice.py"
PRACTICE_VALIDATE = SKILL_ROOT / "scripts" / "validate_practice.py"
PRACTICE_SMOKE = SKILL_ROOT / "tests" / "browser_smoke.mjs"
DEFAULT_GOLD_ROOT = Path(r"F:\work\practice-class-gold-sample-20260907")

if str(COURSEWARE_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(COURSEWARE_ROOT / "scripts"))
if str(SKILL_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from content_contract import validate_content as validate_courseware_content  # noqa: E402
from practice_contract import validate_content as validate_practice_content  # noqa: E402


NON_C_POLLUTION = re.compile(r"(?i)(?:#\s*include\s*[<\"]|\bdev-c\+\+\b|\bcode::blocks\b|\bbinary_search\b|\bc\s*语言补给|\bmalloc\s*\()")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _run_json(command: list[str], cwd: Path = SKILL_ROOT) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=cwd, capture_output=True)
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{stdout}\n{stderr}")
    output = stdout.strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command did not emit JSON: {' '.join(command)}\n{output}") from exc


def _verify_manifest() -> list[dict[str, Any]]:
    manifest = _load(MANIFEST_PATH)
    if manifest.get("status") not in {"pass", "frozen-before-first-generation"}:
        raise RuntimeError("holdout SOURCE-FREEZE.json is not a recognized frozen manifest")
    entries = manifest.get("holdouts")
    if not isinstance(entries, list) or len(entries) != 5:
        raise RuntimeError("holdout SOURCE-FREEZE.json must contain exactly five frozen pairs")
    for entry in entries:
        courseware = SOURCE_ROOT / str(entry["courseware"])
        practice = PRACTICE_ROOT / str(entry["practice"])
        if _sha256(courseware) != entry["courseware_sha256"]:
            raise RuntimeError(f"frozen Courseware source changed: {courseware.name}")
        if _sha256(practice) != entry["practice_sha256"]:
            raise RuntimeError(f"frozen Practice source changed: {practice.name}")
    return entries


def _render_one(entry: dict[str, Any], pass_root: Path) -> dict[str, Any]:
    holdout_id = str(entry["id"])
    courseware_source = SOURCE_ROOT / str(entry["courseware"])
    practice_source = PRACTICE_ROOT / str(entry["practice"])
    courseware_output = pass_root / "courseware" / holdout_id
    practice_output = pass_root / "practice" / holdout_id
    courseware_output.parent.mkdir(parents=True, exist_ok=True)
    practice_output.parent.mkdir(parents=True, exist_ok=True)
    courseware_render = _run_json([sys.executable, str(COURSEWARE_RENDER), "--content-json", str(courseware_source), "--output-dir", str(courseware_output), "--replace", "--json"])
    practice_render = _run_json([sys.executable, str(PRACTICE_RENDER), "--practice-json", str(practice_source), "--courseware-json", str(courseware_source), "--output-dir", str(practice_output), "--replace", "--json"])
    courseware_validation = _run_json([sys.executable, str(COURSEWARE_VALIDATE), "--content-json", str(courseware_source), "--student-html", str(courseware_output / "student.html"), "--teacher-html", str(courseware_output / "teacher.html"), "--json"])
    practice_validation = _run_json([sys.executable, str(PRACTICE_VALIDATE), "--practice-json", str(practice_source), "--courseware-json", str(courseware_source), "--output-dir", str(practice_output), "--json"])
    return {"id": holdout_id, "courseware_output": str(courseware_output), "practice_output": str(practice_output), "courseware_render": courseware_render, "practice_render": practice_render, "courseware_validation": courseware_validation, "practice_validation": practice_validation}


def _safe_student_checks(practice_output: Path) -> dict[str, Any]:
    safe_path = practice_output / "student-package" / "practice-content.json"
    manifest_path = practice_output / "student-package" / "student-manifest.json"
    safe = _load(safe_path) if safe_path.is_file() else {}
    manifest = _load(manifest_path) if manifest_path.is_file() else {}
    forbidden_fields = [field for field in ("teacher_guide", "teacher_reference", "canonical_facts") if field in safe]
    gap_leaks: list[str] = []
    for asset in safe.get("starter_assets", []):
        if isinstance(asset, dict):
            gap_leaks.extend(field for field in ("editable_gaps", "replacement", "target") if field in asset)
    flags = {field: manifest.get(field) is False for field in ("teacher_answers_included", "replacement_metadata_included", "canonical_answers_included")}
    return {"manifest_flags": flags, "forbidden_content_fields": forbidden_fields, "starter_gap_leaks": gap_leaks, "status": "pass" if all(flags.values()) and not forbidden_fields and not gap_leaks else "fail"}


def _all_output_text(practice_output: Path) -> str:
    chunks: list[str] = []
    for path in practice_output.rglob("*"):
        if path.is_file() and path.suffix.casefold() in {".html", ".json", ".txt", ".csv", ".py", ".sql", ".xml", ".md"}:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def _score(entry: dict[str, Any], rendered: dict[str, Any], gold_root: Path) -> dict[str, Any]:
    courseware = _load(SOURCE_ROOT / str(entry["courseware"]))
    practice = _load(PRACTICE_ROOT / str(entry["practice"]))
    courseware_report = validate_courseware_content(courseware, base_dir=SOURCE_ROOT)
    practice_report = validate_practice_content(practice, courseware)
    tasks = [item for item in practice.get("tasks", []) if isinstance(item, dict)]
    core = [item for item in tasks if item.get("level") == "core"]
    slides = {str(item.get("id")) for item in courseware.get("slides", []) if isinstance(item, dict)}
    task_trace = [item for item in tasks if set(item.get("source_slide_ids", [])) <= slides and item.get("source_slide_ids")]
    knowledge = [item for item in practice.get("knowledge_links", []) if isinstance(item, dict)]
    knowledge_trace = [item for item in knowledge if set(item.get("source_slide_ids", [])) <= slides and item.get("source_slide_ids")]
    levels = Counter(str(item.get("level")) for item in tasks)
    step_counts = [len(item.get("steps", [])) for item in tasks]
    interactions = [item.get("interaction", {}) for item in practice.get("learning_center", []) if isinstance(item, dict)]
    interaction_types = sorted({str(item.get("type")) for item in interactions if item.get("type")})
    dynamic_types = {"state-simulator", "stepper", "trace", "diagnose", "multi-question", "classify", "reorder"}
    safe_checks = _safe_student_checks(Path(rendered["practice_output"]))
    context_ok = practice.get("course_context") == courseware.get("course_context")
    output_text = _all_output_text(Path(rendered["practice_output"]))
    language = str(courseware.get("course_context", {}).get("language", "")).casefold()
    non_c_pollution = bool(NON_C_POLLUTION.search(output_text)) if not any(token in language for token in ("c", "c++", "cpp")) else False
    teacher_refs = practice.get("teacher_reference", {}).get("task_references", [])
    teacher_guide = practice.get("teacher_guide", {})
    timing_total = sum(int(item.get("minutes", 0)) for item in teacher_guide.get("timing", []) if isinstance(item, dict))
    planned_courseware = int(courseware.get("prepared_minutes", 0))
    task_minutes = sum(int(item.get("estimated_minutes", 0)) for item in tasks)

    trace_score = round(20 * (0.55 * len(task_trace) / max(1, len(tasks)) + 0.25 * len(knowledge_trace) / max(1, len(knowledge)) + 0.20 * (1 if context_ok else 0)), 1)
    granularity_score = round(15 * (0.30 * min(1, len(tasks) / 8) + 0.25 * min(1, levels["core"] / 5) + 0.15 * min(1, (levels["optional"] + levels["challenge"]) / 2) + 0.20 * min(1, sum(1 for count in step_counts if 3 <= count <= 6) / max(1, len(tasks))) + 0.10 * min(1, task_minutes / 90)), 1)
    starter_tasks = [item for item in tasks if item.get("artifact_kind") in {"source-code", "query", "model", "diagram", "workbook"}]
    starter_score = round(15 * (0.35 * min(1, sum(1 for item in core if item.get("scaffold")) / max(1, len(core))) + 0.30 * min(1, len(starter_tasks) / max(1, len(core))) + 0.20 * (1 if safe_checks["status"] == "pass" else 0) + 0.15 * (1 if not non_c_pollution else 0)), 1)
    interaction_minutes = sum(int(item.get("estimated_minutes", 0)) for item in interactions)
    interaction_score = round(15 * (0.25 * min(1, len(interaction_types) / 6) + 0.25 * min(1, len([item for item in interactions if item.get("type") in dynamic_types]) / 6) + 0.15 * min(1, sum(1 for item in interactions if item.get("type") == "diagnose") / 1) + 0.15 * min(1, sum(1 for item in interactions if item.get("type") in {"multi-question", "state-simulator"}) / 1) + 0.20 * min(1, interaction_minutes / 30)), 1)
    guides = practice.get("study_guide", [])
    kits = practice.get("foundation_kit", [])
    help_coverage = sum(1 for item in core if item.get("help_refs")) / max(1, len(core))
    material_score = round(15 * (0.30 * min(1, len(guides) / 6) + 0.25 * min(1, len(kits) / 5) + 0.25 * help_coverage + 0.20 * min(1, sum(1 for item in guides if len(str(item.get("body", ""))) >= 80 and item.get("worked_example") and item.get("quick_reference")) / max(1, len(guides)))), 1)
    teacher_score = round(10 * (0.45 * min(1, len(teacher_refs) / max(1, len(tasks))) + 0.20 * (1 if teacher_guide.get("timing") else 0) + 0.20 * min(1, len(teacher_guide.get("task_guidance", [])) / max(1, len(core))) + 0.15 * min(1, sum(1 for item in teacher_refs if str(item.get("reference_answer", "")).strip()) / max(1, len(tasks)))), 1)
    context_score = round(5 * (0.60 * (1 if context_ok else 0) + 0.40 * (0 if non_c_pollution else 1)), 1)
    pacing_score = round(5 * (0.35 * (1 if planned_courseware == 90 else 0) + 0.25 * (1 if int(practice.get("duration_minutes", 0)) == 90 else 0) + 0.25 * (1 if timing_total == 90 else 0) + 0.15 * (1 if task_minutes == 90 else 0)), 1)
    scores = {"theory_practice_trace": trace_score, "task_granularity": granularity_score, "scaffold_and_completion": starter_score, "interaction_depth": interaction_score, "learning_material_density": material_score, "teacher_usability": teacher_score, "context_generalization": context_score, "classroom_pacing": pacing_score}
    total = round(sum(scores.values()), 1)
    gold_files = list(gold_root.rglob("*")) if gold_root.is_dir() else []
    gold_html = [path for path in gold_files if path.suffix.casefold() == ".html"]
    evidence = {"task_count": len(tasks), "levels": dict(levels), "step_counts": step_counts, "source_slide_count": len(slides), "traced_task_count": len(task_trace), "traced_knowledge_count": len(knowledge_trace), "interaction_types": interaction_types, "interaction_minutes": interaction_minutes, "study_guide_sections": len(guides), "foundation_topics": len(kits), "core_help_coverage": round(help_coverage, 3), "teacher_reference_count": len(teacher_refs), "courseware_prepared_minutes": planned_courseware, "practice_task_minutes": task_minutes, "teacher_timing_minutes": timing_total, "safe_student_package": safe_checks, "non_c_pollution": non_c_pollution, "courseware_contract_status": courseware_report["status"], "practice_contract_status": practice_report["status"], "gold_benchmark": {"root": str(gold_root), "file_count": len([path for path in gold_files if path.is_file()]), "html_count": len(gold_html)}}
    return {"id": str(entry["id"]), "scores": scores, "total": total, "evidence": evidence, "status": "pass" if total >= 75 and not non_c_pollution and courseware_report["status"] == "pass" and practice_report["status"] == "pass" else "fail"}


def _browser_smoke(pass_root: Path) -> dict[str, Any]:
    env = dict(**__import__("os").environ)
    practice_root = pass_root / "practice"
    practice_command = ["node", str(PRACTICE_SMOKE), str(practice_root)]
    practice = subprocess.run(practice_command, cwd=SKILL_ROOT, capture_output=True, env=env)
    practice_stdout = (practice.stdout or b"").decode("utf-8", errors="replace")
    practice_stderr = (practice.stderr or b"").decode("utf-8", errors="replace")
    courseware_results: dict[str, Any] = {}
    for courseware_dir in sorted((pass_root / "courseware").iterdir()):
        if not courseware_dir.is_dir():
            continue
        command = ["node", str(COURSEWARE_SMOKE), str(courseware_dir / "student.html")]
        result = subprocess.run(command, cwd=COURSEWARE_ROOT, capture_output=True, env=env)
        courseware_results[courseware_dir.name] = {"status": "pass" if result.returncode == 0 else "fail", "stdout": (result.stdout or b"").decode("utf-8", errors="replace").strip(), "stderr": (result.stderr or b"").decode("utf-8", errors="replace").strip()}
    return {"status": "pass" if practice.returncode == 0 and all(item["status"] == "pass" for item in courseware_results.values()) else "fail", "practice": {"status": "pass" if practice.returncode == 0 else "fail", "stdout": practice_stdout.strip(), "stderr": practice_stderr.strip()}, "courseware": courseware_results}


def _write_report(pass_root: Path, report: dict[str, Any]) -> None:
    (pass_root / "holdout-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = [f"# Holdout audit — {report['pass_name']}", "", f"- Technical status: **{report['status']}**", f"- Content-quality review: **{report['content_acceptance']}**", f"- Average score: **{report['average_score']} / 100**", "", "| Holdout | Score | Status |", "|---|---:|---|"]
    lines.extend(f"| {item['id']} | {item['total']} | {item['status']} |" for item in report["holdouts"])
    lines.extend(["", "The score is an auditable architecture/content signal, not a substitute for a teacher reviewing the five generated packages beside the frozen Gold Sample.", "", "## Gold benchmark provenance", "", f"- Frozen reference root: `{report['gold_benchmark']['root']}`", f"- Files: {report['gold_benchmark']['file_count']}; HTML samples: {report['gold_benchmark']['html_count']}", "- No Gold HTML, C source, or data-structure content is copied into the repository."])
    (pass_root / "holdout-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _compare(output_root: Path) -> dict[str, Any]:
    first = _load(output_root / "first-pass" / "holdout-report.json")
    second = _load(output_root / "second-pass" / "holdout-report.json")
    first_scores = {item["id"]: item["total"] for item in first["holdouts"]}
    second_scores = {item["id"]: item["total"] for item in second["holdouts"]}
    stable = all(first_scores.get(key) == second_scores.get(key) for key in first_scores)
    report = {"status": "pass" if first["status"] == "pass" and second["status"] == "pass" and stable else "fail", "content_acceptance": "pending_manual_review", "average_score": second["average_score"], "first_pass": {"average_score": first["average_score"], "scores": first_scores}, "second_pass": {"average_score": second["average_score"], "scores": second_scores}, "stable": stable, "holdouts": second["holdouts"], "gold_benchmark": second["gold_benchmark"], "browser_smoke": {"first_pass": first.get("browser_smoke", {"status": "not-run"}), "second_pass": second.get("browser_smoke", {"status": "not-run"})}}
    (output_root / "holdout-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = ["# Five-course generalization holdout comparison", "", f"- Technical decision: **{report['status']}**", f"- Content acceptance: **{report['content_acceptance']}**", f"- First pass average: **{first['average_score']} / 100**", f"- Second pass average: **{second['average_score']} / 100**", f"- Pass-to-pass stable: **{report['stable']}**", "", "| Holdout | First pass | Second pass |", "|---|---:|---:|"]
    for item in second["holdouts"]:
        lines.append(f"| {item['id']} | {first_scores[item['id']]} | {item['total']} |")
    lines.extend(["", "The five holdouts are deliberately outside the three regression fixtures: Python Web, Excel/Power Query, IPv4/Wireshark, AI evaluation, and software testing/Gherkin.", "The Gold Sample is used only as a frozen, abstract quality benchmark. Human content acceptance remains open until the generated packages are reviewed side by side."])
    (output_root / "holdout-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--pass-name", choices=("first-pass", "second-pass"))
    parser.add_argument("--gold-root", type=Path, default=DEFAULT_GOLD_ROOT)
    parser.add_argument("--browser-smoke", action="store_true")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    if args.compare:
        print(json.dumps(_compare(args.output_root), ensure_ascii=False, indent=2))
        return 0
    if not args.pass_name:
        parser.error("--pass-name is required unless --compare is used")
    entries = _verify_manifest()
    pass_root = args.output_root / args.pass_name
    if pass_root.exists() and any(pass_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite frozen audit pass: {pass_root}")
    pass_root.mkdir(parents=True, exist_ok=True)
    rendered = [_render_one(entry, pass_root) for entry in entries]
    holdouts = [_score(entry, item, args.gold_root) for entry, item in zip(entries, rendered)]
    browser = _browser_smoke(pass_root) if args.browser_smoke else {"status": "not-run"}
    average = round(sum(item["total"] for item in holdouts) / max(1, len(holdouts)), 1)
    report = {"pass_name": args.pass_name, "status": "pass" if all(item["status"] == "pass" for item in holdouts) and average >= 85 and (browser["status"] in {"pass", "not-run"}) else "fail", "content_acceptance": "pending_manual_review", "average_score": average, "holdouts": holdouts, "browser_smoke": browser, "gold_benchmark": holdouts[0]["evidence"]["gold_benchmark"] if holdouts else {"root": str(args.gold_root), "file_count": 0, "html_count": 0}}
    _write_report(pass_root, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
