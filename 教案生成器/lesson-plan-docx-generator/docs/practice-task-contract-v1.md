# Practice Task Contract 1.1

Practice Task Contract 1.1 是 Lesson 到 WorkOrder 的单向 handoff。它描述实践任务事实，不直接生成 WorkOrder DOCX；WorkOrder Agent 必须以它为上游事实源，并写入 linked Content 1.1 的 `source_task_snapshot`。

## 根合同

```json
{
  "contract_version": "1.1",
  "course_profile": {
    "course_name": "…",
    "major": "…",
    "audience": "…",
    "total_hours": 40,
    "theory_hours": 20,
    "practice_hours": 20,
    "delivery_mode": "split_lessons",
    "default_lesson_hours": 2
  },
  "practice_hours": 20,
  "granularity": "per_task",
  "tasks": []
}
```

课程基本信息必须逐字段继承已确认 Lesson，不能在实践侧推断或改写。实践学时必须是正偶数；每个 task 的 `practice_hours` 固定为 2；task 数量严格等于课程实践学时除以 2。`task_id`、`project_id`、`title`、`lesson_ids`、情境、目标、输入、工具/材料、步骤、交付物、验收标准和安全/合规约束由 Agent 根据课程事实提供。`lesson_ids` 可以为空（纯实践课程），或表示理论准备/前置课次；它不制造反向 Lesson 任务 ID。

## 质量与所有权

实践任务 prose、步骤、交付物和验收必须由 Agent 独立创作并由统一 Agent pedagogical review 检查专业准确性、目标—活动—证据、阶段连贯性、容量、递进和交付物覆盖。Python 只校验 schema、小时、ID、课程 profile、对象映射和跨文档保真，不用动作词、领域关键词、IT/护理 marker、字符/n-gram overlap 判断自然度或教学价值。

Lesson 理论课的 `practice_task_ids` 永远为空；WorkOrder 侧不反向生成 Lesson 关联。WorkOrder Agent 只能在 task facts 上展开或重组学生任务项，不得改写目标、交付物、验收、工具/材料或安全约束。

明确不需要实践工单时，实践学时仍进入课程总账，但不得创建本合同、handoff、WorkOrder 或实践侧额外文件。工单 Skill 不可用时保存本合同并使用原样提示：`实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`。

旧的 Practice Task Contract V1 仅保留为显式 legacy 输入；生产路径固定使用 1.1。
