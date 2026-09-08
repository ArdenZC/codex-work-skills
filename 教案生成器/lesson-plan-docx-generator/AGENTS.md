# 教案生成器工作规则 2.2.3

这是 Lesson Skill 的轻量入口。开始任务前必须读取同目录 `SKILL.md` 与 `通用提示词.md`；课程合同、QA、模板和事务规则以 `SKILL.md`、schema 与脚本为准，不在 adapter 中复制字段规则。

- 先进入 `INTAKE_PENDING`，只做一次全中文课程信息确认；确认后冻结课程事实，先做整门课程 outline，再生成完整 Content Contract 2.2 JSON 和 DOCX。
- 2.2.3 的 Lesson DOCX 只承载理论课时；课前 10 分钟、七个课中阶段合计 `hours × 45`、课后 15 分钟。1 学时的内容、步骤、证据和任务复杂度必须实质少于 2 学时。
- `course_materials.textbook`、lesson `resources`、`reference_pool` 三者分离。教材、PPT、课件、案例/数据、内部资源、任务单、设备和环境不是 references；可用的 references 需保留真实责任者与出处，书籍年份可选但不得写“年份未知”。
- 只有用户明确选择 `practice_work_orders=true` 才生成 Practice Task Contract 1.1 与 handoff；每个任务固定 2 学时，任务数和 WorkOrder 数均为实践学时除以 2，理论 Lesson 的 `practice_task_ids` 保持空数组。明确 false 时不生成实践侧文件。
- Lesson→WorkOrder 是单向 handoff。需要工单时，Lesson Agent 在 Lesson QA/DOCX 完成后调用 WorkOrder Skill Agent；不得由 Lesson Python subprocess 调用 WorkOrder Python，也不得伪造工单 DOCX。WorkOrder 不可用时必须原样提示：`实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`
- 正文、实施阶段、评价备注和反思由 Agent 提供；Python 只做 schema、硬事实、结构、格式、模板映射、输出与渲染门禁，不用动作词、专业词、IT/护理 marker、字符/n-gram 相似度判断自然度或教学充分性。自然度、相关性、容量与阶段语义由统一 Agent review 负责；有问题必须由 Agent 重写后再生成。
- 生产命令禁止跳过模板/输出校验；真实 render 未通过或未执行时不得标记 Production PASS。旧版本只可通过显式 legacy/兼容入口读取。
