# Claude Code 入口

开始任务前读取 `SKILL.md` 和 `通用提示词.md`。它们是教案生成器的唯一行为规范：使用 Content Contract V2，先一次性确认 `course_name`、`major`、`audience`、`total_hours`（显示 `default_hours=2`，教材建议确认但不阻断），再做课程级项目/任务规划、生成完整 JSON、运行 Content QA 和模板/输出 QA，最后原子提交 DOCX。确认后不得再问模板、输出目录或是否开始生成 DOCX。`references` 只放文献/文档来源，`resources` 放工具/设备/环境/材料；合法 reference 可跨课复用，同课重复和纯资源名不可用。不要复制作答规则、不要使用 sparse input、不要手工改写模板或在教案中写入 QA/AI 说明。
