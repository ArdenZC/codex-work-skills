# Codex Work Skills

一组用于实际教学工作的可复用 AI Skills。目前包含：

- **教案生成器 2.2.0**：批量生成、整理和校验项目化中文职业教育教案 DOCX；Lesson DOCX 只承载理论，实践通过 Practice Task/WorkOrder 交付；
- **平时成绩记分册生成器**：根据课程成绩单生成并校验平时成绩记分册 XLS。
- **实践任务工单生成器 2.1.0**：由 Agent 将 Lesson Practice Task Contract 创作成 WorkOrder Content，再写入真实 Word 学习工单模板（Phase 2.1 Hardening）。

AI / Agent 负责理解课程资料和生成结构化内容，Skill 自带脚本负责确定性模板写入、格式保护、事务提交和结果 QA。

> **正式持续验证平台**：Windows、macOS  
> **完整 Skill 安装来源**：仓库 `master`  
> **GitHub Release 中的 ZIP**：版本化模板包，不是完整 Skill 安装包

## 当前版本

| Skill | Skill 版本 | 内容合同 | 当前默认模板 | 状态 |
| --- | --- | --- | --- | --- |
| [教案生成器](教案生成器/lesson-plan-docx-generator) | **2.2.0** | **Lesson Content Contract 2.2**（兼容 2.1/2.0） | `lesson-plan v1.1.2` | 稳定 |
| [平时成绩记分册生成器](平时成绩记分册生成器/course-gradebook-generator) | 当前稳定版 | — | `course-gradebook v1.1.0` | 稳定 |
| [实践任务工单生成器](实践任务工单生成器/practice-task-workorder-generator) | **Phase 2.1 / 2.1.0** | **Practice Work Order Content 1.0** | `practice-work-order v1.0.0` | 联动候选 |

**Skill 版本、内容合同版本和模板版本是三个不同概念。** 教案生成器已经进入 **2.2**，但默认 Word 模板仍是经过保护和兼容验证的 `lesson-plan v1.1.2`；升级 Skill 不代表必须把模板版本同步改成 2.2。

完整用户可见更新见 [CHANGELOG.md](CHANGELOG.md)。

Lesson Acceptance V2 的本地验收、报告和人工复核协议见 [docs/lesson-acceptance.md](docs/lesson-acceptance.md)。

## 教案生成器 2.2.0

2.2 是在 2.1 课程基础合同上的理论/实践产物边界和课程参考资料收口，不是模板更新：

- 先进入 `INTAKE_PENDING`，在正式规划前一次性确认课程名称、专业、授课对象和总课时；单课课时默认 2 学时，教材建议确认但不是阻断字段；
- 确认后进入 `INTAKE_CONFIRMED` 并自主完成整门课程规划；不再询问 outline、模板、输出目录或是否开始生成 DOCX；
- Lesson DOCX 只承载理论课时，理论课次数量按默认单课课时向上取整并保留余数；实践课时只通过 Practice Task/WorkOrder handoff 交付；
- 项目数、Lesson 数、Practice Task 数和 WorkOrder 数独立规划，不把项目数写死为 8 或按实践课时机械计算工单数；
- 先做整门课程的项目 / 任务规划，再逐课生成完整 Content 2.2；
- 正式路径不再接受旧 sparse JSON 作为生产输入；
- Python 不替模型创作教学正文，只负责校验、格式化、模板映射和文件生成；
- 沿用既有课程重复 / 相似度、课次递进、单课主语义连通和 implementation 逐项 coherence QA，本版本不扩展这些算法；
- 教学评价按课生成，显式分数限定为 **85–96**、步长 **0.5**，并提供 13 项逐课评价备注；
- 支持护理、会计等非 IT 课程，避免固定 IT 场景和模板套话污染；
- `course_materials.textbook` 与 `reference_pool` 分离，逐课只写 `reference_ids`，教材默认不写入 Word references；每个理论 Lesson 至少有 1 项具体 reference；合法文献 references 可跨课复用，纯资源名、泛化占位和虚构书目信息失败；
- references 只表示可阅读/查阅/引用的文献或文档，resources 表示教学工具、设备、环境和材料；参考资料优先使用国内出版物、高校资料、国家/行业/职业标准和国内权威文件，国内占比是质量信号而非硬失败；
- 引入 Practice Task Contract V1，实践任务可以跨多个课次；`practice_work_orders=true` 时由 Lesson Agent 检测并调用 WorkOrder Agent 统一交付；不可用时只输出 JSON handoff 并明确状态，不伪造工单 DOCX；
- 输出采用 candidate → QA → atomic commit，生成失败不会静默覆盖正式文件；
- 项目内 Full Engine 增加 runtime fingerprint / stale detection，避免新规则配旧 runtime；
- Windows、macOS CI 均执行 Lesson Content、Lesson Package 和 Hardening 回归。

默认 Word 模板仍为 `lesson-plan v1.1.2`，并继续保留 v1.0、v1.1.0、v1.1.1 的兼容路径。

## 实践任务工单生成器 2.1.0（Phase 2.1 Hardening）

