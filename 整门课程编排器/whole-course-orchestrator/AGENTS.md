# 整门课程编排器 Agent 规则

先阅读 `简介.md`、`通用提示词.md` 和 `SKILL.md`。本 Skill 只编排课程级中间层，不复制 Courseware/Practice renderer，也不把某门课程名写进实现分支。

- 用户资料定义课程范围、术语、顺序和主证据；外部资料只能补充，且必须保留 provenance。
- 先写 Teaching Asset Inventory、Knowledge Graph 和 teaching questions，再规划页面与实践；禁止先套 hero/split/grid/timeline 等布局。
- `artifact_type`、`knowledge_node.type`、practice capability 和 typed starter 是通用适配器入口，不得用 `course_name`、`UML` 或某个文件名选择特殊模板。
- 知识状态按 session 累计；Practice core 不能引用 `knowledge_state_after` 之外或 `not_yet_taught` 之内的知识。
- QA 必须比较结构、内容、时长、视觉、文本、任务和素材使用；页数相同本身不是失败，全部同构才是。
- 真实 failure benchmark 只用于冻结和回归；第一阶段测试使用 concept-heavy、visual/modeling-heavy、procedure/tool-heavy 三种 synthetic course，不生成真实 9 PPT × 16+16。
- 所有输出先写 candidate，再通过 QA 后交付；最终用户包与 evidence 分离，不能复制 student/package 目录。
- 自动结果应报告 `READY_FOR_WHOLE_COURSE_ARCHITECTURE_REVIEW`，不能在真实课程未重跑前宣称 `WHOLE_COURSE_PASS`。
