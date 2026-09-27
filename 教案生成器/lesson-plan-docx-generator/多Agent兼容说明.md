# 教案生成器多 Agent 兼容说明

所有 agent 共用 `SKILL.md` 与 `通用提示词.md`，默认生成 Lesson Content Contract 2.2；2.1/2.0 仅作为显式兼容输入。正式任务先完成一次中文 intake 和整门课程 outline，确认结果冻结后再写逐课正文。

Lesson DOCX 只承载理论课时，课前固定 10 分钟、七个课中阶段严格为 `hours × 45` 分钟、课后固定 15 分钟；1 学时必须实质少于 2 学时。教材、resources 和 references 严格分离，references 只接受可阅读/引用的真实来源。

用户明确需要实践工单时，Lesson Agent 完成 Lesson QA/DOCX 后调用 WorkOrder Skill Agent，使用 Practice Task Contract 1.1 单向 handoff；明确不需要时不生成实践侧文件。WorkOrder 不可用时必须提示：`实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`，不得由 Lesson Python subprocess 调用 WorkOrder Python 或伪造工单 DOCX。

`schemas/shared/practice-task-contract.schema.json` 是跨 Skill 的唯一 Practice Task schema。确定性脚本只验证结构、硬事实、格式、模板、输出和渲染门禁；正文质量、阶段连贯性、相关性和容量由统一 Agent pedagogical review 负责。

Lesson Skill 2.3.0 的 Benchmark 也是独立 sidecar。Curator 保留 Catalog/Split 全量信息；Author/Reviewer 的每课运行上下文只包含该课所选 A/B Cards。每课 Review 单独存档，汇总文件记录 review hashes 与课程状态。完整验证后必须构建 Benchmark Authorization，正式 DOCX 生成使用 `--benchmark-mode required --benchmark-authorization <file>`。Round 2 固定 run、Holdout Pack 和 Selection，须通过 Content 2.2 语义修订及 pedagogical review/provenance 复验。Acceptance 应提供 A/B Packs、两类 Selection、课程 Review、逐课 Review 和 Round 2 所需 Round 1 快照。授权与 Benchmark 状态只表示输入来源和证据链完整，不是课程教学质量证明。
