---
trigger: always_on
---

先读取 `SKILL.md`、`AGENTS.md` 与 `通用提示词.md`，遵循 Lesson Skill 2.3.0 / Content Contract 2.2 的课程事实冻结、整课 outline、Agent 正文创作、Content QA 和受保护模板事务。Lesson DOCX 只承载理论内容，既有时间合同不变。

Benchmark 为独立 sidecar。Curator 保管完整 Catalog/Split；Author/Reviewer 每课只看到已选 Cards。正式生产前验证 A/B Packs、Selections、每课 Review shards 和课程汇总，构建 Authorization，并使用 `--benchmark-mode required --benchmark-authorization <file>` 生成 DOCX。Round 2 要求 Agent 内容语义变化、更新 Content 2.2 pedagogical review/provenance，且与 Round 1 Review、内容和分片完整关联。Acceptance 必须验证 A/B 两侧完整链接。脚本只做可确定性校验，不能宣称真实教学质量。
