"""Content-level review for Courseware Content Contract 1.1.

This is intentionally separate from deterministic HTML/output validation. It
checks teaching structure, time plausibility, visual explanation and density
signals without trying to author or rewrite a lesson.
"""

from __future__ import annotations

import re
from typing import Any

from content_contract import normalize_content, validate_content


def _meaningful(value: Any) -> int:
    return len(re.sub(r"\s+", "", str(value or "")))


def _slide_density(slide: dict[str, Any]) -> dict[str, int]:
    metrics = {"paragraph_chars": 0, "bullet_items": 0, "card_items": 0, "table_cells": 0, "code_lines": 0, "svg_count": 0, "image_count": 0, "formula_count": 0}
    for block in slide.get("blocks", []):
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "paragraph":
            metrics["paragraph_chars"] += _meaningful(block.get("text"))
        elif kind in {"bullets", "summary"}:
            metrics["bullet_items"] += len(block.get("items", []))
        elif kind == "cards":
            metrics["card_items"] += len(block.get("items", []))
        elif kind == "table":
            metrics["table_cells"] += len(block.get("headers", [])) + sum(len(row) for row in block.get("rows", []) if isinstance(row, list))
        elif kind == "code":
            metrics["code_lines"] += len(str(block.get("code", "")).splitlines())
        elif kind == "svg":
            metrics["svg_count"] += 1
        elif kind == "image":
            metrics["image_count"] += 1
        elif kind == "formula":
            metrics["formula_count"] += 1
    metrics["visual_count"] = metrics["svg_count"] + metrics["image_count"]
    metrics["content_units"] = sum(metrics.values())
    return metrics


def review_content(content: dict[str, Any]) -> dict[str, Any]:
    normalized, migration = normalize_content(content)
    contract = validate_content(normalized)
    errors: list[str] = []
    warnings: list[str] = []
    if contract["status"] != "pass":
        errors.extend(contract["errors"])
    slide_metrics: list[dict[str, Any]] = []
    for index, slide in enumerate(normalized.get("slides", [])):
        if not isinstance(slide, dict):
            continue
        density = _slide_density(slide)
        density["id"] = slide.get("id")
        density["suggested_minutes"] = slide.get("suggested_minutes")
        slide_metrics.append(density)
        content_units = density["content_units"]
        minutes = int(slide.get("suggested_minutes", 0) or 0)
        if content_units < 4:
            warnings.append(f"slides[{index}] is too sparse for a classroom page; consider a concrete example or visual")
        if content_units > 90 and minutes <= 2:
            warnings.append(f"slides[{index}] is dense for {minutes} planned minutes; consider split/focus planning")
        if density["visual_count"] and not str(slide.get("teaching_intent", {}).get("core_explanation", "")).strip():
            errors.append(f"slides[{index}] contains a visual block without a core explanation intent")
        if density["visual_count"] and not any(block.get("caption") for block in slide.get("blocks", []) if isinstance(block, dict) and block.get("type") in {"svg", "image"}):
            warnings.append(f"slides[{index}] visual block has no caption; speaker script must still identify what to inspect")
    if normalized.get("prepared_minutes", 0) and sum(int(slide.get("suggested_minutes", 0) or 0) for slide in normalized.get("slides", []) if isinstance(slide, dict)) != normalized.get("prepared_minutes"):
        errors.append("prepared_minutes does not equal the planned slide time after normalization")
    status = "FAIL" if errors else ("DEGRADED" if warnings else "PASS")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "slides": len(slide_metrics),
            "slide_density": slide_metrics,
            "prepared_minutes": normalized.get("prepared_minutes"),
            "planned_minutes": sum(int(slide.get("suggested_minutes", 0) or 0) for slide in normalized.get("slides", []) if isinstance(slide, dict)),
        },
        "migration": migration,
    }
