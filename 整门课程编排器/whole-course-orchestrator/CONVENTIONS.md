# Whole-Course conventions

- JSON 是课程级中间合同；单次课 HTML 仍由下游 Skill 负责。
- 所有 ID 在同一输出中稳定且可追溯到 source/session/question/task。
- User source and external source inventories are never merged without `origin_type`.
- `safe_filename()` is the only route from display names to filesystem names.
- Structural validation is deterministic; pedagogical suitability remains a human review boundary.
