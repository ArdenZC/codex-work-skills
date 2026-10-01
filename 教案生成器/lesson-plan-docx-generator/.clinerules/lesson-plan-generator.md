# Cline 教案生成规则

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。当前 Lesson Skill 2.3.1 默认使用 Content Contract 2.3；Content 2.2 按历史规则兼容。确认并冻结课程基本盘，完成全课程 outline 后由 Agent 创作逐课正文、pedagogical review 与来源证据。

Lesson coverage：theory_only/integrated_lessons/hybrid 为 total_hours；split_lessons 为 theory_hours；practice_only 保持无 Lesson。理实一体 64/32/32、默认 2 学时生成 32 Lesson。工单 false 时实践依然计入 Lesson；true 时增加 16 个配套 Practice Task/WorkOrder，WorkOrder 不加算总时数。Hybrid 的 theory/practice/integrated 构成必须精确守恒。Content 2.2 历史语义保持不变。

Template 1.1.2、九阶段、评价体系和 Benchmark sidecar 架构不变。Author/Reviewer 只接收本课选定 Cards。Acceptance、输出 QA 和真实 render 按 `SKILL.md` 执行；Benchmark 不代表教学质量结论。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。

## Lifecycle candidate / practice_only 路由

LIF-01～05 已合并，当前仍是 Lesson Skill **2.3.1 candidate / pre-2.4 release state**，尚未发布 2.4 Stable。Canonical Lesson lifecycle 的完整生产路径为：

```text
Source Truth → Quality Eligibility / Benchmark Preparation → Content → Preproduction QA → Benchmark disposition / Review → Deterministic Teacher Review Packet → Human Teacher Review → Production Authorization → Canonical Generator → Artifact QA → Deterministic Visual Review Packet → Human Visual Review → Acceptance 3.0 → ACCEPTED
```

两处 Human Review 都必须由外部人工提供；synthetic evidence 只证明 contract closure，不代表真实教学质量通过。`production_pass` 是 generator 产物事务结果，不能替代 lifecycle `ACCEPTED`。

Content 2.3 的 `practice_only → lessons=[]` 继续合法。Canonical Lesson pipeline 的 PREVIEW/PRODUCTION 均只适用于至少 1 个真实 Lesson；`bind-content` 在绑定 Content 或推进 AUTHORING_COMPLETE 前明确拒绝 zero-Lesson，不能伪造 Lesson、Teacher Packet/Review 或 Lesson DOCX。Standalone Content tooling/direct generator 的历史行为保持兼容。需要纯实践材料时交给 Practice Task / WorkOrder Skill；Lesson Acceptance 3.0 不用于证明纯实践工单的教学验收，也不宣称 WorkOrder 已有等价生命周期。工单仍只在用户明确需要时创作。

完整边界与剩余发布事项见 `SKILL.md` 的 Lifecycle candidate / practice_only 路由；完整引擎包含对应的 pipeline、Acceptance 和 Release Closeout 文档。
