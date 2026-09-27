# Cline 教案生成规则

先读取同目录 `SKILL.md` 和 `通用提示词.md`，它们是唯一行为规范。使用 Content Contract V2，先做课程级项目/任务 outline，再生成完整 JSON，运行 Content QA、模板/输出 QA 和可用的 Windows/macOS render QA。正文、9 个实施阶段、逐课评价 remarks 和反思必须来自 JSON；不得使用 sparse input、旧套话、默认 IT 内容或静默截断。

Lesson 2.3 Teaching Exemplar Benchmark 使用独立 sidecar。Curator 保管 Catalog/Split；Author 和 Reviewer 每课只接收所选 Cards。完整校验 A/B Packs、A/B Selections、逐课 Review shards 和课程汇总后构建 Authorization。正式 DOCX 使用 `--benchmark-mode required --benchmark-authorization <file>`。Round 2 必须修订 Agent-owned 教学内容、更新 Content 2.2 pedagogical review history/provenance，并复验完整 Round 1 快照。Acceptance 校验 A/B 两侧与所有 Review；Benchmark 不代替教学质量人工判断。
