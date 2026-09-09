# Codex Work Skills

一组用于实际教学工作的可复用 AI Skills。目前包含：

- **教案生成器 2.2.1**：批量生成、整理和校验项目化中文职业教育教案 DOCX；Lesson DOCX 只承载理论，实践工单按明确选择交付；
- **平时成绩记分册生成器**：根据课程成绩单生成并校验平时成绩记分册 XLS。
- **实践任务工单生成器 2.1.0**：由 Agent 将 Lesson Practice Task Contract 创作成 WorkOrder Content，再写入真实 Word 学习工单模板（Phase 2.1 Hardening）。
- **HTML 课件生成器 v1.2.1**：由 Agent 创作 Courseware Content Contract 1.1，再确定性生成理论课离线学生展示版与教师逐字稿版 HTML。
- **实践课 HTML 生成器 v1.2.0**：消费已讲理论的 Courseware Content Contract 1.1，按真实任务、理论边界和课堂能力生成可执行实践课 HTML。

AI / Agent 负责理解课程资料和生成结构化内容，Skill 自带脚本负责确定性模板写入、格式保护、事务提交和结果 QA。

> **正式持续验证平台**：Windows、macOS  
> **完整 Skill 安装来源**：仓库 `master`  
> **GitHub Release 中的 ZIP**：版本化模板包，不是完整 Skill 安装包

## 当前版本

| Skill | Skill 版本 | 内容合同 | 当前默认模板 | 状态 |
| --- | --- | --- | --- | --- |
| [教案生成器](教案生成器/lesson-plan-docx-generator) | **2.2.1** | **Lesson Content Contract 2.2**（兼容 2.1/2.0） | `lesson-plan v1.1.2` | 稳定 |
| [平时成绩记分册生成器](平时成绩记分册生成器/course-gradebook-generator) | 当前稳定版 | — | `course-gradebook v1.1.0` | 稳定 |
| [实践任务工单生成器](实践任务工单生成器/practice-task-workorder-generator) | **Phase 2.1 / 2.1.0** | **Practice Work Order Content 1.0** | `practice-work-order v1.0.0` | 联动候选 |
| [HTML 课件生成器](HTML课件生成器/courseware-html-generator) | **v1.2.1** | **Courseware Content Contract 1.1** | `student.html` + `teacher.html` | 稳定 |
| [实践课 HTML 生成器](实践课HTML生成器/practice-class-html-generator) | **v1.2.0** | **Practice Class Content Contract 1.1**（首选上游 Courseware 1.1） | student/ 与 teacher/ 隔离 HTML + JSON/Starter | 稳定 |

**Skill 版本、内容合同版本和模板版本是三个不同概念。** 教案生成器已经进入 **2.2**，但默认 Word 模板仍是经过保护和兼容验证的 `lesson-plan v1.1.2`；升级 Skill 不代表必须把模板版本同步改成 2.2。

完整用户可见更新见 [CHANGELOG.md](CHANGELOG.md)。

双 Skill 的直接流程是 **Raw materials → Courseware → Practice**：Courseware 负责理论课讲授与教师备课，Practice 只在已讲理论边界内组织实践任务。自动化 QA 通过不等于教学内容天然完美，真实教师审核仍是内容质量的最终边界。

## 双 Skill 用户流程

| Skill | 当前版本 | 主要用途 | 输出 |
| --- | --- | --- | --- |
| [📝 教案生成器](教案生成器/lesson-plan-docx-generator) | **2.2.3** | 课程规划、真实参考资料检索、项目化理论教案生成 | `.docx` |
| [📋 实践任务工单生成器](实践任务工单生成器/practice-task-workorder-generator) | **2.2.0 / Phase 2.2** | 根据实践教学单元生成学生任务工单 | `.docx` |
| [📊 平时成绩记分册生成器](平时成绩记分册生成器/course-gradebook-generator) | **当前稳定版** | 根据真实课程成绩单生成平时成绩记分册 | `.xls` |
### 理论课

