# 教案生成器工作规则

本文件是各类 agent 的轻量入口。开始教案任务前必须读取同目录 `SKILL.md` 和 `通用提示词.md`；Content Contract V2、QA、模板和事务规则只以 `SKILL.md` 为准，不在 adapter 中复制。

执行约束：

- 先读取用户会话、上传资料、能力图谱/任务拆解、课程标准、教材和旧教案；课程级规划先于逐课生成。
- 一次核对课程名、专业/对象、总课时、单次课时和输出目录。资料不足且用户允许推断时继续，不把推断说明写进 DOCX。
- 生成严格的 `content_contract_version: "2.0"` JSON。旧 sparse input（只含 task/hours/flows 等）不得用于生产生成。
- 所有正文、9 个实施阶段、逐课评价备注和三段反思由 JSON 提供；Python 只格式化、映射和校验，不创作正文、不截断、不使用旧默认套话。
- 运行 Content QA、模板 QA、输出保真 QA，并在可用时运行 Windows/macOS 本地 render smoke；正式目录只接受通过 QA 的 candidate 原子提交。
- Agent 生产流程禁止使用 `--skip-template-validation` 或 `--skip-output-validation`；依赖安装后用 `scripts/check_dependencies.py` 做只读检查，缺失时按提示由用户决定是否安装。

使用 `scripts/generate_lesson_plans.py`，完整字段与命令见 `SKILL.md`、`docs/content-contract-v2.md` 和 `examples/tasks.example.json`。
