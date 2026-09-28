# Cline 教案生成规则

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。当前 Lesson Skill 2.3.1 默认使用 Content Contract 2.3；Content 2.2 按历史规则兼容。确认并冻结课程基本盘，完成全课程 outline 后由 Agent 创作逐课正文、pedagogical review 与来源证据。

Lesson coverage：theory_only/integrated_lessons/hybrid 为 total_hours；split_lessons 为 theory_hours；practice_only 保持无 Lesson。理实一体 64/32/32、默认 2 学时生成 32 Lesson。工单 false 时实践依然计入 Lesson；true 时增加 16 个配套 Practice Task/WorkOrder，WorkOrder 不加算总时数。Hybrid 的 theory/practice/integrated 构成必须精确守恒。Content 2.2 历史语义保持不变。

Template 1.1.2、九阶段、评价体系和 Benchmark sidecar 架构不变。Author/Reviewer 只接收本课选定 Cards。Acceptance、输出 QA 和真实 render 按 `SKILL.md` 执行；Benchmark 不代表教学质量结论。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。
