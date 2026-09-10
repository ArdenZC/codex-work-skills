"""Build visual review surfaces from final Courseware/Practice artifacts."""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from orchestrator_core import dump_json, html_page, load_json, safe_filename, slug


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pages: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("data-page-id"):
            self.current = {"id": values["data-page-id"], "title": "", "text": [], "html": ""}
            self.pages.append(self.current)
        if self.current and tag in {"h1", "h2", "h3"}:
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3"}:
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if not self.current or not data.strip():
            return
        text = data.strip()
        self.current["text"].append(text)
        if self.in_title and not self.current["title"]:
            self.current["title"] = text


def _parse_pages(path: Path) -> list[dict[str, Any]]:
    parser = _PageParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    if not parser.pages:
        return [{"id": path.stem, "title": path.stem, "text": [path.stem]}]
    return parser.pages


def _svg_thumbnail(title: str, text: str, target: Path, *, kind: str = "courseware") -> None:
    safe_title = html.escape(title[:120])
    lines = [html.escape(line[:110]) for line in re.split(r"\s+", text) if line][:8]
    text_nodes = "".join(f'<text x="36" y="{86 + index * 28}" font-size="16" fill="#31465b">{line}</text>' for index, line in enumerate(lines))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 420" role="img" aria-label="{safe_title}"><rect width="720" height="420" rx="18" fill="#f5f8fa"/><rect width="720" height="66" rx="18" fill="#dbe8eb"/><text x="36" y="42" font-size="24" font-weight="700" fill="#26384a">{safe_title}</text><rect x="36" y="90" width="648" height="274" rx="12" fill="#ffffff" stroke="#b9cbd4"/><text x="36" y="392" font-size="13" fill="#6a7c8a">{html.escape(kind)} · thumbnail derived from final artifact DOM</text>{text_nodes}</svg>', encoding="utf-8", newline="\n")


