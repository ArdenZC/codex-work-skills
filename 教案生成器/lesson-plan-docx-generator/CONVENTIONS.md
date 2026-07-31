# Aider 约定

先读取 AGENTS.md、SKILL.md 和 通用提示词.md，再处理教案任务。

- 将用户资料整理为 tasks.json，使用 scripts/generate_lesson_plans.py 生成 DOCX。
- 课程单元按“项目一、项目二……”组织，任务名写成具体动作或成果。
- 优先使用 assets/lesson-plan-template.docx，保持 30 行主表和原有格式。
- 生成后检查文件数量、总课时、课程名称、评价表和评分总和。
- 资料不足时提醒用户需要的文件，但不要因为缺少资料而停止；按课程特点推断项目化教学结构。