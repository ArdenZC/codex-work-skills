"""Persist explicit Agent visual-inspection evidence for generated lesson plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from path_safety import paths_equal, paths_overlap


CHECK_NAMES = (
    "clipping",
    "overflow",
    "overlap",
    "blank_pages",
    "abnormal_page_break",
    "large_blank_block",
    "missing_text",
    "text_outside_table",
    "abnormal_row_height",
    "table_boundary",
    "broken_nested_evaluation_table",
)


def output_fingerprint(output_dir: Path | str, qa_report: Path | str) -> str:
    directory = Path(output_dir).expanduser().resolve()
    report = Path(qa_report).expanduser().resolve()
    digest = hashlib.sha256()
    files = sorted(directory.glob("*.docx"), key=lambda item: item.name.casefold())
    if not files:
        raise ValueError("visual inspection evidence requires at least one generated DOCX")
    if any(path.is_symlink() for path in files):
        raise ValueError("visual inspection does not accept symbolic-link DOCX files")
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    if not report.is_file():
        raise ValueError(f"related qa-report.json does not exist: {report}")
    digest.update(report.name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(hashlib.sha256(report.read_bytes()).digest())
    return digest.hexdigest()


def _parse_inspection(value: str) -> tuple[str, list[int]]:
    filename, separator, pages_text = value.partition("=")
    filename = filename.strip()
    if not separator or not filename:
        raise ValueError("--inspect must use FILE.docx=PAGE[,PAGE...] format")
    try:
        pages = sorted({int(item.strip()) for item in pages_text.split(",") if item.strip()})
    except ValueError:
        raise ValueError(f"invalid inspected page list: {value}") from None
    if not pages or any(page <= 0 for page in pages):
        raise ValueError(f"inspected pages must be positive integers: {value}")
    return filename, pages


def _assert_destination_safe(directory: Path, report_path: Path, destination_path: Path) -> None:
    """Reject evidence writes that could overwrite source or protected package files."""

    if destination_path.exists() and destination_path.is_dir():
        raise ValueError(f"visual inspection destination must be a file, not a directory: {destination_path}")

    skill_root = Path(__file__).resolve().parents[1]
    protected_files = [report_path, directory / "qa-report.json", *directory.glob("*.docx")]
    if paths_overlap(destination_path, skill_root):
        raise ValueError(
            f"visual inspection destination must not overlap the protected Skill path: {skill_root}"
        )
    for protected in protected_files:
        if paths_equal(destination_path, protected):
            raise ValueError(f"visual inspection destination must not overwrite protected path: {protected}")


def write_visual_inspection_evidence(
    *,
    output_dir: Path | str,
    qa_report: Path | str,
    destination: Path | str,
    status: str,
    inspected_pages: dict[str, list[int]],
    checks: dict[str, str],
    notes: str,
) -> dict[str, Any]:
    directory = Path(output_dir).expanduser().resolve()
    report_path = Path(qa_report).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    _assert_destination_safe(directory, report_path, destination_path)
    if not report_path.is_file():
        raise ValueError(f"related qa-report.json does not exist: {report_path}")
    try:
        qa_data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"qa-report.json is not valid JSON: {report_path}") from exc
    if not isinstance(qa_data, dict):
        raise ValueError("qa-report.json must contain an object")
    qa_status = str(qa_data.get("status", ""))
    if "output_dir" in qa_data and not paths_equal(qa_data["output_dir"], directory):
        raise ValueError("qa-report output_dir does not match the visual inspection output directory")
    if status == "passed" and qa_status != "passed":
        raise ValueError("passed visual inspection requires a passed QA report")
    validation = qa_data.get("validation", {})
    if status == "passed" and isinstance(validation, dict) and validation.get("output") is False:
        raise ValueError("passed visual inspection requires output validation")
    if status not in {"passed", "failed"}:
        raise ValueError("visual inspection status must be passed or failed")
    if set(checks) != set(CHECK_NAMES) or any(value not in {"passed", "failed"} for value in checks.values()):
        raise ValueError(f"checks must explicitly record passed/failed for: {', '.join(CHECK_NAMES)}")
    if status == "passed" and any(value != "passed" for value in checks.values()):
        raise ValueError("passed visual inspection requires every recorded check to pass")
    if status == "failed" and all(value == "passed" for value in checks.values()):
        raise ValueError("failed visual inspection must identify at least one failed check")
    if not inspected_pages:
        raise ValueError("visual inspection evidence requires inspected files and representative pages")

    available = {path.name for path in directory.glob("*.docx") if path.is_file() and not path.is_symlink()}
    missing = sorted(set(inspected_pages) - available)
    if missing:
        raise ValueError(f"inspected DOCX files do not exist in output: {', '.join(missing)}")
    page_counts = qa_data.get("render", {}).get("page_counts")
    page_bounds_verified = isinstance(page_counts, dict) and bool(page_counts)
    if page_bounds_verified:
        for name, pages in inspected_pages.items():
            maximum = page_counts.get(name)
            if not isinstance(maximum, int) or maximum <= 0 or any(page > maximum for page in pages):
                raise ValueError(f"inspected page is outside render.page_counts for {name}")
    evidence = {
        "status": status,
        "inspected_files": sorted(inspected_pages),
        "inspected_pages": {name: sorted(set(pages)) for name, pages in sorted(inspected_pages.items())},
        "checks": {name: checks[name] for name in CHECK_NAMES},
        "notes": str(notes).strip(),
        "related_qa_report": str(report_path),
        "output_fingerprint": output_fingerprint(directory, report_path),
        "qa_status": qa_status,
        "page_bounds_verified": page_bounds_verified,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.", suffix=".tmp", dir=str(destination_path.parent)
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(evidence, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, destination_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record durable visual evidence only after an Agent has inspected rendered pages"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--qa-report", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status", required=True, choices=("passed", "failed"))
    parser.add_argument("--inspect", action="append", default=[], metavar="FILE.docx=PAGE[,PAGE...]")
    for name in CHECK_NAMES:
        parser.add_argument(f"--{name.replace('_', '-')}", required=True, choices=("passed", "failed"))
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    inspected_pages = dict(_parse_inspection(value) for value in args.inspect)
    checks = {name: getattr(args, name) for name in CHECK_NAMES}
    destination = args.output or (args.output_dir / "visual-inspection.json")
    evidence = write_visual_inspection_evidence(
        output_dir=args.output_dir,
        qa_report=args.qa_report,
        destination=destination,
        status=args.status,
        inspected_pages=inspected_pages,
        checks=checks,
        notes=args.notes,
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
