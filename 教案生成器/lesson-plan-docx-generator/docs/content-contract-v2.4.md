# Lesson Content Contract 2.4

Content 2.4 是新课程的全课程覆盖合同。Content 2.2/2.3 文件仍由其原版本分支校验，不能把旧 `split_lessons` 或旧 `practice_only` 输入自动解释为新版本。

## 学时与课次

每次课默认 `default_hours=2` 学时。课程每 2 学时对应 1 份 Lesson；非整除尾数保留为最后一课的真实学时。`Σ Lesson.hours = total_hours`，逐课理论/实践之和等于课时，且课程理论、实践总账与 `delivery_plan` 完全相等。全理论课程使用 `theory_only`，全实践课程使用 `practice_only`，混合课程可用 `separate_full_lessons`（理论/实践课分开）或既有 `integrated_lessons`/`hybrid`。Content 2.4 拒绝 `split_lessons`，避免沿用旧版只为理论课生成 Lesson 的含义。

| 已确认的组织方式 | `total_hours` | Theory Lesson | Practice Lesson | 示例 |
|---|---:|---:|---:|---|
| 纯理论 | 40 | 20 | 0 | 20 份理论教案 |
| 理论/实践分开 | 40 (20+20) | 10 | 10 | 20 份教案 |
| 纯实践 | 40 | 0 | 20 | 20 份实践教案 |

`Practice Task`/`WorkOrder` 是实践 Lesson 的补充执行材料。其 `practice_hours` 描述支撑的原课程实践环节，不能加到 Lesson 学时上再计一次。用户未要求工单时可以关闭，Practice Lesson 仍然完整生成。需要工单时，2 学时任务与承担实践的 Lesson 双向绑定；任务不能替代 Lesson。旧合同保持旧课时与 `practice_task_ids` 语义。

理论和实践仍共用唯一九阶段 ID、固定时间合同、同一模板和原评价评分，不设置第二套实践阶段、模板或打分方式。

## 实际联网检索与参考文献

每课至少被一个真实搜索 query 覆盖。`reference_research.status` 明确记录 `searched_verified_sources`、`searched_no_reliable_source`、`search_blocked` 或 `not_executed`。只有前两种状态可以继续；后二者不能通过生产生成。每条 query 记录实际工具、时间、课次与结果 URL（无结果使用空数组）。这让“实际检索但没有可靠结果”和“未检索”可区分。

有核实来源时，只能引用 `verified_public` 资料。`reference_research.sources` 与 `reference_pool` 必须一一对应，来源须绑定检索 query、匹配课次、来源页及机构、访问时间、实际读取范围、核验字段和读取内容 SHA-256；声明书目字段必须由权威页或另一条明确的核验来源支撑。课程首页、搜索摘要和没有读取的页面不能做内容核验。优先核验中文高职/专业教材、出版社页、官方教学资料；不相关来源不允许跨课凑数。若搜索后没有可靠来源，reference pool 应为空并说明缺口，不生成猜测书目。

生成器只能验证证据绑定与字段一致性，不能仅凭结构字段证明网络使用真实发生。因此在线检索、原始来源阅读和内容准确性仍须由 Agent 如实操作与署名；生成器不能替代教师或独立来源审查。

## 项目 Agent 工作包和汇总

先一次性确认课程基本盘，再由主 Agent 冻结整门课程 outline，写明项目、Lesson ID、主题、学时、类型、先修、递进、贯穿案例和产出。按项目聚合 Lesson，生成独立工作包；当前运行时支持子 Agent 时每项目一名专属子 Agent，不能按课拆分。如果不支持子 Agent，则主 Agent 按同样项目工作包依次完成，并记为 `sequential_fallback`，不得伪造委派。

项目 Agent 只能返回分配范围内的 Lesson 内容和项目证据，不改课程全局事实、全局 outline 或其他项目输出。主 Agent 合并并核对 Lesson ID 完整且唯一、项目边界、课时账、知识递进、术语、贯穿案例/数据和理论实践衔接；存在冲突时退回对应项目修订。`scripts/project_merge.py` 对照冻结 outline 严格拒绝缺课、重复课、越界课、跨项目 `unit` 冲突、outline 篡改与理论/实践/总课时不一致。最终 Word/PDF 只由主 Agent 调用 canonical generator 生成。

`generation-evidence.json` 必须记下冻结 outline digest、每项目委派/回退模式、owner、工作包/输出摘要、逐项目自检、主 Agent 汇总结果。它随 Content 2.4 的 `generate_lesson_plans.py --generation-evidence` 一起通过验证并复制到产物目录。

## 编写前借鉴、成稿后 15 维对照

每项目编写前须实际检索并阅读与课程、学习者和教学情境相近的完整教学设计或正式公开示范课的具体内容。若没有可靠优秀性证明，来源只能标作 `not_proven`，并说明比较边界；普通课程页、大纲、获奖名单和搜索摘要不能冒充完整优秀教案。没有可访问作品时记录实际检索及结果，不能伪造阅读。

每课初稿完成后、Word 生成前必须按 `schemas/benchmark-lesson-review.schema.json` 已有的 15 维逐课对照，记录已有设计、当前内容证据、来源具体方法、真实差距、改进理由与结论。对照为同上下文普通工作时明确标记 `daily_non_blind`，不能自称正式 Benchmark/A-B、盲审、独立 Reviewer 或 Authorization。只有确实有教学意义的差距才修改；无真实问题保留初稿。修改时既有 `pedagogical_review` 记录初稿、修订与复审，Evidence sidecar 绑定前后摘要。每课比较摘要精确匹配最终 Agent-owned Lesson 内容。

`generation-evidence.schema.json`/`generation_evidence.py` 是生成时门禁，不以 SKILL 文档说明代替执行记录。缺少任一 Lesson、少于 15 个标准维度、未检索/未阅读来源、伪优秀性声明、失配项目、虚假的课时总账或缺少复审均拒绝生产产物。完整的 15 维结果随 QA 和 Artifact Manifest 哈希链交付。

`teaching_quality_gate.status=evidence_complete` 只表示强制证据齐全且绑定。它不等价于“自动教学质量通过”、正式盲审或教师 Acceptance；结构 QA、学科正确性、来源适用性、跨项目人工复核仍分别报告。
