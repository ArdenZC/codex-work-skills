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

    available = {path.name for path in directory.glob("*.docx")}
    missing = sorted(set(inspected_pages) - available)
    if missing:
        raise ValueError(f"inspected DOCX files do not exist in output: {', '.join(missing)}")
    evidence = {
        "status": status,
        "inspected_files": sorted(inspected_pages),
        "inspected_pages": {name: sorted(set(pages)) for name, pages in sorted(inspected_pages.items())},
        "checks": {name: checks[name] for name in CHECK_NAMES},
        "notes": str(notes).strip(),
        "related_qa_report": str(report_path),
        "output_fingerprint": output_fingerprint(directory, report_path),
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
