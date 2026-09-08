---
name: lesson-plan-docx-generator
description: Generate projectized Chinese vocational-course lesson plan DOCX files from Lesson Content Contract 2.2, using the protected Word template, deterministic QA, and optional render smoke.
---

# 教案生成器 Skill 2.2.3

本文件是 Lesson 的唯一人类行为合同。当前 Content Contract 仍为 2.2，默认 Word 模板为 `lesson-plan v1.1.2`，模板 binary 和模板版本不变；2.0/2.1 只作显式 `--legacy` 兼容读取。Schema 和 Python 只实现确定性字段、课时、来源、模板和输出门禁，不代替 Agent 创作教学正文或教学判断。

## 任务入口与一次性确认

任务开始先读取当前会话、用户附件、能力图谱、章节任务拆解、课程标准、教材目录和指定模板。正式规划前进入 `INTAKE_PENDING`，用中文集中确认一次：课程名称、专业、授课对象、总课时、理论课时、实践课时、理论与实践组织方式、单课课时默认 2 学时、使用教材、辅助参考资料、是否同时生成实践任务工单。核心字段未给出显示“待补充”；理论/实践拆分、组织方式和工单偏好未给出显示“待确认”；推断的专业或对象标记“当前理解 / 如不准确请修改”。不得默认 50/50、综合式或“不需要”。

用户确认后进入 `INTAKE_CONFIRMED`，把课程名称、专业、授课对象、总课时、理论课时、实践课时和组织方式冻结到 `confirmed_course_info`，正文 Agent 不得改名或重写。确认后不再询问 outline、项目/任务、评分、模板、输出目录或“是否开始生成 DOCX”；只有新冲突、覆盖安全或用户主动改变要求才暂停。用户界面使用中文标签，不把内部字段名作为提问内容；具体状态合同见 `docs/intake-contract-v2.1.1.json`。`default_hours=2` 只表示默认单课 2 学时，教材为 recommended, not required。

没有任务资料时也必须先形成整门课程 outline，再写逐课内容。Outline 至少给出目标、模块/项目、课次、学时、先决知识、能力阶段、课次产出、相邻课次衔接和案例策略；每项需包含 `lesson_id`、`unit`、`task`、`lesson_type`、`hours`、`theory_hours`、`practice_hours`、`prior_learning`、`capability_stage`、`deliverable`、`next_bridge`、`practice_task_ids`。outline 是全课程骨架，不能只根据单课临时拼接。

## Content Contract 2.2

课程级输入至少包含：

```text
content_contract_version, course_name, major, audience,
default_hours, total_hours, delivery_plan, course_materials,
reference_pool, reference_research, artifact_plan, outline, lessons
```

2.2 Lesson DOCX 只承载理论课时。所有 Lesson 的 `lesson_type=theory`、`practice_hours=0`，Lesson 学时之和等于 `delivery_plan.theory_hours`；理论课次数量为 `ceil(theory_hours / default_hours)`，最后一课保留真实 1 学时尾数，不把余数四舍五入。以 40 学时、20 理论、20 实践为例：不需要工单时为 10 份 Lesson、0 份 WorkOrder；需要工单时仍为 10 份 Lesson、10 份 WorkOrder。

`practice_task_ids` 是保留的兼容字段，Content 2.2 理论 Lesson 必须为 `[]`；PracticeTask 的 `lesson_ids` 单向指向理论 Lesson。Lesson 不保存 WorkOrder 的反向链接，也不因为工单需求改变理论课时。

每课必须独立提供学生分析、教学内容、知识/能力/素质目标、重难点与策略、教学方法、资源、递进关系、评价和反思。实现阶段固定九个 ID 和顺序：

```text
before_class_preparation
task_introduction
operation_demonstration
task_implementation
task_extension
project_practice
peer_review
lesson_summary
after_class_improvement
```

每阶段由 Agent 写入 `content`、`teacher_actions`、`student_actions` 和 `objective`。必须形成“内容 → 教师活动 → 学生活动 → 学生证据/产出 → 设计意图”的阶段级教学链；不要求每个小项机械重复课题，也不能用“所有 item status=passed”作为唯一语义判断。同一课内部可以自然复用必要术语，但不得复制机械句式。阶段语义由 Agent review 负责。

时间合同固定为：课前准备 10 分钟、课后完善 15 分钟；七个课中阶段合计严格等于 `lesson.hours × 45` 分钟。课前/课后不计入 `theory_hours`、`total_hours` 或课堂学时；每课必须显式写入 10 和 15，不能写 0 或可变范围。1 学时 Lesson 的课中内容、步骤、证据和任务复杂度必须实质性少于 2 学时，不能只把分钟数缩短。

## 资料、教材与参考文献

`course_materials.textbook`、课次 `resources` 和课程级 `reference_pool` 始终分离。教材、PPT、课件、案例表/案例数据、任务单、设备、环境和内部教学文件不是 references。教材对象要求真实 `authors`/编者、`title`、`publisher`、`source_kind`；`edition`、`year`、ISBN 等可选，可靠时才写年份；不写“年份未知”、空逗号或猜测书目信息。

