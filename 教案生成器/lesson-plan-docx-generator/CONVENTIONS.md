# Aider 约定（Lesson Skill 2.3.0）

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`，不要在 Aider 配置中复制 Content Contract 字段。工作顺序是一次中文 intake、冻结课程事实、课程 outline、Content 2.2 JSON、确定性 QA、受保护模板写入和真实渲染。

Lesson DOCX 只承载理论；每课使用 10/（`hours × 45`）/15 分钟时间合同，1 学时内容必须实质少于 2 学时。教材、resources 与 references 分离，教材/PPT/课件/案例/内部资源不能成为 reference。只有明确需要实践工单时才生成 Practice Task Contract 1.1/handoff，且由 Agent 调用 WorkOrder Skill；Python 不跨调用、不创作正文、不伪造工单。未执行或失败的真实 render 不能标记生产通过。

2.3 Benchmark 采用 Catalog/Split/A-B Packs、分角色 Selections、逐课 Review shards、课程汇总和完整 Authorization sidecar。Agent 每次只接收本课选定的 Cards。完整验证后，正式 DOCX 调用 generator 时必须传 `--benchmark-mode required --benchmark-authorization <file>`；Acceptance 使用 A/B 双侧 full linkage。Round 2 必须更新实际教学内容以及 Content 2.2 Review history/provenance，禁止只改序列化字节。
