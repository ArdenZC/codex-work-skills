# Lesson Acceptance V2 Report

- Final status: **PENDING_MANUAL_REVIEW**
- Course: 数据结构与算法 / 软件技术专业 / 高职二年级
- Lessons/hours: 20 / 40.0
- Source: `synthetic_fixture`; master: `3ce9d0f7f8f044c382282bda892164bb015ad3ca`
- Content Contract: `2.4`; template: `v1.1.2`
- Render/production: `passed` / `production_pass`
- Delivery: `PASS`; reference gates: `PASS`; practice handoff: `not_applicable`
- Input SHA256: `69A225D09A20E7380BA2D507CF02E00036017CC9D50AD88F9B465942692B59B3`
- QA SHA256: `29039CD4FBDE5A99A2F2D456C44BB2C1C936B792A4D6C4B7B916F35A78B9C562`
- Output inventory SHA256: `E9D9E80A3FE7618259EEF96FA2A0E9B862F2DAB51A5B02494E231B552EBA51B2`
- Artifact manifest: `/workspace/codex-work-skills/教案生成器/lesson-plan-docx-generator/docs/evidence/issue-73-synthetic-course/artifacts/artifact-manifest.json`; SHA256: `398BF9A0FFE37C1A2A7BE55E705232CE96EEF0855B07226C5F2271D5165656B2`; run_id: `issue73-pilot-40h-separate`

## Structural hard gates

Overall: **PASS**

- `PASS` docx_inventory: DOCX inventory must contain exactly one output for every lesson.
- `PASS` qa_files_checked: Use the existing output QA file-count evidence.
- `PASS` total_hours: Declared Lesson coverage and current-contract course hours must agree with QA evidence.
- `PASS` content_contract: Acceptance 2.0 reads compatible Content Contract 2.0/2.1/2.2/2.3/2.4 inputs; it does not author content.
- `PASS` generation_evidence: Content 2.4 search, project workflow, per-Lesson comparison and course review evidence must validate and match QA.
- `PASS` course_profile: The final DOCX must independently reproduce the confirmed course, major, and audience profile.
- `PASS` delivery_consistency: Content 2.1–2.4 delivery hours and lesson/artifact accounting must reconcile.
- `PASS` reference_hard_gates: Reference identity, source and lesson bindings must reconcile; cross-lesson reuse is allowed when relevant.
- `PASS` practice_handoff: Practice Task Contract task links and practice-hour sums must reconcile.
- `PASS` template_identity: Selected template must be lesson-plan v1.1.2.
- `PASS` template_names_and_fidelity: Names, protected layout, writable-field fidelity, and existing QA errors must be clean.
- `PASS` semantic_bookmarks: Existing semantic bookmark inventory/fidelity evidence must be clean when applicable.
- `PASS` content_quality: Content QA status is read from the production qa-report.json.
- `PASS` render_smoke: All DOCX render smoke must pass; visual review remains a separate manual layer.
- `PASS` artifact_manifest: Manifest must map source and final DOCX/PDF hashes, retained-PDF page counts, and matching QA/render/production status.

## Confirmed course profile evidence

- Status: **PASS**; expected: `{"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}`
- Evidence: `[{"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案01_项目一：线性结构与受限容器_线性表的逻辑结构、顺序存储与复杂度.docx", "lesson_id": "L01", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案02_项目一：线性结构与受限容器_单链表节点、头指针与插入删除边界.docx", "lesson_id": "L02", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案03_项目一：线性结构与受限容器_栈、队列与循环队列的约束模型.docx", "lesson_id": "L03", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案04_项目一：线性结构与受限容器_实现顺序表新增、查找和容量边界检查.docx", "lesson_id": "L04", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案05_项目一：线性结构与受限容器_完成单链表插入、删除、反转与指针检查.docx", "lesson_id": "L05", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案06_项目一：线性结构与受限容器_用栈与循环队列完成表达式和排队模拟.docx", "lesson_id": "L06", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案07_项目二：树与图关系处理_二叉树结构、存储方式与遍历次序.docx", "lesson_id": "L07", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案08_项目二：树与图关系处理_二叉搜索树的查找、插入与退化情形.docx", "lesson_id": "L08", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案09_项目二：树与图关系处理_图的邻接表、邻接矩阵、DFS与BFS.docx", "lesson_id": "L09", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案10_项目二：树与图关系处理_加权无向图最小生成树与PrimKruskal.docx", "lesson_id": "L10", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案11_项目二：树与图关系处理_构建二叉树并输出三种遍历与层序结果.docx", "lesson_id": "L11", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案12_项目二：树与图关系处理_实现二叉搜索树并测试查找插入删除.docx", "lesson_id": "L12", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案13_项目二：树与图关系处理_实现DFSBFS并核验访问顺序与连通分量.docx", "lesson_id": "L13", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案14_项目二：树与图关系处理_比较Prim与Kruskal并校验路线变更影响.docx", "lesson_id": "L14", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案15_项目三：排序与检索性能_稳定性、原地性与插入排序工作机理.docx", "lesson_id": "L15", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案16_项目三：排序与检索性能_快速排序分区不变量、递归与复杂度.docx", "lesson_id": "L16", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案17_项目三：排序与检索性能_查找策略、散列表冲突与负载因子.docx", "lesson_id": "L17", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案18_项目三：排序与检索性能_实现插入排序并验证稳定性和比较次数.docx", "lesson_id": "L18", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案19_项目三：排序与检索性能_实现快速排序分区并采集递归比较数据.docx", "lesson_id": "L19", "major": "软件技术专业"}, {"audience": "高职二年级", "course_name": "数据结构与算法", "exact_match": true, "expected": {"audience": "高职二年级", "course_name": "数据结构与算法", "major": "软件技术专业"}, "file": "教案20_项目三：排序与检索性能_实现库存条目检索并测试散列冲突处理.docx", "lesson_id": "L20", "major": "软件技术专业"}]`
- Profile values are read from every final DOCX semantic field after generation; this is an independent smoke profile check.

