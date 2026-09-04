---
name: lesson-plan-docx-generator
description: Generate projectized Chinese vocational-course lesson plan DOCX files from the Lesson Content Contract V2.2 (with V2.1/V2 compatibility), using the protected Word template, output QA, and optional local render smoke. Use for creating, converting, batching, or revising 教案、教学单元设计 and 实训教案 files.
---

# 教案生成器 Skill 2.2.0

本 Skill 的唯一完整行为规范。其他 agent 入口只要求先读取本文件和 `通用提示词.md`，不要复制另一套字段或生成规则。当前支持 Windows 和 macOS。模型负责理解资料并产出完整 Content 2.2 JSON；Python 只负责确定性校验、格式化和模板映射，不能代替模型创作正文。

## 任务入口与 Intake Runtime 2.1.1

任务开始时先读取当前会话、用户上传文件和可用课程资料：能力图谱、章节任务拆解、课程标准、教材目录、旧教案及用户指定的 Word 模板。正式规划前必须进入 `INTAKE_PENDING`，把当前理解整理成一次集中、全中文的课程基本信息确认；即使信息已经从会话或附件中推断出来，也必须展示并请求用户确认一次。确认完成后进入 `INTAKE_CONFIRMED`，直接开始资料检索、课程级 outline、Content 2.2、QA 和 DOCX。

用户界面只使用中文标签，不把内部字段名当作提问内容。一次确认的必含课程基本盘是：课程名称、专业、授课对象、总课时。确认摘要还必须包含以下非阻断信息：理论课时、实践课时、理论与实践组织方式、单课课时默认 2 学时、使用教材、辅助参考资料、是否同时生成实践任务工单。

当四个核心字段中有信息缺失时，在同一确认摘要中显示“待补充”；总课时只能接受用户明确提供的事实。若专业或授课对象只是 Agent 的推断，必须标注“当前理解 / 如不准确请修改”。当理论/实践拆分、组织方式或实践任务工单偏好没有明确提供时，必须显示“待确认”，不能按 50/50、综合式或“否”自动补齐。`default_hours=2` 只能用于说明按 2 学时估算约有多少课次，不能据此推断理论/实践比例。内部字段映射与状态规则见 `docs/intake-contract-v2.1.1.json`；用户界面只显示“辅助参考资料”，内部状态仍使用 `auxiliary_references`，不得把该英文 key 当作用户问题。

首次响应应类似：

```text
我先确认一下课程基本信息：
- 课程名称：《数据结构高级》
- 专业：当前理解 / 如不准确请修改
- 授课对象：当前理解 / 如不准确请修改
- 总课时：40 学时
- 理论课时：待确认
- 实践课时：待确认
- 理论与实践组织方式：待确认（可选：全部理论 / 全部实践 / 分段组织 / 综合组织）
- 单课课时：默认 2 学时
- 使用教材：未指定（如有指定教材请告诉我；没有也可以继续）
- 辅助参考资料：未指定
- 是否同时生成实践任务工单：待确认
以上信息是否正确？如需调整，请一次性告诉我。
```

教材是 recommended, not required：已提供文件或书名直接展示，未提供也不能阻断生成。`practice_work_orders` 未提供时保持待确认；只有用户明确选择后才联动 WorkOrder Skill。确认 `practice_work_orders=true` 后，Lesson Agent 在完成 Lesson QA/DOCX 和 Practice Task Contract handoff 后检测并调用可用的 WorkOrder Skill，由 WorkOrder Agent 创作完整 Content V1、执行 QA 并生成工单，最后统一交付；不可用时正常交付 Lesson 与 handoff，并明确 `WorkOrder Skill unavailable; handoff generated.`，不伪造工单 DOCX。

Intake 未确认前，不得确定项目数量或名称、理论/实践课次结构、实践任务数量、逐课教学内容或生成 DOCX；除非用户已经明确提供了相应事实。确认一次后不得再次询问 outline、项目名称、逐课任务、评分、模板、输出目录或“是否开始生成 DOCX”。默认模板和默认输出规则直接采用。只有用户主动改变要求、确认信息出现无法合理解决的直接冲突，或遇到安全/文件覆盖等真正需要用户决定的事项，才允许再次停下。

