"""Read-only BIFF defined-name validation for original .xls files."""

from __future__ import annotations

import struct
from collections import Counter
from pathlib import Path
from typing import Any

import olefile
from xlrd import open_workbook

from named_range_contracts import MANAGED_NAME_PREFIX, NAMED_RANGE_CONTRACTS, required_names
from named_range_utils import (
    _NAME_RE,
    NamedRangeLocation,
    _validate_relationships,
    _validate_shapes,
    compare_named_range_inventories,
)


class XlsNamedRangeError(ValueError):
    pass


def normalize_xls_summary_information(path: Path | str) -> None:
    """Clear LibreOffice's non-deterministic SummaryInformation save time."""
    workbook_path = Path(path).expanduser().resolve()
    ole = olefile.OleFileIO(str(workbook_path), write_mode=True)
    try:
        stream_name = "\x05SummaryInformation"
        stream = bytearray(ole.openstream(stream_name).read())
        property_set_offset = 48
        if len(stream) < property_set_offset + 8:
            raise XlsNamedRangeError("SummaryInformation stream is truncated")
        property_set_size, property_count = struct.unpack_from("<II", stream, property_set_offset)
        descriptor_offset = property_set_offset + 8
        if property_set_size > len(stream) or descriptor_offset + property_count * 8 > len(stream):
            raise XlsNamedRangeError("SummaryInformation property table is invalid")
        changed = False
        for index in range(property_count):
            property_id, relative_offset = struct.unpack_from(
                "<II", stream, descriptor_offset + index * 8
            )
            if property_id != 13:
                continue
            value_offset = property_set_offset + relative_offset
            if value_offset + 12 > len(stream):
                raise XlsNamedRangeError("SummaryInformation last-save property is truncated")
            value_type = struct.unpack_from("<I", stream, value_offset)[0]
            if value_type != 0x40:
                raise XlsNamedRangeError("SummaryInformation last-save property is not FILETIME")
            stream[value_offset + 4:value_offset + 12] = b"\x00" * 8
            changed = True
        if changed:
            ole.write_stream(stream_name, bytes(stream))
    finally:
        ole.close()


def normalize_libreoffice_print_title_records(path: Path | str) -> None:
    """Keep the BIFF print-title record that Excel and LibreOffice both honor.

    LibreOffice's XLS exporter can emit both the built-in ``Print_Titles``
    record and a second ordinary ``_xlnm.Print_Titles`` record. Excel may hang
    while opening that duplicate pair. The built-in record must remain intact
    because it carries the print-area behavior used by the protected template;
    the duplicate ordinary record is renamed in place, preserving the BIFF
    record length and formula while removing the collision.
    """
    workbook_path = Path(path).expanduser().resolve()
    replacement = b"Ignored_PrintTitle"
    duplicate = b"_xlnm.Print_Titles"
    if len(replacement) != len(duplicate):
        raise XlsNamedRangeError("BIFF print-title replacement must preserve the record length")
    ole = olefile.OleFileIO(str(workbook_path), write_mode=True)
    try:
        stream = bytearray(ole.openstream("Workbook").read())
        matches: list[int] = []
        position = 0
        while position + 4 <= len(stream):
            record_type, record_length = struct.unpack_from("<HH", stream, position)
            record_start = position + 4
            record_end = record_start + record_length
            if record_end > len(stream):
                raise XlsNamedRangeError("Workbook BIFF stream contains a truncated record")
            if record_type == 0x0018:
                payload = stream[record_start:record_end]
                name_length = payload[3] if len(payload) > 3 else 0
                name_start = 15
                if (
                    name_length == len(duplicate)
                    and len(payload) >= name_start + name_length
                    and bytes(payload[name_start:name_start + name_length]) == duplicate
                ):
                    matches.append(record_start + name_start)
            position = record_end
            if record_type == 0x000A:
                break
        if len(matches) > 1:
            raise XlsNamedRangeError("Workbook contains multiple ordinary _xlnm.Print_Titles records")
        if matches:
            start = matches[0]
            stream[start:start + len(duplicate)] = replacement
            ole.write_stream("Workbook", bytes(stream))
    finally:
        ole.close()


def _managed_name_objects(book) -> list[Any]:
    return [
        item
        for item in getattr(book, "name_obj_list", [])
        if str(getattr(item, "name", "")).lower().startswith(MANAGED_NAME_PREFIX)
    ]


