"""Validate Practice Class HTML modules, panes, audience boundaries, and links."""

from __future__ import annotations

import argparse
import html.parser
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from practice_contract import RENDERER_FAMILIES, load_courseware, load_json, validate_content


STUDENT_PAGES = (Path("student") / "student-task.html", Path("student") / "learning-center.html", Path("student") / "study-guide.html", Path("student") / "foundation-kit.html")
TEACHER_PAGES = (Path("teacher") / "teacher-guide.html", Path("teacher") / "teacher-reference.html")
REQUIRED_TOP_LEVEL = {"student", "teacher", "practice-content.json", "qa-report.json"}
EXTERNAL_PATTERN = re.compile(r"(?i)(?:https?:|//|data:|javascript:|file:)")
FORBIDDEN_LAYOUT = re.compile(r"(?i)border-left\s*:\s*4px\s+solid")
FORBIDDEN_MARKERS = ("Contract 1.0", "Practice Class")
FAMILIES = set(RENDERER_FAMILIES.values())


class _HTMLProbe(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.elements: list[dict[str, Any]] = []
        self.panes: list[dict[str, Any]] = []
        self.interactions: list[dict[str, Any]] = []
        self.pane_targets: list[str] = []
        self.doctype = False
        self.meta_charset = False
        self.buttons = 0
        self.text_parts: list[str] = []
        self._ignored_depth = 0

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype html"):
            self.doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        values["_tag"] = tag
        self.elements.append(values)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")
        if tag == "button":
            self.buttons += 1
        if "data-pane" in values:
            self.panes.append(values)
        if "data-interaction-root" in values:
            self.interactions.append(values)
        if values.get("data-pane-target"):
            self.pane_targets.append(values["data-pane-target"] or "")
        if tag == "meta" and values.get("charset"):
            self.meta_charset = values["charset"].lower() == "utf-8"
        if tag in {"script", "style"}:
            self._ignored_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        values["_tag"] = tag
        self.elements.append(values)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.text_parts.append(data)

    @property
    def visible_text(self) -> str:
        return " ".join(" ".join(self.text_parts).split())


def _probe(path: Path) -> _HTMLProbe:
    probe = _HTMLProbe()
    probe.feed(path.read_text(encoding="utf-8"))
    probe.close()
    return probe


def _anchor_ids(path: Path) -> set[str]:
    return _probe(path).ids


def _check_link(source: Path, href: str, output_dir: Path, errors: list[str]) -> None:
    if not href or href.startswith("#"):
        if href.startswith("#") and href[1:] and href[1:] not in _anchor_ids(source):
            errors.append(f"{source.name}: missing local anchor {href}")
        return
    if EXTERNAL_PATTERN.search(href):
        errors.append(f"{source.name}: external, executable, or file link is not allowed: {href}")
        return
    parsed = urlsplit(href)
    relative = unquote(parsed.path)
    target = source if not relative else (source.parent / relative).resolve()
    try:
        target.relative_to(output_dir.resolve())
    except ValueError:
        errors.append(f"{source.name}: link escapes output directory: {href}")
        return
    if not target.is_file():
        errors.append(f"{source.name}: link target does not exist: {href}")
        return
    if parsed.fragment and target.suffix.lower() in {".html", ".htm"} and parsed.fragment not in _anchor_ids(target):
        errors.append(f"{source.name}: target anchor does not exist: {href}")


def _machine_values(content: dict[str, Any]) -> set[str]:
    values = {str(content.get("contract_version", ""))}
    for field in ("tasks", "learning_center", "study_guide", "foundation_kit"):
        values.update(str(item.get("id")) for item in content.get(field, []) if isinstance(item, dict))
    values.update(str(ref) for item in content.get("knowledge_links", []) if isinstance(item, dict) for ref in item.get("source_slide_ids", []))
    values.update(str(ref) for ref in content.get("source_courseware", {}).get("taught_slide_ids", []))
    values.update(FAMILIES)
    values.update(RENDERER_FAMILIES)
    return {value for value in values if value}


def validate_html_file(path: Path, output_dir: Path, *, content: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not path.is_file():
        return {"status": "fail", "errors": [f"missing HTML output: {path}"], "warnings": [], "metrics": {}}
    raw = path.read_text(encoding="utf-8")
    probe = _probe(path)
    if not probe.doctype or not raw.lstrip().lower().startswith("<!doctype html>"):
        errors.append(f"{path.name}: HTML5 doctype is required")
    if not probe.meta_charset:
        errors.append(f"{path.name}: UTF-8 meta charset is required")
    if EXTERNAL_PATTERN.search(raw):
        errors.append(f"{path.name}: external/executable/file URL found in offline HTML")
    if FORBIDDEN_LAYOUT.search(raw):
        errors.append(f"{path.name}: thick left-border template styling is not allowed")
    for href in probe.links:
        _check_link(path, href, output_dir, errors)
    relative = path.resolve().relative_to(output_dir.resolve())
    role = relative.parts[0] if relative.parts else ""
    if role in {"student", "teacher"}:
        if not any(item.get("data-page-module") for item in probe.elements):
            errors.append(f"{path.name}: data-page-module is required")
        if len(probe.panes) > 0:
            active = [item for item in probe.panes if "is-active" in (item.get("class") or "").split()]
            if len(active) != 1:
                errors.append(f"{path.name}: exactly one pane must be marked active in the source")
            pane_ids = [item.get("id") for item in probe.panes]
            if len(pane_ids) != len(set(pane_ids)):
                errors.append(f"{path.name}: pane ids must be unique")
            for target in probe.pane_targets:
                if target.startswith("#") and target[1:] not in probe.ids:
                    errors.append(f"{path.name}: pane target has no matching pane: {target}")
        visible = probe.visible_text.casefold()
        for marker in FORBIDDEN_MARKERS:
            if marker.casefold() in visible:
                errors.append(f"{path.name}: visible text contains machine marker: {marker}")
        if content:
            for value in sorted(_machine_values(content)):
                if value.casefold() in visible:
                    errors.append(f"{path.name}: visible text contains machine value: {value}")
        if role == "student":
            for href in probe.links:
                if href.startswith("#"):
                    continue
                target = (path.parent / urlsplit(href).path).resolve()
                try:
                    target.relative_to((output_dir / "student").resolve())
                except ValueError:
                    errors.append(f"{path.name}: student link leaves student/ tree: {href}")
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "metrics": {"links": len(probe.links), "anchors": len(probe.ids), "buttons": probe.buttons, "panes": len(probe.panes), "interactions": len(probe.interactions), "renderer_families": sorted({item.get("data-renderer-family") for item in probe.interactions if item.get("data-renderer-family")}), "characters": len(raw), "visible_characters": len(probe.visible_text)}}


def _expected_html_paths() -> list[Path]:
    return [*STUDENT_PAGES, *TEACHER_PAGES]


def _slug(value: Any) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", str(value or "")).strip("-")
    return cleaned or "item"


def _elements_with(probe: _HTMLProbe, attr: str, value: str) -> list[dict[str, Any]]:
    return [item for item in probe.elements if item.get(attr) == value]


def validate_output_files(content: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not output_dir.is_dir():
        return {"status": "fail", "errors": [f"missing output directory: {output_dir}"], "warnings": [], "files": []}
    names = {path.name for path in output_dir.iterdir()}
    for required in REQUIRED_TOP_LEVEL:
        if required not in names:
            errors.append(f"missing required output: {required}")
    expected = _expected_html_paths()
    for relative in expected:
        result = validate_html_file(output_dir / relative, output_dir, content=content)
        errors.extend(result["errors"])
        warnings.extend(result["warnings"])
    actual_html = {path.relative_to(output_dir) for path in output_dir.rglob("*.html")}
    unexpected = sorted(actual_html - set(expected))
    if unexpected:
        errors.extend(f"unexpected HTML output: {path.as_posix()}" for path in unexpected)
    stale_dirs = (Path("student") / "tasks", Path("student") / "learning", Path("student") / "guides", Path("student") / "kit", Path("teacher") / "references")
    for stale in stale_dirs:
        if (output_dir / stale).exists():
            errors.append(f"legacy detail directory must not be generated: {stale.as_posix()}")

    page_specs = {
        Path("student") / "student-task.html": (len(content.get("tasks", [])), "task-"),
        Path("student") / "learning-center.html": (len(content.get("learning_center", [])), "lab-"),
        Path("student") / "study-guide.html": (len(content.get("study_guide", [])), "guide-"),
        Path("student") / "foundation-kit.html": (len(content.get("foundation_kit", [])), "kit-"),
        Path("teacher") / "teacher-guide.html": (len(content.get("teacher_guide", {}).get("task_guidance", [])), "teacher-task-"),
        Path("teacher") / "teacher-reference.html": (len(content.get("teacher_reference", {}).get("task_references", [])), "reference-"),
    }
    page_metrics: dict[str, Any] = {}
    for relative, (expected_count, prefix) in page_specs.items():
        path = output_dir / relative
        if not path.is_file():
            continue
        probe = _probe(path)
        if len(probe.panes) != expected_count:
            errors.append(f"{relative.as_posix()} must contain {expected_count} panes, found {len(probe.panes)}")
        if expected_count and not any(item.get("id", "").startswith(prefix) for item in probe.panes):
            errors.append(f"{relative.as_posix()} has no {prefix} pane")
        if relative == Path("student") / "student-task.html" and "task-route" not in probe.ids:
            errors.append("student-task.html must expose a stable task-route anchor")
        page_metrics[relative.as_posix()] = {"panes": len(probe.panes), "interactions": len(probe.interactions), "renderer_families": sorted({item.get("data-renderer-family") for item in probe.interactions if item.get("data-renderer-family")})}

    for asset in content.get("starter_assets", []):
        if not isinstance(asset, dict):
            continue
        target = output_dir / "student" / "starter" / str(asset.get("path", ""))
        if not target.is_file():
            errors.append(f"starter asset output is missing: {target.relative_to(output_dir)}")
        if str(asset.get("path", "")).lower().endswith(".drawio"):
            try:
                ET.fromstring(target.read_text(encoding="utf-8"))
            except (OSError, ET.ParseError) as exc:
                errors.append(f"draw.io starter is not parseable: {asset.get('path')}: {exc}")

    task_page = output_dir / "student" / "student-task.html"
    task_probe = _probe(task_page) if task_page.is_file() else None
    if task_probe:
        for task in content.get("tasks", []):
            if not isinstance(task, dict):
                continue
            panes = _elements_with(task_probe, "data-task-id", str(task.get("id")))
            if len(panes) != 1:
                errors.append(f"student task pane is missing or duplicated: {task.get('id')}")
                continue
            declared = set((panes[0].get("data-source-slide-ids") or "").split())
            refs = set(str(item) for item in task.get("source_slide_ids", []))
            if refs - declared:
                errors.append(f"student task pane lacks source slide references: {task.get('id')}")

    learning_page = output_dir / "student" / "learning-center.html"
    learning_probe = _probe(learning_page) if learning_page.is_file() else None
    if learning_probe:
        by_id = {str(item.get("id")): item for item in content.get("learning_center", []) if isinstance(item, dict)}
        for interaction in learning_probe.interactions:
            center_id = str(interaction.get("data-center-id"))
            center = by_id.get(center_id, {})
            expected = center.get("interaction", {}).get("estimated_minutes") if isinstance(center.get("interaction"), dict) else None
            actual = interaction.get("data-estimated-minutes")
            if expected is not None and str(expected) != str(actual):
                errors.append(f"learning interaction timing must come from its own estimated_minutes: {center_id}")
            if center.get("interaction", {}).get("type") == "classify":
                feedback_nodes = [item for item in learning_probe.elements if "data-classify-feedback" in item]
                if not feedback_nodes or any("hidden" not in item for item in feedback_nodes):
                    errors.append(f"classification feedback must be hidden before checking: {center_id}")
            if center.get("interaction", {}).get("type") == "reorder":
                initial = interaction.get("data-initial-order")
                correct = interaction.get("data-correct-order")
                if not initial or not correct or initial == correct:
                    errors.append(f"reorder interaction must start incorrect and expose a reset path: {center_id}")
                if not any("data-reset" in item for item in learning_probe.elements):
                    errors.append(f"reorder interaction must expose reset: {center_id}")
            if center.get("interaction", {}).get("type") == "state-simulator":
                if not interaction.get("data-state-fields") or not interaction.get("data-rounds"):
                    errors.append(f"state simulator must expose generic state_fields and rounds: {center_id}")

    files = sorted(str(path.relative_to(output_dir)).replace("\\", "/") for path in output_dir.rglob("*") if path.is_file())
    metrics = {"main_html_count": len(actual_html), "page_panes": page_metrics}
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "files": files, "metrics": metrics}


def validate(practice_path: Path, output_dir: Path, courseware_path: Path | None = None) -> dict[str, Any]:
    content = load_json(practice_path); courseware = load_courseware(courseware_path) if courseware_path else None; contract = validate_content(content, courseware); output = validate_output_files(content, output_dir); errors = [*contract["errors"], *output["errors"]]; warnings = [*contract["warnings"], *output["warnings"]]
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "contract": contract, "outputs": output}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--practice-json", required=True, type=Path); parser.add_argument("--courseware-json", type=Path); parser.add_argument("--output-dir", required=True, type=Path); parser.add_argument("--json", action="store_true", dest="as_json"); args = parser.parse_args(); report = validate(args.practice_json, args.output_dir, args.courseware_json); print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else f"status={report['status']} errors={len(report['errors'])} warnings={len(report['warnings'])}"); raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
