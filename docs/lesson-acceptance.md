# Lesson Acceptance V2

Lesson Acceptance V2 兼容读取 Content Contract 2.0/2.1，并对当前生产 Content Contract 2.2 增加理论/实践产物拆分、课程交付、reference catalog 和 Practice Task handoff 门禁。Acceptance schema 仍保持 `2.0`，因为这是验收报告格式版本，不是 Lesson Content 版本。

Lesson Acceptance V2 是一个本地、只读的验收证据汇总器。它读取已经生成的 Content V2 JSON、现有 `qa-report.json` 和 DOCX 输出目录，把结构门禁、Content QA 证据、课程级人工复核和可追溯指纹汇总为：

- `lesson-acceptance-report.json`
- `lesson-acceptance-report.md`

报告目录必须放在输出目录之外，例如 `F:\\acceptance\\database-20260901`。工具不会修改输入 JSON、DOCX、qa-report 或模板，也不会生成 32 课/64 学时的 CI E2E。大批量输出应保留在本地验收工作区，不提交仓库。

## 运行

在仓库根目录运行：

```powershell
$py = "C:\\path\\to\\python.exe"
$head = git rev-parse HEAD
& $py tests/lesson_acceptance.py `
  --input-json F:\\acceptance\\database\\content-v2.json `
  --output-dir F:\\acceptance\\database\\output `
  --qa-report F:\\acceptance\\database\\output\\qa-report.json `
  --report-dir F:\\acceptance\\database\\report `
  --source-type real_agent `
  --master-commit $head `
  --repo-root . `
  --template-version v1.1.2
```

`--source-type` 只能是 `real_agent`、`synthetic_fixture`、`human_authored` 或 `mixed`。如果暂时没有人工 JSON，报告会明确写 `PENDING_MANUAL_REVIEW`，不会把 render smoke 冒充视觉验收，也不会把结构 PASS 冒充课程整体 PASS。

报告结构 schema 见 [`lesson-acceptance-report.schema.json`](lesson-acceptance-report.schema.json)。`acceptance_schema_version` 为 `2.0`；当前 Content Contract 为 `2.2`（兼容 `2.1`/`2.0`），默认模板仍为 `v1.1.2`。

## Content 2.2 hard gates

报告新增 `delivery_metrics`、`reference_metrics` 和 `practice_handoff_metrics`，并在 `structural_hard_gates.gates` 中记录：

- `delivery_plan` 总课时、理论/实践课时、理论 Lesson 与 Practice Task 的实际合计必须一致；Lesson DOCX 只计理论，理论课次数量按默认单课课时向上取整并保留余数；
- reference pool 占位文本、教材重叠（未显式 override）、同课重复 ID 和未解析 ID 必须为零；跨课重复只记录 reuse frequency，不失败；
- Practice Task Contract 的任务数量、实践学时、任务 ID 和理论准备链接必须一致；实践不要求对应实践 Lesson DOCX，纯实践课程可以没有 Lesson。

这些门禁不改变既有 Content QA 的正文重复、progression 或 implementation coherence 算法；它们只收口 Content 2.1/2.2 的课程基础与 artifact 合同。

## 四层验收

### 1. Structural hard gates

工具检查并记录：

- lesson 数量、DOCX inventory、QA `files_checked`；
- 声明总课时与现有 QA 实际总课时；
- Content Contract 2.0/2.1/2.2；
- template id/version、固定名称、protected layout 与 writable-field fidelity；
- semantic bookmark inventory；
- 现有 Content QA status；
- 所有 DOCX 的 render smoke。

这些值全部来自输入和现有 `qa-report.json`；工具不复制生产 duplicate、progression 或 implementation-coherence 算法。

### 2. Content quality evidence

报告只汇总现有 QA 的 whole-lesson、adjacent、字段、implementation、evaluation remark 相似度，以及 duplicate detector 计数和错误证据。它不增加新的相似度阈值，也不要求每课必须不同。

