# Gemini CLI 入口

先读取 `SKILL.md` 和 `通用提示词.md`，遵循同一份 Content Contract 2.1（兼容 2.0）和 QA 流程。正式规划前一次性确认 course_name、major、audience、total_hours、theory_hours、practice_hours、理论/实践组织方式、default_hours=2、教材、辅助资料和是否需要实践任务工单；用户确认后直接完成 outline、Practice Task Contract、JSON、QA 和 DOCX，不再询问模板、输出目录或是否开始生成。课程级 outline 必须先于逐课生成；正文、实施、评价备注和反思由 JSON 提供，Python 只格式化、校验和写入受保护模板。`course_materials.textbook` 与 `reference_pool` 分离，教材默认不进入 references；每课只用 reference_ids，references 是文献/文档，resources 是工具/设备/环境/材料，合法 reference 可跨课复用，但同课重复 ID、纯资源名、2.1 generic 占位来源和为查重虚构书目信息必须失败。不要接受 sparse input、静默截断或把内部 QA 信息写入 DOCX。