若用户明确选择“全部理论”，归一化为 theory_hours=total_hours、practice_hours=0、delivery_mode=theory_only，并将实践任务工单设为 false；若明确选择“全部实践”，归一化为 theory_hours=0、practice_hours=total_hours、delivery_mode=practice_only。其他拆分必须满足 theory_hours + practice_hours = total_hours；不相等时先报告冲突，不得开始 outline。

资料检索优先使用用户提供的教材/课程资料和用户指定教材；有联网能力时再查找出版社或学校官方页、标准/指南、官方技术文档和可核实公开文献。只给出书名时只能写入真实核实的作者、出版社、ISBN、版次或年份；网络不可用时正常继续，不因无法联网中断生成。

- 用户允许合理推断后，按项目化教学补齐项目、任务、教学内容、评价和预生成反思；
- 正式 DOCX 不出现“资料不足、推断、AI、QA、similarity、confidence”等内部说明。

没有任务资料时也必须先形成课程级 outline，再生成逐课内容。outline 至少包含 `lesson_id`、`unit`、`task`、`lesson_type`、`hours`、`theory_hours`、`practice_hours`、`prior_learning`、`capability_stage`、`deliverable`、`next_bridge` 和 `practice_task_ids`。长课程可以内部按 4 至 6 课一批生成，但最终必须用完整课程上下文统一 QA。

## Content Contract V2.2

默认使用 `assets/templates/lesson-plan/v1.1.2/template.docx`。

正式生产输入默认是 `content_contract_version: "2.2"`，与 Word 模板版本独立；运行时兼容读取 `"2.1"` 和 `"2.0"`。默认 Word 模板为 `lesson-plan v1.1.2`，并继续支持 v1.0 legacy-coordinate、v1.1.0/v1.1.1 semantic-bookmark 与旧 compatibility 模板路径；旧 sparse JSON 不再生产生成。

课程级必填字段：

```text
content_contract_version, course_name, major, audience,
default_hours, total_hours, delivery_plan, course_materials,
reference_pool, artifact_plan, outline, lessons
```

每个 2.2 理论课次必须直接提供：

```text
lesson_id, unit, task, lesson_type, hours, theory_hours, practice_hours,
progression, reference_ids, practice_task_ids,
student_analysis, teaching_content, goals,
key_point, difficult_point, teaching_methods, resources,
implementation, evaluation, reflection
```

2.0 输入仍读取课次内的 `references` 对象；2.1 兼容输入保留原有课次语义。2.2 只通过课程级 `reference_pool` 的 `reference_ids` 选取来源，且每个理论 Lesson 至少有 1 项 reference。2.2 的 Lesson DOCX 只承载理论：`sum(lesson.hours) == theory_hours`，所有 Lesson 为 `lesson_type=theory`、`practice_hours=0`；实践只能进入 Practice Task Contract / WorkOrder handoff。`practice_task_ids` 表示与理论课次关联的实践任务，不表示要生成实践 Lesson DOCX。`delivery_plan` 支持 `theory_only`、`practice_only`、`split_lessons`、`integrated_lessons`、`hybrid`，并且 `theory_hours + practice_hours == total_hours`、Practice Task 总学时与 `practice_hours` 相等。`integrated` 只描述 artifact-level 理实一体组织，不把实践小时塞进 Lesson DOCX，也不固定 1+1。

