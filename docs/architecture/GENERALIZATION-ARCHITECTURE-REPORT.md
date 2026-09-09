# 双 Skill Generalization Audit & Architecture Report

日期：2026-09-07
范围：`HTML课件生成器/courseware-html-generator` 与 `实践课HTML生成器/practice-class-html-generator`
结论级别：技术架构可进入 PR 审核；Gold 内容层仍保留人工并排验收，不把自动化绿灯当作可直接授课结论。

## A. Baseline

| 项目 | 证据 |
|---|---|
| repo root | `F:\work\codex-workskills-practice-class` |
| origin/master | `49bdc9f8237d686b0834a40a7620f2713d67adc5` |
| local master | `7af94cd48ccae8c8c2e3ec439cf78c8d9c6e5447` |
| Courseware 基线 | `feature/html-courseware-generator` @ `46496bb7951b945b0fe72f8815a188366d64a42c` |
| 本次分支 | `feature/practice-class-html-generator` |
| 整改开始 HEAD | `cea4689246499e8b76f37712a1d942b628b69829` |
| 专用 worktree | `F:\work\codex-workskills-practice-class` |
| PR #24 | OPEN、非 Draft；base=`feature/html-courseware-generator`；检查时 `MERGEABLE` |
| PR #20 | OPEN、base=`master`；检查时 `CONFLICTING` |

本地 master 与 origin/master 不一致已明确记录，没有 reset、rebase、merge 或静默修复。本轮没有修改 master，没有合并 PR #20，也没有新增或执行 Ubuntu 专用流程。三个已知案例从本轮起只作为 regression fixtures；五门 holdout 在首次生成前通过 `holdouts/SOURCE-FREEZE.json` 冻结。

## B. Courseware Architecture

### DONE：Contract 1.1 与 migration

- 根级时间改为 `session_minutes / prepared_minutes / core_minutes / extension_minutes`；旧 `content_reserve_minutes` 只在迁移入口读取。
- 页级使用 `lecture_minutes / activity_minutes / suggested_minutes`，并验证 `suggested_minutes = lecture_minutes + activity_minutes` 以及页级规划量与 `prepared_minutes` 的关系，不能再让 `120 → 18` 静默 PASS。
- `normalize_content()` 统一把 1.0 输入迁移到内部 1.1 模型，保留稳定 `slide.id`；新 renderer/validator 不维护两套生产分支。
- 新增 `learning_units`、`canonical_facts`、`learning_unit_ids`、`canonical_fact_ids` 与 `teaching_intent`。Practice 只能消费这些已声明的理论范围，Courseware 不反向依赖 Practice。

### DONE：Pedagogical 与结构 QA 分层

`scripts/pedagogical_review.py` 独立检查时间、讲解意图、图/表/代码解释、密度、事实/来源和学生页元数据；`validate_courseware.py` 保留确定性的合同、离线资源、HTML 与输出完整性检查。报告分别保留 Contract、Pedagogical、Browser 三种结论。

### DONE：本地图片与离线渲染

图片资产检查本地路径、MIME、白名单和尺寸，渲染为 data URI；不允许网络 URL、CDN、外部字体或隐式请求。

### DONE：动态 Browser/Overflow QA

Courseware smoke 根据页面实际发现普通内容块和互动控件，不再假设第一页有 `info-card/svg/code`，也不按固定页码寻找 quiz/stepper。覆盖 `file://`、导航、wheel 单页移动、projection、答案/stepper 等当前实际控件；三种 viewport 均检查 document/slide overflow、SVG/表格/代码可见性。DS 发现的真实 SVG 溢出已通过通用 CSS 尺寸约束修复，而不是按 fixture 加 selector。

### DONE：Courseware Gold Benchmark

新增 [courseware-content-gold-benchmark.md](../../HTML课件生成器/courseware-html-generator/references/courseware-content-gold-benchmark.md)，明确真实备课量、讲解结构、页面密度、来源、离线资产和 PASS/DEGRADED/FAIL 边界。

### PARTIAL：Slide Planner/Density Planner

