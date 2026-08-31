# Lesson Content V2

Content Contract V2 (`2.0`) describes teaching content. It is independent of the Word template version (`1.1.2` by default). The production generator accepts only a V2 document; a missing or different `content_contract_version` is rejected with the legacy sparse-input message.

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

References are objects with a visible `text`, internal `source_kind` (`provided`, `generic`, or `verified_public`), and optional internal `evidence`. Generic references must not contain ISBN, standard numbers, publishers, authors, explicit years, editions, file numbers, or a specific book-title form. `verified_public` requires URL or locatable official-source evidence; `provided` requires a real user-supplied file name or material identifier. Without real supplied material, the agent must not invent `provided` evidence. The deterministic boundary is `contract_and_locator_only`: Python validates evidence presence and locator form, but does not prove an upload occurred or that a public source is true; the Agent verifies those facts before authoring JSON. The formatter writes only `text` to DOCX.

## Agent workflow

Read all supplied course material once, confirm only missing course-level facts once, create a course outline, then author all lessons in JSON. Python formats existing values with numbering and line breaks. It must not author teaching prose, fall back to `flows`, cycle scores, or silently truncate over-capacity content.

After schema validation, run `scripts/content_quality.py` for adjacent and non-adjacent exact/item duplicates, calibrated field/implementation/whole-lesson and entity-masked structural similarity, repeated sentences, old boilerplate, independent intra-lesson task/body/deliverable coherence, separate artifact-inheritance and forward-transition progression gates, completeness, the 48-character evaluation remark contract, score patterns, and lesson-scoped domain contamination. `non_it_contamination` is scoped to IT-default terms absent from the input but injected into the rendered output by a template or generator; it is not a general course-domain classifier. Every detector uses one reuse policy: narrative fields are strict; teaching terminology, resources, references, and attendance/compliance/habits rubric remarks are reusable; metadata labels are ignored. Repetition diagnostics expose only limited fragments (maximum 120 characters) with stable SHA-256 digests. Short course-term exemptions never apply to narrative fields.

Each progression gate passes only when both lexical/coherence evidence and `substantive_anchor` evidence pass. Generic action overlap such as design, operation, analysis, checking, flow, or implementation cannot be an anchor; concrete Chinese fragments and technical acronyms can. A non-adjacent declared prior remains valid, but any physical sequence link with `status=review` sets `requires_agent_review=true` and records from/to/reason/score/declared_prior. The Agent must explicitly accept the actual teaching order or rewrite progression.

Only after content QA passes should the generator create candidate DOCX files and run output/fidelity/render-smoke QA, then atomically commit the output. The render report is LibreOffice smoke evidence only; `page_count_method=pdf_page_object_regex` is not pagination or visual QA. After real representative-page inspection, the Agent explicitly runs `scripts/record_visual_inspection.py` to persist `visual-inspection.json` with checks, inspected pages, notes, related QA report, output fingerprint, and timestamp. Python never auto-claims a visual pass. A visual failure requires revised V2 content and a transactional regeneration with `--backup-existing`.

## Acceptance evidence

Synthetic acceptance fixtures exercise deterministic contracts and must be reported as synthetic acceptance. A true Agent E2E is separate evidence: the Agent must author the complete V2 JSON from a natural-language course brief, generate the DOCX files, inspect representative pages, and answer whether the lessons remain visibly different after masking course, task, and topic names. Model-authored E2E evidence does not belong in deterministic CI.
