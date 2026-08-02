# Aider 约定

先读取 AGENTS.md、SKILL.md 和 通用提示词.md，再处理成绩册任务。

- 先定位课程成绩单.xls；没有源文件时不要生成或臆造数据。
- Windows 使用 scripts/generate_gradebook.ps1；macOS/Linux 使用 scripts/generate_gradebook.py。
- 生成后检查学生数量、学号姓名顺序、8 次平时成绩平均值、总评、公式错误和技能成绩列。
- 保留模板样式与 xls 格式，并报告实际校验结果。
- v1.0 使用 legacy coordinates 并删除未使用学生行；v1.1 使用 workbook-level `gb_` named ranges，48 人以内保留到第 52 行，超出容量时精确扩展到最后一名学生，`gb_template_row` 固定为第 5 行。
- Windows 以 Excel COM 生成，Python `xlrd`/`olefile` raw XLS preflight 不可跳过；LibreOffice 只用于完整 round-trip、格式和渲染 QA，双 skip 时 COM 不强制要求 LibreOffice。
- 生成必须先写候选文件，再做 raw 检查和 QA，最后原子替换 XLS 与 QA；失败不得覆盖旧输出或删除无关 XLS。skip QA 仍检查真实非空 XLS 和 v1.1 named-range inventory。
