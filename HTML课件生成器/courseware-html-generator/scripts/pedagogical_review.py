"""Content-level review for Courseware Content Contract 1.1.

This is intentionally separate from deterministic HTML/output validation. It
checks teaching structure, time plausibility, visual explanation and density
signals without trying to author or rewrite a lesson.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

from content_contract import normalize_content, validate_content
from activity_time_reviewer import ACTIVITY_ROLE_LABELS, resolve_activity_role, review_courseware_time
from gold_benchmark import (
    HARD_FLOOR_CHARS_PER_LECTURE_MINUTE,
    NORMAL_TARGET_MAX_CHARS_PER_LECTURE_MINUTE,
    NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE,
)


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


def _normalized_fragment(value: Any) -> str:
    """Return a comparison form that ignores spacing and classroom punctuation."""

    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", str(value or "").casefold())


def _script_fragments(script: str) -> tuple[list[str], list[str]]:
    """Split a script into sentence-like and paragraph-like fragments."""

    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*|[\r\n]+", script) if part.strip()]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", script) if part.strip()]
    return sentences, paragraphs


def _speaker_script_repetition(slides: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect mechanical script duplication without attempting NLP authorship review.

    The thresholds intentionally focus on long, exact repeats.  A short classroom
    transition such as "我们先看这里" is not evidence of padding, while a long
    sentence or paragraph repeated three times is.
    """

    sentence_counts: Counter[str] = Counter()
    sentence_display: dict[str, str] = {}
    paragraph_counts: Counter[str] = Counter()
    paragraph_display: dict[str, str] = {}
    scripts: list[str] = []
    for slide in slides:
        script = str(slide.get("speaker_script", "") or "")
        scripts.append(script)
        sentences, paragraphs = _script_fragments(script)
        for fragment in sentences:
            normalized = _normalized_fragment(fragment)
            if len(normalized) >= 18:
                sentence_counts[normalized] += 1
                sentence_display.setdefault(normalized, re.sub(r"\s+", " ", fragment).strip())
        for fragment in paragraphs:
            normalized = _normalized_fragment(fragment)
            if len(normalized) >= 40:
                paragraph_counts[normalized] += 1
                paragraph_display.setdefault(normalized, re.sub(r"\s+", " ", fragment).strip())

    repeated_sentences = [
        {"count": count, "text": sentence_display[key]}
        for key, count in sentence_counts.most_common()
        if count >= 2
    ]
    repeated_paragraphs = [
        {"count": count, "text": paragraph_display[key]}
        for key, count in paragraph_counts.most_common()
        if count >= 2
    ]

    errors: list[str] = []
    warnings: list[str] = []
    severe_sentences = [item for item in repeated_sentences if item["count"] >= 3]
    severe_paragraphs = [item for item in repeated_paragraphs if item["count"] >= 3]
    if severe_sentences:
        # Repeating a short classroom sentence can be an intentional recap.  It
        # is a review warning; the paragraph/n-gram checks below decide whether
        # the whole script is mechanical padding.
        warnings.append(f"speaker_script repeats {len(severe_sentences)} long complete sentence(s) at least three times")
    if severe_paragraphs:
        errors.append(f"speaker_script repeats {len(severe_paragraphs)} long paragraph(s) at least three times")
    if repeated_sentences and not severe_sentences:
        warnings.append(f"speaker_script contains {len(repeated_sentences)} long sentence repeat(s); inspect for intentional recap")
    if repeated_paragraphs and not severe_paragraphs:
        warnings.append(f"speaker_script contains {len(repeated_paragraphs)} long paragraph repeat(s); inspect for intentional recap")

    # A repeated n-gram ratio catches duplication that is split by punctuation or
    # line breaks.  It is a signal, not a language-quality score.
    normalized_scripts = [_normalized_fragment(script) for script in scripts]
    ngram_size = 16
    repeated_ngram_count = 0
    repeated_ngram_coverage = 0
    total_chars = sum(len(script) for script in normalized_scripts)
    for script in normalized_scripts:
        if len(script) < ngram_size:
            continue
        counts = Counter(script[index:index + ngram_size] for index in range(len(script) - ngram_size + 1))
        repeated = [(gram, count) for gram, count in counts.items() if count >= 2]
        repeated_ngram_count += len(repeated)
        # Count character positions once. Summing every repeated n-gram's
        # overlap can produce ratios above 1.0 for ordinary Chinese prose.
        covered_positions: set[int] = set()
        for gram, _ in repeated:
            start = 0
            while True:
                position = script.find(gram, start)
                if position < 0:
                    break
                covered_positions.update(range(position, min(len(script), position + ngram_size)))
                start = position + 1
        repeated_ngram_coverage += len(covered_positions)
    ngram_ratio = round(repeated_ngram_coverage / max(1, total_chars), 3)
    if ngram_ratio >= 0.30:
        errors.append(f"speaker_script has a high repeated n-gram ratio ({ngram_ratio:.3f})")
    elif ngram_ratio >= 0.12:
        warnings.append(f"speaker_script has a notable repeated n-gram ratio ({ngram_ratio:.3f}); inspect for mechanical copying")

    status = "FAIL" if errors else ("DEGRADED" if warnings else "PASS")
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "scripts": len(scripts),
            "total_normalized_chars": total_chars,
            "repeated_sentences": repeated_sentences[:12],
            "repeated_paragraphs": repeated_paragraphs[:12],
            "repeated_ngram_count": repeated_ngram_count,
            "repeated_ngram_ratio": ngram_ratio,
        },
    }


