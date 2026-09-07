# HTML Courseware conventions

- Treat `Courseware Content Contract 1.1` as the source format; accept 1.0 only through the explicit migration path.
- Keep the Agent/Python boundary: content and scripts are authored separately.
- Use the built-in deterministic renderer; do not add arbitrary HTML or JavaScript to content.
- Publish only after contract QA, offline/output QA, and real browser click/wheel smoke pass.
- Keep `student.html` free of teacher notes, source wording, production metadata, and timing text.
