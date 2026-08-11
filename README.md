# Codex Work Skills

一组用于教学资料处理的可复用 AI skill。当前包含项目化教案生成、平时成绩记分册生成和版本化模板包工具链，重点保证模板格式、输入校验、输出 QA 与 Windows/macOS 使用的一致性。

> **当前内置模板**：教案 `lesson-plan/v1.1.1`，成绩册 `course-gradebook/v1.1.0`
>
> **正式持续验证平台**：Windows、macOS

## 这是什么

两个 Skill 负责理解用户提供的课程资料并生成最终文件，模板写入、格式保留和结果校验由 Skill 自带脚本完成。普通用户通常只需要告诉 Agent 要生成什么、提供相关资料，不需要手动运行生成脚本。

## 两个 Skill

| Skill | 适合做什么 | 主要输入 | 输出 |
| --- | --- | --- | --- |
| [教案生成器](教案生成器/lesson-plan-docx-generator) | 批量生成或修改项目化中文职业教育教案 | 能力图谱、章节任务拆解、课程标准、教材目录、旧教案或课程信息 | 项目化 `.docx` 教案 |
| [平时成绩记分册生成器](平时成绩记分册生成器/course-gradebook-generator) | 根据课程成绩单生成平时成绩记分册 | `课程成绩单.xls` 或包含该文件的班级目录 | 平时成绩记分册 `.xls` |

没有完整资料也可以开始：教案生成器会根据课程信息推断项目化任务结构；成绩册生成器不能凭空生成成绩，必须提供 `课程成绩单.xls`。

## 快速安装

### 推荐：让 AI Agent 自动安装

适用于具备以下能力的 Agent：

- 本地文件访问；
- Git；
- 终端或命令执行。

例如 Codex、Claude Code、Gemini CLI、Cursor Agent、Cline，以及其他具备本地工具权限的 Agent。可以直接复制下面的提示词：

```text
请帮我安装这个仓库中的「教案生成器」和「平时成绩记分册生成器」两个 Skill：

https://github.com/ArdenZC/codex-work-skills

请先阅读仓库 README 和仓库根目录的 AGENTS.md，再阅读两个 Skill 各自的：
- 简介.md
- AGENTS.md
- 通用提示词.md
- SKILL.md

然后：

1. 检查本机 Git、Python 和相关 Office/LibreOffice 依赖；
2. 下载或 clone 仓库；
3. 将两个 Skill 安装到当前 AI 工具对应的 Skill / Rules 目录；
4. 如果当前工具是 Codex，优先使用各 Skill 自带的 scripts/install.py；
5. 不要修改 Skill 源码、模板或 manifest；
6. 安装后验证两个 Skill 是否可以被当前 Agent 识别和调用。

如果缺少依赖，请明确告诉我缺少什么以及如何安装。
```

只安装教案生成器时，可以使用：

```text
请帮我安装这个仓库中的「教案生成器」：

https://github.com/ArdenZC/codex-work-skills

请阅读 README、仓库根目录的 AGENTS.md，以及教案生成器的：
- 简介.md
- AGENTS.md
- 通用提示词.md
- SKILL.md
完成环境检查、安装和安装验证。
不要修改源码或模板。
```

纯网页聊天工具如果没有本机文件和命令权限，不能直接完成安装；需要交给具备这些权限的 Agent 执行。

### 手动安装

```bash
git clone https://github.com/ArdenZC/codex-work-skills.git
cd codex-work-skills
```

Windows PowerShell：

```powershell
python "教案生成器/lesson-plan-docx-generator/scripts/install.py"
python "平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
```

macOS Terminal：

```bash
python3 "教案生成器/lesson-plan-docx-generator/scripts/install.py"
python3 "平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
```

两个安装脚本默认安装到 Codex 的：

```text
~/.codex/skills/
├── lesson-plan-docx-generator/
└── course-gradebook-generator/
```

可用参数：

- `--dry-run`：只显示目标路径，不复制文件；
- `--skills-dir <目录>`：指定 Codex skills 目录；
- `--replace`：先备份已有安装，再替换；默认不会覆盖现有 Skill。

其他 Agent 不一定使用 `~/.codex/skills`。应根据对应工具的规则系统读取 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、`通用提示词.md` 和 `install_adapters.py`。适配器示例：

```powershell
python "<skill>/scripts/install_adapters.py" --target-dir "<project>"
```

macOS 使用 `python3`。默认不覆盖已有规则，明确传入 `--replace` 才会备份并替换。

## 安装后怎么用

普通用户通常不需要手动运行 `generate_*.py` 或 `generate_*.ps1`，直接让 Agent 调用已安装的 Skill 即可。

生成教案：

```text
使用教案生成器，根据这个课程标准和教材目录，
帮我生成《数据库技术》的项目化教案。
```

生成成绩册：

```text
使用平时成绩记分册生成器，
根据这个课程成绩单生成平时成绩记分册。
```

