"""Deterministic source-truth and cross-material fact verification.

The contract validator checks shape.  This module checks whether a canonical
fact can be traced to a supplied raw source and whether the same fact keeps
the same verifiable token across Courseware, Practice, and teacher material.
It intentionally uses adapters and small deterministic evaluators instead of
model confidence or semantic guesswork.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable


TRUTH_MODES = {"strict", "migration-trust"}
VERIFICATION_STATUSES = {"verified", "source-supported", "inferred", "unverified"}
PEDAGOGICAL_KINDS = {"pedagogical-inference", "pedagogical", "teaching-judgment"}
CELL_ADDRESS_PATTERN = re.compile(r"(?<![A-Za-z0-9])\$?[A-Z]{1,3}\$?\d+(?![A-Za-z0-9])")
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9])")
DATE_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)(?![A-Za-z0-9])")
FORMULA_PATTERN = re.compile(r"(?<![A-Za-z0-9])=[^\n，。；;]{1,100}")
USAGE_INTERNAL_KEYS = {
    "id", "source_slide_ids", "learning_unit_ids", "canonical_fact_ids", "knowledge_link_ids",
    "task_ids", "minutes", "estimated_minutes", "suggested_minutes", "lecture_minutes", "activity_minutes",
    "session_minutes", "prepared_minutes", "core_minutes", "extension_minutes", "verification", "evidence",
    "source_refs", "locator", "editable_gaps", "todo_count", "answer_index", "correct", "status",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _resolve_source(source_root: Path, source_id: Any) -> tuple[Path | None, str | None]:
    if not isinstance(source_id, str) or not source_id.strip():
        return None, "evidence.source_id must be a non-empty relative path"
    candidate = Path(source_id)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, f"evidence source escapes source root: {source_id}"
    root = source_root.expanduser().resolve()
    path = (root / candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None, f"evidence source escapes source root: {source_id}"
    if not path.is_file():
        return None, f"evidence source does not exist: {source_id}"
    return path, None


def excel_column_letter(column_index: int) -> str:
    """Return the one-based worksheet column label without an Excel library."""

    if not isinstance(column_index, int) or isinstance(column_index, bool) or column_index < 1:
        raise ValueError("column_index must be a positive integer")
    value = column_index
    letters: list[str] = []
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _normalise_cell(value: Any) -> str:
    return re.sub(r"\$", "", _text(value)).upper()


def _read_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError("CSV has no header row")
    headers = [str(item).strip() for item in rows[0]]
    if not headers or any(not item for item in headers):
        raise ValueError("CSV header contains an empty field")
    if len(headers) != len(set(headers)):
        raise ValueError("CSV header contains duplicate fields")
    data_rows = [row for row in rows[1:] if row and any(str(cell).strip() for cell in row)]
    if any(len(row) != len(headers) for row in data_rows):
        raise ValueError("CSV data row width does not match the header")
    return {"headers": headers, "rows": data_rows, "header_row": 1}


def build_csv_source_model(source_root: Path, source_id: str) -> dict[str, Any]:
    """Build the shared CSV semantic model used by all fact verifiers."""

    path, error = _resolve_source(source_root, source_id)
    if error or path is None:
        raise ValueError(error or f"cannot resolve CSV source: {source_id}")
    if path.suffix.casefold() != ".csv":
        raise ValueError(f"CSV adapter requires a .csv source: {source_id}")
    model = _read_csv(path)
    model.update({"source_id": source_id.replace("\\", "/"), "sha256": _sha256(path)})
    from formula_truth import table_model
    model['columns'] = table_model(path)['columns']
    return model


def _fact_status(fact: dict[str, Any]) -> str | None:
    verification = fact.get("verification")
    if not isinstance(verification, dict):
        return None
    status = verification.get("status")
    return status if status in VERIFICATION_STATUSES else _text(status) or None


def _fact_kind(fact: dict[str, Any]) -> str:
    return _text(fact.get("kind")).strip().casefold()


def _fact_level(fact: dict[str, Any]) -> int:
    verification = fact.get("verification")
    if isinstance(verification, dict) and isinstance(verification.get("level"), int):
        level = verification["level"]
        if level in {1, 2, 3, 4}:
            return level
    kind = _fact_kind(fact)
    if kind in PEDAGOGICAL_KINDS or "pedagogical" in kind:
        return 4
    if any(token in kind for token in ("structured", "computed", "code-derived", "deterministic")):
        return 1
    if any(token in kind for token in ("relationship", "model", "inferred", "derived")):
        return 3
    return 2


def _is_pedagogical(fact: dict[str, Any]) -> bool:
    return _fact_level(fact) == 4 or _fact_kind(fact) in PEDAGOGICAL_KINDS


def _verification(fact: dict[str, Any]) -> dict[str, Any]:
    value = fact.get("verification")
    return value if isinstance(value, dict) else {}


def _expected_value(fact: dict[str, Any]) -> Any:
    verification = _verification(fact)
    for field in ("expected_value", "expected_result"):
        if field in verification:
            return verification[field]
    return None


def _evidence_items(fact: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _list(fact.get("evidence")) if isinstance(item, dict)]


def _line_locator_ok(text: str, locator: Any, quote: str) -> bool:
    if not isinstance(locator, dict):
        return True
    start = locator.get("line_start", locator.get("line"))
    end = locator.get("line_end", start)
    if start is None:
        return True
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return False
    lines = text.splitlines()
    if end > len(lines):
        return False
    return quote in "\n".join(lines[start - 1:end])


def _verify_text_evidence(source_root: Path, evidence: dict[str, Any], location: str) -> dict[str, Any]:
    path, error = _resolve_source(source_root, evidence.get("source_id"))
    result: dict[str, Any] = {
        "location": location,
        "source_id": evidence.get("source_id"),
        "evidence_type": evidence.get("evidence_type"),
        "status": "fail",
        "errors": [],
    }
    if error or path is None:
        result["errors"].append(error or "source cannot be resolved")
        return result
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        result["errors"].append(f"text source is not UTF-8: {exc}")
        return result
    quote = evidence.get("quote")
    if not _non_empty(quote):
        result["errors"].append("text evidence requires a non-empty quote")
    elif quote not in text:
        result["errors"].append("evidence quote is not present in the source")
    elif not _line_locator_ok(text, evidence.get("locator"), quote):
        result["errors"].append("evidence quote is outside the declared line locator")
    result.update({"status": "pass" if not result["errors"] else "fail", "sha256": _sha256(path), "locator": evidence.get("locator")})
    return result


def _csv_locator(model: dict[str, Any], evidence: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    locator = evidence.get("locator")
    errors: list[str] = []
    if not isinstance(locator, dict):
        return None, ["structured CSV evidence requires an object locator"]
    headers = model["headers"]
    field = locator.get("field", locator.get("header"))
    if not isinstance(field, str) or field not in headers:
        errors.append(f"CSV locator.field is not a header: {field}")
        return None, errors
    data_index = locator.get("data_row_index", locator.get("record_index"))
    worksheet_row = locator.get("worksheet_row")
    if data_index is None and isinstance(worksheet_row, int):
        data_index = worksheet_row - int(model.get("header_row", 1))
    if not isinstance(data_index, int) or isinstance(data_index, bool) or data_index < 1:
        errors.append("CSV locator.data_row_index must be a positive one-based index")
        return None, errors
    if data_index > len(model["rows"]):
        errors.append(f"CSV data row is out of range: {data_index}")
        return None, errors
    column_index = headers.index(field) + 1
    derived = {
        "field": field,
        "data_row_index": data_index,
        "header_row": int(model.get("header_row", 1)),
        "worksheet_row": int(model.get("header_row", 1)) + data_index,
        "column_index": column_index,
        "column_letter": excel_column_letter(column_index),
        "cell_address": f"{excel_column_letter(column_index)}{int(model.get('header_row', 1)) + data_index}",
        "value": model["rows"][data_index - 1][column_index - 1],
    }
    record_id = locator.get("record_id")
    if record_id is not None and str(record_id) != str(model["rows"][data_index - 1][0]):
        errors.append(f"CSV locator.record_id does not match data row {data_index}")
    for field_name in ("worksheet_row", "column_index", "column_letter"):
        if field_name not in locator:
            continue
        actual = locator[field_name]
        expected = derived[field_name]
        if _normalise_cell(actual) != _normalise_cell(expected) if field_name == "column_letter" else actual != expected:
            errors.append(f"CSV locator.{field_name}={actual!r} disagrees with derived {expected!r}")
    return derived, errors


def _number(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _same_number(left: Any, right: Any) -> bool:
    left_value, right_value = _number(left), _number(right)
    return left_value is not None and right_value is not None and math.isclose(left_value, right_value, rel_tol=1e-9, abs_tol=1e-9)


def _verify_csv_evidence(source_root: Path, fact: dict[str, Any], evidence: dict[str, Any], location: str) -> dict[str, Any]:
    source_id = evidence.get("source_id")
    result: dict[str, Any] = {"location": location, "source_id": source_id, "status": "fail", "errors": []}
    try:
        model = build_csv_source_model(source_root, str(source_id))
    except Exception as exc:  # noqa: BLE001 - evidence stays machine-readable
        result["errors"].append(str(exc))
        return result
    verification = _verification(fact)
    method = _text(verification.get("method") or verification.get("verifier")).casefold()
    if method in {"csv-cell-address", "csv-cell", "structured-cell"}:
        derived, errors = _csv_locator(model, evidence)
        result["derived"] = derived
        result["errors"].extend(errors)
        expected = _expected_value(fact)
        if expected is None:
            result["errors"].append("csv-cell-address verification requires verification.expected_value")
        elif derived and _normalise_cell(expected) != _normalise_cell(derived["cell_address"]):
            result["errors"].append(f"canonical fact expects {expected!r}, source derives {derived['cell_address']!r}")
        if "value" in evidence and derived and str(evidence["value"]) != str(derived["value"]):
            result["errors"].append(f"evidence.value {evidence['value']!r} does not match source value {derived['value']!r}")
    elif method in {"csv-sum", "csv-count", "csv-row-count", "structured-computed"}:
        locator = evidence.get("locator") if isinstance(evidence.get("locator"), dict) else {}
        field = locator.get("field")
        rows = model["rows"]
        headers = model["headers"]
        if method == "csv-count" or method == "csv-row-count":
            actual: float = float(len(rows))
        elif isinstance(field, str) and field in headers:
            column = headers.index(field)
            actual = sum(_number(row[column]) or 0 for row in rows)
        else:
            result["errors"].append("computed CSV evidence requires locator.field")
            actual = float("nan")
        where = locator.get("where")
        if isinstance(where, dict) and field != where.get("field") and where.get("field") in headers:
            where_column = headers.index(where["field"])
            selected = [row for row in rows if str(row[where_column]) == str(where.get("equals"))]
            if method in {"csv-count", "csv-row-count"}:
                actual = float(len(selected))
            elif isinstance(field, str) and field in headers:
                actual = sum(_number(row[headers.index(field)]) or 0 for row in selected)
        expected = _expected_value(fact)
        result["actual"] = int(actual) if math.isfinite(actual) and actual.is_integer() else actual
        if expected is None:
            result["errors"].append("computed CSV verification requires expected_value or expected_result")
        elif not _same_number(expected, actual):
            result["errors"].append(f"computed fact expects {expected!r}, source computes {result['actual']!r}")
    else:
        result["errors"].append(f"unsupported deterministic CSV verifier: {method or 'missing'}")
    result.update({"status": "pass" if not result["errors"] else "fail", "sha256": model["sha256"]})
    return result


def _evidence_type(evidence: dict[str, Any]) -> str:
    return _text(evidence.get("evidence_type")).casefold().replace("_", "-")


def validate_fact(fact: dict[str, Any], source_root: Path, *, mode: str = "strict", location: str = "canonical_fact") -> dict[str, Any]:
    """Validate one fact against its declared evidence."""

    if mode not in TRUTH_MODES:
        raise ValueError(f"unsupported truth mode: {mode}")
    errors: list[str] = []
    warnings: list[str] = []
    status = _fact_status(fact)
    kind = _fact_kind(fact)
    evidence = _evidence_items(fact)
    if status is not None and status not in VERIFICATION_STATUSES:
        errors.append(f"{location}.verification.status is invalid: {status}")
    if not evidence:
        if _is_pedagogical(fact):
            warnings.append(f"{location} is pedagogical inference and has no deterministic source evidence")
        elif mode == "strict":
            errors.append(f"{location} requires source evidence in strict mode")
        else:
            warnings.append(f"{location} has no source evidence; legacy trust does not mark it verified")
    if mode == "strict" and not _is_pedagogical(fact) and status not in {"verified", "source-supported", "inferred"}:
        errors.append(f"{location}.verification.status must be verified, source-supported, or inferred in strict mode")
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(evidence):
        evidence_location = f"{location}.evidence[{index}]"
        evidence_kind = _evidence_type(item)
        if evidence_kind in {"direct-text", "text", "source-supported", "plain-text"}:
            finding = _verify_text_evidence(source_root, item, evidence_location)
        elif evidence_kind in {"structured-data", "csv", "computed", "csv-computed"} or kind in {"structured-data-fact", "computed-fact"}:
            finding = _verify_csv_evidence(source_root, fact, item, evidence_location) if str(item.get("source_id", "")).casefold().endswith(".csv") else _verify_text_evidence(source_root, item, evidence_location)
        else:
            finding = {"location": evidence_location, "status": "fail", "errors": [f"unsupported evidence_type: {item.get('evidence_type')}"], "source_id": item.get("source_id")}
        findings.append(finding)
        if finding.get("status") != "pass":
            errors.extend(f"{evidence_location}: {error}" for error in finding.get("errors", []))
    if findings and status in {"verified", "source-supported", "inferred"} and not any(item.get("status") == "pass" for item in findings):
        errors.append(f"{location} declares {status} but no evidence verified")
    return {
        "id": fact.get("id"),
        "kind": fact.get("kind"),
        "level": _fact_level(fact),
        "verification_status": status or "unverified",
        "expected": _expected_value(fact),
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "evidence": findings,
    }


def _all_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _all_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_strings(child)


def _usage_strings(value: Any, key: str | None = None) -> Iterable[str]:
    if isinstance(value, str):
        if key not in USAGE_INTERNAL_KEYS:
            yield value
    elif isinstance(value, dict):
        for child_key, child in value.items():
            if child_key in USAGE_INTERNAL_KEYS:
                continue
            yield from _usage_strings(child, child_key)
    elif isinstance(value, list):
        for child in value:
            yield from _usage_strings(child, key)


def _usage_text(value: Any) -> str:
    return "\n".join(_usage_strings(value))


def build_fact_usage_registry(courseware: dict[str, Any], practice: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Collect explicit fact links without inferring missing IDs."""

    registry: dict[str, list[dict[str, Any]]] = {}

    def add(fact_ids: Any, location: str, value: Any, *, core: bool, material: str) -> None:
        field = "speaker_script" if material == "courseware" and isinstance(value, dict) and _non_empty(value.get("speaker_script")) else "content"
        for fact_id in _list(fact_ids):
            if isinstance(fact_id, str) and fact_id.strip():
                registry.setdefault(fact_id, []).append({"location": location, "core": core, "material": material, "field": field, "text": _usage_text(value)})

    for index, slide in enumerate(_list(courseware.get("slides"))):
        if not isinstance(slide, dict):
            continue
        add(slide.get("canonical_fact_ids", []), f"courseware.slides[{index}]", slide, core=slide.get("delivery_track", "core") == "core", material="courseware")
    if isinstance(practice, dict):
        for collection in ("knowledge_links", "tasks", "learning_center", "study_guide", "foundation_kit"):
            for index, item in enumerate(_list(practice.get(collection))):
                if not isinstance(item, dict):
                    continue
                core = collection == "tasks" and item.get("level") == "core"
                add(item.get("canonical_fact_ids", []), f"practice.{collection}[{index}]", item, core=core, material="practice")
        references = practice.get("teacher_reference", {}).get("task_references", []) if isinstance(practice.get("teacher_reference"), dict) else []
        task_levels = {str(item.get("id")): item.get("level") for item in _list(practice.get("tasks")) if isinstance(item, dict)}
        for index, item in enumerate(_list(references)):
            if isinstance(item, dict):
                add(item.get("canonical_fact_ids", []), f"practice.teacher_reference.task_references[{index}]", item, core=task_levels.get(str(item.get("task_id"))) == "core", material="teacher-reference")
    return registry


