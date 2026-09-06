---
name: practice-class-html-generator
description: 根据已讲理论或 Courseware Content Contract 1.0 生成通用高职实践课 HTML 材料，包含分层任务、理论关联、互动学习中心、动态基础补给站和教师课堂指导；不用于 DOCX WorkOrder 或单一课程专用生成。
metadata:
  short-description: 生成达到 Gold 内容密度的理论关联、分层任务和互动学习中心 HTML
---

# 实践课 HTML 生成器

## 目标与边界

用 Agent 创作 `Practice Class Content Contract 1.0`，再由内置 Python renderer 稳定生成一套可在机房/实训课堂使用的 HTML。它适用于编程、数据库、软件建模、人工智能、工具操作、设计分析等课程；不要把 C 语言、数据结构或某一种工具写死在产品概念里。

本 Skill 不生成 DOCX，不调用或改写旧 `practice-task-workorder-generator`，不复制其 Phase、Hardening、模板指纹、symlink 防御或复杂事务体系。它只保留合同、理论关联、任务脚手架、HTML 完整性、内部链接和真实互动 QA。

## 工作流

1. 先读取用户资料；有 Courseware Contract 1.0 时优先使用 `--courseware-json`，把已讲 `slide.id` 作为理论范围。
2. 先按 [内容质量 Gold Benchmark](references/content-quality-gold-benchmark.md) 做教学设计审查，再创作 Practice Class Contract 1.0。不要把 Gold Sample 中的课程知识或历史提交要求照搬到新课程。
3. 知识链接和每个任务都写 `source_slide_ids`，任务写 `core / optional / challenge`、至少 3 个具体步骤、验收、帮助和预计时间，互动写明服务的知识点/任务。90 分钟实践通常拆成 7—12 个小任务，至少 5 个 core、1 个 optional、1 个 challenge。
4. 编程 core 提供完整框架和 2—8 个真实需要学生修改的关键空位；TODO 不能只是解释正确代码。SQL、建模和工具 core 提供等价的可编辑起点、操作脚手架和结果验收。
5. 学习中心设计 5—8 个实验区，至少 4 种互动形式，并包含动态过程、诊断/Debug、连续多题或场景挑战。学习指南设计 6—10 个任务关联小节，foundation kit 设计 5—10 个课程动态微专题。
6. 运行 `scripts/render_practice.py`，生成物理隔离的 `student/` 与 `teacher/` 两棵 HTML 目录、固定入口页与按合同动态生成的详情页、合同副本、QA 报告和位于 `student/starter/` 的可选 starter。离线包是一个可导航的小型站点，不是把所有内容塞进一个 HTML 文件。
7. 运行 `scripts/validate_practice.py`，再用真实浏览器在 1366、1440 和 1920 宽度检查 `file://`、内部链接、详情导航和每一类内容相关互动。

## 输入模式

- Courseware 联动（首选）：Practice JSON + Courseware Content Contract 1.0；知识点和任务的所有 `source_slide_ids` 必须真实存在且集合一致，core task 必须能追溯到已讲知识点。
- 课件/原始资料：以课件合同为理论边界，教材或讲义只补充操作说明，不扩大 core 范围。
- 独立资料：没有课件时先在 Practice Contract 的 `source_courseware.mode` 标为 `independent`，明确本次理论范围后再设计任务。

## 输出

输出目录至少包含：

- `student/student-task.html`：任务索引，只放核心必做 / 有余力 / 提高挑战的摘要卡；详情由合同中的任务动态生成到 `student/tasks/<task-id>.html`；
- `student/learning-center.html`：互动索引，只放实验区摘要；每个实验区详情动态生成到 `student/learning/<learning-id>.html`；
- `student/study-guide.html`：学习资料索引；每个知识小节详情动态生成到 `student/guides/<guide-id>.html`；
- `student/foundation-kit.html`：基础补给索引；每个微专题详情动态生成到 `student/kit/<kit-id>.html`；
- `teacher/teacher-guide.html`：理论桥接、90 分钟节奏、抽查、错误和调节，不放答案倾倒；
- `teacher/teacher-reference.html`：逐任务参考答案索引；逐任务详情动态生成到 `teacher/references/<task-id>.html`；
- `practice-content.json`、`qa-report.json`；
- 合同有 `starter_assets` 时的 `student/starter/`。

入口页只展示摘要，详情页必须用单列阅读结构承载一个任务/知识点/互动，正文最大宽度约 720–920px，并提供返回索引、上一项、下一项、标题和预计时间/帮助入口。学生页面只能在 `student/` 内导航，学生可见文字不得暴露合同版本、原始 task/slide/interaction ID 或教师路径；教师页面可以链接回学生页面。若上游 Courseware Contract 声明 `course_context`，必须保留语言、工具、平台、软件、数据库方言、框架和其他约束。

实践课 HTML 是普通滚动网页，不套 Courseware 的全屏翻页 runtime。交互只为具体任务服务：按钮应反馈预测/匹配/步骤状态，不做装饰动画。

## QA

脚本检查合同结构、Gold 密度底线、source slide 存在性、core 关联、任务时长、上下文继承、真实 starter 空位、非编程起点、互动关联、renderer family、终止状态、逐任务教师参考、学生/教师输出隔离、学生可见信息、HTML 完整性和内部链接。浏览器 smoke 还要检查所有入口/详情页在多个桌面宽度无横向溢出，且每个互动族都有真实可操作控件。它不会把通过脚本当成内容验收；最终仍要把三套真实 HTML 与 Gold Sample 并排审阅，确认任务颗粒度、互动深度、学习资料密度、基础补给、自助路径和课堂节奏达到 Gold。**自动化 PASS 不代表内容验收通过，等待真实 HTML 内容验收。**

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
