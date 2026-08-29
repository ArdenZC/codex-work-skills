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

`total_hours` must equal the sum of lesson `hours`. `major` and `audience` are required input, not Python defaults.

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

The JSON schema defines item counts and character limits. Content QA additionally requires meaningful text and checks course-level differentiation.

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

The score is explicit, must be between 85 and 96, and uses half-point increments. Existing `score_breakdown()` only distributes that score across the protected 13-row table; it does not invent remarks. Generated score sequences must not be all identical, simple cycles, or mechanical arithmetic progressions.

References are objects with a visible `text` and internal `source_kind` (`provided`, `generic`, or `verified_public`). Generic references must not contain ISBN, standard numbers, publishers, authors, explicit years, editions, or file numbers. The formatter writes only `text` to DOCX.

## Agent workflow

Read all supplied course material once, confirm only missing course-level facts once, create a course outline, then author all lessons in JSON. Python formats existing values with numbering and line breaks. It must not author teaching prose, fall back to `flows`, cycle scores, or silently truncate over-capacity content.

After schema validation, run `scripts/content_quality.py` for adjacent and non-adjacent exact duplicates, calibrated field/implementation/whole-lesson similarity, repeated sentences, old boilerplate, progression coherence, completeness, density, score patterns, and domain contamination. Only after content QA passes should the generator create candidate DOCX files and run output/fidelity/render-smoke QA. The render report is smoke evidence only; visual inspection remains an Agent-level representative-page check.
