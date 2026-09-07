---
name: practice-class-html-generator
description: 根据已讲理论或 Courseware Content Contract 1.0 生成通用高职实践课 HTML 材料，包含分层任务、理论关联、互动学习中心、动态基础补给站和教师课堂指导；四个学生模块与两个教师模块在模块内使用 pane 导航；不用于 DOCX WorkOrder 或单一课程专用生成。
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
3. 知识链接和每个任务都写 `source_slide_ids`，任务写 `core / optional / challenge`、具体步骤、验收、帮助和预计时间，互动写明服务的知识点/任务。结构校验只要求合法的非空最小集合；90 分钟实践的 Gold 目标通常是 7—12 个小任务、约 5 个 core、1 个 optional 和 1 个 challenge，具体数量按课程时长和内容颗粒度判断，质量校验以 warning 给出建议而不是把数量写死。
4. 编程 core 提供完整框架和 2—8 个真实需要学生修改的关键空位；TODO 不能只是解释正确代码。SQL、建模和工具 core 提供等价的可编辑起点、操作脚手架和结果验收。
5. 学习中心按课程需要设计互动 pane，90 分钟 Gold 目标通常为 5—8 个实验区、至少 4 种有教学目的的互动形式，并包含动态过程、诊断/Debug、连续多题或场景挑战。互动数量本身不是质量证明：至少两处应有状态变化或多步推进，至少一处应连续处理多个诊断案例；参数变化、状态变化和检查动作都要立即反馈，并且反馈要能把学生带回具体任务。学习指南通常有 6—10 个任务关联小节，foundation kit 通常有 5—10 个课程动态微专题；短课或窄主题可以更少，但必须保留自助路径。
6. 运行 `scripts/render_practice.py`，生成四个学生模块页、两个教师模块页；每个模块页在同一 HTML 内用 pane 承载合同数组内容，只显示一个活动 pane。输出同时包含合同副本、QA 报告和位于 `student/starter/` 的可选 starter。离线包是一个可导航的小型站点，不是把内容拆成大量详情 HTML。
7. 运行 `scripts/validate_practice.py`，再用真实浏览器在 1366、1440 和 1920 宽度检查 `file://`、六个模块页、pane hash 导航和每一类内容相关互动。

## 输入模式

- Courseware 联动（首选）：Practice JSON + Courseware Content Contract 1.0；知识点和任务的所有 `source_slide_ids` 必须真实存在且集合一致，core task 必须能追溯到已讲知识点。
- 课件/原始资料：以课件合同为理论边界，教材或讲义只补充操作说明，不扩大 core 范围。
- 独立资料：没有课件时先在 Practice Contract 的 `source_courseware.mode` 标为 `independent`，明确本次理论范围后再设计任务。

## 输出

输出目录至少包含：

- `student/student-task.html`：任务路线模块；在同一页内用 pane 承载核心必做 / 有余力 / 提高挑战任务；
- `student/learning-center.html`：学习中心模块；在同一页内用 pane 承载互动实验；
- `student/study-guide.html`：学习指南模块；在同一页内用 pane 承载知识小节；
- `student/foundation-kit.html`：基础补给模块；在同一页内用 pane 承载课程动态微专题；没有补给时保留清晰的空状态；
- `teacher/teacher-guide.html`：教师课堂模块；在同一页内用 pane 承载理论桥接、节奏、抽查、错误和调节，不放答案倾倒；
- `teacher/teacher-reference.html`：教师参考模块；在同一页内用 pane 承载逐任务参考答案和可接受成果；
- `practice-content.json`、`qa-report.json`；
- 合同有 `starter_assets` 时的 `student/starter/`。

模块页的导航卡只承担路线选择，pane 内聚焦一个任务、知识点、互动或教师观察对象；正文保持可读的单列宽度，并提供返回目录、上一项、下一项、标题、预计时间和帮助入口。hash 导航和 `data-pane` 状态保证同一时间只有一个 pane 可见。学生页面只能在 `student/` 内导航，学生可见文字不得暴露合同版本、原始 task/slide/interaction ID 或教师路径；教师页面可以链接回学生页面。若上游 Courseware Contract 声明 `course_context`，必须保留语言、工具、平台、软件、数据库方言、框架和其他约束。

`starter_assets` 必须成为学生可实际取得的相对路径文件入口；纯文本起点可以提供页面内预览，但 draw.io 或其他二进制/可编辑文件不能把原始 XML、压缩内容或内部序列化数据倾倒到学生页面。教师参考必须给出可直接拿来核对的完整成果：编程函数要包含关键 TODO 的逐项答案，SQL 要包含完整可运行查询、预期结果、解释、等价写法和常见错误，建模/工具任务要有可见参考模型或等价操作结果。

实践课 HTML 是普通滚动网页，不套 Courseware 的全屏翻页 runtime。交互只为具体任务服务：按钮应反馈预测/匹配/步骤状态，不做装饰动画。

## QA

脚本检查合同结构、Gold 密度建议、source slide 存在性、core 关联、任务时长、上下文继承、真实 starter 空位、非编程起点、互动关联、renderer family、终止状态、逐任务教师参考、学生/教师输出隔离、学生可见信息、HTML 完整性、pane/hash 内部链接和六个主页面。浏览器 smoke 还要检查所有模块页在多个桌面宽度无横向溢出，状态/诊断/比较互动是否真的改变画面并给出反馈，且每个互动族都有真实可操作控件。它不会把通过脚本当成内容验收；最终仍要把三套真实 HTML 与 Gold Sample 并排审阅，确认任务颗粒度、互动深度、学习资料密度、基础补给、自助路径和课堂节奏达到 Gold。**自动化 PASS 不代表内容验收通过，等待真实 HTML 内容验收。**

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
