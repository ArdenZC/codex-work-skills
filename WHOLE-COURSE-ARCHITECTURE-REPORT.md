# Whole-Course Orchestration 1.0 — 第一阶段架构报告

状态：`READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW`

本报告只覆盖架构实现、synthetic tests、基准冻结和可审计输出接口。真实 UML `9 PPT × 16 theory + 16 practice` blind retry 尚未运行，也不在本阶段声称 `WHOLE_COURSE_PASS`。

## A. Baseline

- Repository：`ArdenZC/codex-work-skills`
- Baseline：`origin/master` `3c8fe4a29a4a057cf24e1f3d2b691eb1f9c2408a`
- Baseline tree：`2c0b71488cbf34b44308edff3bb5b229dab02998`
- Feature branch：`feature/whole-course-orchestration`
- Existing downstream Skills remain unchanged: Courseware HTML `1.2.1` and Practice Class HTML `1.2.0`.
- New Skill：`整门课程编排器/whole-course-orchestrator` `1.0.0-alpha`，当前只处于 architecture review。

## B. Failure Benchmark Freeze

正式标识：`WHOLE_COURSE_FAILURE_BENCHMARK_V1`。

Manifest：[benchmarks/WHOLE_COURSE_FAILURE_BENCHMARK_V1/whole-course-failure-benchmark.json](benchmarks/WHOLE_COURSE_FAILURE_BENCHMARK_V1/whole-course-failure-benchmark.json)。它只保存真实外部资料、旧合同、渲染文件、QA 和审计说明的路径、大小、SHA-256 与冻结特征，不把旧产物复制进仓库，也不覆盖它们。

当前快照确认：9 份原始 PPT、旧转换证据中的 9 份 PPTX、16 份理论合同、16 份实践合同、16 次理论渲染、16 次实践渲染、QA 汇总/逐课文件和交付/浏览器审计说明均可定位。

已冻结的 failure signature：

- theory：16/16 为 8 页、同一 layout sequence、61 分钟讲解 + 59 分钟活动、17 blocks、2 SVG；脚本存在跨课模板短语复用；
- practice：16/16 为 2 个任务，`core/modeling/60` + `optional/analysis/60`，步骤同构；
- 总结：`Whole-course content quality = FAIL`，不是单次课 renderer 是否能生成 HTML 的失败。

后续 blind retry 只能读取正式 Skill、原始 PPT 和用户课程要求，不能读取旧合同、旧 HTML 或逐课人工修复建议作为新生成输入。

## C. New Orchestrator

```text
User sources (primary)
        ↓
Teaching Asset Inventory
        ↓
Course Knowledge Graph + research gaps
        ↓
Content-native Session Planner
        ├──────────────┐
        ↓              ↓
Courseware contract  Practice contract
        ↓              ↓
Stable downstream renderers
        └──────┬───────┘
               ↓
        Whole-course Batch QA
               ↓
        Clean Course Package + Evidence
```

编排器负责课程级决策和约束，不实现第三套 HTML/CSS/JavaScript renderer。页面内容、视觉 primitive 和 Practice 合同仍由 Agent 按规划创作，再交给现有下游 Skill 确定性渲染。

## D. Teaching Asset Mining

`mine_teaching_assets.py` 通过 PPTX OOXML 读取 slide text、speaker notes、表格、shape/group、连线/箭头和图片关系，并把图片抽到 inventory 的本地 `image_ref`。旧 `.ppt` 优先调用 LibreOffice 转为 `.pptx`；不可用时记录 `PPT_LEGACY_UNSUPPORTED` 或转换失败，不偷偷 OCR 或伪造结构。

每项 `teaching_asset` 至少含：`id`、`type`、`source_file`、`source_slide`、`source_locator`、`title`、`content_summary`、`raw_text`、`image_ref`、`confidence`、`candidate_topics`、`teaching_value`、`origin`、`origin_type`。`teaching_value` 为 `core` / `supporting` / `optional` / `low-value`；覆盖率按高价值素材使用审查，不把 100% 搬运 PPT 当 KPI。

输出 `source-assets.json` 与 `source-teaching-asset-report.json`，并区分 user source 与 external source。

