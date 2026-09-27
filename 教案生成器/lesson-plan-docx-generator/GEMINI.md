# Gemini CLI 入口（Lesson Skill 2.3.1）

先读取 `SKILL.md`、`AGENTS.md` 与 `通用提示词.md`。新任务默认生成 Content Contract 2.3，Content 2.2 保持历史兼容。一次性确认并冻结课程事实，完成全课程 outline 后由 Agent 创作正文、来源证据和 pedagogical review。

课时覆盖按 mode：`theory_only`、`integrated_lessons`、`hybrid` 使用总学时；`split_lessons` 使用理论学时；`practice_only` 不生成 Lesson。64/32/32 integrated、每课 2 学时必须是 32 Lesson；无工单仍保留全部实践课时，有工单时另有 16 个配套任务/工单且不增加课程总时数。Split 与纯实践行为保持原边界。

Template 1.1.2、九阶段、时间合同、评价体系和 Benchmark sidecar 边界不变。仅用户明确需要工单时才通过 WorkOrder Skill Agent 生成 Practice Task/WorkOrder；不得由 Lesson Python 调用或伪造工单。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。
