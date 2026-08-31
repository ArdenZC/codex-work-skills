# Gemini CLI 入口

先读取 `SKILL.md` 和 `通用提示词.md`，遵循同一份 Content Contract V2 和 QA 流程。正式规划前一次性确认 `course_name`、`major`、`audience`、`total_hours`，摘要显示 `default_hours=2` 并建议确认教材但不阻断；用户确认后直接完成 outline、JSON、QA 和 DOCX，不再询问模板、输出目录或是否开始生成。课程级 outline 必须先于逐课生成；正文、实施、评价备注和反思由 JSON 提供，Python 只格式化、校验和写入受保护模板。`references` 是文献/文档来源，`resources` 是教学工具/设备/环境/材料；合法 reference 可跨课复用，但同课重复、纯资源名和为查重虚构书目信息必须失败。不要接受 sparse input、静默截断或把内部 QA 信息写入 DOCX。
