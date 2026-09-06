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

知识链接至少包含 `id`、`title`、`summary`、`source_slide_ids`、`student_can_do`。任务至少包含 `id`、`level`、`title`、`knowledge_link_ids`、`source_slide_ids`、`modality`、`overview`、`steps`、`acceptance`、`help_refs`、`estimated_minutes`。

`level` 只能是 `core`、`optional`、`challenge`，学生页面显示为“核心必做 / 有余力 / 提高挑战”。`modality` 可以是 `interactive`、`coding`、`modeling`、`database`、`tooling`、`analysis`、`mixed`。编程 core 通过 `starter_asset_ids` 绑定完整、可运行框架，并在 starter 中保留 2—8 个关键 TODO；非编程 core 通过 `scaffold` 写出明确起点和操作路径。若上游提供 `course_context`，Practice 必须逐字段保留其语言、工具、平台、软件、方言和约束，不得静默替换。

## 互动与学习资料

`learning_center` 中每项都要写 `knowledge_link_ids`、`task_ids`、`purpose` 和 `interaction`。renderer 支持选择/匹配、步骤/trace、分类、排序、诊断、预测、关系构建、状态模拟、策略比较、多题挑战和场景决策等内容驱动互动；互动必须有反馈、重试或推进，并服务具体知识点和任务。`study_guide` 按知识链接组织，`foundation_kit` 按课程动态列出基础缺口，不使用固定的 C 语言补给站字段。

## 教师指导

`teacher_guide` 应包括 `purpose`、`theory_bridge`、`timing`、`task_guidance`、`common_errors`、`pace_adjustments` 和 `closing_checks`。它服务于课堂控制和抽查，不要求写成逐字稿。

`teacher_reference.task_references` 必须覆盖每一个任务。每项至少包含 `task_id`、`title`、`source_slide_ids`、`reference_answer`、`key_steps`、`acceptable_variants`、`common_errors` 和 `acceptance_basis`；编程任务放完整可运行参考实现，SQL 任务放完整查询和结果形态，UML/建模任务放对象、关系、责任、消息和可接受变体。它只渲染到 `teacher/teacher-reference.html`，不进入学生目录。

## 输出隔离

renderer 生成 `student/` 和 `teacher/` 两棵目录。学生页的所有链接必须留在 `student/`，不能出现教师答案、教师参考或教师页面路径；教师页允许链接回学生页。starter 始终写入 `student/starter/`，没有声明 starter 资产时不创建空目录。
