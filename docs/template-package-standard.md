# 模板包标准 v1

本仓库的文档与表格生成器使用“版本化模板包”管理模板。模板包的目标是让模板、生成器、输入数据和校验规则可追溯，并允许旧命令继续工作。

## 目录约定

每个生成器至少包含以下文件：

```text
assets/
  <旧模板文件>                         # 兼容入口，不作为新代码的默认来源
  templates/<template-id>/<version>/
    template.<docx|xls>                 # 规范模板，唯一 canonical source
    manifest.yaml                        # 模板结构、字段和保护规则
    CHANGELOG.md
schemas/
  <input>.schema.json                   # 标准化输入数据契约
scripts/
  validate_template.py                  # 模板结构与指纹校验
  validate_output.py                    # 生成物校验并输出 QA 报告
requirements.txt
```

旧模板路径必须保留，且只能作为兼容入口。兼容入口与当前 canonical template 的 SHA-256 必须一致；如果两者发生分歧，校验器报错，不允许静默选择其中一份。

模板包生命周期由仓库根目录的 `tools/template_package.py` 统一处理。工具从 `**/assets/templates/*/*/manifest.yaml` 动态发现包，不维护人工同步的 registry；仓库级校验器同样按 discovery 结果验证所有 canonical 包、输入 schema 和 owner Skill validator。工具只读取 manifest 和包文件，不启动 LibreOffice。validator 信任根是 repo-root 的 Git index；validator 及其 scripts 支持文件必须是已跟踪的普通文件，symlink、未跟踪 canonical-like Skill 和未跟踪 helper 都 fail closed。只有 `scripts/__pycache__/` 内的 `.pyc/.pyo` 会被忽略，普通 scripts 目录中的 `.pyc/.pyo` 即使已跟踪也 fail closed；外部验证建立的隔离 Skill 树还必须不含 `__pycache__`、`.pyc` 或 `.pyo`。工具不会自动暂存文件；新 Skill 需精确 `git add` validator、manifest、模板、schema 和已跟踪 helper，未 commit 的已跟踪工作树修改可以运行。external/work 包不能提供或覆盖 validator，只能使用唯一的 Git-tracked canonical Skill owner。`scaffold` 先检查 lexical/resolved 工作目录，再完整验证 canonical 基线并生成 output sibling 原子 report；仓库内 output 只能在 `work/template-packages/` 下，仓库外路径解析回仓库时拒绝，解析后仍在独立 workspace 的目录或 alias 仍可用，report 与依赖必须解析到同一 workspace。`validate` 对外部包在系统临时隔离 Skill 树执行真实模板校验，`promote` 在不可变 snapshot、stage、最终 target、全树 fingerprint 一致性和动态仓库校验都通过后原子安装，`archive` 生成可复现的自包含 ZIP、SHA-256 sidecar 和结构化元数据。已有 canonical、默认入口、兼容入口和 manifest 不会被这些命令静默覆盖。

## Manifest

`manifest.yaml` 是模板结构和写入契约的唯一事实来源，至少声明：

- `template.id`、`template.name`、`template.version`、`template.format`、`template.file`；
- `generator.version`，记录当前生成器版本；
- `generator.supported_major`，用于拒绝不兼容的模板大版本；
- `structure`，包括工作表/主表、数据区、嵌套表、保护布局和必要的兼容坐标；
- `fields`，包括字段名称、语义写入目标、写入模式、允许的长度或数值范围；
- `allowed_changes` 与 `protected`，说明生成器可以改什么、不能改什么；
- `validation`，包括固定标签、行列数、公式、格式和输出检查项；
- `fingerprint` 必须严格包含 `algorithm: sha256`、`sha256`、`value` 三个键；两个 hash 必须相同并匹配 canonical template 的实际 SHA-256，不能添加未知 fingerprint 键。
- `validation` 中的禁止残留文字、长度/段落限制和是否要求渲染检查。

