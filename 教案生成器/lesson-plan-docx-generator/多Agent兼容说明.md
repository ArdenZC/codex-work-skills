# 教案生成器多 Agent 兼容说明

所有 agent 和模型共用同一份规范：先读取 `SKILL.md` 和 `通用提示词.md`，再生成符合 `content_contract_version: "2.0"`/`"2.1"` 的 `tasks.json`，最后调用同一套 Python 生成器和 QA。不要在工具专用规则中复制 Content V2 字段或另造 DOCX 写入逻辑。Practice Task Contract V1 使用仓库 canonical `schemas/shared/practice-task-contract.schema.json`，WorkOrder Skill 也消费同一份 schema。

Lesson 任务正式规划前必须一次性确认 `course_name`、`major`、`audience`、`total_hours`，显示 `default_hours=2`，并把教材作为建议确认项而非阻断项。一次确认完成后不再询问 outline、项目/任务、评分、模板、输出目录或 DOCX 生成。`references` 是可阅读、查阅、引用或作为课程依据的文献/文档，`resources` 是教学工具、设备、环境和材料；课程级 reference pool 中的合法 reference 可跨课复用，不得为了降低重复率编造书目信息，同课重复和纯资源名仍失败。

## 可用入口

- Codex / Codex CLI：`SKILL.md`、`AGENTS.md`、`agents/openai.yaml`
- Claude Code：`CLAUDE.md`
- Gemini CLI：`GEMINI.md`
- Cursor、Cline、Continue、Windsurf、GitHub Copilot、Aider：各自 adapter 文件
- OpenCode：`AGENTS.md`

`scripts/install_adapters.py` 可以把 adapter 安装到另一个项目，默认是不复制 runtime 的 `instruction-only adapter install（仅规则/指令安装）`；它不承诺目标项目可以直接执行 generator。需要在目标项目的 `.lesson-plan-docx-generator/` 中直接运行 `scripts/generate_lesson_plans.py` 时，必须追加 `--copy-engine`，此时才是 `full runnable project-local Lesson engine（完整可运行引擎）`。Windows 使用 `python`，macOS 使用 `python3`；`--replace` 才会创建备份并替换。

视觉证据 `visual-inspection.json` 是 `Agent visual inspection attestation for the current generated DOCX/QA state`，不是所检查 PDF/图片的加密证明。

## 模型与平台

DeepSeek、Claude、GLM、Gemini、OpenAI 及其他能读文件和运行 Python 的 agent 都可以负责课程规划和完整 JSON 内容创作。Python 生成器只做确定性 schema/Content QA、格式化和受保护模板映射；因此模板结构由脚本约束，但教案正文质量仍取决于 Agent 提供的资料与 V2 JSON。Windows 使用 `python`，macOS 使用 `python3`；LibreOffice 仅用于可选 render smoke。

纯网页工具如果不能写文件或运行命令，可以先输出 V2 JSON，再交给有本地执行能力的 agent。生产流程、路径保护、事务提交和 QA 细节始终以 `SKILL.md` 为准。