`default_hours` 是 Agent 创建每课时使用的默认单课学时；某课显式提供的 `hours` 可以覆盖它，`default_hours` 不要求等于所有 `lessons.hours`。`default_hours`、`total_hours` 和每课 `hours` 都必须是正整数课时：数值可为 `1`、`2`、`4`、`12` 等整数，字符串可为 `"1"`、`"2"`、`"2.0"`；不接受空白字符串、分数、零、负数、`NaN` 或 `Infinity`。`unit` 使用项目化名称（如“项目一……”）；`progression` 包含 `prior_lesson_id`、具体的 `prior_learning`、`capability_stage`、`deliverable`、`next_bridge`。`capability_stage` 只能使用 `认知`、`理解`、`模仿`、`独立`、`综合`、`优化`、`迁移`，不要求机械线性递增。第一课的 `prior_lesson_id` 必须为 `null`，后续课次只能引用已经出现的前序课次。四课及以上不得所有能力阶段完全相同。

`student_analysis` 的 base/problems/strategies、三类 goals 均至少两项；teaching_content 至少三项；重难点均须有 content 和 strategy；methods 至少两项，resources 至少两项。2.2 理论 Lesson 的 `reference_ids` 不得为空；空 reference 直接失败。纯实践课程可以没有 Lesson DOCX，但必须用 Practice Task handoff 表达实践学时，不能虚构理论课次。

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

2.2 的 `course_materials.textbook` 单独表示教材，可为对象或 `null`；它默认不会自动写入 Word 的 references 单元格。Agent 在逐课生成前先形成 `course_reference_pool` / `reference_catalog` planning concept，落盘字段仍是 `reference_pool`，不是新的 JSON contract 字段。每项必须有 `reference_id`、`reference_type`、可识别的具体标题、`source_kind`、`source_region`（`domestic`/`foreign`/`unknown`）和相应 evidence；逐课只写 `reference_ids`。`allow_textbook_as_reference` 默认 false，只有显式为 true 时教材才允许进入 references。`references` 只表示可以阅读、查阅、引用或作为课程依据的文献/文档来源，包括专著、课程/教学标准、国家/行业/职业标准、指南/规范、论文、公开文献、官方技术文档、官方产品手册和用户提供的正式教学文档。`resources` 表示实施教学时使用的工具、设备、环境和材料，例如 MySQL Workbench、数据库服务器、PPT、投影仪、护理模型、虚拟机、实训任务单和案例数据集；这些不能为了凑数写入 references。每课通常选 1–3 项 reference，课程级合法 reference 可重复使用。

`source_kind` 仍保留 `provided`、`generic`、`verified_public`；`provided` 需要用户真实材料 evidence，`verified_public` 需要 URL 或可定位官方来源，`generic` 只可使用具体的文档语义且不得伪造详细书目信息。禁止“统一建模语言相关公开文档”“相关网络资源”“相关公开文献”等泛化占位文本，也禁止猜作者、ISBN、出版社、版次、年份或标准编号。国内来源优先：用户提供资料、国内出版物/专著、国内高校资料、国家/行业/职业标准和国内权威文件优先于外国经典；国内占比低于 70% 只是 quality warning，不是 hard fail，确有国际标准/经典或国内来源不足时可补充外国来源。reference 跨课完全重复允许，属于 `reference_reusable`，明确退出 exact/item/sentence/field/structural/frequency/whole-course 反重复 hard-fail；同一课内部重复 ID 或重复内容仍 hard-fail。References 的重复不属于教案正文重复问题。禁止为了降低课程重复率编造不同教材、作者、ISBN、出版社、标准编号或公开文献；同一教材重复 18 次优于编造 18 本教材。evidence 只用于输入和 QA，DOCX 只写正式引用文本，不写 evidence 元数据。

### Practice Task Contract V1

课程实践学时大于 0 时，2.2 输入必须提供 `practice_task_contract`，版本为 `1.0`，默认 `granularity: "per_task"`。任务字段是 `task_id`、`project_id`、`title`、`lesson_ids`、`practice_hours`、`scenario`、`objectives`、`required_inputs`、`tools_or_materials`、`steps`、`deliverables`、`acceptance_criteria`、`safety_or_compliance`。`lesson_ids` 是提供理论准备/前置知识的理论 Lesson ID，可跨多个课次；纯实践课程没有理论 Lesson 时为空数组。不能假设一课一个任务，也不能假设 WorkOrder 数量等于实践小时数或 Lesson 数量。`practice_work_orders=true` 时，Lesson 只负责生成并 QA canonical handoff，再由已检测到的 WorkOrder Skill 通过 Agent orchestration 消费 handoff；Lesson Python generator 不得 subprocess 调用 WorkOrder Python，也不得自动映射成工单正文。WorkOrder Skill 不可用时只输出 `practice-task-contract.json` handoff，并明确 unavailable 状态，不伪造实践工单 DOCX。

