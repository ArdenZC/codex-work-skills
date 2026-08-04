# 我的工作 Skills 仓库规则

这是一个存放可复用 AI 工作包的私人仓库。处理某个 skill 时，先阅读对应中文目录下的 简介.md，再进入 skill 实际目录阅读 SKILL.md、AGENTS.md 和 通用提示词.md。不要把一个 skill 的模板、输入规则或命令套用到另一个 skill。

当前已有 skill：
- 教案生成器：教案生成器/lesson-plan-docx-generator
- 平时成绩记分册生成器：平时成绩记分册生成器/course-gradebook-generator

模板包维护工具位于 `tools/template_package.py`，动态从 manifest 发现全部包，并统一执行 discover、scaffold、validate、promote、archive。模板包变更应先使用它的 identity/full validation；validator 信任根是当前 repo-root 的 Git index，validator 和 scripts 下可能被导入的支持文件必须已跟踪、为普通文件且不含 symlink；未跟踪 canonical-like Skill 或 helper 不得执行。`scripts/__pycache__/` 下的 `.pyc/.pyo` 仅作为 Python cache 忽略，普通 scripts 目录中的 `.pyc/.pyo` 即使已跟踪也必须拒绝；隔离 validation workspace 建立后不得含有 `__pycache__`、`.pyc` 或 `.pyo`。工具不会自动 `git add`，新 Skill 必须精确暂存 validator、manifest、模板、schema 和已跟踪 helper；已跟踪但未 commit 的修改仍可运行。external 包不能自带或覆盖 validator，只能使用唯一的 Git-tracked canonical Skill owner。外部包验证只能在系统临时隔离 Skill 树执行，Promote 必须经过不可变 snapshot、stage、最终 target 和动态仓库校验，并在每个阶段确认全树字节与 snapshot 一致；validator 或 repo validator 产生任何包内文件都必须回滚。Scaffold 在运行完整 base validator 前检查 lexical/resolved 工作区边界，仓库内 output 只能写入 `work/template-packages/`，仓库外路径若解析回仓库必须拒绝，解析后仍在独立 workspace 的目录或 symlink alias 仍可用；report 与依赖必须解析到同一外部 workspace，且 report 只能位于工作包目录同级。Archive 必须包含依赖闭包并在解压后复验。报告、snapshot、stage、backup 或归档产物不得写入受保护目录或提交到仓库。

所有 skill 都遵循同一原则：模型负责理解用户资料，技能内置脚本负责稳定生成最终文件；资料不足时按各 skill 的默认规则处理，但不能伪造用户未提供的源数据。生成后执行技能自己的校验步骤，并报告实际结果。

处理平时成绩记分册时遵守版本和事务边界：v1.0 使用 legacy coordinates 并删除未使用学生行；v1.1 使用 workbook-level `gb_` named ranges，48 人以内保留到第 52 行，超出容量精确扩展到最后一名学生，`gb_template_row` 固定为第 5 行。Windows 使用 Excel COM 生成，Python `xlrd`/`olefile` raw XLS preflight 不受 skip 参数影响；LibreOffice 只承担完整 round-trip、格式和渲染 QA，双 skip 时 COM 不应强制依赖它。正式输出必须经过候选生成、raw 检查、可选 QA 后再原子替换 XLS 和 QA；失败要保留旧文件和无关 XLS，skip QA 仍须检查真实文件和 v1.1 named ranges。
