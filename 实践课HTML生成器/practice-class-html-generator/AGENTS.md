# 实践课 HTML 生成器 Agent 规则

先阅读 `简介.md`、`通用提示词.md` 和 `SKILL.md`。如果使用 Courseware 联动模式，还要读取上游 Courseware Contract 的实际 JSON；不要把本 Skill 的示例内容套到用户课程上。

## Agent / renderer 边界

- Agent 负责读取理论资料、判断学生起点、设计可完成的任务和创作 Practice Class Content Contract 1.0。
- Python 只负责合同校验、理论页关联 QA、HTML 布局、互动行为、starter 写入和精简输出 QA。
- 不要让模型直接拼接最终 HTML、CSS 或 JavaScript；不要把旧 WorkOrder 的 DOCX、评分册、模板指纹或复杂事务机制带入本 Skill。

## 内容门禁

- 先读取 `references/content-quality-gold-benchmark.md`。每套 90 分钟左右的实践包通常应有 7—12 个小任务（至少 5 core、1 optional、1 challenge）、5—8 个学习中心实验区、6—10 个学习指南小节和 5—10 个 foundation-kit 微专题；这些是内容质量底线，不是把某门课程的知识结构硬编码进 Skill。
- 每个 task 必须显式写出 `source_slide_ids`，并与其 `knowledge_link_ids` 推导出的理论页集合一致；core task 在联动模式下必须追溯到已存在的 `slide.id`。
- 编程或 SQL core 通常提供完整框架和 2—8 个真实需要学生修改的关键空位；建模、数据库和工具任务提供可编辑起点、示例、操作路径和可检查的完成条件。
- 同一个核心知识点至少使用两种不同互动/操作形态；学习中心必须包含动态过程、诊断/Debug、连续多题或场景挑战，不能退化为几张单选卡。
- 默认课堂验收是完成、运行/操作正确、能解释；除非用户明确要求，不写统一提交、截图、报告或收走产物。
- Gold Sample 只提供内容质量标尺；不要复制其中的数据结构知识、案例、代码或历史提交要求。
- Gold 标尺同时检查任务颗粒度、互动深度、资料密度、基础补给、自助路径和课堂节奏；入口索引只放摘要，详情页单列聚焦一个教学对象，自动化 PASS 不等于内容验收通过。
- 互动必须解释一个知识点或帮助完成一个任务；没有教学目的的动画不合格。
- 非编程课程的 foundation kit 不得自动出现 C 语言、代码模板或编程脚手架污染。

## 交付

至少生成四个学生入口索引 `student/student-task.html`、`student/learning-center.html`、`student/study-guide.html`、`student/foundation-kit.html`，并按合同生成 `student/tasks/`、`student/learning/`、`student/guides/`、`student/kit/` 详情页；另有 `teacher/teacher-guide.html`、`teacher/teacher-reference.html`、`teacher/references/`、`practice-content.json` 和 `qa-report.json`。如果合同提供 starter，则生成 `student/starter/`。交付前运行自身测试、内容/链接 QA 和真实浏览器 smoke；学生页面不得链接或泄露教师参考、原始 ID、合同版本或互动类型。
