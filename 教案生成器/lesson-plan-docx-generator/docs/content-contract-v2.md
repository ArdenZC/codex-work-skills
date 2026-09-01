# Lesson Content V2 / V2.1

## 2.1 production addendum

Content Contract `2.1` is the current production contract. Runtime continues to read `2.0` inputs for compatibility; a 2.0 input keeps its lesson-level `references` objects and does not get silently rewritten. The default Word template remains `lesson-plan v1.1.2`.

Before planning, the Agent makes one concentrated confirmation containing `course_name`, `major`, `audience`, `total_hours`, `theory_hours`, `practice_hours`, theory/practice organization, `default_hours=2`, textbook, auxiliary references, and whether practice work orders are wanted. After that confirmation it does not ask again about outline, template, output directory, or DOCX generation.

The 2.1 course fields add:

```text
delivery_plan: mode, total_hours, theory_hours, practice_hours
course_materials: textbook (object or null)
reference_pool: concrete document/source objects (the Agent's course_reference_pool planning concept)
artifact_plan: lesson_plans=true, practice_work_orders=boolean
outline: lesson_id, unit, task, lesson_type, hours, theory_hours,
         practice_hours, prior_learning, capability_stage, deliverable,
         next_bridge, practice_task_ids
```

Each lesson adds `lesson_type` (`theory`, `practice`, or `integrated`), `theory_hours`, `practice_hours`, `reference_ids`, and `practice_task_ids`. All hour values are integer hours; lesson components and course totals must reconcile. A theory lesson cannot carry practice task IDs.

`course_materials.textbook` is not automatically a reference. It is rendered in a lesson only when `allow_textbook_as_reference: true` explicitly allows the same source in `reference_pool`. A 2.1 lesson may use `reference_ids: []`; the Word reference cell is blank, not a placeholder such as “无” or “资料不足”. `reference_pool` entries use `reference_type` (`book`, `standard`, `official_manual`, `official_documentation`, `guideline`, `paper`, `formal_course_document`) and concrete `title`/evidence. Generic placeholder phrases such as “统一建模语言相关公开文档” are rejected; real named organization/title documents are not rejected by that pattern. Pure tools and equipment remain resources, not references.

The same document reference may be reused in every lesson. Cross-lesson reference reuse is a reusable category and is excluded from exact, item, sentence, field, structural, frequency, and whole-course repetition hard-fails. Duplicate IDs inside one lesson and unresolved IDs remain hard failures. Do not invent different bibliographic identities merely to reduce repetition.

When `delivery_plan.practice_hours` is positive, `practice_task_contract` uses the independent [Practice Task Contract V1](practice-task-contract-v1.md) schema and must reconcile task hours and lesson links. If no work-order generator is available, the Lesson generator writes `practice-task-contract.json` as a handoff only.

Content Contract V2 (`2.0`) describes the compatibility teaching-content contract, while Content Contract `2.1` is the current production contract. Both are independent of the Word template version (`1.1.2` by default). The production generator accepts a complete V2.1 document or a complete V2.0 compatibility document; a missing or different `content_contract_version` is rejected with the legacy sparse-input message. A 2.0 document is not silently rewritten to 2.1.

## Course fields

```text
content_contract_version
course_name
major
audience
default_hours
total_hours
lessons
```

`total_hours` must equal the sum of lesson `hours`. `default_hours` is the default single-lesson duration used by the Agent when creating lessons; an explicit `lesson.hours` may override it, so it does not have to equal every lesson's hours. `default_hours`, `total_hours`, and `lessons[].hours` are positive integer lesson hours: integer JSON numbers and strings such as `"1"`, `"2"`, and `"2.0"` are accepted, while fractions, zero, negatives, whitespace, `NaN`, and `Infinity` are rejected. `major` and `audience` are required input, not Python defaults.

## Lesson fields

```text
lesson_id, unit, task, hours
progression: prior_lesson_id, prior_learning, capability_stage, deliverable, next_bridge
student_analysis: base, problems, strategies
teaching_content
goals: knowledge, ability, quality
key_point: content, strategy
difficult_point: content, strategy
teaching_methods, resources, references
implementation
evaluation: score, remarks
reflection: summary, innovation, improvement
```

The JSON schema defines item counts and character limits. `capability_stage` uses the closed vocabulary `认知`, `理解`, `模仿`, `独立`, `综合`, `优化`, `迁移`; it is varied across a long course but is not required to be mechanically monotonic. Content QA additionally requires meaningful text and checks course-level differentiation. `teaching_methods` and necessary tool/resource names may recur; substantive teaching prose may not be a renamed copy.

## Implementation stages

The nine stages and their order are fixed because they map to the existing semantic rows:

```text
before_class_preparation
task_introduction
operation_demonstration
task_implementation
task_extension
project_practice
peer_review
lesson_summary
after_class_improvement
```

Each stage supplies `id`, `label`, `minutes`, `modality`, `content`, `teacher_actions`, `student_actions`, and `objective`. The seven in-class stages are stages 2 through 8, each must be positive, and they must total `hours * 45` minutes. The first and last stages are outside the classroom total; each may be zero but must be no greater than `max(60, hours * 45)`, and together they must be no greater than `2 * hours * 45`. Runtime errors report lesson ID, stage, actual, and limit.

