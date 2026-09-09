"""Validate Practice Class HTML modules, panes, audience boundaries, and links."""

from __future__ import annotations

import argparse
import html
import html.parser
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from practice_contract import RENDERER_FAMILIES, load_courseware, load_json, normalize_content, validate_content
from classroom_integrity import closure


STUDENT_PAGES = (Path("student") / "student-task.html", Path("student") / "learning-center.html", Path("student") / "study-guide.html", Path("student") / "foundation-kit.html")
TEACHER_PAGES = (Path("teacher") / "teacher-guide.html", Path("teacher") / "teacher-reference.html")
REQUIRED_TOP_LEVEL = {"student", "teacher", "practice-content.json", "qa-report.json"}
EXTERNAL_PATTERN = re.compile(r"(?i)(?:https?:|//|data:|javascript:|file:)")
FORBIDDEN_LAYOUT = re.compile(r"(?i)border-left\s*:\s*4px\s+solid")
FORBIDDEN_MARKERS = ("Contract 1.0", "Contract 1.1", "Practice Class", "source_slide_ids", "interaction type", "renderer family", "task_id", "slide_id", "interaction_type", "renderer_family")
FAMILIES = set(RENDERER_FAMILIES.values())
TEXT_ASSET_EXTENSIONS = {".c", ".cpp", ".h", ".hpp", ".py", ".java", ".js", ".ts", ".html", ".htm", ".css", ".sql", ".md", ".txt", ".json", ".yaml", ".yml", ".xml", ".csv"}
NON_TEXT_ASSET_EXTENSIONS = {".drawio", ".xlsx", ".xls", ".docx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".zip"}


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
    # Renderer keys such as ``trace`` can be legitimate course/tool words
    # (for example, Cisco Packet Tracer).  Keep the user-visible guard on
    # stable machine markers and renderer-family labels, not short type keys.
    values.update(FAMILIES)
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


def _asset_is_text(path: str) -> bool:
    suffix = Path(path).suffix.casefold()
    return suffix in TEXT_ASSET_EXTENSIONS and suffix not in NON_TEXT_ASSET_EXTENSIONS


def _validate_reference_completeness(content: dict[str, Any], errors: list[str]) -> None:
    tasks = {str(item.get("id")): item for item in content.get("tasks", []) if isinstance(item, dict) and item.get("id")}
    for reference in content.get("teacher_reference", {}).get("task_references", []):
        if not isinstance(reference, dict):
            continue
        task_id = str(reference.get("task_id"))
        task = tasks.get(task_id, {})
        modality = str(task.get("modality", "")).casefold()
        capabilities = set(task.get("capabilities", [])) if isinstance(task.get("capabilities"), list) else set()
        answer = str(reference.get("reference_answer", ""))
        if ("code_editing" in capabilities or modality in {"coding", "programming"}) and (len(answer) < 160 or "return" not in answer or "{" not in answer):
            errors.append(f"teacher reference for coding task is too short to be a complete code result: {task_id}")
        if ("query_execution" in capabilities or "sql" in modality) and (not re.search(r"\bselect\b", answer, re.IGNORECASE) or not re.search(r"\bfrom\b", answer, re.IGNORECASE)):
            errors.append(f"teacher reference for SQL task needs a complete SQL expression: {task_id}")
        if ("model_editing" in capabilities or modality in {"modeling", "modeling-tool", "model-critique"}) and not reference.get("reference_visual") and not reference.get("model_visual") and not re.search(r"(?:→|->|—|1\s*[-—]\s*0\.\.\*|关系|消息)", answer):
            errors.append(f"teacher reference for modeling task needs relation/message structure or reference_visual: {task_id}")
        if content.get("integrity_version") == "1.0":
            facts = [fact for fact in content.get("formula_facts", []) if isinstance(fact, dict) and fact.get("task_id") == task_id and fact.get("example_scope") == "current-dataset"]
            if task.get("artifact_kind") == "workbook" and not facts:
                errors.append(f"teacher reference for workbook task needs a current-dataset formula fact: {task_id}")
            for fact in facts:
                bindings = fact.get("bindings", {}) if isinstance(fact.get("bindings"), dict) else {}
                fields = [bindings.get("input_field"), *(bindings.get("input_fields") or [])]
                if not any(str(field) and str(field) in answer for field in fields):
                    errors.append(f"teacher reference for workbook task must name bound fields: {task_id}")
                if str(fact.get("formula", "")).replace(" ", "") not in answer.replace(" ", "") and not reference.get("formula_evidence"):
                    errors.append(f"teacher reference for workbook task must show the verified formula: {task_id}")
                if not fact.get("operation_location") or (fact.get("expected_result") is None and not reference.get("reference_result")):
                    errors.append(f"teacher reference for workbook task needs formula location and result: {task_id}")
            verification = task.get("reference_verification")
            if isinstance(verification, dict) and any(item.get("verification_type") in {"manual-evidence", "browser"} for item in verification.get("checks", []) if isinstance(item, dict)):
                for field in ("reference_reasoning", "tool_observation", "environment_boundary"):
                    if not reference.get(field):
                        errors.append(f"teacher reference for manual/tool task needs {field}: {task_id}")


def _validate_safe_student_package(output_dir: Path, errors: list[str]) -> None:
    student_root = output_dir / "student-package"
    manifest_path = student_root / "student-manifest.json"
    safe_content_path = student_root / "practice-content.json"
    teacher_root = output_dir / "teacher-package"
    for path in (student_root / "student", manifest_path, safe_content_path, teacher_root / "teacher", teacher_root / "full-practice-content.json"):
        if not path.exists():
            errors.append(f"safe package output is missing: {path.relative_to(output_dir)}")
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for field in ("teacher_answers_included", "replacement_metadata_included", "canonical_answers_included"):
                if manifest.get(field) is not False:
                    errors.append(f"student manifest must set {field}=false")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"student manifest is not valid JSON: {exc}")
    if safe_content_path.is_file():
        try:
            safe = json.loads(safe_content_path.read_text(encoding="utf-8"))
            for forbidden in ("teacher_guide", "teacher_reference", "canonical_facts"):
                if forbidden in safe:
                    errors.append(f"student package leaks teacher-only field: {forbidden}")
            for asset in safe.get("starter_assets", []):
                if not isinstance(asset, dict):
                    continue
                for forbidden in ("editable_gaps", "replacement", "target"):
                    if forbidden in asset:
                        errors.append(f"student package starter leaks teacher-only field: {forbidden}")
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"student package content is not valid JSON: {exc}")


