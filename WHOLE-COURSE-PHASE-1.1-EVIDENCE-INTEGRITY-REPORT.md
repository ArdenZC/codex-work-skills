# Whole-Course Orchestration Phase 1.1 — Evidence Integrity & Batch QA Repair

> Historical Phase 1.1 report. The current authoritative closeout is [WHOLE-COURSE-PHASE-1.1-CLOSEOUT-REPORT.md](WHOLE-COURSE-PHASE-1.1-CLOSEOUT-REPORT.md), which supersedes the earlier marker-only visual and degraded-browser wording below.

状态：`WHOLE_COURSE_ARCHITECTURE_BLOCKED`

本报告是 Phase 1.1 对 [Phase 1.0 架构报告](WHOLE-COURSE-ARCHITECTURE-REPORT.md) 的证据完整性补充。它只报告本分支上的架构修复、synthetic downstream E2E 和批量 QA；没有运行真实 `9 PPT × 16 theory × 16 practice` blind retry，也没有读取旧合同/旧 HTML 作为新生成输入。

## A. Scope and baseline

- Repository：`ArdenZC/codex-work-skills`。
- Same PR：`#31`，branch `feature/whole-course-orchestration`，base `master`；不新开 PR、不合并、不改 tag。
- Phase 1.1 起点：`10599fe994d004bd4b6691753bb485447074e321`；`origin/master` 仍为 `3c8fe4a29a4a057cf24e1f3d2b691eb1f9c2408a`。
- 原始仓库 `F:\work\codex-work-skills` 未修改；本分支新增证据脚本、schema 兼容字段、下游适配器、E2E 测试和本报告。
- 冻结的 `WHOLE_COURSE_FAILURE_BENCHMARK_V1` 保持原样；旧 UML failure 仍然是回归基准，不被新 synthetic 结果覆盖。

## B. Evidence state model

所有课程级要求现在明确分成三态：

- `required`：合同或具体 teaching question 明确要求的验收元素；
- `planned`：planner/adapter 声明准备生成的元素；
- `observed`：最终 Courseware DOM、最终 Practice 文件、manifest/QA 或真实 contact-sheet 产物实际观察到的元素。

`planned` 不再自动变成 `observed`，planner 也不能验证自己的输出。没有最终 DOM/文件时，visual evidence 是 `FAIL` 或 `PLANNED_NOT_OBSERVED`；没有 starter 文件时，starter evidence 是 `NOT_OBSERVED`。浏览器不可用时保留 `UNAVAILABLE_OR_DEGRADED`，不会转换成最终 PASS。

## C. Multi-asset source mining

`mine_teaching_assets.py` 现在按 slide element 拆分文字、表格、图片、shape、connector/arrow、speaker notes 和 rendered visual reference，并保留 `source_slide_id`、`source_element_ids`、`source_region`、image SHA-256 和本地 asset root。T15/T16 验证同一页的多项素材不会被合成一个模糊 asset，shape graph 与 connector 不会丢失。

最终 synthetic E2E 观察到 3 source slides、6 source assets；这是下游链路证据，不是对真实 9 份 UML PPT 的覆盖声明。

## D. Shape graph and semantic visual evidence

Visual plan 输出 `required_semantic_elements`、`planned_semantic_elements`、`observed_semantic_elements` 和证据状态。Stable Courseware renderer 的 SVG/image figure 保留 artifact type、semantic role 和 source asset marker；`collect_visual_evidence.py` 只从最终 HTML DOM 读取这些 marker。

最终 E2E 结果：4/4 visual plans observed `PASS`。T17/T18 覆盖了“只有计划没有 DOM”失败和嵌套 DOM marker 的真实读取；generic rectangle 不能满足 typed visual contract。

## E. Starter artifact evidence

`collect_starter_evidence.py` 读取真实 starter 文件、manifest、QA 和 behavior evidence；它不复制 planner 的组件列表当作观察结果。draw.io class starter 观察 `partial_classes`、`missing_relationship`、`missing_multiplicity`，sequence starter 观察 lifelines/messages/order 等语义缺口。

最终 E2E 生成并由真实 Practice renderer 产出 3 个 starter，starter evidence 为 `PASS`；T19/T20 验证 plan-only 与真实 draw.io 文件的边界。

## F. Timing and layout integrity

Release mode 缺少问题级 time/effort evidence 会 fail；draft mode 只能明确标记 `DEGRADED_ESTIMATE`。页数和 layout 是问题、证据、活动和结果的后置映射，不使用默认 equal-share lecture ratio。

最终 E2E 的 session page counts 为 `2, 2, 2`，但 layout sequences 为：

```text
[split, check]
[semantic-diagram, semantic-diagram]
[step-build, diagnose]
```

每页 lecture/activity minutes 为：

```text
[(2.2, 1.8), (3.4, 0.6)]
[(5.25, 1.75), (5.25, 1.75)]
[(6.7, 3.3), (4.32, 1.68)]
```

T21/T22 覆盖 release hard fail 与 draft degraded estimate；下游 Courseware QA 的 3 个 synthetic session 均 `pass`。

## G. Similarity and template-collapse QA

`review_whole_course.py` 使用冻结证据和 calibration 记录 `pair_threshold=0.85`、`cluster_fraction=0.70`，并把 knowledge IDs 从 structural practice signature 中排除，避免换 ID 掩盖同构。

