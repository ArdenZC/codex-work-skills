---
name: courseware-html-generator
description: 根据教材、PPT、讲义、教案或课程资料生成离线单文件 HTML 学生展示版和教师逐字稿备课版；适用于需要稳定课堂交互、SVG/代码/表格/练习和逐页讲稿的高职或大专理论课程。
metadata:
  short-description: 生成离线学生展示版与教师逐字稿版 HTML 课件
---

# HTML 课件生成器

## 目标与边界

Agent 负责读取资料、建立课程蓝图并创作 `Courseware Content Contract 1.1`；内置 Python 负责确定性校验、布局、CSS/JavaScript、单文件输出和 QA。不要让模型直接拼接最终 HTML，也不要在输入中提交任意 JavaScript。旧 1.0 只作为一次性迁移入口。

本 Skill 独立于教案 DOCX、实践任务工单和 Practice HTML Skill。Practice 可以消费本 Skill 的稳定 `slide.id`、`learning_units` 和 `canonical_facts`，但 Courseware 不反向依赖 Practice，也不绑定任何课程主题。

## 自适应生成流程

严格按以下顺序工作，并为每一步留下可公开、可复核的结果：

1. **Raw Source**：读取用户资料，区分资料事实、课程约定和未知项；未知事实不得伪造。为事实建立 Source Truth provenance：`source_refs`、`evidence`、`verification.status`；按 direct text、structured data、computed、code-derived、relationship/model、pedagogical inference 区分证据强度。
2. **Teaching Blueprint**：先写课程目标、`session_minutes`/`prepared_minutes`、对象起点与弱项、学习单元、canonical facts、`not_yet_taught` 边界、教学阶段、视觉/活动需求、误解点和预备扩展方案。
3. **Draft Contract**：依据蓝图创作 1.1 JSON。每个学习单元都要有至少一页承载，核心路径和扩展路径要能被教师识别。
4. **Source/Time Gates**：新生成先运行 `source_truth_validator.py --mode strict` 与 `activity_time_reviewer.py --mode strict`。CSV 由共享语义模型推导 header/data row/worksheet row、列号和 cell address；禁止按课程或案例硬编码结果。每个正 `activity_minutes` 必须有 type、教师提示、学生动作、预期产物、检查方法及分段分钟数；`prepared_minutes` 由核心路径和真实 extension reserve 组成。
5. **Structural Validation**：运行 `content_contract.py`，检查字段、语义链、时长、资源和学生答案隔离。
6. **Pedagogical Review**：运行 `pedagogical_review.py`，判断页序、讲稿可讲量、视觉解释、例子、误解、提问和过渡，并纳入 source/time evidence。讲稿的有效容量低于约 80 字/讲解分钟判为内容失败；约 120–160 字/分钟是正常目标区间，偏低是 DEGRADED 信号，不把它伪装成结构错误。
7. **Automatic Contract Repair**：只允许 `scripts/repair_courseware.py` 最多修复两轮可从同一合同推导的遗漏，例如学习单元链接、教学意图字段和已声明页级时长合计；不能凭空补事实、扩展内容或讲稿。修复后必须重新做所有 gates、结构和教学审查。
8. **Revalidation → Render → Browser QA**：只有全部门禁通过才运行 renderer；真实浏览器打开 `file://` 学生页，验证点击、滚轮、键盘和控件边界。时间证据失败时下游 Practice 为 NOT_RUN。
9. **Final Package**：只交付通过门禁的 student/teacher HTML、QA、最终合同和公开生成决策摘要；保留 Agent 草稿与修复报告供审计。

蓝图是公开规划摘要，不包含 chain-of-thought、私有推理或隐藏思考。课程数量、页数和互动数量都只能由目标、时长和学习证据推导，不能作为固定模板或通过数量获得质量分。

## Teaching Blueprint 最小字段

```json
{
  "blueprint_version": "1.0",
  "course_goal": "学生完成后能做出的可观察结果",
  "session_minutes": 90,
  "prepared_minutes": 120,
  "core_minutes": 90,
  "extension_minutes": 30,
  "audience_profile": {
    "level": "授课层级",
    "prior_knowledge": ["已确认的前置知识"],
    "likely_weaknesses": ["可能卡点"]
  },
  "learning_units": [{"id": "unit-1", "title": "知识单元"}],
  "canonical_facts": [{"id": "fact-1", "statement": "可复核事实"}],
  "not_yet_taught": ["明确留到后续的内容"],
  "teaching_sequence": [{"phase": "进入", "purpose": "为什么现在讲", "minutes": 10}],
  "visual_needs": ["必须看懂的图/表/代码"],
  "activity_needs": ["需要学生判断或操作的节点"],
  "likely_misconceptions": ["可观察误解"],
  "prepared_extension_plan": ["教师在有余量时展开的内容"]
}
```

