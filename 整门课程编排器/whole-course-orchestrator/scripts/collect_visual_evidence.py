"""Collect observed semantic visual evidence from final Courseware HTML.

This adapter intentionally does not accept planner requirements as observed
evidence. It only reads marker attributes and accessible DOM metadata that
survived the downstream renderer.
"""

from __future__ import annotations

import argparse
import html as html_module
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from orchestrator_core import dump_json, load_json


KNOWN_ROLES = {
    "actor", "system_boundary", "use_case", "association", "include", "extend", "generalization",
    "class", "class_compartment", "attribute", "operation", "relationship", "multiplicity", "inheritance", "aggregation", "composition",
    "lifeline", "activation", "message", "return", "fragment", "state", "event", "transition", "guard", "initial", "final",
    "node", "artifact", "deployment", "communication_link", "action", "control_flow", "decision", "fork_or_join", "initial_or_final",
}


def _tokens(value: Any) -> Iterable[str]:
    text = str(value or "").replace("-", "_").replace("/", "_")
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]+", text):
        lowered = token.lower()
        if lowered in KNOWN_ROLES:
            yield lowered


class _VisualDOMParser(HTMLParser):
    def __init__(self, source_name: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_name = source_name
        self.pages: dict[str, dict[str, Any]] = {}
        self.current_page: str | None = None
        # Keep the opening tag with the previous page.  A page contains many
        # nested divs; popping on every div end would otherwise close the page
        # at the first inner container and make later evidence look like it
        # belongs to the document root.
        self.page_stack: list[tuple[str, str | None]] = []

    def _page(self) -> dict[str, Any]:
        page_id = self.current_page or "__document__"
        return self.pages.setdefault(page_id, {"page_id": page_id, "artifact_types": set(), "roles": set(), "evidence": [], "asset_ids": set(), "text": []})

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("data-page-id"):
            self.page_stack.append((tag, self.current_page))
            self.current_page = values["data-page-id"]
        page = self._page()
        selector = tag
        if values.get("id"):
            selector += f"#{values['id']}"
        if values.get("class"):
            selector += "." + ".".join(values["class"].split())
        artifact_type = values.get("data-artifact-type") or values.get("data-visual-artifact")
        if artifact_type:
            page["artifact_types"].add(artifact_type)
            page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "artifact-type-marker", "value": artifact_type, "selector": selector})
        for raw_role in (values.get("data-semantic-role", ""), values.get("data-semantic-roles", "")):
            for role in re.split(r"[\s,;|]+", raw_role):
                role = role.strip().lower()
                if not role:
                    continue
                page["roles"].add(role)
                page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "semantic-role-marker", "value": role, "selector": selector})
        for key in ("class", "id", "aria-label", "data-label", "data-role"):
            for role in _tokens(values.get(key)):
                page["roles"].add(role)
                page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "accessible-semantic-label", "value": role, "selector": selector, "attribute": key})
        for key in ("data-source-asset-id", "data-derived-from-asset-id", "data-derived-from-asset-ids"):
            raw_ids = values.get(key, "")
            if raw_ids:
                ids = [item for item in re.split(r"[\s,;|]+", raw_ids) if item]
                page["asset_ids"].update(ids)
                page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "asset-render-marker", "value": ids, "selector": selector, "attribute": key})
        if tag == "img" and values.get("src"):
            page["evidence"].append({"source": self.source_name, "page_id": page["page_id"], "kind": "rendered-image", "value": values["src"][:120], "selector": selector})

    def handle_endtag(self, tag: str) -> None:
        if self.page_stack and self.page_stack[-1][0] == tag:
            _, self.current_page = self.page_stack.pop()

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._page()["text"].append(data.strip())


def _read_html(value: str | Path | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        return value.read_text(encoding="utf-8")
    text = str(value)
    if "<" in text and ">" in text:
        return text
    path = Path(text)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _normalise_page_records(student_html: str | Path | None, teacher_html: str | Path | None) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for name, value in (("student.html", student_html), ("teacher.html", teacher_html)):
        source = _read_html(value)
        if not source:
            continue
        parser = _VisualDOMParser(name)
        parser.feed(source)
        for page_id, record in parser.pages.items():
            target = merged.setdefault(page_id, {"page_id": page_id, "artifact_types": set(), "roles": set(), "evidence": [], "asset_ids": set(), "text": []})
            target["artifact_types"].update(record["artifact_types"])
            target["roles"].update(record["roles"])
            target["evidence"].extend(record["evidence"])
            target["asset_ids"].update(record["asset_ids"])
            target["text"].extend(record["text"])
    return merged


def collect_visual_evidence(
    visual_plans: dict[str, Any] | list[dict[str, Any]],
    student_html: str | Path | None = None,
    teacher_html: str | Path | None = None,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    plans = visual_plans.get("visual_plans", []) if isinstance(visual_plans, dict) else visual_plans
    pages = _normalise_page_records(student_html, teacher_html)
    observed_plans: list[dict[str, Any]] = []
    all_assets: set[str] = set()
    incomplete = False
    for raw in plans or []:
        plan = dict(raw)
        page_id = str(plan.get("page_id") or "")
        record = pages.get(page_id, {"roles": set(), "artifact_types": set(), "evidence": [], "asset_ids": set(), "text": []})
        required = list(dict.fromkeys(str(item) for item in plan.get("required_semantic_elements", [])))
        observed = sorted(set(str(item) for item in record["roles"]))
        plan["observed_semantic_elements"] = observed
        plan["evidence"] = list(record["evidence"])
        plan["observed_artifact_types"] = sorted(record["artifact_types"])
        plan["observed_source_asset_ids"] = sorted(record["asset_ids"])
        if required:
            plan["evidence_status"] = "PASS" if set(required) <= set(observed) else "PLANNED_NOT_OBSERVED" if not observed else "NOT_OBSERVED"
        else:
            # A supporting/generated visual has no typed semantic checklist;
            # its observed artifact marker is still required to distinguish a
            # rendered block from an unfulfilled visual plan.
            plan["evidence_status"] = "PASS" if record["artifact_types"] or observed else "PLANNED_NOT_OBSERVED"
        if required and set(required) - set(observed):
            incomplete = True
        all_assets.update(record["asset_ids"])
        observed_plans.append(plan)
    # A session with no visual requirement is not a missing observation.  A
    # declared visual plan with no final DOM, however, is a failed observation
    # and must remain fail-closed.
    status = "PASS" if not plans else "FAIL" if not pages or incomplete else "PASS"
    result = {
        "schema_version": "1.1",
        "report_type": "whole_course_visual_evidence",
        "status": status,
        "visual_plans": observed_plans,
        "rendered_asset_ids": sorted(all_assets),
        "page_count_observed": len(pages),
        "collection_policy": "Observed roles come only from final Courseware DOM markers, accessible labels, classes or IDs; planner requirements are never used as observations.",
    }
    if output_path:
        dump_json(result, output_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-plans", required=True)
    parser.add_argument("--student-html", required=True)
    parser.add_argument("--teacher-html")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = collect_visual_evidence(load_json(args.visual_plans), args.student_html, args.teacher_html, output_path=args.output_json)
    if args.json:
        print({"status": result["status"], "visuals": len(result["visual_plans"]), "rendered_assets": result["rendered_asset_ids"]})


if __name__ == "__main__":
    main()
