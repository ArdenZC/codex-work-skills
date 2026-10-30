# 项目二 Agent 原始返包的主审更正

**日期：** 2026-10-30
**范围：** Issue #73 项目级质量复审

`project-2-tree-graph.json` 是项目 Agent 的原始返包，保留其历史作者内容。其 `research.EX-GRAPH-APPLICATION.transferable_patterns_only` 把论文方法写成“L10/L14分别追踪Prim边界与Kruskal并查集”。主审实际打开并复核了所引论文全文；原文讨论图表示、DFS/Dijkstra/Prim/拓扑排序等课程组织，以及Prim类选择/更新状态和表示效率，没有讨论Kruskal或并查集。

该原始句子不作为最终课程设计的来源依据，已由 `../pilot-40h-separate/generation-evidence.json` 中修订后的 `EX-GRAPH-APPLICATION.transferable_methods` 和 L09–L14 逐维证据取代。最终表述限定为：论文只可为图章节从表示到应用的宏观组织、Prim候选状态提供有限背景；L10/L14的Kruskal排序、DSU判环、可执行边表、复杂度、支架及测试由课程算法定义和冻结合成数据独立建立。

保留原始项目文件用于追溯，不把它当作修订版证据；这条主审更正在 Owner 验收报告中列为已整改的对标归因错误。

## 第二轮最终内容复核

第二轮复核以 `pilot-40h-separate/lesson-content-v2.4.json`、`practice-starters` 及按该内容重生成的 DOCX/PDF 为准。原始 Agent 返包保留为历史产物；本轮主审更正和补充均由最终课程文件及 `generation-evidence.json` 的最终摘要承接。

- **L11：** 对齐学生目标、25 分钟分配和代码支架。学生按 `G-(C,M)、C-(A,E)、M-(J,P)` 实际构建链式树，再实现三种递归遍历与层序；测试空树、单节点、左右单支和 G 树。单课课堂活动合计 90 分钟，预习 10 分钟、课后 15 分钟另计。
- **L12：** 删除 15/25/45 后依次断言 size 7/6/5 和中序；99 不存在时同时核对树形遍历和 size 不变。新增后继带右孩子的删除变式：树 `[20,10,30,25,27,40]` 删除 20 后中序为 `[10,25,27,30,40]`，验证右子树最小后继的右孩子接回。
- **L14：** Prim/Kruskal 实践断言现在检查每条结果边属于输入、边权和等于报告总权、精确边集、树/森林连通分量及 F 孤立。原图 A–E 权 10；删 BC 副本后权 13；包含孤立 F 的全图只产出 A–E 最小生成树，权 10。测试不改原边表。

Content 2.4 的既有 `pedagogical_review.review_history` 上限为八轮，因此本次独立主审复核不伪造第九轮；最新课程摘要、代码测试、最终生成证据和 Owner 报告记录这次复核与增补。
