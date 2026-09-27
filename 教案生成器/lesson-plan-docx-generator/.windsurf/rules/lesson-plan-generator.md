---
trigger: always_on
---

先读取 `SKILL.md`、`AGENTS.md` 与 `通用提示词.md`。当前默认 Lesson Skill 2.3.1 / Content 2.3，Content 2.2 保持历史兼容。先完成一次课程事实确认、冻结基本盘和全课程 outline，再由 Agent 创作逐课正文与 review。

Content 2.3 的 Lesson coverage 按 mode 确定：theory_only/integrated_lessons/hybrid 使用总学时；split_lessons 使用理论学时；practice_only 保持无 Lesson。64/32/32 integrated、每课 2 学时必须覆盖为 32 Lesson。工单 false 不得删除 Lesson 内实践；true 时配套 16 个 2 学时 Practice Task/WorkOrder，工单不额外增加总时数。Hybrid 支持 theory/practice/integrated 混排且逐课与总账精确守恒。

Content 2.2 历史语义、Template 1.1.2、九阶段、评价与 Benchmark sidecar 架构不变。所有教学内容与判断由 Agent 提供；脚本不写正文、不判质量。