`prepared_minutes` 大于 `session_minutes` 时必须显式区分核心路径和扩展路径；扩展内容每项有 `title`、`minutes`、`content`、`activity`、`use_when`，教师可见为“备用内容 / 讲得快时使用”，学生页不显示制作时长。若没有扩展容量，蓝图和合同应明确写零，而不是虚构扩展页。历史合同只可在显式 `migration-trust` 下回归；它不会把缺证据事实标成 verified。

## 合同与内容要求

- 根级必须提供四个时长字段、`learning_units`、`canonical_facts` 和 `slides`；每个 learning unit 至少由一页的 `learning_unit_ids` 覆盖。
- 每页提供稳定 `id`、合法布局、`lecture_minutes`、`activity_minutes`、`suggested_minutes`、完整 `teaching_intent`、`learning_unit_ids`、blocks 和连续 `speaker_script`。`suggested_minutes` 必须等于前两者之和。
- 讲稿要自然完成进入/承接、当前图表/代码/表格说明、核心解释、例子、易错点、提问与接话和过渡；不要机械拼成固定段落，也不能用“讲一下定义”“追问学生”或提示框凑字数。
- 学生页不得出现教师备注、来源、合同/制作信息、内部时长或答案。教师页与学生页逐页对应。
- block 只使用合同声明的 paragraph、bullets、cards、table、code、formula、svg、image、quiz、stepper、comparison、summary。SVG 必须自包含并承担教学信息；资源离线内联。
- 学生页保持明亮冷白/浅灰蓝课堂视觉，避免深色背景、粗色左边条和装饰性动画。

## 运行时与 QA

renderer 内置并固定：非交互区域真实单击翻页；文字拖选不翻页；按钮、链接、输入、选择器和 `[role=button]` 不误翻页；滚轮使用非被动监听、deltaMode 归一化、累积阈值和冷却；键盘支持箭头、PageUp/PageDown、Space、Home/End；投影增强只改变对比度。

```powershell
python scripts/teaching_blueprint.py --blueprint-json <blueprint.json> --json
python scripts/repair_courseware.py --content-json <draft.json> --output-json <repaired.json> --max-rounds 2
python scripts/render_courseware.py --content-json <repaired.json> --output-dir <out> --replace --json
python scripts/validate_courseware.py --content-json <repaired.json> --student-html <out>/student.html --teacher-html <out>/teacher.html --json
```

生成失败时不覆盖正式目录。交付前必须真实打开 HTML，至少检查背景/标题/普通卡片/SVG/代码区的点击、上下滚轮、一次 wheel 不多跳页，以及答案/stepper/投影控件不会触发翻页。

## 适配器

运行 `scripts/install_adapters.py --target-dir <project>` 可写入 namespaced 的 Codex/Claude/Gemini/Copilot/Aider/Cursor/Cline/Continue/Windsurf/OpenCode 规则；只有显式 `--copy-engine` 才复制 Skill 文件。

## G3.2 Courseware Gold 闭环（Skill 1.2.1）

新生成必须先读取 `docs/planning-integrity-v1.md`，遵循 Integrity Contract 1.0；Content Contract 仍为 1.1。Courseware 默认 `session_delivery_mode: "theory-led"`，活动可声明 `activity_role`：教师带领演示、全班引导推理、学生短检查或学生独立练习。存在独立 Practice 时，理论课不能让独立练习主导课堂活动；边界审查是启发式，不使用固定比例。

讲稿有两个不同语义：80 个有效字符/讲解分钟是硬下限，120–160 是 Courseware Gold 的正常生成目标。正常目标不是 schema 配额；不得用重复扩句填充。Gold 批量门禁记录合格核心页、字符/讲解分钟、最小/中位/最大密度、低于正常目标比例、近下限比例、重复 n-gram、重复段落和代码/表格/SVG 的视觉解释覆盖。封面、目录、极短总结和扩展页不进入密度分母；低于正常目标低于 25% 才可通过该 Gold 门禁，超过 50% 进入 DEGRADED，接近全量或触碰硬下限则 FAIL。

生成顺序固定为：blocks + 教学意图 + 视觉/代码/表格 + lecture_minutes → script planning → 完整 speaker_script。教师讲稿必须直接说明当前图表/代码/表格：代码讲关键行和结构，表格讲列/行和比较，SVG 讲节点/箭头/变化。教师页活动只显示人类标签；“讲得快时可补充”的 reserve 放在教师备用内容中，不增加课堂主线分钟。先验证草稿，再渲染最终内容，不手工修补已生成包。所有行为、资产、公式和规划证据按文档保存，自动评分不得掩盖 DEGRADED 或不可用检查。
