# HTML Courseware adapter

Use `Courseware Content Contract 1.0` as the only renderer input. Read `简介.md`, `通用提示词.md`, and `SKILL.md`; let the Agent author course content and natural Chinese speaker scripts, then run `scripts/render_courseware.py` and `scripts/validate_courseware.py`. Deliver both offline single-file HTML outputs. Do not put arbitrary JavaScript in content, leak teacher/timing/source information into the student pages, or skip real browser click/wheel verification.
