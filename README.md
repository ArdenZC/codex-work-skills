# Codex Work Skills

面向日常教学资料工作的可复用 AI skill 集合。当前仓库提供教案生成、平时成绩记分册生成和版本化模板包工具链，重点保证模板格式、输入校验、输出 QA 和跨平台使用的一致性。

> **当前默认版本**：教案 `lesson-plan/v1.1.1`，成绩册 `course-gradebook/v1.1.0`
>
> **交付验证平台**：Windows、macOS
> **适用方式**：Codex、Claude Code、Gemini CLI、Cursor、Cline、Continue、Windsurf、OpenCode、GitHub Copilot、Aider 等具备本地文件和命令权限的 agent

## 先看这里

| 你的需求 | 使用内容 | 主要输入 | 输出 |
| --- | --- | --- | --- |
| 批量生成或修改中文职业教育教案 | [教案生成器](教案生成器/lesson-plan-docx-generator) | 能力图谱、章节任务拆解、旧教案或课程信息 | 项目化 `.docx` 教案 |
| 生成平时成绩记分册 | [平时成绩记分册生成器](平时成绩记分册生成器/course-gradebook-generator) | `课程成绩单.xls` | 平时成绩记分册 `.xls` |
| 创建、校验、晋级或归档模板包 | [模板包工具链](tools/template_package.py) | 版本化模板包 | 校验报告、归档包或已安装版本 |

没有完整资料也可以开始：教案生成器会根据课程信息推断项目化任务结构；成绩册生成器不能凭空生成成绩，必须提供 `课程成绩单.xls`。

## 快速安装

两个 skill 都自带安装脚本，默认安装到当前用户的 `~/.codex/skills`。安装前请先将本仓库下载或克隆到本机。

### Windows PowerShell

```powershell
python "教案生成器/lesson-plan-docx-generator/scripts/install.py"
python "平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
```

### macOS Terminal

```bash
python3 "教案生成器/lesson-plan-docx-generator/scripts/install.py"
python3 "平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
```

安装脚本支持：

- `--dry-run`：只显示目标路径，不复制文件；
- `--skills-dir <目录>`：指定 Codex skills 目录；
- `--replace`：备份已有安装后再替换，默认不会覆盖现有 skill。

安装后，重新打开或刷新对应的 agent 会话即可使用。每个 skill 的完整输入、命令和校验说明见其目录下的 `SKILL.md`。

## 技能说明

### 教案生成器

目录：`教案生成器/lesson-plan-docx-generator`

- 默认使用内置 Word 模板，保留既有表格结构和格式；
- 支持能力图谱 Excel、章节任务拆解、旧教案或用户提供的 DOCX 模板；
- 默认生成项目化教学：`单元名称` 使用“项目一、项目二……”等项目名称，`任务名称` 使用具体可交付任务；
- 实训课会优先组织成果包、工具、操作记录、互评和过程性评价；
- 自动处理课程名称、课时、教学过程、教学评价分数和教学反思；
- 默认模板为 `lesson-plan/v1.1.1`，仍支持 canonical v1.0 和旧 compatibility 路径。

建议准备：课程名称、专业、授课对象、总课时、单次课时，以及能力图谱或章节任务资料。如果没有这些资料，skill 会明确说明推断依据后按项目化课程结构生成，不会退化成只有章节名称的目录。

### 平时成绩记分册生成器

目录：`平时成绩记分册生成器/course-gradebook-generator`

- 输入 `课程成绩单.xls` 或包含该文件的班级目录；
- 默认使用 `course-gradebook/v1.1.0` 的 workbook-level `gb_` named ranges；
- 保留 v1.0 canonical 和旧 compatibility 模板的 legacy-coordinate 路径；
- 按成绩比例保留或删除技能成绩列，并生成公式、总评和 QA 报告；
- 48 人以内保留模板到第 52 行，超过模板容量时精确扩展到最后一名学生；
- v1.1 的 `gb_template_row` 始终指向第 5 行，不静默回退到固定坐标。

建议先确认源成绩单中的课程、教师、班级、成绩比例、学生学号和姓名完整。技能缺少源成绩单时会要求补充，不会伪造输入数据。

### 模板包工具链

入口：`tools/template_package.py`

用于发现、脚手架、校验、原子晋级、确定性归档、安装、升级和回滚版本化模板包。工具不维护额外注册表，也不会覆盖 canonical 模板包。

## 多 Agent 使用

所有 skill 共用同一套“模型理解输入、脚本负责稳定写入和校验”的工作协议。业务逻辑集中在 skill 自带的 Python/PowerShell 脚本中，便于不同 agent 和不同模型复用相同的输入结构与输出规则。

