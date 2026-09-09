# Courseware Content Contract 1.1

`1.1` 是 Courseware HTML Generator 的生产输入。它只描述理论课内容和教学意图；renderer 负责固定 HTML、CSS、JavaScript、离线资源内联和 QA。输入不允许携带任意脚本或最终 HTML。

## Blueprint-first 生成

在 Contract 之前建立公开 Teaching Blueprint，至少包含：`course_goal`、`session_minutes`、`prepared_minutes`、`core_minutes`、`extension_minutes`、`audience_profile`（`level`、`prior_knowledge`、`likely_weaknesses`）、`learning_units`、`canonical_facts`、`not_yet_taught`、`teaching_sequence`（phase/purpose/minutes）、`visual_needs`、`activity_needs`、`likely_misconceptions` 和 `prepared_extension_plan`。蓝图只写可审计的设计摘要，不写 chain-of-thought 或私有推理。

页数、互动数和脚本段落数由目标、事实、对象和时长决定，不是固定模板或质量加分项。`prepared_minutes > session_minutes` 时必须保留教师可见的扩展路径；90/120 情形应能识别 90 分钟核心和 30 分钟扩展，扩展页写 `delivery_track: "extension"`。

## 根级语义

```json
{
  "contract_version": "1.1",
  "course_title": "课程名",
  "chapter_title": "章节名",
  "audience": "授课对象",
  "session_minutes": 90,
  "prepared_minutes": 120,
  "core_minutes": 90,
  "extension_minutes": 30,
  "learning_units": [],
  "canonical_facts": [],
  "slides": []
}
```

`session_minutes` 是课堂安排，`prepared_minutes` 是合同实际准备的教学容量；`core_minutes` 是基础必讲容量，`extension_minutes = prepared_minutes - core_minutes`。页级 `suggested_minutes = lecture_minutes + activity_minutes`，所有页的计划应与 `prepared_minutes` 对齐。时长字段只供教师版/QA，不进入学生页面。

## 理论语义链

`learning_units` 表示可教知识单元，说明学生应知、应会、先决条件、尚未讲授边界和关联事实。`canonical_facts` 是可复核核心陈述，通过 `source_slide_ids` 和 `learning_unit_ids` 回溯到稳定页 ID。跨模块复用的 fact 应增加 `source_refs`、`evidence` 和 `verification`；事实类型可为 direct textual、structured-data、computed、code-derived、relationship/model 或 pedagogical-inference。每个 learning unit 至少被一页的 `learning_unit_ids` 覆盖。

新生成的 source truth gate 在合同之后执行：UTF-8 CSV 使用共享语义模型区分 header row、data row index 与 worksheet row，并确定性验证单元格/简单求和/计数；文本 evidence 检查 quote 和 locator 是否存在。`verification.status` 可为 `verified`、`source-supported`、`inferred` 或 `unverified`，core factual claim 不能依赖 unverified 或 level-4 pedagogical inference。历史合同只可在显式 `migration-trust` 下回归。

每个 `activity_minutes > 0` 的 slide 还应有 `activity_plan`，包含 `type`、`teacher_prompt`、`student_action`、`expected_artifact_or_response`、`check_method` 和 `segments[{label,minutes}]`；分段总和须接近活动分钟。`extensions` 中的备用项必须有 `id/title/minutes/content/activity/use_when`，教师版显示为备用内容，学生版不显示内部验证字段。

每页必须有稳定 `id`、标题、合法布局、讲稿、时长、`teaching_intent`、`learning_unit_ids` 和 blocks。讲稿要自然完成承接、核心解释、当前图/表/代码说明、例子、误解、提问与接话、过渡；长句偶尔复述可成为 warning，整段复制或脚本大部分重复才是 FAIL。有效讲解容量低于约 80 字/分钟由 Pedagogical Review 判为失败，约 120–160 字/分钟是正常目标区间，不是简单 schema 硬错误。

## Blocks 与资源

支持 paragraph、bullets、cards、table、code、formula、svg、image、quiz、stepper、comparison 和 summary。图片只能引用本地安全资产并由 renderer 内联；不允许网络图片、外部字体、外链脚本、iframe 或任意事件属性。SVG 必须自包含并承担教学信息。

## 生成门禁

流程为 Raw Source → Teaching Blueprint → Draft Contract → Structural Validation → Pedagogical Review → 最多两轮 Automatic Contract Repair → Revalidation → Render → Browser QA → Final Package。修复器只可从同一合同推导学习单元链接、意图字段和已声明时长合计，不能编造事实、扩展内容或讲稿。学生页不出现来源、制作信息、内部时长、教师备注或答案；教师页与学生页逐页对应。自动化通过后仍需真实教师打开 HTML 做内容验收。
