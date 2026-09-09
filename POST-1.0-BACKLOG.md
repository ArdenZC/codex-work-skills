# Post-1.0 Backlog

本文件整理历史 review 中明确保留、但不在 Dual Teaching Skills 1.0 closeout 中修复的问题。它们不阻止当前 release，也不代表本轮已修改代码。

## P2 usability / robustness

### 1. SVG selector / aria reference namespacing

Courseware renderer 对自包含 SVG 的 ID 重写还可以进一步覆盖 inline CSS selector 与 `aria-labelledby` 等 fragment reference，避免合法 SVG 在 ID namespace 后丢失样式或语义关系。

来源：PR #20 historical P2 review，`HTML课件生成器/courseware-html-generator/scripts/render_courseware.py`。

### 2. Installer rollback backup bookkeeping

Courseware adapter staged replacement 的极端文件系统失败路径可以进一步加强 backup 记录，确保首个 `os.replace` 成功后下一次替换失败时仍能完整 rollback。

来源：PR #20 historical P2 review，`HTML课件生成器/courseware-html-generator/scripts/install_adapters.py`。

### 3. HTML entity decoding in page mapping validation

Courseware validator 对包含 HTML-special character 的 slide ID 可以进一步在比较 mapping 前解码属性实体，或明确收紧 ID contract。

来源：PR #20 historical P2 review，`HTML课件生成器/courseware-html-generator/scripts/validate_courseware.py`。

## Handling

- 不在 closeout 中偷偷修复；后续应通过独立 issue/roadmap 和独立 PR 处理。
- 建议后续 issue 标题：`Dual teaching skills post-1.0 hardening`。
- 如实现这些改动，必须重新执行对应 Skill regression、browser smoke 和 release review；不得把本 backlog 项目描述为当前 release 已解决。
