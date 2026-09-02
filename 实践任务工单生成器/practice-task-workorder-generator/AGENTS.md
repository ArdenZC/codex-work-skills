# 实践任务工单生成器 Agent 规则

本目录是独立的 Phase 2 / 联动候选 Skill。先阅读 `简介.md`、`通用提示词.md` 和 `SKILL.md`，再决定输入模式。

## 合同边界

- 优先消费 Lesson Skill 最终交付的 canonical `Practice Task Contract V1` handoff；canonical schema 是仓库 `schemas/shared/practice-task-contract.schema.json`，不要复制或独立演化第二份。
- Practice Task 是唯一上游事实源。保留 `practice_task_id`、`lesson_ids` 集合、`practice_hours`、标题意图、交付物、验收标准、工具/材料和安全/合规约束；冲突时让 WorkOrder 失败并重新生成，绝不改写 Lesson 或上游合同。
- 也可以直接消费 `Practice Work Order Content V1` JSON，但直接输入同样必须通过 WorkOrder Content QA。
- Python 只做 schema、确定性一致性、格式和输出检查；不重新创作任务正文，不凭空补任务、标准或答案。

## WorkOrder QA

- 每项必须让学生知道做什么、需要什么、怎么开始、做哪些步骤、交什么以及怎么算完成。
- 交付物必须可观察，验收标准必须能覆盖主要交付物；“认真完成任务”“完成相关工作”“提交任务成果”等泛句不能独立构成任务、交付物或验收标准。
- 有限规则检查护理/软件之间的明显污染，不建立无限专业词库，不使用 embedding、在线模型或外部 NLP 服务。
- 跨工单反重复只检查任务叙述、交付物和验收叙述；课堂考勤、学生/教师固定评价 rubric 不参与 duplicate hard-fail。

## 模板与输出

- 默认使用 `assets/templates/practice-work-order/v1.0.0/template.docx`，不询问模板、输出目录或是否开始生成。
- 模板是受保护的 canonical binary；只复制到候选输出后修改。生成路径遵循 candidate → Content/Cross-Artifact/Output QA → atomic commit。
- 课堂考勤固定 10 分，task_items 合计固定 90 分，总分 100；支持 1–5 个任务项，每项正整数。
- 学生 `任务结果` 列保持空白，不生成标准 SQL、最终模型、最终护理/会计结果或教师答案。

## 安装与范围

- `install.py` 必须完成 source integrity、staging、shared schema 依赖、原子替换/回滚；不得自动 pip 安装。
- `install_adapters.py` 独立支持 Codex/AGENTS、Claude、Gemini、Copilot、Aider，并提供 minimal/full-current/full-stale/inconsistent 运行时识别。
- 不修改 Lesson canonical Word template，不修改 WorkOrder 原始模板版式，不新增模板版本，不做教师答案版，不进入 Phase 3 完整 64 学时验收或成绩册联动。
