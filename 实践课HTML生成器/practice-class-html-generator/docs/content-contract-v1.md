# Practice Class Content Contract 1.0

Practice Contract 是 Agent 与 renderer 之间的内容边界。它描述一节实践课的教学设计，不描述 HTML/CSS，也不要求某一种课程或语言。

## 根字段

```json
{
  "contract_version": "1.0",
  "course_title": "课程名",
  "practice_title": "本次实践标题",
  "audience": "授课对象",
  "duration_minutes": 90,
  "source_courseware": {
    "mode": "courseware",
    "contract_version": "1.0",
    "chapter_title": "理论章节",
    "taught_slide_ids": ["s01", "s02"]
  },
  "knowledge_links": [],
  "tasks": [],
  "learning_center": [],
  "study_guide": [],
  "foundation_kit": [],
  "teacher_guide": {},
  "starter_assets": []
}
```

`source_courseware.mode` 为 `courseware` 时，CLI 必须收到 `--courseware-json`。`knowledge_links[].source_slide_ids` 必须来自该 Courseware Contract 的稳定 `slide.id`，并且 core task 至少通过一个 knowledge link 回溯到已讲理论页。`independent` 模式允许 source slide 列表为空，但仍应在合同中写出本次理论范围。

## 知识链接与任务

知识链接至少包含 `id`、`title`、`summary`、`source_slide_ids`、`student_can_do`。任务至少包含 `id`、`level`、`title`、`knowledge_link_ids`、`modality`、`overview`、`steps`、`acceptance`、`help_refs`、`estimated_minutes`。

`level` 只能是 `core`、`optional`、`challenge`。`modality` 可以是 `interactive`、`coding`、`modeling`、`database`、`tooling`、`analysis`、`mixed`。编程 core 通过 `starter_asset_ids` 绑定脚手架，并在 starter 中保留 2—8 个关键 TODO；非编程 core 通过 `scaffold` 写出明确起点和操作路径。

## 互动与学习资料

`learning_center` 中每项都要写 `knowledge_link_ids`、`task_ids`、`purpose` 和 `interaction`。目前 renderer 支持 `choice`、`match`、`stepper` 三种内容驱动互动。`study_guide` 按知识链接组织，`foundation_kit` 按课程动态列出基础缺口，不使用固定的 C 语言补给站字段。

## 教师指导

`teacher_guide` 应包括 `purpose`、`theory_bridge`、`timing`、`task_guidance`、`common_errors`、`pace_adjustments` 和 `closing_checks`。它服务于课堂控制和抽查，不要求写成逐字稿。
