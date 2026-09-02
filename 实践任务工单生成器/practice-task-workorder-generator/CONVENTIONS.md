# Practice Task WorkOrder conventions

- Treat the canonical Practice Task Contract V1 as authoritative.
- Keep `practice_task_id`, `lesson_ids`, and `practice_hours` unchanged.
- Do not silently rewrite the upstream Lesson artifact.
- Keep attendance at 10, task items at 90, and total score at 100.
- Keep the student task-result area blank; do not produce a teacher answer or standard result.
- Use `practice-work-order v1.0.0` and run Content, Cross-Artifact, and Output QA.
- `--practice-task-json` is only a validated handoff/authoring-skeleton path; never use it to generate production Content or DOCX. Agent-authored Content V1 is required.
- Publish a batch only after every candidate, Output QA result, and requested render has passed; `skipped` is not a render pass.
- Successful installer replacement deletes temporary backups by default; use `--keep-backup` when an explicit previous copy is needed.