当前 2.2 完整规则见 `docs/content-contract-v2.md`；`examples/tasks-v21.example.json` 保留为 2.1 兼容示例，`examples/tasks.example.json` 保留为 2.0 兼容示例。字段说明见 `docs/content-contract-v2.md` 和 `docs/practice-task-contract-v1.md`，机器约束见 `schemas/lesson-plan-input.schema.json` 与仓库 canonical `schemas/shared/practice-task-contract.schema.json`；`schemas/practice-task-contract.schema.json` 仅为兼容入口。

## Python 与 Agent 的边界

Agent 负责课程级规划和所有逐课教学正文；生成器只做 schema 校验、编号、换行、分钟格式化、字段映射和模板写入。V2 正式路径不得调用旧的 `generated_lesson_fields`、`implementation_cell_values`、`reflection_cell_values`，不得使用 `flows[:3]` 或根据缺失字段创作正文。若内容超出 manifest 的 `max_chars` 或 `max_paragraphs`，必须失败并指出 lesson、field、actual chars、limit，不能截断或静默删减。

## 生成与 QA 顺序

```text
读取资料 → 一次性课程基本信息确认
  -> 课程 outline
  -> Content V2.2 JSON
  -> Input Contract QA
  -> Content Quality QA
  -> Template QA
  -> candidate DOCX generation
  -> Output Structure + Content-to-DOCX Fidelity QA
  -> optional LibreOffice render smoke
  -> atomic commit to final output and external QA report
  -> when practice_work_orders=true, detect and call WorkOrder Skill Agent, then unify Lesson + WorkOrder delivery
  -> Agent representative-page visual inspection
```

使用 `scripts/generate_lesson_plans.py` 生成。所有 DOCX 先写入与正式目录同父目录的 candidate；Content QA、模板 QA、输出结构/书签/格式保护、内容保真 QA 和请求的 render smoke 都通过后才交换到正式目录。显式 `--qa-report` 时，外部报告会在其同父目录先 staging，并与输出目录一起提交；任一交换失败都恢复旧输出和旧报告。非空正式目录需要 `--backup-existing`；交换失败必须恢复旧目录。提交成功后，stdout 只报告正式目录中真实存在的 DOCX 路径。课程基本信息确认后不再为生成 DOCX 追加确认；Agent 的代表页视觉检查属于提交后的验收；若发现溢出、截断、异常分页或空白页，应重写 V2 内容并使用 `--backup-existing` 重新事务生成。`qa-report.json` 只写报告，不写入 DOCX。

独立 `scripts/content_quality.py` 必须在本地确定性运行，不调用在线 API、embedding 或模型服务。它检查既有正文重复、实体屏蔽后的 structural similarity、重复长句、旧套话、完整性、intra-lesson coherence、progression coherence、score pattern、13 项评价备注 density 和非 IT 污染；本轮只新增 2.2 reference 必填、source-region 统计和理论/实践 handoff 检查，不改变既有 repetition、progression、评分或 implementation coherence 算法。`non_it_contamination` 及其 scope 元数据只检测“输入没有但模板或生成器注入输出”的 IT 默认词，不是通用课程分类器。诊断只保留有限片段和稳定 SHA-256，不输出整段用户正文。所有 detector 共用唯一 reuse policy：`narrative_strict`、`terminology_reusable`、`resource_reusable`、`reference_reusable`、`fixed_rubric_reusable` 和 `ignore`。教学方法、必要资源、合法 reference 与 attendance/compliance/habits 固定 rubric 可以记录复用证据但不 hard fail；reference 允许跨课完全重复，且完全退出 exact/item/sentence/field/structural/frequency/whole-course 反重复 hard-fail；同课内部 exact duplicate 和明显的纯工具/设备 reference 必须 hard-fail。短课程术语豁免不得进入 narrative field。不得为了降低课程重复率虚构参考文献。