| Agent / 工具 | 入口或适配文件 |
| --- | --- |
| Codex / Codex CLI | `SKILL.md`、`agents/openai.yaml` |
| Claude Code | `CLAUDE.md` |
| Gemini CLI | `GEMINI.md` |
| Cursor、Cline、Continue、Windsurf、OpenCode | `AGENTS.md` 及对应规则目录 |
| GitHub Copilot CLI / Cloud Agent | `AGENTS.md`、`.github/copilot-instructions.md` |
| Aider | `CONVENTIONS.md`、`.aider.conf.yml` |

工作流与模型供应商无关，DeepSeek、Claude、GLM、Gemini、OpenAI 等模型均可使用。前提是宿主工具能够读写本地文件并执行 Python 或 PowerShell；纯网页聊天工具可以先生成结构化输入，再交给有本地工具权限的 agent 执行。

为目标项目安装适配规则：

```powershell
python "<skill>/scripts/install_adapters.py" --target-dir "<project>"
```

macOS 使用 `python3`。默认不覆盖已有规则；可重复传入 `--adapter claude`、`--adapter cursor` 等参数选择工具，只有明确传入 `--replace` 才会备份并替换。需要把整个 skill 包复制到目标项目时，再增加 `--copy-engine`。

详细兼容矩阵见 [`多Agent兼容规范.md`](多Agent兼容规范.md)。

## 版本与兼容性

| Skill | 版本范围 | 定位模式 | 当前默认 |
| --- | --- | --- | --- |
| 教案生成器 | `1.0.x` | `legacy_coordinates` | 兼容路径 |
| 教案生成器 | `1.1.x` | `word_bookmark` | `v1.1.1` |
| 成绩册生成器 | `1.0.x` | `legacy_coordinates` | 兼容路径 |
| 成绩册生成器 | `1.1.x` | `excel_named_range` | `v1.1.0` |

其他 `1.x` minor 版本当前会被拒绝；版本号和定位模式不一致也会被拒绝。正常生成默认执行模板校验和输出校验，只有显式传入 `--skip-template-validation` 或 `--skip-output-validation` 才会跳过对应的完整 QA；跳过时仍会写入 QA 报告，并将状态标记为 `skipped`。

自定义模板必须提供匹配的 manifest：

- canonical 模板位于各 skill 的 `assets/templates/<template-id>/<version>/`，不应直接覆盖；
- 显式 manifest 的版本、模板路径和 SHA-256 fingerprint 必须一致；
- v1.1 教案只能使用 manifest 声明的 Word 书签，书签名遵守 Word 40 字符限制，ID 只接受 ASCII 十进制数字；
- `bookmarkStart` 和 `bookmarkEnd` 必须位于同一目标段落或物理单元格，构建器还会扫描 header/footer story；
- unknown key、未知 target/mode 和 legacy 模板夹带 semantic 定位字段都会被拒绝，不会静默降级。

## 统一生成流程

```text
输入资料
   ↓
标准化数据 → schema 校验 → 模板校验
   ↓
生成临时候选文件 → raw runtime 检查
   ↓
完整 QA 或显式 skip QA
   ↓
输出校验 → QA 报告 → 原子替换正式输出
```

两个生成器都遵循这条边界。成绩册的 raw XLS、named-range inventory 和基本文件有效性检查不能被 skip 参数绕过；完整 round-trip、格式和渲染 QA 可以按命令显式跳过。

## 平台说明

本仓库的交付和 CI 验证只考虑 Windows、macOS。

| 平台 | 教案 DOCX | 成绩册 XLS |
| --- | --- | --- |
| Windows | Python 生成，必要时可用 Word/LibreOffice 做渲染检查 | 优先使用 Microsoft Excel COM；Python `xlrd`/`olefile` raw XLS preflight 始终执行；完整 LibreOffice QA 可选 |
| macOS | Python 生成，必要时使用 LibreOffice 做渲染检查 | 使用 Python + LibreOffice/`soffice` 完成 `.xls` 转换、写入和回转；不使用 Excel COM |

Windows 同时显式跳过模板和输出 QA 时不强制要求 LibreOffice。Microsoft Excel COM、Word UI 和 Microsoft Office 原生渲染不在 GitHub Actions 中运行；相关 COM 集成需要本地 Windows 和已安装的 Microsoft Office。CI 会在 macOS 和 Windows 上执行结构化 QA、LibreOffice 回转和回归测试。

## 安全与事务边界

