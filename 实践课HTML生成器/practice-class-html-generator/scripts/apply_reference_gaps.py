"""Build and verify teacher/reference versions from student starter gaps.

The student contract keeps only an editable marker and a student-facing
instruction.  The replacement belongs to the teacher/QA side.  This module
applies each gap deterministically and reports whether the resulting artifact
can be parsed, compiled, or executed with a locally available toolchain.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def apply_asset_gaps(asset: dict[str, Any]) -> tuple[str, list[str]]:
    """Return the completed reference content and deterministic gap errors."""

    content = _text(asset.get("content"))
    errors: list[str] = []
    gaps = asset.get("editable_gaps", [])
    if gaps is None:
        return content, errors
    if not isinstance(gaps, list):
        return content, ["editable_gaps must be a list"]
    for index, gap in enumerate(gaps):
        location = f"editable_gaps[{index}]"
        if not isinstance(gap, dict):
            errors.append(f"{location} must be an object")
            continue
        target = gap.get("target") or gap.get("marker")
        replacement = gap.get("replacement")
        if not isinstance(target, str) or not target:
            errors.append(f"{location}.target or marker must be a non-empty string")
            continue
        if not isinstance(replacement, str) or not replacement:
            errors.append(f"{location}.replacement must be a non-empty string")
            continue
        count = content.count(target)
        if count != 1:
            errors.append(f"{location}.target occurs {count} times in the current reference source")
            continue
        content = content.replace(target, replacement, 1)
    return content, errors


def _run(command: list[str], *, timeout: int = 20) -> dict[str, Any]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return {"status": "skip", "reason": f"tool not found: {command[0]}", "command": command}
    except subprocess.TimeoutExpired:
        return {"status": "fail", "reason": f"timed out after {timeout}s", "command": command}
    return {
        "status": "pass" if result.returncode == 0 else "fail",
        "returncode": result.returncode,
        "command": command,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
    }


def verify_reference_asset(asset: dict[str, Any], reference_content: str, work_dir: Path) -> dict[str, Any]:
    """Verify one completed reference artifact without requiring every toolchain."""

    path = Path(str(asset.get("path", "reference.txt")))
    source = work_dir / path.name
    source.write_text(reference_content, encoding="utf-8", newline="\n")
    suffix = path.suffix.casefold()
    if suffix in {".drawio", ".xml"}:
        try:
            ET.fromstring(reference_content)
        except ET.ParseError as exc:
            return {"status": "fail", "kind": "parse", "reason": str(exc)}
        return {"status": "pass", "kind": "parse", "reason": "XML parsed"}
    if suffix in {".c", ".cpp", ".cc", ".cxx"}:
        compiler_names = ["gcc", "clang"] if suffix == ".c" else ["g++", "clang++"]
        compiler = next((shutil.which(name) for name in compiler_names if shutil.which(name)), None)
        if not compiler:
            return {"status": "skip", "kind": "compile", "reason": f"no compiler available ({', '.join(compiler_names)})"}
        executable = work_dir / ("reference.exe" if sys.platform.startswith("win") else "reference.out")
        compile_report = _run([compiler, str(source), "-o", str(executable)])
        compile_report["kind"] = "compile"
        if compile_report["status"] != "pass":
            return compile_report
        run_report = _run([str(executable)], timeout=10)
        run_report["kind"] = "execute"
        return {"status": run_report["status"], "kind": "compile-and-execute", "compile": compile_report, "execute": run_report}
    if suffix == ".py":
        compile_report = _run([sys.executable, "-m", "py_compile", str(source)])
        compile_report["kind"] = "compile"
        return compile_report
    if suffix in {".sql"}:
        client = shutil.which("mysql") or shutil.which("psql") or shutil.which("sqlite3")
        if not client:
            return {"status": "skip", "kind": "execute", "reason": "no local SQL client configured; dialect-specific execution was not guessed"}
        return {"status": "skip", "kind": "execute", "reason": f"SQL client {Path(client).name} detected but no connection/database was supplied"}
    if suffix in {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}:
        return {"status": "pass", "kind": "artifact", "reason": "reference artifact emitted"}
    return {"status": "skip", "kind": "artifact", "reason": f"no verifier registered for {suffix or 'extensionless artifact'}"}


def build_reference_report(content: dict[str, Any], *, output_dir: Path | None = None) -> dict[str, Any]:
    """Apply all gaps, optionally write teacher reference assets, and verify them."""

    assets = content.get("starter_assets", []) if isinstance(content, dict) else []
    if not isinstance(assets, list):
        return {"status": "fail", "errors": ["starter_assets must be a list"], "warnings": [], "assets": []}
    reports: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="practice-reference-") as temp:
        work_dir = Path(temp)
        for asset in assets:
            if not isinstance(asset, dict) or not asset.get("editable_gaps"):
                continue
            completed, apply_errors = apply_asset_gaps(asset)
            asset_id = str(asset.get("id", "asset"))
            report: dict[str, Any] = {"asset_id": asset_id, "path": asset.get("path"), "gap_count": len(asset.get("editable_gaps", [])), "errors": apply_errors}
            errors.extend(f"{asset_id}: {item}" for item in apply_errors)
            if not apply_errors:
                if output_dir is not None:
                    target = output_dir / "reference" / Path(str(asset.get("path", f"{asset_id}.txt")))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(completed, encoding="utf-8", newline="\n")
                    report["reference_path"] = str(target)
                verification = verify_reference_asset(asset, completed, work_dir)
                report["verification"] = verification
                if verification.get("status") == "fail":
                    errors.append(f"{asset_id}: reference verification failed")
                elif verification.get("status") == "skip":
                    warnings.append(f"{asset_id}: {verification.get('reason', 'verification skipped')}")
            reports.append(report)
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "assets": reports}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-json", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    content = json.loads(args.practice_json.read_text(encoding="utf-8"))
    report = build_reference_report(content, output_dir=args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
