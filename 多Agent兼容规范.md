# 多Agent兼容规范

本仓库的两个现有 skill 都采用同一个跨工具协议：AI agent 负责读取输入资料、理解任务并生成结构化输入；skill 自带脚本负责模板写入、格式保留和结果校验。这样可以使用不同的模型和不同的 AI 工具，而不需要维护多套业务逻辑。

## 已覆盖的入口

- Codex / Codex CLI：SKILL.md 和 agents/openai.yaml，安装到用户的 Codex skills 目录。
- Claude Code：CLAUDE.md。
- Gemini CLI：GEMINI.md。
- Cursor / Cursor CLI：AGENTS.md；也可安装 .cursor/rules/ 规则。
- Cline：AGENTS.md；也可安装 .clinerules/ 规则。
- Continue：可安装 .continue/rules/ 规则。
- Windsurf：AGENTS.md；也可安装 .windsurf/rules/ 规则。
- OpenCode：AGENTS.md。
- GitHub Copilot CLI/Cloud Agent：AGENTS.md 和 .github/copilot-instructions.md。
- Aider：CONVENTIONS.md 和 .aider.conf.yml。

## 模型支持

工作流与模型供应商无关，DeepSeek、Claude、GLM、Gemini、OpenAI 以及其他能读写文件的模型都可以使用。需要注意的是，模型是否能生成最终文件取决于宿主工具是否允许本地文件读写和命令执行；纯网页聊天可以先输出结构化输入，由具备本地工具权限的 agent 完成脚本执行。

## 安装适配器

每个 skill 目录都包含 scripts/install_adapters.py。将适配规则复制到目标项目：

Windows:
python path/to/skill/scripts/install_adapters.py --target-dir path/to/project

macOS/Linux:
python3 path/to/skill/scripts/install_adapters.py --target-dir path/to/project

默认不覆盖目标项目中的现有文件。只安装指定工具时可重复传入 --adapter，例如 --adapter claude --adapter cursor；明确传入 --replace 才会备份并替换已有文件。若需要把整个 skill 包也复制到目标项目，可增加 --copy-engine；它会写入目标项目的 .lesson-plan-docx-generator 目录。

工具规则文件会随工具版本变化；如果某个工具暂时不识别专用目录，直接加载对应 skill 的 通用提示词.md 并执行内置脚本即可。