2.2 的 `course_materials.textbook` 与 `reference_pool` 分离，教材默认不进入 Word references。每个理论 Lesson 至少选择一项具体文献/文档；课次只携带 `reference_ids`；`reference_provenance` 负责报告 catalog reuse frequency、placeholder、textbook overlap、same-lesson duplicate、resource-only 和 unresolved ID。参考资料按国内来源优先，国内占比只是质量信号；`references` 的跨课重复由 Content QA 的 `reference_reusable` 证据表示且不得触发正文反重复 hard-fail；同一课内部重复项和 resource-only 项仍按生产 QA 结果处理。空 `reference_ids` 在 2.2 直接失败，不写“无/暂无/资料不足”。

### 3. Teaching design review

这是人工设计审查，不是 Python hard gate。至少逐项记录：scope、progression、task realism、implementation、QA gaming、evaluation、reflection。课程 scope 对每个项目使用：

- `CORE`
- `EXTENSION`
- `POSSIBLE_SCOPE_DRIFT`

不能用“长度不同”代替设计判断。工具会给出每课和全课程的字符分布（min/max/mean/median/p10/p90），这些是描述性证据，没有 `must differ` 门槛。

### 4. Teacher usability

教师完整阅读 4–6 份代表性教案，至少覆盖：

- L01；
- 一个项目边界前后两课；
- 字符量、implementation 或 evaluation 密度较高的一课；
- 有 L32 时包含 L32。

每份按 1–5 记录“是否能直接授课、任务是否可执行、实施步骤是否可操作、评价是否可观察、反思是否能支持改进”，并写定性备注。建议解释：`>=4` 份 usable 是通过信号；约 3 个明确 teacher tweaks 形成 `PASSED_WITH_TEACHER_ADJUSTMENTS`；`<=2` 份 usable 是 acceptance issue。没有读完就保持 `PENDING_MANUAL_REVIEW`。

## Sequence 与项目边界

`sequence_review` 读取现有 `content_quality.progression.sequence_links`，报告物理相邻转换数量（32 课应为 31），并只展开 `REVIEW`、`FAIL` 和项目边界的详细证据。输出状态统一为 `PASS`、`REVIEW`、`FAIL`。

对于历史 Software Modeling 64 学时、32 课的验收，必须特别复核：

`L04→L05`、`L08→L09`、`L12→L13`、`L16→L17`、`L20→L21`、`L24→L25`、`L28→L29`。

这些边界只作为验收关注点，不改变 progression 主算法。

## Visual sampling

render smoke 仍应覆盖全部 DOCX。人工视觉样本按风险选择：首尾课、每个项目、每个项目边界前后、最大页数、最大内容/implementation/evaluation 密度，以及确定性随机的 10–20%。如果没有实际打开并检查页面，`visual_review.status` 必须是 `not_executed`。

## Negative controls

验收工作区应保留一个旧输出目录和可识别 sentinel，然后逐项通过真实生成器验证候选失败、候选清理和旧输出保持不变：

1. nursing SQL contamination；
2. database patient blood pressure；
3. 三课复制 `teacher_actions`；
4. 机械评分（全同/简单循环/等差）；
5. 带虚构详细书目信息的 generic reference；
6. 49 字符评价备注。

这些 negative controls 复用现有 Content QA/生成事务证据，不在 Acceptance V2 里另造 detector。`negative_controls` 没有执行证据时必须保持 `not_executed`。

## Provenance 与人工判断

真实 Agent A/B 生成只在本地执行，不进 CI；brief 必须重新生成完整 32 课，不能把旧 fixture 冒充真实 Agent 证据。报告记录 source type、master commit、input/QA SHA256 和 output inventory fingerprint，并对学校、教师、教材、ISBN、schedule 以及 generic 详细书目信息给出人工核实 flag。用户明确提供且有 evidence 的信息不能直接判为虚构。

历史 baseline 只用于比较趋势，不产生验收阈值。

最终关闭状态只能在人工层完成后使用：

- `PASSED`
- `PASSED_WITH_TEACHER_ADJUSTMENTS`
- `FAILED`

在此之前使用 `PENDING_MANUAL_REVIEW`，不得宣称整体验收通过。