## E. Course Knowledge Graph

`build_knowledge_graph.py` 支持 `concept`、`notation`、`procedure`、`tool_skill`、`analysis_skill`、`modeling_skill`、`calculation`、`implementation`、`diagnosis` 节点类型。节点保留：

- `source_assets`、`prerequisites`、`depends_on`、`related_to`；
- `difficulty`、`importance`；
- `first_taught_session`、`revisited_sessions`、`practice_dependencies`。

每个 session 自动产生 `knowledge_state_before`、`new_knowledge`、`review_knowledge`、`knowledge_state_after` 和 `future_knowledge`。实践 core 的 knowledge IDs 必须属于 after 状态；提前使用会产生 `KNOWLEDGE_BOUNDARY_ERROR`。

## F. Content-native Session Planner

`plan_sessions.py` 要求先提供具体 `teaching_questions` 与可观察 `learning_outcome`，再选择 `primary_job`：`introduce`、`define`、`explain`、`visualize`、`compare`、`worked_example`、`step_through`、`diagnose`、`check`、`summarize`、`bridge`、`demonstrate`。

页数自然来自问题、证据、案例、视觉和检查；布局只是最后一步映射。每页只有一个主要 teaching job，并带 `script_anchor_ids`、`source_asset_ids`、knowledge IDs、lecture/activity minutes 与 content signature。没有 `20 slides`、`6 diagrams`、`5 quizzes` 或按课程名分支。

## G. Visual Planner

`plan_visuals.py` 先声明 `visual_intent`（如 `hierarchy`、`relationship`、`process`、`sequence`、`state_transition`、`topology`），再按 `artifact_type` 使用通用 semantic adapter：

- `use_case_model`：actor、system boundary、use case、association、include、extend、generalization；
- `class_model`：class compartment、attribute、operation、relationship、multiplicity、inheritance、aggregation、composition；
- `sequence_model`：lifeline、activation、message、return、fragment；
- `state_model`：state、event、transition、guard、initial、final；
- `deployment_model`：node、artifact、deployment、communication link。

typed artifact 如果只有 generic rectangle/TODO，或缺少必需语义元素，直接 `SEMANTIC_VISUAL_DEGRADED`。用户图清晰时可 `reuse`；外部图版权不明时只保留语义参考并 `semantic_redraw`，不直接复制。

## H. Whole-course Practice Planner

`plan_practice.py` 由 capability、artifact type、工具、starter 复杂度、学生水平和可观察产物决定 task 数量。支持 `construct`、`complete`、`diagnose`、`compare`、`transform`、`trace`、`implement`、`verify`、`explain`、`refactor` 等能力。

typed starter 与 editable gap 按 artifact 适配：例如 `class_model` 产生 partial classes / missing relationship / missing multiplicity；`sequence_model` 产生 lifelines / missing messages / wrong order；不能使用通用两个矩形 + `TODO_1`。QA 统计 task count、capability、time、starter 和 signature，不把 `core + optional` 或 `2×60` 当默认合同。

## I. Batch QA

`review_whole_course.py` 输出：

`session_slide_counts`、`layout_sequences`、`slide_job_sequences`、`timing_distributions`、`block_signatures`、`visual_intent_distribution`、`teaching_asset_usage`、`script_cross_similarity`、`repeated_phrase_ratio`、`quiz_distractor_reuse`、`comparison_semantic_errors`、`practice_task_counts`、`practice_task_signatures`、`starter_signatures` 和 `knowledge_boundary_errors`。

主要 gates：

- 页数 + jobs + timing + blocks 全部同构 → `WHOLE_COURSE_TEMPLATE_COLLAPSE`；
- 高价值素材长期 unused → `SOURCE_MATERIAL_UNDERUTILIZED`；
- same-position script / generic phrase 高复用 → `SCRIPT_CROSS_SESSION_TEMPLATE_REUSE`；
- comparison 两侧相同、缺 contrast dimension 或正确项落在 wrong side → fail；
- distractor 长期复用 → `QUIZ_DISTRACTOR_REUSE`；
- Practice signature/time/starter 全同 → `WHOLE_COURSE_PRACTICE_TEMPLATE_COLLAPSE`；
- typed visual 或 knowledge boundary 违规 → P0 fail。