- 输入：课程资料、课时和学生层次；也可以直接提供已经确认的 Courseware Content Contract 1.1。
- 使用：HTML 课件生成器。
- 输出：`student.html` 和 `teacher.html`。
- Courseware 是理论课上游；它保存可供实践课消费的 stable slide、learning unit、canonical fact 和课程上下文。

### 实践课

- 输入：已经生成并确认的 Courseware Content Contract 1.1，加上课程环境、工具和任务约束。
- 使用：实践课 HTML 生成器。
- 输出：隔离的 `student-package/` 和 `teacher-package/`，以及可直接使用的实践课 HTML、starter 与参考资产。
- Practice 依赖 Courseware 的理论语义，不应脱离已讲理论自行扩展学生任务。

### Fresh Flow 与 Update Flow

Fresh Flow：

```text
Raw teaching materials → Courseware → Practice
```

如果只重新生成 Courseware，而已有 Practice 仍要复用：

- 方案 A：重新生成 Practice（普通用户的推荐方案）；
- 方案 B：使用 compatibility mapping，并验证 `slide`、`learning unit`、`canonical fact` 的对应关系。

不要让普通用户手工维护复杂 ID。Courseware 的理论语义发生变化时，重新生成 Practice 是最可靠的更新路径。

Lesson Acceptance V2 的本地验收、报告和人工复核协议见 [docs/lesson-acceptance.md](docs/lesson-acceptance.md)。

## 教案生成器 2.2.1

## 📝 教案生成器 2.2.3

- 先进入 `INTAKE_PENDING`，在正式规划前一次性确认课程名称、专业、授课对象和总课时；单课课时默认 2 学时，教材建议确认但不是阻断字段；
- 确认后进入 `INTAKE_CONFIRMED` 并自主完成整门课程规划；不再询问 outline、模板、输出目录或是否开始生成 DOCX；
- Lesson DOCX 只承载理论课时，理论课次数量按默认单课课时向上取整并保留余数；只有明确需要实践工单时才生成 Practice Task Contract/handoff；明确不需要时实践学时仍计入课程总账，但不生成实践侧文件；
- 明确需要实践工单时，实践学时必须为正偶数，每个 Practice Task 固定 2 学时，Practice Task 数和 WorkOrder 数严格等于 `practice_hours / 2`；`project_id` 只用于分组，不改变一任务一工单映射；
- 先做整门课程的项目 / 任务规划，再逐课生成完整 Content 2.2；
- 正式路径不再接受旧 sparse JSON 作为生产输入；
- Python 不替模型创作教学正文，只负责校验、格式化、模板映射和文件生成；
- 沿用既有课程重复 / 相似度、课次递进、单课主语义连通和 implementation 逐项 coherence QA，本版本不扩展这些算法；
- 教学评价按课生成，显式分数限定为 **85–96**、步长 **0.5**，并提供 13 项逐课评价备注；
- 支持护理、会计等非 IT 课程，避免固定 IT 场景和模板套话污染；
- `course_materials.textbook` 与 `reference_pool` 分离，逐课只写 `reference_ids`，教材默认不写入 Word references；每个理论 Lesson 至少有 1 项具体 reference；合法文献 references 可跨课复用，纯资源名、泛化占位和虚构书目信息失败；
- references 只表示可阅读/查阅/引用的文献或文档，resources 表示教学工具、设备、环境和材料；参考资料优先使用国内出版物、高校资料、国家/行业/职业标准和国内权威文件，国内占比是质量信号而非硬失败；
- 引入条件式 Practice Task Contract V1，实践任务可以跨多个理论课次；`practice_work_orders=true` 时由 Lesson Agent 检测并调用 WorkOrder Agent 统一交付；不可用时只输出 JSON handoff 并明确状态，不伪造工单 DOCX；false 时不得有 contract 或 handoff；`practice_task_ids` 仅保留 schema 要求的空数组，不得包含任何任务 ID；
- 输出采用 candidate → QA → atomic commit，生成失败不会静默覆盖正式文件；
- 项目内 Full Engine 增加 runtime fingerprint / stale detection，避免新规则配旧 runtime；
- Windows、macOS CI 均执行 Lesson Content、Lesson Package 和 Hardening 回归。

