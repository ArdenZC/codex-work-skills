# Practice WorkOrder Content 1.1

WorkOrder Content 1.1 是 WorkOrder Skill 的生产写入合同。它不是 Lesson 的第二份课程规划；在 linked 模式下，唯一上游事实是 Lesson 交付的 Practice Task Contract 1.1 和其中的 `source_task_snapshot`。

## 模式与来源

- `mode=linked`：必须有完整 `source_task_snapshot`，并逐字段继承课程基本信息、任务身份、课次集合、2 学时、情境、目标、输入、工具/材料、交付物、验收标准和安全约束。
- `mode=standalone`：必须显式选择 standalone，不能伪造 Lesson 来源快照；适合独立创作或验收样例。
- linked 模式一项 Practice Task 只产生一份 WorkOrder。学生任务项可以把上游步骤重新分组或展开，但不得改变目标、交付物、验收、工具/材料、安全约束或课程基本信息。

## 固定合同

Content 1.1 的根对象固定包含 `contract_version=1.1`、模式、课程基本信息、任务身份、`lesson_ids`、`granularity=per_task`、`practice_hours=2`、组信息、任务项和 Agent pedagogical review。课程基本信息必须与 Practice Task Contract 1.1 逐字段相等；任务标题只使用 `task_title`，不以项目名或内部 ID 冒充。

每份工单包含 1–5 个 `task_items`。每项由 Agent 提供可执行的标题、说明、步骤、工具/材料、交付物和验收标准；交付物使用 `{deliverable_id,text}`，验收使用 `{criterion_id,text,covers:[deliverable_id...]}`。学生可见正文不显示 `PT-*`、`WO-*`、`L-*` 等内部追踪 ID。

评分合同固定为课堂考勤 10 分、任务项合计 90 分、总分 100 分。学生“结果”栏保持空白，不能写答案、完整最终 SQL、最终模型、护理/会计最终结果或任何教师答案。统一 Agent review 负责专业准确性、目标—活动—证据、阶段连贯性、容量、递进和交付物验收映射；Python 只验证结构与硬事实，不用动作词、专业词、IT/护理 marker、字符或 n-gram 重叠判断教学质量。

## QA、渲染与事务

Content QA、Cross-Artifact QA 和 Output QA 通过后才生成 candidate。linked 模式默认必须真实 render；`--skip-render` 被拒绝，render 未执行或失败都不是 Production PASS。standalone 只有在明确 `--mode standalone` 且显式选择 `--render` 或 `--skip-render` 时才可运行，跳过渲染只能得到非生产结果。

整批候选在正式目录之外完成 QA、渲染和检查；任何一项失败都保持正式输出目录原有字节不变。`--replace` 是整批原子替换，不是逐文件放行。模板 `practice-task-workorder v1.0.0` 的二进制和 SHA-256 不变。

旧的 Practice Task Contract V1 / WorkOrder Content V1 只允许通过显式 legacy/兼容入口读取，不得混入 1.1 生产路径。
