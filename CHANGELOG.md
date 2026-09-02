# 更新日志

本文件记录面向使用者的重要版本变化。模板包发布历史与维护者级技术细节仍保留在 GitHub Releases、PR 和 `docs/` 中。

从 **2026-09-01** 起，教案生成器使用独立的 Skill 版本号；Skill 版本、Content Contract 版本和 Word 模板版本分别管理。

## 实践任务工单生成器 2.0.0 — 2026-09-02

### Phase 2 / 联动候选

- 以 canonical Practice Task Contract V1 为唯一上游事实源，新增 Practice Task → WorkOrder 确定性合同映射和 Cross-Artifact QA，保留 `practice_task_id`、`lesson_ids`、`practice_hours`、交付物、验收、工具/材料及安全/合规约束。
- 增强 WorkOrder Content QA：检查可执行性、可观察交付物、验收覆盖、有限跨专业污染和任务叙述反重复；固定考勤 10、任务项 90、总分 100，学生结果区仍为空。
- 完善独立安装器、共享 schema 依赖 doctor、Codex/Claude/Gemini/Copilot/Aider 适配器和 minimal/full-current/full-stale/inconsistent 运行时识别。
- 增加 WorkOrder 双平台 CI job、classifier routing、Package Contract 和 Cross-Artifact regression；使用现有 `practice-work-order v1.0.0`，不创建模板版本或发布。
- 本阶段不生成教师答案，不进入完整 64 学时 Phase 3，不回写成绩册。

## 实践任务工单生成器 Phase 1 — 2026-09-01

- 新增独立的 `practice-task-workorder-generator` Skill，消费 `Practice Work Order Content V1` 或 Lesson 的 `Practice Task Contract V1` handoff。
- 默认真实模板为 `practice-work-order v1.0.0`；固定出勤 10 分、任务 90 分、总分 100，学生任务结果栏保持空白，并保留模板固定的学生/教师评价。
- 提供基础 Contract QA、Output QA、原子 DOCX 生成、安装器和软件/护理样例；不包含 Phase 2 的 Cross Artifact QA、CI/release 或教师答案。
- 本阶段不创建 tag、GitHub Release 或 template release。

## 教案生成器 2.1.0 — 2026-09-01

### 版本关系

```text
Lesson Skill          2.1.0
Content Contract      2.1
Default Word template lesson-plan v1.1.2
```

### 课程基础与交付

- 任务开始必须一次性确认课程名称、专业、授课对象、总课时、理论/实践学时、组织方式、教材、辅助资料和实践工单需求；单课课时默认 2 学时，确认后不再二次打断。
- 新增 `delivery_plan`、课次 `lesson_type`/理论实践学时、完整课程 outline 和 Practice Task Contract V1；课程、课次和实践任务学时必须守恒。
- `course_materials.textbook` 单独保存教材；教材默认不进入 Word references，也不因课程重复率被迫重复引用。

### Reference 合同

- 2.1 逐课只使用 `reference_ids`，从课程级 `reference_pool` 选择具体、可识别、可核实的文献/文档来源；空数组合法并渲染为空白。
- references 与 resources 边界明确：前者是可阅读/引用的文献或文档，后者是教学工具、设备、环境和材料。
- 合法 reference 可跨课完全重复，退出课程反重复 hard-fail；同课重复 ID、未解析 ID、纯资源名和 generic 占位来源仍失败。
- 禁止为了降低重复率虚构教材、作者、ISBN、出版社、标准编号或公开文献；同一教材重复多课优于编造不同资料。

### 兼容性

- 默认 Content Contract 升为 2.1，运行时继续兼容读取 2.0；Content 2.0 不被静默改写。
- 默认 Word 模板仍为 `lesson-plan v1.1.2`，本版本不修改模板二进制、manifest、fingerprint 或模板 Release。

## 教案生成器 2.0.1 — 2026-09-01

### 版本关系

```text
Lesson Skill          2.0.1
Content Contract      2.0
Default Word template lesson-plan v1.1.2
```

### 行为收口

- 任务开始强制一次性确认课程核心信息：课程名称、专业、授课对象和总课时。
- 单课课时默认 2 学时；教材建议确认但不是阻断字段。
- 完成一次确认后不再在生成 DOCX 前二次确认，也不询问模板或输出目录。
- 明确 `references` 是文献/文档来源，`resources` 是教学工具、设备、环境和材料。
- references 跨课允许完全重复，并退出课程反重复 hard-fail；同课内部重复仍失败。
- 明确 resources/references 边界，不允许为了降低重复率虚构参考文献。

## 教案生成器 2.0.0 — 2026-09-01

### 版本关系

```text
Lesson Skill          2.0.0
Content Contract      2.0
Default Word template lesson-plan v1.1.2
```

2.0 是教案生成能力和内容合同的升级，不是 Word 模板大版本升级。默认模板继续使用经过保护和兼容验证的 `lesson-plan v1.1.2`。

