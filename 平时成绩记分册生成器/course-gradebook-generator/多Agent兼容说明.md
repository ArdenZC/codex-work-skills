# 平时成绩记分册生成器多Agent兼容说明

本 skill 采用“AI 定位和理解源表，平台脚本稳定写入模板”的跨工具协议。任何能读取 Excel、执行 PowerShell 或 Python 的 agent 都可以使用。

## 入口

- Codex / Codex CLI：SKILL.md 和 agents/openai.yaml。
- Claude Code：CLAUDE.md。
- Gemini CLI：GEMINI.md。
- Cursor、Cline、Continue、Windsurf、GitHub Copilot、Aider：对应规则文件已放在本目录；也可以运行 scripts/install_adapters.py 复制到另一个项目。
- OpenCode：使用本目录的 AGENTS.md。

## 模型和平台

DeepSeek、Claude、GLM、Gemini、OpenAI 等模型都可以理解源表和选择命令。Windows 以 Excel COM 作为生成引擎，Python `xlrd`/`olefile` 执行不可跳过的 raw XLS preflight；LibreOffice 只用于完整 round-trip、格式和渲染 QA，双 skip 时 COM 不要求 LibreOffice。macOS/Linux 使用 Python、openpyxl 和 LibreOffice/soffice。两条 v1.1 路径共用 manifest 和 `gb_` named-range contract，不依赖某一模型 API，也不允许静默退回坐标写入。v1.0 仍是 legacy coordinates，v1.1 是 workbook-level named ranges；v1.1 48 人以内保留到第 52 行，超出容量精确扩展至最后一名学生并固定 `gb_template_row` 为第 5 行。

所有 agent 都应理解同一事务语义：候选生成 → raw runtime → 可选完整或 skip QA → XLS/QA 原子提交。失败保留旧正式文件和无关 XLS，只清理本轮临时文件；skip QA 不是无检查，仍须验证非空 `.xls` 和 v1.1 原始命名区域。

## 使用限制

没有课程成绩单.xls 时不能生成真实成绩册，必须提醒用户补充源文件。纯网页聊天工具可以先给出所需命令和校验清单，再交给具备本地文件权限的 agent 执行。

## 安装

在 Windows 使用 python，在 macOS/Linux 使用 python3：

python path/to/course-gradebook-generator/scripts/install_adapters.py --target-dir path/to/project

默认不覆盖已有规则文件；增加 --adapter claude --adapter cursor 可以只安装指定适配器，增加 --replace 才会备份并替换已有文件。
