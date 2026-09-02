# WorkOrder adapter

Before generating a student practice work order, read `简介.md`, `通用提示词.md`, and `SKILL.md`.

The canonical Practice Task Contract V1 is the upstream fact source. `--practice-task-json` is handoff-only: it may validate and emit an authoring skeleton, but the Agent must author complete WorkOrder Content V1 before any DOCX. Preserve its task ID, lesson IDs, hours, deliverables, acceptance criteria, tools/materials, and safety/compliance constraints. Use the existing `practice-work-order v1.0.0` template, keep attendance at 10 and Agent-decided task items totaling 90, leave student task results blank, and never create teacher answers. Run Content QA, Cross-Artifact QA, and Output QA before delivery; requested render must be `pass`, not `skipped`.
