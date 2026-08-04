# 模板包维护工具

仓库根目录的 `tools/template_package.py` 是版本化模板包的通用维护入口。它不依赖 Word 或 Excel 的字段注册表，也不把教案或成绩册的业务定位规则复制到工具中；业务规则仍由每个 Skill 自己的 manifest 和 `scripts/validate_template.py` 负责。

## 发现

```bash
python tools/template_package.py discover --json
```

工具扫描 `**/assets/templates/<template-id>/<version>/manifest.yaml`，动态发现所有 canonical 包，不维护固定包列表；检查 manifest、严格 ASCII `MAJOR.MINOR.PATCH`、包目录版本、模板文件、封闭 SHA-256 fingerprint、重复身份、所属 Skill 的真实 validator、输入 schema 和规范化路径。当前仓库使用 `v1.0.0` 这样的目录名，工具将它与 manifest 的 `1.0.0` 身份等价处理。发现阶段不启动 LibreOffice，也不写工作区。validator 信任根是传入 repo-root 的 Git index：validator 必须是已跟踪的、位于已发现 Skill 的 `scripts/validate_template.py` 普通文件；未跟踪的 canonical-like Skill 会保留在 discover 结果中并以错误结束，不会执行。validator 所在 `scripts/` 下的可导入或可执行支持文件也必须已跟踪、为普通文件且无 symlink；只有 `scripts/__pycache__/` 内的 `.pyc/.pyo` 和 Office 临时文件会被忽略，普通 scripts 目录中的 `.pyc/.pyo` 即使已跟踪也会拒绝。external/work 包绝不执行自身或祖先目录提供的 validator，只能从 Git-tracked canonical Skill 解析唯一受信任 owner；隔离 validation workspace 建立后还会检查不存在 `__pycache__`、`.pyc` 和 `.pyo`。工具不会自动 `git add`；开发中的新 Skill 必须精确暂存 validator、manifest、模板、schema 及其已跟踪 helper 后才能运行会执行 validator 的生命周期命令，已跟踪但尚未 commit 的工作树修改允许用于当前验证。

通用 fingerprint 必须严格包含且只包含 `algorithm: sha256`、`sha256` 和 `value`；两个 hash 规范化后必须相同，并且都要匹配实际模板文件。未知字段、缺失字段、大小写错误、Unicode 数字和长度错误都会阻断所有入口。

## 脚手架

```bash
python tools/template_package.py scaffold \
  --base-package <canonical-package> \
  --version 1.1.1 \
  --output-dir work/template-packages/example/1.1.1
```

基线必须先通过所属 Skill 的完整 validator，失败时不会创建输出父目录、依赖、stage 或 report。工作目录检查在完整 validator 前执行，并同时比较 lexical 和 resolved 路径：仓库内 output 只能位于 `work/template-packages/` 之下，仓库内路径解析到外部会拒绝，仓库外路径解析回仓库也会拒绝；仓库根、docs、tools、tests、`.github`、Skill 的 `scripts`/`assets` 和 `work/` 都拒绝。仓库外解析后仍在独立 workspace 的目录或 symlink alias 可以使用，但不能与 base/canonical package 重叠；所有已存在的祖先组件都会参与解析，非存在尾部不会绕过边界检查。report 与 manifest 声明的依赖必须解析到同一外部 workspace，report 仍只能位于 output package 同级。默认只允许同 major/minor 的新 patch，输出目录不能与 canonical 树、基线或其祖先/子目录重叠，也不能覆盖已有目录。工具复制模板、manifest、`CHANGELOG.md`，更新 `template.version` 和实际模板 SHA，默认保留 `generator.version`；`--generator-version` 先通过严格 ASCII semver，并要求 major 与 `generator.supported_major` 一致。基线 manifest 声明的相对 v1.0 依赖会复制到工作包同级位置，保证工作包可被真实 validator 独立校验。

默认报告文件名为 `scaffold-report-<template-id>-<version>.json`。显式或默认报告必须位于 output package 的同级目录，且使用 `.json` 后缀；因此不能写入仓库根、docs、scripts、tools、tests、canonical/package、依赖或其他源码目录。报告使用临时文件、flush/fsync（可行时）和 `os.replace` 原子提交；报告提交失败会回滚本轮 output/dependency。

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

