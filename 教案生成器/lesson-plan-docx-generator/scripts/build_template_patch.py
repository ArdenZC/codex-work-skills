"""Build a lesson-plan patch template without changing protected DOCX structure."""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path

import yaml
from docx import Document
from lxml import etree

from path_safety import paths_overlap


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"


def _visible_text_nodes(root: etree._Element) -> list[etree._Element]:
    return root.xpath(".//w:t", namespaces={"w": W_NS})


def _replace_visible_once(root: etree._Element, old_text: str, new_text: str) -> None:
    nodes = _visible_text_nodes(root)
    joined = "".join(node.text or "" for node in nodes)
    occurrences = joined.count(old_text)
    if occurrences != 1:
        raise ValueError(f"Expected exactly one visible occurrence of {old_text!r}, found {occurrences}")
    start = joined.index(old_text)
    end = start + len(old_text)
    cursor = 0
    first: etree._Element | None = None
    for node in nodes:
        text = node.text or ""
        node_start, node_end = cursor, cursor + len(text)
        if node_end > start and node_start < end:
            if first is None:
                first = node
                local_start = max(start - node_start, 0)
                local_end = min(end - node_start, len(text))
                node.text = text[:local_start] + new_text + text[local_end:]
            else:
                local_start = max(start - node_start, 0)
                local_end = min(end - node_start, len(text))
                node.text = text[:local_start] + text[local_end:]
        cursor = node_end
    if first is not None and any((node.text or "") for node in nodes):
        first.set(f"{{{XML_NS}}}space", "preserve")


def _replace_document_text(document_xml: bytes, replacements: list[tuple[str, str]]) -> bytes:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    try:
        root = etree.fromstring(document_xml, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"word/document.xml is not valid XML: {exc}") from exc
    for old_text, new_text in replacements:
        _replace_visible_once(root, old_text, new_text)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _canonical_paths() -> set[Path]:
    skill_dir = Path(__file__).resolve().parents[1]
    package_root = skill_dir / "assets" / "templates" / "lesson-plan"
    protected = {
        skill_dir / "assets" / "lesson-plan-template.docx",
    }
    for version in ("v1.0.0", "v1.1.0", "v1.1.1", "v1.1.2"):
        protected.add(package_root / version)
    return {path.resolve(strict=False) for path in protected}


def _assert_target_safe(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Source template not found: {source}")
    if paths_overlap(source, target):
        raise ValueError("Source and target templates must not overlap")
    if target.exists() or target.is_symlink():
        raise FileExistsError(
            f"Refusing to overwrite existing target; choose a new path: {target}"
        )
    for protected in _canonical_paths():
        if paths_overlap(target, protected):
            raise ValueError(f"Refusing to write protected canonical template path: {target}")


def build_patch(source: Path, target: Path, replacements: list[tuple[str, str]]) -> None:
    if source.resolve() == target.resolve():
        raise ValueError("Source and target templates must be different files")
    _assert_target_safe(source, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(source, "r") as source_zip, zipfile.ZipFile(temporary, "w") as target_zip:
            for info in source_zip.infolist():
                payload = source_zip.read(info.filename)
                if info.filename == "word/document.xml":
                    payload = _replace_document_text(payload, replacements)
                target_zip.writestr(info, payload)
        with zipfile.ZipFile(temporary, "r") as check_zip:
            if check_zip.testzip() is not None:
                raise ValueError("patched DOCX contains a corrupt ZIP member")
            document_xml = check_zip.read("word/document.xml")
        etree.fromstring(document_xml)
        try:
            Document(str(temporary))
        except Exception as exc:  # pragma: no cover - python-docx parser details
            raise ValueError(f"patched DOCX could not be reopened: {exc}") from exc
        os.replace(str(temporary), str(target))
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--manifest", type=Path, help="Read template.patches.visible_text_replacements from a UTF-8 YAML manifest")
    parser.add_argument("--replace", action="append", metavar="OLD=NEW")
    args = parser.parse_args()
    replacements: list[tuple[str, str]] = []
    values = list(args.replace or [])
    if args.manifest:
        manifest = yaml.safe_load(args.manifest.expanduser().resolve().read_text(encoding="utf-8")) or {}
        patches = manifest.get("template", {}).get("patches", {})
        for item in patches.get("visible_text_replacements", []):
            values.append(f"{item['from']}={item['to']}")
    if not values:
        parser.error("provide --manifest or at least one --replace")
    for value in values:
        if "=" not in value:
            parser.error("--replace must use OLD=NEW")
        old_text, new_text = value.split("=", 1)
        if not old_text or not new_text or old_text == new_text:
            parser.error("--replace values must contain two different non-empty strings")
        replacements.append((old_text, new_text))
    build_patch(args.source.expanduser().resolve(), args.target.expanduser().resolve(), replacements)
    print(f"patched={args.target.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
