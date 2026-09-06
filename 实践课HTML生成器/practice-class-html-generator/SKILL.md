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
2. 创作 Practice Class Contract 1.0：知识链接写 `source_slide_ids`，任务写 `core / optional / challenge`、步骤、验收、帮助和预计时间，互动写明服务的知识点/任务。
3. 编程 core 提供完整框架和 2—8 个关键 TODO；建模/数据库/工具 core 提供明确场景、起点、操作脚手架和结果验收。
4. 运行 `scripts/render_practice.py`，生成五个 HTML、合同副本、QA 报告和可选 `starter/`。
5. 运行 `scripts/validate_practice.py`，再用真实浏览器检查 `file://`、内部链接和至少一个内容相关互动。

## 输入模式

- Courseware 联动（首选）：Practice JSON + Courseware Content Contract 1.0；所有 `source_slide_ids` 必须真实存在，core task 必须能追溯到已讲知识点。
- 课件/原始资料：以课件合同为理论边界，教材或讲义只补充操作说明，不扩大 core 范围。
- 独立资料：没有课件时先在 Practice Contract 的 `source_courseware.mode` 标为 `independent`，明确本次理论范围后再设计任务。

## 输出

输出目录至少包含：

- `student-task.html`：详细任务书和三层难度；
- `learning-center.html`：预测、匹配、诊断或步骤互动；
- `study-guide.html`：与知识链接和理论页对应的学习资料；
- `foundation-kit.html`：动态课程/工具/语法基础补给；
- `teacher-guide.html`：理论桥接、课堂节奏、抽查、错误和调节；
- `practice-content.json`、`qa-report.json`；
- 合同有 `starter_assets` 时的 `starter/`。

实践课 HTML 是普通滚动网页，不套 Courseware 的全屏翻页 runtime。交互只为具体任务服务：按钮应反馈预测/匹配/步骤状态，不做装饰动画。

## QA

脚本检查合同结构、source slide 存在性、core 关联、任务时长、编程脚手架、非编程起点、互动关联、输出文件、HTML 完整性和内部链接。它不会把通过脚本当成内容验收；最终仍要审阅三个优先级最高的事实：学生能否完成、理论是否真的支撑任务、互动是否有教学价值。

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