def _try_playwright(path: Path, page_ids: list[str], output_dir: Path, prefix: str) -> tuple[list[Path], str]:
    """Use an already-installed Playwright runtime when available.

    No browser is downloaded here. If the runtime/browser is unavailable the
    caller records a degraded, inspectable SVG fallback instead of claiming a
    browser screenshot.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return [], "playwright-unavailable"
    outputs: list[Path] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(path.resolve().as_uri(), wait_until="load")
            locator = page.locator("[data-page-id]")
            count = locator.count()
            for index, page_id in enumerate(page_ids):
                if index >= count:
                    break
                target = output_dir / f"{prefix}-{slug(page_id)}.png"
                locator.nth(index).screenshot(path=str(target))
                outputs.append(target)
            browser.close()
    except Exception as exc:  # pragma: no cover - host-dependent browser state
        return [], f"playwright-failed:{type(exc).__name__}"
    return outputs, "playwright"


def _drawio_thumbnail(path: Path, target: Path) -> None:
    try:
        root = ET.fromstring(path.read_bytes())
        labels = [str(node.attrib.get("value") or node.attrib.get("id") or "") for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "mxCell" and (node.attrib.get("value") or node.attrib.get("id"))]
    except (OSError, ET.ParseError):
        labels = ["draw.io artifact could not be parsed"]
    _svg_thumbnail(path.name, " ".join(labels), target, kind="drawio starter")


def _starter_thumbnail(starter_dir: Path, target_dir: Path, stem: str) -> Path | None:
    files = [path for path in starter_dir.rglob("*") if path.is_file()]
    if not files:
        return None
    chosen = next((path for path in files if path.suffix.lower() in {".drawio", ".xml"}), files[0])
    target = target_dir / f"{stem}-{slug(chosen.name)}.svg"
    if chosen.suffix.lower() in {".drawio", ".xml"}:
        _drawio_thumbnail(chosen, target)
    else:
        _svg_thumbnail(chosen.name, chosen.read_text(encoding="utf-8", errors="ignore")[:1000], target, kind="starter preview")
    return target


def build_contact_sheets(
    theory_outputs: list[dict[str, Any]] | None,
    practice_outputs: list[dict[str, Any]] | None,
    output_dir: str | Path,
    *,
    visual_plans: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
    use_browser: bool = True,
) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    thumbs = root / "thumbnails"
    thumbs.mkdir(parents=True, exist_ok=True)
    theory_outputs = theory_outputs or []
    practice_outputs = practice_outputs or []
    course_rows: list[str] = []
    thumbnail_paths: list[Path] = []
    browser_methods: list[str] = []
    for index, item in enumerate(theory_outputs, start=1):
        student_html = Path(str(item.get("student_html") or item.get("student") or "")).expanduser().resolve()
        if not student_html.is_file():
            continue
        pages = _parse_pages(student_html)
        page_ids = [str(page["id"]) for page in pages]
        browser_paths: list[Path] = []
        method = "fallback-svg"
        if use_browser:
            browser_paths, method = _try_playwright(student_html, page_ids, thumbs, f"session-{index:02d}")
        browser_methods.append(method)
        for page_index, page in enumerate(pages):
            target = browser_paths[page_index] if page_index < len(browser_paths) else thumbs / f"session-{index:02d}-{slug(page['id'])}.svg"
            if not target.exists():
                _svg_thumbnail(str(page.get("title") or page["id"]), " ".join(page.get("text", [])), target)
            thumbnail_paths.append(target)
            course_rows.append(f'<article class="course-card"><h3>{html.escape(str(item.get("title") or item.get("id") or f"Session {index}"))} · {html.escape(str(page.get("title") or page["id"]))}</h3><img src="{html.escape(target.relative_to(root).as_posix())}" alt="courseware thumbnail"></article>')

    visual_rows: list[str] = []
    inventory_assets = (inventory or {}).get("assets", []) if isinstance(inventory, dict) else (inventory or [])
    for asset in inventory_assets:
        ref = asset.get("rendered_visual_ref") or asset.get("image_ref")
        if not ref:
            continue
        path = Path(str(ref))
        if not path.is_absolute() and inventory and inventory.get("asset_root"):
            path = Path(str(inventory["asset_root"])) / path
        if path.is_file():
            destination = thumbs / f"visual-{slug(str(asset.get('id')))}{path.suffix or '.svg'}"
            shutil.copy2(path, destination)
            thumbnail_paths.append(destination)
            visual_rows.append(f'<article class="visual-card"><h3>{html.escape(str(asset.get("title") or asset.get("id")))}</h3><img src="{html.escape(destination.relative_to(root).as_posix())}" alt="visual evidence thumbnail"><p>{html.escape(str(asset.get("type")))}</p></article>')
    practice_rows: list[str] = []
    for index, item in enumerate(practice_outputs, start=1):
        starter_dir = Path(str(item.get("student_dir") or item.get("student_root") or "")).expanduser().resolve()
        starter = _starter_thumbnail(starter_dir, thumbs, f"practice-{index:02d}") if starter_dir.is_dir() else None
        if starter:
            thumbnail_paths.append(starter)
        tasks = item.get("tasks", []) if isinstance(item.get("tasks"), list) else []
        task_cards = []
        for task in tasks:
            image = f'<img src="{html.escape(starter.relative_to(root).as_posix())}" alt="starter thumbnail">' if starter else "<div class='missing-thumb'>starter thumbnail unavailable</div>"
            task_cards.append(f'<article class="practice-card"><h3>{html.escape(str(task.get("title") or task.get("id")))}</h3>{image}<p>{html.escape(str(task.get("capability") or task.get("modality") or ""))} · {html.escape(str(task.get("estimated_minutes") or ""))} min</p></article>')
        practice_rows.append(f'<section><h2>{html.escape(str(item.get("title") or item.get("id") or f"Practice {index}"))}</h2>{"".join(task_cards) or "<p>No task records supplied</p>"}</section>')

    def sheet(title: str, body: str) -> str:
        return html_page(title, f"<h1>{html.escape(title)}</h1><div class='sheet-grid'>{body}</div>")

    course_path = root / "course-contact-sheet.html"
    visual_path = root / "visual-gallery.html"
    practice_path = root / "practice-contact-sheet.html"
    course_path.write_text(sheet("Course contact sheet", "".join(course_rows) or "<p>No final Courseware pages were supplied.</p>"), encoding="utf-8", newline="\n")
    visual_path.write_text(sheet("Visual gallery", "".join(visual_rows) or "<p>No rendered visual files were supplied.</p>"), encoding="utf-8", newline="\n")
    practice_path.write_text(sheet("Practice contact sheet", "".join(practice_rows) or "<p>No final Practice artifacts were supplied.</p>"), encoding="utf-8", newline="\n")
    browser_ok = bool(browser_methods) and all(method == "playwright" for method in browser_methods)
    status = "PASS" if thumbnail_paths and browser_ok else "DEGRADED" if thumbnail_paths else "NOT_RUN"
    result = {
        "schema_version": "1.1",
        "report_type": "whole_course_contact_sheets",
        "status": status,
        "thumbnail_count": len(thumbnail_paths),
        "browser_methods": browser_methods,
        "files": {"course": str(course_path), "visual": str(visual_path), "practice": str(practice_path)},
        "thumbnail_paths": [str(path) for path in thumbnail_paths],
        "review_policy": "Contact sheets are a human review surface; they do not add an automated quality score.",
    }
    dump_json(result, root / "contact-sheet-evidence.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theory-json", required=True)
    parser.add_argument("--practice-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--visual-plans")
    parser.add_argument("--assets")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = build_contact_sheets(load_json(args.theory_json), load_json(args.practice_json), args.output_dir, visual_plans=load_json(args.visual_plans) if args.visual_plans else None, inventory=load_json(args.assets) if args.assets else None, use_browser=not args.no_browser)
    if args.json:
        print({"status": result["status"], "thumbnail_count": result["thumbnail_count"], "files": result["files"]})


if __name__ == "__main__":
    main()
