---
name: course-gradebook-generator
description: Generate 湖北职业技术学院 style 平时成绩记分册 .xls workbooks from 课程成绩单.xls files using the bundled template. 中文显示名：平时成绩记分册生成器。Use when the user asks to create, fill, batch-generate, or update 平时成绩记分册, 平时成绩登记表, or manifest-defined 平时成绩项目 from a 课程成绩单/成绩单 Excel file, including cases where skill columns should be removed when 技能成绩 is 0%.
---

# 平时成绩记分册生成器

## Purpose

Generate one 平时成绩记分册 `.xls` from a course score sheet named like `课程成绩单.xls`, preserving the bundled template style.

If the user has not provided a source workbook, remind them that this skill needs a `课程成绩单.xls` file or a folder containing it.

## Platform Support

- Windows: prefer `scripts/generate_gradebook.ps1`, which uses Microsoft Excel COM as the generation engine and writes through the v1.1 workbook-level named-range contract while preserving the native `.xls` template.
- macOS/Linux: use `scripts/generate_gradebook.py`, which requires Python 3, `openpyxl`, and LibreOffice/soffice. It converts `.xls` through LibreOffice, edits the workbook, then converts back to `.xls`.
- If LibreOffice is missing on macOS/Linux, tell the user to install LibreOffice before running the generator.

## Bundled Resources

- Default canonical template: `assets/templates/course-gradebook/v1.1.0/template.xls`
- Legacy canonical template: `assets/templates/course-gradebook/v1.0.0/template.xls`
- Compatibility template entry: `assets/平时成绩记分册模板.xls` (v1.0 legacy coordinates)
- Manifest and changelog: `assets/templates/course-gradebook/v1.1.0/manifest.yaml`, `assets/templates/course-gradebook/v1.1.0/CHANGELOG.md`
- Input schema: `schemas/gradebook-input.schema.json`
- Windows generator: `scripts/generate_gradebook.ps1`
- Cross-platform generator: `scripts/generate_gradebook.py`

Use Excel COM on Windows and Python/LibreOffice on macOS/Linux or when Excel COM is unavailable. Windows raw safety preflight uses Python `xlrd`/`olefile` and cannot be bypassed by either skip flag; LibreOffice is only needed for full round-trip, formatting, and rendering QA. When Windows receives both skip flags, it does not require LibreOffice. Both v1.1 paths use the same 24 managed workbook-level names from `named_range_contracts.py`; the v1.0 and compatibility paths remain explicit legacy-coordinate modes. v1.1 has no silent coordinate fallback.


## Multi-Agent Use

Treat the bundled generator scripts and the source workbook as the cross-agent contract. Codex loads this file as a skill; other agents should first read 通用提示词.md and the nearest tool adapter, then select the Windows or macOS/Linux path described here.

- AGENTS.md is the shared baseline for Codex CLI, OpenCode, Windsurf, Cursor CLI, and GitHub Copilot agents.
- CLAUDE.md and GEMINI.md are native entry points for Claude Code and Gemini CLI.
- Cursor, Cline, Continue, Windsurf, GitHub Copilot, and Aider adapters are included in the package and can be copied into another project with scripts/install_adapters.py.
- The workflow is model/provider independent. DeepSeek, Claude, GLM, Gemini, OpenAI, and other models can use it when their host tool can read files and run PowerShell or Python.
- Never invent a source workbook. If 课程成绩单.xls is missing, remind the user to provide it.
- The adapter installer skips existing files by default and creates a timestamped backup when --replace is explicitly supplied.

Read 多Agent兼容说明.md for the compatibility matrix and platform-specific limitations.

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
   - Confirm the manifest-defined number of generated 平时成绩 values average exactly to source 平时成绩.
   - Confirm 总评 equals source 总成绩.
   - Confirm no visible Excel errors such as `#REF!` or `#VALUE!`.
   - Confirm 技能成绩 columns are deleted when 技能成绩比例 is `0%`; otherwise keep 技能成绩 and 折合 columns.
   - For v1.1, confirm the QA report has `anchor_mode: excel_named_range`, the expected 21-name or 24-name variant, and matching top-level and `checks.named_ranges` diagnostics.

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
- v1.1 output writes use workbook-level names such as `gb_term`, `gb_data_table`, `gb_regular_items`, and the declared formula columns; do not replace them with hard-coded output coordinates.
- For up to 48 students, preserve the template capacity through row 52; for larger classes, extend data names to the generated last row while keeping `gb_template_row` at row 5.
- v1.0 uses legacy coordinates and deletes unused student rows. v1.1 keeps rows through 52 for up to 48 students, extends every dynamic data name to the exact last student row above capacity, and keeps `gb_template_row` at row 5.

## Template Package Workflow

Both generators follow `输入资料 → 标准化数据 → schema 校验 → 模板校验 → 临时候选 → raw runtime 检查 → 完整或 skip QA → XLS/QA 原子替换`. The Python path reads `manifest.yaml` directly. The Windows Excel COM path uses the bundled `manifest_to_json.py` bridge, so the same named-range contract, worksheet names, metadata fields, student rows, score columns, formula columns, regular-item count, and zero-skill column switch come from the same manifest. Template and output validation inspect both raw BIFF `.xls` names and round-trip `.xlsx` names. Normal generation writes `qa-report.json`; the report includes template/generator versions, anchor mode, named-range variant, actual template path, custom-template flag, engine, validation status, checks, errors, warnings, and skipped checks without copying student identifiers or raw scores. `--manifest`, `--schema`, `--skip-template-validation`, `--skip-output-validation`, `--qa-report`, and `--output-file` are optional additions to the original CLI; fingerprint and raw runtime validation still run before either skip path, and skipped validation still checks a real non-empty `.xls` and writes `status=skipped`. Candidate failure preserves existing formal outputs and unrelated XLS files. When `--output-file` is supplied, only that file is checked; legacy directory-only validation explicitly fails when multiple `.xls` candidates exist.

Install Python dependencies from `requirements.txt`. The Windows COM path requires Microsoft Excel plus Python `xlrd`/`olefile` for the non-skippable raw XLS preflight; LibreOffice is required only when full structural, round-trip, format, or rendering QA is requested. The cross-platform path requires LibreOffice/soffice for `.xls` conversion. `olefile` is also used by the versioned template builder to normalize raw BIFF metadata and is installed from the same requirements file. No external absolute tool path is a formal dependency.
