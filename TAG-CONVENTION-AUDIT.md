# Tag Convention Audit

审计日期：2026-09-09
仓库：`ArdenZC/codex-work-skills`

## Existing convention

仓库已有明确的模板包发布 convention：

- annotated tag 使用 `template/<template-id>/v<version>`；
- GitHub Release 与模板 ZIP、`.sha256` sidecar、metadata 绑定；
- `.github/workflows/template-release.yml` 只服务模板包发布；
- README、`docs/template-package-release.md` 和 `docs/template-package-standard.md` 都把 GitHub Release 定义为模板包分发，不是完整 Skill 安装包。

当前远端 tags：

- `template/course-gradebook/v1.1.0`
- `template/lesson-plan/v1.1.1`

本地还存在一个未出现在远端的兼容性 tag：`template/lesson-plan/v1.1.0`；本轮不删除。

当前 GitHub Releases：

- `template/course-gradebook/v1.1.0`
- `template/lesson-plan/v1.1.1`

没有发现 Courseware / Practice 的既有 tag 或 GitHub Release 命名规范。

## Closeout decision

采用两个独立 Skill 的 annotated SemVer tags：

- `courseware-html-generator-v1.2.1`
- `practice-class-html-generator-v1.2.0`

两个 tag 都指向 docs-only closeout PR 合并后的最终 master；该最终 tree 同时包含 PR #20 与 PR #24 的完整产品树和最终发布文档。

不创建 `dual-teaching-skills-generalization-1.0` milestone tag：现有 convention 按产品/template 版本命名，release notes 和 manifest 已记录 `Dual Teaching Skills Generalization 1.0 achieved`。

不创建 GitHub Release：现有 GitHub Release 机制专用于模板包 ZIP，双 Skill 从仓库 master/tag 安装。

## Gate

本审计只提出命名和目标策略；实际 tag 创建必须在 docs-only closeout PR 合并、final master smoke、版本复核和 clean-tree 检查全部通过后执行。
