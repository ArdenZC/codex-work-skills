---
description: 生成项目化中文教案 DOCX 的统一入口
alwaysApply: true
---

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。当前规范为 Lesson Skill 2.3.0、Content Contract 2.2 与 Template 1.1.2；完成一次课程 Intake、冻结课程基本盘和全课程 outline，再由 Agent 创作正文并运行现有 QA/事务流程。

Lesson 2.3 Benchmark 只使用独立 sidecar。Curator 独占 Catalog/Split；Author 和 Reviewer 每次只接收本课所选 Cards。完整校验 A/B Packs、Selections、逐课 Review shards 和课程汇总后生成 Authorization。正式 DOCX 必须使用 `--benchmark-mode required --benchmark-authorization <file>`。Round 2 固定 run/B 输入，要求语义内容修订、更新 Content 2.2 pedagogical review history/provenance 并复验 Round 1 全部快照。Acceptance 链接 A/B 两侧及所有 Review 文件。教学语义仍由 Agent 负责，脚本不产出正文或质量分。
