# Courseware Content Contract 1.0

该合同是 Agent 与 deterministic renderer 之间的唯一生产输入。它描述教学内容，不允许嵌入任意 HTML/JavaScript runtime。

## 课程级字段

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `contract_version` | string | 固定 `1.0` |
| `course_title` | string | 必填、非空 |
| `chapter_title` | string | 必填、非空 |
| `audience` | string | 必填；默认高职/大专对象，但不自动出现在学生页 |
| `content_reserve_minutes` | integer | 必填、正数；内部储备量，不渲染到学生页 |
| `theme` | string | 可选，默认 `morandi-academy` |
| `slides` | array | 必填，至少 2 页 |

## 页面级字段

每页 `id`、`title`、`layout`、`blocks`、`speaker_script` 和 `suggested_minutes` 必填。`id` 在课程内唯一；`layout` 可用 `hero`、`split`、`grid`、`focus`、`comparison`、`timeline`、`default`。`demo_hint`、`classroom_followup` 和 `pacing_note` 是教师版辅助信息，每项最多渲染一个浅色框，共不超过三个。

`speaker_script` 是自然中文连续讲稿，不是关键词列表。QA 以去空白字符数与 `suggested_minutes` 的最低阈值比较：至少 `max(120, suggested_minutes × 45)` 个有意义字符。这个阈值是最低门禁，不代表替 Agent 决定稿件风格。

## Block 类型

| 类型 | 主要字段 | 用途 |
| --- | --- | --- |
| `paragraph` | `text` | 解释段落 |
| `bullets` | `items` | 要点列表 |
| `cards` | `items: [{title, text, tone?}]` | 并列概念/步骤 |
| `table` | `headers`, `rows` | 对照或数据 |
| `code` | `language`, `code`, `caption?` | 代码与中文讲解 |
| `formula` | `formula`, `explanation?` | 公式/推导 |
| `svg` | `svg`, `caption?` | 自包含教学 SVG |
| `quiz` | `question`, `options`, `answer_index`, `explanation?` | 隐藏答案练习 |
| `stepper` | `steps: [{title, text}]` | 可前后/重置的过程演示 |
| `comparison` | `left_title`, `left`, `right_title`, `right` | 两侧比较 |
| `summary` | `items` | 页面归纳 |

所有可见文本由 renderer 转义；SVG 是唯一允许以受限 markup 进入输出的 block。SVG 必须只有自包含图形，不得含 `<script>`、事件属性、外部 `href/src`、网络 URL 或外部字体。

## 学生/教师分离

renderer 只把 `blocks`、课程/章节标题和页面标题放入学生页。`speaker_script`、`suggested_minutes`、`demo_hint`、`classroom_followup`、`pacing_note` 只进入教师页或 QA。学生页不得通过隐藏 DOM、`data-*` 或 script 字符串泄露这些制作信息；因此 renderer 不把内部字段序列化到学生文档。
