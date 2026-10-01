# GitHub Copilot 教案规则

开始前阅读 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。Lesson Skill 2.3.1 默认使用 Content Contract 2.3；Content 2.2 继续按历史合同兼容。先确认并冻结课程基本盘，完成全课程 outline，再由 Agent 创作逐课正文和 pedagogical review。Python 只做 schema、硬事实、格式、模板、事务和渲染门禁。

Content 2.3 中，theory_only、integrated_lessons、hybrid 的 Lesson 覆盖 total_hours；split_lessons 仅覆盖 theory_hours；practice_only 保持无 Lesson。64/32/32 integrated、每课 2 学时必须生成 32 Lesson。工单 false 仍保留完整 Lesson 内实践，true 时另外提供 16 个 2 学时 Practice Task/WorkOrder；它们不重复计入总学时。Hybrid 可混合 theory/practice/integrated Lesson，但逐课和课程理论/实践/总账必须精确守恒。

Content 2.2 历史语义、Template 1.1.2、九阶段、评价体系和 Benchmark sidecar 架构不变。只有用户明确需要工单才由 Lesson Agent 调用 WorkOrder Skill Agent；Lesson Python 不调用 WorkOrder Python、不伪造工单。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。

## Lifecycle candidate / practice_only 路由

LIF-01～05 已合并，当前仍是 Lesson Skill **2.3.1 candidate / pre-2.4 release state**，尚未发布 2.4 Stable。Canonical Lesson lifecycle 的完整生产路径为：

```text
Source Truth → Quality Eligibility / Benchmark Preparation → Content → Preproduction QA → Benchmark disposition / Review → Deterministic Teacher Review Packet → Human Teacher Review → Production Authorization → Canonical Generator → Artifact QA → Deterministic Visual Review Packet → Human Visual Review → Acceptance 3.0 → ACCEPTED
```

两处 Human Review 都必须由外部人工提供；synthetic evidence 只证明 contract closure，不代表真实教学质量通过。`production_pass` 是 generator 产物事务结果，不能替代 lifecycle `ACCEPTED`。

Content 2.3 的 `practice_only → lessons=[]` 继续合法。Canonical Lesson pipeline 的 PREVIEW/PRODUCTION 均只适用于至少 1 个真实 Lesson；`bind-content` 在绑定 Content 或推进 AUTHORING_COMPLETE 前明确拒绝 zero-Lesson，不能伪造 Lesson、Teacher Packet/Review 或 Lesson DOCX。Standalone Content tooling/direct generator 的历史行为保持兼容。需要纯实践材料时交给 Practice Task / WorkOrder Skill；Lesson Acceptance 3.0 不用于证明纯实践工单的教学验收，也不宣称 WorkOrder 已有等价生命周期。工单仍只在用户明确需要时创作。

完整边界与剩余发布事项见 `SKILL.md` 的 Lifecycle candidate / practice_only 路由；完整引擎包含对应的 pipeline、Acceptance 和 Release Closeout 文档。
