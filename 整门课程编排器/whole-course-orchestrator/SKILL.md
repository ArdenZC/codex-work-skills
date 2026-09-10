---
name: whole-course-orchestrator
description: 将整套教材或 PPT 编排成可审计的课程级教学素材、知识图谱、内容原生单次课计划、理论—实践边界、批量 QA 和课程包；不负责渲染单次课 HTML。
metadata:
  short-description: 整门课程级教学编排与批量质量审查
---

# 整门课程编排器 1.1

Phase 1.1 adds evidence integrity and downstream batch QA to the 1.0 architecture. The authoritative state model is `required → planned → observed`; a planner declaration is never final evidence, and a planner cannot validate its own output.

## 目标与边界

本 Skill 解决“一次输入整套课程资料后，批量生成整学期课程发生模板坍缩”的课程级问题。它不是第三个 HTML renderer，也不替代 Agent 创作单次课正文：

- Agent 读取用户材料、判断教学问题、创作课程蓝图和下游合同内容；
- Python 负责素材结构化、ID/来源/累计知识状态、内容原生计划、语义视觉约束、跨课 QA、来源 provenance 和安全打包；
- `HTML课件生成器` 继续生成已经规划好的理论课 HTML；
- `实践课HTML生成器` 继续生成已经规划好的实践课 HTML；
- 本阶段不读取旧失败合同/HTML 来修复或重生成真实 UML 课程。

最重要的原则是：**CONTENT DECIDES STRUCTURE.** 页数、布局、图、练习和实践任务由 teaching questions、知识状态、素材价值和学生可观察结果决定，不由固定数量决定。

## 工作流

1. **Source boundary**：登记用户材料、hash、课程范围、学生层次和外部研究策略。用户材料是 primary source。默认允许外部研究，但外部资料只能 supplementary；用户明确禁止联网时整个研究阶段必须禁用。
2. **Teaching Asset Mining**：从 PPT/PPTX 尽可能提取文字、备注、表格、图片、图形、箭头、步骤、代码和练习。旧 `.ppt` 优先 LibreOffice 转换或渲染；OCR 只能是最后手段。每项素材保留来源定位、教学价值、图片引用和 origin。
3. **Course Knowledge Graph**：建立带 prerequisites、depends_on、revisited_sessions、practice_dependencies 的知识节点，并为每节课计算 `knowledge_state_before/after`。Practice core 只能使用 after 状态中的知识。
4. **Research gaps**：先基于图谱和素材检测 `missing_visual`、`weak_example`、`missing_comparison` 等缺口，再统一筛选外部候选来源。外部来源与用户来源分开保存；冲突必须显式报告，不得静默覆盖。
5. **Content-native Session Planner**：先生成具体 `teaching_questions`，再为每个问题选择一个主要 teaching job，最后才选择布局。自然页数可以不同；相邻页面只有引入新证据、案例或练习时才允许重复。
6. **Semantic Visual Planner**：为视觉声明 `visual_intent` 与 `artifact_type`。类型化图必须具备语义元素，例如 `class_model` 的 class compartment、attribute、operation、relationship、multiplicity；只有矩形的占位图 fail closed。优先复用用户图或 semantic redraw，不默认复制外部图片。
7. **Practice Planner**：按能力和 artifact type 选择 task 数量、模态、typed starter 与 editable gap。禁止把所有课都编排成 `core + optional` 或 `2×60`；禁止用 generic TODO 替代有语义的缺口。
8. **Whole-course QA**：跨 session 计算结构、文本、视觉、知识边界、素材使用和实践签名，检查模板坍缩、source underutilization、脚本同构、比较逻辑、quiz distractor、知识越界和研究质量。
9. **Package**：输出干净的教师课程包与独立 evidence 目录。最终包不得同时暴露 `student/` 和 `student-package/student/` 两棵重复学生树；所有用户可见文件名必须经过 `safe_filename()`。

10. **Observe final artifacts**：对 Courseware 从最终 DOM 读取 semantic/source markers；对 Practice 从实际 starter 文件、manifest、QA 和 behavior evidence 读取 typed evidence；对 contact sheet 区分真实浏览器 thumbnail 与无浏览器的 `DEGRADED` fallback。`PLANNED_NOT_OBSERVED`、`NOT_OBSERVED` 和 `UNAVAILABLE_OR_DEGRADED` 必须保留，不能自动升级为 PASS。

## 外部资料规则

来源优先级为：用户资料 > 官方/标准/官方教程 > 高质量高校/专业教学参考 > 社区资料。外部候选必须通过 relevance、authority、student_level_fit、visual_value、teaching_value、recency 和 complexity 过滤，并记录 URL、标题、检索时间、license_note、used_for、selected/rejected reason。

外部资料不能改变用户材料定义的课程范围和顺序；不能大段复制网页原文或在版权不明时直接嵌图。`origin_type` 至少区分 `user-provided`、`external-authoritative`、`external-reference` 和 `derived`，Teaching Asset 还要区分 `user_source`、`web_official`、`web_academic`、`web_professional`、`web_community`、`generated`。

## 失败边界

- 关键 schema、来源定位、累计状态或语义视觉证据缺失时 fail closed；
- 外部研究不可用时记录 `EXTERNAL_RESEARCH_UNAVAILABLE` 并继续使用用户源；
- 用户禁网时记录 `EXTERNAL_RESEARCH_DISABLED_BY_USER`，不得偷偷搜索；
- automated QA 通过不等于教师人工教学验收通过；
- rendered Courseware/Practice QA 通过不等于 browser smoke 或 contact-sheet proof 通过；
- 真实 UML failure benchmark 在架构评审前不重跑，第一阶段状态只能是 `READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW` 或 `WHOLE_COURSE_ARCHITECTURE_BLOCKED`；没有 browser runtime 时必须选择后者。

## 交付合同

核心输出包括：`source-assets.json`、`source-teaching-asset-report.json`、`knowledge-graph.json`、`session-plans.json`、`visual-plans.json`、`practice-plans.json`、`external-source-research.json`、`whole-course-qa.json`、`whole-course-e2e.json`、`contact-sheet-evidence.json`、`source-portfolio.html` 以及干净课程包。它们是给下游 Skill 与教师审计使用的中间层，不是新的 HTML 渲染格式。

## 运行入口

```powershell
python scripts/mine_teaching_assets.py --source-root <ppt-dir> --output-dir <asset-dir> --json
python scripts/build_knowledge_graph.py --course-json <course-map.json> --output-json <knowledge-graph.json> --json
python scripts/plan_sessions.py --course-json <course-map.json> --knowledge-graph <knowledge-graph.json> --assets <source-assets.json> --output-json <session-plans.json> --json
python scripts/plan_visuals.py --session-plans <session-plans.json> --assets <source-assets.json> --output-json <visual-plans.json> --json
python scripts/plan_practice.py --course-json <course-map.json> --knowledge-graph <knowledge-graph.json> --output-json <practice-plans.json> --json
python scripts/review_whole_course.py --session-plans <session-plans.json> --practice-plans <practice-plans.json> --knowledge-graph <knowledge-graph.json> --assets <source-assets.json> --output-json <whole-course-qa.json> --json
python scripts/downstream_e2e.py --output-dir <e2e-dir> --no-browser --allow-degraded-browser --json
python scripts/package_course.py --package-json <package-manifest.json> --output-dir <course-package> --json
```
