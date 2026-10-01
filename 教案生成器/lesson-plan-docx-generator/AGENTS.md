# 教案生成器工作规则 2.3.1

这是 Lesson Skill 的轻量入口。开始前阅读同目录 `SKILL.md`、`通用提示词.md` 和当前输入对应的合同文档；字段与 QA 以 schema/脚本为准。新任务默认 Lesson Content Contract 2.3，Content 2.2 只按原历史合同兼容读取，不得静默改写。

- 先完成一次中文课程信息确认并冻结课程基本盘，再规划整门课程 outline，再由 Agent 创作逐课正文、pedagogical review 与 provenance。正文、阶段活动、评价和反思不由 Python 生成。
- Content 2.3 coverage：`theory_only`、`integrated_lessons`、`hybrid` 使用 `total_hours`；`split_lessons` 使用 `theory_hours`；`practice_only` 保持零 Lesson。所有课次数量按 coverage / `default_hours` 向上取整，尾课保留真实余数。
- `integrated_lessons` 只能使用 integrated Lesson；`hybrid` 可混合 theory/practice/integrated。逐课及课程理论/实践/总时数必须精确守恒，不得机械平均伪造构成。
- 64/32/32 integrated、默认每课 2 学时必须是 32 个 Lesson、覆盖 64 学时。工单 false 时仍生成 32 个 Lesson 和 0 个 Practice Task/WorkOrder；true 时仍为 32 个 Lesson，并提供 16 个 2 学时 Practice Task/WorkOrder。工单是 Lesson 实践环节材料，不增加课程总时数。
- Content 2.2 继续使用旧理论课边界：64/32/32 保持 16 个理论 Lesson。`split_lessons` 在 Content 2.3 也保留这一边界；`practice_only` 保持原有无 Lesson 行为。
- Content 2.3 的 `practice_task_ids`：工单关闭时所有 Lesson 为空；工单开启时 theory Lesson 为空，integrated/practice Lesson 与所承载任务双向链接。split 仍只允许 task→theory 的单向 handoff。
- Lesson Skill 2.3.1 的 Teaching Exemplar Benchmark 继续使用独立 sidecar 与现有 Catalog/Split/A-B/Review/Authorization 信任边界；Authorization 1.0 兼容 Content 2.2/2.3 并记录实际输入版本。不新增 Lesson benchmark 字段。
- Template 1.1.2、固定九阶段、评价体系和 Practice Task Contract 1.1 保持不变。教材、resources 与 references 分开；不得伪造来源。
- 生产生成必须通过 schema、内容、模板、输出、事务和所请求的真实 render 校验。未执行或失败的 render 不得标记 `production_pass`。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。

## Lifecycle candidate / practice_only 路由

LIF-01～05 已合并，当前仍是 Lesson Skill **2.3.1 candidate / pre-2.4 release state**，尚未发布 2.4 Stable。Canonical Lesson lifecycle 的完整生产路径为：

```text
Source Truth → Quality Eligibility / Benchmark Preparation → Content → Preproduction QA → Benchmark disposition / Review → Deterministic Teacher Review Packet → Human Teacher Review → Production Authorization → Canonical Generator → Artifact QA → Deterministic Visual Review Packet → Human Visual Review → Acceptance 3.0 → ACCEPTED
```

两处 Human Review 都必须由外部人工提供；synthetic evidence 只证明 contract closure，不代表真实教学质量通过。`production_pass` 是 generator 产物事务结果，不能替代 lifecycle `ACCEPTED`。

Content 2.3 的 `practice_only → lessons=[]` 继续合法。Canonical Lesson pipeline 的 PREVIEW/PRODUCTION 均只适用于至少 1 个真实 Lesson；`bind-content` 在绑定 Content 或推进 AUTHORING_COMPLETE 前明确拒绝 zero-Lesson，不能伪造 Lesson、Teacher Packet/Review 或 Lesson DOCX。Standalone Content tooling/direct generator 的历史行为保持兼容。需要纯实践材料时交给 Practice Task / WorkOrder Skill；Lesson Acceptance 3.0 不用于证明纯实践工单的教学验收，也不宣称 WorkOrder 已有等价生命周期。工单仍只在用户明确需要时创作。

完整边界与剩余发布事项见 `SKILL.md` 的 Lifecycle candidate / practice_only 路由；完整引擎包含对应的 pipeline、Acceptance 和 Release Closeout 文档。
