# Courseware Content Contract 1.0（历史兼容入口）

生产合同已升级到 [Courseware Content Contract 1.1](content-contract-v1.1.md)。本文件只保留历史链接，不能作为新内容的 authoring 模板。

renderer 可以读取旧 1.0 JSON，并在内存中迁移 `content_reserve_minutes`、旧页 `suggested_minutes`、学习单元和事实关联，再按 1.1 合同验证和生成。迁移不会改变稳定的 `slide.id`；新文件必须显式写 `session_minutes`、`prepared_minutes`、`core_minutes`、`extension_minutes`、`learning_units`、`canonical_facts`、页级教学意图和 `lecture_minutes/activity_minutes`。
