# 我的工作 Skills 仓库规则

这是一个存放可复用 AI 工作包的私人仓库。处理某个 skill 时，先阅读对应中文目录下的 简介.md，再进入 skill 实际目录阅读 SKILL.md、AGENTS.md 和 通用提示词.md。不要把一个 skill 的模板、输入规则或命令套用到另一个 skill。

当前已有 skill：
- 教案生成器：教案生成器/lesson-plan-docx-generator
- 平时成绩记分册生成器：平时成绩记分册生成器/course-gradebook-generator

所有 skill 都遵循同一原则：模型负责理解用户资料，技能内置脚本负责稳定生成最终文件；资料不足时按各 skill 的默认规则处理，但不能伪造用户未提供的源数据。生成后执行技能自己的校验步骤，并报告实际结果。