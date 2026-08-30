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

`total_hours` must equal the sum of lesson `hours`. `default_hours` is the default single-lesson duration used by the Agent when creating lessons; an explicit `lesson.hours` may override it, so it does not have to equal every lesson's hours. `major` and `audience` are required input, not Python defaults.

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

Each stage supplies `id`, `label`, `minutes`, `modality`, `content`, `teacher_actions`, `student_actions`, and `objective`. The seven in-class stages are stages 2 through 8 and must total `hours * 45` minutes. The first and last stages are outside the classroom total.

## Evaluation criteria

The remarks object is closed and must use exactly these IDs:

```text
attendance, attention, participation, compliance, values, ethics,
habits, online_learning, discussion, homework, practice, presentation,
improvement
```

The score is explicit, must be between 85 and 96, and uses half-point increments. Existing `score_breakdown()` only distributes that score across the protected 13-row table; it does not invent remarks. Every remark must be meaningful, and every Content V2 template version applies the 48-character contract limit without truncation; a manifest may only make that limit stricter. The schema `maxLength=80` remains a syntactic compatibility bound, not the rendered-density safety limit. Generated score sequences must not be all identical, simple cycles of any period, or mechanical arithmetic progressions.

References are objects with a visible `text`, internal `source_kind` (`provided`, `generic`, or `verified_public`), and optional internal `evidence`. Generic references must not contain ISBN, standard numbers, publishers, authors, explicit years, editions, file numbers, or a specific book-title form. `verified_public` requires URL or locatable official-source evidence; `provided` requires a real user-supplied file name or material identifier. Without real supplied material, the agent must not invent `provided` evidence. The formatter writes only `text` to DOCX.

## Agent workflow

Read all supplied course material once, confirm only missing course-level facts once, create a course outline, then author all lessons in JSON. Python formats existing values with numbering and line breaks. It must not author teaching prose, fall back to `flows`, cycle scores, or silently truncate over-capacity content.

After schema validation, run `scripts/content_quality.py` for adjacent and non-adjacent exact/item duplicates, calibrated field/implementation/whole-lesson and entity-masked structural similarity, repeated sentences, old boilerplate, separate artifact-inheritance and forward-transition progression gates, completeness, the 48-character evaluation remark contract, score patterns, and lesson-scoped domain contamination. Only after content QA passes should the generator create candidate DOCX files and run output/fidelity/render-smoke QA, then atomically commit the output. The render report is LibreOffice smoke evidence only, not pagination or visual QA; visual inspection is a post-commit Agent-level representative-page check. A visual failure requires revised V2 content and a transactional regeneration with `--backup-existing`.

## Acceptance evidence

Synthetic acceptance fixtures exercise deterministic contracts and must be reported as synthetic acceptance. A true Agent E2E is separate evidence: the Agent must author the complete V2 JSON from a natural-language course brief, generate the DOCX files, inspect representative pages, and answer whether the lessons remain visibly different after masking course, task, and topic names. Model-authored E2E evidence does not belong in deterministic CI.
