# GitHub Copilot 教案规则

开始前阅读 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。Lesson Skill 2.3.1 默认使用 Content Contract 2.3；Content 2.2 继续按历史合同兼容。先确认并冻结课程基本盘，完成全课程 outline，再由 Agent 创作逐课正文和 pedagogical review。Python 只做 schema、硬事实、格式、模板、事务和渲染门禁。

Content 2.3 中，theory_only、integrated_lessons、hybrid 的 Lesson 覆盖 total_hours；split_lessons 仅覆盖 theory_hours；practice_only 保持无 Lesson。64/32/32 integrated、每课 2 学时必须生成 32 Lesson。工单 false 仍保留完整 Lesson 内实践，true 时另外提供 16 个 2 学时 Practice Task/WorkOrder；它们不重复计入总学时。Hybrid 可混合 theory/practice/integrated Lesson，但逐课和课程理论/实践/总账必须精确守恒。

Content 2.2 历史语义、Template 1.1.2、九阶段、评价体系和 Benchmark sidecar 架构不变。只有用户明确需要工单才由 Lesson Agent 调用 WorkOrder Skill Agent；Lesson Python 不调用 WorkOrder Python、不伪造工单。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。
