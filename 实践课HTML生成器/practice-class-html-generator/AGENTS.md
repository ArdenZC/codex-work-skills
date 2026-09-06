# 实践课 HTML 生成器 Agent 规则

先阅读 `简介.md`、`通用提示词.md` 和 `SKILL.md`。如果使用 Courseware 联动模式，还要读取上游 Courseware Contract 的实际 JSON；不要把本 Skill 的示例内容套到用户课程上。

## Agent / renderer 边界

- Agent 负责读取理论资料、判断学生起点、设计可完成的任务和创作 Practice Class Content Contract 1.0。
- Python 只负责合同校验、理论页关联 QA、HTML 布局、互动行为、starter 写入和精简输出 QA。
- 不要让模型直接拼接最终 HTML、CSS 或 JavaScript；不要把旧 WorkOrder 的 DOCX、评分册、模板指纹或复杂事务机制带入本 Skill。

## 内容门禁

- 每个 task 必须显式写出 `source_slide_ids`，并与其 `knowledge_link_ids` 推导出的理论页集合一致；core task 在联动模式下必须追溯到已存在的 `slide.id`。
- 编程 core 通常提供完整框架和 2—8 个关键 TODO；建模、数据库和工具任务提供明确起点、示例、操作路径和可检查的完成条件。
- 互动必须解释一个知识点或帮助完成一个任务；没有教学目的的动画不合格。
- 非编程课程的 foundation kit 不得自动出现 C 语言、代码模板或编程脚手架污染。

## 交付

至少生成 `student/student-task.html`、`student/learning-center.html`、`student/study-guide.html`、`student/foundation-kit.html`、`teacher/teacher-guide.html`、`teacher/teacher-reference.html`、`practice-content.json` 和 `qa-report.json`。如果合同提供 starter，则生成 `student/starter/`。交付前运行自身测试、内容/链接 QA 和真实浏览器 smoke；学生页面不得链接或泄露教师参考。
