# 教案生成器工作规则

本文件是各类 agent 的轻量入口。开始教案任务前必须读取同目录 `SKILL.md` 和 `通用提示词.md`；Content Contract V2、QA、模板和事务规则只以 `SKILL.md` 为准，不在 adapter 中复制。

执行约束：

- 先读取用户会话、上传资料、能力图谱/任务拆解、课程标准、教材和旧教案；课程级规划先于逐课生成。
- 正式规划前必须一次性展示并确认 `course_name`、`major`、`audience`、`total_hours`；摘要固定写 `default_hours=2`（单课课时默认 2 学时），并建议确认教材但不把教材缺失作为阻断。确认后不得再次询问 outline、项目/任务、评分、模板、输出目录或是否开始生成 DOCX；除用户主动改变要求、无法解决的直接冲突或安全/覆盖决策外不再打断。
- `references` 只放可阅读、查阅、引用或作为课程依据的文献/文档；`resources` 放教学工具、设备、环境和材料。课程级 reference pool 中的合法来源可跨课复用，但同课内部重复 reference 和纯工具/设备名作为 reference 必须失败；禁止为了降重复率虚构书目信息或公开文献。
- 生成严格的 `content_contract_version: "2.0"` JSON。旧 sparse input（只含 task/hours/flows 等）不得用于生产生成。
- 所有正文、9 个实施阶段、逐课评价备注和三段反思由 JSON 提供；Python 只格式化、映射和校验，不创作正文、不截断、不使用旧默认套话。
- 运行 Content QA、模板 QA、输出保真 QA，并在可用时运行 Windows/macOS 本地 render smoke；正式目录只接受通过 QA 的 candidate 原子提交。
- Agent 生产流程禁止使用 `--skip-template-validation` 或 `--skip-output-validation`；依赖安装后用 `scripts/check_dependencies.py` 做只读检查，缺失时按提示由用户决定是否安装。

使用 `scripts/generate_lesson_plans.py`，完整字段与命令见 `SKILL.md`、`docs/content-contract-v2.md` 和 `examples/tasks.example.json`。
