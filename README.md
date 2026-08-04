# 我的工作 Skills

这个仓库用于存放我在工作中复用的 Codex skills。后续新增 skill 时，建议每个 skill 都使用一个中文目录，并在目录中放置 `简介.md`，说明用途、适用场景、输入材料和安装方式。

## 技能列表

| 技能名称 | 简介 | 安装目录 |
| --- | --- | --- |
| 教案生成器 | 按内置 Word 教案模板生成项目化中文教案 DOCX；可读取能力图谱、章节任务拆解或旧教案，并能在资料不足时按课程特点推断项目和任务。 | `教案生成器/lesson-plan-docx-generator` |
| 平时成绩记分册生成器 | 根据 `课程成绩单.xls` 自动生成平时成绩记分册，内置模板，按 manifest 定义生成平时成绩项目，并按成绩比例删除或保留技能成绩列；支持 Windows Excel COM 和 macOS/Linux LibreOffice 路径。 | `平时成绩记分册生成器/course-gradebook-generator` |
| 模板包工具链 | 自动发现、脚手架、完整校验、原子晋级和确定性归档版本化模板包；不维护额外注册表，也不覆盖 canonical 包。 | `tools/template_package.py` |

## 使用约定

- 中文目录用于给同事识别技能用途。
- 实际 Codex skill 目录保留兼容命名，便于安装到 `.codex/skills` 后稳定调用。
- 每个 skill 需要包含中文简介，说明它能做什么、需要用户提供哪些资料、没有资料时会如何默认处理。
- 如果 skill 内置模板或脚本，放在 skill 目录下的 `assets/`、`scripts/` 等子目录中，避免依赖个人电脑上的临时路径。

## 多Agent兼容

仓库中的所有现有 skill 都提供统一的多 Agent 工作协议：AI 负责理解输入资料，技能脚本负责稳定生成最终文件。每个 skill 都包含 AGENTS.md、CLAUDE.md、GEMINI.md、通用提示词.md、Aider 约定和可生成 Cursor/Cline/Continue/Windsurf/Copilot 规则的适配器脚本。

适配范围包括 Codex、Claude Code、Gemini CLI、Cursor、Cline、Continue、Windsurf、OpenCode、GitHub Copilot CLI/Cloud Agent、Aider，以及使用 DeepSeek、Claude、GLM、Gemini、OpenAI 等模型的其他 agent 工具。纯网页聊天工具可以先生成结构化输入，再交给具备本地文件和命令权限的 agent 执行。

在任一 skill 目录运行 scripts/install_adapters.py 可以把适配规则安装到目标项目；默认不会覆盖已有规则文件。

成绩册的两个版本有明确边界：v1.0 使用 legacy coordinates，按输入人数删除未使用学生行；v1.1 使用 workbook-level `gb_` named ranges，48 人以内保留到第 52 行，超过模板容量时精确扩展到最后一名学生，`gb_template_row` 始终指向第 5 行。Windows 路径以 Excel COM 作为生成引擎，Python 的 `xlrd`/`olefile` 原始 XLS preflight 在任何 skip 参数下都不可跳过；LibreOffice 只用于完整 round-trip、格式和渲染 QA。Windows 同时显式跳过模板和输出 QA 时，不强制要求 LibreOffice。

成绩册生成采用候选文件事务：临时生成 → 不可跳过的 raw runtime 检查 → 可选完整 QA 或真实文件基础检查 → XLS 与 QA 原子替换。任一步失败都保留既有正式文件和输出目录中的无关 XLS，只清理本次运行的临时文件；skip QA 仍必须确认输出是非空 `.xls`，v1.1 还必须通过原始 named-range inventory。

## 模板包标准

文档和表格生成器使用版本化模板包。每个包的 canonical template、`manifest.yaml`、输入 schema、模板/输出校验器和 `CHANGELOG.md` 都随 skill 分发；旧模板路径继续保留为兼容入口，并由 SHA-256 校验防止两份模板分叉。

统一流程为：

```text
输入资料 → 标准化数据 → schema 校验 → 模板校验 → 生成 → 输出校验 → QA 报告
```

规范说明见 [`docs/template-package-standard.md`](docs/template-package-standard.md)。教案模板版本契约为：`1.0.x` 使用 `legacy_coordinates`，`1.1.x` 使用 `word_bookmark`；成绩册模板版本契约为：`1.0.x` 使用 `legacy_coordinates`，`1.1.x` 使用 `excel_named_range`；其他 `1.x` minor 当前拒绝，版本与定位模式不一致也拒绝。自定义 `1.1.x` manifest 必须完整声明对应的 semantic contract，unknown key、未知 target/mode 不会降级处理；legacy `1.0.x` 也不得夹带 semantic 定位字段。当前默认使用 `lesson-plan/v1.1.0` 和 `course-gradebook/v1.1.0`，两者均保留 v1.0 兼容路径。正常生成默认校验，只有显式传入 `--skip-template-validation` 或 `--skip-output-validation` 才会跳过；跳过时仍写入 QA 报告并标记为 `skipped`。