- 生成先写临时候选文件，raw runtime 检查和 QA 通过后才替换正式 XLS 与 QA；
- 任一步失败都保留旧正式输出和输出目录中的无关文件，只清理本次运行的临时文件；
- 不覆盖源成绩单、实际或声明模板、manifest、base template、base manifest、canonical 或 compatibility 模板；
- 模板工具的 stage、target 和仓库动态校验通过后才原子晋级；
- 工具不会自动 `git add`，新模板包需要精确暂存 validator、manifest、模板、schema 和 helper；
- 已安装包保持 immutable，rollback 只切换已安装版本的 active/previous 状态，不执行 bundle 中的代码。

## 模板包工具链

在仓库根目录运行。路径参数应替换为实际模板包或工作目录：

```bash
# 发现并检查仓库中的 canonical 包
python tools/template_package.py discover --json

# 创建并校验新版本
python tools/template_package.py scaffold \
  --base-package <canonical-package> \
  --version <new-version> \
  --output-dir <work-package>
python tools/template_package.py validate --package <package> --json

# 原子晋级并生成确定性归档
python tools/template_package.py promote --package <package>
python tools/template_package.py archive \
  --package <package> \
  --output-dir dist/template-packages

# 验证、安装和检查归档
python tools/template_package.py verify-release \
  --release-dir dist/template-packages --json
python tools/template_package.py install \
  --release-dir dist/template-packages --json
python tools/template_package.py list-installed --verify --json
```

常用模板/输出校验命令：

```bash
python scripts/validate_template.py \
  --template <template> \
  --manifest <manifest.yaml>
python scripts/validate_output.py \
  --input-json <input.json> \
  --output-dir <output> \
  --manifest <manifest.yaml>
```

### 工具链的关键保护

- `discover` 动态读取 manifest，并检查 fingerprint、owner、schema、Git index 信任根和 canonical 包完整性；未跟踪的 canonical-like skill、symlink validator、未跟踪 helper 会被拒绝；`scripts/__pycache__/` 中的 Python cache 会被忽略，普通 `scripts` 中的 `.pyc/.pyo` 会被拒绝；
- `validate` 在系统临时目录创建隔离的正常 Skill 树，只复制 Git-tracked 普通脚本并调用真实 validator；`--identity-only` 只做身份检查，不代表完整通过；超时时已产生的 stdout/stderr 会保留为 UTF-8 文本；
- `scaffold` 检查 lexical/resolved workspace、symlink containment、报告路径和依赖路径；仓库内输出只能写入 `work/template-packages/`；
- `promote` 从不可变 snapshot 开始，在 stage、最终 target 和 repository-wide 动态校验都通过后原子安装，并保护所有 canonical skill 的完整模板树；
- `archive` 递归包含依赖闭包，解压后再次验证，生成稳定排序、固定时间和权限的 ZIP、SHA-256 sidecar 以及 `<id>-<version>.metadata.json`；
- 所有变更命令拒绝覆盖已有目标；支持 `--dry-run` 的命令不会创建文件。

## 发布和安装生命周期

canonical 模板、三文件 archive、installed 版本和 GitHub Release 是四类不同对象：

```text
canonical source → deterministic archive → installed version → GitHub Release
```

- 正式 release 只接受当前仓库内真实 Git-tracked 的 canonical 包；archive 中的每个文件必须与当前 HEAD blob 逐字节一致，CRLF/LF 或其他换行差异都会被拒绝；
- 发布前会保存完整 HEAD blob 快照，发布后逐项核对 ZIP、metadata 和远程 asset SHA；
- GitHub 操作前会校验 origin 的 GitHub owner/name，`--repository` 只能作为同一仓库断言；
- release workflow 只从 clean `master` 手动触发，并按 template/version 串行化；`operation_id` 用于证明 annotated tag、Release 和 asset 的归属；
- 不覆盖已有 tag、Release 或 asset；live 校验远程 master 和三个发布 asset 的 SHA；
- external future patch 只能先通过 `archive` 生成 bundle，再由 `verify-release`、`install` 或 `upgrade` 处理；
- 默认 `list-installed` 重新计算 bundle inventory SHA，`--verify` 才执行完整隔离 Skill QA；不可信 ZIP 受资源上限保护。

详细字段、作者约束和生命周期说明：

- [`docs/template-package-standard.md`](docs/template-package-standard.md)
- [`docs/template-package-authoring.md`](docs/template-package-authoring.md)
- [`docs/template-package-release.md`](docs/template-package-release.md)

## 仓库约定

- 顶层中文目录用于直观标识用途，实际安装目录使用稳定的兼容名称；
- 每个 skill 应包含 `SKILL.md`、中文简介、输入说明、`assets/`、`scripts/` 和必要的 schema/manifest；
- 新增 skill 时同时更新对应的多 Agent 入口和适配器；
- 模板和脚本随 skill 分发，不依赖个人电脑上的绝对路径或临时文件；
- 变更模板包时保留 CHANGELOG、fingerprint 和可复现的验证记录。
