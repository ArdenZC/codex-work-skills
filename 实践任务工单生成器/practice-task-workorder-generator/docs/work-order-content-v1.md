# Practice Work Order Content V1

## 输入

Content V1 是工单 Skill 的直接写入合同。每份输入包含课程基本信息、实践任务标识、项目名称、正整数实践学时、组信息和 1–5 个任务项。每个任务项包含：

- `title`：任务标题；
- `description`：给学生看的任务说明；
- `score`：任务分值，所有任务合计必须为 90；
- `tools_or_materials`：实施所需工具、设备、环境或材料；
- `steps`：可执行步骤；
- `deliverables`：学生应提交的产物；
- `acceptance_criteria`：用于检查产物的可观察标准。

出勤固定 10 分，任务固定 90 分，合计 100 分。合同不包含 `total_score` 这样的可由 QA 推导的字段，避免两个来源发生漂移。

## 输出映射

脚本只负责确定性地替换模板中的项目标题、组信息、任务行和教师评价中的项目名。任务结果列保持空白；学生评价的自评/小组评价/教师评价以及教师评价表的固定问题保持模板原样。

## Lesson handoff

Lesson Skill 的 `Practice Task Contract V1` 是上游 handoff，不是本 Skill 的第二份课程合同。Phase 1 只读取其中的任务字段，映射成 Content V1；缺少可执行步骤、交付物或验收标准时报告错误，不用模型或 Python 补写答案。
