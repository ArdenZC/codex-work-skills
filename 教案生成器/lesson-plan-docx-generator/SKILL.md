---
name: lesson-plan-docx-generator
description: Generate projectized Chinese vocational-course lesson plan DOCX files from the built-in Word template, an optional supplied template, an Excel 能力图谱, or an inferred project/task structure. Use when the user asks to create, batch-generate, convert, split, or revise 教案/教学单元设计/实训教案 files, while preserving a DOCX template format, reminding the user what source files are helpful, defaulting to 项目化教学 when materials are missing, setting course names/hours, adding natural teaching evaluation scores, and verifying generated DOCX layout.
---

# Lesson Plan DOCX Generator

Use this skill to reproduce the established workflow for template-matched, projectized Chinese lesson plan DOCX generation.

## Intake Reminder

At the start of a generation task, briefly tell the user these materials are helpful, but do not block if they want you to proceed with reasonable assumptions:

- course name, major, audience, total hours, and per-lesson hours;
- 能力图谱/章节任务拆解 Excel, existing syllabus, textbook table of contents, or old lesson plans;
- a different DOCX template only if they do not want the built-in template;
- required output folder and any fixed unit/task names.

If the user provides none of these, infer a projectized teaching plan from the course name and common vocational-course structure. State the assumption, then generate instead of producing a chapter-only outline.

## Inputs

Require or infer:

- `template_docx`: optional. Use the canonical built-in template at `assets/templates/lesson-plan/v1.1.0/template.docx` unless the user explicitly supplies a different template. Supplying canonical `assets/templates/lesson-plan/v1.0.0/template.docx` or the old `assets/lesson-plan-template.docx` without `--manifest` automatically selects the v1.0 coordinate manifest; arbitrary custom templates require a matching `--manifest`.
- `output_dir`: final DOCX folder. Back up an existing output folder before overwriting.
- `course_name`: value for the title and `课程名称` cell.
- `tasks`: project/task records. Prefer extracting these from an Excel 能力图谱 when supplied.
- `hours`: per task or inferred by total hours. For 实训课 with 12 total hours, prefer 6 tasks x 2 hours unless the user supplies another structure.


## Multi-Agent Use

Treat tasks.json and scripts/generate_lesson_plans.py as the cross-agent contract. Codex loads this file as a skill; other agents should first read 通用提示词.md and the nearest tool adapter before producing the same JSON and running the same script.

- AGENTS.md is the shared baseline for Codex CLI, OpenCode, Windsurf, Cursor CLI, and GitHub Copilot agents.
- CLAUDE.md and GEMINI.md are native entry points for Claude Code and Gemini CLI.
- Cursor, Cline, Continue, Windsurf, GitHub Copilot, and Aider adapters are included in the package and can be copied into another project with scripts/install_adapters.py.
- The workflow is model/provider independent. DeepSeek, Claude, GLM, Gemini, OpenAI, and other models can use it when their host tool can read files and run Python; the DOCX result does not depend on a particular model API.
- The adapter installer skips existing files by default and creates a timestamped backup when --replace is explicitly supplied.

Read 多Agent兼容说明.md for the compatibility matrix and examples/tasks.example.json for a complete input example.

## Workflow

1. Use the `documents` skill for DOCX work. If an Excel 能力图谱 is supplied, use the `spreadsheets` skill only to inspect/extract task data, not to author the final DOCX.
2. Inspect the template structure before generation. The known template has one 30-row main table:
   - row 1: course/major/audience
   - row 2: unit/task/hours
   - row 4: learning analysis
   - row 5: teaching content
   - row 7: goals
   - rows 8-12: key/difficulty/method/resources/references
   - row 13: nested teaching evaluation table
   - rows 17, 19-25, 27: teaching implementation
   - rows 28-30: reflection
3. Extract tasks from the source:
   - For an Excel 能力图谱, inherit merged project/task cells downward.
   - Merge multiple `流程` rows under the same task into one lesson plan.
   - Keep project names in `单元名称`; keep task names in `任务名称`.
