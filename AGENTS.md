# 我的工作 Skills 仓库规则

这是一个存放可复用 AI 工作包的私人仓库。处理某个 skill 时，先阅读对应中文目录下的 简介.md，再进入 skill 实际目录阅读 SKILL.md、AGENTS.md 和 通用提示词.md。不要把一个 skill 的模板、输入规则或命令套用到另一个 skill。

当前已有 skill：
- 教案生成器：教案生成器/lesson-plan-docx-generator
- 平时成绩记分册生成器：平时成绩记分册生成器/course-gradebook-generator

所有 skill 都遵循同一原则：模型负责理解用户资料，技能内置脚本负责稳定生成最终文件；资料不足时按各 skill 的默认规则处理，但不能伪造用户未提供的源数据。生成后执行技能自己的校验步骤，并报告实际结果。

处理平时成绩记分册时遵守版本和事务边界：v1.0 使用 legacy coordinates 并删除未使用学生行；v1.1 使用 workbook-level `gb_` named ranges，48 人以内保留到第 52 行，超出容量精确扩展到最后一名学生，`gb_template_row` 固定为第 5 行。Windows 使用 Excel COM 生成，Python `xlrd`/`olefile` raw XLS preflight 不受 skip 参数影响；LibreOffice 只承担完整 round-trip、格式和渲染 QA，双 skip 时 COM 不应强制依赖它。正式输出必须经过候选生成、raw 检查、可选 QA 后再原子替换 XLS 和 QA；失败要保留旧文件和无关 XLS，skip QA 仍须检查真实文件和 v1.1 named ranges。
