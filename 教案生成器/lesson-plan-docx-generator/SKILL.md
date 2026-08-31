---
name: lesson-plan-docx-generator
description: Generate projectized Chinese vocational-course lesson plan DOCX files from a strict Lesson Content V2 JSON contract, using the protected Word template, semantic bookmarks, output QA, and optional local render smoke. Use for creating, converting, batching, or revising 教案, 教学单元设计, and 实训教案 files.
---

# 教案生成器

本 Skill 的唯一完整行为规范。其他 agent 入口只要求先读取本文件和 `通用提示词.md`，不要复制另一套字段或生成规则。当前支持 Windows 和 macOS；模型供应商不影响 DOCX 结果。

## 任务入口

任务开始时先读取当前会话、用户上传文件和可用课程资料：能力图谱、章节任务拆解、课程标准、教材目录、旧教案及用户指定的 Word 模板。一次核对课程名称、专业或授课对象、总课时、单次课时和输出目录：

- 信息足够时直接规划，不重复追问；
- 真正缺少且会影响整门课程的事实时，只进行一次集中确认；
- 用户允许合理推断后，按项目化教学补齐项目、任务、教学内容、评价和预生成反思；
- 正式 DOCX 不出现“资料不足、推断、AI、QA、similarity、confidence”等内部说明。

没有任务资料时也必须先形成课程级 outline，再生成逐课内容。outline 至少包含 lesson sequence、项目/任务、prior learning、capability stage、deliverable、next bridge。长课程可以内部按 4 至 6 课一批生成，但最终必须用完整课程上下文统一 QA。

## Content Contract V2

默认使用 `assets/templates/lesson-plan/v1.1.2/template.docx`。

正式生产输入必须是 `content_contract_version: "2.0"`，与 Word 模板版本独立。默认 Word 模板为 `lesson-plan v1.1.2`，并继续支持 v1.0 legacy-coordinate、v1.1.0/v1.1.1 semantic-bookmark 与旧 compatibility 模板路径；旧 sparse JSON 不再生产生成。

课程级必填字段：

```text
content_contract_version, course_name, major, audience,
default_hours, total_hours, lessons
```

每课必须直接提供：

```text
lesson_id, unit, task, hours, progression,
student_analysis, teaching_content, goals,
key_point, difficult_point, teaching_methods, resources, references,
implementation, evaluation, reflection
```

`default_hours` 是 Agent 创建每课时使用的默认单课学时；某课显式提供的 `hours` 可以覆盖它，`default_hours` 不要求等于所有 `lessons.hours`。`unit` 使用项目化名称（如“项目一……”）；`progression` 包含 `prior_lesson_id`、具体的 `prior_learning`、`capability_stage`、`deliverable`、`next_bridge`。`capability_stage` 只能使用 `认知`、`理解`、`模仿`、`独立`、`综合`、`优化`、`迁移`，不要求机械线性递增。第一课的 `prior_lesson_id` 必须为 `null`，后续课次只能引用已经出现的前序课次。四课及以上不得所有能力阶段完全相同。

`student_analysis` 的 base/problems/strategies、三类 goals 均至少两项；teaching_content 至少三项；重难点均须有 content 和 strategy；methods 至少两项，resources 至少两项，references 至少一项。

每课 `implementation` 必须按以下九个 ID、固定顺序完整提供，且每个阶段的 `label`、`minutes`、`modality`、`content`、`teacher_actions`、`student_actions`、`objective` 全部来自 JSON：

```text
before_class_preparation
task_introduction
operation_demonstration
task_implementation
task_extension
project_practice
peer_review
lesson_summary
after_class_improvement
```

课前准备和课后完善属于课外阶段；中间七个阶段的分钟数必须严格等于 `hours * 45`。每个课外阶段允许 0 分钟，但不得超过 `max(60, hours * 45)`，两个课外阶段合计不得超过 `2 * hours * 45`；报错必须指出 lesson ID、stage、actual 和 limit。`operation_demonstration` 是语义行位，可在护理、会计、机械等课程中显示为方法示范、案例解析或技能示范。

