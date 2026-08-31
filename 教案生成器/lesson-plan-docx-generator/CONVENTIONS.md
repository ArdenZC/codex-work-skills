# Aider 约定

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`，不要在 Aider 配置中复制 Content V2 规则。任务开始先一次性确认 `course_name`、`major`、`audience`、`total_hours`，显示 `default_hours=2` 并建议确认教材但不阻断；确认后直接完成课程级项目/任务规划、JSON、QA 和 DOCX，不再询问模板、输出目录或是否开始生成。把课程资料整理成 `content_contract_version: "2.0"` 的 JSON，再运行 `scripts/generate_lesson_plans.py`。

生成器会保护现有 v1.0/v1.1 Word 模板、semantic bookmark、manifest 和格式 QA。所有正文、9 个实施阶段、评价 remarks 和反思必须由 JSON 提供；Python 只做 schema、Content QA、格式化、输出保真和原子提交。`references` 只放文献/文档来源，`resources` 放教学工具、设备、环境和材料；reference 可跨课复用，但同课重复和纯资源名必须失败。非空输出目录须显式使用 `--backup-existing`，Windows/macOS 均运行真实校验。