版本使用严格的 ASCII `MAJOR.MINOR.PATCH`，不接受前导零、`v` 前缀、预发布后缀或 Unicode 数字。`scaffold --generator-version` 也必须使用同一 semver 解析器，并且 major 必须等于 manifest 的 `generator.supported_major`。版本—定位模式矩阵固定为：教案 `1.0.x = legacy_coordinates`、`1.1.x = word_bookmark`；成绩册 `1.0.x = legacy_coordinates`、`1.1.x = excel_named_range`。其他 `1.x` minor 和不支持的大版本均拒绝，显式模式与版本冲突也拒绝。结构或生成契约不兼容时增加 MAJOR；新增兼容字段或规则时增加 MINOR；错误修复或指纹修订时增加 PATCH。生成器默认只接受 `supported_major` 对应的大版本。

### 模板身份与指纹

- 只传 `--template` 时，解析器只对 canonical/compatibility 路径或已知 canonical SHA-256 自动选择精确 manifest；任意其他模板必须显式提供 manifest。
- 显式传入 manifest 时，canonical 和 compatibility 原始路径必须与 manifest 声明的版本精确匹配；自定义路径不再仅凭旧 canonical SHA 推断同一 minor 的 patch 版本，但跨 minor 的已知模板 SHA 仍然拒绝。
- 自定义模板的 manifest 必须声明实际模板文件路径和 64 位 SHA-256 fingerprint。普通复制 canonical 模板不会被要求改变 ZIP 元数据，复制文件的真实 SHA 可以用于兼容的 patch manifest；fingerprint 不匹配是阻断错误。
- 本实现对 compatibility 原始路径采取严格 v1.0 身份策略，因此 v1.0.0 compatibility 文件配 v1.0.1 manifest 会被拒绝；如需 patch manifest，应复制到自定义路径并使用实际 fingerprint。

## 标准工作流

```text
输入资料 → 标准化数据 → schema 校验 → 模板校验 → 生成 → 输出校验 → 渲染预览（按 manifest） → QA 报告
```

校验失败必须返回非零退出码，并在标准错误输出清晰原因。非阻断提醒放入 `warnings`，不能把警告伪装成成功校验。正常生成默认启用模板校验和输出校验；只有显式传入 `--skip-template-validation` 或 `--skip-output-validation` 才能跳过。

模板包的完整 validator 始终在系统临时的正常 Skill 树中执行，覆盖 canonical、external、archive 解压包以及 scaffold、snapshot、stage、最终 target 和动态仓库校验；不会从真实 canonical 或用户工作目录直接加载 owner validator。隔离树只复制 Git-tracked 的普通源文件和声明依赖，真实仓库的 `__pycache__`、`.pyc`、`.pyo` 不会被读取或修改。validator 子进程使用 `python -B` 和 OS 环境白名单，过滤 `PYTHONPATH`、`PYTHONHOME`、`PYTHONSTARTUP`、`PYTHONINSPECT` 等注入变量，设置 `PYTHONNOUSERSITE=1`，并将 `PYTHONPYCACHEPREFIX` 重定向到临时树内的 `python-cache`。验证前后检查缓存和字节码，超时产生的部分 stdout/stderr 会统一解码并保留为 UTF-8 文本，所有临时目录必须清理；清理失败即为失败。`--identity-only` 只执行身份检查，不执行完整 validator，也不能作为完整通过。

## Word 语义书签

教案 `lesson-plan/v1.1.0` 使用标准 Word `w:bookmarkStart`/`w:bookmarkEnd` 作为写入锚点。所有 managed semantic bookmark 必须匹配 `^[A-Za-z][A-Za-z0-9_]{0,39}$`，不使用中文、空格、连字符、点号、`_GoBack` 或超过 40 个字符的名称；教学实施区使用 `prep`、`intro`、`demo`、`exec`、`extend`、`practice`、`peer`、`summary`、`improve` 等短阶段代码。固定字段、教学实施区的每个实际可写单元格、三个教学反思单元格和评价表父单元格均有独立锚点。生成器先解析书签并按父段落或父单元格写入，写入完成后由输出校验确认必需书签仍成对存在、位于主文档、容器正确，且 start/end 的完整稳定边界位置未改变。构建器对临时最终 DOCX 扫描主文档、所有页眉和页脚 story 后才原子替换输出；书签 ID 只允许 ASCII 十进制数字。

