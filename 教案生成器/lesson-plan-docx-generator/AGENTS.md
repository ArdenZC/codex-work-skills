# 教案生成器工作规则 2.1

本文件是各类 agent 的轻量入口。开始教案任务前必须读取同目录 `SKILL.md` 和 `通用提示词.md`；Content Contract 2.1、QA、模板和事务规则只以 `SKILL.md` 为准，不在 adapter 中复制。

执行约束：

- 先读取用户会话、上传资料、能力图谱/任务拆解、课程标准、教材和旧教案；课程级规划先于逐课生成。
- 正式规划前一次性展示并确认 `course_name`、`major`、`audience`、`total_hours`、`theory_hours`、`practice_hours`、理论/实践组织方式、`default_hours=2`、教材、辅助参考资料和是否需要实践任务工单。已提供信息直接显示，不重复追问。
- 这一次确认后直接完成资料检索、outline、Content Contract 2.1、Practice Task Contract、QA 和 DOCX；不得再问 outline、任务、评分、模板、输出目录或是否开始 DOCX。
- 2.1 的 `course_materials.textbook` 与 `reference_pool` 分离；教材默认不写入 Word references。每课只用 `reference_ids`，空数组合法；references 是可引用文献/文档，resources 是工具/设备/环境/材料。合法来源可跨课复用，同课重复 ID、未解析 ID、占位文献和纯资源名必须失败；禁止为降重复率虚构书目信息。
- 默认使用 `content_contract_version: "2.1"` JSON；运行时兼容读取 2.0。旧 sparse input（只含 task/hours/flows 等）不得用于生产生成。
- 所有正文、9 个实施阶段、逐课评价备注和三段反思由 JSON 提供；Python 只格式化、映射和校验，不创作正文、不截断、不使用旧默认套话。
- 运行 Content QA、模板 QA、输出保真 QA，并在可用时运行 Windows/macOS 本地 render smoke；正式目录只接受通过 QA 的 candidate 原子提交。
- Agent 生产流程禁止使用 `--skip-template-validation` 或 `--skip-output-validation`；依赖安装后用 `scripts/check_dependencies.py` 做只读检查，缺失时按提示由用户决定是否安装。

使用 `scripts/generate_lesson_plans.py`，完整字段与命令见 `SKILL.md`、`docs/content-contract-v2.md`、`docs/practice-task-contract-v1.md`、两个 schema 和 `examples/tasks-v21.example.json`；`examples/tasks.example.json` 仅保留为 2.0 兼容示例。