模板包默认校验命令如下，路径应替换为对应 Skill 目录中的脚本和版本化 manifest：

```bash
python scripts/validate_template.py --template <template> --manifest <manifest.yaml>
python scripts/validate_output.py --input-json <input.json> --output-dir <output> --manifest <manifest.yaml>
```

模板包维护使用仓库根目录的统一工具：

```bash
python tools/template_package.py discover --json
python tools/template_package.py scaffold --base-package <canonical-package> --version <new-version> --output-dir <work-package>
python tools/template_package.py validate --package <package> --json
python tools/template_package.py promote --package <package>
python tools/template_package.py archive --package <package> --output-dir <dist>
```

`discover` 动态读取所有 manifest，并严格验证 fingerprint、owner 和 schema；validator 信任根是当前 repo-root 的 Git index，未跟踪的 canonical-like Skill、symlink validator 或未跟踪 scripts helper 都会被拒绝且不会执行。`scripts/__pycache__/` 下的 `.pyc/.pyo` 会被识别为 Python cache 并忽略，普通 scripts 目录中的 `.pyc/.pyo` 即使已跟踪也会被拒绝；隔离 validation workspace 建立后不会含有 `__pycache__`、`.pyc` 或 `.pyo`。工具不会自动 `git add`，新 Skill 需要精确暂存 validator、manifest、模板、schema 和 helper；已跟踪但未 commit 的修改仍可验证。`validate` 对外部包在系统临时隔离 Skill 树中只复制 Git-tracked 普通脚本，调用所属 Skill 的真实 `scripts/validate_template.py`；`--identity-only` 只代表身份检查而不是完整通过。`scaffold` 必须先检查 lexical/resolved 工作目录再通过 base full validation；仓库内 output 只能写入 `work/template-packages/`，仓库外 lexical 路径若解析回仓库会被拒绝，解析后仍在独立 workspace 的目录或 symlink alias 可以使用，报告和依赖必须解析到同一 workspace，报告名包含 template id/version 且只能位于 output sibling。`promote` 从不可变 snapshot 开始，在 stage、最终 target 和动态仓库校验都通过后原子安装；`archive` 递归包含依赖闭包，解压后再次完整验证，并生成稳定排序、固定时间和权限的 ZIP、SHA-256 sidecar 与 `<id>-<version>.metadata.json`。所有变更命令都拒绝覆盖已有目标，支持 `--dry-run` 的命令不会创建文件。详细字段和生命周期见 [`docs/template-package-authoring.md`](docs/template-package-authoring.md)。

自定义模板应同时提供匹配的 manifest；内置 canonical 模板位于各 Skill 的 `assets/templates/<template-id>/<version>/`，不应直接覆盖。显式传入 manifest 时，canonical 或 compatibility 原始路径必须与声明版本精确匹配；自定义路径按 manifest 的版本、结构、书签契约和实际 SHA-256 fingerprint 校验，不会仅因 SHA 与旧 canonical 相同而推断 patch 版本。因此，普通 `shutil.copy2` 复制的 v1.1.0 模板可以配套声明真实 fingerprint 的 v1.1.1 manifest；compatibility 原始路径配 v1.0.1 manifest 则按路径身份规则拒绝。教案 v1.1 模板只能使用 manifest 显式声明的 Word 书签写入，书签名称遵守 Word 40 字符安全规则并使用短阶段代码，书签 ID 只接受 ASCII 十进制数字；`bookmarkStart`/`bookmarkEnd` 必须位于同一目标段落或物理单元格，构建器还会扫描所有 header/footer story。canonical v1.0 模板和旧 `assets/lesson-plan-template.docx` 仅传 `--template` 时会自动解析为 `legacy_coordinates`，自定义模板仍必须提供匹配 manifest。

模板包完整校验的执行边界：canonical、external、archive 解压包以及 scaffold/promote 的 snapshot、stage、target 和动态仓库验证，统一复制到系统临时的正常 Skill 树，通过 `python -B` 和受控子进程环境执行。只复制 Git-tracked 普通源文件与声明依赖，真实仓库的 `__pycache__`、`.pyc`、`.pyo` 不参与执行；外部 `PYTHONPATH`、`PYTHONHOME`、`PYTHONSTARTUP`、`PYTHONINSPECT` 等注入变量不会传入，user site 被禁用，Python cache 只允许写入临时树内的 `python-cache`，执行后必须检查并清理。任何隔离或清理失败都会使验证失败，`--identity-only` 仍只做身份检查。
