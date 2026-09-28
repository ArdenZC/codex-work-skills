# Lesson Content Contract 2.3

Lesson Skill 2.3.1 默认生成 Content Contract 2.3。Content 2.2 仍按原合同读取，不会被静默改写；Template 1.1.2、九阶段、评价体系、Practice Task Contract 1.1 和 Benchmark sidecar 架构均保持不变。

## Lesson coverage by delivery mode

`expected_lesson_coverage_hours(delivery_plan)` 是唯一课时覆盖规则：

| `delivery_plan.mode` | Lesson coverage | Lesson count |
| --- | --- | --- |
| `theory_only` | `total_hours` | `ceil(total_hours / default_hours)` |
| `integrated_lessons` | `total_hours` | `ceil(total_hours / default_hours)` |
| `hybrid` | `total_hours` | `ceil(total_hours / default_hours)` |
| `split_lessons` | `theory_hours` | `ceil(theory_hours / default_hours)` |
| `practice_only` | 0; preserve the existing no-Lesson behavior | 0 |

最后一课保留真实余数，不得将 1 学时尾课扩为 2 学时。

对于 `integrated_lessons`，每课必须为 `lesson_type=integrated`，且 `theory_hours > 0`、`practice_hours > 0`。`hybrid` 可按实际课程安排使用 `theory`、`practice` 和 `integrated` Lesson。每课都必须满足 `hours = theory_hours + practice_hours`；课程汇总必须分别等于已确认的理论、实践和总学时。不要为了均分而伪造每课构成；无法全部表示成 integrated Lesson 时使用 hybrid。

`split_lessons` 继续只用 theory Lesson 覆盖理论学时，实践另由 Practice Task/WorkOrder 承载。`practice_only` 保留 Content 2.2 的零 Lesson 行为。`practice_task_ids` 规则只改变于 Content 2.3：理论 Lesson 始终为空；`practice_work_orders=false` 时所有 Lesson 为空；请求工单时，integrated/practice Lesson 与实际承载的 Practice Task 双向链接。Split 课程继续使用单向 task→theory Lesson 链接。

## 64-hour integrated example

课程事实为 `total_hours=64`、`theory_hours=32`、`practice_hours=32`、`default_hours=2`、`mode=integrated_lessons` 时，Content 2.3 必须提供 32 个 Lesson，`sum(lesson.hours)=64`，理论构成合计 32，实践构成合计 32。

- `practice_work_orders=false`：32 个 Lesson DOCX，0 个 Practice Task/WorkOrder；32 学时实践仍留在 Lesson 内部账。
- `practice_work_orders=true`：仍为 32 个 Lesson DOCX，另有 16 个 2 学时 Practice Task，可由 WorkOrder Skill 生成 16 份配套工单。

Practice Task/WorkOrder 的实践学时属于这 64 学时，不得再次加到 Lesson coverage 或课程总时数。工单是 Lesson 实践环节的配套执行材料，不替代 Lesson。

## Shared 2.2 requirements

Content 2.3 保留 Content 2.2 的课程确认快照、reference/source-truth 规则、Agent authoring provenance、`pedagogical_review` 的 draft/revised/history/final digest、固定九阶段与时长规则，以及确定性 validator/Agent 教学判断边界。2.2 的 theory-only 和空 `practice_task_ids` 校验继续独立执行，不能用 2.3 规则重释历史输入。

Teaching Exemplar Benchmark 1.0、Review 1.0、Authorization 1.0 和 Acceptance 2.0 仍使用现有 sidecar/evidence 链，Authorization 记录输入实际的 `content_contract_version`。本版本不改变 Catalog、Split、Card、Selection、Review rubric、per-Lesson shards 或 trust boundary。