使用前建议提供的资料：

- 教案：课程名称、专业、授课对象、总课时、单次课时，以及能力图谱、章节任务拆解、课程标准、教材目录或旧教案；
- 成绩册：`课程成绩单.xls`，或包含该文件的班级目录；
- 自定义模板：对应版本的 manifest 和匹配的 SHA-256 fingerprint。

## 平台与系统要求

Windows 和 macOS 是当前 CI 与交付验收平台。

| 平台 | 教案生成器 | 成绩册生成器 |
| --- | --- | --- |
| Windows | Python 生成；需要时可用 Word 或 LibreOffice 做渲染检查 | Excel COM 是推荐生成路径；raw XLS preflight 始终执行；完整 LibreOffice QA 可选 |
| macOS | Python 生成；需要时可用 LibreOffice 做渲染检查 | Python + LibreOffice/`soffice` 完成 `.xls` 转换、写入和回转 |

其他要求：

- Python 3 是两个 Skill 的基础运行环境；缺少 Python 依赖时，按对应 Skill 的 `requirements.txt` 安装；
- Windows 的 Excel COM 路径需要本机安装 Microsoft Excel；
- macOS 的成绩册路径需要 LibreOffice，并确保 `soffice` 可用；
- Linux：基于 Python + LibreOffice 的路径设计上保持兼容，但当前不属于持续集成验收平台；
- Microsoft Excel COM、Word UI 和 Microsoft Office 原生渲染不在 GitHub Actions 中运行。

## 当前版本与兼容性

这些版本指内置 canonical 模板版本，不是 Skill 安装包版本。Skill 本身的安装来源仍是仓库 `master`，不是 GitHub Release ZIP。

| Skill | 版本 | 定位方式 | 说明 |
| --- | --- | --- | --- |
| 教案生成器 | `1.0.x` | `legacy_coordinates` | 旧模板兼容路径 |
| 教案生成器 | `1.1.x` | `word_bookmark` | 当前默认 `v1.1.1` |
| 成绩册生成器 | `1.0.x` | `legacy_coordinates` | 旧模板兼容路径 |
| 成绩册生成器 | `1.1.x` | `excel_named_range` | 当前默认 `v1.1.0` |

其他 `1.x` minor 版本当前会被拒绝，版本号与定位方式不一致也会被拒绝。正常生成默认执行 schema、模板和输出 QA；只有显式传入 skip 参数才会跳过对应的完整 QA，并在报告中标记为 `skipped`。canonical 模板不应直接覆盖，自定义模板应提供匹配 manifest。

教案 v1.1.1 保留项目化结构、70 个 Word 语义书签和两个课时严格合计 90 分钟的课中阶段；成绩册 v1.1.0 保留 8 次平时成绩、24 个 `gb_` named ranges、48 人模板容量规则、技能成绩列切换和输出 QA。

## 关于 GitHub Release

GitHub Releases 中的：

```text
lesson-plan-*.zip
course-gradebook-*.zip
```

是版本化模板包，不是完整 Skill 安装包。普通用户安装 Skill 时，应安装仓库 `master` 中的完整 Skill 目录；模板 Release 主要用于模板包的验证、分发、升级、回滚和维护。下载模板 ZIP 不等于安装对应的教案或成绩册 Skill。

## 多 Agent 与模型支持

仓库提供统一的跨工具协议：AI Agent 负责读取资料和生成结构化输入，Skill 脚本负责模板写入、格式保留和结果校验。入口包括：

- Codex / Codex CLI：`SKILL.md`、`agents/openai.yaml`；
- Claude Code：`CLAUDE.md`；
- Gemini CLI：`GEMINI.md`；
- Cursor、Cline、Continue、Windsurf、OpenCode：`AGENTS.md` 和对应规则目录；
- GitHub Copilot：`AGENTS.md`、`.github/copilot-instructions.md`；
- Aider：`CONVENTIONS.md`、`.aider.conf.yml`。

工作流与模型供应商无关，DeepSeek、Claude、GLM、Gemini、OpenAI 等模型都可以使用。能否生成最终文件取决于宿主工具是否允许本地文件读写和命令执行。详细兼容矩阵见 [`多Agent兼容规范.md`](多Agent兼容规范.md)。

## 模板与维护者工具

两个 Skill 使用版本化 canonical 模板、manifest、schema 和 QA。普通用户不需要直接使用模板包命令；仓库根目录的 `tools/template_package.py` 为维护者提供：

- `discover`；
- `scaffold`；
- `validate`；
- `promote`；
- `archive`；
- `verify-release`；
- `install` / `upgrade` / `rollback`；
- `release`。

正式模板生成默认执行 schema、模板和输出 QA；canonical 模板不应直接覆盖。完整维护者规范见：

- [模板包标准](docs/template-package-standard.md)
- [模板包作者指南](docs/template-package-authoring.md)
- [模板包发布与安装](docs/template-package-release.md)