progression 的 artifact inheritance 和 forward transition 都必须同时通过词面/coherence 证据与 `substantive_anchor` 证据；“设计、操作、分析、检查、流程、实施”等通用动作不能独立作为 anchor。非相邻 `prior_lesson_id` 仍允许；若物理顺序链为 `review`，报告必须置 `requires_agent_review=true` 并列出 from/to/reason/score/declared_prior。Agent 最终验收不能静默忽略 physical sequence review；无法解释实际授课顺序时必须重写 progression。

确定性 QA 通过并完成原子提交后，Agent 还要逐课内部复审：这一课比上一课新增什么、使用了上一课什么知识或成果、产出了什么、下一课如何使用该成果。这个复审不写入 DOCX。请求 `--render` 时，Python 报告只表示 `render.scope=smoke`，页数方法是轻量 `pdf_page_object_regex`；它不等同于 visual QA 或 pagination verified，也不能证明没有溢出、截断、异常分页或表格变形。Agent 应检查第一课、正文最密集课、最后一课，课程达到 12 课时再检查 1–2 个中间课，关注 clipping、overflow、overlap、blank pages、abnormal row height 和 table boundary。真实检查后使用 `scripts/record_visual_inspection.py` 显式写入独立 `visual-inspection.json`；该文件记录代表页、checks、notes、关联 qa-report、output fingerprint 和 timestamp，Python 不会自动声称视觉通过。视觉失败时必须修改 V2 JSON，用 `--backup-existing` 重新事务生成并重新检查。

默认输出 QA 会读取原始 V2 JSON，通过纯 formatter 计算 expected，再对照 semantic bookmark 或 v1.0 坐标；不重新调用教学内容创作函数。模板布局、70 个 semantic bookmarks、bookmark IDs/names、fingerprint、v1.0/v1.1 compatibility 和 canonical 二进制均受保护。若本机存在 LibreOffice，使用 `--render` 做 render smoke；没有 renderer 时 structural QA 仍通过，报告标记 `render.status=not_executed`。真实分页、溢出和视觉布局结论只来自 Agent 的代表页检查。

适配器安装语义固定为：默认是 `instruction-only adapter install（仅规则/指令安装）`，只安装项目规则和最小 instructions，不复制完整 runtime，也不承诺目标项目可以独立执行 generator；只有追加 `--copy-engine` 才是 `full runnable project-local Lesson engine（完整可运行引擎）`。目标项目需要直接调用 `.lesson-plan-docx-generator/scripts/generate_lesson_plans.py` 时必须使用 `--copy-engine`。`visual-inspection.json` 是 `Agent visual inspection attestation for the current generated DOCX/QA state`，表示 Agent 对当前生成 DOCX/QA 状态的代表页检查，不是所检查 PDF/图片的加密证明。

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
scripts/validate_visual_inspection.py --output-dir output --qa-report output/qa-report.json --evidence output/visual-inspection.json
```

手动安装及依赖检查（安装器不会自动修改 Python 环境）：

```text
python scripts/install.py --skills-dir <skills-dir>
python <skills-dir>\lesson-plan-docx-generator\scripts\check_dependencies.py
```

`check_dependencies.py` 只读检查 `docx`、`yaml`、`jsonschema`；缺失时提示 `pip install -r requirements.txt`。Agent 生产流程禁止使用 `--skip-template-validation` 或 `--skip-output-validation`；这两个兼容参数只有在显式设置 `LESSON_ALLOW_UNSAFE_VALIDATION_SKIP=1` 时才可用于受控测试，并必须在报告中明确为 `skipped`。输入契约、内容质量和路径保护不能被跳过。临时 JSON、PDF、图片和 candidate 目录在任务结束后清理，不提交生成 DOCX。

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
