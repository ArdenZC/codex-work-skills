# Dual Teaching Skills Generalization 1.0

发布日期：2026-09-09
代码基线：`f97f0dcbb88db2c467aefabd77003d1532810a31`
正式 Skill tags：`courseware-html-generator-v1.2.1`、`practice-class-html-generator-v1.2.0`

## Overview

本次发布完成两个可复用教学 Skill 的正式闭环：

- Courseware HTML Generator 1.2.1：理论课课件生成；
- Practice Class HTML Generator 1.2.0：实践课内容生成。

推荐工作流：

```text
Raw teaching materials → Courseware → Practice
```

Courseware 负责理论课的学生展示与教师备课；Practice 消费已经讲授的 Courseware 语义，在理论边界内组织可执行实践任务。

## Courseware release highlights

- 学生 / 教师两份完全离线的单文件 HTML；
- 明亮 16:9 投影布局；
- 点击、滚轮和键盘翻页；
- 可直接朗读的详细教师 speaker scripts；
- theory-led planning；
- session / prepared time model；
- Learning Units 与 Canonical Facts；
- Source Truth 与 Time Evidence；
- Gold speaker-script gate；
- dynamic browser QA；
- 本地 image assets；
- Courseware Content Contract 1.1。

## Practice release highlights

- Courseware semantic linkage；
- `learning_unit_ids`、`canonical_fact_ids` 与 `source_slide_ids`；
- `not_yet_taught` boundary；
- adaptive task planning；
- core / optional / challenge 分层；
- learning center、study guide、foundation kit；
- starter bundle；
- executable reference 与 behavior verification；
- classroom asset passthrough；
- formula truth；
- student / teacher package isolation；
- Practice Class Content Contract 1.1。

## Provenance and validation

- PR #20 merge：`87dad9509c8f416c15a4eddfe14d096a666815a5`。
- PR #24 merge：`f97f0dcbb88db2c467aefabd77003d1532810a31`。
- Accepted Courseware source commit：`1493715169bb6fde12c69260ff795a8402a7a070`。
- Accepted Practice source commit：`8c8cadfdcf8521a7d5a274ebb4d68aced194b794`。
- Frozen Blind Source SHA-256：`2A3EE2FB02E9D149960461C9B32574BAEE672BB753C4202600B617168A9E7732`。
- Final master smoke、core unit tests、quick_validate、render/validate、真实 browser smoke、冻结 deterministic blind regression 和 cross-skill linkage 均通过。
- Final human Courseware Gold / Practice review：PASS。

## Known limitations

1. 自动化 PASS 不等于最终教学质量；教师仍应根据班级实际情况做最终课堂判断。
2. 重新生成 Courseware 后，如果想继续复用旧 Practice，需要 compatibility mapping，或直接重新生成 Practice；普通用户推荐重新生成 Practice。
3. Excel 原生界面、Wireshark、Packet Tracer 等现场工具行为可能仍依赖 manual evidence。
4. Lesson / LibreOffice / Gradebook 等既有环境失败不是这两个 Skill 引入的问题。

GitHub Release not created because the repository's existing release convention is for versioned template packages, not complete Skills.
