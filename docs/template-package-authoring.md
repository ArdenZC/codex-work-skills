# 模板包维护工具

仓库根目录的 `tools/template_package.py` 是版本化模板包的通用维护入口。它不依赖 Word 或 Excel 的字段注册表，也不把教案或成绩册的业务定位规则复制到工具中；业务规则仍由每个 Skill 自己的 manifest 和 `scripts/validate_template.py` 负责。

## 发现

```bash
python tools/template_package.py discover --json
```

工具扫描 `**/assets/templates/<template-id>/<version>/manifest.yaml`，动态发现所有 canonical 包，不维护固定包列表；检查 manifest、严格 ASCII `MAJOR.MINOR.PATCH`、包目录版本、模板文件、封闭 SHA-256 fingerprint、重复身份、所属 Skill 的真实 validator、输入 schema 和规范化路径。当前仓库使用 `v1.0.0` 这样的目录名，工具将它与 manifest 的 `1.0.0` 身份等价处理。发现阶段不启动 LibreOffice，也不写工作区。不同 Skill 声明同一 id/format 时，外部包必须显式落在某个 owner Skill 树中，否则报告 ambiguous owner。

通用 fingerprint 必须严格包含且只包含 `algorithm: sha256`、`sha256` 和 `value`；两个 hash 规范化后必须相同，并且都要匹配实际模板文件。未知字段、缺失字段、大小写错误、Unicode 数字和长度错误都会阻断所有入口。

## 脚手架

```bash
python tools/template_package.py scaffold \
  --base-package <canonical-package> \
  --version 1.1.1 \
  --output-dir work/template-packages/example/1.1.1
```

基线必须先通过所属 Skill 的完整 validator，失败时不会创建输出父目录、依赖、stage 或 report。默认只允许同 major/minor 的新 patch，输出目录不能与 canonical 树、基线或其祖先/子目录重叠，也不能覆盖已有目录。工具复制模板、manifest、`CHANGELOG.md`，更新 `template.version` 和实际模板 SHA，默认保留 `generator.version`；`--generator-version` 先通过严格 ASCII semver，并要求 major 与 `generator.supported_major` 一致。基线 manifest 声明的相对 v1.0 依赖会复制到工作包同级位置，保证工作包可被真实 validator 独立校验。

默认报告文件名为 `scaffold-report-<template-id>-<version>.json`，报告路径不得位于 canonical/package、依赖、`tools`、`tests`、`.github` 或任何 manifest/template/schema 文件内。报告使用临时文件、flush/fsync（可行时）和 `os.replace` 原子提交；报告提交失败会回滚本轮 output/dependency。

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

默认执行通用身份/fingerprint 检查，再调用包所属 Skill 的真实 `scripts/validate_template.py`，统一记录 validator 的 stdout、stderr 和退出码。外部包会复制 validator、本地依赖、schema、当前包和声明的 base 依赖到系统临时隔离 Skill 树中执行，真实 canonical 树不会创建 shadow；随机临时绝对路径不会进入报告。完整校验必须通过时才报告 `status=passed`。`--identity-only` 明确报告 `status=identity_only`、`full_validation=false`，它不是完整通过，适合纯路径或 manifest 检查。

## 晋级

```bash
python tools/template_package.py promote --package <validated-work-package>
```

目标路径由所属 Skill 的模板根、manifest 的 template id 和版本计算，不能由用户指定任意 canonical 目标。工具先把工作包复制到系统临时目录的不可变 snapshot，并只使用 snapshot 完整校验；随后复制到 canonical 同父目录 stage，执行 identity/full validation，安装后再次对实际 target 执行真实 validator，要求 `status=passed`、`full_validation=true`、`validation_scope=package`，最后运行动态 `tests/validate_template_packages.py` 验证全部 canonical 包。任何后置失败都会删除本次 target、确认删除结果并清理 stage；删除失败会同时报告原始错误和回滚错误，既有包不会被覆盖。`--dry-run` 会执行 snapshot 和前置完整校验并仅输出计划。

## 归档

```bash
python tools/template_package.py archive \
  --package <validated-package> \
  --output-dir dist/template-packages
```

归档前必须完整校验，并递归收集 `base_manifest/base_template` 依赖闭包。输出为 `<id>-<version>.zip`、同名 `.sha256` sidecar 和 `<id>-<version>.metadata.json` 元数据；ZIP 内统一使用 `<template-id>/<version>/...`，使 v1.1 解压后仍能解析 v1.0 相对依赖。每个依赖执行身份和 fingerprint 检查，循环、跨 id、逃离 template root 或缺少成对引用都会失败。

ZIP 文件使用 NFC/casefold 稳定排序，拒绝 casefold/NFC 冲突、zip-slip、symlink、控制字符、Windows 保留名称、尾随点/空格和非法字符；中文合法路径可以保留。生成后会解压到新的系统临时目录，复验路径、入口包、依赖闭包、所有文件 SHA、metadata，并用真实 owner validator 完整验证入口包。ZIP、sidecar、metadata 三个最终文件拒绝覆盖并作为一个提交事务处理，任一步失败都会清理已提交文件和临时文件。

## CI 与交付边界

CI 对 `tools/**` 变更运行现有双平台模板包工作流，并把 `tools` 纳入 `compileall`；不会增加新的平台或放宽现有 timeout。工具测试使用真实 CLI 和轻量 fixture，仓库级 `tests/validate_template_packages.py` 会动态校验发现到的全部 canonical 包和所属 schema/validator。归档、scaffold report、stage、snapshot 和 backup 都是本地工作产物，不应提交、打 tag、创建 release 或上传 `dist`。
