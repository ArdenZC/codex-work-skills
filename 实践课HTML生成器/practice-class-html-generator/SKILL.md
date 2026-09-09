---
name: practice-class-html-generator
description: 根据已讲理论或 Courseware Content Contract 1.1 生成通用高职实践课 HTML 材料，包含分层任务、理论关联、按需互动学习中心、动态基础补给站和教师课堂指导；四个学生模块与两个教师模块在模块内使用 pane 导航；不用于 DOCX WorkOrder 或单一课程专用生成。
metadata:
  short-description: 生成理论关联、可执行任务和按需互动学习中心 HTML
---

# 实践课 HTML 生成器

## 目标与边界

Agent 先建立 Practice Blueprint，再创作 `Practice Class Content Contract 1.1`；Python renderer 负责合同、链接、学生/教师隔离、布局、交互和输出 QA。它适用于编程、数据库、软件建模、人工智能、工作表、工具操作和设计分析等课程，不把任何一门课程或工具写成产品分支。旧 1.0 只作为迁移输入，不作为生成目标。

## 自适应生成流程

1. **Theory Boundary**：优先读取上游 Courseware Contract 1.1，确认已讲 `slide.id`、`learning_units`、`canonical_facts` 和 `not_yet_taught`；没有上游时明确 `independent` 理论范围。跨模块复用的事实沿用上游 `source_refs`、`evidence` 和 `verification`，不在 Practice 中覆盖其值。
2. **Practice Blueprint**：先列出学习单元、可练能力、每种活动的 affordance、工具/起点、支架、反馈、覆盖矩阵和不纳入 core 的边界。
3. **Draft Contract**：只为已确认的可观察结果选择任务、starter、学习资料和互动；任务层级、互动数量和学习中心是否存在都由课程证据决定，不能套用固定配额。
4. **Evidence Gates**：新生成先对上游 Courseware 执行 strict Source Truth 和 Time Evidence；Courseware 时间证据失败时 Practice 为 `NOT_RUN`。Core task 可提供可选 `time_breakdown`，用步骤分钟解释 `estimated_minutes`；缺少时是轻量 warning，明显总和不匹配才失败。历史 fixture 仅在显式 `migration-trust` 下回归。
5. **Structural Validation**：运行 `practice_contract.py`，检查理论回链、任务完整性、起点文件、编辑空位、工具环境、学生答案隔离和教师参考。
6. **Pedagogical Review**：运行 `practice_pedagogical_review.py`，分别给课程结构、难度支架、自然形式选择、教师脚本/桥接、任务价值和自助支持提供证据与发现，并纳入时间/事实证据；数量只作描述，不得加分。
7. **Automatic Contract Repair**：允许 `scripts/repair_practice.py` 最多两轮，从既有 Courseware/Practice 合同推导缺失的语义链接、starter 引用、操作语义和教师回链；禁止新增任务、互动或学生答案，禁止把 teacher replacement 泄露到 starter。修复后必须重新跑事实/时间/合同/教学审查。
8. **Revalidation → Render → Browser QA**：所有 strict gates 通过后再生成四个学生模块、两个教师模块，最后在真实浏览器检查 `file://`、pane/hash、链接、反馈和多个桌面宽度。
9. **Final Package**：保留 Agent 草稿、最终合同、repair report、QA 和公开决策摘要；学生包只包含安全 starter，不含教师答案、replacement 元数据、canonical facts 或时间规划字段。

## Practice Blueprint 最小字段

