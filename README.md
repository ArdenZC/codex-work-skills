# 我的工作 Skills

这个仓库用于存放我在工作中复用的 Codex skills。后续新增 skill 时，建议每个 skill 都使用一个中文目录，并在目录中放置 `简介.md`，说明用途、适用场景、输入材料和安装方式。

## 技能列表

| 技能名称 | 简介 | 安装目录 |
| --- | --- | --- |
| 教案生成器 | 按内置 Word 教案模板生成项目化中文教案 DOCX；可读取能力图谱、章节任务拆解或旧教案，并能在资料不足时按课程特点推断项目和任务。 | `教案生成器/lesson-plan-docx-generator` |
| 平时成绩记分册生成器 | 根据 `课程成绩单.xls` 自动生成平时成绩记分册，内置模板，按 manifest 定义生成平时成绩项目，并按成绩比例删除或保留技能成绩列；支持 Windows Excel COM 和 macOS/Linux LibreOffice 路径。 | `平时成绩记分册生成器/course-gradebook-generator` |

## 使用约定

- 中文目录用于给同事识别技能用途。
- 实际 Codex skill 目录保留兼容命名，便于安装到 `.codex/skills` 后稳定调用。
- 每个 skill 需要包含中文简介，说明它能做什么、需要用户提供哪些资料、没有资料时会如何默认处理。
- 如果 skill 内置模板或脚本，放在 skill 目录下的 `assets/`、`scripts/` 等子目录中，避免依赖个人电脑上的临时路径。

## 多Agent兼容

仓库中的所有现有 skill 都提供统一的多 Agent 工作协议：AI 负责理解输入资料，技能脚本负责稳定生成最终文件。每个 skill 都包含 AGENTS.md、CLAUDE.md、GEMINI.md、通用提示词.md、Aider 约定和可生成 Cursor/Cline/Continue/Windsurf/Copilot 规则的适配器脚本。

适配范围包括 Codex、Claude Code、Gemini CLI、Cursor、Cline、Continue、Windsurf、OpenCode、GitHub Copilot CLI/Cloud Agent、Aider，以及使用 DeepSeek、Claude、GLM、Gemini、OpenAI 等模型的其他 agent 工具。纯网页聊天工具可以先生成结构化输入，再交给具备本地文件和命令权限的 agent 执行。

在任一 skill 目录运行 scripts/install_adapters.py 可以把适配规则安装到目标项目；默认不会覆盖已有规则文件。

## 模板包标准

文档和表格生成器使用版本化模板包。每个包的 canonical template、`manifest.yaml`、输入 schema、模板/输出校验器和 `CHANGELOG.md` 都随 skill 分发；旧模板路径继续保留为兼容入口，并由 SHA-256 校验防止两份模板分叉。

统一流程为：

```text
输入资料 → 标准化数据 → schema 校验 → 模板校验 → 生成 → 输出校验 → QA 报告
```

规范说明见 [`docs/template-package-standard.md`](docs/template-package-standard.md)。当前版本：教案默认使用 `lesson-plan/v1.1.0` 语义书签模板，同时保留 `lesson-plan/v1.0.0` 坐标兼容模式；记分册为 `course-gradebook/v1.0.0`。正常生成默认校验，只有显式传入 `--skip-template-validation` 或 `--skip-output-validation` 才会跳过；跳过时仍写入 QA 报告并标记为 `skipped`。

模板包默认校验命令如下，路径应替换为对应 Skill 目录中的脚本和版本化 manifest：

```bash
python scripts/validate_template.py --template <template> --manifest <manifest.yaml>
python scripts/validate_output.py --input-json <input.json> --output-dir <output> --manifest <manifest.yaml>
```

自定义模板应同时提供匹配的 manifest；内置 canonical 模板位于各 Skill 的 `assets/templates/<template-id>/<version>/`，不应直接覆盖。教案 v1.1 模板只能使用 manifest 显式声明的 Word 书签写入，书签名称遵守 Word 40 字符安全规则并使用短阶段代码，书签 ID 只接受 ASCII 十进制数字；`bookmarkStart`/`bookmarkEnd` 必须位于同一目标段落或物理单元格，构建器还会扫描所有 header/footer story。canonical v1.0 模板和旧 `assets/lesson-plan-template.docx` 仅传 `--template` 时会自动解析为 `legacy_coordinates`，自定义模板仍必须提供匹配 manifest。
