# Aider 约定

先读取 `SKILL.md`、`AGENTS.md` 和 `通用提示词.md`，不要在 Aider 配置中复制 Content V2 规则。把课程资料整理成 `content_contract_version: "2.0"` 的 JSON，先完成课程级项目/任务规划，再运行 `scripts/generate_lesson_plans.py`。

生成器会保护现有 v1.0/v1.1 Word 模板、semantic bookmark、manifest 和格式 QA。所有正文、9 个实施阶段、评价 remarks 和反思必须由 JSON 提供；Python 只做 schema、Content QA、格式化、输出保真和原子提交。非空输出目录须显式使用 `--backup-existing`，Windows/macOS 均运行真实校验。