def _parse_name(book, item: Any) -> NamedRangeLocation:
    name = str(item.name)
    if _NAME_RE.fullmatch(name) is None or not name.startswith(MANAGED_NAME_PREFIX):
        raise XlsNamedRangeError(f"Invalid managed named range name: {name}")
    if int(getattr(item, "hidden", 0) or 0):
        raise XlsNamedRangeError(f"Managed named range must not be hidden: {name}")
    if int(getattr(item, "scope", -1)) != -1:
        raise XlsNamedRangeError(f"Managed named range must be workbook scoped: {name}")
    if any(
        int(getattr(item, attribute, 0) or 0) != 0
        for attribute in ("any_external", "any_err", "complex", "binary")
    ) or bool(getattr(item, "any_rel", False)):
        raise XlsNamedRangeError(f"Named range {name} uses an external, relative, complex, or broken reference")
    result = getattr(item, "result", None)
    refs = getattr(result, "value", None)
    if not isinstance(refs, list) or len(refs) != 1 or not hasattr(refs[0], "coords"):
        raise XlsNamedRangeError(f"Named range {name} is not one absolute worksheet rectangle")
    coords = tuple(refs[0].coords)
    if len(coords) < 6:
        raise XlsNamedRangeError(f"Named range {name} has incomplete BIFF coordinates")
    sheet_start, sheet_end, row_start, row_end, col_start, col_end = coords[:6]
    if sheet_end != sheet_start + 1:
        raise XlsNamedRangeError(f"Named range {name} targets multiple worksheets")
    if row_end <= row_start or col_end <= col_start:
        raise XlsNamedRangeError(f"Named range {name} has an empty BIFF destination")
    sheet_names = book.sheet_names()
    if sheet_start < 0 or sheet_start >= len(sheet_names):
        raise XlsNamedRangeError(f"Named range {name} targets an invalid worksheet index {sheet_start}")
    return NamedRangeLocation(
        name=name,
        scope="workbook",
        sheet=sheet_names[sheet_start],
        min_row=int(row_start) + 1,
        min_col=int(col_start) + 1,
        max_row=int(row_end),
        max_col=int(col_end),
    )


def list_xls_managed_names(path: Path | str) -> list[NamedRangeLocation]:
    book = open_workbook(str(Path(path).expanduser().resolve()), formatting_info=False)
    locations = [_parse_name(book, item) for item in _managed_name_objects(book)]
    return sorted(locations, key=lambda item: item.name)


def validate_xls_named_range_inventory(
    path: Path | str,
    contract: dict[str, Any] | None,
    variant: str,
) -> dict[str, Any]:
    """Validate the original BIFF records, never just the converted XLSX."""
    expected_names = tuple(required_names(variant))
    report: dict[str, Any] = {
        "required": sorted(expected_names),
        "required_count": len(expected_names),
        "actual_count": 0,
        "locations": {},
        "missing": [],
        "duplicate": [],
        "invalid_names": [],
        "unexpected": [],
        "scope_errors": [],
        "broken": [],
        "destination_errors": [],
        "shape_errors": [],
        "relationship_errors": [],
        "errors": [],
    }
    book = open_workbook(str(Path(path).expanduser().resolve()), formatting_info=False)
    records = _managed_name_objects(book)
    counts = Counter(str(item.name) for item in records)
    expected_set = set(expected_names)
    for name, count in sorted(counts.items()):
        if count > 1:
            report["duplicate"].append(name)
        if name not in expected_set:
            report["unexpected"].append(name)
    locations: dict[str, NamedRangeLocation] = {}
    for item in sorted(records, key=lambda value: str(value.name)):
        name = str(item.name)
        if name not in expected_set or counts[name] != 1:
            continue
        try:
            locations[name] = _parse_name(book, item)
        except XlsNamedRangeError as exc:
            message = str(exc)
            if "Invalid managed named range name" in message:
                report["invalid_names"].append(name)
            elif "workbook scoped" in message:
                report["scope_errors"].append(message)
            elif "worksheet" in message or "index" in message:
                report["destination_errors"].append(message)
            elif "rectangle" in message or "coordinates" in message or "empty" in message:
                report["shape_errors"].append(message)
            else:
                report["broken"].append(message)
    report["missing"] = sorted(expected_set - set(counts))
    _validate_shapes(locations, contract or NAMED_RANGE_CONTRACTS, expected_names, report["shape_errors"])
    _validate_relationships(locations, report["relationship_errors"])
    report["actual_count"] = len(locations)
    report["locations"] = {name: locations[name].to_dict() for name in sorted(locations)}
    report["duplicate"] = sorted(set(report["duplicate"]))
    report["unexpected"] = sorted(set(report["unexpected"]))
    report["invalid_names"] = sorted(set(report["invalid_names"]))
    for key in (
        "scope_errors",
        "broken",
        "destination_errors",
        "shape_errors",
        "relationship_errors",
    ):
        report[key] = sorted(set(report[key]))
    report["errors"] = sorted(
        set(
            [f"Missing managed named range: {name}" for name in report["missing"]]
            + [f"Duplicate managed named range: {name}" for name in report["duplicate"]]
            + [f"Unexpected managed named range: {name}" for name in report["unexpected"]]
            + report["scope_errors"]
            + report["broken"]
            + report["destination_errors"]
            + report["shape_errors"]
            + report["relationship_errors"]
        )
    )
    return report


def compare_xls_and_xlsx_named_ranges(
    xls_report: dict[str, Any],
    xlsx_report: dict[str, Any],
    names: tuple[str, ...] | None = None,
) -> list[str]:
    return compare_named_range_inventories(xls_report, xlsx_report, names)
