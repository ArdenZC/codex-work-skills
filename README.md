<div align="center">

# Codex Work Skills

**面向真实教学工作的可复用 AI Skills 仓库**

把课程资料、教学要求和真实办公模板连接起来，让 Agent 负责理解与创作，让确定性工具负责校验、格式保护、渲染和交付。

[![Template package CI](https://github.com/ArdenZC/codex-work-skills/actions/workflows/template-package-ci.yml/badge.svg?branch=master)](https://github.com/ArdenZC/codex-work-skills/actions/workflows/template-package-ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Platforms](https://img.shields.io/badge/CI-Windows%20%7C%20macOS-4C566A)
![Skills](https://img.shields.io/badge/Teaching%20Skills-6-5E81AC)

[快速了解](#快速了解) · [典型工作流](#典型工作流) · [使用方式](#使用方式) · [仓库结构](#仓库结构) · [文档](docs/README.md) · [更新日志](CHANGELOG.md)

</div>

---

## 这是什么

`codex-work-skills` 是一组围绕**真实教学生产任务**构建的 AI Skills。它不是只生成一段文本的 Prompt 集合，而是把 Agent 创作、结构化内容合同、真实 Word/Excel/HTML 产物、确定性 QA、渲染验证和安装/runtime 检查放在同一条生产链上。

仓库当前覆盖六类工作：

- 课程教案 DOCX；
- 实践任务工单 DOCX；
- 理论课离线 HTML 课件；
- 实践课离线 HTML 学习包；
- 整门课程级教学编排（架构评审阶段）；
- 平时成绩记分册 XLS。

> **完整 Skill 的权威来源是 `master`。** GitHub Releases 中的 ZIP 主要用于版本化模板包发布，不等同于完整 Skill 安装包。

## 快速了解

| Skill | 当前版本 / 合同 | 主要产物 | 状态 |
| --- | --- | --- | --- |
| [📝 教案生成器](教案生成器/lesson-plan-docx-generator) | **Skill 2.2.3** · Lesson Content **2.2** · Template **1.1.2** | 理论课教案 `.docx` | ✅ Stable |
| [📋 实践任务工单生成器](实践任务工单生成器/practice-task-workorder-generator) | **2.2.0 / Phase 2.2** · Practice Task **1.1** · WorkOrder Content **1.1** | 学生实践工单 `.docx` | ✅ Stable |
| [🖥️ HTML 课件生成器](HTML课件生成器/courseware-html-generator) | **1.2.1** · Courseware Contract **1.1** | `student.html` + `teacher.html` | ✅ Stable |
| [🧪 实践课 HTML 生成器](实践课HTML生成器/practice-class-html-generator) | **1.2.0** · Practice Class Contract **1.1** | student / teacher 离线 HTML 包 | ✅ Stable |
| [🧭 整门课程编排器](整门课程编排器/whole-course-orchestrator) | **1.0.0-alpha** · Whole-Course Orchestration **1.0** | 素材清单、知识图谱、课次计划、批量 QA、课程包 | ⚠️ Architecture review |
| [📊 平时成绩记分册生成器](平时成绩记分册生成器/course-gradebook-generator) | Template **course-gradebook 1.1.0** | 平时成绩记分册 `.xls` | ✅ Stable |

### 当前稳定能力

**Lesson 2.2.3**

- 一次性确认课程名称、专业、授课对象和课时结构，再进行整门课程规划；
- Lesson DOCX 只承载理论课时；课前固定 **10 分钟**、课中按 **`hours × 45`**、课后固定 **15 分钟**；
- Agent 负责真实教学内容与 pedagogical review，Python 只处理结构、学时、模板、reference provenance、渲染和其他确定性事实；
- 教材、教学资源和参考文献分离；有外部来源时要求可核验，无法核实时宁可留空也不虚构；
- 默认使用受保护的 `lesson-plan v1.1.2` Word 模板。

**Practice WorkOrder 2.2.0**

- **1 Practice Task = 1 WorkOrder = 2 practice hours**；
- 关联模式精确继承已确认课程基本盘和来源任务快照，不重新猜专业或授课对象；
- 考勤固定 **10 分**，任务评价合计 **90 分**，学生结果区保持空白；
- linked / standalone 模式明确分层，正式 linked 生产需要完整 handoff、Cross-Artifact QA 与真实 render gate；
- 默认使用受保护的 `practice-work-order v1.0.0` Word 模板。

**Courseware / Practice HTML**

- Courseware 负责理论课学生展示版与教师逐字稿版；
- Practice 在已讲理论边界内组织实践任务，不脱离上游自行扩展知识；
- 产物为可直接 `file://` 打开的离线 HTML，不依赖 CDN、外部字体或 npm runtime。

## 典型工作流

### 1. 教案 + 实践工单

```text
Confirmed course profile
        ↓
Whole-course planning
        ↓
Theory Lessons ─────────────→ Lesson DOCX
        │
        └─ when workorders are requested
                    ↓
            Practice Task Contract 1.1
                    ↓
            Practice WorkOrder 2.2.0
                    ↓
              WorkOrder DOCX
```

例如一门 `40h = 20h 理论 + 20h 实践` 的课程：

- 不生成实践工单：`10 Lesson + 0 WorkOrder`；
- 生成实践工单：`10 Lesson + 10 WorkOrder`；
- 实践学时始终参与课程总账，但只有用户明确需要时才生成实践侧产物。

### 2. 理论课 HTML + 实践课 HTML

```text
Raw teaching materials
        ↓
Courseware Content Contract 1.1
        ↓
Courseware HTML
  ├─ student.html
  └─ teacher.html
        ↓
Practice Class Content Contract 1.1
        ↓
Practice HTML packages
```

Courseware 是理论语义上游。理论内容发生变化时，优先重新生成对应 Practice；不要让普通用户手工维护复杂 ID 映射。

### 3. 成绩单 → 平时成绩记分册

```text
课程成绩单.xls
      ↓
Gradebook generator
      ↓
平时成绩记分册.xls
```

Windows 优先使用 Excel COM；macOS/Linux 使用 Python + LibreOffice 路径。模板样式和 `.xls` 格式由 Skill 自带合同保护。

### 4. 整门课程编排

```text
Raw course sources
        ↓
Teaching Asset Inventory
        ↓
Course Knowledge Graph + research gaps
        ↓
Content-native Session Plans
        ├─ Courseware HTML Generator
        └─ Practice Class HTML Generator
        ↓
Whole-course Batch QA → clean course package
```

编排器是 Courseware / Practice 的上层，不是第三个 renderer。它会先用 synthetic tests 和架构 QA 检查模板坍缩、素材长期未用、语义视觉退化、知识越界和实践同构；真实 UML failure benchmark 在架构评审前不会重跑。

## 设计原则

### Agent 负责语义，工具负责事实

```text
Agent
├─ 理解课程与资料
├─ 设计教学内容
├─ 判断教学容量
├─ 组织活动与成果
└─ Pedagogical Review

Deterministic tooling
├─ Schema / contract validation
├─ 学时、数量、ID、评分守恒
├─ Template mapping / formatting
├─ Reference provenance
├─ Cross-artifact checks
├─ Render / output QA
└─ Install / runtime fingerprint
```

这条边界是仓库目前最重要的架构原则：**确定性 QA 不替 Agent 创作教学正文，自动化 PASS 也不替代教师最终教学判断。**

### Fail closed，而不是“看起来生成成功”

生产路径遇到关键合同缺失、reference 无法核实、handoff 不完整、render 未验证或 runtime stale 时，优先明确失败或标记未验证，不通过伪造内容、跳过 QA 或静默降级制造“成功”。

### 模板与 Skill 分开版本化

Skill 版本、Content Contract 版本和模板版本独立演进。例如：

```text
Lesson Skill          2.2.3
Lesson Content        2.2
Lesson Word Template  1.1.2
```

升级业务能力并不意味着必须修改已经通过版式与兼容性验证的 Office 模板。

## 使用方式

### 1. 获取仓库

```bash
git clone https://github.com/ArdenZC/codex-work-skills.git
cd codex-work-skills
```

### 2. 选择 Skill

每个 Skill 目录中的 `SKILL.md` 是该 Skill 的**人类可读 canonical contract**。先阅读它，再调用对应脚本或让支持文件/命令执行的 Agent 使用该 Skill。

```text
教案生成器/lesson-plan-docx-generator/SKILL.md
实践任务工单生成器/practice-task-workorder-generator/SKILL.md
HTML课件生成器/courseware-html-generator/SKILL.md
实践课HTML生成器/practice-class-html-generator/SKILL.md
整门课程编排器/whole-course-orchestrator/SKILL.md
平时成绩记分册生成器/course-gradebook-generator/SKILL.md
```

Lesson / WorkOrder 提供独立 installer；首次使用可以先查看：

```bash
python "教案生成器/lesson-plan-docx-generator/scripts/install.py" --help
python "实践任务工单生成器/practice-task-workorder-generator/scripts/install.py" --help
```

仓库同时提供 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 以及 Skill 内的 adapter/facade，便于 Codex、Claude Code、Gemini CLI、Cursor、Windsurf、Continue 等宿主遵循同一份核心合同。

### 3. 不要从 GitHub Release ZIP 安装完整 Skill

Releases 主要发布 canonical Office template package 及其 SHA / metadata。完整运行代码、schemas、facades、installer 与最新合同仍应从仓库 `master` 获取。

## 仓库结构

```text
codex-work-skills/
├─ 教案生成器/
│  └─ lesson-plan-docx-generator/
├─ 实践任务工单生成器/
│  └─ practice-task-workorder-generator/
├─ HTML课件生成器/
│  └─ courseware-html-generator/
├─ 实践课HTML生成器/
│  └─ practice-class-html-generator/
├─ 整门课程编排器/
│  └─ whole-course-orchestrator/
├─ 平时成绩记分册生成器/
│  └─ course-gradebook-generator/
├─ schemas/                 # 跨 Skill 共享合同
├─ tools/                   # template tooling / release / blind evaluation
├─ tests/                   # 跨包与回归测试
├─ docs/                    # 维护、验收、架构、发布与历史归档
├─ .github/workflows/       # Windows / macOS CI 与 template release
├─ AGENTS.md                # 仓库级 Agent 规则
├─ CHANGELOG.md
└─ README.md
```

Generalization、holdout 和阶段性 release evidence 已归档到 `docs/` 对应分类目录；根目录只保留当前使用与维护入口。

## 质量与验证

主 CI 在 Windows 与 macOS 上覆盖核心 Skill、Package Contracts、Tooling、Release 与 CI Gate；需要真实 Office/LibreOffice 行为的路径不会用纯文本检查冒充渲染成功。

- CI workflow：[`template-package-ci.yml`](.github/workflows/template-package-ci.yml)
- 测试执行说明：[docs/test-execution.md](docs/test-execution.md)
- Lesson 人工验收协议：[docs/lesson-acceptance.md](docs/lesson-acceptance.md)
- 模板规范：[docs/template-package-standard.md](docs/template-package-standard.md)

> 自动化 QA 的职责是守住可确定的合同和工程事实。**最终教学内容是否适合真实课堂，仍以教师人工审核为边界。**

## 文档导航

- 📚 [文档索引](docs/README.md)
- 🧾 [更新日志](CHANGELOG.md)
- 🧩 [模板包标准](docs/template-package-standard.md)
- 🛠️ [模板包制作](docs/template-package-authoring.md)
- 🚀 [模板包发布](docs/template-package-release.md)
- ✅ [Lesson Acceptance](docs/lesson-acceptance.md)
- 🤖 [Agent 仓库规则](AGENTS.md)

## Release 说明

当前 GitHub Releases 主要承担**模板包**发布，例如 `lesson-plan` 与 `course-gradebook` 的 canonical archive、SHA-256 和 metadata。Skill 本身按仓库版本演进，不把模板 Release tag 当成 Skill 版本号。

查看全部 Release：<https://github.com/ArdenZC/codex-work-skills/releases>

## 项目定位

这是一个以真实个人教学工作流为驱动的工程型 Skills 仓库。目标不是追求“所有课程都自动完美”，而是把可重复的教学生产流程做成：

**可确认 · 可追踪 · 可验证 · 可渲染 · 可恢复 · 可人工复核**

如果你只想快速体验，从 **教案生成器** 或 **HTML 课件生成器** 开始即可。