```json
{
  "blueprint_version": "1.0",
  "practice_goal": "学生完成后能产生的可观察结果",
  "duration_minutes": 90,
  "available_learning_units": [{"id": "unit-1", "title": "已讲单元"}],
  "practiceable_abilities": ["观察", "编辑", "解释"],
  "forbidden_not_yet_taught": ["本节不纳入 core 的边界"],
  "activity_affordances": [{"ability": "编辑", "observable_output": "可运行或可核对结果", "feedback": "即时检查方式"}],
  "task_plan": [{"result": "结果", "modality": "由课程选择", "starter_need": "需要/不需要及原因"}],
  "scaffold_strategy": ["基础生起点和卡住时的下一步"],
  "tool_workflow": ["工具起始状态、操作、预期可见结果"],
  "support_strategy": ["study guide、starter、帮助和教师介入"],
  "assessment_strategy": ["完成/运行/操作/解释的核对证据"],
  "coverage_matrix": [{
    "ability": "编辑",
    "learning_unit": "unit-1",
    "canonical_facts": ["fact-1"],
    "allowed_depth": "本次允许深度",
    "suitable_modality": "为什么选这个形式",
    "starter_need": "起点需求",
    "scaffold": "支架和求助路径"
  }]
}
```

coverage matrix 是设计约束，不是数量排行榜。`challenge` 可以为零；五个 core、两个 optional、没有 Learning Center，若 starter、study guide、参考成果和验收足够，都是合法形态。Learning Center 只在有即时反馈、状态变化、连续诊断、多步操作或场景判断等真实 affordance 时出现。

## 任务语义完整性

- `implementation`/`code_editing`：提供真实 starter、可编辑空位或明确 edit target、验收和帮助；学生起点不含完整 replacement。
- `debugging`/`diagnosis`：写明 symptom、faulty artifact、expected behavior、diagnosis target、repair target 和验收。
- `modeling`/`model_editing`：提供可编辑模型、required edit、modeling constraints 和参考成果。
- `tooling`/`tool_operation`：写明 tool、starting state、具体 operations 和 expected observable result。
- `experiment`：写明 variable、control、operation、observation 和 expected reasoning。

不同课程可以选择不同能力组合；不要因为模板熟悉而强加代码 starter、固定互动族或统一提交物。默认验收是完成、运行/操作正确、能解释关键判断，除非用户明确要求，不加截图、报告或收走产物。

## 输出与 QA

输出四个学生模块 `student/student-task.html`、`student/learning-center.html`、`student/study-guide.html`、`student/foundation-kit.html`，两个教师模块 `teacher/teacher-guide.html`、`teacher/teacher-reference.html`，以及合同、QA、学生包和教师包。Learning Center 可以为空；foundation kit 可以为空，但要给出自助路径的质量解释。

```powershell
python scripts/teaching_blueprint.py --blueprint-json <blueprint.json> --json
python scripts/repair_practice.py --practice-json <draft.json> --courseware-json <courseware.json> --output-json <repaired.json> --max-rounds 2
python scripts/render_practice.py --practice-json <repaired.json> --courseware-json <courseware.json> --output-dir <out> --replace --json
python scripts/validate_practice.py --practice-json <repaired.json> --courseware-json <courseware.json> --output-dir <out> --json
```

学生页面不得暴露合同版本、内部 ID、教师参考、replacement 或答案。真实浏览器须检查四个学生页、两个教师页、pane/hash 导航、starter 链接、每类实际存在的互动以及按钮反馈；在 1366、1440 和 1920 宽度确认无横向溢出。自动化 PASS 不等于教师内容验收通过。

## 适配器

运行 `scripts/install_adapters.py --target-dir <project>` 可写入 namespaced 的 Codex/Claude/Gemini/Copilot/Aider/Cursor/Cline/Continue/Windsurf/OpenCode 规则；只有显式 `--copy-engine` 才复制 Skill 文件。

## G3 正式完整性规则（Skill 1.2.0）

新生成必须先读取 `docs/integrity-contract-v1.md`，遵循 Integrity Contract 1.0；Content Contract 仍为 1.1。使用 strict evidence mode；migration-trust 仅用于历史回归。先验证草稿，再渲染最终内容，不手工修补已生成包。所有行为、资产、公式和规划证据按文档保存，自动评分不得掩盖 DEGRADED 或不可用检查。
