---
name: lesson-plan-docx-generator
description: Generate projectized Chinese vocational-course lesson plan DOCX files from a strict Lesson Content V2 JSON contract, using the protected Word template, semantic bookmarks, output QA, and optional local render QA. Use for creating, converting, batching, or revising 教案, 教学单元设计, and 实训教案 files.
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

默认使用 `assets/templates/lesson-plan/v1.1.1/template.docx`。

正式生产输入必须是 `content_contract_version: "2.0"`，与 Word 模板版本独立。默认 Word 模板仍为 `lesson-plan v1.1.1`，并继续支持 v1.0 legacy-coordinate 与 v1.1 semantic-bookmark 模板路径；旧 sparse JSON 不再生产生成。

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

`unit` 使用项目化名称（如“项目一……”）；`progression` 包含具体的 `prior_learning`、`capability_stage`、`deliverable`、`next_bridge`。四课及以上不得所有能力阶段完全相同，但不要求机械线性递增。

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

课前准备和课后完善属于课外阶段；中间七个阶段的分钟数必须严格等于 `hours * 45`。`operation_demonstration` 是语义行位，可在护理、会计、机械等课程中显示为方法示范、案例解析或技能示范。

评价必须显式提供 0 至 100 的 `evaluation.score` 和 canonical 13 个 criterion IDs 的逐课 `remarks`。`score_breakdown()` 只负责把显式总分确定性拆到既有表格行；Python 不创作备注，不使用三套固定 remarks 循环或机械分数 fallback。反思必须显式提供 summary、innovation、improvement，允许课前预生成，但要围绕本课任务、重难点、组织、预期表现、问题和下一课衔接产生差异。

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
  -> optional Render QA
  -> atomic commit to final output
```

使用 `scripts/generate_lesson_plans.py` 生成。所有 DOCX 先写入与正式目录同父目录的 candidate；Content QA、模板 QA、输出结构/书签/格式保护、内容保真 QA 和请求的 render 都通过后才交换到正式目录。非空正式目录需要 `--backup-existing`；交换失败必须恢复旧目录。`qa-report.json` 只写在输出目录，不写入 DOCX。

独立 `scripts/content_quality.py` 必须在本地确定性运行，不调用在线 API、embedding 或模型服务。它检查 exact duplicates、implementation duplicates、重复长句、字段/整课 SequenceMatcher 与字符 n-gram 相似度、旧套话、完整性、progression、score pattern、density 和非 IT 污染，并在报告中记录 lesson IDs、field、score 和重复片段。合理重复的课程名、专业、固定工具名、阶段 ID 和评价维度标签不作为正文重复。

默认输出 QA 会读取原始 V2 JSON，通过纯 formatter 计算 expected，再对照 semantic bookmark 或 v1.0 坐标；不重新调用教学内容创作函数。模板布局、70 个 semantic bookmarks、bookmark IDs/names、fingerprint、v1.0/v1.1 compatibility 和 canonical 二进制均受保护。若本机存在 LibreOffice，使用 `--render` 做真实分页检查；没有 renderer 时 structural QA 仍通过，报告标记 `render.status=not_executed`。

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
