# 实践任务工单生成器 Agent 规则

本目录是独立的 Phase 1 Skill。先阅读 `简介.md`、`通用提示词.md` 和 `SKILL.md`，再决定输入模式。

## 合同边界

- 优先消费 Lesson Skill 最终交付的 `Practice Task Contract V1` handoff；不要重新设计或复制 Lesson Content Contract。
- 也可以直接消费 `Practice Work Order Content V1` JSON。
- 每个任务必须有可执行步骤、工具/材料、交付物和验收标准；信息不足时停止并报告缺失字段，不编造来源或答案。
- 工单正文是学生执行说明，不写标准答案、完整 SQL、最终 E-R 图、教师答案或代学生填写的结果。

## 模板与输出

- 默认使用 `assets/templates/practice-work-order/v1.0.0/template.docx`。
- 模板是受保护的 canonical binary；只复制到候选输出后修改。
- 生成路径遵循 candidate → output QA → atomic commit；输出失败不得静默覆盖正式文件。
- 学生结果列保持空白，固定学生/教师评价结构不重新设计。

## Phase 1 禁止事项

不要扩大到 Lesson 模板、评分规则、progression、implementation coherence、跨工件全链路 QA、CI/release 架构或教师答案生成。Phase 2 能力只能在文档中标记为未实现，不能宣称已完成。
