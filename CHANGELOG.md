# 更新日志

本文件记录面向使用者的重要版本变化。模板包发布历史与维护者级技术细节仍保留在 GitHub Releases、PR 和 `docs/` 中。

从 **2026-09-01** 起，教案生成器使用独立的 Skill 版本号；Skill 版本、Content Contract 版本和 Word 模板版本分别管理。

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
