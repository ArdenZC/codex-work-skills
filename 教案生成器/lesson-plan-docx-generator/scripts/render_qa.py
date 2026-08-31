"""Optional local PDF rendering for generated lesson plans."""

from __future__ import annotations

import subprocess
import tempfile
import re
from pathlib import Path
from shutil import which
from typing import Any


def find_renderer() -> str | None:
    candidates = (
        which("soffice"),
        which("soffice.com"),
        which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    )
    return next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)


def _pdf_page_count(path: Path) -> int:
    """Count page objects without adding a heavyweight PDF dependency."""

    payload = path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?:\s|/|>)", payload))


def render_docx_directory(output_dir: Path | str, *, timeout: int = 180) -> dict[str, Any]:
    """Render every DOCX to a disposable PDF and report only render evidence."""

    directory = Path(output_dir).expanduser().resolve()
    files = sorted(directory.glob("*.docx"))
    renderer = find_renderer()
    if renderer is None:
        return {
            "status": "not_executed",
            "reason": "LibreOffice render smoke not executed: LibreOffice/soffice was not found",
            "scope": "smoke",
            "renderer": None,
            "files_checked": 0,
            "page_count": 0,
            "page_counts": {},
            "page_count_method": "pdf_page_object_regex",
            "errors": [],
        }
    if not files:
        return {
            "status": "failed",
            "reason": "LibreOffice render smoke failed: no DOCX files were available for rendering",
            "scope": "smoke",
            "renderer": renderer,
            "files_checked": 0,
            "page_count": 0,
            "page_counts": {},
            "page_count_method": "pdf_page_object_regex",
            "errors": ["no DOCX files were available for rendering"],
        }

    errors: list[str] = []
    page_counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="lesson-render-") as temp_name:
        render_dir = Path(temp_name)
        profile_dir = render_dir / "profile"
        profile_dir.mkdir()
        for path in files:
            result = subprocess.run(
                [
                    renderer,
                    "--headless",
                    f"-env:UserInstallation={profile_dir.as_uri()}",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(render_dir),
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            pdf = render_dir / f"{path.stem}.pdf"
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip().replace("\n", " ")
                errors.append(f"{path.name}: renderer exit {result.returncode}: {detail[:240]}")
            elif not pdf.is_file() or pdf.stat().st_size == 0:
                errors.append(f"{path.name}: renderer did not create a non-empty PDF")
            else:
                try:
                    page_count = _pdf_page_count(pdf)
                except OSError as exc:
                    errors.append(f"{path.name}: PDF page count could not be read: {exc}")
                else:
                    page_counts[path.name] = page_count
                    if page_count <= 0:
                        errors.append(f"{path.name}: rendered PDF contains no pages")

    return {
        "status": "failed" if errors else "passed",
        "reason": "LibreOffice render smoke passed" if not errors else "LibreOffice render smoke failed",
        "scope": "smoke",
        "renderer": renderer,
        "files_checked": len(files),
        "page_count": sum(page_counts.values()),
        "page_counts": page_counts,
        "page_count_method": "pdf_page_object_regex",
        "errors": errors,
    }
