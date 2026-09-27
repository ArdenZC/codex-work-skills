---
description: 生成项目化中文教案 DOCX 的统一入口
alwaysApply: true
---

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。Lesson Skill 2.3.1 默认 Content 2.3，Content 2.2 保持历史行为。确认课程事实、冻结课程基本盘并完成全课程 outline，再由 Agent 创作正文和 review。

Content 2.3 中，theory_only/integrated_lessons/hybrid 的 Lesson 覆盖 total_hours；split_lessons 仅覆盖 theory_hours；practice_only 维持零 Lesson。64/32/32 integrated 且默认每课 2 学时生成 32 Lesson。工单关闭仍保留所有实践课时；工单开启可另有 16 个 2 学时实践任务/工单，工单不增加总学时。Hybrid 的 Lesson 类型可混合但理论/实践/总账必须精确相等。

Content 2.2 兼容语义、Template 1.1.2、九阶段、评价体系和 Benchmark sidecar trust boundary 均保持不变。教学语义由 Agent 判断；Python 只做确定性校验和输出。
