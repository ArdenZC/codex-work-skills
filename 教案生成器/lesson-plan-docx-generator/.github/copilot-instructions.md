# GitHub Copilot 教案规则

开始前阅读 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。当前为 Lesson Skill 2.3.0 / Content Contract 2.2；先做一次课程 Intake、冻结课程基本盘并完成全课程 outline。正文与教学判断由 Agent 负责，Python 只执行 schema、硬事实、格式、模板、事务和渲染门禁。课程资料、教材、resources 与 references 分开管理，不补造来源信息。

Teaching Exemplar Benchmark 使用 Content 2.2 以外的 sidecar。Curator 管理完整 Catalog/Split；Author/Reviewer 仅取得当前 Lesson 已选的 A/B Cards。完整验证 A/B Packs、Selections、逐课 Review shards 和课程汇总后，创建 Benchmark Authorization；正式生成 DOCX 时必须使用 `generate_lesson_plans.py --benchmark-mode required --benchmark-authorization <file>`。Round 2 固定 run、Holdout Pack 和 Selection，必须有 Agent-owned 语义内容修订并刷新 Content 2.2 `pedagogical_review` history/provenance。Acceptance 要校验 A/B 两侧和每课 Review。Benchmark 不是教学质量结论。

只有用户明确要求实践工单时才创建 Practice Task Contract 1.1/handoff，并由 Lesson Agent 调用 WorkOrder Skill Agent；Lesson Python 不可跨调用 WorkOrder Python，也不可伪造工单 DOCX。WorkOrder Skill 不可用时，交付 handoff 并使用 `SKILL.md` 规定的中文提示。
