# 教案生成器多Agent兼容说明

本 skill 采用“AI 提取结构，脚本生成 DOCX”的跨工具协议。任何能读取课程资料、写出 tasks.json 并运行 Python 的 agent 都可以得到同一套模板结果。

## 入口

- Codex / Codex CLI：SKILL.md 和 agents/openai.yaml。
- Claude Code：CLAUDE.md。
- Gemini CLI：GEMINI.md。
- Cursor、Cline、Continue、Windsurf、GitHub Copilot、Aider：对应规则文件已放在本目录；也可以运行 scripts/install_adapters.py 复制到另一个项目。
- OpenCode：使用本目录的 AGENTS.md。

## 模型

DeepSeek、Claude、GLM、Gemini、OpenAI 等模型都可以负责生成同一格式的 tasks.json。DOCX 的表格结构、模板样式、评分拆解和总课时校验由 Python 脚本执行，不绑定模型 API。

## 使用限制

纯网页聊天工具如果没有本地文件和命令执行能力，可以先生成 tasks.json，再交给具备本地工具权限的 agent 执行脚本。需要 Python 3 和 python-docx；LibreOffice 只用于渲染或分页复核，不是生成 DOCX 的硬性依赖。

## 安装

在 Windows 使用 python，在 macOS/Linux 使用 python3：

python path/to/lesson-plan-docx-generator/scripts/install_adapters.py --target-dir path/to/project

默认不覆盖已有规则文件；增加 --adapter claude --adapter cursor 可以只安装指定适配器，增加 --replace 才会备份并替换已有文件。