def _meaningful_length(value: Any) -> int:
    return len(re.sub(r"\s+", "", str(value or "")))


def _speaker_script_planning(slides: list[dict[str, Any]]) -> dict[str, Any]:
    """Review speaking capacity against lecture time without changing the contract."""

    items: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for index, slide in enumerate(slides):
        lecture = slide.get("lecture_minutes")
        actual = _meaningful_length(slide.get("speaker_script", ""))
        if not isinstance(lecture, int) or isinstance(lecture, bool) or lecture <= 0:
            items.append({"index": index, "id": slide.get("id"), "lecture_minutes": lecture, "meaningful_chars": actual, "status": "not-applicable"})
            continue
        minimum = lecture * HARD_FLOOR_CHARS_PER_LECTURE_MINUTE
        normal_minimum = lecture * NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE
        normal_maximum = lecture * NORMAL_TARGET_MAX_CHARS_PER_LECTURE_MINUTE
        if actual < minimum:
            status = "FAIL"
            errors.append(f"slides[{index}].speaker_script has {actual} meaningful chars; below the effective guidance floor {minimum} for {lecture} lecture minutes")
        elif actual < normal_minimum:
            status = "DEGRADED"
            warnings.append(f"slides[{index}].speaker_script has {actual} meaningful chars; normal target starts at {normal_minimum} for {lecture} lecture minutes")
        else:
            status = "PASS"
            if actual > normal_maximum * 2:
                warnings.append(f"slides[{index}].speaker_script is unusually long for {lecture} lecture minutes; inspect for density")
        items.append({
            "index": index,
            "id": slide.get("id"),
            "lecture_minutes": lecture,
            "meaningful_chars": actual,
            "effective_floor_chars": minimum,
            "normal_target_chars": [normal_minimum, normal_maximum],
            "status": status,
        })
    return {"status": "FAIL" if errors else ("DEGRADED" if warnings else "PASS"), "errors": errors, "warnings": warnings, "slides": items}


def _delivery_path_review(content: dict[str, Any], slides: list[dict[str, Any]]) -> dict[str, Any]:
    """Ensure a prepared reserve is represented as an explicit teacher path."""

    session = content.get("session_minutes")
    prepared = content.get("prepared_minutes")
    declared_extension = content.get("extension_minutes")
    track_minutes = {"core": 0, "extension": 0}
    for slide in slides:
        track = slide.get("delivery_track", "core")
        if track in track_minutes:
            track_minutes[track] += int(slide.get("suggested_minutes", 0) or 0)
    errors: list[str] = []
    warnings: list[str] = []
    extension_items = [item for item in content.get("extensions", []) if isinstance(item, dict)]
    extension_item_minutes = sum(int(item.get("minutes", 0) or 0) for item in extension_items if isinstance(item.get("minutes"), int))
    if isinstance(session, int) and isinstance(prepared, int) and prepared > session:
        required_extension = prepared - session
        if not isinstance(declared_extension, int) or declared_extension < required_extension:
            errors.append(f"prepared reserve needs at least {required_extension} extension minutes, declared {declared_extension}")
        if max(track_minutes["extension"], extension_item_minutes) < required_extension:
            errors.append(
                f"prepared reserve needs an explicit extension path of at least {required_extension} minutes; "
                f"found slides={track_minutes['extension']}, extension_items={extension_item_minutes}"
            )
        if track_minutes["extension"] == 0 and extension_item_minutes == 0:
            errors.append("prepared_minutes exceeds session_minutes but no extension slide or extension item is present")
        if track_minutes["core"] > session:
            warnings.append(f"core delivery path is {track_minutes['core']} minutes for a {session}-minute session")
    elif isinstance(declared_extension, int) and declared_extension > 0 and track_minutes["extension"] == 0 and extension_item_minutes == 0:
        errors.append("extension_minutes is positive but no delivery_track=extension slide or extension item is present")
    return {
        "status": "FAIL" if errors else ("DEGRADED" if warnings else "PASS"),
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "session_minutes": session,
            "prepared_minutes": prepared,
            "declared_extension_minutes": declared_extension,
            "track_minutes": track_minutes,
            "extension_item_minutes": extension_item_minutes,
        },
    }


