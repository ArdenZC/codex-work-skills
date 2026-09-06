---
name: practice-class-html-generator
description: 根据已讲理论或 Courseware Content Contract 1.0 生成通用高职实践课 HTML 材料，包含分层任务、理论关联、互动学习中心、动态基础补给站和教师课堂指导；不用于 DOCX WorkOrder 或单一课程专用生成。
metadata:
  short-description: 生成理论关联、分层任务和互动学习中心 HTML
---

# 实践课 HTML 生成器

## 目标与边界

用 Agent 创作 `Practice Class Content Contract 1.0`，再由内置 Python renderer 稳定生成一套可在机房/实训课堂使用的 HTML。它适用于编程、数据库、软件建模、人工智能、工具操作、设计分析等课程；不要把 C 语言、数据结构或某一种工具写死在产品概念里。

本 Skill 不生成 DOCX，不调用或改写旧 `practice-task-workorder-generator`，不复制其 Phase、Hardening、模板指纹、symlink 防御或复杂事务体系。它只保留合同、理论关联、任务脚手架、HTML 完整性、内部链接和真实互动 QA。

## 工作流

1. 先读取用户资料；有 Courseware Contract 1.0 时优先使用 `--courseware-json`，把已讲 `slide.id` 作为理论范围。
2. 创作 Practice Class Contract 1.0：知识链接和每个任务都写 `source_slide_ids`，任务写 `core / optional / challenge`、步骤、验收、帮助和预计时间，互动写明服务的知识点/任务。
3. 编程 core 提供完整框架和 2—8 个关键 TODO；建模/数据库/工具 core 提供明确场景、起点、操作脚手架和结果验收。
4. 运行 `scripts/render_practice.py`，生成物理隔离的 `student/` 与 `teacher/` 两棵 HTML 目录、合同副本、QA 报告和位于 `student/starter/` 的可选 starter。
5. 运行 `scripts/validate_practice.py`，再用真实浏览器检查 `file://`、内部链接和至少一个内容相关互动。

## 输入模式

- Courseware 联动（首选）：Practice JSON + Courseware Content Contract 1.0；知识点和任务的所有 `source_slide_ids` 必须真实存在且集合一致，core task 必须能追溯到已讲知识点。
- 课件/原始资料：以课件合同为理论边界，教材或讲义只补充操作说明，不扩大 core 范围。
- 独立资料：没有课件时先在 Practice Contract 的 `source_courseware.mode` 标为 `independent`，明确本次理论范围后再设计任务。

## 输出

输出目录至少包含：

- `student/student-task.html`：详细任务书和核心必做 / 有余力 / 提高挑战；
- `student/learning-center.html`：预测、分类、排序、诊断、状态模拟或步骤互动；
- `student/study-guide.html`：与知识链接和理论页对应的学习资料；
- `student/foundation-kit.html`：动态课程/工具/语法/建模基础补给；
- `teacher/teacher-guide.html`：理论桥接、90 分钟节奏、抽查、错误和调节，不放答案倾倒；
- `teacher/teacher-reference.html`：逐任务参考答案、结果、变体、明显错误和验收依据；
- `practice-content.json`、`qa-report.json`；
- 合同有 `starter_assets` 时的 `student/starter/`。

学生页面只能在 `student/` 内导航；教师页面可以链接回学生页面。若上游 Courseware Contract 声明 `course_context`，必须保留语言、工具、平台、软件、数据库方言、框架和其他约束。

实践课 HTML 是普通滚动网页，不套 Courseware 的全屏翻页 runtime。交互只为具体任务服务：按钮应反馈预测/匹配/步骤状态，不做装饰动画。

## QA

脚本检查合同结构、source slide 存在性、core 关联、任务时长、上下文继承、编程脚手架、非编程起点、互动关联、逐任务教师参考、学生/教师输出隔离、HTML 完整性和内部链接。它不会把通过脚本当成内容验收；最终仍要审阅三个优先级最高的事实：学生能否完成、理论是否真的支撑任务、互动是否有教学价值。

## 命令

```powershell
python scripts/render_practice.py `
  --practice-json examples/data-structures.practice.json `
  --courseware-json ..\..\HTML课件生成器\courseware-html-generator\examples\data-structures.example.json `
  --output-dir .\out\data-structures --replace --json

python scripts/validate_practice.py `
  --practice-json examples/data-structures.practice.json `
  --courseware-json ..\..\HTML课件生成器\courseware-html-generator\examples\data-structures.example.json `
  --output-dir .\out\data-structures --json
```

## 适配器

运行 `scripts/install_adapters.py --target-dir <project>` 可写入 namespaced 的 Codex/Claude/Gemini/Copilot/Aider/Cursor/Cline/Continue/Windsurf/OpenCode 规则。默认只写规则；只有显式 `--copy-engine` 才复制 Skill 文件。
