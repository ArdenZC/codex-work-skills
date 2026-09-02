# Gemini CLI 入口

若 `practice_work_orders=true`，Lesson Agent 完成 Lesson QA/DOCX 后必须检测并调用 WorkOrder Skill Agent，统一交付 Lesson 与 WorkOrder；不可用时明确 `WorkOrder Skill unavailable; handoff generated.`，不得由 Lesson Python 生成工单。

先读取 `SKILL.md` 和 `通用提示词.md`，遵循 Lesson Skill 2.1.1、Content Contract 2.1（兼容 2.0）和 QA 流程。正式规划前进入 `INTAKE_PENDING`，用中文一次性确认课程名称、专业、授课对象、总课时，并在同一摘要显示理论/实践课时、理论与实践组织方式（全部理论、全部实践、分段组织或综合组织）、单课默认 2 学时、教材、辅助资料和实践任务工单偏好；四个核心字段缺失时显示“待补充”，总课时必须由用户明确提供；未提供的结构显示“待确认”，不按 50/50、综合式或“否”推断，推断的专业/对象标注“当前理解 / 如不准确请修改”。用户确认后进入 `INTAKE_CONFIRMED`，直接完成 outline、Practice Task Contract、JSON、QA 和 DOCX，不再询问模板、输出目录或是否开始生成。课程级 outline 必须先于逐课生成；正文、实施、评价备注和反思由 JSON 提供，Python 只格式化、校验和写入受保护模板。`course_materials.textbook` 与 `reference_pool` 分离，教材默认不进入 references；每课只用 `reference_ids`，references 是文献/文档，resources 是工具/设备/环境/材料，合法 reference 可跨课复用，但同课重复 ID、纯资源名、2.1 generic 占位来源和为查重虚构书目信息必须失败。不要接受 sparse input、静默截断或把内部 QA 信息写入 DOCX。
