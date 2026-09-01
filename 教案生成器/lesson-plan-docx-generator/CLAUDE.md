# Claude Code 入口

开始任务前读取 `SKILL.md` 和 `通用提示词.md`。它们是教案生成器的唯一行为规范：默认使用 Content Contract 2.1（兼容读取 2.0），先一次性确认课程名称、专业、授课对象、总课时、理论/实践学时、组织方式、`default_hours=2`、教材、辅助资料和实践任务工单需求，再做课程级 outline、Practice Task Contract、完整 JSON、Content/模板/输出 QA，最后原子提交 DOCX。确认后不得再问模板、输出目录或是否开始生成 DOCX。`course_materials.textbook` 与 `reference_pool` 分离，教材默认不写入 references；每课只用 `reference_ids`，references 是文献/文档来源，resources 是工具/设备/环境/材料，合法 reference 可跨课复用，同课重复 ID、纯资源名和占位文献不可用。不要使用 sparse input、不要手工改写模板或在教案中写入 QA/AI 说明。
