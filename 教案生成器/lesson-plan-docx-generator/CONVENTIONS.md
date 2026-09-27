# Aider 约定（Lesson Skill 2.3.1）

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`。默认输出 Content 2.3，Content 2.2 保持历史语义；按 delivery mode 确定 Lesson coverage：theory_only/integrated_lessons/hybrid 为 total_hours，split_lessons 为 theory_hours，practice_only 为零 Lesson。

理实一体 64/32/32、默认每课 2 学时必须生成 32 个 Lesson。Practice Task/WorkOrder 是已计入 64 小时的实践环节配套材料：false 时不生成工单但实践仍在 Lesson 内，true 时另生成 16 个 2 学时任务/工单，均不得二次累计。Hybrid 可混合 theory/practice/integrated Lesson 并精确守恒；split 与纯实践边界保持不变。

正文与教学判断来自 Agent。模板 1.1.2、九阶段、评价体系和 Benchmark 独立 sidecar 架构保持不变。只做确定性 schema、课时、来源、模板、输出、事务和 render 校验；未成功的真实 render 不得标记生产通过。