评价必须显式提供 85–96 的 `evaluation.score`，使用 0.5 分步进，并提供 canonical 13 个 criterion IDs 的逐课 `remarks`。每条 remark 必须有实质内容；所有 Content V2 模板版本统一执行不超过 48 个有意义字符的合同上限，manifest 只能进一步收紧，超限必须失败而不能截断。未指定分数时建议自然集中在 88–94，但不得全为 90、任意短周期循环、严格递增或递减。`score_breakdown()` 只负责把显式总分确定性拆到既有表格行；Python 不创作备注，不使用三套固定 remarks 循环或机械分数 fallback。反思必须显式提供 summary、innovation、improvement，允许课前预生成，但要围绕本课任务、重难点、组织、预期表现、问题和下一课衔接产生差异。

`references` 使用 `{text, source_kind, evidence?}` 对象；`source_kind` 为 `provided`、`generic` 或 `verified_public`。没有用户材料时使用泛化资料名称，不能虚构教材、作者、出版社、ISBN、标准编号、年份、版次或文件编号；`generic` 不得伪装为具体书名，`verified_public` 必须提供 URL 或可定位的官方来源证据，`provided` 必须提供真实用户资料标识。没有真实附件或资料标识时不得自报 `provided`，只能使用 `generic` 或完成公开来源验证后使用 `verified_public`。信任边界为 `contract_and_locator_only`：Python 只验证 evidence 存在与 locator 形式，不证明用户真的上传了文件，也不证明公开资料真实；Agent 必须在写 JSON 前完成资料核对。evidence 只用于输入和 QA，DOCX 只写 `text`。

完整可运行示例见 `examples/tasks.example.json`，字段说明见 `docs/content-contract-v2.md`，机器约束见 `schemas/lesson-plan-input.schema.json`。

## Python 与 Agent 的边界

Agent 负责课程级规划和所有逐课教学正文；生成器只做 schema 校验、编号、换行、分钟格式化、字段映射和模板写入。V2 正式路径不得调用旧的 `generated_lesson_fields`、`implementation_cell_values`、`reflection_cell_values`，不得使用 `flows[:3]` 或根据缺失字段创作正文。若内容超出 manifest 的 `max_chars` 或 `max_paragraphs`，必须失败并指出 lesson、field、actual chars、limit，不能截断或静默删减。

## 生成与 QA 顺序

```text
资料读取与一次性核对
  -> 课程 outline
  -> Content V2 JSON
  -> Input Contract QA
  -> Content Quality QA
  -> Template QA
  -> candidate DOCX generation
  -> Output Structure + Content-to-DOCX Fidelity QA
  -> optional LibreOffice render smoke
  -> atomic commit to final output and external QA report
  -> Agent representative-page visual inspection
```

使用 `scripts/generate_lesson_plans.py` 生成。所有 DOCX 先写入与正式目录同父目录的 candidate；Content QA、模板 QA、输出结构/书签/格式保护、内容保真 QA 和请求的 render smoke 都通过后才交换到正式目录。显式 `--qa-report` 时，外部报告会在其同父目录先 staging，并与输出目录一起提交；任一交换失败都恢复旧输出和旧报告。非空正式目录需要 `--backup-existing`；交换失败必须恢复旧目录。提交成功后，stdout 只报告正式目录中真实存在的 DOCX 路径。Agent 的代表页视觉检查属于提交后的验收；若发现溢出、截断、异常分页或空白页，应重写 V2 内容并使用 `--backup-existing` 重新事务生成。`qa-report.json` 只写报告，不写入 DOCX。

独立 `scripts/content_quality.py` 必须在本地确定性运行，不调用在线 API、embedding 或模型服务。它检查 `adjacent_exact_duplicates`、`adjacent_similarity_pairs`、`field_similarity_pairs`、`whole_lesson_similarity_pairs`、`implementation_similarity_pairs`、逐项重复、实体屏蔽后的 structural similarity、重复长句、旧套话、完整性、progression coherence、score pattern、13 项评价备注 density 和非 IT 污染。所有 detector 共用唯一 reuse policy：`narrative_strict`、`terminology_reusable`、`resource_reusable`、`reference_reusable`、`fixed_rubric_reusable` 和 `ignore`。教学方法、必要资源、合法 reference 与 attendance/compliance/habits 固定 rubric 可以记录复用证据但不 hard fail；学情、目标、教学内容、重难点、反思、progression 和 implementation 始终严格。短课程术语豁免不得进入 narrative field。