## Final artifact chain

- Source JSON: `/workspace/codex-work-skills/教案生成器/lesson-plan-docx-generator/docs/evidence/issue-73-synthetic-course/pilot-40h-separate/lesson-content-v2.4.json` / `69A225D09A20E7380BA2D507CF02E00036017CC9D50AD88F9B465942692B59B3`
- Final DOCX: `20 per-Lesson files; see the manifest for paths and SHA256 values`
- Final PDF: `20 per-Lesson files; see the manifest for paths and SHA256 values`
- Retained final PDF pages: `130`; QA: `passed`; render: `passed`; production: `production_pass`
- Reference evidence: `reference-evidence.json` / `70B56472D127E999835DB8E7FA0B7EC22D3F3F93B48731D44BCA0C232E83FB21`
- Page count and hashes are read from the retained final files; this report does not handwrite them.


## Existing Content QA evidence

- QA status: `passed`; detector counts: `{"adjacent_exact_duplicates": 0, "adjacent_implementation_exact_duplicates": 0, "adjacent_item_duplicates": 0, "adjacent_similarity_pairs": 0, "evaluation_remark_duplicates": 0, "exact_duplicates": 0, "field_similarity_pairs": 0, "frequency_item_duplicates": 0, "implementation_duplicates": 0, "implementation_similarity_pairs": 0, "implementation_structural_similarity_pairs": 0, "item_duplicates": 0, "repeated_sentences": 0, "structural_similarity_pairs": 0, "whole_lesson_similarity_pairs": 0}`
- Similarity/duplicate values are evidence copied from the existing QA report; this harness adds no new hard threshold.
- Render page counts and file mappings are read from artifact-manifest.json, not hand-written in this report.
- Reference reuse remains course-reusable; only same-lesson duplicate/resource-only decisions belong to the existing reference QA.

## Sequence and boundaries

- Physical transitions: 19; summary: `{"FAIL": 0, "PASS": 19, "REVIEW": 0, "boundaries": 2}`
- Review details are expanded for failed/review links and unit boundaries only.

## Manual review status

- Visual: `not_executed`
- Teaching design: `not_executed`
- Teacher usability: `not_executed`
- Course scope: `not_executed`
- Hallucination/provenance: `no_flags`
- Manual completion required: `["visual_review", "teaching_design_review", "teacher_usability", "course_scope_review"]`
- Read 4-6 representative lessons in full: L01, a boundary before/after, a complex/high-density lesson, and L32 when present.
- Teacher rubric is 1-5 across all five documented criteria; the report requires complete per-Lesson assessments, usable_count, and tweak_count.

## Scope and length

- Course scope must classify every project as CORE / EXTENSION / POSSIBLE_SCOPE_DRIFT; each POSSIBLE_SCOPE_DRIFT needs reviewer disposition and notes.
- Length values are descriptive distributions only. There is no must-differ rule.

## Negative controls

- Negative Controls remain a release/qualification concern; their default not_executed state does not block a per-course Acceptance 2.0 pass.
- Any supplied Negative Controls payload with failed/fail/rejected status still makes Acceptance FAILED.
- Current negative-control status: `not_executed`

## Provenance and hallucination review

- Real Agent A/B generation is local-only evidence and is not a CI test.
- School, teacher, textbook, ISBN, schedule, and generic detailed bibliography fields are review flags, not automatic falsehoods; every detected flag must have an explicit disposition and notes before a pass.
- The optional `--hallucination-review` JSON accepts a `dispositions` list keyed by each flag's `kind` and `path`.
- Historical baselines are comparison-only and do not create thresholds.

## Interpretation

- `PENDING_MANUAL_REVIEW` is not a pass claim. Visual, teaching-design, teacher-usability, course-scope, and hallucination/provenance gates must close before PASSED or PASSED_WITH_TEACHER_ADJUSTMENTS.
- CLI exits are 0 for either passed status, 1 for FAILED, 3 for PENDING_MANUAL_REVIEW, and 2 for report errors. `--allow-pending-exit-zero` restores the legacy pending exit code for compatible callers.
