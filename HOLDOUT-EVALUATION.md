# Five-course Holdout Evaluation

## 1. Freeze and provenance

Source packs 在首次生成前冻结于 `实践课HTML生成器/practice-class-html-generator/holdouts/SOURCE-FREEZE.json`。五门课程均是本轮新建，未使用 Data Structures/UML/Database 的教学知识：

1. Python Web API：HTTP request/response、Flask route、template、form、browser validation、diagnosis；
2. Excel / Power Query：cell reference、IF/COUNTIF、filter、CSV refresh、chart decision；
3. 计算机网络：IPv4/subnet、Wireshark observation、Packet Tracer topology、route/path、fault diagnosis；
4. AI 分类评价：classification、confusion matrix、precision/recall、threshold、结果解释；
5. 软件测试设计：equivalence partition、boundary value、Gherkin/TestRail、test case、defect、coverage。

Gold Sample 只作为抽象质量 benchmark：`F:\work\practice-class-gold-sample-20260907`，源 ZIP SHA-256：`9A11124ABD451DE8FB3D537A527B304A41BF4A09C9CFEF28662A1F7B9B89C2B9`；冻结目录 29 files / 15 HTML。仓库只记录 provenance/benchmark 规则，没有复制 Gold HTML、C starter、数据结构知识或页面正文。

## 2. First-pass / second-pass result

审计输出：`F:\work\practice-class-generalization-audit-20260907-r6`。两次均是完整生成、validator、safe-package 检查和 Windows Chrome smoke；没有先改 holdout fixture 再冒充 first-pass。

| Holdout | First-pass | Second-pass | 状态 |
|---|---:|---:|---|
| H1 Python Web | 93.4 | 93.4 | PASS |
| H2 Excel / 数据处理 | 97.0 | 97.0 | PASS |
| H3 计算机网络 | 92.5 | 92.5 | PASS |
| H4 AI 分类评价 | 93.4 | 93.4 | PASS |
| H5 软件测试设计 | 92.5 | 92.5 | PASS |
| 平均 | **93.8** | **93.8** | **stable=True** |

审计维度包括：理论→实践 trace、任务颗粒度、脚手架与可完成性、互动深度、资料密度、教师可用性、课程上下文泛化和课堂节奏。每套证据均为 8 tasks（5/2/1）、5 个 source slides、8 个 task trace、7 类互动、6 个 study-guide sections、5 个 foundation topics、8 个 teacher references、90 分钟课时规划。所有 holdout Courseware/Practice 合同为 PASS，Practice browser 6 页 × 3 viewport，Courseware browser 每套 5 页，均 PASS。

## 3. Teaching design and findings per holdout

### H1 Python Web — 93.4

Core 以 route、request/response、form validation、template data flow 和 browser verification 为主，提供可运行的 Python/Flask starter 与 3 个真实 gap；optional 覆盖错误响应/日志，challenge 做组合场景。互动使用状态推演、连续诊断、选择、排序和多题，将 HTTP 状态与任务验收连接起来。

P0：自动化未发现理论越界、答案泄漏、不可运行 starter 或 teacher reference 冲突。
P1：脚手架分数受“代码 gap 数量与非代码 support 统一评分”影响，内容人工仍需确认 Flask 环境说明是否适配真实机房。

### H2 Excel / Power Query — 97.0

Core 是单元格引用、条件公式、聚合、筛选和 refresh 验证；学生拿到 CSV、formula card 与操作步骤，不生成 C/代码 TODO。optional 是图表选择与异常数据，challenge 是刷新后结果解释。互动让学生逐项分类字段、比较参数、排序操作顺序并逐题判断。

P0：未发现代码模板污染、答案泄漏或条件不足。
P1：需要教师确认 Excel/Power Query 版本差异与课堂数据文件权限；这是 source/toolchain 配置问题，不是 renderer fixture 分支。

### H3 计算机网络 — 92.5

Core 连接 IPv4/subnet 计算、拓扑观察、路径/路由证据和故障诊断；脚手架是地址表、拓扑/Packet Tracer 操作清单和 Wireshark observation card，不套编程 starter。状态视觉使用通用 table/path 语义，诊断互动连续推进到可验证修复。

P0：未发现 C/Dev-C++ 污染、理论越界或学生答案泄漏。
P1：Packet Tracer/Wireshark 现场环境与网络权限仍需教师确认；部分工具操作必须在真实软件中完成，HTML 只能提供观察点和自助路径。

### H4 AI 分类评价 — 93.4

Core 依次处理样本分类、混淆矩阵、precision/recall、threshold 变化和结果解释；提供 Python/NumPy starter 的 3 个关键 gap，同时保留手算表格路径。互动通过参数变化、状态检查、连续诊断和多题反馈把指标解释带回实践任务。

P0：未发现指标事实冲突、答案泄漏或 C 模板污染。
P1：需要人工核对样本分布与课堂已有统计基础；这是内容深度/课程先修审阅，不是通用渲染故障。

### H5 软件测试设计 — 92.5

Core 从等价类、边界值到 Gherkin/TestRail test case、缺陷诊断和 coverage check；学生获得场景表、验收卡和操作脚手架，不强行生成应用代码。互动包含场景分类、排序、连续缺陷诊断和逐题检查。

P0：未发现 C/代码模板污染、答案泄漏或理论越界。
P1：需要人工确认 TestRail 字段与课堂工具版本；非代码任务的“可用性”最终仍要看教师是否能把操作卡直接发给学生。

## 4. Gold comparison and open acceptance

自动 holdout 指标达到 Gold Sample 所要求的任务层级、互动种类、资料/基础补给、教师参考和 90 分钟节奏下限；两次生成分数完全稳定，平均 93.8，最低 92.5。这个结果证明架构没有被 C/SQL/UML fixture 绑死，但不证明五套内容在教学解释、例子质量和课堂语境上已经与 Gold Sample 同级。

共同的非阻断 P1 是：资料密度审计为每套 6 个 guide sections / 5 个 foundation topics，达到最低结构目标但没有把 Gold 的“可自助深度”自动证明出来；非编程脚手架还需要教师核对实际软件环境。P2 是继续提升自动 rubric 对真实材料质量、图示有效性和课堂追问深度的辨识力。

`content_acceptance` 明确保持 `pending_manual_review`。人工验收前不宣布“内容质量完成”，也不把 holdout 自动分数等同于可直接授课。