4. If no task source is supplied, create a projectized task list before writing JSON:
   - Use project names like `项目一 认识课程核心对象`, `项目二 完成基础操作`, `项目三 实施综合应用`, adjusted to the actual course.
   - Use task names as concrete deliverables or skill actions, not generic chapter titles.
   - For database-style courses, follow the pattern `项目一 理解数据库`, `项目二 设计学生信息管理数据库`, `项目三 创建与维护数据库`, `项目四 创建与维护数据表`, `项目五 查询与维护数据表`, etc.
   - For 实训课, use fewer project tasks and emphasize deliverables, tools,成果包,互评, and过程性评价.
5. Prepare a canonical JSON file and run `scripts/generate_lesson_plans.py`. Omit `--template` to use the manifest-selected built-in template.
6. The generator follows `输入资料 → 标准化数据 → schema 校验 → 模板校验 → 生成 → 输出校验 → QA 报告`. Validate all DOCX files:
   - count files and total hours;
   - assert 30 main-table rows;
   - assert `课程名称` and title match `course_name`;
   - assert each evaluation table exists and scores sum to the requested target;
   - scan for template course-name leftovers such as `Linux操作系统应用`.
7. Render and inspect layout:
   - Prefer the `documents` renderer if it works.
   - Use the installed documents renderer or LibreOffice when available; any local rendering helper is optional and is not a skill dependency.
   - Inspect a contact sheet plus at least one dense representative page.
8. Clean temporary scripts and QA images. Keep only final DOCX outputs and any intentional backup.

## Canonical Task JSON

Create a JSON file like:

```json
{
  "course_name": "软件测试实训",
  "major": "软件技术",
  "audience": "高职二年级",
  "default_hours": "2",
  "lessons": [
    {
      "unit": "项目一 软件测试实训项目准备",
      "task": "测试环境搭建与测试计划编制",
      "hours": "2",
      "flows": ["分析实训项目需求", "搭建测试环境并准备测试数据"],
      "knowledge": ["软件测试实训流程", "测试计划结构"],
      "tools": "测试计划模板、需求说明书、测试环境检查表",
      "score": 89.0
    }
  ]
}
```

Run:

```powershell
& "<bundled-python>" "<skill-dir>\scripts\generate_lesson_plans.py" `
  --tasks-json "F:\work\tasks.json" `
  --output-dir "F:\work\某课程教案"
```

To override the built-in template, pass `--template "D:\path\template.docx"`.

## Content Rules

- All generated lesson plans must be projectized by default: `单元名称` starts with `项目一/项目二/...`, and `任务名称` is an actionable task under that project.
- Preserve the template table structure and formatting by editing existing paragraphs/cells in place.
- Use `course_name` in both the title and row 1 course cell.
- Use natural Chinese teaching text for learning analysis, goals, teaching process, and reflection.
- For 实训课, emphasize task output, tools,操作记录,成果包,互评, and过程性评价.
- Scores should look realistic, usually 88.5-91.5, not all identical; input scores use 0.5-point increments.
- Keep the canonical JSON provider-neutral so another agent or model can continue the task without reinterpreting the document template.
- Do not change unrelated source files or existing folders without backing them up.

## Verification Notes

- If PowerShell displays Chinese filenames as mojibake, verify with Python/docx content before assuming files are corrupt.
- LibreOffice may paginate differently from Word. Use render QA to catch layout defects, but Word COM export is also acceptable when the user needs Word-native pagination.

## Template Package

- Manifest: `assets/templates/lesson-plan/v1.1.0/manifest.yaml`
- Canonical template: `assets/templates/lesson-plan/v1.1.0/template.docx`
- Canonical manifest and changelog: `assets/templates/lesson-plan/v1.1.0/manifest.yaml`, `assets/templates/lesson-plan/v1.1.0/CHANGELOG.md`
- Input schema: `schemas/lesson-plan-input.schema.json`
- Validators: `scripts/validate_template.py` and `scripts/validate_output.py`
- QA output: `qa-report.json` in the generated output directory

The package preserves the original single-paragraph replacement and multiline-cell writing modes. v1.1 writes through semantic Word bookmarks, uses Word-safe names no longer than 40 characters, accepts only ASCII decimal bookmark IDs, and verifies complete start/end boundaries, every header/footer story, and physical containers after generation; v1.1 manifest contract fields must be explicit and are never silently defaulted. v1.0 remains available through canonical or old compatibility template-only resolution as well as an explicit manifest. It does not depend on external absolute paths; install Python dependencies from `requirements.txt` when the host does not already provide them. Do not edit the canonical template directly; a custom template should be accompanied by a matching manifest.
