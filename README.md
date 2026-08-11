# Codex Work Skills

一组用于实际教学工作的可复用 AI Skills，目前包含教案生成器和平时成绩记分册生成器。

AI 负责理解课程资料和用户要求，Skill 内的确定性脚本负责生成最终 Word/Excel 文件并进行结构与格式校验，尽量避免直接编辑 Office 文件造成格式漂移。当前正式持续验证平台为 Windows 和 macOS。

## Skills

| Skill | 用途 | 当前模板 |
| --- | --- | --- |
| [教案生成器](教案生成器/简介.md) | 根据课程资料生成项目化中文教案 DOCX | [lesson-plan v1.1.0](https://github.com/ArdenZC/codex-work-skills/releases/tag/template/lesson-plan/v1.1.0) |
| [平时成绩记分册生成器](平时成绩记分册生成器/简介.md) | 根据课程成绩单自动生成平时成绩记分册 XLS | [course-gradebook v1.1.0](https://github.com/ArdenZC/codex-work-skills/releases/tag/template/course-gradebook/v1.1.0) |

### 教案生成器

- 生成整门课程的项目化中文教案。
- 可读取能力图谱、课程标准、教材目录、章节任务拆解或已有教案。
- 内置 Word 模板，不需要另外准备模板。
- 生成后自动进行结构和格式 QA。

详细说明：[教案生成器简介](教案生成器/简介.md) · [Skill 说明](教案生成器/lesson-plan-docx-generator/SKILL.md)

### 平时成绩记分册生成器

- 输入学校课程成绩单 `.xls`。
- 自动拆分多次平时成绩并适配学生人数。
- 保留学校 Excel 模板格式。
- 自动处理技能成绩列，生成后进行输出 QA。

详细说明：[平时成绩记分册生成器简介](平时成绩记分册生成器/简介.md) · [Skill 说明](平时成绩记分册生成器/course-gradebook-generator/SKILL.md)

## 快速安装

### 推荐：让 AI Agent 自动安装

只要使用的是能够访问本地文件、Git 和终端的 AI Agent，例如 Codex、Claude Code、Gemini CLI、Cursor Agent、Cline，以及其他具备本地命令执行能力的 Agent，就可以直接把仓库地址交给 AI：

```text
请帮我安装这个仓库中的「教案生成器」和「平时成绩记分册生成器」两个 Skill：

https://github.com/ArdenZC/codex-work-skills

请先阅读仓库 README 和两个 Skill 的简介，检查本机依赖，然后将 Skill 安装到当前 AI 工具对应的 skills 目录，并验证安装是否成功。

不要修改 Skill 源码或模板。
```

只安装教案生成器时，可以使用：

```text
请帮我安装这个仓库里的「教案生成器」，阅读它的安装说明后完成依赖检查、安装和验证：
https://github.com/ArdenZC/codex-work-skills
```

纯网页聊天工具如果没有本地文件和命令权限，无法直接完成本机安装。

### 手动安装

先获取仓库：

```bash
git clone https://github.com/ArdenZC/codex-work-skills.git
cd codex-work-skills
```

在 Windows 上安装到 Codex 默认目录：

```powershell
python ".\教案生成器\lesson-plan-docx-generator\scripts\install.py"
python ".\平时成绩记分册生成器\course-gradebook-generator\scripts\install.py"
```

在 macOS 上安装到 Codex 默认目录：

```bash
python3 "./教案生成器/lesson-plan-docx-generator/scripts/install.py"
python3 "./平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
```

默认安装目录是 `~/.codex/skills/`。如果目标目录已经存在，明确使用 `--replace` 才会替换；它会先备份已有安装：

```powershell
python ".\教案生成器\lesson-plan-docx-generator\scripts\install.py" --replace
```

安装后目录应类似：

```text
~/.codex/skills/
├── lesson-plan-docx-generator/
└── course-gradebook-generator/
```

其他 Agent 的 Skill 或 Rules 机制可能不同。请让对应 Agent 根据仓库中的 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、`通用提示词.md` 或适配脚本安装。

## 安装后怎么用

正常情况下用户不需要自己运行生成脚本，让 AI Agent 调用 Skill 即可。

生成教案：

```text
使用教案生成器，根据这个课程标准和教材目录，帮我生成《数据库技术》的项目化教案。
```

生成成绩册：

```text
使用平时成绩记分册生成器，根据这个课程成绩单生成平时成绩记分册。
```

## 系统要求

### 通用

- Git。
- Python 3。
- 支持本地文件和终端操作的 AI Agent。

### 教案生成器

- Windows 和 macOS 均已验证。
- 完整 Office 渲染 QA 需要 LibreOffice。

### 平时成绩记分册生成器

- Windows：推荐 Microsoft Excel，生成器优先使用 Excel COM。
- macOS：使用 Python + LibreOffice 路径。

正式持续验证平台是 Windows 和 macOS。Linux 的 LibreOffice Python 路径在设计上保持兼容，但当前不属于持续集成验收平台。

## 当前版本

- 教案模板： [lesson-plan v1.1.0](https://github.com/ArdenZC/codex-work-skills/releases/tag/template/lesson-plan/v1.1.0)。
- 成绩册模板： [course-gradebook v1.1.0](https://github.com/ArdenZC/codex-work-skills/releases/tag/template/course-gradebook/v1.1.0)。

这些 Release 是模板包版本。Skill 本身以本仓库 `master` 为当前安装来源。

## 其他 AI Agent

Skill 附带 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、`通用提示词.md` 和适配脚本。

对于不直接支持 Codex Skill 目录的工具，可以让 Agent 阅读这些文件并按照自身规则安装。当前协议可用于 Claude Code、Gemini CLI、Cursor、Cline、Continue、Windsurf、OpenCode、GitHub Copilot 和 Aider 等工具；具体安装目录由对应工具决定。

## 关于 GitHub Release

GitHub Releases 中的 `lesson-plan` / `course-gradebook` ZIP 是版本化模板包，不是完整 Skill 安装包。

普通用户安装 Skill 应从本仓库安装完整 Skill 目录。模板 Release 主要用于模板版本验证、分发、升级和回滚。

## 模板包维护

项目内部使用版本化模板包和严格 QA。维护者可使用仓库根目录的工具：

```bash
python tools/template_package.py discover --json
python tools/template_package.py validate --package <package> --json
python tools/template_package.py archive --package <package> --output-dir dist/template-packages
```

完整设计与命令：

- [模板包标准](docs/template-package-standard.md)
- [模板包编写规范](docs/template-package-authoring.md)
- [模板包发布流程](docs/template-package-release.md)
