---
trigger: always_on
---

先读取 `SKILL.md`、`AGENTS.md` 与 `通用提示词.md`。当前默认 Lesson Skill 2.3.1 / Content 2.3，Content 2.2 保持历史兼容。先完成一次课程事实确认、冻结基本盘和全课程 outline，再由 Agent 创作逐课正文与 review。

Content 2.3 的 Lesson coverage 按 mode 确定：theory_only/integrated_lessons/hybrid 使用总学时；split_lessons 使用理论学时；practice_only 保持无 Lesson。64/32/32 integrated、每课 2 学时必须覆盖为 32 Lesson。工单 false 不得删除 Lesson 内实践；true 时配套 16 个 2 学时 Practice Task/WorkOrder，工单不额外增加总时数。Hybrid 支持 theory/practice/integrated 混排且逐课与总账精确守恒。

Content 2.2 历史语义、Template 1.1.2、九阶段、评价与 Benchmark sidecar 架构不变。所有教学内容与判断由 Agent 提供；脚本不写正文、不判质量。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。
