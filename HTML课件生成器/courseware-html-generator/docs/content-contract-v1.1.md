# Courseware Content Contract 1.1

`1.1` 是 Courseware HTML Generator 的生产输入。它只描述理论课内容和教学意图；renderer 负责固定的 HTML、CSS、JavaScript、离线资源内联和 QA。输入不允许携带任意脚本或最终 HTML。

## 根级语义

必填字段为：

```json
{
  "contract_version": "1.1",
  "course_title": "课程名",
  "chapter_title": "章节名",
  "audience": "授课对象",
  "session_minutes": 90,
  "prepared_minutes": 100,
  "core_minutes": 80,
  "extension_minutes": 20,
  "learning_units": [],
  "canonical_facts": [],
  "slides": []
}
```

`session_minutes` 是课堂安排，`prepared_minutes` 是本次合同实际准备的教学容量，`core_minutes` 是基础必讲容量，`extension_minutes` 必须等于 `prepared_minutes - core_minutes`。页级 `lecture_minutes + activity_minutes` 必须等于 `suggested_minutes`；所有页的 `suggested_minutes` 之和应与 `prepared_minutes` 基本一致。它们都是教师版/QA 信息，不进入学生可见文字。

`course_context` 可声明语言、工具、平台、软件、数据库方言、框架和其他约束。下游 Practice Skill 可以读取并继承这些值，但 Courseware Skill 不依赖 Practice Skill。

## 理论语义链

`learning_units` 表示可教的知识单元，至少说明学生应知道什么、能做什么、先决条件、尚未讲授的边界和关联事实。`canonical_facts` 是可复核的核心陈述，必须通过 `source_slide_ids` 和 `learning_unit_ids` 回溯到稳定的 `slide.id`。每页使用 `learning_unit_ids`，因此实践课能从 slide 继续追踪到知识单元和事实，而不是只挂一个没有语义的页码。

每页必须有稳定 `id`、标题、布局、讲稿、时长、`teaching_intent` 和 `learning_unit_ids`。`teaching_intent` 包含开场、核心解释、例子、易错点、提问和过渡；讲稿必须是可直接朗读的连续语言。

## Blocks 与资源

支持 paragraph、bullets、cards、table、code、formula、svg、image、quiz、stepper、comparison 和 summary。图片只能引用合同 `assets` 中的本地 PNG/JPEG/GIF/WEBP，renderer 会内联为 data URI；不允许网络图片、外部字体、外链脚本、iframe 或任意事件属性。SVG 必须自包含并承担教学信息。

## 兼容迁移

旧 `1.0` 输入仍可被读取，但只在 `content_contract.normalize_content()` 中一次性迁移：

- `content_reserve_minutes` 不再成为生产字段；根据旧页 `suggested_minutes` 生成显式根级时长；
- 旧页生成保守的学习单元/事实占位并保留原 `slide.id`；
- `suggested_minutes` 被拆为 `lecture_minutes + activity_minutes`，默认把旧页分钟视为讲解容量；
- renderer、Practice 联动和新 schema 均以迁移后的 1.1 对象为准。

新内容不得继续写 1.0 字段。`slide.id`、学习单元 ID 和事实 ID 是跨 Skill 关联键，后续改稿应保持稳定；如果理论含义变化，应新增 ID 或显式迁移，而不是复用旧 ID 表示另一件事。
