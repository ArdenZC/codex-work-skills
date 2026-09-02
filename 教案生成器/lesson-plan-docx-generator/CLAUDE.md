# Claude Code 入口

若 `practice_work_orders=true`，Lesson Agent 完成 Lesson QA/DOCX 后必须检测并调用 WorkOrder Skill Agent，统一交付 Lesson 与 WorkOrder；不可用时明确 `WorkOrder Skill unavailable; handoff generated.`，不得由 Lesson Python 生成工单。

开始任务前读取 `SKILL.md` 和 `通用提示词.md`。它们是教案生成器的唯一行为规范：当前为 Lesson Skill 2.1.1，默认使用 Content Contract 2.1（兼容读取 2.0）。先进入 `INTAKE_PENDING`，用中文一次性确认课程名称、专业、授课对象、总课时；同一摘要显示理论/实践课时、理论与实践组织方式（全部理论、全部实践、分段组织或综合组织）、单课默认 2 学时、教材、辅助资料和实践任务工单偏好。四个核心字段缺失时显示“待补充”，总课时必须由用户明确提供；未明确提供的结构显示“待确认”，不按 50/50、综合式或“否”推断；推断的专业/对象标注“当前理解 / 如不准确请修改”。确认后进入 `INTAKE_CONFIRMED`，直接做课程级 outline、Practice Task Contract、完整 JSON、Content/模板/输出 QA，最后原子提交 DOCX，不能再问模板、输出目录或是否开始 DOCX。`course_materials.textbook` 与 `reference_pool` 分离，教材默认不写入 references；每课只用 `reference_ids`，references 是文献/文档来源，resources 是工具/设备/环境/材料，合法 reference 可跨课复用，同课重复 ID、纯资源名和占位文献不可用。不要使用 sparse input、不要手工改写模板或在教案中写入 QA/AI 说明。
