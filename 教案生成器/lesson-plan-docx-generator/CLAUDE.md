# Claude Code 入口（Lesson Skill 2.2.3）

开始前读取 `SKILL.md` 与 `通用提示词.md`。先一次性完成中文 intake，确认后冻结课程事实并先做全课程 outline；随后按 Content Contract 2.2 生成理论 Lesson、QA 和 DOCX。

Lesson DOCX 只承载理论。每课课前 10 分钟、七个课中阶段合计 `hours × 45` 分钟、课后 15 分钟；1 学时内容必须实质少于 2 学时。教材、resources、references 分离，references 保留真实责任者信息，书籍年份可选且不写未知年份。只有明确需要实践工单时才生成 Practice Task Contract 1.1/handoff，并在 Lesson QA/DOCX 后调用 WorkOrder Skill Agent；不得由 Lesson Python 跨调用或伪造 WorkOrder DOCX。工单不可用时使用 SKILL.md 规定的原样提示。
