# 教案生成器多 Agent 兼容说明

所有 Agent 共用 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。Lesson Skill 2.3.1 默认输出 Content Contract 2.3；Content 2.2 保持历史语义并可直接兼容读取。正式规划先做一次中文 intake、冻结课程事实并完成全课程 outline，再由 Agent 写逐课正文与 pedagogical review。

Content 2.3 的 Lesson coverage 取决于 delivery mode：`theory_only`、`integrated_lessons`、`hybrid` 覆盖 `total_hours`；`split_lessons` 覆盖 `theory_hours`；`practice_only` 保持零 Lesson。Integrated Lesson 必须有正理论和实践构成；hybrid 可混合 theory/practice/integrated Lesson；课程理论、实践、总学时逐项守恒。64/32/32 integrated 且默认每课 2 学时对应 32 个 Lesson、64 小时覆盖。工单 false 时仍生成 32 Lesson、0 工单；true 时另有 16 个配套实践任务/工单，这些实践学时不再次累计。Content 2.2 仍按理论 Lesson 规则，split 与 practice_only 语义不变。

用户明确要求 Practice Task/WorkOrder 时，Lesson Agent 完成 handoff 后调用 WorkOrder Skill Agent。Content 2.3 的 integrated/practice Lesson 与实践任务双向链接，theory Lesson 的 `practice_task_ids` 为空；工单关闭时所有 Lesson 链接为空。Split 保留 task→theory Lesson 单向链接。不得由 Lesson Python 调用 WorkOrder Python 或伪造 DOCX。

`schemas/shared/practice-task-contract.schema.json` 是跨 Skill 的唯一 Practice Task schema。Template 1.1.2、九阶段、评价体系不变。来源真实可核验；Content 2.3 保留 Content 2.2 的 reference/source-truth 和 Agent review/provenance 规则。

Teaching Exemplar Benchmark 继续独立 sidecar：Curator 管理 Catalog/Split，Author/Reviewer 每课只看所选 Cards，保持 A/B Packs、Selections、逐课 Review shards、课程汇总和 Authorization 的现有边界。Authorization 1.0 同时支持 Content 2.2/2.3，并记录实际输入版本；不改变 benchmark 架构或向 Lesson JSON 加字段。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。

## Lifecycle candidate / practice_only 路由

LIF-01～05 已合并，当前仍是 Lesson Skill **2.3.1 candidate / pre-2.4 release state**，尚未发布 2.4 Stable。Canonical Lesson lifecycle 的完整生产路径为：

```text
Source Truth → Quality Eligibility / Benchmark Preparation → Content → Preproduction QA → Benchmark disposition / Review → Deterministic Teacher Review Packet → Human Teacher Review → Production Authorization → Canonical Generator → Artifact QA → Deterministic Visual Review Packet → Human Visual Review → Acceptance 3.0 → ACCEPTED
```

两处 Human Review 都必须由外部人工提供；synthetic evidence 只证明 contract closure，不代表真实教学质量通过。`production_pass` 是 generator 产物事务结果，不能替代 lifecycle `ACCEPTED`。

Content 2.3 的 `practice_only → lessons=[]` 继续合法。Canonical Lesson pipeline 的 PREVIEW/PRODUCTION 均只适用于至少 1 个真实 Lesson；`bind-content` 在绑定 Content 或推进 AUTHORING_COMPLETE 前明确拒绝 zero-Lesson，不能伪造 Lesson、Teacher Packet/Review 或 Lesson DOCX。Standalone Content tooling/direct generator 的历史行为保持兼容。需要纯实践材料时交给 Practice Task / WorkOrder Skill；Lesson Acceptance 3.0 不用于证明纯实践工单的教学验收，也不宣称 WorkOrder 已有等价生命周期。工单仍只在用户明确需要时创作。

完整边界与剩余发布事项见 `SKILL.md` 的 Lifecycle candidate / practice_only 路由；完整引擎包含对应的 pipeline、Acceptance 和 Release Closeout 文档。
