# WorkOrder 适配器

生成前只需读取 `SKILL.md`。关联工单消费 Lesson 的 Practice Task Contract 1.1，并要求 Agent 提供完整 WorkOrder Content 1.1 和 pedagogical review；handoff-only 不得生成正式 Content 或 DOCX。

关联模式保留 exact source-task snapshot，执行 Cross-Artifact QA 和真实渲染；standalone/debug 只有显式跳过渲染才可使用。固定考勤 10 分、任务 90 分、总分 100 分，学生结果区保持空白，学生可见区域隐藏内部 ID，不生成答案。