现有 Pedagogical Review 会依据段落、列表、表格、代码、图示和时间产生密度警告/失败条件，Browser QA 会硬性拦截明显 overflow；本轮没有实现自动拆页或自动改写内容的 planner。拆页仍由 Agent 按 Gold Benchmark 设计，避免 renderer 擅自改变教学语义。

## C. Practice Architecture

### DONE：Editable Gap / Reference Version / Leakage

- `editable_gaps[].marker` 只要求真实出现在学生 starter；`replacement` 是 teacher/QA canonical answer，不要求也不允许出现在学生 TODO 行。
- `apply_reference_gaps.py` 从 Student Starter + replacement 生成教师 reference，再执行可行的语言/文件结构检查。
- 学生分发目录是 `student-package/`：只有学生页面、无答案合同副本和 starter；教师内容、reference、完整合同和 QA 在 `teacher-package/`。validator 会检查 teacher reference、replacement、canonical 字段和 gap 泄漏。

### DONE：能力与脚手架模型

任务同时声明 `task_kind`、`artifact_kind`、`capabilities`、`scaffold_level`，不再从 `modality` 字符串猜课程形态。编程 core 以完整框架 + 真实关键空位为主，非编程任务以可编辑模型、表格、SQL/工具起点和结果验收提供等价脚手架。

### DONE：通用状态与 reference visual

`visualization.kind` 支持 `sequence-range / timeline / table-state / state-machine / queue / graph-path` 等；无专用 adapter 时回退通用状态表，不把所有状态课程画成数组。教师参考使用显式 `reference_visual.kind`，UML 只是一个 adapter，不是全局数据结构。

### DONE：互动与自助路径

互动服务具体知识点/任务，包含选择、步骤、分类、排序、状态推演、连续诊断和多题/参数比较等 renderer family。每个 core 有至少一个有效 support path，但不强迫每个任务都制造网页小游戏；学习指南、foundation kit、starter 和结构化步骤都可以成为自助路径。

## D. Cross-Skill Linkage

- Practice 首选消费 Courseware Content Contract 1.1；知识点和任务同时保存 `source_slide_ids` 与 `learning_unit_ids`，并校验 slide 真实存在、slide 属于对应 learning unit。
- 跨材料关键规则、术语、固定数据、关系和工具链通过 `canonical_fact_ids` 保持单一 truth；任务验收、学习中心、study guide、starter reference、teacher reference 使用同一事实集合。
- validator 拦截不存在的 learning unit、未讲 `not_yet_taught` 进入 core、source slide 不属于对应理论单元以及 context 不一致。

## E. Execution status（DONE / PARTIAL / BLOCKED）

| 阶段/整改项 | 状态 | 说明 |
|---|---|---|
| R0 baseline / PR / worktree | DONE | SHA、分支、base/head、mergeable 状态已留证；master 未修复 |
| Courseware time / semantic contract | DONE | 1.1 migration、learning units、canonical facts、stable slide IDs |
| Courseware pedagogical review | DONE | 独立 review 与确定性 validator 分层 |
| Courseware browser / overflow | DONE | 动态发现、三 viewport、真实 regression smoke 全通过 |
| Courseware density planner | PARTIAL | 有密度 review 和 overflow gate，未自动拆页 |
| Practice editable gap / reference / leakage | DONE | 学生 starter 不含 replacement，reference 从 gap 生成/检查 |
| Practice capabilities / visualization | DONE | 通用能力、脚手架和状态/reference visual adapter |
| Student/Teacher package isolation | DONE | `student-package` 可单独分发，teacher-only 内容隔离 |
| DS/UML/DB migration regression | DONE | 三套实际生成、合同/HTML/链接/浏览器回归通过 |
| Five holdout freeze / first-pass / second-pass | DONE | 五个新课程，首次与二次输出均保留 |
| Gold Sample provenance | DONE | 只保存抽象 benchmark 与 SHA，不复制 Gold HTML/C/数据结构内容 |
| MySQL live execution | PARTIAL | DB reference 结构/语义检查通过；本机无连接/数据库，SQL 执行明确 skip |
| Final content acceptance | PARTIAL | 自动证据达到 PR 审核门槛，仍待教师把三套输出与 Gold 并排验收 |

没有 BLOCKED 项；PARTIAL 项没有伪装成 DONE。