def validate_output_files(content: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not output_dir.is_dir():
        return {"status": "fail", "errors": [f"missing output directory: {output_dir}"], "warnings": [], "files": []}
    names = {path.name for path in output_dir.iterdir()}
    for required in REQUIRED_TOP_LEVEL:
        if required not in names:
            errors.append(f"missing required output: {required}")
    _validate_safe_student_package(output_dir, errors)
    package_integrity = closure(content, output_dir / "student" / "starter")
    if content.get("integrity_version") == "1.0":
        errors.extend(package_integrity["errors"])
    expected = _expected_html_paths()
    for relative in expected:
        result = validate_html_file(output_dir / relative, output_dir, content=content)
        errors.extend(result["errors"])
        warnings.extend(result["warnings"])
    actual_html = {
        path.relative_to(output_dir)
        for path in output_dir.rglob("*.html")
        if len(path.relative_to(output_dir).parts) == 2 and path.relative_to(output_dir).parts[0] in {"student", "teacher"}
    }
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
        if asset.get('role', 'student-edit') in {'teacher-reference', 'test-only'}:
            if (output_dir / 'student' / 'starter' / str(asset.get('path', ''))).exists():
                errors.append('teacher-only starter leaked')
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
        assets_by_id = {str(asset.get("id")): asset for asset in content.get("starter_assets", []) if isinstance(asset, dict) and asset.get("id")}
        starter_links = {str(item.get("data-starter-path")): item for item in task_probe.elements if item.get("_tag") == "a" and item.get("data-starter-path")}
        starter_previews = {str(item.get("data-starter-preview-path")) for item in task_probe.elements if item.get("data-starter-preview-path")}
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
            for asset_id in task.get("starter_asset_ids", []):
                asset = assets_by_id.get(str(asset_id))
                if not asset:
                    continue
                asset_path = str(asset.get("path", "")).replace("\\", "/")
                if asset_path not in starter_links:
                    errors.append(f"task {task.get('id')} starter has no clickable href: {asset_path}")
                target = output_dir / "student" / "starter" / asset_path
                if not target.is_file():
                    continue
                if _asset_is_text(asset_path):
                    if asset_path not in starter_previews:
                        errors.append(f"text starter has no content preview marker: {asset_path}")
                    else:
                        escaped_content = html.escape(target.read_text(encoding="utf-8"), quote=True)
                        if escaped_content and escaped_content not in task_page.read_text(encoding="utf-8"):
                            errors.append(f"starter preview does not match file content: {asset_path}")
                elif asset_path.casefold().endswith(".drawio"):
                    if asset_path in starter_previews:
                        errors.append(f"draw.io starter must not expose a raw preview: {asset_path}")
                    if "mxGraphModel" in task_probe.visible_text or "mxCell" in task_probe.visible_text:
                        errors.append(f"draw.io starter XML is visible in student page: {asset_path}")

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
    metrics = {"main_html_count": len(actual_html), "page_panes": page_metrics, "starter_links": len(starter_links) if task_probe else 0, "starter_previews": len(starter_previews) if task_probe else 0, "classroom_package_integrity": package_integrity}
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "files": files, "metrics": metrics}


def validate(practice_path: Path, output_dir: Path, courseware_path: Path | None = None) -> dict[str, Any]:
    raw_content = load_json(practice_path); courseware = load_courseware(courseware_path) if courseware_path else None; content, _ = normalize_content(raw_content, courseware); contract = validate_content(content, courseware); output = validate_output_files(content, output_dir); completeness_errors: list[str] = []; _validate_reference_completeness(content, completeness_errors); errors = [*contract["errors"], *output["errors"], *completeness_errors]; warnings = [*contract["warnings"], *output["warnings"]]
    return {"status": "pass" if not errors else "fail", "errors": errors, "warnings": warnings, "contract": contract, "outputs": output}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--practice-json", required=True, type=Path); parser.add_argument("--courseware-json", type=Path); parser.add_argument("--output-dir", required=True, type=Path); parser.add_argument("--json", action="store_true", dest="as_json"); args = parser.parse_args(); report = validate(args.practice_json, args.output_dir, args.courseware_json); print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else f"status={report['status']} errors={len(report['errors'])} warnings={len(report['warnings'])}"); raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
