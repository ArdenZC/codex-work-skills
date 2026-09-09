# 实践课 HTML 生成器 Agent 规则

先阅读 `简介.md`、`通用提示词.md` 和 `SKILL.md`。如果使用 Courseware 联动模式，还要读取上游 Courseware Contract 的实际 JSON；不要把本 Skill 的示例内容套到用户课程上。

## Agent / renderer 边界

- Agent 负责读取理论资料、判断学生起点、设计可完成的任务和创作 Practice Class Content Contract 1.1；旧 1.0 只能通过迁移读取。
- Python 只负责合同校验、理论页关联 QA、HTML 布局、互动行为、starter 写入和精简输出 QA；内容质量评分与结构 QA 分离。
- 不要让模型直接拼接最终 HTML、CSS 或 JavaScript；不要把旧 WorkOrder 的 DOCX、评分册、模板指纹或复杂事务机制带入本 Skill。

## 内容门禁

- 先读 `references/content-quality-gold-benchmark.md`，然后从原始理论边界写 Practice Blueprint 和 coverage matrix。任务、层级、互动、Learning Center、study guide 和 foundation kit 的数量都由能力覆盖、工具 affordance、时长和学生可完成性决定；数量既不是固定门槛，也不产生分数。
- 每个 task 必须显式写出 `source_slide_ids`，并与其 `knowledge_link_ids` 推导出的理论页集合一致；core task 在联动模式下必须追溯到已存在的 `slide.id`，且不能进入 `not_yet_taught`。
- implementation/code_editing、debugging/diagnosis、modeling/model_editing、tooling/tool_operation 和 experiment 任务分别满足合同声明的起点、症状、模型、工具和变量字段。
- 互动必须解释一个知识点或帮助完成一个任务；只有存在即时反馈、状态变化、连续诊断、多步操作或场景判断时才加入 Learning Center。它可以为空，starter + study guide 仍可构成合法核心路径。
- 默认课堂验收是完成、运行/操作正确、能解释；除非用户明确要求，不写统一提交、截图、报告或收走产物。
- Gold Sample 只提供内容质量标尺；不要复制其中的数据结构知识、案例、代码或历史提交要求。
- Gold 标尺检查任务颗粒度、互动深度、资料密度、基础补给、自助路径和课堂节奏；四个学生模块和两个教师模块在模块内使用 pane，自动化 PASS 不等于内容验收通过。
- 非编程课程的 foundation kit 不得自动出现 C 语言、代码模板或编程脚手架污染。

## 交付

至少生成四个学生模块页 `student/student-task.html`、`student/learning-center.html`、`student/study-guide.html`、`student/foundation-kit.html` 和两个教师模块页 `teacher/teacher-guide.html`、`teacher/teacher-reference.html`；合同数组在各模块内生成 pane，不再生成 `student/tasks/`、`student/learning/`、`student/guides/`、`student/kit/` 或 `teacher/references/` 详情目录，另有 `practice-content.json` 和 `qa-report.json`。如果合同提供 starter，则生成 `student/starter/`。交付前运行自身测试、内容/链接 QA 和真实浏览器 smoke；学生页面不得链接或泄露教师参考、原始 ID、合同版本或互动类型。