默认执行通用身份/fingerprint 检查，再调用受信任 Skill 的真实 `scripts/validate_template.py`；执行前会再次读取 Git index、检查 owner validator 和完整 scripts 支持文件，工作树新增但未暂存的 helper 会 fail closed。external 包会复制 Git-tracked 的普通脚本、本地依赖、schema、当前包和声明的 base 依赖到系统临时隔离 Skill 树中执行，绝不执行 external workspace 自带的 validator；真实 canonical 树不会创建 shadow，随机临时绝对路径不会进入报告。完整校验必须通过时才报告 `status=passed`。`--identity-only` 明确报告 `status=identity_only`、`full_validation=false`，它不是完整通过，适合纯路径或 manifest 检查。

所有完整 validator 流程都使用系统临时的正常 Skill 树，包括 canonical、external、archive 解压包以及 scaffold、snapshot、stage、最终 target 和动态仓库校验；不存在 canonical 直接执行的例外。隔离树只复制 Git-tracked 的普通源文件、模板、manifest、schema、helper 和声明依赖，真实仓库的 `__pycache__`、`.pyc`、`.pyo` 不会被读取或写入。子进程使用 `python -B` 和 OS 环境白名单，过滤 `PYTHONPATH`、`PYTHONHOME`、`PYTHONSTARTUP`、`PYTHONINSPECT` 等注入变量，设置 `PYTHONNOUSERSITE=1`，并把 `PYTHONPYCACHEPREFIX` 指向临时树内的 `python-cache`。验证前后都会检查缓存、字节码和临时目录边界，清理失败返回失败；报告的 `source_scope` 可为 `canonical` 或 `external`，完整报告的 `validation_scope` 必须为 `isolated_temp`。身份检查不会执行 validator，也不会报告为完整通过。

## 晋级

```bash
python tools/template_package.py promote --package <validated-work-package>
```

目标路径由所属 Skill 的模板根、manifest 的 template id 和版本计算，不能由用户指定任意 canonical 目标。工具先把工作包复制到系统临时目录的不可变 snapshot，并只使用 snapshot 完整校验；snapshot、stage、安装后的 target、target validator 成功后以及动态仓库校验成功后都必须与 snapshot 全树字节一致，validator 或 repository validator 在包内产生任何文件都会阻断晋级。随后复制到 canonical 同父目录 stage，执行 identity/full validation，安装后再次对实际 target 执行真实 validator，要求 `status=passed`、`full_validation=true`、`validation_scope=isolated_temp`，最后运行动态 `tests/validate_template_packages.py` 验证全部 canonical 包。任何后置失败都会删除本次 target、确认删除结果并清理 stage；删除失败会同时报告原始错误和回滚错误，既有包不会被覆盖。`--dry-run` 会执行 snapshot 和前置完整校验并仅输出计划。

## 归档

```bash
python tools/template_package.py archive \
  --package <validated-package> \
  --output-dir dist/template-packages
```

归档前必须完整校验，并递归收集 `base_manifest/base_template` 依赖闭包。输出为 `<id>-<version>.zip`、同名 `.sha256` sidecar 和 `<id>-<version>.metadata.json` 元数据；ZIP 内统一使用 `<template-id>/<version>/...`，使 v1.1 解压后仍能解析 v1.0 相对依赖。每个依赖执行身份和 fingerprint 检查，循环、跨 id、逃离 template root 或缺少成对引用都会失败。

ZIP 文件使用 NFC/casefold 稳定排序，拒绝 casefold/NFC 冲突、zip-slip、symlink、控制字符、Windows 保留名称、尾随点/空格和非法字符；中文合法路径可以保留。生成后会解压到新的系统临时目录，复验路径、入口包、依赖闭包、所有文件 SHA、metadata，并用真实 owner validator 完整验证入口包。ZIP、sidecar、metadata 三个最终文件拒绝覆盖并作为一个提交事务处理，任一步失败都会清理已提交文件和临时文件。

## CI 与交付边界

CI 对 `tools/**` 变更运行现有双平台模板包工作流，并把 `tools` 纳入 `compileall`；不会增加新的平台或放宽现有 timeout。工具测试使用真实 CLI 和轻量 fixture，fixture 必须先初始化 Git 并精确暂存需要信任的 validator、manifest、模板、schema 和 helper；仓库级 `tests/validate_template_packages.py` 会动态校验发现到的全部 canonical 包和所属 schema/validator。仓库内 scaffold 工作包统一放在 `/work/template-packages/`，该目录不属于正式模板包或发布内容，并由 `.gitignore` 忽略。归档、scaffold report、stage、snapshot 和 backup 都是本地工作产物，不应提交、打 tag、创建 release 或上传 `dist`。
