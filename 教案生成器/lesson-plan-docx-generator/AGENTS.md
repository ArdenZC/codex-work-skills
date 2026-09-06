# 教案生成器工作规则 2.2.1

本文件是各类 agent 的轻量入口。开始教案任务前必须读取同目录 `SKILL.md` 和 `通用提示词.md`；Content Contract 2.2、QA、模板和事务规则只以 `SKILL.md` 为准，不在 adapter 中复制。

执行约束：

- 先读取用户会话、上传资料、能力图谱/任务拆解、课程标准、教材和旧教案；课程级规划先于逐课生成。
- 开始时进入 `INTAKE_PENDING`，正式规划前只做一次全中文课程基本信息确认：课程名称、专业、授课对象、总课时；摘要同时显示理论课时、实践课时、理论与实践组织方式（可选：全部理论、全部实践、分段组织、综合组织）、单课课时默认 2 学时、使用教材、辅助参考资料和是否同时生成实践任务工单。内部字段映射与状态规则见 `docs/intake-contract-v2.1.1.json`，不要把英文 key 作为用户界面。
- 四个核心字段缺失时必须在同一摘要显示“待补充”，总课时只能来自用户明确事实；未明确提供的理论/实践结构、组织方式和工单偏好必须显示“待确认”，不得默认 50/50、综合式或“否”。专业/授课对象若为推断，必须标注“当前理解 / 如不准确请修改”。Intake 未确认前不得提前确定项目、课次结构、实践任务数量、正文或 DOCX；用户确认后进入 `INTAKE_CONFIRMED`，再按已确认的工单选择完成资料检索、outline、Content Contract 2.2、QA 和 DOCX。
- 这一次确认后不得再问 outline、任务、评分、模板、输出目录或是否开始 DOCX。只有明确 `practice_work_orders=true` 才由 Lesson Agent 检测并调用可用的 WorkOrder Skill Agent，完成 WorkOrder Content V1、QA、DOCX 和统一交付；明确 false 时保留实践学时总账但不产生 Practice Task Contract、handoff、WorkOrder 或实践侧额外文件；WorkOrder 不可用时仅在 true 分支明确 `实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`，不伪造工单。
- 2.2 的 `course_materials.textbook` 与 `reference_pool` 分离；教材默认不写入 Word references。Lesson DOCX 只承载理论课时，实践课时不进入 Lesson DOCX；`sum(lesson.hours)=theory_hours`，实践学时仍参与课程总账，理论与实践合计等于总课时。理论课次按 `ceil(theory_hours/default_hours)` 计算，余数课时必须保留，不能四舍五入。
- 2.2 每个理论 Lesson 必须引用至少一项 `reference_ids`；references 是可阅读、查阅、引用或作为课程依据的文献/文档，resources 是工具、设备、环境和材料。引用目录按用户资料、国内出版物/高校资料、国家/行业/职业标准、国内权威文档、国外经典优先建立；国内占比是质量信号，不得为凑占比或降低重复率虚构作者、出版社、ISBN、版次或标准编号。合法 references 可跨课复用，同课重复 ID、未解析 ID、占位文献和纯资源名必须失败；教材只有显式允许时才可同时作为 reference。
- 默认使用 `content_contract_version: "2.2"` JSON；运行时兼容读取 2.1 和 2.0。仅在 `practice_work_orders=true` 时使用 Practice Task Contract：实践学时为正偶数，每任务 2 学时，任务数和 WorkOrder 数均为 `practice_hours / 2`；任务的 `lesson_ids` 只表示相关理论 Lesson 的准备/前置关系，纯实践课程可以为空，`project_id` 只用于分组。明确 false 时不填 handoff，所有 `practice_task_ids` 保留为空数组且不得有任务 ID。项目数和 Lesson 数仍按课程设计，但 WorkOrder 不得另行重规划。
- 所有正文、9 个实施阶段、逐课评价备注和三段反思由 JSON 提供；Python 只格式化、映射和校验，不创作正文、不截断、不使用旧默认套话。
- 运行 Content QA、模板 QA、输出保真 QA，并在可用时运行 Windows/macOS 本地 render smoke；正式目录只接受通过 QA 的 candidate 原子提交。
- WorkOrder 联动必须保持 Agent orchestration；Lesson Python generator 不得 subprocess 调用 WorkOrder Python，也不得从 handoff 自动创作工单正文。
- Agent 生产流程禁止使用 `--skip-template-validation` 或 `--skip-output-validation`；依赖安装后用 `scripts/check_dependencies.py` 做只读检查，缺失时按提示由用户决定是否安装。

使用 `scripts/generate_lesson_plans.py`，完整字段与命令见 `SKILL.md`、`docs/content-contract-v2.md`、`docs/practice-task-contract-v1.md`、`schemas/lesson-plan-input.schema.json`、仓库 canonical `schemas/shared/practice-task-contract.schema.json` 和 `examples/tasks-v21.example.json`；`schemas/practice-task-contract.schema.json` 仅为兼容入口，`examples/tasks.example.json` 仅保留为 2.0 兼容示例。