WorkOrder 以仓库 `schemas/shared/practice-task-contract.schema.json` 定义的 Practice Task Contract V1 为唯一上游事实源，保留任务 ID、课次集合、实践学时、交付物、验收、工具/材料和安全约束。`--practice-task-json` 只校验 handoff 并输出 authoring skeleton；正式 DOCX 必须来自 Agent 完整创作的 Practice Work Order Content V1。它增加逐步骤可执行性、逐交付物验收、工具/材料保留、Practice Task → WorkOrder Cross-Artifact QA、批量 all-or-none 发布、事务式安装/依赖 doctor，以及 Codex/Claude/Gemini/Copilot/Aider 适配器；评分仍固定为课堂考勤 10 + 任务项 90 = 100，学生任务结果保持空白。

它使用现有 `practice-work-order v1.0.0` 模板，不新增模板版本，不生成教师答案，不做成绩册回写，也不进入完整 64 学时 Phase 3 验收。

## 三个 Skill 能做什么

| Skill | 主要输入 | 输出 |
| --- | --- | --- |
| 教案生成器 | 课程名称、专业、授课对象、总课时，以及能力图谱、章节任务拆解、课程标准、教材目录、旧教案或其他课程资料 | 项目化 `.docx` 教案 + QA 报告 |
| 平时成绩记分册生成器 | `课程成绩单.xls` 或包含该文件的班级目录 | 平时成绩记分册 `.xls` + QA 报告 |
| 实践任务工单生成器 2.1 | Agent-authored Practice Work Order Content V1，或用于 authoring 的 Lesson Practice Task Contract V1 handoff | 学习工单 `.docx` + Content/Cross-Artifact/Output QA |

教案资料不完整时可以继续：Agent 会先读取会话和附件，再一次性确认课程基础（单课默认 2 学时；教材建议确认但不阻断），确认后按课程结构完成规划和生成，不再询问模板、输出目录或是否开始生成 DOCX。Lesson DOCX 不替代实践工单；成绩册不能凭空生成成绩，必须提供真实课程成绩单。实践工单不能代写答案，学生任务结果栏保持空白。

## 快速安装

### 推荐：让 AI Agent 自动安装

适用于具备本地文件访问、Git 和终端执行能力的 Agent，例如 Codex、Claude Code、Gemini CLI、Cursor Agent、Cline 等。

可以直接复制：

```text
请帮我安装这个仓库中的「教案生成器」和「平时成绩记分册生成器」两个 Skill：

https://github.com/ArdenZC/codex-work-skills

请先阅读仓库 README 和根目录 AGENTS.md，再阅读两个 Skill 各自的 简介.md、AGENTS.md、通用提示词.md 和 SKILL.md。

然后：
1. 检查本机 Git、Python 和相关 Office / LibreOffice 依赖；
2. clone 仓库；
3. 将两个 Skill 安装到当前 AI 工具对应的 Skill / Rules 目录；
4. 如果当前工具是 Codex，优先使用各 Skill 自带的 scripts/install.py；
5. 不要修改 Skill 源码、模板或 manifest；
6. 安装后验证两个 Skill 是否可以被当前 Agent 识别和调用。

如果缺少依赖，请明确告诉我缺少什么以及如何安装。
```

实践任务工单生成器目前为独立 Phase 2.1 联动候选 Skill，可按需单独安装：

```text
请帮我安装这个仓库中的「实践任务工单生成器 2.1」：
https://github.com/ArdenZC/codex-work-skills

请阅读仓库 README、根目录 AGENTS.md，以及实践任务工单生成器下的简介.md、AGENTS.md、通用提示词.md 和 SKILL.md。
读取 Lesson 的 Practice Task Contract V1，先由 Agent 创作完整 Practice Work Order Content V1，再固定 10+90=100，保留上游 ID/课次/学时/工具/材料，运行 Content/Cross-Artifact/Output QA 和请求的真实 render，学生结果区留空，不生成教师答案。
```

只安装教案生成器：

```text
请帮我安装这个仓库中的「教案生成器 2.2.0」：
https://github.com/ArdenZC/codex-work-skills

请阅读 README、根目录 AGENTS.md、教案生成器/简介.md，以及 lesson-plan-docx-generator 下的 AGENTS.md、通用提示词.md 和 SKILL.md。
完成环境检查、安装和安装验证，不要修改源码或模板。
```

纯网页聊天工具如果没有本机文件和命令权限，不能直接完成本地安装。

### Codex 手动安装

```bash
git clone https://github.com/ArdenZC/codex-work-skills.git
cd codex-work-skills
```

Windows PowerShell：

```powershell
python "教案生成器/lesson-plan-docx-generator/scripts/install.py"
python "平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
python "实践任务工单生成器/practice-task-workorder-generator/scripts/install.py"
```

macOS Terminal：

```bash
python3 "教案生成器/lesson-plan-docx-generator/scripts/install.py"
python3 "平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
python3 "实践任务工单生成器/practice-task-workorder-generator/scripts/install.py"
```

默认安装到：

```text
~/.codex/skills/
├── lesson-plan-docx-generator/
├── course-gradebook-generator/
└── practice-task-workorder-generator/
```