def _expected_tokens(fact: dict[str, Any]) -> list[str]:
    verification = _verification(fact)
    tokens = [str(item) for item in _list(verification.get("key_tokens")) if _non_empty(item)]
    expected = _expected_value(fact)
    if expected is not None and str(expected).strip():
        tokens.append(str(expected))
    return list(dict.fromkeys(tokens))


def _token_conflicts(fact: dict[str, Any], usage_text: str) -> list[str]:
    verification = _verification(fact)
    expected = _expected_value(fact)
    family = _text(verification.get("token_family")).casefold()
    if not family and expected is not None and CELL_ADDRESS_PATTERN.fullmatch(str(expected).strip()):
        family = "cell-address"
    if family in {"cell-address", "cell", "spreadsheet-cell"}:
        expected_cells = {_normalise_cell(item) for item in _expected_tokens(fact) if CELL_ADDRESS_PATTERN.fullmatch(str(item).strip())}
        allowed = {_normalise_cell(item) for item in _list(verification.get("allowed_tokens")) if CELL_ADDRESS_PATTERN.fullmatch(str(item).strip())}
        allowed.update(expected_cells)
        observed = {_normalise_cell(item) for item in CELL_ADDRESS_PATTERN.findall(usage_text)}
        return sorted(observed - allowed)
    if family in {"number", "numeric", "value"}:
        expected_numbers = {str(item).strip() for item in _expected_tokens(fact) if NUMBER_PATTERN.fullmatch(str(item).strip())}
        allowed_numbers = {str(item).strip() for item in _list(verification.get("allowed_tokens")) if NUMBER_PATTERN.fullmatch(str(item).strip())}
        allowed_numbers.update(expected_numbers)
        observed = {item for item in NUMBER_PATTERN.findall(usage_text) if item not in allowed_numbers}
        return sorted(observed)
    if family in {"date", "datetime"}:
        expected_dates = {str(item).strip() for item in _expected_tokens(fact) if DATE_PATTERN.fullmatch(str(item).strip())}
        allowed_dates = {str(item).strip() for item in _list(verification.get("allowed_tokens")) if DATE_PATTERN.fullmatch(str(item).strip())}
        allowed_dates.update(expected_dates)
        observed = {item for item in DATE_PATTERN.findall(usage_text) if item not in allowed_dates}
        return sorted(observed)
    if family in {"formula", "expression"}:
        expected_formulas = {str(item).strip() for item in _expected_tokens(fact) if str(item).strip().startswith("=")}
        allowed_formulas = {str(item).strip() for item in _list(verification.get("allowed_tokens")) if str(item).strip().startswith("=")}
        allowed_formulas.update(expected_formulas)
        observed = {item.strip() for item in FORMULA_PATTERN.findall(usage_text) if item.strip() not in allowed_formulas}
        return sorted(observed)
    conflict_tokens = [str(item) for item in _list(verification.get("conflict_tokens")) if _non_empty(item)]
    expected_tokens = {str(item) for item in _expected_tokens(fact)}
    allowed_tokens = expected_tokens | {str(item) for item in _list(verification.get("allowed_tokens")) if _non_empty(item)}
    return sorted({token for token in conflict_tokens if token not in allowed_tokens and token in usage_text})
    return []


