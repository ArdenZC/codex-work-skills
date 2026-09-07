# Generalization Holdouts

本目录的五门课程不是 Data Structures / UML / Database regression fixtures，也不是从 Gold Sample 复制来的课程内容。`build_holdouts.py` 用独立的课程规格生成冻结的 Courseware 1.1 source pack 和 Practice 1.1 contract：

1. Python Web 接口：Python / VS Code / Flask，代码编辑与请求验证；
2. Excel 数据处理：工作表、公式、筛选和透视分析，不含代码模板；
3. 计算机网络：IPv4、抓包和路径诊断，工具操作与状态推演；
4. AI 分类评估：Python / Jupyter / NumPy，混淆矩阵、阈值和指标解释；
5. 软件测试设计：等价类、决策表、缺陷分诊和测试用例设计，不含 C/代码脚手架。

运行 `python holdouts/build_holdouts.py --write` 可写出 `source-packs/` 和 `practice-contracts/`。第一次生成前先运行 `python holdouts/build_holdouts.py --freeze-manifest`，把 source pack 的哈希固定到审计报告；首轮输出另存到审计目录，后续改进不得覆盖首轮目录。
