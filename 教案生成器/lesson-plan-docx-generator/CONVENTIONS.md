# Aider 约定（Lesson Skill 2.3.1）

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。默认输出 Content 2.3，Content 2.2 保持历史语义；按 delivery mode 确定 Lesson coverage：theory_only/integrated_lessons/hybrid 为 total_hours，split_lessons 为 theory_hours，practice_only 为零 Lesson。

理实一体 64/32/32、默认每课 2 学时必须生成 32 个 Lesson。Practice Task/WorkOrder 是已计入 64 小时的实践环节配套材料：false 时不生成工单但实践仍在 Lesson 内，true 时另生成 16 个 2 学时任务/工单，均不得二次累计。Hybrid 可混合 theory/practice/integrated Lesson 并精确守恒；split 与纯实践边界保持不变。

正文与教学判断来自 Agent。模板 1.1.2、九阶段、评价体系和 Benchmark 独立 sidecar 架构保持不变。只做确定性 schema、课时、来源、模板、输出、事务和 render 校验；未成功的真实 render 不得标记生产通过。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。

## Lifecycle candidate / practice_only 路由

LIF-01～05 已合并，当前仍是 Lesson Skill **2.3.1 candidate / pre-2.4 release state**，尚未发布 2.4 Stable。Canonical Lesson lifecycle 的完整生产路径为：

```text
Source Truth → Quality Eligibility / Benchmark Preparation → Content → Preproduction QA → Benchmark disposition / Review → Deterministic Teacher Review Packet → Human Teacher Review → Production Authorization → Canonical Generator → Artifact QA → Deterministic Visual Review Packet → Human Visual Review → Acceptance 3.0 → ACCEPTED
```

两处 Human Review 都必须由外部人工提供；synthetic evidence 只证明 contract closure，不代表真实教学质量通过。`production_pass` 是 generator 产物事务结果，不能替代 lifecycle `ACCEPTED`。

Content 2.3 的 `practice_only → lessons=[]` 继续合法。Canonical Lesson pipeline 的 PREVIEW/PRODUCTION 均只适用于至少 1 个真实 Lesson；`bind-content` 在绑定 Content 或推进 AUTHORING_COMPLETE 前明确拒绝 zero-Lesson，不能伪造 Lesson、Teacher Packet/Review 或 Lesson DOCX。Standalone Content tooling/direct generator 的历史行为保持兼容。需要纯实践材料时交给 Practice Task / WorkOrder Skill；Lesson Acceptance 3.0 不用于证明纯实践工单的教学验收，也不宣称 WorkOrder 已有等价生命周期。工单仍只在用户明确需要时创作。

完整边界与剩余发布事项见 `SKILL.md` 的 Lifecycle candidate / practice_only 路由；完整引擎包含对应的 pipeline、Acceptance 和 Release Closeout 文档。
