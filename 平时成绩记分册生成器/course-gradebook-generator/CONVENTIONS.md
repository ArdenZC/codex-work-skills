# Aider 约定

先读取 AGENTS.md、SKILL.md 和 通用提示词.md，再处理成绩册任务。

- 先定位课程成绩单.xls；没有源文件时不要生成或臆造数据。
- Windows 使用 scripts/generate_gradebook.ps1；macOS/Linux 使用 scripts/generate_gradebook.py。
- 生成后检查学生数量、学号姓名顺序、8 次平时成绩平均值、总评、公式错误和技能成绩列。
- 保留模板样式与 xls 格式，并报告实际校验结果。
- 默认 v1.1 通过 workbook-level `gb_` named ranges 写入；v1.0 和旧兼容入口继续使用 legacy 坐标模式。
