# WHOLE_COURSE_FAILURE_BENCHMARK_V1

这是第一阶段架构实现使用的正式失败基准 manifest。仓库只保存来源与旧产物的路径、文件大小和 SHA-256，不复制或覆盖外部 PPT、旧合同、旧 HTML 和 QA 文件。

当前快照完整性：

- 9 份原始 `.ppt`；
- 由旧生产链记录的 9 份转换 `.pptx` hash 与页数；
- 16 份 Courseware contracts、16 份 Practice contracts；
- 16 次理论课的渲染文件与 16 次实践课的渲染文件；
- `qa_contracts` 汇总与逐课 QA；
- `_courseware_build` 中的交付/浏览器审计说明。

失败特征与原始请求保持一致：理论课 `8` 页、固定 layout/job/timing/block 签名，实践课 `2` 个固定形态任务；完整数值见 JSON 的 `failure_findings`。这些旧产物只能作为 regression benchmark，不能作为新生成输入。

如果未来执行 blind retry，只允许读取正式 Skill、原始 PPT 和用户课程要求；读取旧合同、旧 HTML 或逐课修复建议会破坏盲测边界。
