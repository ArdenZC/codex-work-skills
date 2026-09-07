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

知识链接至少包含 `id`、`title`、`summary`、`source_slide_ids`、`student_can_do`。任务至少包含 `id`、`level`、`title`、`knowledge_link_ids`、`source_slide_ids`、`modality`、`overview`、`steps`、`acceptance`、`help_refs`、`estimated_minutes`；合同结构最低允许 1 个任务、1 个步骤，内容质量建议再根据时长给出。90 分钟左右的 Gold 目标通常是 7—12 个任务、约 5 个 core、1 个 optional、1 个 challenge、每个任务至少 3 个具体步骤，但这些数量由 validator 作为 quality recommendation/warning 检查，不能写死成跨课程 schema 门槛。

`level` 只能是 `core`、`optional`、`challenge`，学生页面显示为“核心必做 / 有余力 / 提高挑战”。`modality` 可以是 `interactive`、`coding`、`modeling`、`database`、`tooling`、`analysis`、`mixed`。编程 core 通常通过 `starter_asset_ids` 绑定完整、可运行框架，并在 starter 中保留 2—8 个关键 TODO；非编程 core 通过 `scaffold` 写出明确起点和操作路径。若上游提供 `course_context`，Practice 必须逐字段保留其语言、工具、平台、软件、方言和约束，不得静默替换。

## 互动与学习资料

`learning_center` 中每项都要写 `knowledge_link_ids`、`task_ids`、`purpose` 和 `interaction`。90 分钟左右的 Gold 目标通常为 5—8 个实验区、至少 4 种互动类型，并包含动态过程、诊断/Debug、连续多题或场景挑战；短课可以按主题缩放。合同里的 `interaction.type` 是教学语义，不等于某个 CSS 组件；renderer 必须把它映射为真实可操作的 renderer family，例如 choice、step、classify、reorder、state-simulator、multi-question 等。每个互动必须有反馈、重试或推进，并服务具体知识点和任务。可以提供 `success_feedback`、`retry_feedback`、`completion_feedback` 作为课程内容反馈；未提供时 renderer 使用中性反馈，不得在 renderer 中硬编码 UML、SQL、C 或某个领域的正确答案。互动数量达到 Gold 建议值不等于互动质量达标：至少两处应有状态变化或多步推进，至少一处应连续处理多个诊断案例，参数变化要立即改变比较结果。

状态模拟器使用通用的 `state_fields`、`state` 和 `rounds`：每个 round 至少提供 `given`、`expected`、`status` 和 `feedback`，可选 `observation` 与 `next_expected`；`status=continue` 时必须有下一状态，终止时不得提供下一状态且终止轮必须是最后一轮。字段可以是边界、对象、消息、记录、工具状态或课程定义的其他过程变量，不能把 `left/right/mid` 写成跨课程合同。需要把对象状态可视化时，可选 `state_visual` 提供 `items` 与字段映射；它只负责把当前候选范围、焦点和检查后的观察结果画出来，不改变原有状态填写与终止规则。`diagnose` 可选 `diagnostic_cases` 连续呈现多个“现象判断 + 最小修复”案例；`compare-strategies` 可选 `comparison` 让学生切换参数并看到各系列数值/解释变化。多题互动应能逐题推进，排序互动应提供真实的移动操作，不能用一个“选择顺序”的下拉框冒充排序。`study_guide` 与 `foundation_kit` 的数量由时长/课程主题决定，通常分别以 6—10 个任务关联小节和 5—10 个动态微专题为 Gold 参考，不使用固定的 C 语言补给站字段。

## 教师指导

`teacher_guide` 应包括 `purpose`、`theory_bridge`、`timing`、`task_guidance`、`common_errors`、`pace_adjustments` 和 `closing_checks`。它服务于课堂控制和抽查，不要求写成逐字稿。默认完成标准是现场完成、运行/操作正确和能解释，不把统一提交写成默认门槛。

`teacher_reference.task_references` 必须覆盖每一个任务。每项至少包含 `task_id`、`title`、`source_slide_ids`、`reference_answer`、`key_steps`、`acceptable_variants`、`common_errors` 和 `acceptance_basis`；编程任务放完整可运行参考实现，SQL 任务放完整查询和结果形态，UML/建模任务放对象、关系、责任、消息和可接受变体。它只渲染到 `teacher/teacher-reference.html`，不进入学生目录。

## 输出信息架构与学生可见边界

renderer 固定生成四个学生模块页：`student-task.html`、`learning-center.html`、`study-guide.html` 和 `foundation-kit.html`；任务、互动、学习小节和补给微专题在各自模块页内渲染成 pane，由导航和 hash 切换，任一时刻只显示一个 pane。教师侧固定生成 `teacher-guide.html` 与 `teacher-reference.html` 两个模块页，教师观察点和逐任务参考成果同样在 pane 内切换，不再生成按 task 拆分的详情 HTML。每个 pane 只承载一个焦点，正文应保持可读的单列阅读宽度，并提供返回目录、上一项、下一项、标题、预计时间和帮助入口。

学生可见文字不得出现 `contract_version`、原始 task/guide/kit/slide ID、`interaction.type` 或 renderer family；这些值可以保留在机器可读属性中供 QA 使用。学生页的链接必须留在 `student/`，不得链接教师页。离线输出是六个可导航的模块页加 JSON/starter 资源；不承诺所有内容在一个文件内展开，但也不把一个教学对象拆成额外的动态 HTML 文件。

## 输出隔离

renderer 生成 `student/` 和 `teacher/` 两棵目录。学生页的所有链接必须留在 `student/`，不能出现教师答案、教师参考或教师页面路径；教师页允许链接回学生页。starter 始终写入 `student/starter/`，没有声明 starter 资产时不创建空目录。
