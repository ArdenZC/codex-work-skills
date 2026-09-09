# 双 Skill Generalization QA Report

本报告把结构、语义、浏览器运行和内容层审阅分开。自动化 PASS 不等于教师内容验收 PASS。

## 1. Test entry and static checks

- Practice package tests：`python tests/test_practice_class.py` → **14 tests OK**。
- Practice generalization tests：`python tests/test_generalization.py` → **3 tests OK**。
- Practice 合计：**17 tests OK**。
- Courseware regression tests：`python tests/test_courseware.py` → **12 tests OK**。
- 新脚本 `holdout_audit.py / build_holdouts.py / practice_pedagogical_review.py / apply_reference_gaps.py`：`py_compile` → **PASS**。
- `git diff --check`：**PASS**（仅提示 Windows 工作树 LF/CRLF 转换，不是内容错误）。
- 本仓库的 Python 测试入口是直接运行 `tests/test_*.py`；环境没有 pytest，因此没有把未安装的 pytest 当作测试结果。

## 2. Contract / pedagogical / linkage

### Courseware

- 1.1 examples 的时间、context、learning unit、canonical fact、stable slide ID → **PASS**。
- `prepared_minutes=120` 而页级规划只有约 18 分钟 → **FAIL**，测试确认无法隐藏 mismatch。
- 讲稿明显短于 `lecture_minutes` 或缺教学意图 → **FAIL**。
- context root 与 nested context 冲突、未知 learning unit/slide 引用 → **FAIL**。
- 合法 UML/无 `info-card` 页面不再被 browser smoke 的旧 selector 假失败。
- 本地 image asset → MIME/存在性检查与 data URI 内嵌 **PASS**。

### Practice

- 三套 regression fixture 的 `source_slide_ids` 全部真实存在，context 与上游一致，所有 core 有理论关联和 support path → **PASS**。
- 五套 holdout Courseware/Practice contract pairs：**5/5 PASS**；每套 8 tasks（5 core / 2 optional / 1 challenge），全部有真实 source slide 关联。
- `learning_unit_ids`、`canonical_fact_ids`、`not_yet_taught`、capabilities、artifact/scaffold、starter gap 和 teacher reference 规则 → **PASS**。
- 非编程 fixture（UML、数据库、Excel、网络、软件测试）未出现 C/Dev-C++/Code::Blocks/`#include`/binary-search 模板污染 → **PASS**。
- `student-package` 的 manifest 标记答案/替换元数据/canonical answer 均为 false；完整 reference 只在 `teacher-package` → **PASS**。

## 3. Regression generation and QA

生成根目录：`F:\work\practice-class-generalization-regression-20260907`。

| Fixture | Courseware | Practice | 关键 reference evidence |
|---|---|---|---|
| Data Structures | 生成/合同/HTML QA PASS；Chrome 5 页、7 actions PASS | 8 tasks、4 C starter、4 TODO/gaps、7 guide、7 kit、7 interactions PASS | reference C compile + sample execute PASS |
| UML | 生成/合同/HTML QA PASS；Chrome 5 页、6 actions PASS | 8 tasks、draw.io/sequence scaffolds、4 gaps、8 interactions PASS | draw.io XML parse + sequence artifact PASS；无 C 模板 |
| Database | 生成/合同/HTML QA PASS；Chrome 3 页、3 actions PASS | 8 tasks、ER drawio + setup/query SQL、6 gaps、8 guide、7 kit PASS | ER XML parse + SQL reference semantics PASS；MySQL live execute 因无连接明确 skip |

Practice regression browser smoke：三套 × 6 主页面 × 1366×768 / 1440×900 / 1920×1080，互动族与内部链接检查 **PASS**。Courseware regression browser smoke：三套最新渲染输出均 **PASS**，没有把“固定第几页有某控件”当作前提。

## 4. Browser / offline / link evidence

- Courseware：`file://`、动态普通内容块、互动控件、导航、wheel 单步、projection/answer/stepper、document/slide overflow → **PASS**。
- Practice：六个页面、三种 viewport、pane/hash 导航、choice/classify/diagnose/multi-question/reorder/state-simulator/stepper → **PASS**。
- 生成页的相对链接、starter 路径、学生/教师页面边界由 validator 与 browser smoke 双重检查 → **PASS**。
- 未执行 Ubuntu 专用本地流程；遵守本轮 Windows-only 要求。PR 既有 CI 状态仅作远端背景，不替代本地生成证据。

## 5. Content-layer boundary

Courseware 的旧 regression fixture 中仍有少量 Pedagogical Review warning（主要是历史资料的稀疏页/节奏问题），不影响结构/运行回归，但也不应被描述成 Gold 内容验收通过。数据库本机检测到 MySQL client 但没有连接/数据库，已把 live execution 记为 `skip`，没有伪报成功。

Holdout 审计将 `content_acceptance` 保持为 `pending_manual_review`。因此本报告的 PASS 只覆盖合同、结构、链接、泄漏、参考成果和真实浏览器行为；教师仍需看实际 HTML 的教学解释、课堂节奏和材料是否真的达到 Gold。
