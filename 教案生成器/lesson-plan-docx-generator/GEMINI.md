# Gemini CLI 入口（Lesson Skill 2.3.1）

先读取 `SKILL.md`、`AGENTS.md` 与 `通用提示词.md`。新任务默认生成 Content Contract 2.4，Content 2.2/2.3 保持原历史语义。一次性确认并冻结课程事实及项目化全课程 outline 后，按项目委派专属 Agent；不支持子 Agent 时按项目顺序执行并记录 fallback。每项目写前联网检索和阅读可迁移教案设计，写后逐课按现有 15 维标准对照；主 Agent 统一核算、复核、合并和生成。

Content 2.4 所有 mode 都覆盖总学时；`separate_full_lessons` 分开生成 theory/practice Lesson，`practice_only` 也生成实践 Lesson。只有 Content 2.2/2.3 历史 `split_lessons` 仅覆盖理论课时、历史 `practice_only` 为零 Lesson。64/32/32 integrated、每课 2 学时必须是 32 Lesson；无工单仍保留全部实践课时，有工单时另有配套任务/工单且不增加课程总时数。完整 2.4 工作流和 sidecar 门禁见 `docs/content-contract-v2.4.md`。

Template 1.1.2、九阶段、时间合同、评价体系和 Benchmark sidecar 边界不变。仅用户明确需要工单时才通过 WorkOrder Skill Agent 生成 Practice Task/WorkOrder；不得由 Lesson Python 调用或伪造工单。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。

## Lifecycle candidate / practice_only 路由

LIF-01～05 已合并，当前仍是 Lesson Skill **2.3.1 candidate / pre-2.4 release state**，尚未发布 2.4 Stable。Canonical Lesson lifecycle 的完整生产路径为：

```text
Source Truth → Quality Eligibility / Benchmark Preparation → Content → Preproduction QA → Benchmark disposition / Review → Deterministic Teacher Review Packet → Human Teacher Review → Production Authorization → Canonical Generator → Artifact QA → Deterministic Visual Review Packet → Human Visual Review → Acceptance 3.0 → ACCEPTED
```

两处 Human Review 都必须由外部人工提供；synthetic evidence 只证明 contract closure，不代表真实教学质量通过。`production_pass` 是 generator 产物事务结果，不能替代 lifecycle `ACCEPTED`。

Content 2.3 的 `practice_only → lessons=[]` 继续合法。Canonical Lesson pipeline 的 PREVIEW/PRODUCTION 均只适用于至少 1 个真实 Lesson；`bind-content` 在绑定 Content 或推进 AUTHORING_COMPLETE 前明确拒绝 zero-Lesson，不能伪造 Lesson、Teacher Packet/Review 或 Lesson DOCX。Standalone Content tooling/direct generator 的历史行为保持兼容。需要纯实践材料时交给 Practice Task / WorkOrder Skill；Lesson Acceptance 3.0 不用于证明纯实践工单的教学验收，也不宣称 WorkOrder 已有等价生命周期。工单仍只在用户明确需要时创作。

完整边界与剩余发布事项见 `SKILL.md` 的 Lifecycle candidate / practice_only 路由；完整引擎包含对应的 pipeline、Acceptance 和 Release Closeout 文档。
