# 教案生成器多 Agent 兼容说明

所有 agent 和模型共用同一份规范：先读取 `SKILL.md` 和 `通用提示词.md`，再生成符合 `content_contract_version: "2.0"` 的 `tasks.json`，最后调用同一套 Python 生成器和 QA。不要在工具专用规则中复制 Content V2 字段或另造 DOCX 写入逻辑。

## 可用入口

- Codex / Codex CLI：`SKILL.md`、`AGENTS.md`、`agents/openai.yaml`
- Claude Code：`CLAUDE.md`
- Gemini CLI：`GEMINI.md`
- Cursor、Cline、Continue、Windsurf、GitHub Copilot、Aider：各自 adapter 文件
- OpenCode：`AGENTS.md`

`scripts/install_adapters.py` 可以把 adapter 安装到另一个项目，默认不覆盖已有规则，`--replace` 才会创建备份并替换。

## 模型与平台

DeepSeek、Claude、GLM、Gemini、OpenAI 及其他能读文件和运行 Python 的 agent 都可以负责课程规划和完整 JSON 内容创作。Python 生成器只做确定性 schema/Content QA、格式化和受保护模板映射；因此模板结构由脚本约束，但教案正文质量仍取决于 Agent 提供的资料与 V2 JSON。Windows 使用 `python`，macOS 使用 `python3`；LibreOffice 仅用于可选 render smoke。

纯网页工具如果不能写文件或运行命令，可以先输出 V2 JSON，再交给有本地执行能力的 agent。生产流程、路径保护、事务提交和 QA 细节始终以 `SKILL.md` 为准。
