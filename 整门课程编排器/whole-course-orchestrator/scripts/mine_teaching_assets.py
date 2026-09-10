"""Extract source slides and independently reusable teaching assets.

The miner deliberately keeps the source slide container separate from the
assets discovered inside it. A slide may therefore yield text, tables,
images, notes and a shape-based diagram at the same time. The parser uses
the OOXML package directly so that missing optional Python presentation
libraries cannot silently remove visual evidence.
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from orchestrator_core import dump_json, relative_posix, sha256_bytes, sha256_file, slug


ASSET_TYPES = (
    "fact",
    "definition",
    "diagram",
    "screenshot",
    "worked_example",
    "case",
    "exercise",
    "question",
    "procedure",
    "comparison",
    "misconception",
    "tool_operation",
    "code_example",
    "table",
    "formula",
    "story/context",
    "speaker_note_hint",
    "summary",
    "image",
    "visual_candidate_unresolved",
)


def _local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _texts(xml: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    values: list[str] = []
    for node in root.iter():
        if _local(node) == "t" and (node.text or "").strip():
            values.append(re.sub(r"\s+", " ", node.text or "").strip())
    return values


def _paragraphs(element: ET.Element) -> list[str]:
    values: list[str] = []
    for paragraph in element.iter():
        if _local(paragraph) != "p":
            continue
        text = "".join((node.text or "") for node in paragraph.iter() if _local(node) == "t")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            values.append(text)
    return values


def _natural_slide_key(name: str) -> tuple[int, str]:
    match = re.search(r"slide(\d+)\.xml$", name)
    return (int(match.group(1)) if match else 0, name)


def _rels_target(rels_xml: bytes, rel_id: str) -> str | None:
    try:
        root = ET.fromstring(rels_xml)
    except ET.ParseError:
        return None
    for node in root:
        if node.attrib.get("Id") != rel_id:
            continue
        target = node.attrib.get("Target", "")
        if not target or node.attrib.get("TargetMode") == "External":
            return None
        normalized = posixpath.normpath(posixpath.join("ppt/slides", target))
        return normalized if normalized.startswith("ppt/") else f"ppt/{normalized.lstrip('/')}"
    return None


def _relationship_id(node: ET.Element) -> str | None:
    return next((value for key, value in node.attrib.items() if key.rsplit("}", 1)[-1] == "embed"), None)


def _slide_relationships(archive: zipfile.ZipFile, slide_name: str) -> bytes:
    rel_name = f"ppt/slides/_rels/{Path(slide_name).name}.rels"
    return archive.read(rel_name) if rel_name in archive.namelist() else b""


def _slide_images(archive: zipfile.ZipFile, slide_name: str, slide_xml: bytes) -> list[dict[str, str]]:
    """Return every image relationship with its owning shape identity."""

    try:
        root = ET.fromstring(slide_xml)
    except ET.ParseError:
        return []
    rels = _slide_relationships(archive, slide_name)
    if not rels:
        return []
    results: list[dict[str, str]] = []
    for picture in root.iter():
        if _local(picture) != "pic":
            continue
        shape_id = next((node.attrib.get("id") for node in picture.iter() if _local(node) == "cNvPr" and node.attrib.get("id")), None)
        for node in picture.iter():
            if _local(node) != "blip":
                continue
            rel_id = _relationship_id(node)
            target = _rels_target(rels, rel_id or "")
            if target and target in archive.namelist():
                results.append({"target": target, "relationship_id": rel_id or "", "source_shape_id": shape_id or "unknown"})
    return results


def _notes(archive: zipfile.ZipFile, slide_number: int) -> list[str]:
    name = f"ppt/notesSlides/notesSlide{slide_number}.xml"
    return _texts(archive.read(name)) if name in archive.namelist() else []


def _classify(text: str, *, image_count: int = 0, table_count: int = 0, shape_count: int = 0, arrow: bool = False) -> tuple[str, float]:
    lowered = text.lower()
    if any(key in lowered for key in ("练习", "任务", "exercise", "quiz", "判断题")):
        return "exercise", 0.96
    if any(key in lowered for key in ("步骤", "操作步骤", "procedure", "step", "首先", "然后", "最后")):
        return "procedure", 0.93
    if any(key in lowered for key in ("截图", "屏幕", "screenshot", "界面", "点击")) and image_count:
        return "screenshot", 0.94
    if any(key in lowered for key in ("定义", "是什么", "definition", "概念")):
        return "definition", 0.92
    if any(key in lowered for key in ("比较", "区别", "对比", "versus", " vs ")):
        return "comparison", 0.9
    if any(key in lowered for key in ("例题", "示例", "案例", "worked example", "case")):
        return "worked_example", 0.88
    if any(key in lowered for key in ("误区", "易错", "常见错误", "misconception")):
        return "misconception", 0.9
    if table_count:
        return "table", 0.9
    if image_count or arrow or shape_count >= 4:
        return "diagram", 0.82
    if any(key in lowered for key in ("总结", "小结", "summary")):
        return "summary", 0.9
    if any(key in lowered for key in ("代码", "code", "python", "java", "sql")):
        return "code_example", 0.85
    return "fact", 0.72


def _value(asset_type: str, text: str, image_count: int = 0) -> str:
    lowered = text.lower()
    if any(key in lowered for key in ("谢谢", "thank", "版权", "copyright", "目录", "agenda")):
        return "low-value"
    if asset_type in {"diagram", "screenshot", "worked_example", "case", "exercise", "procedure", "comparison", "table", "image"}:
        return "core"
    if asset_type in {"definition", "fact", "code_example", "tool_operation", "question", "misconception", "speaker_note_hint"}:
        return "supporting"
    return "optional" if image_count else "low-value"


def _topics(title: str, text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", f"{title} {text}")
    seen: list[str] = []
    for item in candidates:
        if item not in seen and item not in {"学生", "课程", "内容", "说明", "本页"}:
            seen.append(item)
    return seen[:12]


def _c_nv_pr(element: ET.Element) -> tuple[str, str]:
    for node in element.iter():
        if _local(node) == "cNvPr":
            return str(node.attrib.get("id") or "unknown"), str(node.attrib.get("name") or "")
    return "unknown", ""


def _region(element: ET.Element) -> dict[str, int] | None:
    for node in element.iter():
        if _local(node) != "xfrm":
            continue
        off = next((child for child in node if _local(child) == "off"), None)
        ext = next((child for child in node if _local(child) == "ext"), None)
        if off is None or ext is None:
            continue
        try:
            return {
                "x": int(off.attrib.get("x", 0)),
                "y": int(off.attrib.get("y", 0)),
                "w": int(ext.attrib.get("cx", 0)),
                "h": int(ext.attrib.get("cy", 0)),
            }
        except ValueError:
            return None
    return None


def _shape_kind(element: ET.Element) -> str:
    return _local(element)


def _direct_shape_elements(root: ET.Element) -> Iterable[tuple[ET.Element, str | None]]:
    """Yield shape descendants while retaining group hierarchy."""

    def visit(parent: ET.Element, group_id: str | None = None) -> Iterable[tuple[ET.Element, str | None]]:
        for child in list(parent):
            kind = _local(child)
            if kind == "grpSp":
                current, _ = _c_nv_pr(child)
                yield from visit(child, current)
            elif kind in {"sp", "pic", "graphicFrame", "cxnSp"}:
                yield child, group_id

    tree = next((node for node in root.iter() if _local(node) == "spTree"), root)
    yield from visit(tree)


def _shape_graph(root: ET.Element) -> dict[str, Any]:
    shapes: list[dict[str, Any]] = []
    connectors: list[dict[str, Any]] = []
    for element, group_id in _direct_shape_elements(root):
        shape_id, name = _c_nv_pr(element)
        region = _region(element) or {}
        record = {
            "id": shape_id,
            "kind": _shape_kind(element),
            "name": name,
            "text": " ".join(_paragraphs(element)),
            "x": region.get("x"),
            "y": region.get("y"),
            "width": region.get("w"),
            "height": region.get("h"),
            "group_id": group_id,
        }
        if _shape_kind(element) == "cxnSp":
            start = next((node.attrib.get("id") for node in element.iter() if _local(node) == "stCxn"), None)
            end = next((node.attrib.get("id") for node in element.iter() if _local(node) == "endCxn"), None)
            line_kind = next((node.attrib.get("prst", "") for node in element.iter() if _local(node) == "prstGeom"), "")
            head = next((node.attrib.get("type", "") for node in element.iter() if _local(node) == "headEnd"), "")
            tail = next((node.attrib.get("type", "") for node in element.iter() if _local(node) == "tailEnd"), "")
            connectors.append({
                "id": shape_id,
                "from_shape": start or "unknown",
                "to_shape": end or "unknown",
                "line_kind": line_kind or "connector",
                "arrow_start": head or None,
                "arrow_end": tail or None,
                "x": region.get("x"),
                "y": region.get("y"),
                "width": region.get("w"),
                "height": region.get("h"),
            })
        else:
            shapes.append(record)
    return {"shapes": shapes, "connectors": connectors}


def _table_records(root: ET.Element) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, table in enumerate((node for node in root.iter() if _local(node) == "tbl"), start=1):
        rows: list[list[str]] = []
        for row in (node for node in table if _local(node) == "tr"):
            cells: list[str] = []
            for cell in (node for node in row if _local(node) == "tc"):
                cells.append(" ".join(_paragraphs(cell)).strip())
            if cells:
                rows.append(cells)
        records.append({"index": index, "rows": rows, "columns": max((len(row) for row in rows), default=0), "cell_text": rows})
    return records


def _copy_media(archive: zipfile.ZipFile, name: str, output_dir: Path, source_stem: str, slide_number: int, shape_id: str) -> str:
    target_dir = output_dir / "images" / slug(source_stem)
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(name).suffix or ".bin"
    target = target_dir / f"s{slide_number:03d}-shape-{slug(shape_id)}{suffix}"
    if not target.exists():
        target.write_bytes(archive.read(name))
    return relative_posix(target, output_dir)


def _diagram_svg(graph: dict[str, Any], output_dir: Path, source_stem: str, slide_number: int) -> str:
    shapes = graph.get("shapes", [])
    connectors = graph.get("connectors", [])
    max_x = max((int(item.get("x") or 0) + int(item.get("width") or 0) for item in shapes), default=7200000)
    max_y = max((int(item.get("y") or 0) + int(item.get("height") or 0) for item in shapes), default=4050000)
    scale = 100000
    width = max(360, min(1600, int(max_x / scale) + 80))
    height = max(220, min(1000, int(max_y / scale) + 80))
    by_id = {str(item.get("id")): item for item in shapes}
    elements: list[str] = []
    for connector in connectors:
        start = by_id.get(str(connector.get("from_shape")))
        end = by_id.get(str(connector.get("to_shape")))
        if not start or not end:
            continue
        x1 = int((int(start.get("x") or 0) + int(start.get("width") or 0) / 2) / scale)
        y1 = int((int(start.get("y") or 0) + int(start.get("height") or 0) / 2) / scale)
        x2 = int((int(end.get("x") or 0) + int(end.get("width") or 0) / 2) / scale)
        y2 = int((int(end.get("y") or 0) + int(end.get("height") or 0) / 2) / scale)
        elements.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#6b8f9d" stroke-width="3" marker-end="url(#arrow)" data-shape-connector="{html.escape(str(connector.get("id")))}"/>')
    for shape in shapes:
        x = int(int(shape.get("x") or 0) / scale)
        y = int(int(shape.get("y") or 0) / scale)
        w = max(80, int(int(shape.get("width") or 800000) / scale))
        h = max(42, int(int(shape.get("height") or 500000) / scale))
        label = html.escape(str(shape.get("text") or shape.get("name") or shape.get("id")))
        elements.append(f'<g data-source-shape-id="{html.escape(str(shape.get("id")))}"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#edf4f5" stroke="#6b8f9d"/><text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" text-anchor="middle" dominant-baseline="middle" fill="#26384a" font-size="14">{label[:80]}</text></g>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="source shape diagram" data-source-shape-graph="1"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#6b8f9d"/></marker></defs>{"".join(elements)}</svg>'
    target_dir = output_dir / "visuals"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{slug(source_stem)}-s{slide_number:03d}-diagram.svg"
    target.write_text(svg, encoding="utf-8", newline="\n")
    return relative_posix(target, output_dir)


def _base_asset(
    *,
    asset_id: str,
    asset_type: str,
    path: Path,
    slide_id: str,
    slide_number: int,
    title: str,
    text: str,
    source_element_ids: list[str],
    source_region: dict[str, Any] | None,
    source_kind: str,
    confidence: float,
    image_refs: list[str] | None = None,
) -> dict[str, Any]:
    refs = list(image_refs or [])
    return {
        "id": asset_id,
        "type": asset_type,
        "source_file": str(path),
        "source_slide": slide_number,
        "source_slide_id": slide_id,
        "source_element_ids": source_element_ids,
        "source_region": source_region,
        "source_kind": source_kind,
        "source_locator": f"pptx:{path.name}#slide-{slide_number}" + (f"#element-{','.join(source_element_ids)}" if source_element_ids else ""),
        "title": title,
        "content_summary": text[:500],
        "raw_text": text,
        "image_ref": refs[0] if refs else None,
        "image_refs": refs,
        "confidence": confidence,
        "candidate_topics": _topics(title, text),
        "teaching_value": _value(asset_type, text, len(refs)),
        "origin": "user_source",
        "origin_type": "user-provided",
        "source_url": None,
        "source_title": None,
        "retrieved_at": None,
        "license_note": None,
    }


def parse_pptx(path: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    slides: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted((name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")), key=_natural_slide_key)
        for slide_index, name in enumerate(names, start=1):
            xml = archive.read(name)
            texts = _texts(xml)
            notes = _notes(archive, slide_index)
            root = ET.fromstring(xml)
            graph = _shape_graph(root)
            tables = _table_records(root)
            image_records = _slide_images(archive, name, xml)
            image_refs: list[dict[str, str]] = []
            for record in image_records:
                ref = _copy_media(archive, record["target"], output_dir, path.stem, slide_index, record["source_shape_id"])
                image_refs.append({**record, "image_ref": ref, "media_sha256": sha256_bytes(archive.read(record["target"]))})
            slide_id = f"slide-{slug(path.stem)}-{slide_index:03d}"
            title = texts[0] if texts else f"第 {slide_index} 页"
            slide_asset_ids: list[str] = []

            # Text is intentionally split at shape/paragraph level. This is
            # a conservative structural split, not an NLP claim.
            for shape_index, (element, _group_id) in enumerate(_direct_shape_elements(root), start=1):
                shape_id, _shape_name = _c_nv_pr(element)
                if _shape_kind(element) in {"pic", "cxnSp"}:
                    continue
                if any(_local(node) == "tbl" for node in element.iter()):
                    continue
                parts = _paragraphs(element)
                if not parts:
                    continue
                for paragraph_index, text in enumerate(parts, start=1):
                    asset_type, confidence = _classify(text, image_count=len(image_records), shape_count=len(graph["shapes"]), arrow=bool(graph["connectors"]))
                    if asset_type == "diagram" and len(graph["shapes"]) <= 1 and not graph["connectors"]:
                        asset_type = "fact"
                    asset_id = f"asset-{slug(path.stem)}-s{slide_index:03d}-e{slug(shape_id)}-p{paragraph_index:02d}"
                    asset = _base_asset(
                        asset_id=asset_id,
                        asset_type=asset_type,
                        path=path,
                        slide_id=slide_id,
                        slide_number=slide_index,
                        title=text if paragraph_index == 1 else f"{title} · {paragraph_index}",
                        text=text,
                        source_element_ids=[shape_id],
                        source_region=_region(element),
                        source_kind="title" if shape_index == 1 and paragraph_index == 1 else "shape-text",
                        confidence=confidence,
                    )
                    if asset_type == "screenshot" and image_refs:
                        # Keep the Phase 1 compatibility view while still
                        # emitting an independent image asset below.
                        asset["image_refs"] = [item["image_ref"] for item in image_refs]
                        asset["image_ref"] = asset["image_refs"][0]
                    asset["inventory_evidence"] = {
                        "text_count": len(parts),
                        "speaker_note_count": len(notes),
                        "table_count": len(tables),
                        "shape_count": len(graph["shapes"]),
                        "connector_count": len(graph["connectors"]),
                        "image_count": len(image_records),
                        "arrow_detected": bool(graph["connectors"]),
                    }
                    assets.append(asset)
                    slide_asset_ids.append(asset_id)

            for table in tables:
                table_id = f"asset-{slug(path.stem)}-s{slide_index:03d}-table-{table['index']:02d}"
                table_text = " | ".join(" / ".join(row) for row in table["rows"])
                table_asset = _base_asset(
                    asset_id=table_id,
                    asset_type="table",
                    path=path,
                    slide_id=slide_id,
                    slide_number=slide_index,
                    title=f"{title} · 表格 {table['index']}",
                    text=table_text,
                    source_element_ids=[f"table-{table['index']}"],
                    source_region=None,
                    source_kind="table",
                    confidence=0.98,
                )
                table_asset.update({"rows": table["rows"], "columns": table["columns"], "cell_text": table["cell_text"], "source_locator": f"pptx:{path.name}#slide-{slide_index}#table-{table['index']}"})
                assets.append(table_asset)
                slide_asset_ids.append(table_id)

            for image_index, image in enumerate(image_refs, start=1):
                image_id = f"asset-{slug(path.stem)}-s{slide_index:03d}-image-{image_index:02d}"
                image_asset = _base_asset(
                    asset_id=image_id,
                    asset_type="image",
                    path=path,
                    slide_id=slide_id,
                    slide_number=slide_index,
                    title=f"{title} · 图片 {image_index}",
                    text="",
                    source_element_ids=[image["source_shape_id"]],
                    source_region=None,
                    source_kind="embedded-image",
                    confidence=0.99,
                    image_refs=[image["image_ref"]],
                )
                image_asset.update({"image_ref": image["image_ref"], "relationship_id": image["relationship_id"], "source_shape_id": image["source_shape_id"], "media_sha256": image["media_sha256"]})
                assets.append(image_asset)
                slide_asset_ids.append(image_id)

            graph_shapes = [shape for shape in graph["shapes"] if shape.get("kind") != "pic"]
            if len(graph_shapes) >= 2 or graph["connectors"]:
                diagram_id = f"asset-{slug(path.stem)}-s{slide_index:03d}-diagram"
                rendered = _diagram_svg(graph, output_dir, path.stem, slide_index)
                diagram = _base_asset(
                    asset_id=diagram_id,
                    asset_type="diagram",
                    path=path,
                    slide_id=slide_id,
                    slide_number=slide_index,
                    title=f"{title} · shape diagram",
                    text=" ".join(shape.get("text", "") for shape in graph_shapes).strip(),
                    source_element_ids=[str(shape.get("id")) for shape in graph["shapes"] + graph["connectors"]],
                    source_region=None,
                    source_kind="shape-graph",
                    confidence=0.97,
                )
                diagram.update({"shape_graph": graph, "rendered_visual_ref": rendered, "structured_parse_status": "complete"})
                assets.append(diagram)
                slide_asset_ids.append(diagram_id)
            elif any(_shape_kind(element) == "graphicFrame" for element, _ in _direct_shape_elements(root)):
                unresolved_id = f"asset-{slug(path.stem)}-s{slide_index:03d}-visual-unresolved"
                unresolved = _base_asset(
                    asset_id=unresolved_id,
                    asset_type="visual_candidate_unresolved",
                    path=path,
                    slide_id=slide_id,
                    slide_number=slide_index,
                    title=f"{title} · unresolved visual",
                    text=" ".join(texts),
                    source_element_ids=[str(shape.get("id")) for shape in graph["shapes"]],
                    source_region=None,
                    source_kind="unsupported-graphic",
                    confidence=0.4,
                )
                unresolved.update({"shape_graph": graph, "structured_parse_status": "partial"})
                assets.append(unresolved)
                slide_asset_ids.append(unresolved_id)

            if len(notes) > 1 or any(len(note) >= 12 for note in notes):
                note_text = " ".join(notes)
                note_id = f"asset-{slug(path.stem)}-s{slide_index:03d}-notes"
                note_asset = _base_asset(
                    asset_id=note_id,
                    asset_type="speaker_note_hint",
                    path=path,
                    slide_id=slide_id,
                    slide_number=slide_index,
                    title=f"{title} · speaker note",
                    text=note_text,
                    source_element_ids=[f"notesSlide{slide_index}"],
                    source_region=None,
                    source_kind="speaker-notes",
                    confidence=0.99,
                )
                note_asset["student_visible"] = False
                assets.append(note_asset)
                slide_asset_ids.append(note_id)

            slides.append({
                "id": slide_id,
                "slide": slide_index,
                "title": title,
                "raw_text": " ".join(texts),
                "speaker_notes": notes,
                "asset_ids": slide_asset_ids,
                "image_refs": [item["image_ref"] for item in image_refs],
                "shape_graph": graph if (graph["shapes"] or graph["connectors"]) else None,
            })
    return assets, {"slide_count": len(slides), "slides": slides}


def _convert_legacy_ppt(path: Path, temp_dir: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("PPT_LEGACY_UNSUPPORTED: LibreOffice/soffice is unavailable")
    result = subprocess.run(
        [soffice, "--headless", "--convert-to", "pptx", "--outdir", str(temp_dir), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    converted = temp_dir / f"{path.stem}.pptx"
    if result.returncode != 0 or not converted.is_file():
        detail = (result.stderr or result.stdout or "conversion failed").strip()
        raise RuntimeError(f"PPT_LEGACY_CONVERSION_FAILED: {detail}")
    return converted


def mine_sources(source_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_paths = sorted(path for path in source_root.rglob("*") if path.is_file() and path.suffix.lower() in {".pptx", ".ppt"})
    all_assets: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    source_slides: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="whole-course-ppt-") as temp_name:
        temp_dir = Path(temp_name)
        for source in source_paths:
            parse_path = source
            conversion = None
            if source.suffix.lower() == ".ppt":
                try:
                    parse_path = _convert_legacy_ppt(source, temp_dir)
                    conversion = "libreoffice-pptx"
                except RuntimeError as exc:
                    errors.append({"source_file": str(source), "code": str(exc)})
                    sources.append({"source_file": str(source), "format": "ppt", "sha256": sha256_file(source), "status": "unavailable", "slides": []})
                    continue
            try:
                assets, slide_info = parse_pptx(parse_path, output_dir)
                all_assets.extend(assets)
                source_slides.extend({"source_file": str(source), **slide} for slide in slide_info["slides"])
                sources.append({
                    "source_file": str(source),
                    "parsed_file": str(parse_path),
                    "format": source.suffix.lower().lstrip("."),
                    "sha256": sha256_file(source),
                    "parsed_sha256": sha256_file(parse_path),
                    "conversion": conversion,
                    "status": "parsed",
                    **slide_info,
                })
            except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
                errors.append({"source_file": str(source), "code": "PPT_PARSE_FAILED", "detail": str(exc)})
                sources.append({"source_file": str(source), "format": source.suffix.lower().lstrip("."), "sha256": sha256_file(source), "status": "failed", "slides": []})
    by_type = {asset_type: sum(1 for asset in all_assets if asset["type"] == asset_type) for asset_type in ASSET_TYPES}
    high_value = [asset for asset in all_assets if asset["teaching_value"] == "core"]
    multi_asset_slides = sum(1 for slide in source_slides if len(slide.get("asset_ids", [])) > 1)
    report = {
        "schema_version": "1.1",
        "sources": len(sources),
        "total_slides": len(source_slides),
        "candidate_teaching_slides": sum(1 for slide in source_slides if slide.get("asset_ids")),
        "asset_count": len(all_assets),
        "multi_asset_slide_count": multi_asset_slides,
        "asset_counts_by_type": by_type,
        "high_value_asset_count": len(high_value),
        "assets_selected": 0,
        "assets_actually_used": 0,
        "unused_high_value_assets": [asset["id"] for asset in high_value],
        "errors": errors,
        "coverage_definition": "Coverage is asset-level and value-aware; 100% slide reuse is not a goal.",
    }
    inventory = {
        "schema_version": "1.1",
        "inventory_type": "teaching_asset_inventory",
        "origin_policy": "user sources are primary; external sources are supplementary and separately recorded",
        "sources": sources,
        "source_slides": source_slides,
        "assets": all_assets,
        "asset_root": str(output_dir.resolve()),
        "coverage": report,
        "evidence_state_model": {"required": "downstream contract requirements", "planned": "orchestrator references", "observed": "final artifact evidence only"},
    }
    dump_json(inventory, output_dir / "source-assets.json")
    dump_json(report, output_dir / "source-teaching-asset-report.json")
    return inventory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if not args.source_root.is_dir():
        parser.error(f"source root does not exist: {args.source_root}")
    result = mine_sources(args.source_root, args.output_dir)
    if args.json:
        print({"sources": len(result["sources"]), "slides": len(result.get("source_slides", [])), "assets": len(result["assets"]), "output_dir": str(args.output_dir)})


if __name__ == "__main__":
    main()
