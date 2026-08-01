from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from docx.oxml.ns import qn


W_BODY = qn("w:body")
W_BOOKMARK_START = qn("w:bookmarkStart")
W_BOOKMARK_END = qn("w:bookmarkEnd")
W_CELL = qn("w:tc")
W_PARAGRAPH = qn("w:p")


@dataclass(frozen=True)
class BookmarkRecord:
    """A paired Word bookmark or an orphaned bookmark boundary."""

    name: str
    bookmark_id: str
    start: Any | None
    end: Any | None
    story: str = "main"

    @property
    def paired(self) -> bool:
        return self.start is not None and self.end is not None


def _document_element(document_or_element: Any) -> Any:
    if hasattr(document_or_element, "element"):
        return document_or_element.element
    return document_or_element


def _main_body(document_or_element: Any) -> Any:
    element = _document_element(document_or_element)
    if getattr(element, "tag", None) == W_BODY:
        return element
    body = element.find(W_BODY)
    if body is None:
        raise ValueError("Main document body is missing")
    return body


def _records_for_root(root: Any, story: str) -> list[BookmarkRecord]:
    starts: dict[str, list[Any]] = defaultdict(list)
    ends: dict[str, list[Any]] = defaultdict(list)
    order: list[tuple[str, Any]] = []
    for node in root.iter():
        if node.tag == W_BOOKMARK_START:
            bookmark_id = str(node.get(qn("w:id"), ""))
            starts[bookmark_id].append(node)
            order.append(("start", node))
        elif node.tag == W_BOOKMARK_END:
            bookmark_id = str(node.get(qn("w:id"), ""))
            ends[bookmark_id].append(node)
            order.append(("end", node))

    records: list[BookmarkRecord] = []
    seen_ids: set[str] = set()
    for kind, node in order:
        bookmark_id = str(node.get(qn("w:id"), ""))
        if kind == "start":
            # A bookmark id must have exactly one start and one end. Duplicate ids
            # remain visible as orphaned records so validation can explain them.
            start_nodes = starts[bookmark_id]
            end_nodes = ends.get(bookmark_id, [])
            end = end_nodes[0] if len(start_nodes) == 1 and len(end_nodes) == 1 else None
            records.append(
                BookmarkRecord(
                    name=str(node.get(qn("w:name"), "")),
                    bookmark_id=bookmark_id,
                    start=node,
                    end=end,
                    story=story,
                )
            )
            seen_ids.add(bookmark_id)
        elif bookmark_id not in seen_ids:
            records.append(BookmarkRecord(name="", bookmark_id=bookmark_id, start=None, end=node, story=story))
    return records


def list_bookmarks(document_or_element: Any) -> list[BookmarkRecord]:
    """List only bookmarks in the main document body, preserving XML boundaries."""
    return _records_for_root(_main_body(document_or_element), "main")


def _record_from_value(document_or_element: Any, bookmark: BookmarkRecord | Any) -> BookmarkRecord:
    if isinstance(bookmark, BookmarkRecord):
        return bookmark
    bookmark_id = str(getattr(bookmark, "get", lambda *_args: "")(qn("w:id"), ""))
    bookmark_name = str(getattr(bookmark, "get", lambda *_args: "")(qn("w:name"), ""))
    for record in list_bookmarks(document_or_element):
        if record.bookmark_id == bookmark_id and (not bookmark_name or record.name == bookmark_name):
            return record
    raise ValueError("Bookmark boundary does not belong to the main document")


def find_bookmark(document_or_element: Any, name: str) -> BookmarkRecord | None:
    """Find one named main-document bookmark; duplicate names are an error."""
    matches = [record for record in list_bookmarks(document_or_element) if record.name == name]
    if len(matches) > 1:
        raise ValueError(f"Duplicate bookmark name {name}: {len(matches)} occurrences")
    if not matches:
        return None
    if not matches[0].paired:
        raise ValueError(f"Bookmark {name} has an orphaned start/end boundary")
    return matches[0]


def _nearest_ancestor(element: Any | None, tag: str) -> Any | None:
    current = element
    while current is not None:
        if current.tag == tag:
            return current
        current = current.getparent()
    return None


def bookmark_parent_paragraph(document_or_element: Any, bookmark: BookmarkRecord | Any) -> Any | None:
    record = _record_from_value(document_or_element, bookmark)
    return _nearest_ancestor(record.start, W_PARAGRAPH)


