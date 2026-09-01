# Phase 1 验收范围

## 必过检查

- manifest fingerprint 与 canonical DOCX SHA-256 一致；
- canonical 文档能打开，包含三张表和固定表头；
- 生成文档保留 canonical 的学生/教师评价结构；
- 出勤为 10 分，任务项合计 90 分，总分 100；
- 每个任务都写入标题、说明、分值、工具/材料、步骤、交付物和验收标准；
- 学生结果列为空；
- candidate、Output QA、atomic commit 任一环节失败都不产生半成品正式输出。

## Phase 1 样例

本阶段用软件类 3 份和护理类 3 份样例做结构与输出 QA。样例输出放在仓库之外，不作为产品资料提交。

## 明确未实现

Phase 1 不宣称实现 Lesson DOCX 与工单的全链路 Cross Artifact QA，不宣称 CI/release，不生成教师答案，也不把工单结果写回成绩册。上述内容留待单独的 Phase 2 work order。
