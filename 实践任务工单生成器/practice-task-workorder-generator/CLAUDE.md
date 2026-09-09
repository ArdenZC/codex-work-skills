# WorkOrder 适配器

生成前读取同目录 `SKILL.md`。它是实践任务工单的唯一人类合同。

关联模式使用 Lesson 的 Practice Task Contract 1.1 和 Agent 创作的 WorkOrder Content 1.1；保留完整来源任务快照，完成 Cross-Artifact QA，并以 `practice-work-order v1.0.0` 真实渲染通过后交付。handoff-only 只能生成创作骨架，不能伪造 Content 或 DOCX。

独立调试必须明确选择 standalone；只有显式跳过渲染才可报告 `render.status=skipped`，不构成生产通过。固定考勤 10 分、任务 90 分、总分 100 分，学生结果区保持空白，不生成教师答案。学生可见区域隐藏内部任务、项目和课次 ID。