可用参数：

- `--dry-run`：只显示计划，不复制文件；
- `--skills-dir <目录>`：指定 Codex skills 目录；
- `--replace`：备份并替换已有安装；默认不覆盖。
- `--keep-backup`：成功替换时保留上一份安装；默认成功后清理临时 backup。

Python 依赖见各 Skill 的 `requirements.txt`。教案生成器安装后可运行其 dependency check；缺少依赖时按提示安装，不会由安装器静默修改 Python 环境。

## 其他 Agent / 项目级规则

三个 Skill 都提供 Agent adapter。默认 adapter 安装只复制规则 / instructions；需要在目标项目中直接运行完整 engine 时，应显式使用对应的 `--copy-engine`。

示例：

```powershell
python "<skill>/scripts/install_adapters.py" --target-dir "<project>"
```

完整项目内 Lesson engine：

```powershell
python "lesson-plan-docx-generator/scripts/install_adapters.py" --target-dir "<project>" --copy-engine
```

macOS 使用 `python3`。共享 `AGENTS.md`、Claude、Gemini、Copilot 和 Aider 规则使用 namespaced marker，可与其他 Skill 共存。

## 安装后怎么用

生成教案：

```text
使用教案生成器 2.2.0，根据这份课程标准和教材目录，
帮我生成《数据库技术》的项目化教案。
```

生成成绩册：

```text
使用平时成绩记分册生成器，
根据这个课程成绩单生成平时成绩记分册。
```

生成实践任务工单：

```text
使用实践任务工单生成器 2.1，根据这份 Practice Task Contract V1 handoff 创作完整 WorkOrder Content V1 并生成学习工单；结果栏留空，不生成答案。
```

普通用户通常不需要直接运行 `generate_*.py` / `generate_*.ps1`，由 Agent 调用 Skill 即可。

## 平台与系统要求

Windows 和 macOS 是当前 CI 与交付验收平台。

| 平台 | 教案生成器 | 成绩册生成器 |
| --- | --- | --- |
| Windows | Python 生成 DOCX；需要时可用 Word 或 LibreOffice 做渲染检查 | Excel COM 是推荐生成路径；raw XLS preflight 始终执行；LibreOffice QA 可选 |
| macOS | Python 生成 DOCX；需要时可用 LibreOffice 做渲染检查 | Python + LibreOffice / `soffice` 完成 XLS 转换、写入和回转 |

其他说明：

- Python 3 是基础运行环境；
- Windows Excel COM 需要本机 Microsoft Excel；
- macOS 成绩册路径需要 LibreOffice；
- Linux 的 Python + LibreOffice 路径设计上保持兼容，但当前不是持续集成验收平台；
- GitHub Actions 不运行 Microsoft Excel COM、Word UI 或 Microsoft Office 原生渲染。

## 版本关系

教案生成器目前同时存在三种版本号：

```text
Lesson Skill          2.2.0
Content Contract      2.2 (reads 2.1/2.0)
Word template         lesson-plan v1.1.2
```

它们职责不同：

- **Skill 版本**：用户看到的教案生成器整体能力版本；
- **Content Contract**：Agent 与 Python 之间的结构化内容合同；
- **模板版本**：Word 文件布局、语义书签和模板兼容版本。

因此“教案生成器 2.2”不意味着 Word 模板必须叫 `v2.2`。

## 关于 GitHub Release

GitHub Releases 中的：

```text
lesson-plan-*.zip
course-gradebook-*.zip
```

是**版本化模板包**，不是完整 Skill 安装包。完整 Skill 仍从仓库 `master` 安装。模板 Release 主要用于模板包的验证、分发、升级和回滚。

## 多 Agent 与模型支持

仓库提供统一跨工具协议：模型负责理解资料并生成结构化输入，Skill 脚本负责确定性模板写入和 QA。

主要入口：

- Codex / Codex CLI：`SKILL.md`、`agents/openai.yaml`；
- Claude Code：`CLAUDE.md`；
- Gemini CLI：`GEMINI.md`；
- Cursor、Cline、Continue、Windsurf、OpenCode：`AGENTS.md` 和对应规则目录；
- GitHub Copilot：`AGENTS.md`、`.github/copilot-instructions.md`；
- Aider：`CONVENTIONS.md`、`.aider.conf.yml`。

不同模型可能生成不同教学内容；对于同一份已经验证的 Content V2 JSON，Python / 模板写入和 QA 是确定性的，不依赖模型 API。

详细兼容矩阵见 [多Agent兼容规范.md](多Agent兼容规范.md)。

## 维护者文档

普通用户通常不需要直接使用模板包工具。维护者入口：

- [更新日志](CHANGELOG.md)
- [模板包标准](docs/template-package-standard.md)
- [模板包作者指南](docs/template-package-authoring.md)
- [模板包发布与安装](docs/template-package-release.md)
- `tools/template_package.py`

模板包工具统一支持 discover、scaffold、validate、promote、archive、verify-release、install、upgrade、rollback 和 release。canonical 模板不应直接覆盖。
