# Practice Class Content Contract 1.0

Practice Contract 是 Agent 与 renderer 之间的内容边界。它描述一节实践课的教学设计，不描述 HTML/CSS，也不要求某一种课程或语言。

## 根字段

```json
{
  "contract_version": "1.0",
  "course_title": "课程名",
  "practice_title": "本次实践标题",
  "audience": "授课对象",
  "duration_minutes": 90,
  "course_context": {
    "course_name": "课程名",
    "audience": "授课对象",
    "language": "语言或建模记法",
    "tools": ["课程实际工具"],
    "platform": "平台",
    "software": "软件",
    "database_dialect": "数据库方言（如适用）",
    "framework": "框架或标准（如适用）",
    "other_constraints": ["课程约束"]
  },
  "source_courseware": {
    "mode": "courseware",
    "contract_version": "1.0",
    "chapter_title": "理论章节",
    "taught_slide_ids": ["s01", "s02"]
  },
  "knowledge_links": [],
  "tasks": [],
  "learning_center": [],
  "study_guide": [],
  "foundation_kit": [],
  "teacher_guide": {},
  "teacher_reference": {"task_references": []},
  "starter_assets": []
}
```

`source_courseware.mode` 为 `courseware` 时，CLI 必须收到 `--courseware-json`。`knowledge_links[].source_slide_ids` 和每个 task 自身的 `source_slide_ids` 必须来自该 Courseware Contract 的稳定 `slide.id`；任务的直接列表必须与其 `knowledge_link_ids` 推导出的理论页集合一致，core task 还必须有非空直接关联。`independent` 模式可以使用自定义理论页标识，但仍应在合同中写出本次理论范围。

## 知识链接与任务

知识链接至少包含 `id`、`title`、`summary`、`source_slide_ids`、`student_can_do`。任务至少包含 `id`、`level`、`title`、`knowledge_link_ids`、`source_slide_ids`、`modality`、`overview`、`steps`、`acceptance`、`help_refs`、`estimated_minutes`。质量门禁要求一套常规实践至少 7 个任务、5 个 core、1 个 optional、1 个 challenge，每个任务至少 3 个具体步骤。

`level` 只能是 `core`、`optional`、`challenge`，学生页面显示为“核心必做 / 有余力 / 提高挑战”。`modality` 可以是 `interactive`、`coding`、`modeling`、`database`、`tooling`、`analysis`、`mixed`。编程 core 通过 `starter_asset_ids` 绑定完整、可运行框架，并在 starter 中保留 2—8 个关键 TODO；非编程 core 通过 `scaffold` 写出明确起点和操作路径。若上游提供 `course_context`，Practice 必须逐字段保留其语言、工具、平台、软件、方言和约束，不得静默替换。

## 互动与学习资料

`learning_center` 中每项都要写 `knowledge_link_ids`、`task_ids`、`purpose` 和 `interaction`。常规实践应有 5—8 个实验区、至少 4 种互动类型，并包含动态过程、诊断/Debug、连续多题或场景挑战。合同里的 `interaction.type` 是教学语义，不等于某个 CSS 组件；renderer 必须把它映射为真实可操作的 renderer family，例如 choice、step、classify、reorder、state-simulator、multi-question 等。每个互动必须有反馈、重试或推进，并服务具体知识点和任务。可以提供 `success_feedback`、`retry_feedback`、`completion_feedback` 作为课程内容反馈；未提供时 renderer 使用中性反馈，不得在 renderer 中硬编码 UML、SQL、C 或某个领域的正确答案。

状态模拟器的每个 `round` 必须写 `left`、`right`、`mid`、`status` 和 `feedback`。`status` 只能是 `continue`、`found` 或 `not-found`：继续时提供下一状态，终止时不得提供下一状态，且终止轮必须是最后一轮。多题互动应能逐题推进，排序互动应提供真实的移动操作，不能用一个“选择顺序”的下拉框冒充排序。`study_guide` 应有 6—10 个 task 关联小节，`foundation_kit` 应有 5—10 个按课程动态列出的基础微专题，不使用固定的 C 语言补给站字段。

## 教师指导

`teacher_guide` 应包括 `purpose`、`theory_bridge`、`timing`、`task_guidance`、`common_errors`、`pace_adjustments` 和 `closing_checks`。它服务于课堂控制和抽查，不要求写成逐字稿。默认完成标准是现场完成、运行/操作正确和能解释，不把统一提交写成默认门槛。

`teacher_reference.task_references` 必须覆盖每一个任务。每项至少包含 `task_id`、`title`、`source_slide_ids`、`reference_answer`、`key_steps`、`acceptable_variants`、`common_errors` 和 `acceptance_basis`；编程任务放完整可运行参考实现，SQL 任务放完整查询和结果形态，UML/建模任务放对象、关系、责任、消息和可接受变体。它只渲染到 `teacher/teacher-reference.html`，不进入学生目录。

## 输出信息架构与学生可见边界

renderer 固定生成四个学生入口索引：`student-task.html`、`learning-center.html`、`study-guide.html` 和 `foundation-kit.html`。入口只呈现摘要卡；任务、互动、学习小节和补给微专题分别生成到 `student/tasks/`、`student/learning/`、`student/guides/` 和 `student/kit/` 的详情页。教师参考同样使用 `teacher-reference.html` 索引加 `teacher/references/<task-id>.html` 详情页。详情页只承载一个焦点，正文应保持约 720—920px 的单列阅读宽度，并提供返回索引、上一项、下一项、标题、预计时间和帮助入口。

学生可见文字不得出现 `contract_version`、原始 task/guide/kit/slide ID、`interaction.type` 或 renderer family；这些值可以保留在机器可读属性中供 QA 使用。学生页的链接必须留在 `student/`，不得链接教师页。离线输出是一个可导航的站点包，不承诺所有内容在一个文件内展开。

## 输出隔离

renderer 生成 `student/` 和 `teacher/` 两棵目录。学生页的所有链接必须留在 `student/`，不能出现教师答案、教师参考或教师页面路径；教师页允许链接回学生页。starter 始终写入 `student/starter/`，没有声明 starter 资产时不创建空目录。
