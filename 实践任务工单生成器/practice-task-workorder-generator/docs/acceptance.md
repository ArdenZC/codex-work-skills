# Lesson 2.2.3 / WorkOrder 2.2.0 验收范围

## 必过检查

- Practice Task Contract 1.1、WorkOrder Content 1.1 schema、handoff 和 linked source snapshot 通过；旧版只走显式兼容入口。
- linked 工单逐字段保真课程基本信息、任务 ID、课次集合、标题、2 学时、目标、交付物、验收、工具/材料和安全约束；任务项只可展开或重组，不可改写上游目标和交付。
- 任务项可执行，交付物和验收标准使用一一对应的对象 ID 映射；Python 不用字符/n-gram 或专业 marker 判断自然度，统一 Agent review 负责教学判断。
- 课堂考勤固定 10 分，任务项合计 90 分，总分 100 分；学生结果栏为空，不含答案。
- WorkOrder DOCX 可打开，保留三张主体表、动态任务行、学生/教师评价和模板固定 rubric；内部任务/课次 ID 不进入学生可见默认正文。
- WorkOrder template v1.0.0 SHA-256 为 `F20308238D07C7BFB9B1F9D2A25591D6EE09F13EC5855B7C57FA914CEE9457BD`，二进制不修改。
- linked 模式真实 render 通过；未执行 render 只能是 UNVERIFIED/非生产结果。CI 在 macOS 和 Windows 使用真实 LibreOffice render smoke。

## E2E

用新写的 IT 与非 IT Lesson 2 学时样例、非 IT 2 学时 linked handoff 和一个 1 学时 Lesson 样例，分别验证结构、Content QA、Cross-Artifact QA、DOCX、真实 render 和代表页人工检查。synthetic fixture、Agent-authored Content 和人工接受结论分开记录；不生成完整课程，也不建立庞大测试系统。

## 明确边界

本轮不修改 Lesson v1.1.2 或 WorkOrder v1.0.0 模板二进制，不发布 Release，不合并分支，不做 Codex Review，不开发答案版或成绩册回写。视觉检查只能由 Agent 对真实渲染页作出并记录，脚本不能伪造人工视觉通过。
