# Claude Code 入口（Lesson Skill 2.3.1）

开始前读取 `SKILL.md`、`AGENTS.md` 与 `通用提示词.md`。默认生成 Content Contract 2.3，既有 2.2 JSON 按历史规则兼容。先一次性确认并冻结课程事实，再完成全课程 outline 和逐课 Agent 内容审阅。

2.3 的 `theory_only`、`integrated_lessons`、`hybrid` Lesson 覆盖总学时；`split_lessons` 仍只覆盖理论学时；`practice_only` 保持无 Lesson。Integrated/hybrid 精确分账理论、实践与总学时。64/32/32 integrated、默认每课 2 学时生成 32 Lesson；不需要工单仍生成 32 Lesson，需要工单时另外配套 16 个 2 学时 Practice Task/WorkOrder，工单不增加课程总时数。Content 2.2 历史语义保持不变。

每课执行既有九阶段与 10 / `hours × 45` / 15 分钟合同。教材、resources、references 分开，references 保留真实出处。Benchmark 保持独立 sidecar 和现有 Authorization 链；本版本仅支持 Content 2.2/2.3 并记录实际版本。工单由 WorkOrder Skill Agent 创作，不由 Lesson Python 跨调用或伪造。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。
