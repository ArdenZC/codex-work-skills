"""Build visual review surfaces from final Courseware/Practice artifacts."""

from __future__ import annotations

import argparse
import html
import json
import os
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


def _playwright_root() -> str | None:
    for key in ("WHOLE_COURSE_PLAYWRIGHT_ROOT", "PLAYWRIGHT_ROOT", "COURSEWARE_PLAYWRIGHT_ROOT", "PRACTICE_PLAYWRIGHT_ROOT"):
        value = os.environ.get(key)
        if value and Path(value).exists():
            return value
    return None


def _try_python_playwright(path: Path, page_ids: list[str], output_dir: Path, prefix: str) -> tuple[list[Path], dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return [], {"method": "playwright-unavailable", "runtime": "unavailable", "version": None, "error": "python-playwright-unavailable"}
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
                locator.nth(index).evaluate("element => { element.style.display = 'block'; element.setAttribute('aria-hidden', 'false'); }")
                locator.nth(index).screenshot(path=str(target))
                outputs.append(target)
            version = browser.version
            browser.close()
    except Exception as exc:  # pragma: no cover - host-dependent browser state
        return [], {"method": f"playwright-failed:{type(exc).__name__}", "runtime": "unavailable", "version": None, "error": str(exc)}
    return outputs, {"method": "playwright", "runtime": "Chromium/Playwright", "version": version, "error": None}


def _try_node_playwright(path: Path, page_ids: list[str], output_dir: Path, prefix: str) -> tuple[list[Path], dict[str, Any]]:
    """Use the Node Playwright install already provisioned by CI.

    The stable Courseware and Practice CI jobs install the Node package and
    Chromium.  Reusing that package keeps Whole-Course browser proof on the
    same supported setup instead of introducing a second browser framework.
    """
    root = _playwright_root()
    if not root or shutil.which("node") is None:
        return [], {"method": "playwright-unavailable", "runtime": "unavailable", "version": None, "error": "node-playwright-unavailable"}
    script = r'''
const { pathToFileURL } = require("url");
const { chromium } = require(process.env.WHOLE_COURSE_PLAYWRIGHT_ROOT);
(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1280, height: 800}});
  await page.goto(pathToFileURL(process.env.WHOLE_COURSE_INPUT).href, {waitUntil: "load"});
  const ids = JSON.parse(process.env.WHOLE_COURSE_PAGE_IDS);
  const locator = page.locator("[data-page-id]");
  const count = await locator.count();
  const outputs = [];
  for (let index = 0; index < ids.length && index < count; index += 1) {
    const target = locator.nth(index);
    await target.evaluate(element => { element.style.display = "block"; element.setAttribute("aria-hidden", "false"); });
    const output = process.env.WHOLE_COURSE_OUTPUT + "/" + process.env.WHOLE_COURSE_PREFIX + "-" + ids[index].replace(/[^A-Za-z0-9_-]+/g, "-") + ".png";
    await target.screenshot({path: output});
    outputs.push(output);
  }
  console.log(JSON.stringify({version: browser.version(), outputs}));
  await browser.close();
})().catch(error => { console.error(error && error.stack ? error.stack : String(error)); process.exit(2); });
'''
    env = os.environ.copy()
    env.update({
        "WHOLE_COURSE_PLAYWRIGHT_ROOT": root,
        "WHOLE_COURSE_INPUT": str(path.resolve()),
        "WHOLE_COURSE_OUTPUT": str(output_dir.resolve()),
        "WHOLE_COURSE_PREFIX": prefix,
        "WHOLE_COURSE_PAGE_IDS": json.dumps(page_ids),
    })
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        return [], {"method": "playwright-failed:node", "runtime": "unavailable", "version": None, "error": result.stderr.strip()[-500:]}
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return [], {"method": "playwright-failed:node-output", "runtime": "unavailable", "version": None, "error": result.stdout[-500:]}
    outputs = [Path(value) for value in payload.get("outputs", []) if Path(value).is_file()]
    return outputs, {"method": "playwright", "runtime": "Chromium/Playwright", "version": payload.get("version"), "error": None}


def _try_playwright(path: Path, page_ids: list[str], output_dir: Path, prefix: str) -> tuple[list[Path], dict[str, Any]]:
    outputs, metadata = _try_python_playwright(path, page_ids, output_dir, prefix)
    if outputs or metadata.get("method") == "playwright":
        return outputs, metadata
    node_outputs, node_metadata = _try_node_playwright(path, page_ids, output_dir, prefix)
    if node_metadata.get("method") == "playwright-unavailable" and str(metadata.get("method", "")).startswith("playwright-failed"):
        return node_outputs, metadata
    return node_outputs, node_metadata


def _try_document_screenshot(path: Path, target: Path) -> tuple[bool, dict[str, Any]]:
    """Screenshot a real HTML/SVG artifact for a Practice/visual thumbnail."""
    root = _playwright_root()
    if root and shutil.which("node"):
        script = r'''
const { pathToFileURL } = require("url");
const { chromium } = require(process.env.WHOLE_COURSE_PLAYWRIGHT_ROOT);
(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1280, height: 800}});
  await page.goto(pathToFileURL(process.env.WHOLE_COURSE_INPUT).href, {waitUntil: "load"});
  if (process.env.WHOLE_COURSE_INPUT.toLowerCase().endsWith(".svg")) {
    await page.locator("svg").first().screenshot({path: process.env.WHOLE_COURSE_OUTPUT, animations: "disabled"});
  } else {
    await page.screenshot({path: process.env.WHOLE_COURSE_OUTPUT, fullPage: true});
  }
  console.log(JSON.stringify({version: browser.version()}));
  await browser.close();
})().catch(error => { console.error(error && error.stack ? error.stack : String(error)); process.exit(2); });
'''
        env = os.environ.copy()
        env.update({"WHOLE_COURSE_PLAYWRIGHT_ROOT": root, "WHOLE_COURSE_INPUT": str(path.resolve()), "WHOLE_COURSE_OUTPUT": str(target.resolve())})
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=env, check=False)
        if result.returncode == 0 and target.is_file():
            try:
                version = json.loads(result.stdout.strip().splitlines()[-1]).get("version")
            except (json.JSONDecodeError, IndexError):
                version = None
            return True, {"method": "playwright", "runtime": "Chromium/Playwright", "version": version}
    return False, {"method": "playwright-unavailable", "runtime": "unavailable", "version": None}


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
    browser_versions: set[str] = set()
    browser_failures: list[dict[str, Any]] = []
    browser_unavailable = False
    fallback_count = 0
    screenshot_count = 0
    for index, item in enumerate(theory_outputs, start=1):
        student_html = Path(str(item.get("student_html") or item.get("student") or "")).expanduser().resolve()
        if not student_html.is_file():
            continue
        pages = _parse_pages(student_html)
        page_ids = [str(page["id"]) for page in pages]
        browser_paths: list[Path] = []
        browser_info: dict[str, Any] = {"method": "fallback-svg", "runtime": "disabled", "version": None}
        method = "fallback-svg"
        if use_browser:
            browser_paths, browser_info = _try_playwright(student_html, page_ids, thumbs, f"session-{index:02d}")
            method = str(browser_info.get("method") or "playwright-failed")
            if browser_info.get("version"):
                browser_versions.add(str(browser_info["version"]))
            if method == "playwright-unavailable":
                browser_unavailable = True
            elif method.startswith("playwright-failed") or len(browser_paths) != len(page_ids):
                browser_failures.append({"kind": "courseware", "session_id": item.get("id"), "method": method, "expected": len(page_ids), "observed": len(browser_paths), "error": browser_info.get("error")})
        browser_methods.append(method)
        for page_index, page in enumerate(pages):
            target = browser_paths[page_index] if page_index < len(browser_paths) else thumbs / f"session-{index:02d}-{slug(page['id'])}.svg"
            if not target.exists():
                _svg_thumbnail(str(page.get("title") or page["id"]), " ".join(page.get("text", [])), target)
                fallback_count += 1
            else:
                if target.suffix.lower() in {".png", ".webp"}:
                    screenshot_count += 1
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
            destination = thumbs / f"visual-{slug(str(asset.get('id')))}.png" if use_browser else thumbs / f"visual-{slug(str(asset.get('id')))}{path.suffix or '.svg'}"
            rendered = False
            image_info: dict[str, Any] = {"method": "fallback-svg", "runtime": "disabled", "version": None}
            if use_browser:
                rendered, image_info = _try_document_screenshot(path, destination)
                if image_info.get("version"):
                    browser_versions.add(str(image_info["version"]))
                if not rendered:
                    method = str(image_info.get("method") or "playwright-failed")
                    if method == "playwright-unavailable":
                        browser_unavailable = True
                    else:
                        browser_failures.append({"kind": "visual", "asset_id": asset.get("id"), "method": method})
            if not rendered:
                destination = thumbs / f"visual-{slug(str(asset.get('id')))}{path.suffix or '.svg'}"
                shutil.copy2(path, destination)
                fallback_count += 1
            else:
                screenshot_count += 1
            thumbnail_paths.append(destination)
            visual_rows.append(f'<article class="visual-card"><h3>{html.escape(str(asset.get("title") or asset.get("id")))}</h3><img src="{html.escape(destination.relative_to(root).as_posix())}" alt="visual evidence thumbnail"><p>{html.escape(str(asset.get("type")))}</p></article>')
    practice_rows: list[str] = []
    for index, item in enumerate(practice_outputs, start=1):
        starter_dir = Path(str(item.get("student_dir") or item.get("student_root") or "")).expanduser().resolve()
        starter = None
        if use_browser and starter_dir.is_dir():
            student_page = starter_dir / "student-task.html"
            candidate = thumbs / f"practice-{index:02d}-student-task.png"
            rendered, image_info = _try_document_screenshot(student_page, candidate) if student_page.is_file() else (False, {"method": "missing-practice-page", "runtime": "unavailable", "version": None})
            if rendered:
                starter = candidate
                screenshot_count += 1
                if image_info.get("version"):
                    browser_versions.add(str(image_info["version"]))
            else:
                method = str(image_info.get("method") or "playwright-failed")
                if method == "playwright-unavailable":
                    browser_unavailable = True
                else:
                    browser_failures.append({"kind": "practice", "session_id": item.get("id"), "method": method})
                starter = _starter_thumbnail(starter_dir, thumbs, f"practice-{index:02d}")
                if starter:
                    fallback_count += 1
        elif starter_dir.is_dir():
            starter = _starter_thumbnail(starter_dir, thumbs, f"practice-{index:02d}")
            if starter:
                fallback_count += 1
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
    browser_ok = browser_ok and use_browser and not browser_failures and not browser_unavailable and fallback_count == 0 and screenshot_count > 0
    status = "PASS" if thumbnail_paths and browser_ok else "FAIL" if thumbnail_paths and browser_failures else "DEGRADED" if thumbnail_paths else "NOT_RUN"
    result = {
        "schema_version": "1.1",
        "report_type": "whole_course_contact_sheets",
        "status": status,
        "thumbnail_count": len(thumbnail_paths),
        "browser_methods": browser_methods,
        "browser_runtime": "Chromium/Playwright" if browser_ok else "disabled" if not use_browser else "unavailable_or_failed",
        "browser_version": sorted(browser_versions),
        "viewport": {"width": 1280, "height": 800},
        "render_method": "chromium_screenshot" if browser_ok else "fallback_svg_or_source_image",
        "screenshot_count": screenshot_count,
        "fallback_count": fallback_count,
        "browser_rendered": browser_ok,
        "browser_unavailable": browser_unavailable,
        "browser_failures": browser_failures,
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