progression 的 artifact inheritance 和 forward transition 都必须同时通过词面/coherence 证据与 `substantive_anchor` 证据；“设计、操作、分析、检查、流程、实施”等通用动作不能独立作为 anchor。非相邻 `prior_lesson_id` 仍允许；若物理顺序链为 `review`，报告必须置 `requires_agent_review=true` 并列出 from/to/reason/score/declared_prior。Agent 最终验收不能静默忽略 physical sequence review；无法解释实际授课顺序时必须重写 progression。

确定性 QA 通过并完成原子提交后，Agent 还要逐课内部复审：这一课比上一课新增什么、使用了上一课什么知识或成果、产出了什么、下一课如何使用该成果。这个复审不写入 DOCX。请求 `--render` 时，Python 报告只表示 `render.scope=smoke`，页数方法是轻量 `pdf_page_object_regex`；它不等同于 visual QA 或 pagination verified，也不能证明没有溢出、截断、异常分页或表格变形。Agent 应检查第一课、正文最密集课、最后一课，课程达到 12 课时再检查 1–2 个中间课，关注 clipping、overflow、overlap、blank pages、abnormal row height 和 table boundary。真实检查后使用 `scripts/record_visual_inspection.py` 显式写入独立 `visual-inspection.json`；该文件记录代表页、checks、notes、关联 qa-report、output fingerprint 和 timestamp，Python 不会自动声称视觉通过。视觉失败时必须修改 V2 JSON，用 `--backup-existing` 重新事务生成并重新检查。

默认输出 QA 会读取原始 V2 JSON，通过纯 formatter 计算 expected，再对照 semantic bookmark 或 v1.0 坐标；不重新调用教学内容创作函数。模板布局、70 个 semantic bookmarks、bookmark IDs/names、fingerprint、v1.0/v1.1 compatibility 和 canonical 二进制均受保护。若本机存在 LibreOffice，使用 `--render` 做 render smoke；没有 renderer 时 structural QA 仍通过，报告标记 `render.status=not_executed`。真实分页、溢出和视觉布局结论只来自 Agent 的代表页检查。

路径 preflight 在 mkdir、生成、move、backup、delete 之前执行，保护 Skill root、输入 JSON、schema、selected/custom template、manifest、canonical/compatibility package、scripts 和 tests，并拒绝 ancestor、descendant、resolved symlink 及 Windows lexical/8.3 alias overlap。不要把输出写入受保护目录或自定义模板包。

## 命令

Windows：

```powershell
python scripts/generate_lesson_plans.py `
  --tasks-json tasks.json `
  --output-dir output `
  --render
```

macOS：

```bash
python3 scripts/generate_lesson_plans.py \
  --tasks-json tasks.json \
  --output-dir output \
  --render
```

单独校验输出：

```text
scripts/validate_template.py --json
scripts/validate_output.py --input-json tasks.json --output-dir output --render
```

跳过参数只影响相应 QA 层，并必须在报告中明确为 `skipped`；输入契约、内容质量和路径保护不能被跳过。临时 JSON、PDF、图片和 candidate 目录在任务结束后清理，不提交生成 DOCX。

## 模板文件

```text
assets/templates/lesson-plan/v1.1.2/template.docx
assets/templates/lesson-plan/v1.1.2/manifest.yaml
assets/templates/lesson-plan/v1.1.1/template.docx
assets/templates/lesson-plan/v1.1.1/manifest.yaml
assets/templates/lesson-plan/v1.0.0/template.docx
assets/templates/lesson-plan/v1.0.0/manifest.yaml
schemas/lesson-plan-input.schema.json
scripts/content_contract.py
scripts/content_quality.py
scripts/generate_lesson_plans.py
scripts/validate_template.py
scripts/validate_output.py
```

不要直接编辑 canonical template。自定义模板必须匹配 manifest 和 fingerprint，并接受相同的结构、格式、书签、路径和输出 QA。
