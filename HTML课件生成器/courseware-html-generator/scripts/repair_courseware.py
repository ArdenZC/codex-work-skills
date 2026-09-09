"""Perform safe, deterministic Courseware Contract repair rounds.

Only omissions that can be derived from the same contract are repaired here:
semantic IDs are copied from canonical facts, intent fields are shaped from an
existing script, and a minute total is reconciled from already declared page
parts.  The helper never invents a missing fact, extension plan, or lecture
script; those remain Agent-authored repairs.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path
from typing import Any

from content_contract import TEACHING_INTENT_FIELDS, normalize_content, validate_content


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _sentences(value: str) -> list[str]:
    pieces = [piece.strip() for piece in value.replace("\n", " ").split("。") if piece.strip()]
    return pieces or ([value.strip()] if value.strip() else [])


def _derived_intent(slide: dict[str, Any]) -> dict[str, str] | None:
    script = _text(slide.get("speaker_script"))
    title = _text(slide.get("title")) or "本页主题"
    sentences = _sentences(script)
    if not sentences:
        return None
    first, last = sentences[0], sentences[-1]
    middle = "。".join(sentences[: min(3, len(sentences))]) + "。"
    return {
        "opening": first,
        "core_explanation": middle,
        "example": last,
        "misconception": f"围绕“{title}”检查学生是否把相邻概念混用。",
        "question": f"请学生用自己的话解释“{title}”并指出一个判断依据。",
        "transition": f"下一页继续把“{title}”放进新的例子或操作步骤中。",
    }


def _derived_slide_units(slide_id: str, facts: list[dict[str, Any]]) -> list[str]:
    return sorted({
        str(unit_id)
        for fact in facts
        if isinstance(fact, dict) and slide_id in fact.get("source_slide_ids", [])
        for unit_id in fact.get("learning_unit_ids", [])
        if isinstance(unit_id, str) and unit_id.strip()
    })


def _repair_round(content: dict[str, Any], actions: list[dict[str, Any]], round_number: int) -> bool:
    changed = False
    facts = [item for item in content.get("canonical_facts", []) if isinstance(item, dict)]
    for index, slide in enumerate(content.get("slides", [])):
        if not isinstance(slide, dict):
            continue
        location = f"slides[{index}]"
        unit_ids = slide.get("learning_unit_ids")
        if not isinstance(unit_ids, list) or not unit_ids:
            derived = _derived_slide_units(str(slide.get("id", "")), facts)
            if derived:
                slide["learning_unit_ids"] = derived
                actions.append({"round": round_number, "field": f"{location}.learning_unit_ids", "method": "canonical_facts.source_slide_ids", "value": derived})
                changed = True
        intent = slide.get("teaching_intent")
        if not isinstance(intent, dict):
            intent = {}
        derived_intent = _derived_intent(slide)
        if derived_intent:
            missing = [field for field in TEACHING_INTENT_FIELDS if not _text(intent.get(field)).strip()]
            if missing:
                for field in missing:
                    intent[field] = derived_intent[field]
                slide["teaching_intent"] = intent
                actions.append({"round": round_number, "field": f"{location}.teaching_intent", "method": "existing speaker_script and slide title", "filled": missing})
                changed = True
        lecture = slide.get("lecture_minutes")
        activity = slide.get("activity_minutes")
        suggested = slide.get("suggested_minutes")
        if isinstance(lecture, int) and not isinstance(lecture, bool) and isinstance(activity, int) and not isinstance(activity, bool):
            total = lecture + activity
            if total > 0 and suggested != total:
                slide["suggested_minutes"] = total
                actions.append({"round": round_number, "field": f"{location}.suggested_minutes", "method": "lecture_minutes + activity_minutes", "value": total})
                changed = True
    return changed


def repair_content(content: Any, *, base_dir: Path | None = None, max_rounds: int = 2) -> dict[str, Any]:
    normalized, migration = normalize_content(content)
    if not isinstance(normalized, dict):
        return {"status": "fail", "errors": ["content root must be an object"], "warnings": [], "actions": [], "rounds": 0, "migration": migration, "content": normalized}
    repaired = copy.deepcopy(normalized)
    actions: list[dict[str, Any]] = []
    report = validate_content(repaired, base_dir=base_dir)
    rounds_used = 0
    round_limit = min(max(0, max_rounds), 2)
    for round_number in range(1, round_limit + 1):
        if report["status"] == "pass":
            break
        rounds_used = round_number
        if not _repair_round(repaired, actions, round_number):
            break
        report = validate_content(repaired, base_dir=base_dir)
    if report["status"] != "pass":
        report = dict(report)
        report["manual_repair_required"] = [error for error in report.get("errors", []) if any(token in error for token in ("speaker_script", "delivery_track", "extension", "learning_unit_ids", "canonical"))]
    return {
        "status": "pass" if report["status"] == "pass" else "fail",
        "errors": report.get("errors", []),
        "warnings": report.get("warnings", []),
        "actions": actions,
        "rounds": rounds_used,
        "round_limit": round_limit,
        "migration": migration,
        "content": repaired,
        "validation": report,
    }


def _copy_assets(input_path: Path, output_path: Path, content: dict[str, Any]) -> None:
    for asset in content.get("assets", []):
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            continue
        relative = Path(asset["path"])
        if relative.is_absolute() or ".." in relative.parts:
            continue
        source = (input_path.parent / relative).resolve()
        target = (output_path.parent / relative).resolve()
        try:
            source.relative_to(input_path.parent.resolve())
            target.relative_to(output_path.parent.resolve())
        except ValueError:
            continue
        if source.is_file() and source != output_path.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-json", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--max-rounds", type=int, default=2)
    args = parser.parse_args(argv)
    source = args.content_json.expanduser().resolve()
    target = args.output_json.expanduser().resolve()
    try:
        if source == target:
            raise ValueError("repair output must not overwrite the Agent input contract")
        raw = json.loads(source.read_text(encoding="utf-8"))
        result = repair_content(raw, base_dir=source.parent, max_rounds=args.max_rounds)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result["content"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        _copy_assets(source, target, result["content"] if isinstance(result["content"], dict) else {})
        public = {key: value for key, value in result.items() if key not in {"content", "validation"}}
        public["validation"] = result.get("validation", {})
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "pass" else 1
    except Exception as exc:  # noqa: BLE001 - CLI keeps repair evidence machine-readable
        print(json.dumps({"status": "fail", "errors": [str(exc)], "actions": [], "rounds": 0}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
