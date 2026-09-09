# HTML Courseware conventions

- Treat `Courseware Content Contract 1.1` as the source format; accept 1.0 only through the explicit migration path.
- Require a public Teaching Blueprint before the draft contract; keep the Agent/Python boundary: content and scripts are authored separately.
- Run structural QA, pedagogical review, at most two derived-field repair rounds, revalidation, rendering, and browser QA in that order.
- Let facts, learning units, audience, and timing choose page/interaction shape; never reward fixed counts.
- Use the built-in deterministic renderer; do not add arbitrary HTML or JavaScript to content.
- Publish only after contract QA, offline/output QA, and real browser click/wheel smoke pass.
- Keep `student.html` free of teacher notes, source wording, production metadata, and timing text.
- New generation uses `strict` Source Truth and time-evidence gates. `migration-trust` is only for legacy regression fixtures.
- A factual canonical fact needs traceable `source_refs`/`evidence` and a verification status; core facts may be level 1–3, never an unverified fact or a level-4 pedagogical inference.
- CSV evidence must derive field column and worksheet row from the shared semantic model; never encode a course-specific cell answer.
- Every positive `activity_minutes` value carries an executable `activity_plan`; prepared time is core path plus actual extension reserve content, not unexplained numeric padding.