默认 Word 模板仍为 `lesson-plan v1.1.2`，并继续保留 v1.0、v1.1.0、v1.1.1 的兼容路径。

- 正式规划前一次性确认课程名称、专业、授课对象、总课时、理论/实践课时、组织方式和工单偏好；
- 未确认的理论/实践比例、组织方式和工单偏好保持“待确认”，不自动猜 50/50；
- Lesson DOCX 只覆盖理论课时，默认 **2 学时 / 份**；
- 用户确认的课程元数据贯穿内容合同和最终 DOCX，避免专业、授课对象等字段漂移；
- 教材、教学资源、参考文献严格分离，课程教材和 PPT / 课件不作为参考文献；
- 在具备联网能力时优先检索可核验的出版社、高校公开课程、国家/行业标准和权威公开资料，并保留真实责任者信息；
- 参考文献允许跨课合理复用，不为了“去重”强行制造不真实来源；
- 删除机械的“聚焦：xxx”等主题尾缀，正文以自然教学语言体现课次主题；
- 支持不同专业方向，避免固定领域场景污染；
- 教学评价分数限定在 **85–96**，支持 `0.5` 步长；
- 使用受保护的 `lesson-plan v1.1.2` Word 模板生成 `.docx`。

内容合同：**Lesson Content Contract 2.2**；实践侧上游合同：**Practice Task Contract 1.1**。
默认模板：**lesson-plan v1.1.2**。

## 📋 实践任务工单生成器 2.2.0

- **1 个实践教学单元 = 2 学时 = 1 份任务工单**；
- Lesson 只有在用户明确要求生成工单时才建立 Practice Task Contract；
- Practice Task 与 WorkOrder 一一对应；
- 关联工单使用 Practice Task Contract 1.1 和 WorkOrder Content 1.1 的完整来源任务快照；独立模式必须明确选择；
- 课堂考勤固定 **10 分**，其余任务评价合计 **90 分**，总分 100 分；
- 学生任务结果区保持空白，不生成教师答案；
- 使用真实 `practice-work-order v1.0.0` 模板；关联模式默认真实渲染通过后才交付。

它使用现有 `practice-work-order v1.0.0` 模板，不新增模板版本，不生成教师答案，不做成绩册回写，也不进入完整 64 学时 Phase 3 验收。

## HTML 课件生成器 1.2.1

HTML 课件生成器把教材、PPT、讲义、教案或课程资料转成两份完全离线的单文件 HTML：学生课堂展示版和教师逐页备课版。Agent 负责理解资料并创作 `Courseware Content Contract 1.1`；内置 Python renderer 负责固定视觉系统、页面布局、SVG/代码/表格/quiz/stepper、点击/滚轮/键盘翻页、投影增强、输出 QA 和原子提交。

- 学生版是 16:9 投影优先的明亮莫兰迪学院风，保持高课堂信息密度，不显示教师备注、制作/来源措辞或内部时长；
- 教师版左侧与学生页逐页对应，右侧提供可直接朗读的自然中文连续逐字稿和最多三个辅助提示框；
- 合同使用 explicit time model、learning units、canonical facts、`not_yet_taught`、course context、source truth、time evidence 和 theory-led planning；
- 两份 HTML 均无服务器、CDN、外部字体、网络图片和 npm runtime，Chrome / Edge 可直接通过 `file://` 打开；
- renderer 内置全局非交互点击翻页、稳定滚轮翻页和键盘备用；练习按钮、stepper 与投影增强不会误触发翻页；
- 生成后执行合同、学生禁用词、SVG、安全外链、页数/id 对应和单文件 QA，并用真实浏览器验证 click、wheel 和本地离线加载。

