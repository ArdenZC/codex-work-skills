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

## Manifest

`manifest.yaml` 是模板结构和写入契约的唯一事实来源，至少声明：

- `template.id`、`template.name`、`template.version`、`template.format`、`template.file`；
- `generator.version`，记录当前生成器版本；
- `generator.supported_major`，用于拒绝不兼容的模板大版本；
- `structure`，包括工作表/主表、数据区、嵌套表、保护布局和必要的兼容坐标；
- `fields`，包括字段名称、语义写入目标、写入模式、允许的长度或数值范围；
- `allowed_changes` 与 `protected`，说明生成器可以改什么、不能改什么；
- `validation`，包括固定标签、行列数、公式、格式和输出检查项；
- canonical template 的 `fingerprint.sha256`。
- `validation` 中的禁止残留文字、长度/段落限制和是否要求渲染检查。

版本使用 `MAJOR.MINOR.PATCH`。结构或生成契约不兼容时增加 MAJOR；新增兼容字段或规则时增加 MINOR；错误修复或指纹修订时增加 PATCH。生成器默认只接受 `supported_major` 对应的大版本。

## 标准工作流

```text
输入资料 → 标准化数据 → schema 校验 → 模板校验 → 生成 → 输出校验 → 渲染预览（按 manifest） → QA 报告
```

校验失败必须返回非零退出码，并在标准错误输出清晰原因。非阻断提醒放入 `warnings`，不能把警告伪装成成功校验。正常生成默认启用模板校验和输出校验；只有显式传入 `--skip-template-validation` 或 `--skip-output-validation` 才能跳过。

## Word 语义书签

教案 `lesson-plan/v1.1.0` 使用标准 Word `w:bookmarkStart`/`w:bookmarkEnd` 作为写入锚点。所有 managed semantic bookmark 必须匹配 `^[A-Za-z][A-Za-z0-9_]{0,39}$`，不使用中文、空格、连字符、点号、`_GoBack` 或超过 40 个字符的名称；教学实施区使用 `prep`、`intro`、`demo`、`exec`、`extend`、`practice`、`peer`、`summary`、`improve` 等短阶段代码。固定字段、教学实施区的每个实际可写单元格、三个教学反思单元格和评价表父单元格均有独立锚点。生成器先解析书签并按父段落或父单元格写入，写入完成后由输出校验确认必需书签仍成对存在、位于主文档、容器正确，且 start/end 的完整稳定边界位置未改变。构建器对临时最终 DOCX 扫描主文档、所有页眉和页脚 story 后才原子替换输出；书签 ID 只允许 ASCII 十进制数字。

v1.1 模板必须从 v1.0.0 模板复制生成，去除书签边界后与 v1.0.0 的可见内容和结构 XML 严格等价。v1.1 manifest 的 semantic 契约字段必须显式存在，不能由 Python 定义静默补全；包括 `anchors.required`、`anchors.containers`、固定字段的 `target/bookmark/mode`、实施阶段的 `id/code/bookmarks`、反思书签和评价书签。校验器不会用坐标模式静默补写缺失书签。v1.0 canonical 模板和旧 compatibility entry 仅传 `--template` 时自动解析为对应的 v1.0 manifest，QA 报告会标记 `anchor_mode: legacy_coordinates`；v1.1.x 报告会记录 `anchor_mode: word_bookmark`、必需/保留数量以及缺失、重复、非法 ID 和边界错误。自定义模板必须显式提供匹配的 manifest。

## 模板保护边界

生成器只能写 manifest 中声明的字段，或按声明的行/列规则增删学生行和技能列。页边距、页眉页脚、合并单元格、固定标签、工作表名称、公式列、打印设置、样式和其他未声明结构均视为 protected。canonical 模板和旧 compatibility entry 可以通过 `--template` 参数自动解析；自定义模板必须同时传入匹配的 `--manifest`，指纹不一致必须给出明确警告，结构不满足时仍然失败。

## QA 报告

每次生成都应在输出目录生成 QA 报告，至少包含 `template_id`、`template_version`、`generator_version`、`status`、`checks`、`errors` 和 `warnings`，并记录实际 `template_path`、`custom_template`、`engine`、`validation_skipped`。完整校验通过时 `status` 为 `passed`；显式跳过任一校验时为 `skipped`，不能用警告伪装成完整通过。报告只记录校验元数据、行号、数量和错误类别，不写入学生姓名、学号或其他原始输入内容。报告不替代进程退出码：有阻断错误时进程必须返回非零。

## 兼容性

- 原有 CLI 参数继续保留；新参数只做可选扩展。
- DOCX 生成器继续使用 `python-docx`，并保留单段落替换和多段落内容写入模式；教案 v1.1 的正常写入必须以 Word 书签为入口。
- `.xls` 生成器继续保留 Windows Excel COM 路径，并提供 Python + LibreOffice 路径；两条路径使用同一份 manifest。Windows COM 负责生成时保留 Excel 原生格式，但默认结构化 QA 仍调用 Python/LibreOffice 转换器；没有 LibreOffice 时只能显式跳过相应校验，报告会标记为 `skipped`。
- 仓库内脚本不得依赖个人电脑上的临时工具目录或其他外部绝对路径。
- 当前模板版本：教案默认 `lesson-plan/v1.1.0`，兼容 `lesson-plan/v1.0.0`；记分册 `course-gradebook/v1.0.0`。
- 默认校验命令：

  ```bash
  python scripts/validate_template.py --template <template> --manifest <manifest.yaml>
  python scripts/validate_output.py --input-json <input.json> --output-dir <output> --manifest <manifest.yaml>
  ```

- 自定义模板必须同时提供匹配的 manifest；不建议直接修改内置 canonical 模板。仅传 canonical v1.0 模板或旧 compatibility entry 时，解析器会自动选择 v1.0 manifest。