def validate_cross_material_consistency(courseware: dict[str, Any], practice: dict[str, Any] | None = None, *, mode: str = "strict") -> dict[str, Any]:
    """Check explicit fact links and key verifiable tokens across materials."""

    if mode not in TRUTH_MODES:
        raise ValueError(f"unsupported truth mode: {mode}")
    facts = {str(item.get("id")): item for item in _list(courseware.get("canonical_facts")) if isinstance(item, dict) and _non_empty(item.get("id"))}
    registry = build_fact_usage_registry(courseware, practice)
    errors: list[str] = []
    warnings: list[str] = []
    findings: list[dict[str, Any]] = []
    for fact_id, usages in sorted(registry.items()):
        fact = facts.get(fact_id)
        if fact is None:
            errors.append(f"fact usage references unknown canonical fact: {fact_id}")
            continue
        if _fact_status(fact) == "unverified" and any(item.get("core") for item in usages):
            errors.append(f"unverified canonical fact is used by a core teaching surface: {fact_id}")
        if _fact_level(fact) == 4 and any(item.get("core") for item in usages):
            errors.append(f"pedagogical inference cannot be the sole core fact: {fact_id}")
        for usage in usages:
            conflicts = _token_conflicts(fact, usage.get("text", ""))
            item = {"fact_id": fact_id, "location": usage.get("location"), "material": usage.get("material"), "field": usage.get("field"), "core": usage.get("core"), "status": "pass" if not conflicts else "fail", "conflicting_tokens": conflicts}
            findings.append(item)
            if conflicts:
                errors.append(f"FACT_CONTRADICTION {fact_id} at {usage.get('location')} ({usage.get('material')}.{usage.get('field')}): {', '.join(conflicts)}")
        if not usages:
            warnings.append(f"canonical fact has no explicit material usage: {fact_id}")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "facts": len(facts),
        "usages": sum(len(items) for items in registry.values()),
        "findings": findings,
        "registry": {key: [{field: item[field] for field in ("location", "material", "field", "core")} for item in values] for key, values in sorted(registry.items())},
    }


