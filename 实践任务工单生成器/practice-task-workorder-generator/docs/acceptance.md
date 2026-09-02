# Phase 2.1 Hardening 验收范围

## 必过检查

- canonical Practice Task schema、WorkOrder Content V1 schema 和 handoff 校验/保真通过；`--practice-task-json` 不直接生成正式 Content 或 DOCX；
- Practice Task → WorkOrder 的 `practice_task_id`、`lesson_ids`、`practice_hours`、标题意图、交付物、验收、工具/材料和安全/合规通过 Cross-Artifact QA；
- 任务可执行，主要步骤含动作和对象，所有 substantive deliverables 均有可观察验收覆盖，跨专业明显污染被拒绝；
- 课堂考勤为 10 分，任务项合计 90 分，总分 100，支持 1–5 个任务项；
- 生成 DOCX 可打开，保留三张主体表、动态任务行、学生/教师评价和 20/30/50 rubric；
- 学生任务结果区为空，未写入教师答案；
- canonical WorkOrder template SHA-256 为 `F20308238D07C7BFB9B1F9D2A25591D6EE09F13EC5855B7C57FA914CEE9457BD`，不修改原模板版式；
- 安装器、依赖 doctor、五类适配器和 WorkOrder CI job 通过对应合同测试；成功替换默认清理 backup，显式 `--keep-backup` 才保留。

## E2E

用小型 8 学时软件和非 IT 课程分别走 Lesson Content 2.1 → Practice Task Contract V1 → WorkOrder → Cross-Artifact QA → DOCX。提交的 synthetic fixture 与一次真实 Agent-authored 小型验收必须在报告中区分；本阶段不生成完整 64 学时课程。

## 明确边界

Phase 2.1 不修改 Lesson 或 WorkOrder canonical Word template，不新增模板版本，不发布 GitHub Release，不开发教师答案版，不做成绩册回写，也不进入 Phase 3 64 学时验收。请求 render 时 `skipped` 不能算成功；Render Smoke 只是 PDF 转换/页数证据，人工逐页查看才可称为 visual inspection。
