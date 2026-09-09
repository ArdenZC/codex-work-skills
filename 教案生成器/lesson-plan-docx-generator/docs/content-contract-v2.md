# Lesson Content Contract 2.2

Lesson Skill 2.2.3 的当前生产输入是完整的 Lesson Content Contract 2.2。2.1/2.0 只作为显式兼容输入；命令行必须明确传入 `--legacy`，兼容输入不会被静默改写为 2.2。Lesson 模板仍为 v1.1.2，二进制和 SHA-256 不变。

## 课程边界

课程先完成一次中文 intake 和整门 outline，再生成逐课内容。确认后的课程名称、专业、授课对象、总课时、理论/实践课时和组织方式冻结在课程快照中，正文 Agent 不得改写。Lesson DOCX 只承载理论课时：

```text
sum(lesson.hours) == delivery_plan.theory_hours
delivery_plan.theory_hours + delivery_plan.practice_hours == delivery_plan.total_hours
```

理论课次为 `ceil(theory_hours / default_hours)`，最后一课保留真实余数；1 学时不能被四舍五入成 2 学时。每个 Lesson 是理论 Lesson，`practice_hours=0`，`practice_task_ids=[]`。

## 时间与教学质量

九个实施阶段顺序固定。课前准备固定 10 分钟，七个课中阶段合计严格为 `lesson.hours × 45` 分钟，课后完善固定 15 分钟；课前和课后属于课外活动，不计入课堂学时。1 学时必须在内容、步骤、证据和任务复杂度上实质少于 2 学时。

每个阶段形成 `content → teacher_actions → student_actions → student evidence/output → objective` 的语义链。完整正文、阶段内容、评价备注和反思由 Agent 提供；统一 Agent pedagogical review 负责专业准确性、目标—活动—证据、阶段连贯性、容量、递进和参考资料相关性。出现问题时 Agent 必须重写，Python 不追加教学 prose，也不以动作词、领域词、字符阈值或 n-gram 重叠替代 review。

## 资料边界

`course_materials.textbook`、lesson `resources`、`reference_pool` 和 `reference_research` 分离。教材、PPT、课件、案例/数据、任务单、设备、环境和内部教学资源不是 references；reference 必须是可阅读、查阅、引用或作为课程依据的文献/文档。书籍保留真实作者/编者、标题和出版社，年份可选且不得写“年份未知”；课程文档保留真实责任者、高校和平台/出版社。来源不足时少写，不填占位来源，不伪造书目信息；同一真实 reference 可以跨课复用，同课重复 ID 失败。

有联网能力时 Agent 在写入 reference pool 前检索真实公开来源；无可靠外部来源时明确记录 `no_verified_external_source`，reference pool 可为空，不能把检索要求变成 Python 的内容判断。

## Practice Task 单向 handoff

只有用户明确选择 `practice_work_orders=true` 才创建 Practice Task Contract 1.1。实践学时必须为正偶数；每个任务固定 2 学时，任务数等于 `practice_hours / 2`，由 Lesson Agent 在 Lesson QA/DOCX 完成后交给 WorkOrder Skill Agent。Practice Task 的课程基本信息逐字段继承 Lesson；`lesson_ids` 只是理论准备/前置关系。明确 false 时不生成 contract、handoff、WorkOrder 或实践侧文件。

若 WorkOrder Skill 不可用，必须保存 handoff 数据并提示：`实践任务工单生成器当前不可用，已保存实践任务数据文件，可在工单生成器可用后继续生成。`，不得由 Lesson Python subprocess 调用 WorkOrder Python 或伪造工单。

## 输出

只有 Content QA、模板 QA、输出 QA 和请求的真实 render 全部满足门禁，才可原子提交 DOCX。render smoke 只证明 DOCX 能被真实转换并完成基础输出检查（not pagination，也不是人工 visual QA）；render 未执行或失败时不得标记 Production PASS；人工代表页检查另行记录，不能由 Python 冒充。