### 主要变化

- 引入严格的 **Lesson Content Contract V2**；正式生产输入使用 `content_contract_version: "2.0"`。
- 生成流程改为先形成整门课程的项目 / 任务 outline，再生成逐课完整内容。
- Python 正式路径不再根据 sparse input、旧套话或固定循环创作教学正文，只负责 schema/runtime 校验、格式化、模板映射和文件生成。
- 增加课程级重复 / 相似度 QA，拒绝长句重复、固定骨架换主题词和过度模板化内容。
- 增加 progression QA：检查前序课次、成果继承、forward transition、substantive anchor 和物理课次顺序。
- 增加 intra-lesson 主语义连通 QA，要求 task、核心教学内容和 deliverable 属于同一语义链。
- implementation 改为逐项 coherence 检查，避免一个教学阶段中夹入明显跨专业内容后仍因整体文本正确而通过。
- 评价分数显式限定为 **85–96**、步长 **0.5**；拒绝全同、严格单调、机械短周期循环等不自然模式。
- canonical 13 项评价备注改为逐课显式生成，统一执行 48 个有意义字符的安全上限。
- 反思允许在课前预生成，但必须围绕本课任务、重难点、组织方式、预期表现、问题和下一课衔接形成差异。
- references 使用 `provided / generic / verified_public` 来源合同；没有真实资料时不再虚构教材、作者、出版社、ISBN、标准编号或年份。
- 支持护理、会计、机械等非 IT 课程，减少固定 IT 场景和默认资源污染。
- QA 报告中的正文诊断限制为 bounded preview + SHA-256，不保存完整输入 JSON 或整段教案正文。
- DOCX 输出采用 candidate → QA → atomic commit；失败不会静默覆盖正式输出。
- External QA、cleanup、rollback 和路径安全得到加强，覆盖 Windows 8.3、symlink、macOS alias / NFC / NFD 等边界。
- 输出文件名、DOCX symlink、模板 fingerprint、semantic bookmarks、布局和内容保真继续执行确定性校验。
- 项目级 adapter 区分 instruction-only 与 `--copy-engine` Full Engine；Full Engine 使用 runtime fingerprint / stale detection，避免新规则与旧 runtime 静默混用。
- Windows 和 macOS required CI 均执行 Lesson Content、Lesson Package 和 Hardening suite。

### 兼容性

继续支持以下 Word 模板路径：

- `lesson-plan v1.0.x`：legacy coordinates；
- `lesson-plan v1.1.0`：semantic bookmarks；
- `lesson-plan v1.1.1`：semantic bookmarks；
- `lesson-plan v1.1.2`：当前默认；
- 既有 compatibility 模板路径。

正式 2.0 生产路径不再把旧 sparse JSON 当作主要输入合同；需要由 Agent 先构造完整 Content V2 JSON。

### 安装与升级

完整 Lesson Skill 仍从仓库 `master` 安装。GitHub Release 中的 `lesson-plan-*.zip` 是版本化模板包，不是 Lesson Skill 2.0 安装包。

Codex 用户可继续使用：

```text
教案生成器/lesson-plan-docx-generator/scripts/install.py
```

项目级多 Agent 规则默认只做 instruction-only 安装；如需在项目内直接运行完整 generator，应显式使用 `install_adapters.py --copy-engine`。

### 验证

2.0 收口阶段已覆盖：

- Windows / macOS Lesson Content、Lesson Package、Hardening CI；
- 数据库、护理和会计领域 deterministic / fresh E2E；
- Content QA、progression、逐项 implementation coherence、DOCX QA；
- LibreOffice render smoke；
- canonical template SHA 稳定性；
- Gradebook、Tooling、Release 和 Package Contract 跨模块回归。

### 已知边界

- LibreOffice render smoke 不等于 Microsoft Word 原生分页或 Word UI 视觉验收。
- `visual-inspection.json` 只有在 Agent / 人工实际查看代表页面后才表示视觉检查完成。
- Reference provenance 的 Python 信任边界为 contract / locator validation；公开资料真实性仍需 Agent 在生成 JSON 前核对。
- 自然语言教学内容的最终专业正确性仍需要真实课程使用验证，deterministic QA 不取代教师或 Agent 对教学语义的判断。

---

## 历史说明

2.0.0 之前，仓库主要使用模板版本和 PR / Release 历史描述教案生成器演进，例如：

- `lesson-plan v1.0`：legacy coordinate 模板；
- `lesson-plan v1.1.0`：引入 Word semantic bookmarks；
- `lesson-plan v1.1.1`：课堂时长和重难点方法标签收口；
- `lesson-plan v1.1.2`：当前默认模板及评价标签泛化。

这些仍是**模板版本历史**，不应与 Lesson Skill 2.0.0 混为同一个版本序列。
