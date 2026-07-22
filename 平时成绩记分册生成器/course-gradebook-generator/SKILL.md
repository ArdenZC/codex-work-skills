---
name: course-gradebook-generator
description: Generate 湖北职业技术学院 style 平时成绩记分册 .xls workbooks from 课程成绩单.xls files using the bundled template. 中文显示名：平时成绩记分册生成器。Use when the user asks to create, fill, batch-generate, or update 平时成绩记分册, 平时成绩登记表, or 8次平时成绩 from a 课程成绩单/成绩单 Excel file, including cases where skill columns should be removed when 技能成绩 is 0%.
---

# 平时成绩记分册生成器

## Purpose

Generate one 平时成绩记分册 `.xls` from a course score sheet named like `课程成绩单.xls`, preserving the bundled template style.

If the user has not provided a source workbook, remind them that this skill needs a `课程成绩单.xls` file or a folder containing it.

## Platform Support

- Windows: prefer `scripts/generate_gradebook.ps1`, which uses Microsoft Excel COM and preserves the legacy `.xls` template most faithfully.
- macOS/Linux: use `scripts/generate_gradebook.py`, which requires Python 3, `openpyxl`, and LibreOffice/soffice. It converts `.xls` through LibreOffice, edits the workbook, then converts back to `.xls`.
- If LibreOffice is missing on macOS/Linux, tell the user to install LibreOffice before running the generator.

## Bundled Resources

- Template: `assets/平时成绩记分册模板.xls`
- Windows generator: `scripts/generate_gradebook.ps1`
- Cross-platform generator: `scripts/generate_gradebook.py`

Use Excel COM on Windows to preserve legacy `.xls` formatting. Use the cross-platform Python/LibreOffice path on macOS/Linux or when Excel COM is unavailable.

## Workflow

1. Locate the source workbook.
   - Prefer an explicitly attached or mentioned `课程成绩单.xls`.
   - If the user provides a class folder, look for `课程成绩单.xls` inside it.
   - If missing, ask the user to provide/upload `课程成绩单.xls`.

2. Run the bundled generator.
   - Windows source file:
     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>/scripts/generate_gradebook.ps1" -SourcePath "<path/to/课程成绩单.xls>" -OutputDir "<output-dir>"
     ```
   - Windows class folder:
     ```powershell
     powershell -NoProfile -ExecutionPolicy Bypass -File "<skill>/scripts/generate_gradebook.ps1" -SourcePath "<path/to/class-folder>" -OutputDir "<output-dir>"
     ```
   - macOS/Linux source file or class folder:
     ```bash
     python3 "<skill>/scripts/generate_gradebook.py" --source "<path/to/课程成绩单.xls-or-folder>" --output-dir "<output-dir>"
     ```

3. Verify before responding.
   - Confirm output row count equals parsed student count.
   - Confirm 学号 and 姓名 match the source row order.
   - Confirm 8 generated 平时成绩 values average exactly to source 平时成绩.
   - Confirm 总评 equals source 总成绩.
   - Confirm no visible Excel errors such as `#REF!` or `#VALUE!`.
   - Confirm 技能成绩 columns are deleted when 技能成绩比例 is `0%`; otherwise keep 技能成绩 and 折合 columns.

4. Preview when layout changed or when columns were deleted.
   - Export the first sheet to PDF/PNG with Excel COM if practical.
   - Check that course, teacher, class, headers, and total columns are visible and not clipped.
   - Widen the final class/total column if class text shows as `########`.

5. Return only the final workbook link(s), plus a compact verification summary.

## Generation Rules

- Copy the bundled template, then fill values into the copy.
- Keep only as many student rows as the source has:
  - Delete unused template student rows.
  - Insert copied template rows only when the source has more students than the template supports.
- Preserve row/column styling, borders, number formats, and `.xls` format.
- Populate the metadata row from the source:
  - 开课学期
  - 课程
  - 教师
  - 班级
  - 成绩比例
- Generate 8 平时成绩 values per student:
  - Use deterministic randomness seeded by class + 学号 + 平时成绩.
  - Use 0.5-point increments.
  - Keep values close to the source 平时成绩; target max deviation should be about 6 points or less.
  - Ensure the average of all 8 values equals the source 平时成绩 exactly.
- Write formulas for 折合 and 总评 using the source score proportions.
- If 技能成绩比例 is `0%`, delete the 技能成绩 and 技能折合 columns from the output.
