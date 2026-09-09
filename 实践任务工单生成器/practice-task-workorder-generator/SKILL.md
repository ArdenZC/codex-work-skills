# 实践任务工单生成器 Skill 2.2.0

这是 Lesson 的实践任务下游 Skill，当前收口范围为 Phase 2.2。它把 Agent 创作的 WorkOrder Content 1.1 写入受保护的 `practice-work-order v1.0.0` 模板；模板二进制、版式和模板版本不变。本 Skill 不进入 Phase 3，不生成教师答案，不联动成绩册。

本文件是工单行为的唯一人类合同。机器字段约束以 `schemas/work-order-content.schema.json` 和仓库根目录的 `schemas/shared/practice-task-contract.schema.json` 为准；Python 只实现这些确定性约束、模板映射、输出检查、渲染门禁和事务，不复制或替代本文件的教学判断。

## 输入与模式

Practice Task Contract 1.1 是关联模式的唯一上游事实源。它必须包含已确认的课程基本盘：课程名称、专业、授课对象、总课时、理论课时、实践课时、组织方式和默认单课学时；每个 Practice Task 固定 2 学时，任务数等于实践学时除以 2。

WorkOrder Content 1.1 必须由 Agent 独立创作，至少包含：

- `content_contract_version=1.1`、`mode`、课程基本盘、`task_id`、`project_id`、`task_title`、`lesson_ids`、`practice_hours=2`、小组占位信息和任务项；
- 每个任务项的标题、描述、工具/材料、步骤、交付物、验收标准和 Agent `pedagogical_review`；
- 关联模式的 `source_task_snapshot`。它必须逐字段保存上游任务的 ID、项目、标题、课次、学时、场景、目标、输入、步骤、交付物、验收标准、工具/材料和安全/合规要求。

模式边界必须保持清楚：

- `mode=linked`：同时提供 Practice Task Contract 1.1 和完整 WorkOrder Content 1.1；生成前必须通过课程基本盘相等、任务身份、课次、2 学时和 exact snapshot 的 Cross-Artifact QA。只有 handoff 时只能输出 Agent 创作骨架，不能生成正式 Content 或 DOCX。
- `mode=standalone`：只允许在命令行明确传入 `--mode standalone`，且不能声称已完成上游 handoff；`source_task_snapshot` 不得出现。`--skip-render` 只能用于明确的 standalone/debug 输出，报告中的 `render.status=skipped`，不构成 Production PASS。
- `mode=linked` 默认执行真实 DOCX 渲染。必须得到 `render.status=pass` 才能报告生产成功；没有 LibreOffice 时 fail-closed，并明确渲染未验证。`--skip-render` 不得绕过关联模式的生产门禁。

旧的 Practice Task/WorkOrder V1 只可通过显式 `--legacy` 或迁移适配器读取。默认路径只接受 1.1，不得把兼容字段当作新的合同。

## Agent 创作与质量判断

Agent 在写入前必须先完成整份工单的 pedagogical review；发现问题先重写 Content，再交给 Python。Review 至少说明：专业准确性、普通学生九十分钟内完成的可行性、上游目标到活动和证据的连贯性、工具准备与先决知识、交付物专业性、每个交付物到验收标准的映射、没有教师答案泄露，以及安全/合规边界。`status=approved` 且 `capacity=fit` 才能生成。

一个 Practice Task 只生成一个 WorkOrder。任务项可以按教学流程组织或扩展，但不得改写来源任务的目标、场景、输入、步骤和约束。WorkOrder 应让普通学生在约 90 分钟内完成核心产出；若负荷过大，应由 Agent 合并、缩小、调整顺序或标记可选扩展，而不是由 Python 估算或追加说明。

每个 WorkOrder 的评分固定为课堂考勤 10 分、任务项合计 90 分、总分 100 分。具体任务项分值由 Agent 按工作量和产出重要性决定，不机械均分；Python 只校验总和。每个实质性交付物使用 `D1` 等内部 ID，每条验收标准使用 `C1` 等内部 ID，并在 `covers` 中明确覆盖至少一个交付物。学生文档不显示这些内部 ID。

学生的“任务结果”栏必须保持空白。不要把标准答案、完整代码、最终模型、临床结论、会计结论或其他教师答案写入正文或结果栏。固定学生/教师评价表沿用模板，不创建第二套评分体系，也不参与跨工单重复判断。

Python 不用字符 n-gram、模糊相似度、动作词库、专业词库或 IT/护理标记来判断自然度、相关性、案例质量、教学价值或九十分钟负荷。Python 只做 schema、ID/小时/分值/空值、精确重复、交付物 ID 映射、来源快照、课程信息和模板/输出/渲染等硬门禁；语义问题由 Agent review 负责。

## 资料与标题

WorkOrder 不维护第二套参考文献系统。课程资料、Practice Task 的输入和工具来自上游或 Agent 已确认内容；不能为了降低重复率虚构任务、工具、教材、作者、出版社、ISBN、标准编号或公开文献。关联标题必须使用上游 `title` 原样写入 `task_title`，Word 主标题也只使用 `task_title`；`project_name` 只属于显式 legacy 迁移输入，不是 WorkOrder Content 1.1 字段，也不能替代任务标题。

JSON、QA 报告、文件名和内部日志可以保留 `task_id`、`project_id`、`lesson_ids` 作为追溯信息；学生可见的 metadata、标题、正文和 Office core properties 默认隐藏这些内部 ID。模板中只有明确的业务编号占位才可显示。

## 生成、验证与交付

正式顺序是：读取 canonical 合同 → Agent 完成 Content 1.1 和 review → Content QA →（关联模式）Cross-Artifact QA → candidate DOCX → Output QA →（关联模式默认）真实 Render Smoke → 全部通过后批量原子发布。任一 candidate、QA 或渲染失败，都不得发布部分工单；不得修改上游 Lesson 或模板 binary。

输出 QA 至少确认三张顶层表、固定表头、考勤 10 分、任务项 90 分、总分 100 分、动态任务行、学生结果空白、固定评价表、任务标题和课程信息。Render Smoke 只证明文件能被分页渲染，不等于人工视觉检查；人工检查仍需由调用 Agent 另行记录。

标准入口：

```text
实践任务 handoff：--practice-task-json … --authoring-skeleton-output …
关联生成：--content-json … --practice-task-json … --mode linked --render
独立调试：--content-json … --mode standalone --skip-render
```

默认使用模板路径 `assets/templates/practice-work-order/v1.0.0/template.docx`。安装器只复制完整 Skill 和 canonical shared schema，不自动安装 Python 依赖；成功替换默认清理临时 backup，只有显式 `--keep-backup` 才保留。安装后可用源树的 `scripts/install.py --doctor --json --skills-dir <目录>` 比对 `source_fingerprint`、`installed_fingerprint` 和 `status=current`。适配器只能读取本文件和通用 Agent 方法提示，不得另写一套业务规则。