单独相同页数不判死刑；必须综合结构、内容、时长、组件、文本、任务和素材使用。

## J. Packaging

`package_course.py` 将下游产物组织为：

```text
课程包/
├─ 00_课程总览/
│  ├─ 课程总览.html
│  ├─ source-portfolio.html
│  ├─ visual-gallery.html
│  ├─ course-contact-sheet.html
│  ├─ source-usage-dashboard.html
│  ├─ knowledge-progression.html
│  └─ practice-contact-sheet.html
├─ 理论课/01_.../学生课件.html + 教师备课.html
├─ 实践课/01_.../学生资料/ + 教师资料/
└─ _evidence/
   ├─ package-manifest.json
   ├─ course-blueprint.json
   ├─ knowledge-graph.json
   ├─ source-assets.json
   └─ qa/
```

用户包不重复输出 `student/` 与 `student-package/student/`。显示名与文件名通过 `safe_filename()` 分离，`C/S` 会变成 `C-S`，并拒绝路径分隔符、保留名和控制字符。

## K. Tests

`整门课程编排器/whole-course-orchestrator/tests/test_whole_course.py` 的 15 个 synthetic tests 覆盖 T1–T14（另有素材抽取和外部研究回归）：

1. T1 template collapse；
2. T2 三种课程形态的自然差异；
3. T3 source underuse；
4. T4 comparison 两侧相同；
5. T5 comparison correct item on wrong side；
6. T6 quiz distractor reuse；
7. T7 script cross-session similarity；
8. T8 practice fixed shape；
9. T9 typed starter；
10. T10 generic rectangle / semantic visual degradation；
11. T11 knowledge before taught；
12. T12 cumulative state / revisit；
13. T13 safe filename；
14. T14 duplicate student/package tree；
15. 额外回归：小型 PPTX 的 definition、diagram、screenshot、exercise、procedure 与 speaker notes / 图片引用，以及外部资料禁用、优先级和 provenance 冲突。

根 CI 增加 `whole-course-orchestrator` synthetic job，只运行架构测试、compile 和 installer dry-run，不运行真实 9 PPT。

## L. Gold Calibration

Phase 2 只把历史认可的 Data Structures Gold 与 UML 第一课 Gold 当作质量参考，检查：知识点颗粒度、单页具体性、真实视觉语义、明确例题、丰富层次和教师可指认证据；不复制 Gold 页数、文字、案例或内容。

本阶段已把 calibration 边界写入 Skill/测试说明，但未宣称 Gold 人工验收或真实课程质量通过。

## M. Git / Issue / PR

- 从 `origin/master` 创建 `feature/whole-course-orchestration`，没有污染已发布 Courseware / Practice 分支；
- 不修改 release tags 或历史报告；
- 提交按能力拆分：asset inventory、knowledge graph、session planner、visual planner、external research、practice planner、batch QA、packaging；
- 新 Issue/PR 应引用 `WHOLE_COURSE_FAILURE_BENCHMARK_V1`，不能 reopen 旧 Courseware / Practice release issue；
- PR 合入前仍需人工 architecture review；真实 blind retry 是后续阶段。

## N. Remaining Findings

- 真实用户 PPT 的结构化 asset coverage 尚未通过新 inventory 重跑验证；冻结 manifest 只证明旧外部证据可定位；
- 下游 Courseware / Practice 尚未消费新中间合同并产出真实整课包；
- visual gallery/contact sheet 当前是课程级审计索引，真实缩略图/HTML render 需后续下游生成；
- 外部互联网候选由 Agent/宿主提供，Python 层负责研究 gap、质量筛选、预算和 provenance，不在离线测试中伪造网页结果；
- 人工 Gold review、教师 pedagogical acceptance、Windows/Chrome 实际整课渲染均未执行。

## O. Status

`READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW`

这一状态只表示第一阶段的通用架构、合同、synthetic tests、失败基准冻结和可审计接口已准备评审；它不表示真实 UML whole-course generation 已通过。