最终 rendered script QA：6 个脚本，same-position similarity mean `0.3857`、max `0.5243`、generic phrase ratio `0`、repeated sentence cluster `0`，没有 `SCRIPT_CROSS_SESSION_TEMPLATE_REUSE`。T28/T30 仍能让旧式同构 fixture 触发 collapse；冻结 UML benchmark 的 failure status 仍为 `FAIL`。

## H. Source ↔ knowledge ↔ research gap

Asset-to-knowledge link 只接受 Agent explicit mapping、course-map `source_assets` 或记录过的 title/text semantic matching；不会把 `candidate_topics` 或任意 asset ID 直接当成 knowledge node ID。最终 synthetic graph 有 2 条显式 asset-knowledge links，未产生 synthetic research gap；T25/T26 同时覆盖误报抑制和真实 `missing_visual` gap 保留。

外部 research 仍由 Agent/宿主提供候选来源；Python 只保存 relevance、authority、provenance、selected/rejected reason 和用户禁网/不可用状态，不伪造网页证据。

## I. Downstream three-session E2E

`downstream_e2e.py` 的链路为：source fixture → asset mining → knowledge graph → session/visual/practice plans → Courseware adapter → **real Courseware renderer** → DOM visual evidence → Practice adapter → **real Practice renderer** → starter evidence → whole-course QA → contact sheets。

最终运行结果：

- Courseware：3/3 renderer outputs；每个 Courseware pedagogical status `PASS`；
- Practice：3/3 renderer outputs，QA `pass, pass, pass`；
- rendered visual semantic coverage：`4/4 PASS`；
- starter semantic evidence：`PASS`；
- actual source asset usage：`PASS`，6 个 source asset 均有最终 rendered evidence；
- script-to-slide grounding：`6/6 PASS`；
- plan QA：`PASS`；render QA：`PASS`；findings：空；
- downstream compatibility outputs 使用稳定 renderer 的 `migration-trust` 兼容模式；这不是新 generation 的 strict acceptance，也不是 blind retry 结果。

## J. Contact-sheet integrity

`contact_sheets.py` 不下载浏览器或伪造 screenshot。当前宿主没有可用 browser runtime，因此最终 contact-sheet evidence 为 `DEGRADED`，但仍从最终 HTML DOM/真实 draw.io starter 生成了 10 个可定位 SVG thumbnail：6 个 theory pages、1 个 source visual asset、3 个 Practice starter。

因此本节是“真实文件缩略图存在，但真实浏览器 render proof 未完成”，不能写成 contact-sheet PASS。最终 E2E JSON SHA-256 为：

```text
109AF6EDC771B6D193443A9C4EB37E39FA984A4DC7A01F37EB9CDDCC256CBC36
```

## K. Frozen old benchmark

`WHOLE_COURSE_FAILURE_BENCHMARK_V1` 仍保留 9 source PPT、16 theory contracts、16 practice contracts、历史渲染/QA/审计 evidence 的定位与 hash。T30 证明旧 shape 仍触发预期 failure findings；没有对旧 UML 产物手工编辑或重新生成。

## L. Regression and CI coverage

- Whole-Course tests：34 passed（原 T1–T14 + Phase 1.1 T15–T32 + rendered-script regression T33）。
- Whole-Course compileall：passed。
- Courseware tests：38 passed。
- CI change-classifier tests：16 passed。
- Whole-Course installer dry-run：passed，`dry-run=yes (no filesystem mutation)`。
- Practice 本机完整套件：67 tests 中 64 passed、3 个因本机没有 CI 专用 Flask (`ModuleNotFoundError: No module named 'flask'`) 未通过；仓库 CI 明确从 `.github/scripts/requirements-ci-practice-tests.txt` 安装 Flask 3.x，本次没有静默安装依赖或修改 Practice renderer。
- Root tests that require `python-docx`/PyYAML were not represented as PASS in this host because those optional test dependencies are absent。
- CI workflow 现在显式包含 compile、synthetic tests、downstream E2E/contact smoke 和 installer dry-run；`--allow-degraded-browser` 只允许 smoke 命令记录 blocked 状态后退出成功，不改变 JSON 的最终 blocked 状态。

## M. Human and environment boundary

自动 QA 不等于教师 pedagogical acceptance。尚未宣称真实课程质量通过，也未完成真实 Windows/Chrome whole-course render、真实用户 PPT 覆盖、代表性页面人工视觉检查、教师接受或外部资料人工版权确认。`migration-trust` 仅是兼容回归 evidence；strict new-generation evidence 和 human acceptance 仍需后续真实流程。

## N. Final gate and next action

Phase 1.1 当前最终状态为：

```text
WHOLE_COURSE_ARCHITECTURE_BLOCKED
```

阻断条件只有未完成的 browser/runtime contact-sheet proof；内容、计划、下游 renderer、DOM/file evidence 和 automated batch QA 已分别报告为通过。下一步只能在具备可定位 browser runtime 后重新执行同一 synthetic E2E/browser smoke，确认 contact-sheet status 为 `PASS`，再由人工审查代表性理论页、复杂视觉、实践 starter、时间容量和跨课差异；在此之前不应运行真实 9-PPT blind retry。
