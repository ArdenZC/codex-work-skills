"""Optional local PDF rendering for generated lesson plans."""

from __future__ import annotations

import subprocess
import tempfile
import re
import shutil
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


def pdf_page_count(path: Path | str) -> int:
    """Count page objects in a retained PDF without adding a heavyweight dependency."""

    payload = Path(path).read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?:\s|/|>)", payload))


# Keep the private name available for compatibility with older callers while
# exposing the same implementation to the final-artifact manifest verifier.
_pdf_page_count = pdf_page_count


def render_docx_directory(
    output_dir: Path | str,
    *,
    timeout: int = 180,
    pdf_output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Render every DOCX and optionally retain PDFs for auditable manifests."""

    directory = Path(output_dir).expanduser().resolve()
    retained_pdf_dir = Path(pdf_output_dir).expanduser().resolve() if pdf_output_dir else None
    if retained_pdf_dir is not None:
        retained_pdf_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(directory.glob("*.docx"))
    symlink_files = [path for path in files if path.is_symlink()]
    renderer = find_renderer()
    if renderer is None:
        if symlink_files:
            errors = [f"{path.name}: DOCX symbolic links are not rendered or opened" for path in symlink_files]
            return {
                "status": "failed",
                "reason": "LibreOffice render smoke failed",
                "scope": "smoke",
                "renderer": None,
                "files_checked": len(files),
                "page_count": 0,
                "page_counts": {},
                "page_count_method": "pdf_page_object_regex",
                "errors": errors,
            }
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
    errors.extend(f"{path.name}: DOCX symbolic links are not rendered or opened" for path in symlink_files)
    page_counts: dict[str, int] = {}
    pdf_files: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="lesson-render-") as temp_name:
        render_dir = Path(temp_name)
        profile_dir = render_dir / "profile"
        profile_dir.mkdir()
        for path in files:
            if path.is_symlink():
                continue
            try:
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
            except subprocess.TimeoutExpired:
                errors.append(f"{path.name}: renderer timed out after {timeout}s")
                continue
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
                    elif retained_pdf_dir is not None:
                        retained = retained_pdf_dir / pdf.name
                        try:
                            shutil.copy2(pdf, retained)
                        except OSError as exc:
                            errors.append(f"{path.name}: retained PDF could not be copied: {exc}")
                        else:
                            pdf_files[path.name] = str(retained)

    return {
        "status": "failed" if errors else "passed",
        "reason": "LibreOffice render smoke passed" if not errors else "LibreOffice render smoke failed",
        "scope": "smoke",
        "renderer": renderer,
        "files_checked": len(files),
        "page_count": sum(page_counts.values()),
        "page_counts": page_counts,
        "page_count_method": "pdf_page_object_regex",
        "pdf_files": pdf_files,
        "errors": errors,
    }
