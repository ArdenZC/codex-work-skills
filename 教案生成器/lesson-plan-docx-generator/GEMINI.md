# Gemini CLI 入口（Lesson Skill 2.3.0）

先读取 `SKILL.md` 与 `通用提示词.md`，按一次 intake、课程 outline、Content Contract 2.2、QA、模板写入和真实 render 的顺序工作。确认后的课程事实不可被正文改写；Lesson DOCX 只承载理论，课前/课中/课后时间合同必须精确执行，1 学时必须有实质性较小的内容和证据负荷。

仅在用户明确需要实践工单时创建 Practice Task Contract 1.1 与单向 handoff，并由 Lesson Agent 在自身 QA/DOCX 完成后调用 WorkOrder Skill Agent。不得由 Lesson Python 调用工单 Python 或伪造工单。教材、教学资源、参考文献分离；references 不得由设备、PPT、课件、案例或内部资源冒充。

Lesson 2.3 Benchmark 必须按 `SKILL.md` 使用逐课 Review shards 与课程汇总完成完整来源链接，随后创建 Authorization，并在正式生成时传入 `--benchmark-mode required --benchmark-authorization <file>`。Author/Reviewer 只接收本课所选 Cards；Round 2 需语义修订、更新 Content 2.2 pedagogical review/provenance 并复验 Round 1 完整快照。Acceptance 链接 A/B Packs 与 Selections、课程汇总和逐课 Review；Benchmark 不代表真实教学质量结论。
