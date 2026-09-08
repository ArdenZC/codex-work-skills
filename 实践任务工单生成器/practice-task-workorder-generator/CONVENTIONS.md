# 实践任务工单约定

- 以 `SKILL.md` 为唯一人类合同；机器约束由 Content 1.1、Practice Task Contract 1.1 schema 实现。
- 关联 Content 必须保留 exact source-task snapshot；一项 Practice Task 对应一份 2 学时 WorkOrder。
- 任务项分值由 Agent 按工作量决定，合计 90；固定考勤 10、总分 100；学生任务结果栏留空。
- 每个交付物用内部 ID 映射到至少一条验收标准；学生可见文档隐藏任务、项目和课次 ID。
- 关联模式执行 Content/Cross-Artifact/Output QA 和真实 render；standalone/debug 显式 `--skip-render` 不构成生产通过。
- 旧 V1 只允许显式 `--legacy` 或迁移适配器；安装替换默认清理临时 backup，需保留时显式 `--keep-backup`。
