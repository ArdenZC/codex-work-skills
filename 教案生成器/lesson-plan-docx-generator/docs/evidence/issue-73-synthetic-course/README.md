# Issue #73 full-course pilot evidence

This folder records a **synthetic** 40-hour, three-project data-structures course used to exercise Content Contract 2.4 and the original DOCX/PDF generator. It is not a real school's approved syllabus, a teacher review, or evidence that the generated course has been used in class.

## Root causes and implementation

The previous Content 2.3 delivery ledger deliberately counted only theory Lesson hours for `split_lessons`, while `practice_only` counted zero Lesson hours. Practice WorkOrders were a separate artifact and could therefore be mistaken for the practice course itself. Reference searches and exemplar comparisons were recommended in Skill text, but the normal generation path did not require auditable search receipts, read captures, or per-Lesson comparison records. Project instructions also lacked a checked merge boundary. Finally, a structural QA pass could be mistaken for a teaching-quality pass.

Content 2.4 adds explicit whole-course coverage while preserving the old contract meanings:

| Contract/mode | Meaning |
| --- | --- |
| Content 2.2/2.3 `split_lessons` | Historical theory-only Lesson coverage remains unchanged. |
| Content 2.2/2.3 `practice_only` | Historical zero-Lesson behavior remains unchanged. |
| Content 2.4 `theory_only` | Lessons cover every theory hour. |
| Content 2.4 `practice_only` | Practice Lessons cover every practice hour. |
| Content 2.4 `separate_full_lessons` | Separate theory and practice Lessons cover the complete course ledger; `split_lessons` is rejected. |
| Content 2.4 `integrated_lessons` / `hybrid` | Retain their full-course Lesson coverage behavior. |

The 2.4 ledger checks Lesson count, ID uniqueness, hours, type, theory/practice sums, and the frozen course totals. Practice tasks remain optional additional materials linked to practice Lessons; they do not add hours or replace Lessons. The existing nine-stage structure, stage IDs, scoring rules, rating values, and v1.1.2 template binary are unchanged.

Content 2.4 generation also requires a hash-bound evidence sidecar. Its validator checks the frozen outline and shared facts, actual-search receipts and outcomes, captured source reads and lesson scope, exemplar research, all 15 existing comparison dimensions for every Lesson, revision/re-review records, project merge results, and the main Agent's course reconciliation. Missing search, fabricated/unbound references, missing comparison, duplicate IDs, cross-project scope conflicts, and hour mismatches fail closed. Acceptance calls the result `evidence_complete` only to describe completed workflow evidence; it is not an automated pedagogical pass or a formal blind benchmark.

## Frozen course and generated coverage

Each meeting is 2 hours. The frozen outline contains 20 Lessons and the complete course contains 40 hours:

| Project | Lesson IDs | Theory | Practice | Total |
| --- | --- | ---: | ---: | ---: |
| Project 1: linear structures and restricted containers | L01–L06 | 6 h | 6 h | 12 h |
| Project 2: trees and graph relationships | L07–L14 | 8 h | 8 h | 16 h |
| Project 3: sorting and search performance | L15–L20 | 6 h | 6 h | 12 h |
| **Course** | **L01–L20** | **20 h** | **20 h** | **40 h** |

The project merge report records 20 unique IDs, the frozen outline hash, project input/output hashes, no duplicate IDs, no project scope conflicts, and matching 40/20/20 hour totals. The main review records the L06→L07 and L14→L15 boundaries, consistent terminology and frozen case data, and theory-to-practice handoffs.

| Evidence | File |
| --- | --- |
| Frozen outline and shared case facts | `frozen-course-outline.json`, `frozen-shared-course-facts.json` |
| Three project Agent returns | `project-work/project-1-linear.json`, `project-work/project-2-tree-graph.json`, `project-work/project-3-sort-search.json` |
| Deterministic project merge | `project-merge-report.json` |
| Merged Content 2.4 | `pilot-40h-separate/lesson-content-v2.4.json` |
| Search, reading, subagent, comparisons, and course review evidence | `pilot-40h-separate/generation-evidence.json` |

The session supported subagents and actually delegated one whole project per Agent: `project_linear`, `project_tree_graph`, and `project_sort_search`. Each returned all theory and practice Lessons for its assigned project. No fallback was used for this pilot. A separate unit test verifies the sequential main-Agent fallback record when subagents are unavailable; that test fixture is not presented as a real fallback run.

## Verified Chinese references

The project workers recorded 29 bibliography-search receipts and 21 exemplar-search receipts. The receipts preserve the actual Chinese query text, tool, timestamp, returned URLs, project/Lesson scope, and outcome. Search results are not treated as read sources.