有可验证外部来源时，Agent 先检索真实来源再建立 reference pool；`book` 至少有作者/编者、书名、出版社，`formal_course_document` 保留真实责任者、机构和平台/出版社，URL/evidence 只留在 JSON/QA。没有联网、没有可靠外部来源、只有用户提供教材/PPT/资源时，允许 `reference_pool=[]`，并写 `reference_research.status=no_verified_external_source`；此时课次 `reference_ids` 可以为空。参考资料规划概念可称 `course_reference_pool` 或 `reference_catalog`，落盘仍只有 canonical `reference_pool`；`source_region` 仅用于来源记录。不得为了“凑数”虚构作者、出版社、ISBN、标准编号或公开来源。

引用身份只做保守规范化：Unicode、书名括号、空白、全/半角标点、中文/阿拉伯数字版次和常见版次后缀可统一；相近但不同的书名不能被模糊合并，例如“数据结构基础”不能等同于“高级数据结构”。教材不进入 references；同一真实来源跨课复用可以通过，单课内部重复仍失败。禁止为了降低课程重复率编造或改写参考来源。

## Practice Task Contract 1.1 与 WorkOrder 联动

只有用户明确选择 `practice_work_orders=true` 时才生成 handoff。Practice Task Contract 1.1 使用仓库唯一 canonical schema `schemas/shared/practice-task-contract.schema.json`，顶层必须有 `contract_version`、`course_profile`、`practice_hours`、`granularity`、`tasks`。课程基本盘必须逐字段继承已确认 Lesson：课程名称、专业、对象、总课时、理论课时、实践课时、组织方式、默认单课学时；不能在实践侧推断或改写。

实践学时必须为正偶数；任务数为 `practice_hours / 2`，每个 Practice Task 固定 2 学时。任务必须保留 `task_id`、`project_id`、`title`、`lesson_ids`、`practice_hours`、`scenario`、`objectives`、`required_inputs`、`tools_or_materials`、`steps`、`deliverables`、`acceptance_criteria`、`safety_or_compliance`。`project_id` 只作上层分组，不改变一任务一工单粒度。

Lesson Agent 先完成全课程 outline、理论 Lesson、Content QA 和 Practice Task Contract，再通过 Agent orchestration 调用 WorkOrder Skill Agent；Lesson Python 不得 subprocess 调用 WorkOrder Python。WorkOrder Agent 必须独立创作 WorkOrder Content 1.1，完成来源快照、Cross-Artifact QA、Output QA 和真实渲染。若 WorkOrder Skill 不可用，只交付 Lesson 与 handoff，并明确：`实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`；不得伪造工单 DOCX。

若用户明确选择 `practice_work_orders=false`，实践学时仍计入课程总账，但禁止 practice contract、handoff、WorkOrder 和实践侧额外文件；Lesson 的 `practice_task_ids` 仍为 `[]`。

## Agent 与 Python 的边界

Agent 负责课程级规划、相邻衔接、案例策略、所有教学正文、阶段活动、学生证据、评价 remarks、反思、参考来源判断和 Practice Task prose。每课必须附 `pedagogical_review`，至少审阅专业准确性、目标—活动—证据链、阶段连贯性、课时容量、递进关系和参考文献相关性；发现问题先重写再交给生成器。

Python 只 hard-fail 可确定事实：课时和阶段分钟、理论/实践账、ID 与 outline 一致性、`practice_task_ids=[]`、参考来源元数据/来源状态、教材与 references 分离、课程基本盘、schema、模板、事务、DOCX 结构/保真和真实渲染。它不得用字符 n-gram、相似度阈值、动作词或专业词库来判断自然度、相关性、教学价值、案例质量、90 分钟完成度或阶段语义，也不能发现问题后向 JSON 追加教学句子。

为防止机械注入，formatter 只删除独立的主题元话术尾缀，如 `聚焦/聚焦于/围绕/针对/对应主题/核心主题/本节主题/任务主题/本节关联：...`；正常专业句子不改写，例如“比较两种结构的空间代价，对应不同数据规模。” 最终 DOCX 的这类 meta suffix 计数必须为 0，不能把防御性清理当作根层教学质量判断。

## 生成与生产门禁

```text
读取资料 → 一次性 Intake 确认 → 全课程 outline
→ Content Contract 2.2 / Practice Task Contract 1.1（如明确需要）
→ Input/Content QA → candidate DOCX → Output QA
→ 请求时真实 Render Smoke → atomic commit
→ 如需工单则调用 WorkOrder Skill Agent → 统一交付与人工验收
```

默认使用模板路径 `assets/templates/lesson-plan/v1.1.2/template.docx`。生成器先在正式目录同父目录创建 candidate，所有结构/内容/模板/路径 QA 通过后才交换；非空输出目录需显式 `--backup-existing`，失败须恢复原输出。`--render` 的结果只代表 smoke；缺少渲染后端时报告 `RENDER UNVERIFIED` 或 fail-closed，不能声称分页/视觉通过。人工视觉检查另行记录，至少查看第一课、最密集课和最后一课。

生产命令：

```powershell
python scripts/generate_lesson_plans.py --tasks-json tasks.json --output-dir output --render
```

`--skip-template-validation`、`--skip-output-validation` 只允许受控测试并需显式环境变量；生产交付不得绕过。安装器不自动安装 Python 依赖，只执行完整源树、shared schema、模板和 fingerprint 的事务安装；完成后应在新会话中验证 Skill 版本和真实生成路径。

旧 Content 2.0/2.1 只走明确 `--legacy` 兼容入口，默认新生成遵循 2.2。不要删除、修改或重新发布 `lesson-plan v1.1.2` 模板 binary，也不要在本轮进入 Phase 3 或完整课程批量生产。