详细规则、Content Contract 和调用示例见 [HTML课件生成器/简介.md](HTML课件生成器/简介.md) 与 [HTML课件生成器/courseware-html-generator/README.md](HTML课件生成器/courseware-html-generator/README.md)。

## 实践课 HTML 生成器 1.2.0

实践课 HTML 生成器消费 `Practice Class Content Contract 1.1`，首选直接读取 Courseware Content Contract 1.1，并以真实 `source_slide_ids`、`learning_unit_ids` 和 `canonical_fact_ids` 把知识点、core 任务和互动连接到已讲理论。它保持课程泛化：数据结构可以生成代码 starter，UML 生成建模/工具脚手架，数据库生成 ER/SQL/客户端操作脚手架；foundation-kit 从合同动态生成，不复用旧实践工单的 Phase 或 Hardening 架构。

输出包括 `student/` 下四份学生 HTML、`teacher/` 下教师指南和逐任务教师参考、`practice-content.json`、`qa-report.json`，以及隔离的 `student-package/` / `teacher-package/` 和按需生成的 `student/starter/`。实践侧执行 Editable Gap answer isolation、Executable Reference、Behavioral Verification、Classroom Asset Integrity、Formula Truth 与 manual evidence 状态检查。详细合同和调用示例见 [实践课HTML生成器/简介.md](实践课HTML生成器/简介.md) 与 [practice-class-html-generator/README.md](实践课HTML生成器/practice-class-html-generator/README.md)。

## 五个 Skill 能做什么

| Skill | 主要输入 | 输出 |
| --- | --- | --- |
| 教案生成器 | 课程名称、专业、授课对象、总课时，以及能力图谱、章节任务拆解、课程标准、教材目录、旧教案或其他课程资料 | 项目化 `.docx` 教案 + QA 报告 |
| 平时成绩记分册生成器 | `课程成绩单.xls` 或包含该文件的班级目录 | 平时成绩记分册 `.xls` + QA 报告 |
| 实践任务工单生成器 2.1 | Agent-authored Practice Work Order Content V1，或用于 authoring 的 Lesson Practice Task Contract V1 handoff | 学习工单 `.docx` + Content/Cross-Artifact/Output QA |
| HTML 课件生成器 1.2.1 | 教材、PPT、讲义、教案或 Agent-authored Courseware Content Contract 1.1 | `student.html` + `teacher.html` + QA 报告 |
| 实践课 HTML 生成器 1.2.0 | Courseware Content Contract 1.1 或 Practice Class Content Contract 1.1 | `student/` + `teacher/` 实践课 HTML + `practice-content.json` + `qa-report.json` + packages/starter |

教案资料不完整时可以继续：Agent 会先读取会话和附件，再一次性确认课程基础（单课默认 2 学时；教材建议确认但不阻断）；理论/实践结构和工单偏好未提供时保持“待确认”，确认后按已确认选择完成规划和生成，不再询问模板、输出目录或是否开始生成 DOCX。Lesson DOCX 不替代实践工单；成绩册不能凭空生成成绩，必须提供真实课程成绩单。实践工单不能代写答案，学生任务结果栏保持空白。

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
请帮我安装这个仓库中的「教案生成器 2.2.1」：
https://github.com/ArdenZC/codex-work-skills

请阅读 README、根目录 AGENTS.md、教案生成器/简介.md，以及 lesson-plan-docx-generator 下的 AGENTS.md、通用提示词.md 和 SKILL.md。
完成环境检查、安装和安装验证，不要修改源码或模板。
```

安装 HTML 课件生成器：

```text
请安装当前仓库中的「HTML 课件生成器 1.2.1」：
https://github.com/ArdenZC/codex-work-skills

