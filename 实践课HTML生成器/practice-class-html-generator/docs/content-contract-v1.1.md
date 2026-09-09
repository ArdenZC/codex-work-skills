# Practice Class Content Contract 1.1

`1.1` 是通用实践课 Skill 的生产目标。它直接消费 Courseware Content Contract 1.1，或者在 `independent` 模式下明确写出本次理论边界。它描述学生活动、帮助、互动和教师参考成果，不描述 HTML/CSS，也不复用旧 WorkOrder 的阶段、模板指纹或事务架构。

## Blueprint-first 约束

正式生成先产生公开 Practice Blueprint。Blueprint 至少包含 `practice_goal`、`duration_minutes`、`available_learning_units`、`practiceable_abilities`、`forbidden_not_yet_taught`、`activity_affordances`、`task_plan`、`scaffold_strategy`、`tool_workflow`、`support_strategy`、`assessment_strategy` 和 `coverage_matrix`。矩阵每行必须说明 Ability、Learning Unit、Canonical Facts、Allowed depth、Suitable modality、Starter need 和 Scaffold；不得包含私有推理。

任务和互动的数量不是 contract 约束，也不是 Gold 分数来源。challenge 可以为零；较少的 core/optional 组合或没有 Learning Center，只要理论回链、起点、支架、自助资料、验收和参考成果完整，仍然合法。

## 理论关联

`source_courseware.mode=courseware` 时必须传入上游合同。`taught_slide_ids`、每个 `knowledge_links[].source_slide_ids` 和每个 task 的 `source_slide_ids` 必须来自真实稳定的 `slide.id`；task 的直接集合必须等于其知识链接推导出的页集合。`learning_unit_ids` 和 `canonical_fact_ids` 进一步证明任务使用了这些页讲过的语义。Practice 复用 Courseware fact 时必须通过 Source Truth usage registry，不能覆盖上游事实值；core task 不能触碰上游 `not_yet_taught` 边界。

## 任务能力模型

任务声明 `core / optional / challenge`、`task_kind`、`artifact_kind`、`capabilities` 和 `scaffold_level`。`estimated_minutes` 可用 `time_breakdown[{step,minutes}]` 解释组成；Core 优先提供，Optional/Challenge 不强制。形式由 affordance 选择，不按课程名分支：

- `implementation`/`code_editing`：真实 starter、editable gap 或明确 edit target、验收和帮助；starter 不能包含完整 replacement。
- `debugging`/`diagnosis`：`symptom`、`faulty_artifact`、`expected_behavior`、`diagnosis_target`、`repair_target` 和验收。
- `modeling`/`model_editing`：可编辑模型、`required_edit`、`modeling_constraints` 和参考成果。
- `tooling`/`tool_operation`：`tool`、`starting_state`、具体 `operations` 和 `expected_observable_result`。
- `experiment`：`variable`、`control`、`operation`、`observation` 和 `expected_reasoning`。

## 互动合同

`learning_center` 可为空；非空互动必须服务明确知识点/任务，并提供即时反馈、重试或推进。状态模拟器使用课程自定义的 `state_fields`，排序从错误顺序开始，分类反馈检查前隐藏，诊断支持按案例推进，终止状态不泄露下一步答案。互动族由课程 affordance 选择，不设置数量配额。

## 学生包与教师包

renderer 生成四个学生模块和两个教师模块，并提供学生包、教师包、合同和 QA。学生包只含安全 starter 和去除教师答案、replacement 元数据、canonical answers 的副本；教师包提供逐任务完整参考成果。学生页不暴露内部 ID、合同版本、教师路径或答案。

## 生成与验收

流程固定为 Blueprint → Draft Contract → Structural Validation → Pedagogical Review → 最多两轮 Automatic Contract Repair → Revalidation → Render → Browser QA → Final Package。自动化结构/浏览器 PASS 不等于教师内容验收通过；最终还需对照原始资料检查任务颗粒度、互动深度、自助路径、课堂节奏和参考成果。