def bookmark_parent_cell(document_or_element: Any, bookmark: BookmarkRecord | Any) -> Any | None:
    record = _record_from_value(document_or_element, bookmark)
    return _nearest_ancestor(record.start, W_CELL)


def bookmark_location(document_or_element: Any, name: str) -> tuple[tuple[str, int], ...] | None:
    """Return an XML ancestry signature for one named main-document bookmark."""
    record = find_bookmark(document_or_element, name)
    if record is None:
        return None
    body = _main_body(document_or_element)
    current = record.start
    path: list[tuple[str, int]] = []
    while current is not None and current is not body:
        parent = current.getparent()
        if parent is None:
            break
        same_tag = [node for node in parent if node.tag == current.tag]
        path.append((str(current.tag), same_tag.index(current)))
        current = parent
    path.append((str(body.tag), 0))
    return tuple(reversed(path))


def _story_roots(document: Any) -> Iterable[tuple[str, Any]]:
    yield "main", _main_body(document)
    package = getattr(getattr(document, "part", None), "package", None)
    if package is None:
        return
    for part in package.iter_parts():
        part_name = str(getattr(part, "partname", ""))
        if "/word/header" in part_name or "/word/footer" in part_name:
            element = getattr(part, "element", None)
            if element is not None:
                yield part_name, element


def validate_bookmark_inventory(
    document: Any,
    required_names: Iterable[str] = (),
    expected_containers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate pairing, uniqueness, location, and required semantic containers.

    The returned report is intentionally JSON-friendly except for the XML elements
    kept in the records list, which callers may use for anchored writes.
    """
    required = [str(name) for name in required_names]
    expected = {str(name): str(value) for name, value in (expected_containers or {}).items()}
    main_records = list_bookmarks(document)
    all_records = [record for story, root in _story_roots(document) for record in _records_for_root(root, story)]

    named_main = [record.name for record in main_records if record.name]
    named_all = [record.name for record in all_records if record.name]
    start_id_counts = Counter(record.bookmark_id for record in all_records if record.start is not None)
    end_id_counts = Counter(record.bookmark_id for record in all_records if record.end is not None)
    duplicate_ids = sorted(
        bookmark_id
        for bookmark_id in set(start_id_counts) | set(end_id_counts)
        if start_id_counts[bookmark_id] != 1 or end_id_counts[bookmark_id] != 1
    )
    duplicate_names = sorted(name for name, count in Counter(named_all).items() if count > 1)
    orphaned = sorted(
        f"{record.story}:{record.name or '<unnamed>'}#{record.bookmark_id}"
        for record in all_records
        if not record.paired
    )
    outside_main = sorted(
        name
        for name in set(named_all)
        if name not in named_main
    )
    main_by_name = {record.name: record for record in main_records if record.name and record.paired}
    missing = sorted(name for name in required if name not in main_by_name)
    container_errors: list[str] = []
    for name, expected_container in expected.items():
        record = main_by_name.get(name)
        if record is None:
            continue
        paragraph = bookmark_parent_paragraph(document, record)
        cell = bookmark_parent_cell(document, record)
        actual_container = "cell" if cell is not None else "document_paragraph" if paragraph is not None else "unknown"
        if actual_container != expected_container:
            container_errors.append(
                f"bookmark {name} expected container {expected_container}, got {actual_container}"
            )

    errors: list[str] = []
    if missing:
        errors.append("missing required bookmarks: " + ", ".join(missing))
    if duplicate_names:
        errors.append("duplicate bookmark names: " + ", ".join(duplicate_names))
    if duplicate_ids:
        errors.append("bookmark IDs are not unique and paired: " + ", ".join(duplicate_ids))
    if orphaned:
        errors.append("orphaned bookmark boundaries: " + ", ".join(orphaned))
    if outside_main:
        errors.append("required/named bookmarks outside main document: " + ", ".join(outside_main))
    errors.extend(container_errors)
    return {
        "valid": not errors,
        "required": required,
        "required_count": len(required),
        "bookmarks": sorted(name for name in named_main),
        "main_count": len(named_main),
        "preserved_count": sum(1 for name in required if name in main_by_name),
        "missing": missing,
        "duplicates": duplicate_names,
        "duplicate_ids": duplicate_ids,
        "orphaned": orphaned,
        "outside_main": outside_main,
        "container_errors": container_errors,
        "errors": errors,
        "records": main_records,
    }