请先阅读 README、根目录 AGENTS.md、HTML课件生成器/简介.md，以及 courseware-html-generator 下的 AGENTS.md、通用提示词.md 和 SKILL.md。
使用 scripts/install.py 完成安装验证；不要修改源码。生成课件时必须使用 Courseware Content Contract 1.1，运行合同/输出 QA，并用真实浏览器验证 file:// 下的点击和滚轮翻页。
```

安装实践课 HTML 生成器：

```text
请安装当前仓库中的「实践课 HTML 生成器 1.2.0」：
https://github.com/ArdenZC/codex-work-skills

请先阅读 README、根目录 AGENTS.md、实践课HTML生成器/简介.md，以及 practice-class-html-generator 下的 AGENTS.md、通用提示词.md 和 SKILL.md。
使用 scripts/install.py 完成安装验证；生成实践课时优先消费 Courseware Content Contract 1.1，运行合同、输出、引用/行为和浏览器 QA，保持学生包无教师答案泄漏。
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
python "HTML课件生成器/courseware-html-generator/scripts/install.py"
python "实践课HTML生成器/practice-class-html-generator/scripts/install.py"
```

macOS Terminal：

```bash
python3 "教案生成器/lesson-plan-docx-generator/scripts/install.py"
python3 "平时成绩记分册生成器/course-gradebook-generator/scripts/install.py"
python3 "实践任务工单生成器/practice-task-workorder-generator/scripts/install.py"
python3 "HTML课件生成器/courseware-html-generator/scripts/install.py"
python3 "实践课HTML生成器/practice-class-html-generator/scripts/install.py"
```

默认安装到：

```text
~/.codex/skills/
├── lesson-plan-docx-generator/
├── course-gradebook-generator/
├── practice-task-workorder-generator/
├── courseware-html-generator/
└── practice-class-html-generator/
```

可用参数：

- `--dry-run`：只查看安装计划；
- `--skills-dir <目录>`：指定 Skill 目录；
- `--replace`：替换已有安装；
- `--keep-backup`：替换成功后保留上一份安装备份（支持该参数的 installer）；
- `--doctor --json`：由源树只读比对已安装副本的 fingerprint，并要求 `status=current`。

Python 依赖见各 Skill 的 `requirements.txt`。教案生成器安装后可运行其 dependency check；缺少依赖时按提示安装，不会由安装器静默修改 Python 环境。

## 其他 Agent / 项目级规则

五个 Skill 都提供 Agent adapter。默认 adapter 安装只复制规则 / instructions；需要在目标项目中直接运行完整 engine 时，应显式使用对应的 `--copy-engine`。

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
使用教案生成器 2.2.1，根据这份课程标准和教材目录，
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

生成 HTML 课件：

```text
使用 HTML课件生成器，根据我上传的教材第6章内容生成课堂课件。
默认面向大专学生，按约120分钟内容储备准备，但不要在学生课件显示任何时长或制作信息。
同时生成学生展示版和教师备课版。
```

生成实践课：

```text
使用实践课 HTML 生成器，根据已经讲授的 Courseware Content Contract 1.1 生成实践课学生包和教师包；任务必须保留 learning unit、canonical fact 与 source slide 关联，不越过 not_yet_taught 边界。
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
Lesson Skill          2.2.1
Content Contract      2.2 (reads 2.1/2.0)
Word template         lesson-plan v1.1.2
```

双 Skill 版本：

```text
Courseware Skill      1.2.1
Courseware Contract   1.1
Practice Skill        1.2.0
Practice Contract     1.1
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

Courseware 和 Practice 是从仓库 `master` 安装的 Skill；本次 Generalization 1.0 使用独立的 annotated SemVer tags 标识两个 Skill，不创建 GitHub Release，因为仓库现有 Release convention 专用于模板 ZIP。

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
