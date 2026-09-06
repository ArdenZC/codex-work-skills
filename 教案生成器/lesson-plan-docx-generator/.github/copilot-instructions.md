# GitHub Copilot 教案规则

若明确 `practice_work_orders=true`，由 Lesson Agent 检测并调用 WorkOrder Skill Agent；每个 Practice Task 和 WorkOrder 固定对应 2 学时，实践学时必须为偶数且数量等于实践学时除以 2；不可用时交付 Lesson 与 handoff 并明确 `WorkOrder Skill unavailable; handoff generated.`，不得由 Lesson Python subprocess 或伪造工单 DOCX。若明确 false，实践学时只进入课程总账，不生成 contract、handoff、WorkOrder 或实践侧额外文件。

开始前读取同目录 `SKILL.md` 和 `通用提示词.md`。遵循 Content Contract V2：先课程级规划，所有逐课正文、实施阶段、评价 remarks 和反思直接进入 JSON；Python 只做校验、格式化、模板映射和 candidate 原子提交。运行真实 Content/Template/Output QA，支持 Windows/macOS，不接受 sparse input、旧套话、IT 默认污染或静默截断。
