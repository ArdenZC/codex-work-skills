# 教案生成器多 Agent 兼容说明

所有 agent 和模型共用同一份 Lesson Skill 2.2.1 规范：先读取 `SKILL.md` 和 `通用提示词.md`，再生成符合 `content_contract_version: "2.2"`（兼容 `"2.1"`/`"2.0"`）的 `tasks.json`，最后调用同一套 Python 生成器和 QA。不要在工具专用规则中复制 Content V2 字段或另造 DOCX 写入逻辑。Practice Task Contract V1 只在用户明确需要实践工单时使用，实践任务固定 2 学时、任务数和 WorkOrder 数均为实践学时除以 2；明确不需要时实践只计入课程总账，不生成 handoff 或实践侧文件。Contract 使用仓库 canonical `schemas/shared/practice-task-contract.schema.json`，WorkOrder Skill 也消费同一份 schema。

Lesson 任务正式规划前必须进入 `INTAKE_PENDING`，用中文一次性确认课程名称、专业、授课对象、总课时，并在同一摘要显示理论课时、实践课时、理论与实践组织方式（全部理论、全部实践、分段组织或综合组织）、单课默认 2 学时、教材、辅助参考资料和实践任务工单偏好。四个核心字段缺失时显示“待补充”，总课时必须由用户明确提供；未明确提供的结构显示“待确认”，不能按 50/50、综合式或“否”推断；推断的专业/对象标注“当前理解 / 如不准确请修改”。教材建议确认但不是阻断字段，默认单课 2 学时不单独追问。确认后进入 `INTAKE_CONFIRMED`，不再询问 outline、项目/任务、评分、模板、输出目录或 DOCX 生成。2.2 Lesson DOCX 只承载理论，实践课时不进入 Lesson；只有明确需要实践工单时才由 Practice Task/WorkOrder handoff 表达，实践任务固定 2 学时、数量与 WorkOrder 数均为实践学时除以 2，明确不需要时不生成 handoff。若用户确认需要实践工单，Lesson Agent 完成 Lesson QA/DOCX 后必须检测并调用 WorkOrder Skill Agent，统一交付；不可用时明确 `实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`，不得由 Lesson Python 生成或伪造工单 DOCX。`references` 是可阅读、查阅、引用或作为课程依据的文献/文档，`resources` 是教学工具、设备、环境和材料；课程级 reference pool 中的合法 reference 可跨课复用，优先国内出版物、高校资料和标准，不得为了降低重复率编造书目信息，同课重复和纯资源名仍失败。完整映射见 `docs/intake-contract-v2.1.1.json`。

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
