# Practice Task Contract V1

`Practice Task Contract V1` 是 Lesson Skill 在课程规划阶段交给后续实训任务工单 Skill 的跨专业 handoff。它描述“课程中安排哪些实践任务、由哪些课次承载、需要什么输入和验收标准”，不直接生成执行工单 DOCX。

## 版本与范围

```json
{"contract_version": "1.0", "granularity": "per_task"}
```

`granularity` 可为 `per_lesson`、`per_task` 或 `per_project`，默认建议 `per_task`。一个实践任务可以跨多个课次；课次不等于任务，不能按课次机械生成任务。

任务字段为：

- `task_id`、`project_id`、`title`、`lesson_ids`、`practice_hours`；
- `scenario`、`objectives`、`required_inputs`、`tools_or_materials`、`steps`；
- `deliverables`、`acceptance_criteria`、`safety_or_compliance`。

字段只表达通用的实践组织要求，不要求 IT 专业字段。护理、会计、机械和其他专业可以使用同一合同。

## 与 Content Contract 2.1 的关系

Content 2.1 的 `delivery_plan.practice_hours` 必须等于任务合同的 `practice_hours`，也必须等于所有任务 `practice_hours` 之和。实践课或综合课通过 `practice_task_ids` 关联任务；理论课必须使用空数组。任务的 `lesson_ids` 只能指向实践课或综合课，不能占用纯理论课。

Content 2.1 还要求课程级 `artifact_plan`：

```json
{"lesson_plans": true, "practice_work_orders": false}
```

Lesson Skill 负责课程组织和本合同；当 `artifact_plan.practice_work_orders=true` 且 WorkOrder Skill 可用时，Lesson Agent 在完成 Lesson QA/DOCX 后调用 WorkOrder Skill Agent，由其根据本 handoff 创作完整 WorkOrder Content V1、执行 QA 并生成工单 DOCX，最后统一交付。当前没有工单生成器时，只输出 `practice-task-contract.json` 作为 handoff，并明确 `WorkOrder Skill unavailable; handoff generated.`，不虚构工单 DOCX；Lesson Python generator 不得 subprocess 调用 WorkOrder Python。

## 与 Content Contract 2.2 的关系

Content 2.2 将 Lesson DOCX 限定为理论教学，实践学时只由本 V1 handoff 和后续 WorkOrder 承载。`delivery_plan.total_hours` 必须等于 `theory_hours + practice_hours`；理论 Lesson 的 `hours` 之和必须等于 `theory_hours`；所有任务 `practice_hours` 之和必须等于 `practice_hours`。`lesson_ids` 表示为实践任务提供知识准备或前置支撑的理论 Lesson ID，可以关联一个或多个理论课次，不表示要生成“实践 Lesson DOCX”。纯实践课程没有理论 Lesson 时，`lesson_ids` 使用空数组；这是 V1 合同在 2.2 artifact split 下的明确语义，合同版本仍为 `1.0`。

Practice Task 数量和 WorkOrder 数量都由 Agent 按任务边界动态规划，不按 `practice_hours / default_hours` 机械推导。跨课重复使用同一个 Lesson reference 不影响实践 handoff，也不要求为每个实践小时创建 Lesson DOCX。

## 生成边界

Python 只校验课时、ID、课次类型和合同结构，不代写实践任务的教学 prose。实际任务内容必须由 Agent 根据课程资料和已确认的课程基础信息提供。
