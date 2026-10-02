"""Validate every committed Whole-Course runtime JSON against its schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - exercised by CI setup failure
    raise SystemExit("jsonschema is required for Whole-Course schema validation; install the CI test dependency") from exc


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _validate(value: Any, schema_name: str, label: str) -> int:
    schema = _load(SCHEMAS / schema_name)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(f"{label}:{'/'.join(str(item) for item in error.absolute_path) or '<root>'}: {error.message}" for error in errors[:8])
        raise ValueError(details)
    return 1


def validate_e2e(root: Path) -> int:
    mapping = {
        "source-assets.json": "teaching-asset-inventory.schema.json",
        "knowledge-graph.json": "course-knowledge-graph.schema.json",
        "session-plans.json": "session-plan.schema.json",
        "visual-plans.json": "visual-plan.schema.json",
        "practice-plans.json": "practice-plan.schema.json",
        "external-research.json": "external-source-research.schema.json",
        "whole-course-plan-qa.json": "whole-course-plan-qa.schema.json",
        "whole-course-render-qa.json": "whole-course-render-qa.schema.json",
        "whole-course-e2e.json": "whole-course-e2e.schema.json",
        "contact-sheets/contact-sheet-evidence.json": "whole-course-contact-sheet.schema.json",
    }
    count = 0
    for relative, schema_name in mapping.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"missing runtime output: {path}")
        count += _validate(_load(path), schema_name, str(path))
    e2e = _load(root / "whole-course-e2e.json")
    count += _validate(e2e["visual_evidence"], "whole-course-visual-evidence.schema.json", f"{root / 'whole-course-e2e.json'}#visual_evidence")
    count += _validate(e2e["starter_evidence"], "whole-course-starter-evidence.schema.json", f"{root / 'whole-course-e2e.json'}#starter_evidence")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--e2e-root", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if not args.e2e_root and not args.replay:
        parser.error("one of --e2e-root or --replay is required")
    count = 0
    if args.e2e_root:
        count += validate_e2e(args.e2e_root.expanduser().resolve())
    if args.replay:
        path = args.replay.expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"missing replay output: {path}")
        count += _validate(_load(path), "whole-course-failure-replay.schema.json", str(path))
    print(json.dumps({"status": "PASS", "validated_outputs": count}, ensure_ascii=False))


if __name__ == "__main__":
    main()
