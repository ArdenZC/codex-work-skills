"""Best-effort render smoke for a generated Work Order DOCX."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def render_file(path: Path, output_dir: Path, *, timeout: int = 45) -> dict[str, Any]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return {"status": "skipped", "reason": "LibreOffice/soffice is not installed", "pages": None}
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = output_dir / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"status": "fail", "reason": f"soffice timed out after {timeout}s", "pages": None}
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"status": "fail", "reason": str(exc), "pages": None}
    pdf = pdf_dir / f"{path.stem}.pdf"
    if not pdf.is_file():
        return {"status": "fail", "reason": "soffice did not produce a PDF", "pages": None}
    page_count = None
    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        try:
            subprocess.run(
                [pdftoppm, "-png", str(pdf), str(output_dir / "page")],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            page_count = len(list(output_dir.glob("page-*.png")))
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return {"status": "fail", "reason": f"page rasterization failed: {exc}", "pages": None}
    return {"status": "pass", "reason": "render smoke completed", "pages": page_count, "pdf": str(pdf)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = render_file(args.input, args.output_dir, timeout=args.timeout)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report["status"])
    return 0 if report["status"] in {"pass", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
