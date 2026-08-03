# 模板包维护工具

仓库根目录的 `tools/template_package.py` 是版本化模板包的通用维护入口。它不依赖 Word 或 Excel 的字段注册表，也不把教案或成绩册的业务定位规则复制到工具中；业务规则仍由每个 Skill 自己的 manifest 和 `scripts/validate_template.py` 负责。

## 发现

```bash
python tools/template_package.py discover --json
```

工具扫描 `**/assets/templates/<template-id>/<version>/manifest.yaml`，检查 manifest、严格 ASCII `MAJOR.MINOR.PATCH`、包目录版本、模板文件、SHA-256 fingerprint、重复身份、所属 Skill 的真实 validator 和规范化路径。当前仓库使用 `v1.0.0` 这样的目录名，工具将它与 manifest 的 `1.0.0` 身份等价处理。发现阶段不启动 LibreOffice，也不写工作区。

## 脚手架

```bash
python tools/template_package.py scaffold \
  --base-package <canonical-package> \
  --version 1.1.1 \
  --output-dir work/template-packages/example/1.1.1
```

基线必须是有效 canonical 包。默认只允许同 major/minor 的新 patch，输出目录不能与 canonical 树、基线或其祖先/子目录重叠，也不能覆盖已有目录。工具复制模板、manifest、`CHANGELOG.md`，更新 `template.version` 和实际模板 SHA，默认保留 `generator.version`；基线 manifest 声明的相对 v1.0 依赖会复制到工作包同级位置，保证工作包可被真实 validator 独立校验。生成 `scaffold-report.json` 到包外。

开发中的新 minor 可以显式使用 `--allow-unsupported-minor`，但只能输出到 canonical 树外，报告固定写入：

```json
{
  "promotable": false,
  "reason": "Template minor is not supported by the current generator contract."
}
```

此类包不能直接 `promote`。`--dry-run` 只输出计划，不创建包、依赖或报告。

## 校验

```bash
python tools/template_package.py validate --package <package> --json
```

默认执行通用身份/fingerprint 检查，再调用包所属 Skill 的真实 `scripts/validate_template.py`，统一记录 validator 的 stdout、stderr 和退出码。完整校验必须通过时才报告 `status=passed`。`--identity-only` 明确报告 `status=identity_only`、`full_validation=false`，它不是完整通过，适合纯路径或 manifest 检查。

## 晋级

```bash
python tools/template_package.py promote --package <validated-work-package>
```

目标路径由所属 Skill 的模板根、manifest 的 template id 和版本计算，不能由用户指定任意 canonical 目标。工具先完整校验，拒绝已存在目标、unsupported minor、路径重叠和 symlink；然后通过同父目录 stage 原子安装，重新发现目标并运行 `tests/validate_template_packages.py`。后置校验失败会删除本次安装并清理 stage，原有包、默认选择、兼容模板和生成器文件不变。`--dry-run` 会执行前置完整校验并仅输出计划。

## 归档

```bash
python tools/template_package.py archive \
  --package <validated-package> \
  --output-dir dist/template-packages
```

归档前必须完整校验。输出为 `<id>-<version>.zip`、同名 `.sha256` sidecar 和 `.json` 元数据；ZIP 内文件使用稳定的 POSIX 路径、排序、固定时间 `1980-01-01`、固定权限和固定压缩级别。`__pycache__`、`.pyc`、Office 临时文件、QA/scaffold 报告、stage 和 backup 不进入归档。工具会重新打开 ZIP，检查路径、重复项、manifest、template、每个文件 SHA、archive SHA 和 sidecar 一致性，并拒绝覆盖已有归档。

## CI 与交付边界

CI 对 `tools/**` 变更运行现有双平台模板包工作流，并把 `tools` 纳入 `compileall`；不会增加新的平台或放宽现有 timeout。工具测试使用真实 CLI 和轻量 fixture，当前四个 canonical 包的完整模板包校验仍由 `tests/validate_template_packages.py` 负责。归档、scaffold report、stage 和 backup 都是本地工作产物，不应提交、打 tag、创建 release 或上传 `dist`。
