# Practice Class Content Contract 1.1

`1.1` 是通用实践课 Skill 的生产目标。它直接消费 Courseware Content Contract 1.1，或者在 `independent` 模式下明确写出本次理论边界。它描述学生要完成的活动、帮助、互动和教师参考成果，不描述 HTML/CSS，也不复用旧 WorkOrder 的阶段、Hardening、模板指纹或事务架构。

## 理论关联

`source_courseware.mode=courseware` 时必须传入上游合同。`taught_slide_ids`、每个 `knowledge_links[].source_slide_ids` 和每个 task 的 `source_slide_ids` 必须来自真实稳定的 `slide.id`；task 的直接集合必须等于其知识链接推导出的页集合。`learning_unit_ids` 和 `canonical_fact_ids` 进一步证明任务确实使用了这些页讲过的语义。core task 不能触碰上游 `not_yet_taught` 边界。

## 任务能力模型

任务除了 `core / optional / challenge` 层级，还声明 `task_kind`、`artifact_kind`、`capabilities` 和 `scaffold_level`。能力是课程无关的，例如 `code_editing`、`model_editing`、`query_execution`、`diagnosis`、`state_tracking`、`visualization`、`explanation` 和 `scenario_reasoning`。Agent 根据课程选择能力；foundation-kit、starter、参考成果和互动必须响应能力，而不是依据课程名分支。

编程/SQL core 通常提供完整上下文和 2—8 个真实可改的关键空位。每个空位必须有学生说明和教师 replacement，学生页只收到安全 starter。建模、工具、工作表和场景任务要给等价的可编辑起点、对象/字段/关系槽、操作顺序或验收表，不能把“读一段说明”冒充实践。

## 互动合同

`learning_center` 的 `interaction.type` 是教学语义，renderer 把它映射为通用 family。`state-simulator` 使用课程自定义的 `state_fields`、`given`、`expected`、`next_expected` 和终止状态；字段不能写死成 left/right/mid。`visualization.kind` 可以是 sequence-range、timeline、table-state、state-machine、queue、graph-path、comparison 或 table。只有 `sequence-range` 才使用范围/焦点字段，其余可用状态值表呈现。

互动必须有即时反馈、重试或推进，并服务明确知识点/任务。分类反馈默认隐藏到检查后；排序必须从错误顺序开始；状态未知字段加载为空，不能把答案预填进输入框；终止轮不能暴露下一轮。诊断应能连续处理多个现象，连续题组应逐题推进。互动数量是质量参考，不是跨课程固定 schema。

## 学生包与教师包

renderer 同时生成便于本地调试的根目录、`student-package/` 和 `teacher-package/`：

- 学生包只包含四个学生页、可取得的 `starter/` 和去除教师答案/替换元数据的安全合同副本；学生页链接不能离开 `student/`；
- 教师包包含两个教师页、完整合同、逐任务参考成果和自动生成的 reference 目录；
- `teacher-guide.html` 负责节奏、巡视和追问，`teacher-reference.html` 负责完整代码/SQL/模型/结果和可接受变体；
- 安全包 manifest 明确 `teacher_answers_included=false`、`replacement_metadata_included=false`、`canonical_answers_included=false`。

## Gold 内容审查

`references/content-quality-gold-benchmark.md` 和冻结的 Gold Sample 只提供任务颗粒度、互动深度、资料密度、基础补给、自助路径和课堂节奏的标尺，不提供课程知识模板。90 分钟课通常可参考 7—12 个活动、5—8 个互动区、6—10 个学习资料小节和 5—10 个基础微专题，但 validator 只输出 duration-aware recommendation。自动化结构、浏览器和教学完整性 QA 必须分开，PASS 不等于内容层验收。
