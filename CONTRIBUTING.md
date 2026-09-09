# Contributing

这个仓库首先服务于真实教学工作流，因此变更优先级是：**不破坏真实产物 > 合同一致性 > 可维护性 > 新功能数量**。

## 开始之前

1. 从最新 `master` 建分支，不在旧 worktree 或过期 runtime 上继续开发。
2. 阅读根目录 [AGENTS.md](AGENTS.md) 和目标 Skill 的 `SKILL.md`。
3. 确认你要修改的是哪一层：
   - Skill behavior；
   - Content Contract / schema；
   - deterministic tooling；
   - Office / HTML template；
   - docs / facade。
4. 不要把 Skill 版本、Content Contract 版本和模板版本混为一谈。

## 设计边界

### Agent 负责语义

教学内容、领域理解、课时容量、活动设计、验收标准质量与 pedagogical review 由 Agent 负责。

### Python / tooling 负责确定性事实

Schema、学时、数量、ID、评分守恒、模板映射、reference provenance、Cross-Artifact、render、事务与 runtime fingerprint 等确定性事实由工具负责。

不要用关键词、字符重叠或领域词表去模拟本应由 Agent 完成的教学判断。

## 模板修改

Office 模板属于受保护的 canonical package。修改前请先阅读：

- [Template Package Standard](docs/template-package-standard.md)
- [Template Package Authoring](docs/template-package-authoring.md)
- [Template Package Release](docs/template-package-release.md)

如果只是修改 Skill 行为，不要顺手升级或重写已经通过验证的模板 binary。

## 测试

优先运行与改动直接相关的最小回归，再依赖仓库 CI 完成 Windows/macOS、Package Contracts、Tooling、Release 和 CI Gate 验证。

测试说明见 [docs/test-execution.md](docs/test-execution.md)。

不要为了“变绿”使用：

- `continue-on-error` 绕过真实失败；
- 删除仍然有效的 assertion；
- 把真实 render 降级成文本检查；
- 用旧 CI run 证明新 HEAD；
- 生成看似完整但来源不可靠的 reference 或 handoff。

## Pull Request

PR 建议说明：

- 解决的问题；
- 改动的合同层；
- 明确没有修改的边界；
- 真实产物或 smoke（如果涉及产物）；
- CI / render 状态；
- 尚未解决的问题。

对教学内容的最终判断不能只写“测试通过”；需要真实产物时，应保留人工验收边界。

## 文档

用户可见行为变化请同步更新：

- 根目录 `README.md`（如果影响入口或当前能力）；
- `CHANGELOG.md`；
- 对应 Skill 的 `SKILL.md` / manifest；
- 必要的 `docs/` 说明。

纯内部重构不需要把 README 写成开发日志。
