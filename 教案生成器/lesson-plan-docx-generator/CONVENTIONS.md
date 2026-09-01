# Aider 约定

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`，不要在 Aider 配置中复制 Content 2.1 规则。任务开始一次性确认 course_name、major、audience、total_hours、theory_hours、practice_hours、理论/实践组织方式、default_hours=2、教材、辅助资料和是否需要实践任务工单；确认后直接完成课程级 outline、Practice Task Contract、JSON、QA 和 DOCX，不再询问模板、输出目录或是否开始生成。把课程资料整理成默认 `content_contract_version: "2.1"` 的 JSON（运行时兼容 2.0），课程教材与 reference_pool 分开，每课只写 reference_ids。

生成器会保护现有 v1.0/v1.1 Word 模板、semantic bookmark、manifest 和格式 QA。所有正文、9 个实施阶段、评价 remarks、反思和实践任务 prose 必须由 JSON 提供；Python 只做 schema、Content QA、格式化、输出保真和原子提交。`references` 只放可引用文献/文档，`resources` 放工具/设备/环境/材料；reference 可跨课复用，但同课重复 ID、未解析 ID、纯资源名和 generic 占位来源必须失败。非空输出目录须显式使用 `--backup-existing`，Windows/macOS 均运行真实校验。
