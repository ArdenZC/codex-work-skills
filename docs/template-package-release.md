# 模板包发布与安装

Phase 3.2 在既有 `tools/template_package.py` 上增加发布归档验证和本地安装生命周期。它不维护第二份模板 registry；release metadata 中的 `packages`、`files`、`entry_package` 和 `owner_skill` 仍是唯一归档事实来源。

## 四类对象

- **canonical package**：Skill 目录中由 Git 跟踪的 `assets/templates/<id>/<version>`。它是正式 release 的唯一 source provenance 输入，不是安装目录；external release workspace package 不能通过 `release` 生成带 repository `source_commit` 的 plan。
- **archive bundle**：`<id>-<version>.zip`、同名 `.zip.sha256` 和 `<id>-<version>.metadata.json` 三个文件。ZIP 不含 source commit，且不能覆盖已有文件。
- **installed package**：默认位于仓库根 `installed/template-packages/`，也可以是解析后仍在仓库外的独立目录。每个版本写入 `<id>/versions/<version>/bundle/` 和 `.installation.json`，`active.json` 只指向当前版本。
- **GitHub Release**：由 master-only、手动触发的 workflow 创建。它只是 archive 三文件的远程分发，不是 canonical source，也不替代本地 archive 验证。

## 生成和验证

```bash
python tools/template_package.py release \
  --template-id lesson-plan --version 1.1.0 \
  --output-dir dist/template-packages --json

python tools/template_package.py verify-release \
  --release-dir dist/template-packages --json
```

`release` 只接受当前仓库内真实 canonical package，并先要求 clean worktree；随后对 entry 与 dependency closure 中 archive 会包含的每个文件检查 Git index tracked、工作树和 staged 内容都与当前 HEAD 一致，建立包含 repository path、HEAD blob SHA、SHA-256、大小和精确字节来源的不可变快照。所有文件都要求逐字节一致，任何 `.md`、`.txt`、`.yaml`、`.yml` 的 CRLF/LF 或其他换行差异也会被拒绝；只有这些检查通过后才写入 `source_commit`。它再调用已有 deterministic archive，最后重新验证 sidecar、实际 ZIP SHA、metadata contract、ZIP 顺序、per-file SHA/size 和 ZIP 内容与 HEAD 快照一致，校验失败会清理本次 archive、sidecar、metadata 和 plan。NFC/casefold portable path、依赖闭包、entry identity 和当前 Git-tracked Skill owner validator 仍会验证。Release owner 按 `template_id + format + owner_skill` 解析，不要求仓库存在同版本 canonical package；Release 的 `template_sha256` 只绑定自身 entry package。external future patch 应通过 `archive` 生成 bundle，再由 `verify-release`/`install`/`upgrade` 接受。生成的 `.release-plan.json` 只含稳定 asset 文件名、精确 tag `template/<id>/v<version>`、release name、archive SHA、`prerelease: false` 和 source commit；不含绝对路径。`--dry-run` 不创建 archive、sidecar、metadata 或 plan。

Phase 3.1 的 archive metadata 保持 `tool_version=0.1.0`，以保护已有确定性 archive SHA；Phase 3.2 生命周期状态使用 `RELEASE_TOOL_VERSION=0.2.0` 和 `INSTALL_STATE_SCHEMA_VERSION=1.0`。

## 安装、升级和回滚

```bash
python tools/template_package.py install --release-dir dist/template-packages --json
python tools/template_package.py upgrade --archive path/to/course-gradebook-1.1.1.zip --json
python tools/template_package.py rollback --template-id course-gradebook --json
python tools/template_package.py rollback --template-id course-gradebook --to-version 1.1.0 --json
python tools/template_package.py list-installed --verify --json
```

安装和升级使用模板级 `.lock`，通过 `O_CREAT|O_EXCL` 创建，遇到已有锁直接失败，没有 `--break-lock`。版本目录一旦提交就不可修改、不可覆盖；安装只接受未安装模板，升级必须严格高于 active version，且保留旧版本。rollback 是 installed version state switch：默认切换到 `previous_version`，显式参数切换到任意已安装且不同于 active 的版本；不会下载、重建或删除版本，连续 rollback 可以在 active/previous 之间 toggle。

所有写入都先进入同父目录 stage，再原子交换版本目录和 `active.json`。post-validation、active state 写入或 lock release 失败时，新版本和状态都会恢复，并报告无法清理的 lock/文件。`.installation.json` 只记录相对文件 inventory、archive SHA、entry package 和版本身份，不记录绝对路径。`active.json` 的兼容性由 `schema_version` 决定，`updated_by_tool_version` 只需是严格 ASCII semver。`list-installed` 默认会读取 state/installation schema、扫描 bundle 中的真实文件、重新计算每个文件 SHA，并拒绝 extra/missing/modified/symlink/special/staging/cache 内容；不会启动 LibreOffice 或 full validator。`--verify` 复用这次 inventory 结果，再用当前受信任 owner validator 隔离验证已安装 bundle。

安装器永远不写 canonical source tree，也不执行 bundle 中携带的 Python validator 或其他代码。执行的唯一 validator 是当前仓库 Git index 中受信任的 owner；安装根必须是 `installed/template-packages/` 下的仓库内路径，或解析后完全独立于仓库的外部路径。lexical/resolved containment、symlink 四象限、Windows 8.3 别名、canonical/package/bundle/stage overlap 都 fail closed。

## GitHub 发布

`.github/workflows/template-release.yml` 只有 `workflow_dispatch` 触发，并按 `template_id/version` 使用 `concurrency` 串行化且不取消运行中的发布；先 checkout `master`，通过 live `git ls-remote` 确认远程 master 与 source commit 一致，生成并验证 release bundle 和 plan，确认同名 tag、release、assets 均不存在，再创建带 `operation_id` 的 annotated tag、GitHub Release 和三个 asset。operation_id 不进入 ZIP、sidecar、metadata 或 deterministic release-plan。发布前计算三个本地 asset SHA；发布后下载三个 asset，逐字节比较 local/remote SHA 与 plan，再执行本地 `verify-release`。远程操作出现不确定错误时会 reconcile tag annotation、Release body marker 和 asset context；只有 ownership 可证明的本次资源才会补偿删除，无法证明时不做破坏性清理并提示人工检查。事务失败时不会覆盖或删除预先存在的远程资源。GitHub CLI 的 origin 必须是 GitHub.com HTTPS 或 SSH repository，`--repository` 仅用于断言与 origin 的 owner/name 相同；mismatch、缺失或非 GitHub origin 会在任何远程变更前失败。

## Release 安全上限

`verify-release` 和解压共享保守资源限制：最多 512 个文件、单文件 64 MiB、总未压缩大小 256 MiB、压缩比 200；central directory 在任何解压前检查，文件 SHA 使用流式读取，避免将整个 Office 模板一次性加载到内存。

正式发布需要 GitHub Actions 的 `contents: write` 权限。普通 CI 只运行独立 release 回归，不创建真实 tag 或 GitHub Release。离线环境可以运行 `release`、`verify-release`、`install`、`upgrade`、`rollback` 和 `list-installed`；不具备 `gh`、远程网络或 Microsoft Office 的环境不能执行对应的远程发布/Excel COM 集成步骤。
