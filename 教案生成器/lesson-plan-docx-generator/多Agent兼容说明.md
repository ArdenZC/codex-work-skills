# 教案生成器多 Agent 兼容说明

所有 agent 共用 `SKILL.md` 与 `通用提示词.md`，默认生成 Lesson Content Contract 2.2；2.1/2.0 仅作为显式兼容输入。正式任务先完成一次中文 intake 和整门课程 outline，确认结果冻结后再写逐课正文。

Lesson DOCX 只承载理论课时，课前固定 10 分钟、七个课中阶段严格为 `hours × 45` 分钟、课后固定 15 分钟；1 学时必须实质少于 2 学时。教材、resources 和 references 严格分离，references 只接受可阅读/引用的真实来源。

用户明确需要实践工单时，Lesson Agent 完成 Lesson QA/DOCX 后调用 WorkOrder Skill Agent，使用 Practice Task Contract 1.1 单向 handoff；明确不需要时不生成实践侧文件。WorkOrder 不可用时必须提示：`实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`，不得由 Lesson Python subprocess 调用 WorkOrder Python 或伪造工单 DOCX。

`schemas/shared/practice-task-contract.schema.json` 是跨 Skill 的唯一 Practice Task schema。确定性脚本只验证结构、硬事实、格式、模板、输出和渲染门禁；正文质量、阶段连贯性、相关性和容量由统一 Agent pedagogical review 负责。

Lesson Skill 2.3.0 的 Benchmark 也是独立 sidecar。Curator 保留 Catalog/Split 全量信息；Author/Reviewer 的每课运行上下文只包含该课所选 A/B Cards。每课 Review 单独存档，汇总文件记录 review hashes 与课程状态。Authorization claims 由共享 deterministic helper 重验完整 Content、A/B、Selection、Review shards 和课程 Review 后导出；builder 拒绝 `REVISION_REQUIRED`。generator required mode，以及 optional 模式中任何提供 Authorization 的调用，都必须提供完整 evidence；Round 2 还要提供 Round 1 Review、Content 与 shards。Acceptance 重新 derive 并比较 Artifact Authorization、manifest Benchmark block 与 evidence。`2.3-benchmark-linked` 只说明证据链绑定，不代表教学结论通过。
