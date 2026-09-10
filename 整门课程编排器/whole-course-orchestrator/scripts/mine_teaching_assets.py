"""Extract a teaching-asset inventory from PPT/PPTX sources without OCR-first parsing."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from orchestrator_core import dump_json, relative_posix, sha256_bytes, sha256_file, slug, text_of


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
    "summary",
)


def _local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _texts(xml: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    values = []
    for node in root.iter():
        if _local(node) == "t" and (node.text or "").strip():
            values.append(re.sub(r"\s+", " ", node.text or "").strip())
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
        if node.attrib.get("Id") == rel_id:
            target = node.attrib.get("Target", "")
            if target.startswith("../"):
                target = target[3:]
            return target if target.startswith("ppt/") else f"ppt/{target.lstrip('/')}"
    return None


def _slide_images(archive: zipfile.ZipFile, slide_name: str, slide_xml: bytes) -> list[str]:
    rel_name = f"ppt/slides/_rels/{Path(slide_name).name}.rels"
    if rel_name not in archive.namelist():
        return []
    try:
        root = ET.fromstring(slide_xml)
    except ET.ParseError:
        return []
    try:
        rels = archive.read(rel_name)
    except KeyError:
        return []
    results = []
    for node in root.iter():
        if _local(node) != "blip":
            continue
        rel_id = next((value for key, value in node.attrib.items() if key.rsplit("}", 1)[-1] == "embed"), None)
        target = _rels_target(rels, rel_id or "")
        if target and target in archive.namelist() and target not in results:
            results.append(target)
    return results


def _notes(archive: zipfile.ZipFile, slide_number: int) -> list[str]:
    name = f"ppt/notesSlides/notesSlide{slide_number}.xml"
    return _texts(archive.read(name)) if name in archive.namelist() else []


def _classify(text: str, *, image_count: int, table_count: int, shape_count: int, arrow: bool) -> tuple[str, float]:
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


def _value(asset_type: str, text: str, image_count: int) -> str:
    lowered = text.lower()
    if any(key in lowered for key in ("谢谢", "thank", "版权", "copyright", "目录", "agenda")):
        return "low-value"
    if asset_type in {"diagram", "screenshot", "worked_example", "case", "exercise", "procedure", "comparison", "table"}:
        return "core"
    if asset_type in {"definition", "fact", "code_example", "tool_operation", "question", "misconception"}:
        return "supporting"
    return "optional" if image_count else "low-value"


def _topics(title: str, text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", f"{title} {text}")
    seen: list[str] = []
    for item in candidates:
        if item not in seen and item not in {"学生", "课程", "内容", "说明", "本页"}:
            seen.append(item)
    return seen[:8]


def _copy_image(archive: zipfile.ZipFile, name: str, output_dir: Path, source_stem: str) -> str:
    target_dir = output_dir / "images" / slug(source_stem)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / Path(name).name
    if not target.exists():
        target.write_bytes(archive.read(name))
    return relative_posix(target, output_dir)


def parse_pptx(path: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    slides: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted((name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")), key=_natural_slide_key)
        for slide_index, name in enumerate(names, start=1):
            xml = archive.read(name)
            texts = _texts(xml)
            notes = _notes(archive, slide_index)
            combined = " ".join(texts + notes)
            try:
                root = ET.fromstring(xml)
                table_count = sum(1 for node in root.iter() if _local(node) == "tbl")
                shape_count = sum(1 for node in root.iter() if _local(node) in {"sp", "pic", "graphicFrame", "cxnSp"})
                arrow = "arrow" in xml.decode("utf-8", errors="ignore").lower() or "lineend" in xml.decode("utf-8", errors="ignore").lower()
            except ET.ParseError:
                table_count, shape_count, arrow = 0, 0, False
            image_names = _slide_images(archive, name, xml)
            image_refs = [_copy_image(archive, image, output_dir, path.stem) for image in image_names]
            title = texts[0] if texts else f"第 {slide_index} 页"
            asset_type, confidence = _classify(combined, image_count=len(image_names), table_count=table_count, shape_count=shape_count, arrow=arrow)
            asset_id = f"asset-{slug(path.stem)}-s{slide_index:03d}"
            value = _value(asset_type, combined, len(image_names))
            asset = {
                "id": asset_id,
                "type": asset_type,
                "source_file": str(path),
                "source_slide": slide_index,
                "source_locator": f"pptx:{path.name}#slide-{slide_index}",
                "title": title,
                "content_summary": combined[:500],
                "raw_text": combined,
                "image_ref": image_refs[0] if image_refs else None,
                "image_refs": image_refs,
                "confidence": confidence,
                "candidate_topics": _topics(title, combined),
                "teaching_value": value,
                "origin": "user_source",
                "origin_type": "user-provided",
                "source_url": None,
                "source_title": None,
                "retrieved_at": None,
                "license_note": None,
                "inventory_evidence": {
                    "text_count": len(texts),
                    "speaker_note_count": len(notes),
                    "table_count": table_count,
                    "shape_count": shape_count,
                    "image_count": len(image_names),
                    "arrow_detected": arrow,
                },
            }
            assets.append(asset)
            slides.append({"slide": slide_index, "title": title, "asset_ids": [asset_id], "image_refs": image_refs})
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
                    sources.append({"source_file": str(source), "format": "ppt", "sha256": sha256_file(source), "status": "unavailable"})
                    continue
            try:
                assets, slide_info = parse_pptx(parse_path, output_dir)
                all_assets.extend(assets)
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
            except (OSError, zipfile.BadZipFile, ET.ParseError) as exc:
                errors.append({"source_file": str(source), "code": "PPT_PARSE_FAILED", "detail": str(exc)})
                sources.append({"source_file": str(source), "format": source.suffix.lower().lstrip("."), "sha256": sha256_file(source), "status": "failed"})
    by_type = {asset_type: sum(1 for asset in all_assets if asset["type"] == asset_type) for asset_type in ASSET_TYPES}
    high_value = [asset for asset in all_assets if asset["teaching_value"] == "core"]
    report = {
        "schema_version": "1.0",
        "sources": len(sources),
        "total_slides": sum(int(item.get("slide_count", 0)) for item in sources),
        "candidate_teaching_slides": len(all_assets),
        "asset_counts_by_type": by_type,
        "high_value_asset_count": len(high_value),
        "assets_selected": 0,
        "assets_actually_used": 0,
        "unused_high_value_assets": [asset["id"] for asset in high_value],
        "errors": errors,
        "coverage_definition": "Coverage is asset-level and value-aware; 100% slide reuse is not a goal.",
    }
    inventory = {
        "schema_version": "1.0",
        "inventory_type": "teaching_asset_inventory",
        "origin_policy": "user sources are primary; external sources are supplementary and separately recorded",
        "sources": sources,
        "assets": all_assets,
        "coverage": report,
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
        print({"sources": len(result["sources"]), "assets": len(result["assets"]), "output_dir": str(args.output_dir)})


if __name__ == "__main__":
    main()
