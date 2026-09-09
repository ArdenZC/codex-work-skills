"""Run the generic render/QA/freeze pipeline for one Agent-authored blind holdout.

This entry point never authors a course contract and contains no course-specific
branches.  A separate Agent must provide both 1.1 contracts and the public design
decision summary.  ``--generation-method builder`` is deliberately rejected so a
deterministic fixture builder cannot be reported as blind Skill generation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DECISION_KEYS = {
    "course_blueprint",
    "learning_units",
    "courseware_structure_reasoning_summary",
    "practice_blueprint",
    "chosen_task_kinds",
    "chosen_scaffold_levels",
    "chosen_interactions",
    "why_these_interactions_fit",
    "rejected_options",
}
FORBIDDEN_INPUT_MARKERS = (
    "holdouts/practice-contracts",
    "holdouts/source-packs",
    "examples/data-structures",
    "examples/uml",
    "examples/database",
)
SECOND_PASS_FORBIDDEN_INPUT_MARKERS = (
    "blind-generalization-20260907/first-pass",
    "blind-generalization-20260907/agent-inputs",
)
THIRD_PASS_FORBIDDEN_INPUT_MARKERS = (
    "blind-generalization-20260907/first-pass",
    "blind-generalization-20260907/second-pass",
    "blind-generalization-20260907/second-agent-inputs",
    "blind-generalization-20260907/agent-inputs",
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _manifest_scalar(path: Path, key: str) -> str | None:
    """Read a simple unquoted YAML scalar without adding a YAML dependency."""

    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*[\"']?([^\"'\r\n#]+?)[\"']?\s*$", re.MULTILINE)
    match = pattern.search(path.read_text(encoding="utf-8"))
    return match.group(1).strip() if match else None


def _git_provenance(repo: Path, expected_commit: str | None) -> dict[str, Any]:
    repo = repo.expanduser().resolve()
    result: dict[str, Any] = {"repository": str(repo), "expected_commit": expected_commit, "status": "fail", "errors": []}
    if not repo.is_dir():
        result["errors"].append(f"generator repository does not exist: {repo}")
        return result
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        result["errors"].append(f"cannot read generator git state: {exc}")
        return result
    result.update({"head": head, "dirty_worktree": bool(dirty.strip()), "status_porcelain": dirty})
    if expected_commit and head.casefold() != expected_commit.casefold():
        result["errors"].append(f"generator HEAD {head} does not match requested commit {expected_commit}")
    if dirty.strip():
        result["errors"].append("generator worktree is dirty for formal blind generation")
    result["status"] = "pass" if not result["errors"] else "fail"
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _find_freeze_manifest(source_pack: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit.expanduser().resolve()
    for parent in (source_pack.resolve(), *source_pack.resolve().parents):
        candidate = parent / "SOURCE-FREEZE.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"could not find SOURCE-FREEZE.json above {source_pack}")


def _verify_source_freeze(source_pack: Path, explicit: Path | None = None) -> dict[str, Any]:
    source_pack = source_pack.expanduser().resolve()
    manifest_path = _find_freeze_manifest(source_pack, explicit)
    manifest = _json_load(manifest_path)
    errors: list[str] = []
    if manifest.get("status") != "frozen-before-generation":
        errors.append("source freeze status is not frozen-before-generation")
    try:
        source_rel = _relative(source_pack, manifest_path.parent)
    except ValueError:
        source_rel = ""
        errors.append("source pack is outside the freeze manifest root")
    entry = next((item for item in manifest.get("holdouts", []) if item.get("relative_dir") == source_rel), None)
    if not isinstance(entry, dict):
        errors.append(f"source pack is not listed in freeze manifest: {source_rel}")
        return {"status": "fail", "errors": errors, "manifest": str(manifest_path), "files": []}
    expected_files = {
        str(item.get("relative_path")): str(item.get("sha256", "")).lower()
        for item in entry.get("files", [])
        if isinstance(item, dict) and item.get("relative_path")
    }
    actual_files = {
        _relative(path, manifest_path.parent)
        for path in source_pack.rglob("*")
        if path.is_file()
    }
    if actual_files != set(expected_files):
        errors.append(
            "source pack file set differs from freeze manifest: "
            f"missing={sorted(set(expected_files) - actual_files)} extra={sorted(actual_files - set(expected_files))}"
        )
    checked: list[dict[str, Any]] = []
    for relative_path, expected_sha in sorted(expected_files.items()):
        target = manifest_path.parent / relative_path
        if not target.is_file():
            errors.append(f"frozen source file is missing: {relative_path}")
            continue
        actual_sha = _sha256(target)
        checked.append({"relative_path": relative_path, "sha256": actual_sha})
        if actual_sha != expected_sha:
            errors.append(f"frozen source hash mismatch: {relative_path}")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "manifest": str(manifest_path),
        "holdout_id": entry.get("id"),
        "frozen_at": manifest.get("frozen_at"),
        "files": checked,
    }


def _check_input_path(path: Path, label: str, extra_markers: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        errors.append(f"{label} does not exist: {path}")
        return errors
    normalized = str(path.resolve()).replace("\\", "/").casefold()
    for marker in (*FORBIDDEN_INPUT_MARKERS, *extra_markers):
        if marker in normalized:
            errors.append(f"{label} is inside a forbidden historical fixture path: {path}")
    return errors


def _check_input_content(path: Path, label: str, extra_markers: tuple[str, ...] = ()) -> list[str]:
    """Reject historical contract/answer references hidden in a copied input."""

    if not path.is_file():
        return []
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{label} cannot be read for blind-boundary inspection: {exc}"]
    normalized = value.replace("\\", "/").casefold()
    markers = (*FORBIDDEN_INPUT_MARKERS, *extra_markers)
    return [f"{label} contains a forbidden historical input marker: {marker}" for marker in markers if marker.casefold() in normalized]


def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
        return {
            "status": "pass" if result.returncode == 0 else "fail",
            "returncode": result.returncode,
            "command": command,
            "cwd": str(cwd),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:  # noqa: BLE001 - pipeline evidence must retain command failure
        return {"status": "fail", "returncode": None, "command": command, "cwd": str(cwd), "stdout": "", "stderr": str(exc)}


def _decision_errors(path: Path) -> list[str]:
    try:
        value = _json_load(path)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        return [f"generation decision is not valid JSON: {exc}"]
    if not isinstance(value, dict):
        return ["generation decision must be a JSON object"]
    missing = sorted(DECISION_KEYS - set(value))
    errors = [f"generation decision is missing required public summary keys: {', '.join(missing)}"] if missing else []
    private_keys = sorted(key for key in value if any(marker in key.casefold() for marker in ("chain_of_thought", "private_reasoning", "hidden_reasoning")))
    if private_keys:
        errors.append("generation decision contains private chain-of-thought fields: " + ", ".join(private_keys))
    return errors


def _validate_blueprint(script: Path, function_name: str, value: Any) -> dict[str, Any]:
    """Load the validator from the selected Skill without importing repo code."""

    spec = importlib.util.spec_from_file_location(f"_g1_{function_name}_{id(value)}", script)
    if spec is None or spec.loader is None:
        return {"status": "fail", "errors": [f"cannot load blueprint validator: {script}"], "warnings": []}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function_name)(value)


def _blueprint_validation(decision_path: Path, courseware_skill: Path, practice_skill: Path, *, required: bool) -> dict[str, Any]:
    if not required:
        return {"status": "not-required", "courseware": None, "practice": None, "errors": []}
    try:
        decision = _json_load(decision_path)
        if not isinstance(decision, dict):
            return {"status": "fail", "courseware": None, "practice": None, "errors": ["generation decision must be an object before blueprint validation"]}
        courseware = _validate_blueprint(
            courseware_skill / "scripts" / "teaching_blueprint.py",
            "validate_course_blueprint",
            decision.get("course_blueprint"),
        )
        practice = _validate_blueprint(
            practice_skill / "scripts" / "teaching_blueprint.py",
            "validate_practice_blueprint",
            decision.get("practice_blueprint"),
        )
        errors = [f"course_blueprint: {item}" for item in courseware.get("errors", [])]
        errors.extend(f"practice_blueprint: {item}" for item in practice.get("errors", []))
        return {
            "status": "pass" if not errors else "fail",
            "courseware": courseware,
            "practice": practice,
            "errors": errors,
        }
    except Exception as exc:  # noqa: BLE001 - preserve invalid public planning evidence
        return {"status": "fail", "courseware": None, "practice": None, "errors": [f"blueprint validation failed: {exc}"]}


def _freeze_output(output_dir: Path, status: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path.name == "output-freeze.json":
            continue
        files.append({"relative_path": _relative(path, output_dir), "sha256": _sha256(path)})
    manifest = {"status": status, "frozen_at": _now(), "files": files}
    _write_json(output_dir / "output-freeze.json", manifest)
    return manifest


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite output subdirectory: {target}")
    shutil.copytree(source, target)


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    pass_name = getattr(args, "pass_name", "first-pass")
    auto_repair = bool(getattr(args, "auto_repair", False))
    source_pack = args.source_pack.expanduser().resolve()
    courseware_skill = args.courseware_skill.expanduser().resolve()
    practice_skill = args.practice_skill.expanduser().resolve()
    courseware_json = args.courseware_json.expanduser().resolve()
    practice_json = args.practice_json.expanduser().resolve()
    decision_json = args.generation_decision.expanduser().resolve()
    output = args.output.expanduser().resolve()
    third_pass = pass_name in {"third-pass", "fourth-pass"}
    if pass_name == 'fourth-pass':
        for p in (courseware_json, practice_json, decision_json):
            normalized_path = str(p).replace('\\', '/').casefold()
            if any(marker in normalized_path for marker in ('/third-pass/', '/third-agent-inputs/')):
                raise ValueError('fourth-pass forbids third-pass inputs')
    extra_forbidden = (
        THIRD_PASS_FORBIDDEN_INPUT_MARKERS
        if third_pass
        else SECOND_PASS_FORBIDDEN_INPUT_MARKERS if pass_name == "second-pass" else ()
    )
    errors: list[str] = []
    if pass_name not in {"first-pass", "second-pass", "third-pass", "fourth-pass"}:
        errors.append(f"unsupported pass name: {pass_name}")
    if args.generation_method != "agent-skill":
        errors.append("BLIND_TEST_INVALID: generation method is not agent-skill")
    if not source_pack.is_dir():
        errors.append(f"source pack is not a directory: {source_pack}")
    for label, path in (("Courseware Skill", courseware_skill), ("Practice Skill", practice_skill)):
        if not path.is_dir():
            errors.append(f"{label} is not a directory: {path}")
    for label, path in (("courseware contract", courseware_json), ("practice contract", practice_json), ("generation decision", decision_json)):
        errors.extend(_check_input_path(path, label, extra_forbidden))
        errors.extend(_check_input_content(path, label, extra_forbidden))
    generator_repo = getattr(args, "generator_repo", None)
    generator_commit = getattr(args, "generator_commit", None)
    git_evidence: dict[str, Any] = {"status": "not-required", "dirty_worktree": None, "errors": []}
    if third_pass:
        if not generator_repo:
            errors.append("third-pass requires --generator-repo")
        if not generator_commit:
            errors.append("third-pass requires --generator-commit")
        if generator_repo and generator_commit:
            git_evidence = _git_provenance(Path(generator_repo), str(generator_commit))
            errors.extend(git_evidence.get("errors", []))
    if decision_json.is_file():
        errors.extend(_decision_errors(decision_json))
        if pass_name == "fourth-pass":
            try:
                decision_value = _json_load(decision_json)
                if not decision_value.get("adaptive_planning_evidence"):
                    errors.append("fourth-pass generation decision must include adaptive_planning_evidence")
            except Exception:
                pass
    if pass_name == "fourth-pass":
        for label, path in (("courseware contract", courseware_json), ("practice contract", practice_json)):
            if path.is_file():
                try:
                    contract = _json_load(path)
                    if contract.get("integrity_version") != "1.0":
                        errors.append(f"{label} must use integrity_version 1.0 for fourth-pass generation")
                except Exception:
                    pass
    blueprint_validation = _blueprint_validation(decision_json, courseware_skill, practice_skill, required=pass_name in {"second-pass", "third-pass", "fourth-pass"}) if decision_json.is_file() else {
        "status": "not-run", "courseware": None, "practice": None, "errors": []
    }
    errors.extend(blueprint_validation.get("errors", []))
    freeze = {"status": "fail", "errors": ["source pack was not checked"]}
    if source_pack.is_dir():
        try:
            freeze = _verify_source_freeze(source_pack, args.source_freeze)
            errors.extend(freeze.get("errors", []))
        except Exception as exc:  # noqa: BLE001 - retain freeze evidence
            errors.append(f"source freeze verification failed: {exc}")
    if output.exists():
        if any(output.iterdir()):
            errors.append(f"refusing to overwrite non-empty {pass_name} output: {output}")
        else:
            output.rmdir()
    if errors:
        return 2, {
            "status": "BLIND_TEST_INVALID",
            "errors": errors,
            "pass_name": pass_name,
            "source_freeze": freeze,
            "blueprint_validation": blueprint_validation,
            "generation_method": args.generation_method,
            "provenance": git_evidence,
        }

    output.mkdir(parents=True, exist_ok=False)
    generation_started_at = _now()
    _write_json(output / "source-freeze.json", freeze)
    shutil.copytree(source_pack, output / "raw-source" / source_pack.name)
    shutil.copy2(decision_json, output / "generation-decision.json")
    input_archive = output / "agent-inputs"
    input_archive.mkdir(parents=True, exist_ok=True)
    shutil.copy2(courseware_json, input_archive / "courseware-content.json")
    shutil.copy2(practice_json, input_archive / "practice-content.json")
    provenance = {
        "generation_method": "agent-skill",
        "agent_skill_generation": True,
        "builder_generation": False,
        "pass_name": pass_name,
        "automatic_repair": auto_repair,
        "blueprint_validation": blueprint_validation,
        "courseware_skill": str(courseware_skill),
        "practice_skill": str(practice_skill),
        "source_pack": str(source_pack),
        "source_freeze_manifest": freeze.get("manifest"),
        "contract_inputs": {
            "courseware": str(courseware_json),
            "practice": str(practice_json),
        },
        "generator_commit": git_evidence.get("head") if third_pass else None,
        "dirty_worktree": git_evidence.get("dirty_worktree") if third_pass else None,
        "dirty": git_evidence.get("dirty_worktree") if third_pass else None,
        "courseware_skill_version": _manifest_scalar(courseware_skill / "manifest.yaml", "version"),
        "practice_skill_version": _manifest_scalar(practice_skill / "manifest.yaml", "version"),
        "courseware_contract_version": "1.1",
        "practice_contract_version": "1.1",
        "source_freeze_sha256": _sha256(Path(freeze["manifest"])) if freeze.get("manifest") and Path(freeze["manifest"]).is_file() else None,
        "generation_started_at": generation_started_at,
        "generation_finished_at": None,
    }
    _write_json(output / "generation-provenance.json", provenance)

    command_evidence: dict[str, Any] = {}
    stage_root = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent)))
    try:
        courseware_scripts = courseware_skill / "scripts"
        practice_scripts = practice_skill / "scripts"
        courseware_stage = stage_root / "courseware"
        practice_stage = stage_root / "practice"
        courseware_run_json = courseware_json
        practice_run_json = practice_json
        repair_evidence: dict[str, Any] = {"status": "not-run", "round_limit": 2}
        if auto_repair:
            repaired_root = stage_root / "repaired"
            repaired_courseware = repaired_root / "courseware-content.json"
            repaired_practice = repaired_root / "practice-content.json"
            repair_evidence = {"status": "fail", "round_limit": 2}
            repair_evidence["courseware"] = _run([
                sys.executable,
                str(courseware_scripts / "repair_courseware.py"),
                "--content-json", str(courseware_json),
                "--output-json", str(repaired_courseware),
                "--max-rounds", "2",
            ], courseware_skill)
            if repair_evidence["courseware"].get("status") == "pass":
                courseware_run_json = repaired_courseware
                repair_evidence["practice"] = _run([
                    sys.executable,
                    str(practice_scripts / "repair_practice.py"),
                    "--practice-json", str(practice_json),
                    "--courseware-json", str(courseware_run_json),
                    "--output-json", str(repaired_practice),
                    "--max-rounds", "2",
                ], practice_skill)
                if repair_evidence["practice"].get("status") == "pass":
                    practice_run_json = repaired_practice
            else:
                repair_evidence["practice"] = {"status": "not-run", "reason": "Courseware repair failed"}
            repair_evidence["status"] = "pass" if repair_evidence.get("courseware", {}).get("status") == "pass" and repair_evidence.get("practice", {}).get("status") == "pass" else "fail"
        command_evidence["contract_repair"] = repair_evidence
        strict_gate_ready = True
        if third_pass:
            source_truth_report = output / "source-truth" / "report.json"
            courseware_time_report = output / "time-evidence" / "courseware.json"
            practice_time_report = output / "time-evidence" / "practice.json"
            command_evidence["source_truth"] = _run([
                sys.executable,
                str(courseware_scripts / "source_truth_validator.py"),
                "--courseware-json", str(courseware_run_json),
                "--practice-json", str(practice_run_json),
                "--source-root", str(source_pack),
                "--mode", "strict",
                "--output-json", str(source_truth_report),
            ], courseware_skill)
            command_evidence["courseware_time_evidence"] = _run([
                sys.executable,
                str(courseware_scripts / "activity_time_reviewer.py"),
                "--content-json", str(courseware_run_json),
                "--mode", "strict",
                "--output-json", str(courseware_time_report),
            ], courseware_skill)
            if command_evidence["source_truth"]["status"] == "pass" and command_evidence["courseware_time_evidence"]["status"] == "pass":
                command_evidence["practice_time_evidence"] = _run([
                    sys.executable,
                    str(practice_scripts / "practice_time_reviewer.py"),
                    "--practice-json", str(practice_run_json),
                    "--mode", "strict",
                    "--output-json", str(practice_time_report),
                ], practice_skill)
            else:
                command_evidence["practice_time_evidence"] = {"status": "not-run", "reason": "Courseware Source Truth or TIME_EVIDENCE gate failed; Practice NOT_RUN"}
            strict_gate_ready = all(command_evidence[key].get("status") in {"pass", "DEGRADED"} for key in ("source_truth", "courseware_time_evidence", "practice_time_evidence"))
        if not strict_gate_ready:
            command_evidence["courseware_render"] = {"status": "not-run", "reason": "strict Source Truth/Time Evidence gate failed; render blocked"}
        else:
            render_command = [
                sys.executable,
                str(courseware_scripts / "render_courseware.py"),
                "--content-json", str(courseware_run_json),
                "--output-dir", str(courseware_stage),
                "--replace", "--json",
            ]
            if third_pass:
                render_command.extend(["--source-root", str(source_pack), "--evidence-mode", "strict"])
            command_evidence["courseware_render"] = _run(render_command, courseware_skill)
        if command_evidence["courseware_render"]["status"] == "pass":
            _copy_tree(courseware_stage, output / "courseware")
            shutil.copy2(courseware_run_json, output / "courseware" / "courseware-content.json")
            shutil.copy2(courseware_run_json, output / "courseware" / "contract.json")
            shutil.copy2(courseware_json, output / "courseware" / "agent-contract.json")
            command_evidence["courseware_validate"] = _run([
                sys.executable,
                str(courseware_scripts / "validate_courseware.py"),
                "--content-json", str(courseware_run_json),
                "--student-html", str(output / "courseware" / "student.html"),
                "--teacher-html", str(output / "courseware" / "teacher.html"),
                "--json",
            ], courseware_skill)
        else:
            command_evidence["courseware_validate"] = {"status": "not-run", "reason": "Courseware render failed"}

        if command_evidence["courseware_render"]["status"] == "pass":
            practice_render_command = [
                sys.executable,
                str(practice_scripts / "render_practice.py"),
                "--practice-json", str(practice_run_json),
                "--courseware-json", str(courseware_run_json),
                "--output-dir", str(practice_stage),
                "--replace", "--json",
            ]
            if third_pass:
                practice_render_command.extend(["--source-root", str(source_pack), "--evidence-mode", "strict"])
            command_evidence["practice_render"] = _run(practice_render_command, practice_skill)
            if command_evidence["practice_render"]["status"] == "pass":
                _copy_tree(practice_stage, output / "practice")
                shutil.copy2(practice_json, output / "practice" / "practice-content-input.json")
                shutil.copy2(practice_json, output / "practice" / "agent-contract.json")
                command_evidence["practice_validate"] = _run([
                    sys.executable,
                    str(practice_scripts / "validate_practice.py"),
                    "--practice-json", str(output / "practice" / "practice-content.json") if pass_name == "fourth-pass" else str(practice_run_json),
                    "--courseware-json", str(courseware_run_json),
                    "--output-dir", str(output / "practice"),
                    "--json",
                ], practice_skill)
            else:
                command_evidence["practice_validate"] = {"status": "not-run", "reason": "Practice render failed"}
        else:
            command_evidence["practice_render"] = {"status": "not-run", "reason": "Courseware render failed"}
            command_evidence["practice_validate"] = {"status": "not-run", "reason": "Courseware render failed"}

        if args.browser_smoke and (output / "courseware" / "student.html").is_file() and (output / "practice").is_dir():
            courseware_smoke = courseware_scripts.parent / "tests" / "browser_smoke.mjs"
            practice_smoke = practice_scripts.parent / "tests" / "browser_smoke.mjs"
            courseware_browser = _run(["node", str(courseware_smoke), str(output / "courseware" / "student.html")], courseware_skill)
            practice_browser = _run(["node", str(practice_smoke), str(output / "practice")], practice_skill)
            command_evidence["browser_smoke"] = {
                "status": "pass" if courseware_browser["status"] == "pass" and practice_browser["status"] == "pass" else "fail",
                "courseware": courseware_browser,
                "practice": practice_browser,
            }
        else:
            command_evidence["browser_smoke"] = {"status": "fail", "reason": "browser smoke was not run or required outputs are missing"}

        _write_json(output / "evidence" / "commands.json", command_evidence)
        successful = all(
            command_evidence.get(key, {}).get("status") == "pass"
            for key in ("courseware_render", "courseware_validate", "practice_render", "practice_validate", "browser_smoke")
        )
        if pass_name == "fourth-pass":
            for required_report in (
                output / "courseware" / "qa-report.json",
                output / "practice" / "qa-report.json",
                output / "practice" / "behavior-verification.json",
                output / "practice" / "asset-lineage.json",
            ):
                if not required_report.is_file():
                    successful = False
            if (output / "courseware" / "qa-report.json").is_file() and (output / "practice" / "qa-report.json").is_file():
                try:
                    courseware_qa = _json_load(output / "courseware" / "qa-report.json")
                    practice_qa = _json_load(output / "practice" / "qa-report.json")
                    successful = successful and courseware_qa.get("status") == "pass" and practice_qa.get("status") == "pass"
                except (OSError, ValueError):
                    successful = False
        status = "pass" if successful else "fail"
        provenance["generation_finished_at"] = _now()
        provenance["source_truth_status"] = command_evidence.get("source_truth", {"status": "not-run"}).get("status")
        provenance["time_evidence_status"] = command_evidence.get("courseware_time_evidence", {"status": "not-run"}).get("status")
        _write_json(output / "generation-provenance.json", provenance)
        report = {
            "status": status,
            "holdout_id": freeze.get("holdout_id"),
            "generation_method": "agent-skill",
            "agent_skill_generation": True,
            "pass_name": pass_name,
            "first_pass": pass_name == "first-pass",
            "second_pass": pass_name == "second-pass",
            "third_pass": third_pass,
            "automatic_repair": auto_repair,
            "blueprint_validation": blueprint_validation,
            "source_freeze": freeze,
            "courseware_skill": str(courseware_skill),
            "practice_skill": str(practice_skill),
            "courseware_contract": str(output / "courseware" / "courseware-content.json"),
            "practice_contract": str(output / "practice" / "practice-content.json"),
            "commands": command_evidence,
            "known_findings": [],
            "repair": repair_evidence,
            "provenance": provenance,
        }
        _write_json(output / "run-report.json", report)
        output_freeze = _freeze_output(output, "frozen-after-generation" if status == "pass" else "frozen-after-generation-attempt")
        report["output_freeze"] = {"path": str(output / "output-freeze.json"), "file_count": len(output_freeze["files"])}
        return (0 if status == "pass" else 1), report
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pack", required=True, type=Path)
    parser.add_argument("--courseware-skill", required=True, type=Path)
    parser.add_argument("--practice-skill", required=True, type=Path)
    parser.add_argument("--courseware-json", required=True, type=Path)
    parser.add_argument("--practice-json", required=True, type=Path)
    parser.add_argument("--generation-decision", required=True, type=Path)
    parser.add_argument("--generation-method", required=True, choices=("agent-skill", "builder"))
    parser.add_argument("--source-freeze", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pass-name", choices=("first-pass", "second-pass", "third-pass", "fourth-pass"), default="first-pass")
    parser.add_argument("--generator-repo", type=Path, help="repository to verify for a clean third-pass generator")
    parser.add_argument("--generator-commit", help="exact committed generator SHA required for third-pass")
    parser.add_argument("--auto-repair", action="store_true", help="run the Skill-provided repair helpers for at most two rounds")
    parser.add_argument("--browser-smoke", action="store_true")
    args = parser.parse_args(argv)
    try:
        code, report = run(args)
    except Exception as exc:  # noqa: BLE001 - preserve a machine-readable invalid result
        code, report = 2, {"status": "BLIND_TEST_INVALID", "errors": [str(exc)], "generation_method": args.generation_method}
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
