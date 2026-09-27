# Lesson Content Contract 2.2

本文件仅定义 Content Contract 2.2 的历史输入与行为。Lesson Skill 2.3.1 默认生成 Content 2.3，但仍按本文件兼容读取 2.2；不会静默把 2.2 改写成 2.3。2.1/2.0 只作显式 `--legacy` 兼容输入。Lesson 模板仍为 v1.1.2，二进制和 SHA-256 不变。Teaching Exemplar Benchmark 1.0 在 Content 2.2 之外使用独立 sidecar。

## 课程边界

Content 2.2 历史行为：课程先完成一次中文 intake 和整门 outline，再生成逐课内容。确认后的课程名称、专业、授课对象、总课时、理论/实践课时和组织方式冻结在课程快照中，正文 Agent 不得改写。仅对 Content 2.2，Lesson DOCX 只承载理论课时：

```text
sum(lesson.hours) == delivery_plan.theory_hours
delivery_plan.theory_hours + delivery_plan.practice_hours == delivery_plan.total_hours
```

理论课次为 `ceil(theory_hours / default_hours)`，最后一课保留真实余数；1 学时不能被四舍五入成 2 学时。每个 Lesson 是理论 Lesson，`practice_hours=0`，`practice_task_ids=[]`。

## 时间与教学质量

九个实施阶段顺序固定。课前准备固定 10 分钟，七个课中阶段合计严格为 `lesson.hours × 45` 分钟，课后完善固定 15 分钟；课前和课后属于课外活动，不计入课堂学时。1 学时必须在内容、步骤、证据和任务复杂度上实质少于 2 学时。

每个阶段的学生证据或产出必须明确写在现有 `student_actions` 中；当证据需要对应学习目标时，也要在 `objective` 中写明可观察的对应关系。Content Contract 2.2 的 Schema 没有独立的 `student_evidence` 或 `success_criteria` 字段；这些字段只能作为未来契约升级的候选。完整正文、阶段内容、评价备注和反思由 Agent 提供；统一 Agent pedagogical review 负责专业准确性、目标—活动—证据、阶段连贯性、容量、递进和参考资料相关性。出现问题时 Agent 必须重写，Python 不追加教学 prose，也不以动作词、领域词、字符阈值或 n-gram 重叠替代 review。

## 资料边界

`course_materials.textbook`、lesson `resources`、`reference_pool` 和 `reference_research` 分离。教材、PPT、课件、案例/数据、任务单、设备、环境和内部教学资源不是 references；reference 必须是可阅读、查阅、引用或作为课程依据的文献/文档。书籍保留真实作者/编者、标题和出版社，年份可选且不得写“年份未知”；课程文档保留真实责任者、高校和平台/出版社。来源不足时少写，不填占位来源，不伪造书目信息；同一真实 reference 可以跨课复用，同课重复 ID 失败。

有联网能力时 Agent 在写入 reference pool 前检索真实公开来源。`no_verified_external_source` 仅表示没有核实到公开网络来源，不表示没有用户提供的资料；此状态下 reference pool 可以为空，也可以只含有真实出处的 `source_kind=provided` 正式资料。此状态下不得附带检索 query/source 记录，也不得放入 `verified_public`。真实公开来源必须绑定检索记录。当前兼容规则仍要求只要存在 `verified_public` references，每一课都至少关联一条 reference；Lesson Skill 2.3.0 Phase 1 不改变这项兼容门槛。

Reference 的国内/国外/未知数量和占比只作为描述性指标，不设 Content 2.2 未声明的国内来源占比门槛。

## Practice Task 单向 handoff

只有用户明确选择 `practice_work_orders=true` 才创建 Practice Task Contract 1.1。实践学时必须为正偶数；每个任务固定 2 学时，任务数等于 `practice_hours / 2`，由 Lesson Agent 在 Lesson QA/DOCX 完成后交给 WorkOrder Skill Agent。Practice Task 的课程基本信息逐字段继承 Lesson；`lesson_ids` 只是理论准备/前置关系。明确 false 时不生成 contract、handoff、WorkOrder 或实践侧文件。

若 WorkOrder Skill 不可用，必须保存 handoff 数据并提示：`实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`，不得由 Lesson Python subprocess 调用 WorkOrder Python 或伪造工单。

## 输出

只有 Content QA、模板 QA、输出 QA 和请求的真实 render 全部满足门禁，才可原子提交 DOCX。Content 2.2 在没有请求 render 时可得到 `qa_status=passed` 与 `production_status=structural_pass`，这只证明结构和确定性检查通过，不是生产就绪。含理论 Lesson 的课程只有在 `generate_lesson_plans.py --render` 成功、每课 PDF 均已保留且 SHA-256/页数校验通过后才是 `production_status=production_pass`；无 Lesson 产物时保持 `structural_pass`。缺少 renderer、render 失败或跳过输出校验都不能得到生产通过。standalone `validate_output.py --render` 只执行临时诊断 render，最多报告 `structural_pass`。render smoke 只证明 DOCX 能被真实转换并完成基础输出检查（not pagination，也不是人工 visual QA）；人工代表页检查另行记录，不能由 Python 冒充。

Lesson Skill 2.3.0 Phase 1 实现 Teaching Exemplar Benchmark、Authoring Set/Holdout Set 和独立 reviewer sidecar。显式 `student_evidence`、`analysis_basis`、`reflection_mode`、Content Contract 升级、Template 升级、逐课 reference relevance 与 Development Gold runner 均不属于 Phase 1。