def validate_source_truth(courseware: dict[str, Any], source_root: Path, practice: dict[str, Any] | None = None, *, mode: str = "strict") -> dict[str, Any]:
    """Run source verification and optional cross-material consistency."""

    if mode not in TRUTH_MODES:
        raise ValueError(f"unsupported truth mode: {mode}")
    errors: list[str] = []
    warnings: list[str] = []
    fact_reports: list[dict[str, Any]] = []
    facts = _list(courseware.get("canonical_facts"))
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            errors.append(f"canonical_facts[{index}] must be an object")
            continue
        report = validate_fact(fact, source_root, mode=mode, location=f"canonical_facts[{index}]")
        fact_reports.append(report)
        errors.extend(report["errors"])
        warnings.extend(report["warnings"])
    consistency = validate_cross_material_consistency(courseware, practice, mode=mode)
    errors.extend(consistency["errors"])
    warnings.extend(consistency["warnings"])
    from formula_truth import verify_formulas
    formula_reports = [verify_formulas(c, source_root) for c in (courseware, practice) if c is not None]
    errors.extend(e for report in formula_reports for e in report['errors'])
    return {
        "status": "pass" if not errors else "fail",
        "mode": mode,
        "source_root": str(source_root.expanduser().resolve()),
        "errors": errors,
        "warnings": warnings,
        "facts": fact_reports,
        "cross_material": consistency,
        "formula_truth": formula_reports,
    }


def source_freeze_sha256(manifest_path: Path) -> str:
    return _sha256(manifest_path.expanduser().resolve())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courseware-json", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--practice-json", type=Path)
    parser.add_argument("--mode", choices=sorted(TRUTH_MODES), default="strict")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    try:
        courseware = json.loads(args.courseware_json.expanduser().resolve().read_text(encoding="utf-8"))
        practice = json.loads(args.practice_json.expanduser().resolve().read_text(encoding="utf-8")) if args.practice_json else None
        report = validate_source_truth(courseware, args.source_root, practice, mode=args.mode)
    except Exception as exc:  # noqa: BLE001 - CLI keeps evidence machine-readable
        report = {"status": "fail", "mode": args.mode, "errors": [str(exc)], "warnings": []}
    if args.output_json:
        args.output_json.expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        args.output_json.expanduser().resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
