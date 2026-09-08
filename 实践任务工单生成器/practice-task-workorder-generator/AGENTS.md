# 实践任务工单生成器 Agent 规则

先读 `SKILL.md`；本文件只提供入口顺序和协作边界，不覆盖 Skill 的业务合同。

## 入口

- 关联生成必须同时获得 Lesson 的 Practice Task Contract 1.1 和 Agent 创作的 WorkOrder Content 1.1。
- 只有 handoff 时，只校验上游合同并输出创作骨架；不得自动补写 Content，不得伪造 DOCX。
- 独立调试必须明确选择 `mode=standalone`；它不能声称完成了 Lesson handoff。
- 旧版 V1 只在用户或迁移流程明确传入 `--legacy` 时读取。

## Agent 责任

- Practice Task 是上游事实源；关联 Content 必须保存完整 `source_task_snapshot`，不改写目标、场景、输入、步骤、交付物、验收、工具/材料和安全约束。
- Agent 独立创作任务项、学生可见文字和分值，并在生成前提交完整 pedagogical review。Review 要覆盖专业性、目标—活动—证据链、九十分钟容量、工具/前置条件、交付物—验收映射、答案泄露和安全合规。
- Python 仅做 schema、ID、课时、固定评分、空白结果区、精确快照、模板映射、输出/渲染和事务门禁；不以词库、字符 n-gram 或相似度代替教学判断。

## 交付边界

- 固定考勤 10 分、任务项合计 90 分、总分 100 分；学生任务结果区保持空白，不生成教师答案或最终业务结论。
- 关联模式默认真实渲染，必须 `render.status=pass`；standalone/debug 只有显式 `--skip-render` 才能跳过，且不构成 Production PASS。
- 学生可见区域隐藏任务、项目和课次内部 ID；JSON、QA、文件名和日志可用于追溯。
- 使用并保护 `practice-work-order v1.0.0` 模板 binary；全批 candidate、QA 和 render 通过后才原子发布。不要改 Lesson 或模板，不进入 Phase 3。
