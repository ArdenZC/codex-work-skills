# 教案生成器工作规则 2.3.1

这是 Lesson Skill 的轻量入口。开始前阅读同目录 `SKILL.md`、`通用提示词.md` 和当前输入对应的合同文档；字段与 QA 以 schema/脚本为准。新任务默认 Lesson Content Contract 2.4；Content 2.2/2.3 只按原历史合同兼容读取，不得静默改写。

- 先完成一次中文课程信息确认并冻结课程基本盘，再规划整门课程 outline，再由 Agent 创作逐课正文、pedagogical review 与 provenance。正文、阶段活动、评价和反思不由 Python 生成。
- Content 2.4 新课全覆盖：纯理论、理实分开、纯实践都按 `total_hours/default_hours` 向上取整并生成全部 Lesson；`separate_full_lessons` 表示分开的理论课/实践课，`practice_only` 也必须生成实践 Lesson。仅 2.2/2.3 保留旧 split/practice-only 语义。
- `integrated_lessons` 只能使用 integrated Lesson；`hybrid` 可混合 theory/practice/integrated。逐课及课程理论/实践/总时数必须精确守恒，不得机械平均伪造构成。
- 64/32/32 integrated、默认每课 2 学时必须是 32 个 Lesson、覆盖 64 学时。工单 false 时仍生成 32 个 Lesson 和 0 个 Practice Task/WorkOrder；true 时仍为 32 个 Lesson，并提供 16 个 2 学时 Practice Task/WorkOrder。工单是 Lesson 实践环节材料，不增加课程总时数。
- 40 学时/默认每课 2 学时：纯理论 20 份；20+20 理实分开 10 理论+10实践，共 20 份；纯实践 20 份实践教案。Content 2.2 与 2.3 不变：例如 split 仍只在旧版本中覆盖理论。
- Content 2.3 的 `practice_task_ids`：工单关闭时所有 Lesson 为空；工单开启时 theory Lesson 为空，integrated/practice Lesson 与所承载任务双向链接。split 仍只允许 task→theory 的单向 handoff。
- Lesson Skill 2.3.1 的正式 Teaching Exemplar Benchmark 继续使用独立 sidecar 与现有 Catalog/Split/A-B/Review/Authorization 信任边界；Authorization 1.0 兼容 Content 2.2/2.3 并记录实际输入版本。不新增 Lesson benchmark 字段。
- Template 1.1.2、固定九阶段、评价体系和 Practice Task Contract 1.1 保持不变。教材、resources 与 references 分开；不得伪造来源。
- 生产生成必须通过 schema、内容、模板、输出、事务和所请求的真实 render 校验。未执行或失败的 render 不得标记 `production_pass`。
Agent 只创作 Lesson Content JSON、Practice Task handoff data、Benchmark sidecars/evidence 与 pedagogical review。最终 Lesson DOCX 只允许由 canonical generate_lesson_plans.py 基于 Template 1.1.2 生成并通过 Output QA、所需 retained render、artifact manifest verification 与 Acceptance；任一 generator/template validation/Output QA/manifest verification 失败即 BLOCKED，禁止手工创建、修改、修补或绕过。完整禁令见 SKILL.md「最终 Lesson DOCX 的不可绕过生产边界」。

## Content 2.4 执行门禁

- 每课先检索并记录可读的相关公开优秀/示范教案；写完初稿后每课按原有 15 维 rubric 对照。状态、来源、阅读范围、真实性及逐课差距均写入 generation evidence；不是推荐项。
- Content 2.4 必须提供可校验的 `generation-evidence.json` 并调用 `generate_lesson_plans.py --generation-evidence ...`；未执行搜索、未有逐课对照、缺项目委派或汇总冲突均 fail closed。
- 主 Agent 冻结 outline 后按项目派发，一项目一名专属子 Agent；无子 Agent 时依项目工作包顺序由主 Agent 执行并记录 fallback。主 Agent 独占总表合并、Word/PDF 和课程级 QA。
- 全面合同见 [`docs/content-contract-v2.4.md`](docs/content-contract-v2.4.md)。Content 2.2/2.3 是历史语义，不被 2.4 重解释。

## Lifecycle candidate / practice_only 路由

LIF-01～05 已合并，当前仍是 Lesson Skill **2.3.1 candidate / pre-2.4 release state**，尚未发布 2.4 Stable。Canonical Lesson lifecycle 的完整生产路径为：

```text
Source Truth → Quality Eligibility / Benchmark Preparation → Content → Preproduction QA → Benchmark disposition / Review → Deterministic Teacher Review Packet → Human Teacher Review → Production Authorization → Canonical Generator → Artifact QA → Deterministic Visual Review Packet → Human Visual Review → Acceptance 3.0 → ACCEPTED
```

两处 Human Review 都必须由外部人工提供；synthetic evidence 只证明 contract closure，不代表真实教学质量通过。`production_pass` 是 generator 产物事务结果，不能替代 lifecycle `ACCEPTED`。

Content 2.3 的 `practice_only → lessons=[]` 继续合法。Canonical Lesson pipeline 的 PREVIEW/PRODUCTION 均只适用于至少 1 个真实 Lesson；`bind-content` 在绑定 Content 或推进 AUTHORING_COMPLETE 前明确拒绝 zero-Lesson，不能伪造 Lesson、Teacher Packet/Review 或 Lesson DOCX。Standalone Content tooling/direct generator 的历史行为保持兼容。需要纯实践材料时交给 Practice Task / WorkOrder Skill；Lesson Acceptance 3.0 不用于证明纯实践工单的教学验收，也不宣称 WorkOrder 已有等价生命周期。工单仍只在用户明确需要时创作。

完整边界与剩余发布事项见 `SKILL.md` 的 Lifecycle candidate / practice_only 路由；完整引擎包含对应的 pipeline、Acceptance 和 Release Closeout 文档。

## RQ-03O2 opt-in lifecycle

显式 Orchestrator/Pipeline 2.0 运行要求独立 Semantic Scope Review 1.0、完整来源/配置/资格/受保护操作证据、Teacher Packet/Review 2.0 和 PA 2.0。歧义必须逐项由独立教师批准操作解决，确定性修订不得 waiver。外部 operator TrustContext 未配置时生产失败关闭；历史 1.0 和 standalone 行为保持 legacy，不授予 O2 权限。安装、更改正文/来源/outline 或权限策略后必须按合同重新运行与审查。本段仅说明仍处于 2.3.1 candidate 的显式 O2 lifecycle 边界；普通新课使用本分支 Content 2.4，不代表已获得 O2 Production Authorization。

版本分派、控制器配置和门禁见 [Semantic lifecycle 2.0](docs/semantic-scope-lifecycle-v2.md).