## Evaluation criteria

The remarks object is closed and must use exactly these IDs:

```text
attendance, attention, participation, compliance, values, ethics,
habits, online_learning, discussion, homework, practice, presentation,
improvement
```

The score is explicit, must be between 85 and 96, and uses half-point increments. Existing `score_breakdown()` only distributes that score across the protected 13-row table; it does not invent remarks. Every remark must be meaningful, and every Content V2 template version applies the 48-character contract limit without truncation; a manifest may only make that limit stricter. The schema `maxLength=80` remains a syntactic compatibility bound, not the rendered-density safety limit. Generated score sequences must not be all identical, strict monotonic/arithmetic sequences, or genuine simple cycles. A non-divisible partial tail is only cyclic after one initial period when the repeated tail is at least `max(3, ceil(period / 2))`; two coincidental tail values do not fail. Reports include `cycle_confidence`, `full_cycles`, `tail_length`, and `tail_fraction`.

References are objects with a visible `text`, internal `source_kind` (`provided`, `generic`, or `verified_public`), and optional internal `evidence`. A reference is a readable, citable document or source used as course basis: a textbook, course/teaching standard, national/industry/occupational standard, guideline, paper, public document, official technical manual, official product manual, or formal user-supplied teaching document. `resources` are teaching tools, equipment, environments, and materials such as PPT, projectors, MySQL Workbench, blood-pressure monitors, database servers, nursing models, computer rooms, task sheets, and datasets; standalone resource names do not satisfy `references`. A course-level reference pool may be reused across lessons, and cross-lesson reference repetition is explicitly allowed by `reference_reusable`; only same-lesson exact duplicates fail. Generic references must not contain ISBN, standard numbers, publishers, authors, explicit years, editions, file numbers, or a specific book-title form. `verified_public` requires URL or locatable official-source evidence; `provided` requires a real user-supplied file name or material identifier. Without real supplied material, the agent must not invent `provided` evidence. The deterministic boundary is `contract_and_locator_only`: Python validates evidence presence, locator form, and the conservative resource-only boundary, but does not prove an upload occurred or that a public source is true; the Agent verifies those facts before authoring JSON. The formatter writes only `text` to DOCX.

## Agent workflow

Read all supplied course material once, then make one concentrated confirmation of `course_name`, `major`, `audience`, `total_hours`, `theory_hours`, `practice_hours`, theory/practice organization, `default_hours=2`, textbook, auxiliary references, and practice-work-order preference. Textbook confirmation is recommended but not blocking. After that confirmation, create the course outline and author all lessons in JSON without asking again about the outline, template, output directory, or DOCX generation. Python formats existing values with numbering and line breaks. It must not author teaching prose, fall back to `flows`, cycle scores, or silently truncate over-capacity content.

After schema validation, run `scripts/content_quality.py` for adjacent and non-adjacent exact/item duplicates, calibrated field/implementation/whole-lesson and entity-masked structural similarity, repeated sentences, old boilerplate, independent intra-lesson task/body/deliverable coherence, separate artifact-inheritance and forward-transition progression gates, completeness, the 48-character evaluation remark contract, score patterns, and lesson-scoped domain contamination. `non_it_contamination` is scoped to IT-default terms absent from the input but injected into the rendered output by a template or generator; it is not a general course-domain classifier. Every detector uses one reuse policy: narrative fields are strict; teaching terminology, resources, references, and attendance/compliance/habits rubric remarks are reusable; metadata labels are ignored. References are excluded from every cross-lesson duplicate/similarity hard-fail path, while same-lesson duplicate references and conservative resource-only reference checks remain hard failures. Repetition diagnostics expose only limited fragments (maximum 120 characters) with stable SHA-256 digests. Short course-term exemptions never apply to narrative fields.

Each progression gate passes only when both lexical/coherence evidence and `substantive_anchor` evidence pass. Generic action overlap such as design, operation, analysis, checking, flow, or implementation cannot be an anchor; concrete Chinese fragments and technical acronyms can. A non-adjacent declared prior remains valid, but any physical sequence link with `status=review` sets `requires_agent_review=true` and records from/to/reason/score/declared_prior. The Agent must explicitly accept the actual teaching order or rewrite progression.

Only after content QA passes should the generator create candidate DOCX files and run output/fidelity/render-smoke QA, then atomically commit the output. The render report is LibreOffice smoke evidence only; `page_count_method=pdf_page_object_regex` is not pagination or visual QA. After real representative-page inspection, the Agent explicitly runs `scripts/record_visual_inspection.py` to persist `visual-inspection.json` with checks, inspected pages, notes, related QA report, output fingerprint, and timestamp. Python never auto-claims a visual pass. A visual failure requires revised V2 content and a transactional regeneration with `--backup-existing`.

## Acceptance evidence

Synthetic acceptance fixtures exercise deterministic contracts and must be reported as synthetic acceptance. A true Agent E2E is separate evidence: the Agent must author the complete V2 JSON from a natural-language course brief, generate the DOCX files, inspect representative pages, and answer whether the lessons remain visibly different after masking course, task, and topic names. Model-authored E2E evidence does not belong in deterministic CI.
