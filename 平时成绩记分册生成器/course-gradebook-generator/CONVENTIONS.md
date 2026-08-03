# Aider 约定

先读取 AGENTS.md、SKILL.md 和 通用提示词.md，再处理成绩册任务。

- 先定位课程成绩单.xls；没有源文件时不要生成或臆造数据。
- Windows 使用 scripts/generate_gradebook.ps1；macOS/Linux 使用 scripts/generate_gradebook.py。
- 生成后检查学生数量、学号姓名顺序、8 次平时成绩平均值、总评、公式错误和技能成绩列。
- 保留模板样式与 xls 格式，并报告实际校验结果。
- v1.0 使用 legacy coordinates 并删除未使用学生行；v1.1 使用 workbook-level `gb_` named ranges，48 人以内保留到第 52 行，超出容量时精确扩展到最后一名学生，`gb_template_row` 固定为第 5 行。
- Windows 以 Excel COM 生成，Python `xlrd`/`olefile` raw XLS preflight 不可跳过；LibreOffice 只用于完整 round-trip、格式和渲染 QA，双 skip 时 COM 不强制要求 LibreOffice。
- 生成必须先写候选文件，再做 raw 检查和 QA，最后原子替换 XLS 与 QA；失败不得覆盖旧输出或删除无关 XLS。skip QA 仍检查真实非空 XLS 和 v1.1 named-range inventory。
- 目录事务交换故障注入仅供测试使用：测试环境可设置 `GRADEBOOK_TEST_FAIL_DIRECTORY_SWAP=1`，正常运行不要设置。
- `build_named_range_template.py --force` 只允许替换独立且安全的输出包：输出目录不得与 source package 重叠，也不得等于、包含或位于 canonical v1.0 package 内。
- canonical v1.1 package 只能作为明确的正式构建目标；不得将其共同父目录或其内部子目录作为输出目录。对自定义 source package 应使用安全的 sibling 输出目录。
