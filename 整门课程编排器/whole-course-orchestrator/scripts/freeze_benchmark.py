"""Create a manifest-only freeze of an existing whole-course failure benchmark."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator_core import dump_json, sha256_file


def _file_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "relative_path": path.resolve().relative_to(root.resolve()).as_posix() if path.resolve().is_relative_to(root.resolve()) else path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _records(root: Path, pattern: str) -> list[dict[str, Any]]:
    return [_file_record(path, root) for path in sorted(root.glob(pattern)) if path.is_file()]


def freeze(source_dir: Path, build_dir: Path, output: Path) -> dict[str, Any]:
    source_dir = source_dir.resolve()
    build_dir = build_dir.resolve()
    raw_sources = sorted(path for path in source_dir.glob("*.ppt") if path.is_file())
    source_manifest_path = build_dir / "source_manifest.json"
    sessions_path = build_dir / "sessions.json"
    expected_source_manifest = None
    if source_manifest_path.is_file():
        import json

        expected_source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    derived_sources = expected_source_manifest.get("files", []) if expected_source_manifest else []

    artifact_sets = {
        "source_manifest": _records(build_dir, "source_manifest.json"),
        "sessions": _records(build_dir, "sessions.json"),
        "courseware_contracts": _records(build_dir, "contracts/session-*/courseware.json"),
        "practice_contracts": _records(build_dir, "contracts/session-*/practice.json"),
        "courseware_rendered": _records(build_dir, "rendered/courseware/session-*/*"),
        "practice_rendered": _records(build_dir, "rendered/practice/session-*/**/*"),
        "qa_reports": _records(build_dir, "qa_contracts/*.json"),
        "audit_reports": _records(build_dir, "*.md"),
    }
    missing_required = [
        name for name, records in artifact_sets.items()
        if name in {"source_manifest", "sessions", "courseware_contracts", "practice_contracts", "courseware_rendered", "practice_rendered", "qa_reports"} and not records
    ]
    benchmark = {
        "benchmark_id": "WHOLE_COURSE_FAILURE_BENCHMARK_V1",
        "freeze_schema_version": "1.0",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "freeze_mode": "manifest-only-external-artifacts",
        "availability": "complete" if not missing_required and len(raw_sources) == 9 else "incomplete",
        "source_root": str(source_dir),
        "build_root": str(build_dir),
        "source_files": [
            _file_record(path, source_dir)
            for path in raw_sources
        ],
        "converted_source_evidence": [
            {
                "source_id": item.get("source_id"),
                "pptx_file": item.get("pptx_file"),
                "pptx_sha256": item.get("pptx_sha256"),
                "slide_count": item.get("slide_count"),
            }
            for item in derived_sources
        ],
        "course_shape": {
            "course": "软件建模与设计",
            "source_ppt_count": 9,
            "source_slide_count": 1035,
            "theory_session_count": 16,
            "practice_session_count": 16,
            "theory_minutes_per_session": 120,
            "practice_minutes_per_session": 120,
            "courseware_contract_version": "1.1",
            "practice_contract_version": "1.1",
        },
        "generator_evidence": {
            "courseware_skill": "1.2.1",
            "practice_skill": "1.2.0",
            "note": "Versions are recorded from the release baseline used by the benchmark; this freeze does not upgrade or rerun either renderer.",
        },
        "failure_findings": {
            "status": "FAIL",
            "theory": {
                "all_sessions_slide_count": 8,
                "layout_sequence": ["hero", "split", "grid", "timeline", "focus", "comparison", "focus", "default"],
                "lecture_minutes": 61,
                "activity_minutes": 59,
                "blocks_per_session": 17,
                "svg_count_per_session": 2,
                "finding_codes": ["WHOLE_COURSE_TEMPLATE_COLLAPSE", "SCRIPT_CROSS_SESSION_TEMPLATE_REUSE"],
            },
            "practice": {
                "task_count_per_session": 2,
                "task_shape": ["core/modeling/60", "optional/analysis/60"],
                "step_sequence": ["read_prompt", "model", "review", "choose_scenario", "find_evidence", "raise_risk"],
                "finding_codes": ["WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE"],
            },
        },
        "artifact_sets": artifact_sets,
        "missing_required_sets": missing_required,
        "preservation_rule": "This manifest freezes external evidence by path and digest. The source and generated artifacts must not be overwritten by the architecture implementation.",
        "blind_retry_rule": "Before a later benchmark retry, read only this formal Skill, the original source files and user course requirements; do not reuse old contracts, old HTML or per-session repair advice.",
    }
    dump_json(benchmark, output)
    return benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    if not args.source_dir.is_dir():
        parser.error(f"source directory does not exist: {args.source_dir}")
    if not args.build_dir.is_dir():
        parser.error(f"build directory does not exist: {args.build_dir}")
    result = freeze(args.source_dir, args.build_dir, args.output_json)
    print({"benchmark_id": result["benchmark_id"], "availability": result["availability"], "source_files": len(result["source_files"])})


if __name__ == "__main__":
    main()