1. 杨淑萍、聂哲：《数据结构（Java版）》，高等教育出版社，2013年7月，ISBN 978-7-04-037626-5. [Official publisher product page](https://xuanshu.hep.com.cn/front/h5Mobile/bookDetails?bookId=59ce6307ba9eb884cf81dc1c). The page identifies its vocational-education readership and exposes the table of contents. It does not show a numbered edition. It displays a latest-impression field of 2013年1月; that field is retained as displayed and is not treated as an edition or used to infer one.
2. 张静：《数据结构（Java语言描述）（换封面，十四五）》，高等教育出版社，2021年5月，ISBN 978-7-04-055957-6；the publisher page lists a 2024年11月 latest impression. [Official publisher product page](https://xuanshu.hep.com.cn/front/h5Mobile/bookDetails?bookId=648deb81938b7cc2960f04a1). The page title includes “十四五” but does not state a numbered edition.

The publisher pages were directly opened and read. The metadata and table of contents support topic relevance; no textbook chapter body is claimed to have been read. The 2013 book's table of contents supports the linear-list and stack/queue lessons, and the two books' catalog topics support the tree, graph, sorting, and search scope as recorded per Lesson in the project evidence.

For the requested theory/practice pilot examples, L01 theory is mapped to REF-HEP-JAVA-2013's linear-list and complexity contents. L19 practice is mapped to REF-HEP-JAVA-2021's sorting topics and the read QuickSort teaching design EX-AIIT-QUICKSORT; the exemplar contributes bounded activity/feedback methods, not textbook facts.

The Hubei Normal University OPAC URL appeared in the actual `Q-HEP-ISBN-01` search result. A direct `fetch_content` attempt at 2026-10-29T10:20:45Z returned `proxy_error` and no extracted text. **It is not counted as an independent bibliographic verification.** The P1 project record preserves the search result, failed-read status, and zero verified fields; the final reference evidence binds the ISBN to the directly read HEP publisher page.

## Exemplar research and 15-dimension comparisons

Before drafting, each project searched for topic- and learner-relevant public teaching designs. Agents read the returned documents themselves and recorded excerpts, read scopes, hashes, transferable methods, and limitations. Among the readable sources were:

- 程菲, 安徽信息工程学院教务处：《数据结构与算法》线上教学设计, a complete 17-page, one-hour QuickSort lesson. Its population and programming prerequisite differ from this synthetic vocational course; it is used only for bounded method transfer, and the exact topic match is L19.
- 张静, 公安海警学院, 《遍历二叉树》 teaching design: a complete short public micro-course design read from its PDF; its platform record did not establish an award.
- A full paper on binary-tree preorder teaching design and a full graph-course content-design paper. Both were read, but are used only within the recorded topic and genre limits; neither is represented as a full minute-by-minute excellent lesson.

No source had sufficient evidence to be labeled “excellent,” “award-winning,” or an official demonstration lesson. The workflow is recorded as `completed_limited_comparison`, not a formal A/B review. Search results that were only course descriptions, syllabi, or event reports were not passed off as complete lesson exemplars. Project 2's BST workshop news story, for example, is recorded as a limited secondary account and is not counted as a full teaching design.

All 20 Lessons have a post-draft comparison against the existing 15 dimensions. Each dimension records the current design, concrete evidence, gap, improvement reason, and disposition. Where a substantive issue was found, the project return records the revision and re-review; where not, it records why the draft was retained. The source-by-Lesson mappings and full comparison records are in `generation-evidence.json` and the project returns.

## Actual generator, QA, and Acceptance

The original generator rendered the synthetic Content 2.4 through the unchanged v1.1.2 template. Retained artifacts are in `artifacts/`:

- 20 per-Lesson DOCX and 20 per-Lesson PDF files.
- 40 total hours, 130 PDF pages, Content Contract 2.4.
- Generator: `production_status=production_pass`, QA `passed`, render `passed`.
- Content-quality QA: zero errors/warnings and zero reported duplicate/similarity detector findings.
- Manifest hash-binds the Content, generation-evidence sidecar, 20 DOCX/PDF pairs, and QA report.

These statuses establish generation, consistency, and structural QA for this synthetic fixture. They do not establish that a teacher has visually inspected the pages, approved the scope, or accepted the teaching design. The generated [Acceptance report](acceptance-final/lesson-acceptance-report.md) therefore remains **`PENDING_MANUAL_REVIEW`**: visual review, teaching-design review, teacher usability, and course-scope review were not executed. The stored report makes this limitation explicit.

The generator run did not request WorkOrders. Contract tests cover both 40-hour `practice_only` cases with no WorkOrders and with 20 linked two-hour tasks; the tasks are additional artifacts and the Lesson ledger stays at 40 hours. The tests also cover the 40-hour split course with and without WorkOrders, 40-hour theory-only, missing and duplicate Lessons, split mismatch, unexecuted search, fake citation, absent exemplar comparison, subagent fallback, duplicate project results, cross-project conflicts, changed hour totals, and preservation of frozen outline order. The actual 40-hour DOCX/PDF render in this folder is the 20-theory/20-practice case; no separate pure-practice DOCX set is claimed here.

## Test and review boundaries

The existing historical Content 2.2/2.3 tests, final Acceptance lifecycle tests, and the new Content 2.4 tests are kept in the repository test shards.

Local results on this branch:

- Content 2.4: 9 tests passed.
- Historical Content 2.2/2.3: 76 tests passed.
- Lesson skill hardening: 38 tests passed.
- Final Acceptance lifecycle: 92 tests passed, including the existing benchmark-linked render and acceptance cases.
- Shard partition checks for lesson content/package separation: 2 tests passed; the new 2.4 module is in the lesson-content shard.
- Full `tests.test_run_test_shards`: 30 of 31 passed. The remaining failure is the unchanged gradebook package's `test_template_validator`, which reports protected formatting differences in the gradebook v1.1.0 workbook. This PR does not modify that package or its template. Exact-HEAD GitHub Actions status is recorded in the Issue #73 Draft PR.

A structural or workflow-evidence pass must not be quoted as teacher approval, pedagogical quality acceptance, visual approval, or a formal blind benchmark.