v1.1 模板必须从 v1.0.0 模板复制生成，去除书签边界后与 v1.0.0 的可见内容和结构 XML 严格等价。v1.1 manifest 的 semantic 契约字段必须显式存在，不能由 Python 定义静默补全；包括 `anchors.required`、`anchors.containers`、固定字段的 `target/bookmark/mode`、实施阶段的 `id/code/bookmarks`、反思书签和评价书签。固定字段、implementation、reflection、stage 和 evaluation 都采用封闭 allowed-key 契约，未知或冲突的定位键直接失败。v1.0 legacy manifest 只允许坐标字段和 `anchors.mode: legacy_coordinates`，不得出现 semantic `required`、`containers`、`bookmark`、`stages` 或 semantic implementation/reflection 定位元数据。固定字段的 `target`、`mode`、`bookmark`、`container` 来自同一集中定义，未知值会在模板校验和生成前失败。校验器不会用坐标模式静默补写缺失书签。v1.0 canonical 模板和旧 compatibility entry 仅传 `--template` 时自动解析为对应的 v1.0 manifest，QA 报告会标记 `anchor_mode: legacy_coordinates`；v1.1.x 报告会记录 `anchor_mode: word_bookmark`、必需/保留数量以及缺失、重复、非法 ID 和边界错误。自定义模板必须显式提供匹配的 manifest。

## 模板保护边界

生成器只能写 manifest 中声明的字段，或按声明的行/列规则增删学生行和技能列。页边距、页眉页脚、合并单元格、固定标签、工作表名称、公式列、打印设置、样式和其他未声明结构均视为 protected。canonical 模板和旧 compatibility entry 可以通过 `--template` 参数自动解析；自定义模板必须同时传入匹配的 `--manifest`，指纹不一致必须作为明确错误报告，结构不满足时仍然失败。

### Excel 命名区域

成绩册 `course-gradebook/v1.1.0` 使用 24 个 `gb_` 前缀的 workbook-level named ranges 作为唯一生产写入契约。Python/openpyxl、Windows Excel COM、模板校验和输出 QA 共用 `named_range_contracts.py` 与 manifest；v1.1 不允许静默退回坐标写入。无技能成绩变体移除 `gb_header_skill`、`gb_skill_score_col` 和 `gb_skill_weighted_col`，保留 21 个名称；学生数超过 48 时，数据区域名称扩展到实际末行，`gb_template_row` 仍固定为第 5 行样式来源。模板校验同时读取原始 BIFF `.xls` 和 LibreOffice 回转 `.xlsx`，并比较名称、作用域、目标工作表、地址、形状和关系。

容量规则必须由输出校验按固定基线计算：v1.0 使用 legacy coordinates，并删除未使用学生行；v1.1 在 48 人以内保留至第 52 行，超过 48 人时所有动态数据名称统一扩展至 `data_start_row + student_count - 1`，`gb_template_row` 仍为第 5 行。输出自身的当前末行不能被用作预期值。

成绩册 `course-gradebook/v1.0.0` 以及 `assets/平时成绩记分册模板.xls` 继续使用 legacy 坐标模式。v1.1 manifest 的 `anchors`、`fields`、`layout` 和变体契约必须封闭且完整，不能夹带 v1.0 坐标结构；自定义模板必须提供匹配 manifest 和 fingerprint。生成器在显式 skip 参数生效前仍强制检查 fingerprint；QA 报告同时提供顶层命名区域诊断和 `checks.named_ranges`，两者必须保持一致。构建器会固定 BIFF 非业务元数据，以便从 v1.0 canonical 模板确定性生成相同的 v1.1 `.xls` 包。

## QA 报告