def theory_practice_boundary_review(
    content: dict[str, Any],
    *,
    separate_practice_available: bool = False,
) -> dict[str, Any]:
    """Review theory/practice responsibility without enforcing a fixed ratio."""

    mode = content.get("session_delivery_mode", "theory-led")
    totals = {role: 0 for role in ACTIVITY_ROLE_LABELS}
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    for index, slide in enumerate(content.get("slides", [])):
        if not isinstance(slide, dict):
            continue
        activity_minutes = slide.get("activity_minutes", 0)
        if not isinstance(activity_minutes, int) or activity_minutes <= 0:
            continue
        plan = slide.get("activity_plan") if isinstance(slide.get("activity_plan"), dict) else {}
        role, role_status = resolve_activity_role(plan)
        item = {
            "index": index,
            "slide_id": slide.get("id"),
            "activity_minutes": activity_minutes,
            "activity_role": role,
            "activity_role_status": role_status,
            "label": ACTIVITY_ROLE_LABELS.get(role, "未分类活动"),
            "delivery_track": slide.get("delivery_track", "core"),
        }
        evidence.append(item)
        if role in totals:
            totals[role] += activity_minutes
        else:
            errors.append(f"slides[{index}] activity role is not classifiable")

    independent = totals["student-independent-practice"]
    supported = sum(totals[role] for role in ("teacher-led-demonstration", "guided-whole-class-reasoning", "short-student-check"))
    core_activity = sum(
        item["activity_minutes"]
        for item in evidence
        if item["delivery_track"] != "extension"
    )
    if separate_practice_available and mode in {"theory-led", "mixed"} and independent > 0:
        if supported == 0:
            errors.append("theory/practice boundary: independent practice is the only planned classroom activity while a separate Practice asset is available")
        elif independent > supported:
            warnings.append(
                "theory/practice boundary: student-independent-practice exceeds teacher-led, guided, and short-check activity minutes; review the Courseware/Practice split"
            )
    status = "FAIL" if errors else ("DEGRADED" if warnings else "PASS")
    return {
        "status": status,
        "session_delivery_mode": mode,
        "separate_practice_available": separate_practice_available,
        "role_minutes": totals,
        "independent_practice_minutes": independent,
        "teacher_guided_or_checked_minutes": supported,
        "core_activity_minutes": core_activity,
        "activities": evidence,
        "errors": errors,
        "warnings": warnings,
        "heuristic": "compare independent-practice minutes with teacher-led/guided/short-check minutes; no fixed ratio",
    }


def review_content(
    content: dict[str, Any],
    *,
    time_mode: str = "migration-trust",
    separate_practice_available: bool = False,
) -> dict[str, Any]:
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
    repetition = _speaker_script_repetition([slide for slide in normalized.get("slides", []) if isinstance(slide, dict)])
    errors.extend(repetition["errors"])
    warnings.extend(repetition["warnings"])
    slides = [slide for slide in normalized.get("slides", []) if isinstance(slide, dict)]
    script_planning = _speaker_script_planning(slides)
    errors.extend(script_planning["errors"])
    warnings.extend(script_planning["warnings"])
    delivery_paths = _delivery_path_review(normalized, slides)
    errors.extend(delivery_paths["errors"])
    warnings.extend(delivery_paths["warnings"])
    time_evidence = review_courseware_time(normalized, mode=time_mode)
    if time_evidence["status"] == "FAIL":
        errors.extend(time_evidence["errors"])
    else:
        warnings.extend(time_evidence["warnings"])
    boundary = theory_practice_boundary_review(
        normalized,
        separate_practice_available=separate_practice_available,
    )
    errors.extend(boundary["errors"])
    warnings.extend(boundary["warnings"])
    from planning_integrity import planning_profile, coverage_review
    profile = planning_profile(normalized)
    coverage = coverage_review(normalized)
    if time_mode == 'strict' and coverage['status'] != 'PASS':
        warnings.append('script content coverage evidence requires review')
    status = "FAIL" if errors else ("DEGRADED" if warnings else "PASS")
    return {
        "status": status,
        "score": 30 if status == 'PASS' else (24 if status == 'DEGRADED' else 0),
        "score_max": 30,
        "planning_profile": profile,
        "script_coverage": coverage,
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            "slides": len(slide_metrics),
            "slide_density": slide_metrics,
            "prepared_minutes": normalized.get("prepared_minutes"),
            "planned_minutes": sum(int(slide.get("suggested_minutes", 0) or 0) for slide in normalized.get("slides", []) if isinstance(slide, dict)),
            "speaker_script_repetition": repetition,
            "speaker_script_planning": script_planning,
            "delivery_paths": delivery_paths,
            "time_evidence": time_evidence,
            "theory_practice_boundary": boundary,
        },
        "migration": migration,
    }
