# 整门课程编排器

本目录实现 Whole-Course Orchestration 1.1 的第一阶段架构与证据完整性层。它输出课程级 JSON 合同、最终 artifact evidence、下游 E2E 结果与干净课程包，供稳定的 Courseware / Practice HTML Skill 消费。

证据状态必须区分 `required`、`planned` 和 `observed`。最终 DOM/file/contact-sheet 才能产生 observed evidence；semantic marker plumbing 不能代替 typed structure；真实浏览器部分失败是 `FAIL`，无浏览器运行时才是 `DEGRADED`。正式 strict gate 未完成时 Whole-Course final status 必须保持 `WHOLE_COURSE_ARCHITECTURE_BLOCKED`。

## 不做什么

- 不渲染 HTML、CSS 或 JavaScript；
- 不以课程名、文件名或 UML 特例选择模板；
- 不把旧 16+16 失败合同读取为新生成输入；
- 不在架构评审前运行真实 9 份 PPT 的 whole-course retry。

详细工作流见 [SKILL.md](SKILL.md)、[Phase 1.1 closeout report](../../WHOLE-COURSE-PHASE-1.1-CLOSEOUT-REPORT.md)、[failure benchmark replay report](../../benchmarks/WHOLE_COURSE_FAILURE_BENCHMARK_V1/FAILURE-BENCHMARK-REPLAY-REPORT.md) 和仓库根目录 [WHOLE-COURSE-ARCHITECTURE-REPORT.md](../../WHOLE-COURSE-ARCHITECTURE-REPORT.md)。
