#!/usr/bin/env python3
"""Cross-platform gradebook generator for 课程成绩单.xls -> 平时成绩记分册.xls.

Requires Python 3, openpyxl, and LibreOffice/soffice on PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
from copy import copy
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import get_column_letter


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "平时成绩记分册模板.xls"


def find_soffice() -> str:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        shutil.which("soffice.com"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/libreoffice",
        "/usr/local/bin/libreoffice",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise RuntimeError(
        "LibreOffice/soffice was not found. Install LibreOffice and make soffice available on PATH."
    )


def convert_with_soffice(soffice: str, source: Path, out_dir: Path, target: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [soffice, "--headless", "--convert-to", target, "--outdir", str(out_dir), str(source)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"LibreOffice conversion failed: {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}")
    ext = target.split(":")[0].lower()
    output = out_dir / f"{source.stem}.{ext}"
    if not output.exists():
        matches = sorted(out_dir.glob(f"{source.stem}.*"))
        if matches:
            return matches[-1]
        raise RuntimeError(f"LibreOffice did not create expected output for {source}")
    return output


def cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def to_number(value) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def read_meta(ws) -> dict:
    line2 = cell_text(ws.cell(2, 1).value)
    line3 = cell_text(ws.cell(3, 1).value)
    meta = {
        "course": "",
        "teacher": "",
        "class_name": "",
        "term": "",
        "skill_pct": 0.0,
        "theory_pct": 0.0,
        "regular_pct": 0.0,
    }
    m = re.search(r"课程名称:([^\r\n]+?)\s+教师:", line2)
    if not m:
        m = re.search(r"课程名称:([^\r\n ]+)", line2)
    if m:
        meta["course"] = m.group(1).strip()
    m = re.search(r"教师:([^\r\n]+?)(?:\s*上课班级:|$)", line2)
    if m:
        meta["teacher"] = m.group(1).strip()
    m = re.search(r"上课班级:([^\r\n]+?)(?:\s*成绩项目比例:|$)", line2)
    if m:
        meta["class_name"] = m.group(1).strip()
    m = re.search(r"开课学期:([^\s]+)", line3)
    if m:
        meta["term"] = m.group(1).strip()
    m = re.search(r"技能成绩(\d+(?:\.\d+)?)%", line2)
    if m:
        meta["skill_pct"] = float(m.group(1)) / 100
    m = re.search(r"理论成绩(\d+(?:\.\d+)?)%", line2)
    if m:
        meta["theory_pct"] = float(m.group(1)) / 100
    m = re.search(r"平时成绩(\d+(?:\.\d+)?)%", line2)
    if m:
        meta["regular_pct"] = float(m.group(1)) / 100
    return meta


def header_map(ws, start_col: int, end_col: int) -> dict[str, int]:
    found = {}
    for col in range(start_col, end_col + 1):
        header = cell_text(ws.cell(4, col).value)
        if header:
            found[header] = col
    return found


def read_students(ws) -> list[dict]:
    starts = []
    for col in range(1, ws.max_column + 1):
        if cell_text(ws.cell(4, col).value) == "学号" and cell_text(ws.cell(4, col + 1).value) == "姓名":
            starts.append(col)
    if not starts:
        raise RuntimeError("Could not find 学号/姓名 headers in source workbook.")

    blocks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else ws.max_column
        blocks.append((start, header_map(ws, start, end)))

    students = []
    for row in range(5, ws.max_row + 1):
        for start, headers in blocks:
            student_id = cell_text(ws.cell(row, start).value)
            name = cell_text(ws.cell(row, start + 1).value)
            if not re.fullmatch(r"\d{8,}", student_id) or not name:
                continue
            for required in ("理论成绩", "平时成绩", "总成绩"):
                if required not in headers:
                    raise RuntimeError(f"Source block is missing {required}.")
            students.append(
                {
                    "id": student_id,
                    "name": name,
                    "skill": to_number(ws.cell(row, headers["技能成绩"]).value) if "技能成绩" in headers else 0.0,
                    "theory": to_number(ws.cell(row, headers["理论成绩"]).value),
                    "regular": to_number(ws.cell(row, headers["平时成绩"]).value),
                    "total": to_number(ws.cell(row, headers["总成绩"]).value),
                }
            )
    if not students:
        raise RuntimeError("No students parsed from source workbook.")
    return students


def stable_seed(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little") & 0x7FFFFFFF


def generate_regular_scores(target: float, seed_text: str) -> list[float]:
    target_units = round(target * 2)
    target_total_units = target_units * 8
    rng = random.Random(stable_seed(seed_text))
    for _ in range(2000):
        scores = []
        total = 0
        for _idx in range(7):
            low = max(-8, -target_units)
            high = min(8, 200 - target_units)
            score = target_units + rng.randint(low, high)
            scores.append(score)
            total += score
        last = target_total_units - total
        if last < 0 or last > 200:
            continue
        if abs(last - target_units) > 12:
            continue
        scores.append(last)
        values = [score / 2 for score in scores]
        if max(abs(value - target) for value in values) <= 6:
            return values
    return [target] * 8


def copy_row_style(ws, source_row: int, target_row: int, max_col: int) -> None:
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, max_col + 1):
        src = ws.cell(source_row, col)
        dst = ws.cell(target_row, col)
        if src.has_style:
            dst._style = copy(src._style)
        if src.number_format:
            dst.number_format = src.number_format
        if src.alignment:
            dst.alignment = copy(src.alignment)
        if src.font:
            dst.font = copy(src.font)
        if src.fill:
            dst.fill = copy(src.fill)
        if src.border:
            dst.border = copy(src.border)


def writable_cell(ws, row: int, col: int):
    coord = f"{get_column_letter(col)}{row}"
    for merged_range in ws.merged_cells.ranges:
        if coord in merged_range:
            cell = ws.cell(merged_range.min_row, merged_range.min_col)
            if isinstance(cell, MergedCell):
                ws.unmerge_cells(str(merged_range))
                return ws.cell(row, col)
            return cell
    return ws.cell(row, col)


def set_value(ws, row: int, col: int, value) -> None:
    writable_cell(ws, row, col).value = value


def formula_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".") or "0"


def build_one(source_xls: Path, template_xls: Path, output_dir: Path, soffice: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="gradebook_") as tmp_name:
        tmp = Path(tmp_name)
        source_xlsx = convert_with_soffice(soffice, source_xls, tmp / "source", "xlsx")
        template_xlsx = convert_with_soffice(soffice, template_xls, tmp / "template", "xlsx")

        src_wb = load_workbook(source_xlsx, data_only=True)
        src_ws = src_wb.worksheets[0]
        meta = read_meta(src_ws)
        students = read_students(src_ws)

        wb = load_workbook(template_xlsx)
        ws = wb["平时成绩"] if "平时成绩" in wb.sheetnames else wb.worksheets[0]
        has_skill = meta["skill_pct"] > 0.000001
        if not has_skill:
            for merged_range in list(ws.merged_cells.ranges):
                if merged_range.max_col >= 15:
                    ws.unmerge_cells(str(merged_range))
            ws.delete_cols(15, 2)

        data_start = 5
        template_last_row = 52
        max_col = 17 if has_skill else 15
        existing_rows = template_last_row - data_start + 1
        if len(students) > existing_rows:
            needed = len(students) - existing_rows
            ws.insert_rows(template_last_row + 1, needed)
            for row in range(template_last_row + 1, template_last_row + needed + 1):
                copy_row_style(ws, template_last_row, row, max_col)
            template_last_row += needed

        for row in range(data_start, template_last_row + 1):
            for col in range(1, max_col + 1):
                ws.cell(row, col).value = None

        set_value(ws, 2, 3, meta["term"])
        set_value(ws, 2, 7, meta["course"])
        set_value(ws, 2, 12, meta["teacher"])
        set_value(ws, 2, 15, meta["class_name"])
        set_value(ws, 3, 4, f"平时成绩({round(meta['regular_pct'] * 100)}%)")
        set_value(ws, 3, 13, f"理论成绩({round(meta['theory_pct'] * 100)}%)")
        if has_skill:
            set_value(ws, 3, 15, f"技能成绩（{round(meta['skill_pct'] * 100)}%）")
        else:
            ws.column_dimensions["O"].width = max(ws.column_dimensions["O"].width or 0, 18)

        regular_pct = formula_number(meta["regular_pct"])
        theory_pct = formula_number(meta["theory_pct"])
        skill_pct = formula_number(meta["skill_pct"])
        class_code = source_xls.parent.name or source_xls.stem

        for idx, student in enumerate(students):
            row = data_start + idx
            scores = generate_regular_scores(student["regular"], f"{class_code}|{student['id']}|{student['regular']}")
            ws.cell(row, 1).value = idx + 1
            ws.cell(row, 2).value = student["id"]
            ws.cell(row, 2).number_format = "@"
            ws.cell(row, 3).value = student["name"]
            for offset, score in enumerate(scores):
                ws.cell(row, 4 + offset).value = score
            ws.cell(row, 12).value = f"=AVERAGE(D{row}:K{row})*{regular_pct}"
            ws.cell(row, 13).value = student["theory"]
            ws.cell(row, 14).value = f"=M{row}*{theory_pct}"
            if has_skill:
                ws.cell(row, 15).value = student["skill"]
                ws.cell(row, 16).value = f"=O{row}*{skill_pct}"
                ws.cell(row, 17).value = f"=ROUND(AVERAGE(D{row}:K{row})*{regular_pct}+M{row}*{theory_pct}+O{row}*{skill_pct},0)"
            else:
                ws.cell(row, 15).value = f"=ROUND(AVERAGE(D{row}:K{row})*{regular_pct}+M{row}*{theory_pct},0)"

        # Keep exactly as many student rows as the source contains.
        first_extra = data_start + len(students)
        if first_extra <= template_last_row:
            ws.delete_rows(first_extra, template_last_row - first_extra + 1)

        output_dir.mkdir(parents=True, exist_ok=True)
        temp_xlsx = tmp / f"{class_code}-平时成绩记分册.xlsx"
        wb.save(temp_xlsx)
        converted = convert_with_soffice(soffice, temp_xlsx, output_dir, "xls")
        final_path = output_dir / f"{class_code}-平时成绩记分册.xls"
        if converted.resolve() != final_path.resolve():
            if final_path.exists():
                final_path.unlink()
            converted.replace(final_path)

        return {
            "source": str(source_xls),
            "output": str(final_path),
            "count": len(students),
            "course": meta["course"],
            "class_name": meta["class_name"],
            "has_skill": has_skill,
            "regular_pct": meta["regular_pct"],
            "theory_pct": meta["theory_pct"],
            "skill_pct": meta["skill_pct"],
            "engine": "libreoffice-openpyxl",
            "platform": platform.system(),
        }


def resolve_sources(source_path: Path) -> list[Path]:
    if not source_path.exists():
        raise RuntimeError(f"Source path not found: {source_path}. Provide 课程成绩单.xls or a folder containing it.")
    if source_path.is_dir():
        candidate = source_path / "课程成绩单.xls"
        if not candidate.exists():
            raise RuntimeError(f"Folder does not contain 课程成绩单.xls: {source_path}")
        return [candidate]
    return [source_path]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 平时成绩记分册 from 课程成绩单.xls.")
    parser.add_argument("--source", required=True, help="课程成绩单.xls path or a folder containing it")
    parser.add_argument("--output-dir", default="", help="Output directory")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Template .xls path")
    args = parser.parse_args()

    sources = resolve_sources(Path(args.source).expanduser().resolve())
    template = Path(args.template).expanduser().resolve()
    if not template.exists():
        raise RuntimeError(f"Template not found: {template}")
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else sources[0].parent / "平时成绩记分册_生成"
    soffice = find_soffice()
    results = [build_one(source, template, output_dir, soffice) for source in sources]
    payload = results[0] if len(results) == 1 else results
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