每次生成都应在输出目录生成 QA 报告，至少包含 `template_id`、`template_version`、`generator_version`、`status`、`checks`、`errors` 和 `warnings`，并记录实际 `template_path`、`custom_template`、`engine`、`validation_skipped`。完整校验通过时 `status` 为 `passed`；显式跳过任一校验时为 `skipped`，不能用警告伪装成完整通过。报告只记录校验元数据、行号、数量和错误类别，不写入学生姓名、学号或其他原始输入内容。报告不替代进程退出码：有阻断错误时进程必须返回非零。

生成与 QA 使用同一事务边界：候选 XLS 先完成不可跳过的 raw BIFF 可打开性、命名区域 scope/name/目标/shape/relationship 和 canonical 位置检查，再按参数执行完整 QA 或基础 skip QA，最后才原子替换正式 XLS 和 `qa-report.json`。失败不得覆盖旧正式文件或删除无关 XLS。skip QA 仍检查文件存在、普通文件、输出目录内、扩展名、非空和 v1.1 raw named-range inventory。

## 兼容性

- 原有 CLI 参数继续保留；新参数只做可选扩展。
- DOCX 生成器继续使用 `python-docx`，并保留单段落替换和多段落内容写入模式；教案 v1.1 的正常写入必须以 Word 书签为入口。
- `.xls` 生成器继续保留 Windows Excel COM 路径，并提供 Python + LibreOffice 路径；两条路径使用同一份 manifest。Windows COM 是生成引擎，Python 的 `xlrd`/`olefile` 负责不可跳过的 raw XLS preflight；LibreOffice 只用于完整 round-trip、格式和渲染 QA。Windows 同时显式跳过模板和输出 QA 时，不强制要求 LibreOffice；报告会标记为 `skipped`。
- 仓库内脚本不得依赖个人电脑上的临时工具目录或其他外部绝对路径。
- 当前模板版本：教案默认 `lesson-plan/v1.1.0`，兼容 `lesson-plan/v1.0.0`；记分册默认 `course-gradebook/v1.1.0`，兼容 `course-gradebook/v1.0.0` 和旧 `assets/平时成绩记分册模板.xls`。
- 默认校验命令：

  ```bash
  python scripts/validate_template.py --template <template> --manifest <manifest.yaml>
  python scripts/validate_output.py --input-json <input.json> --output-dir <output> --manifest <manifest.yaml>
  ```

- 自定义模板必须同时提供匹配的 manifest；不建议直接修改内置 canonical 模板。仅传 canonical v1.0 模板或旧 compatibility entry 时，解析器会自动选择 v1.0 manifest。

## 发布与安装边界

canonical package 只存在于 Skill 的 Git-tracked source tree；正式 `release` 还要求 clean worktree，并确认 archive closure 中每个正式文件的工作树和 index 内容都等于当前 HEAD，才能让 `source_commit` 证明发布字节。external future patch 可以 archive、verify、install、upgrade，但不能用正式 release 声明 repository provenance。archive 是由现有 metadata contract 描述的三个分发文件，installed package 则位于独立的 `installed/template-packages/` 生命周期目录。Release 不要求同版本 canonical package，可信执行来源是按 `template_id`、format 和 `owner_skill` 解析出的当前 Git-tracked Skill validator；Release template SHA 只绑定自身 entry package。安装器不回写 canonical，不执行 archive 中的 validator，不覆盖已经安装的 version；安装和升级使用 O_EXCL lock、stage/atomic exchange 和当前 trusted owner full validation。rollback 是 installed version state switch，可以在 active/previous 之间双向切换。默认 `list-installed` 必须重新计算 bundle inventory SHA，并拒绝额外、缺失、修改、symlink、special 或 staging/cache 文件；`--verify` 才运行 full validator。archive 校验和 GitHub Release 校验分别独立执行，verify-release 对 ZIP 施加 entry/size/total/compression limits 并使用流式 SHA；GitHub Release 不是第二份 registry。正式 tag/release 只能由 master-only `workflow_dispatch` 创建，同一 template/version 由 Actions concurrency 串行，Python 事务还必须用 operation_id 证明远程 ownership；发布前 live 确认远程 master，下载 asset 必须与 local plan 逐字节一致，普通 CI 不创建远程资源。
