# Practice Work Order Content V1

## 输入与来源

Content V1 是 WorkOrder Skill 的直接写入合同，`content_contract_version` 保持 `1.0`。每份输入包含课程基本信息、`practice_task_id`、项目名、正整数实践学时、组信息和 1–5 个任务项。可选的 `task_title`、`project_id`、`safety_or_compliance` 用于保留 Practice Task 的追踪和约束信息。

Lesson handoff 使用 canonical `schemas/shared/practice-task-contract.schema.json` 中的 Practice Task Contract V1。它是上游事实源，不是 WorkOrder 的第二份课程合同。WorkOrder 映射不得随机生成新的任务 ID、改变 `lesson_ids` 集合或改变 `practice_hours`。

## 字段边界

上游继承字段：`practice_task_id`、`project_id`、`task_title`、`lesson_ids`、`practice_hours`、`scenario`、`objectives`、`required_inputs`、`tools_or_materials`、`deliverables`、`acceptance_criteria` 和 `safety_or_compliance`。

WorkOrder 渲染字段：课程/专业/对象、`project_name`、组占位符、由 Agent 展开的 `task_items`、固定评价占位。Python 只做验证、确定性映射和模板格式化，不重新创作任务正文或答案。

每个 task item 包含：

- `title`：任务标题；
- `description`：给学生看的任务说明；
- `score`：正整数，所有任务合计必须为 90；
- `tools_or_materials`：实施所需工具、设备、环境或材料；
- `steps`：可执行步骤；
- `deliverables`：学生应提交的可观察产物；
- `acceptance_criteria`：能判断产物是否完成的标准。

课堂考勤固定 10 分，任务固定 90 分，合计 100 分。合同不增加可漂移的 `total_score` 字段。

## QA 与输出

Content QA 拒绝空泛任务、不可观察交付物、无覆盖验收标准、明显跨专业污染、同一工单内叙述重复和分值错误；跨工单只比较任务叙述、交付物及验收叙述。固定课堂考勤、学生/教师评价 rubric 不参与反重复 hard-fail。

Cross-Artifact QA 检查上游与工单的 ID、课次集合、小时、标题意图、交付物、验收标准、工具/材料和安全/合规约束。失败时 WorkOrder 失败，不自动修改 Practice Task 或 Lesson。

任务结果列保持空白；不能写标准答案、完整 SQL、最终模型、护理/会计最终结果或教师答案。学生评价的自评/小组评价/教师评价以及教师评价表的固定问题保持模板原样。
