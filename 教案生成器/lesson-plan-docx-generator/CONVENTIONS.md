# Aider 约定（Lesson Skill 2.2.1）

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`，不要在 Aider 配置中复制 Content 2.2 规则。任务开始进入 `INTAKE_PENDING`，用中文一次性确认课程名称、专业、授课对象、总课时，并同屏显示理论/实践课时、理论与实践组织方式、单课默认 2 学时、教材、辅助资料和是否同时生成实践任务工单；四个核心字段缺失时显示“待补充”，总课时必须由用户明确提供；未提供的结构显示“待确认”，不按 50/50、综合式或“否”推断。教材建议确认但不是阻断字段，默认单课 2 学时不单独追问。确认后进入 `INTAKE_CONFIRMED`，按工单选择直接完成课程级 outline、必要时的 Practice Task Contract、JSON、QA 和 DOCX，不再询问模板、输出目录或是否开始生成。把课程资料整理成默认 `content_contract_version: "2.2"` 的 JSON（运行时兼容 2.1/2.0），Lesson DOCX 只承载理论；明确 true 时 Practice Task 与 WorkOrder 按每任务 2 学时、任务数等于实践学时除以 2 交付，明确 false 时实践只计入总账且不生成 contract/handoff/WorkOrder。课程参考资料优先使用国内出版物、高校资料和标准并允许真实来源跨课复用。

生成器会保护现有 v1.0/v1.1 Word 模板、semantic bookmark、manifest 和格式 QA。所有正文、9 个实施阶段、评价 remarks、反思和实践任务 prose 必须由 JSON 提供；Python 只做 schema、Content QA、格式化、输出保真和原子提交。`references` 只放可引用文献/文档，`resources` 放工具/设备/环境/材料；reference 可跨课复用，但同课重复 ID、未解析 ID、纯资源名和 generic 占位来源必须失败。非空输出目录须显式使用 `--backup-existing`，Windows/macOS 均运行真实校验。
