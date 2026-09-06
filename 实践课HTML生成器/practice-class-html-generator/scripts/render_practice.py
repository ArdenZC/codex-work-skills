"""Render Practice Class Content Contract 1.0 into offline classroom pages."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from practice_contract import LEVEL_LABELS, load_courseware, load_json, require_valid
from validate_practice import validate_output_files


STUDENT_HTML = ("student-task.html", "learning-center.html", "study-guide.html", "foundation-kit.html")
TEACHER_HTML = ("teacher-guide.html", "teacher-reference.html")
OUTPUT_HTML = STUDENT_HTML + TEACHER_HTML


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def text_block(value: Any) -> str:
    return esc(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", value).strip("-")
    return cleaned or "item"


def nav(active: str, role: str) -> str:
    if role == "student":
        links = (
            ("student-task.html", "学生任务", "student"),
            ("learning-center.html", "学习中心", "center"),
            ("study-guide.html", "学习指南", "guide"),
            ("foundation-kit.html", "基础工具包", "kit"),
        )
    else:
        links = (
            ("teacher-guide.html", "教师指南", "teacher"),
            ("teacher-reference.html", "教师参考", "reference"),
            ("../student/student-task.html", "学生任务", "student"),
            ("../student/learning-center.html", "学习中心", "center"),
        )
    items = "".join(
        f'<a class="nav-link {"active" if key == active else ""}" href="{href}">{label}</a>'
        for href, label, key in links
    )
    return f'<nav class="nav" aria-label="实践课页面导航">{items}</nav>'


CONTEXT_LABELS = {
    "course_name": "课程",
    "audience": "对象",
    "language": "语言",
    "tools": "工具",
    "platform": "平台",
    "software": "软件",
    "database_dialect": "数据库方言",
    "framework": "框架",
    "other_constraints": "约束",
}


def context_chips(content: dict[str, Any]) -> str:
    context = content.get("course_context") or {}
    chips: list[str] = []
    for field in CONTEXT_LABELS:
        value = context.get(field)
        if isinstance(value, list):
            value = "、".join(str(item) for item in value)
        if value:
            chips.append(f'<span class="chip">{esc(CONTEXT_LABELS[field])}：{esc(value)}</span>')
    return "".join(chips)


def shell(content: dict[str, Any], active: str, title: str, body: str, *, role: str) -> str:
    source = content["source_courseware"]
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)} · {esc(content["practice_title"])}</title>
  <style>
    :root {{ --ink:#25384a; --muted:#657789; --paper:#fbfaf7; --sky:#dcecef; --sage:#e6efe9; --peach:#f8eade; --line:#d6e0e1; --accent:#557f8b; --focus:#b46e4e; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; line-height:1.7; }}
    a {{ color:#2f6676; }}
    .page {{ max-width:1100px; margin:0 auto; padding:24px 22px 56px; }}
    .masthead {{ display:flex; gap:20px; justify-content:space-between; align-items:flex-start; padding:20px 0 10px; }}
    .eyebrow {{ color:var(--accent); font-size:.82rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    h1,h2,h3 {{ line-height:1.25; margin:0 0 12px; }} h1 {{ font-size:clamp(1.75rem,4vw,2.8rem); }} h2 {{ font-size:1.45rem; }} h3 {{ font-size:1.08rem; }}
    p {{ margin:8px 0 14px; }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 24px; padding:10px; background:#f0f4f1; border:1px solid var(--line); border-radius:14px; }}
    .nav-link {{ padding:7px 12px; border-radius:10px; text-decoration:none; color:var(--ink); }} .nav-link:hover,.nav-link.active {{ background:var(--sky); color:#214e5a; }}
    .hero {{ background:linear-gradient(135deg,var(--sky),#f3f6ef 64%,var(--peach)); padding:24px; border:1px solid var(--line); border-radius:22px; }}
    .hero p {{ max-width:800px; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:16px; }} .chip {{ display:inline-flex; padding:4px 10px; border-radius:999px; background:#ffffffaa; border:1px solid #c7d9da; color:#3f5b68; font-size:.9rem; }}
    .section {{ margin-top:28px; }} .section-head {{ display:flex; gap:12px; align-items:baseline; justify-content:space-between; margin-bottom:12px; }}
    .card-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:14px; }}
    .card {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:18px; box-shadow:0 4px 16px #384d5a0d; }}
    .card.soft {{ background:var(--sage); }} .card.warm {{ background:var(--peach); }} .card.blue {{ background:var(--sky); }}
    .label {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:.78rem; font-weight:700; background:#eef2f2; color:#526b75; }} .label.core {{ background:#dcecef; color:#285b68; }} .label.optional {{ background:#e6efe9; color:#3a6553; }} .label.challenge {{ background:#f8eade; color:#87523a; }}
    .task-card {{ margin:14px 0; }} .task-top {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px; }}
    .task-meta {{ color:var(--muted); font-size:.9rem; }}
    ol,ul {{ margin:7px 0 12px; padding-left:1.35rem; }} li {{ margin:4px 0; }}
    .scaffold {{ padding:12px 14px; margin:12px 0; border-radius:12px; background:#f3f6f4; border:1px dashed #b8cac6; }}
    .acceptance {{ display:grid; gap:6px; }} .check {{ display:flex; gap:8px; align-items:flex-start; }}
    pre {{ overflow:auto; padding:14px; border-radius:12px; background:#263b48; color:#f4f6f1; font:.88rem/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }} code {{ font-family:inherit; }}
    .source-ref {{ display:inline-block; margin:3px 4px 3px 0; padding:3px 8px; border-radius:8px; background:#eef5f4; color:#426b76; font-size:.84rem; text-decoration:none; }}
    .source-ref:hover {{ background:#dcecef; }} .callout {{ padding:14px 16px; border-radius:14px; background:#fff9ed; border:1px solid #ead9ae; }}
    .interaction {{ margin-top:12px; padding:14px; background:#f7f8f6; border-radius:13px; border:1px solid var(--line); }}
    .interaction button,.interaction select,.interaction input {{ border:1px solid #adc3c6; background:#fff; color:var(--ink); border-radius:9px; padding:8px 11px; margin:5px 5px 5px 0; cursor:pointer; font:inherit; }} .interaction button:hover,.interaction button:focus,.interaction select:focus,.interaction input:focus {{ background:var(--sky); outline:2px solid #9dbdc1; outline-offset:1px; }}
    .feedback {{ min-height:1.7em; color:#3e6759; font-weight:600; }} .feedback.wrong {{ color:#8a5b45; }} .step {{ display:none; padding:12px; background:#fff; border-radius:10px; }} .step.show {{ display:block; }}
    .classify-item,.reorder-item,.simulator-row,.multi-question {{ padding:7px 0; }} .classify-item label,.reorder-item label {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }} .sim-array {{ padding:8px 10px; background:#fff; border-radius:9px; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }}
    .reference-answer {{ white-space:pre-wrap; }}
    .footer {{ margin-top:42px; padding-top:16px; border-top:1px solid var(--line); color:var(--muted); font-size:.9rem; }}
    @media (max-width:700px) {{ .page {{ padding:16px 14px 42px; }} .masthead {{ display:block; }} .nav {{ gap:4px; }} .nav-link {{ padding:6px 8px; font-size:.9rem; }} }}
  </style>
</head>
<body>
  <main class="page">
    <header class="masthead">
      <div><div class="eyebrow">Practice Class · Contract {esc(content["contract_version"])}</div><h1>{esc(content["practice_title"])}</h1></div>
      <div class="chip">{esc(source["chapter_title"])}</div>
    </header>
    {nav(active, role)}
    {body}
    <footer class="footer">{esc(content["course_title"])} · 面向 {esc(content["audience"])} · 本页为离线单文件课件</footer>
  </main>
  <script>
  (() => {{
     document.querySelectorAll('[data-choice]').forEach((button) => button.addEventListener('click', () => {{
       const box = button.closest('[data-question], [data-interaction]');
       const feedback = box && box.querySelector('.feedback');
       if (feedback) {{ feedback.textContent = button.dataset.feedback || ''; feedback.classList.toggle('wrong', button.dataset.correct !== 'true'); }}
       if (box) box.querySelectorAll('[data-choice]').forEach((item) => item.setAttribute('aria-pressed', item === button ? 'true' : 'false'));
       const root = button.closest('[data-multi-root]');
       if (root) {{
         const questions = [...root.querySelectorAll('[data-question]')];
         const answered = questions.filter((item) => item.querySelector('[data-choice][aria-pressed="true"]')).length;
         const correct = questions.filter((item) => item.querySelector('[data-choice][aria-pressed="true"]')?.dataset.correct === 'true').length;
         const score = root.querySelector('[data-multi-score]');
         if (score) score.textContent = `已完成 ${{answered}} / ${{questions.length}} 题；当前正确 ${{correct}} 题`;
       }}
     }}));
    document.querySelectorAll('[data-stepper]').forEach((box) => {{
      const steps = [...box.querySelectorAll('.step')]; let current = 0;
      const show = (index) => {{ current = Math.max(0, Math.min(index, steps.length - 1)); steps.forEach((step, i) => step.classList.toggle('show', i === current)); const status = box.querySelector('.step-status'); if (status) status.textContent = `第 ${{current + 1}} / ${{steps.length}} 步`; }};
      box.querySelector('[data-prev]').addEventListener('click', () => show(current - 1)); box.querySelector('[data-next]').addEventListener('click', () => show(current + 1)); show(0);
    }});
    document.querySelectorAll('[data-classify]').forEach((box) => {{
      box.querySelector('[data-check]').addEventListener('click', () => {{
        let correct = true; box.querySelectorAll('[data-classify-item]').forEach((item) => {{ const select = item.querySelector('select'); const ok = select.value === item.dataset.answer; correct = correct && ok; }});
        const feedback = box.querySelector('.feedback'); feedback.textContent = correct ? '分类全部正确：请再说出每一类为什么服务当前任务。' : '还有分类需要调整：先看它是否保存业务状态、呈现界面，还是负责一次动作。'; feedback.classList.toggle('wrong', !correct);
      }});
    }});
    document.querySelectorAll('[data-reorder]').forEach((box) => {{
      box.querySelector('[data-check]').addEventListener('click', () => {{ const expected = JSON.parse(box.dataset.correctOrder); const actual = [...box.querySelectorAll('select')].map((item) => item.value); const ok = expected.every((item, i) => item === actual[i]); const feedback = box.querySelector('.feedback'); feedback.textContent = ok ? '顺序成立：请解释每一步如何把结果交回业务目标。' : '顺序还需要调整：先找请求，再找掌握规则的对象，最后写出可观察结果。'; feedback.classList.toggle('wrong', !ok); }});
    }});
    document.querySelectorAll('[data-simulator]').forEach((box) => {{
      const rounds = JSON.parse(box.dataset.rounds); let current = 0;
      const feedback = box.querySelector('.feedback'); const status = box.querySelector('.sim-status'); const next = box.querySelector('[data-next-round]');
      const fill = (round) => {{ box.querySelector('[data-sim-left]').value = round.left; box.querySelector('[data-sim-right]').value = round.right; box.querySelector('[data-sim-mid]').value = ''; box.querySelector('[data-sim-next-left]').value = ''; box.querySelector('[data-sim-next-right]').value = ''; }};
      box.querySelector('[data-check]').addEventListener('click', () => {{ const round = rounds[current]; const actual = ['left','right','mid','next-left','next-right'].map((name) => Number(box.querySelector(`[data-sim-${{name}}]`).value)); const ok = actual[0] === round.left && actual[1] === round.right && actual[2] === round.mid && actual[3] === round.next_left && actual[4] === round.next_right; feedback.textContent = ok ? round.feedback : '请同时核对当前闭区间、mid，以及比较后得到的下一轮 left/right。'; feedback.classList.toggle('wrong', !ok); if (ok && current < rounds.length - 1) {{ next.disabled = false; }} else if (ok) {{ next.disabled = true; status.textContent = '全部轮次完成'; }} }});
      next.addEventListener('click', () => {{ const round = rounds[current]; current += 1; fill(rounds[current]); next.disabled = true; status.textContent = `第 ${{current + 1}} / ${{rounds.length}} 轮；上一轮新区间为 [${{round.next_left}}, ${{round.next_right}}]`; feedback.textContent = '请输入这一轮的 mid 和下一轮区间，再检查边界排除理由。'; feedback.classList.remove('wrong'); }}); fill(rounds[0]); status.textContent = `第 1 / ${{rounds.length}} 轮`;
    }});
  }})();
  </script>
</body>
</html>
'''


def source_links(knowledge: list[dict[str, Any]], *, target: str = "") -> str:
    links: list[str] = []
    for item in knowledge:
        refs = "、".join(esc(ref) for ref in item.get("source_slide_ids", [])) or "独立设计"
        href = f"{target}#knowledge-{slug(item['id'])}" if target else f"#knowledge-{slug(item['id'])}"
        links.append(f'<a class="source-ref" href="{href}">{esc(item["title"])} · 理论页 {refs}</a>')
    return "".join(links)


def render_task(
    task: dict[str, Any],
    assets_by_id: dict[str, dict[str, Any]],
    knowledge_by_id: dict[str, dict[str, Any]],
    guide_ids: set[str],
    kit_ids: set[str],
) -> str:
    level = task["level"]
    refs = "、".join(esc(ref) for ref in task.get("knowledge_link_ids", []))
    source_refs = task.get("source_slide_ids", [])
    source_label = "、".join(esc(ref) for ref in source_refs) or "独立资料"
    steps = "".join(
        f"<li><strong>{esc(step['title'])}</strong>：{text_block(step['instruction'])}"
        + (f"<br><span class=\"task-meta\">自检：{text_block(step['check'])}</span>" if step.get("check") else "")
        + "</li>"
        for step in task["steps"]
    )
    acceptance = "".join(f'<div class="check"><span aria-hidden="true">□</span><span>{text_block(item)}</span></div>' for item in task["acceptance"])
    help_parts: list[str] = []
    for ref in task.get("help_refs", []):
        if ref in guide_ids:
            help_parts.append(f'<a class="source-ref" href="study-guide.html#guide-{slug(ref)}">{esc(ref)}</a>')
        elif ref in kit_ids:
            help_parts.append(f'<a class="source-ref" href="foundation-kit.html#kit-{slug(ref)}">{esc(ref)}</a>')
        else:
            help_parts.append(f'<span class="source-ref">{esc(ref)}</span>')
    starter = ""
    for asset_id in task.get("starter_asset_ids", []):
        asset = assets_by_id.get(asset_id)
        if not asset:
            continue
        starter += f'<details><summary>打开 starter：{esc(asset["path"])}</summary><pre><code>{esc(asset["content"])}</code></pre><p class="task-meta">也可下载：<a href="starter/{esc(asset["path"])}">{esc(asset["path"])}</a></p></details>'
    return f'''
    <article class="card task-card" id="task-{slug(task["id"])}" data-task-id="{esc(task["id"])}">
      <div class="task-top"><span class="label {esc(level)}">{esc(LEVEL_LABELS.get(level, level))}</span><span class="chip">{esc(task["modality"])}</span><span class="task-meta">约 {esc(task["estimated_minutes"])} 分钟</span></div>
      <h3>{esc(task["title"])}</h3>
      <p>{text_block(task["overview"])}</p>
      <p class="task-meta">理论锚点：{refs} · 理论页：<span class="task-source-refs">{source_label}</span></p>
      <div class="scaffold"><strong>脚手架：</strong>{text_block(task["scaffold"])}</div>
      <h4>完成步骤</h4><ol>{steps}</ol>
      <h4>验收清单</h4><div class="acceptance">{acceptance}</div>
      {starter}
      <div class="task-meta">需要帮助时：{"".join(help_parts) or "先回到学习中心复做对应互动"}</div>
    </article>'''


def render_student(content: dict[str, Any]) -> str:
    knowledge = content["knowledge_links"]
    assets = {item["id"]: item for item in content["starter_assets"]}
    knowledge_by_id = {item["id"]: item for item in knowledge}
    guide_ids = {item["id"] for item in content["study_guide"]}
    kit_ids = {item["id"] for item in content["foundation_kit"]}
    grouped = {level: [task for task in content["tasks"] if task["level"] == level] for level in ("core", "optional", "challenge")}
    sections = ""
    headings = {"core": "核心必做：先完成可验证的最小成果", "optional": "有余力：扩大练习面", "challenge": "提高挑战：解释与迁移"}
    for level in ("core", "optional", "challenge"):
        sections += f'<section class="section" id="{level}-tasks"><div class="section-head"><h2>{headings[level]}</h2><span class="task-meta">{len(grouped[level])} 项</span></div>{"".join(render_task(task, assets, knowledge_by_id, guide_ids, kit_ids) for task in grouped[level])}</section>'
    theory = "".join(
        f'<article class="card blue" id="knowledge-{slug(item["id"])}"><h3>{esc(item["title"])}</h3><p>{text_block(item["summary"])}</p><p><strong>做完后你能：</strong>{text_block(item["student_can_do"])}</p><div>{source_links([item])}</div></article>'
        for item in knowledge
    )
    body = f'''
    <section class="hero"><div class="eyebrow">先做出一个可检查的成果</div><h2>{esc(content["course_title"])} · 实践任务</h2><p>本页把理论页的概念转成一步一步的操作、建模或实现。先完成核心必做，再按时间选择有余力或提高挑战；每项任务都保留理论锚点和可观察的验收条件。</p><div class="meta"><span class="chip">课堂时长 {esc(content["duration_minutes"])} 分钟</span><span class="chip">核心任务 {len(grouped["core"])} 项</span><span class="chip">理论页 {len(content["source_courseware"]["taught_slide_ids"])} 页</span>{context_chips(content)}</div></section>
    <section class="section"><div class="section-head"><h2>从理论页进入实践</h2><a href="learning-center.html">去学习中心做互动 →</a></div><div class="card-grid">{theory}</div></section>
    {sections}'''
    return shell(content, "student", "学生任务", body, role="student")


def _option_buttons(interaction: dict[str, Any]) -> str:
    return "".join(
        f'<button type="button" data-choice data-correct="{"true" if option.get("correct", index == interaction.get("answer_index")) else "false"}" data-feedback="{esc(option["feedback"])}" aria-pressed="false">{esc(option["label"])}</button>'
        for index, option in enumerate(interaction["options"])
    )


def render_interaction(center: dict[str, Any]) -> str:
    interaction = center["interaction"]
    kind = interaction["type"]
    interaction_id = esc(center["id"])
    if kind in {"choice", "match", "diagnose", "predict-next", "build-relation", "compare-strategies", "scenario-decision"}:
        return f'<div class="interaction" data-interaction="{interaction_id}" data-interaction-type="{esc(kind)}"><strong>{esc(interaction["prompt"])}</strong><div>{_option_buttons(interaction)}</div><div class="feedback" aria-live="polite">选择后看反馈，并把理由说完整。</div></div>'
    if kind in {"stepper", "trace"}:
        steps = "".join(f'<div class="step"><strong>{esc(step["title"])}</strong><p>{text_block(step["text"])}</p></div>' for step in interaction["steps"])
        return f'<div class="interaction" data-stepper="{interaction_id}" data-interaction-type="{esc(kind)}"><strong>{esc(interaction["prompt"])}</strong>{steps}<div><button type="button" data-prev>上一步</button><button type="button" data-next>下一步</button><span class="task-meta step-status" aria-live="polite"></span></div></div>'
    if kind == "classify":
        categories = "".join(f'<option value="{esc(category)}">{esc(category)}</option>' for category in interaction["categories"])
        items = "".join(f'<div class="classify-item" data-classify-item data-answer="{esc(item["answer"])}"><label>{esc(item["label"])}<select aria-label="为 {esc(item["label"])} 选择分类"><option value="">请选择</option>{categories}</select></label><small class="task-meta">{esc(item["feedback"])}</small></div>' for item in interaction["items"])
        return f'<div class="interaction" data-classify="{interaction_id}" data-interaction-type="classify"><strong>{esc(interaction["prompt"])}</strong>{items}<button type="button" data-check>检查分类</button><div class="feedback" aria-live="polite">逐项分类，再说明判断依据。</div></div>'
    if kind == "reorder":
        options = "".join(f'<option value="{esc(item["id"])}">{esc(item["label"])}</option>' for item in interaction["items"])
        rows = "".join(f'<div class="reorder-item"><label>第 {index + 1} 步<select aria-label="第 {index + 1} 步">{options}</select></label></div>' for index in range(len(interaction["items"])))
        order = esc(json.dumps(interaction["correct_order"], ensure_ascii=False))
        return f'<div class="interaction" data-reorder="{interaction_id}" data-correct-order="{order}" data-interaction-type="reorder"><strong>{esc(interaction["prompt"])}</strong>{rows}<button type="button" data-check>检查顺序</button><div class="feedback" aria-live="polite">先排出消息链，再说明每个接收者掌握的规则。</div></div>'
    if kind == "state-simulator":
        state = interaction["state"]
        values = "、".join(esc(value) for value in state["values"])
        rounds = esc(json.dumps(interaction["rounds"], ensure_ascii=False))
        return f'<div class="interaction" data-simulator="{interaction_id}" data-rounds="{rounds}" data-interaction-type="state-simulator"><strong>{esc(interaction["prompt"])}</strong><p class="sim-array">数组：[{values}]；目标：{esc(state["target"])}</p><div class="simulator-row">当前闭区间：<label>left <input data-sim-left type="number"></label><label>right <input data-sim-right type="number"></label><label>mid <input data-sim-mid type="number"></label></div><div class="simulator-row">下一轮闭区间：<label>next left <input data-sim-next-left type="number"></label><label>next right <input data-sim-next-right type="number"></label></div><button type="button" data-check>检查本轮</button><button type="button" data-next-round disabled>进入下一轮</button><span class="task-meta sim-status" aria-live="polite"></span><div class="feedback" aria-live="polite">先填写当前轮和下一轮的五个下标，再检查边界是否仍是闭区间。</div></div>'
    if kind == "multi-question":
        question_parts: list[str] = []
        for index, question in enumerate(interaction["questions"]):
            option_parts = []
            for option_index, option in enumerate(question["options"]):
                correct = "true" if option.get("correct", option_index == question.get("answer_index")) else "false"
                option_parts.append(f'<button type="button" data-choice data-correct="{correct}" data-feedback="{esc(option["feedback"])}" aria-pressed="false">{esc(option["label"])}</button>')
            question_parts.append(f'<div class="multi-question" data-question><p><strong>{index + 1}. {esc(question["prompt"])}</strong></p><div>{"".join(option_parts)}</div><div class="feedback" aria-live="polite">请选择并读反馈。</div></div>')
        questions = "".join(question_parts)
        return f'<div class="interaction" data-interaction="{interaction_id}" data-multi-root data-interaction-type="multi-question"><strong>{esc(interaction["prompt"])}</strong>{questions}<div class="feedback" data-multi-score aria-live="polite">已完成 0 / {len(interaction["questions"])} 题；当前正确 0 题</div></div>'
    return f'<div class="interaction" data-interaction="{interaction_id}"><strong>{esc(interaction["prompt"])}</strong><div class="feedback">此互动暂未配置。</div></div>'


def render_center(content: dict[str, Any], center: dict[str, Any]) -> str:
    knowledge = {item["id"]: item for item in content["knowledge_links"]}
    refs = [knowledge[item] for item in center["knowledge_link_ids"] if item in knowledge]
    source = "、".join(ref for item in refs for ref in item.get("source_slide_ids", [])) or "独立练习"
    tasks = "、".join(center["task_ids"])
    return f'<article class="card" id="center-{slug(center["id"])}"><div class="task-top"><span class="label">知识点互动 · {esc(center["interaction"]["type"])}</span><span class="task-meta">理论页 {esc(source)}</span></div><h3>{esc(center["title"])}</h3><p>{text_block(center["purpose"])}</p><p class="task-meta">服务任务：{esc(tasks)}</p>{render_interaction(center)}</article>'


def render_learning_center(content: dict[str, Any]) -> str:
    centers = "".join(render_center(content, center) for center in content["learning_center"])
    body = f'<section class="hero"><div class="eyebrow">互动只为帮助你完成任务</div><h2>学习中心</h2><p>每个互动都对应一个知识点和至少一个实践任务。操作后必须读反馈、说明理由，再回到学生任务页面执行；互动不是装饰动画。</p><div class="meta">{context_chips(content)}</div></section><section class="section"><div class="card-grid">{centers}</div></section>'
    return shell(content, "center", "学习中心", body, role="student")


def render_study_guide(content: dict[str, Any]) -> str:
    guides = "".join(
        f'<article class="card" id="guide-{slug(guide["id"])}"><h3>{esc(guide["title"])}</h3>'
        f'<p class="task-meta">知识点：{esc("、".join(guide["knowledge_link_ids"]))} · 对应任务：{"、".join(f"<a href=\"student-task.html#task-{slug(task_id)}\">{esc(task_id)}</a>" for task_id in guide["task_ids"])}</p>'
        f'<p>{text_block(guide["body"])}</p><div class="callout"><strong>同一案例/公式/操作：</strong>{text_block(guide["worked_example"])}</div>'
        f'<h4>快速查表</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in guide["quick_reference"])}</ul>'
        f'<h4>常见卡点</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in guide["common_errors"])}</ul>'
        f'<h4>检查自己</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in guide["checkpoints"])}</ul></article>'
        for guide in content["study_guide"]
    )
    body = f'<section class="hero"><div class="eyebrow">卡住时回到可观察的判断</div><h2>学习指南</h2><p>这里不是答案库，而是一组帮助你继续完成任务的复盘卡片。先指出自己卡在概念、步骤还是验收，再打开对应条目。</p></section><section class="section"><div class="card-grid">{guides}</div></section>'
    return shell(content, "guide", "学习指南", body, role="student")


def render_foundation_kit(content: dict[str, Any]) -> str:
    kits = "".join(
        f'<article class="card soft" id="kit-{slug(kit["id"])}"><div class="label">{esc(kit["kind"])}</div><h3>{esc(kit["title"])}</h3>'
        f'<p class="task-meta">服务任务：{"、".join(f"<a href=\"student-task.html#task-{slug(task_id)}\">{esc(task_id)}</a>" for task_id in kit["task_ids"])}</p>'
        f'<p>{text_block(kit["content"])}</p><div class="callout"><strong>什么时候打开：</strong>{text_block(kit["when_to_use"])}</div>'
        f'<ol>{"".join(f"<li>{text_block(item)}</li>" for item in kit["steps"])}</ol>'
        f'<h4>自检</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in kit["self_check"])}</ul></article>'
        for kit in content["foundation_kit"]
    )
    body = f'<section class="hero"><div class="eyebrow">按课程动态生成的起步工具</div><h2>基础工具包</h2><p>工具包只包含完成本次实践所需的最小支撑：术语、操作顺序、检查表或 starter 入口。课程上下文来自上游理论课合同。</p><div class="meta">{context_chips(content)}</div></section><section class="section"><div class="card-grid">{kits}</div></section>'
    return shell(content, "kit", "基础工具包", body, role="student")


def task_source_text(task: dict[str, Any], knowledge_by_id: dict[str, dict[str, Any]]) -> str:
    return "、".join(task.get("source_slide_ids", [])) or "独立设计"


def render_teacher_guide(content: dict[str, Any]) -> str:
    teacher = content["teacher_guide"]
    knowledge_by_id = {item["id"]: item for item in content["knowledge_links"]}
    task_by_id = {item["id"]: item for item in content["tasks"]}
    timing = "".join(f'<li><strong>{esc(item["minutes"])} 分钟</strong>：{text_block(item["focus"])}</li>' for item in teacher["timing"])
    guidance = "".join(
        f'<article class="card"><div class="task-top"><span class="label {esc(task_by_id[item["task_id"]]["level"])}">{esc(LEVEL_LABELS.get(task_by_id[item["task_id"]]["level"], task_by_id[item["task_id"]]["level"]))}</span><span class="task-meta">理论页 {esc(task_source_text(task_by_id[item["task_id"]], knowledge_by_id))}</span></div><h3>{esc(item["task_id"])} · {esc(task_by_id[item["task_id"]]["title"])}</h3><p><strong>巡回观察：</strong>{text_block(item["look_for"])}</p><p><strong>卡住时追问：</strong>{text_block(item["ask_when_stuck"])}</p></article>'
        for item in teacher["task_guidance"]
    )
    errors = "".join(f'<li><strong>{text_block(item["symptom"])}</strong>：{text_block(item["intervention"])}</li>' for item in teacher["common_errors"])
    pace_adjustments = "".join(f'<div class="card soft"><p>{text_block(item)}</p></div>' for item in teacher["pace_adjustments"])
    closing_checks = "".join(f"<li>{text_block(item)}</li>" for item in teacher["closing_checks"])
    body = f'''
    <section class="hero"><div class="eyebrow">课堂控制台</div><h2>教师指南</h2><p>{text_block(teacher["purpose"])}</p><div class="callout"><strong>理论—实践桥：</strong>{text_block(teacher["theory_bridge"])}</div><div class="meta"><a class="source-ref" href="../student/student-task.html">打开学生任务</a><a class="source-ref" href="teacher-reference.html">打开教师参考</a>{context_chips(content)}</div></section>
    <section class="section"><h2>建议节奏（90 分钟）</h2><div class="card"><ol>{timing}</ol></div></section>
    <section class="section"><h2>任务观察点与理论链接</h2><div class="card-grid">{guidance}</div></section>
    <section class="section"><h2>常见错误与干预</h2><div class="card warm"><ul>{errors}</ul></div></section>
    <section class="section"><h2>弱基础与快进度学生</h2><div class="card-grid">{pace_adjustments}</div></section>
    <section class="section"><h2>完成标准与随机出口抽查</h2><div class="card blue"><p>完成标准：学生现场完成核心必做任务的可观察成果，能够指出理论页、解释关键判断，并用验收条件复核结果；不把统一提交物作为默认门槛。</p><ul>{closing_checks}</ul></div></section>'''
    return shell(content, "teacher", "教师指南", body, role="teacher")


def render_teacher_reference(content: dict[str, Any]) -> str:
    references = []
    task_by_id = {item["id"]: item for item in content["tasks"]}
    for reference in content["teacher_reference"]["task_references"]:
        task = task_by_id[reference["task_id"]]
        result = f'<p><strong>参考结果：</strong>{text_block(reference["reference_result"])}</p>' if reference.get("reference_result") else ""
        references.append(f'''
        <article class="card" id="reference-{slug(reference["task_id"])}">
          <div class="task-top"><span class="label {esc(task["level"])}">{esc(LEVEL_LABELS.get(task["level"], task["level"]))}</span><span class="task-meta">理论页 {esc("、".join(reference["source_slide_ids"]))}</span></div>
          <h3>{esc(reference["task_id"])} · {esc(reference["title"])}</h3>
          <p><a class="source-ref" href="../student/student-task.html#task-{slug(reference["task_id"])}">回到学生任务</a></p>
          <h4>参考答案 / 结果</h4><pre class="reference-answer"><code>{esc(reference["reference_answer"])}</code></pre>{result}
          <h4>关键步骤</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["key_steps"])}</ul>
          <h4>可接受变体</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["acceptable_variants"])}</ul>
          <h4>明显错误</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["common_errors"])}</ul>
          <h4>验收依据</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["acceptance_basis"])}</ul>
        </article>''')
    body = f'<section class="hero"><div class="eyebrow">教师专用逐任务参考层</div><h2>教师参考</h2><p>本页包含参考答案、结果形态、可接受变体和明显错误，供教师巡视、抽查和评分使用。它与学生目录物理隔离。</p><div class="meta"><a class="source-ref" href="../student/student-task.html">学生任务</a><a class="source-ref" href="teacher-guide.html">教师指南</a>{context_chips(content)}</div></section><section class="section"><div class="card-grid">{"".join(references)}</div></section>'
    return shell(content, "reference", "教师参考", body, role="teacher")


def _safe_asset_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative.strip():
        raise ValueError(f"starter asset path must be relative and stay within student/starter/: {relative}")
    return path


def generate(practice_path: Path, output_dir: Path, courseware_path: Path | None = None, *, replace: bool = False) -> dict[str, Any]:
    content = load_json(practice_path)
    courseware = load_courseware(courseware_path) if courseware_path else None
    contract_report = require_valid(content, courseware)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not replace:
        raise FileExistsError(f"output directory is not empty; use --replace: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if replace:
        for stale in (*OUTPUT_HTML, "starter"):
            target = output_dir / stale
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        for stale in ("student", "teacher"):
            target = output_dir / stale
            if target.exists() and not target.is_dir():
                target.unlink()
    student_dir = output_dir / "student"
    teacher_dir = output_dir / "teacher"
    student_dir.mkdir(exist_ok=True)
    teacher_dir.mkdir(exist_ok=True)
    starter_dir = student_dir / "starter"
    if replace and starter_dir.is_dir():
        shutil.rmtree(starter_dir)
    if content["starter_assets"]:
        starter_dir.mkdir(exist_ok=True)
    (output_dir / "practice-content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for asset in content["starter_assets"]:
        destination = starter_dir / _safe_asset_path(asset["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(asset["content"], encoding="utf-8", newline="\n")
    student_pages = {
        "student-task.html": render_student(content),
        "learning-center.html": render_learning_center(content),
        "study-guide.html": render_study_guide(content),
        "foundation-kit.html": render_foundation_kit(content),
    }
    teacher_pages = {
        "teacher-guide.html": render_teacher_guide(content),
        "teacher-reference.html": render_teacher_reference(content),
    }
    for name, page in student_pages.items():
        (student_dir / name).write_text(page, encoding="utf-8", newline="\n")
    for name, page in teacher_pages.items():
        (teacher_dir / name).write_text(page, encoding="utf-8", newline="\n")
    (output_dir / "qa-report.json").write_text("{}\n", encoding="utf-8", newline="\n")
    output_report = validate_output_files(content, output_dir)
    report = {"status": "pass" if output_report["status"] == "pass" else "fail", "contract": contract_report, "outputs": output_report}
    (output_dir / "qa-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if report["status"] != "pass":
        raise ValueError("rendered practice output failed QA: " + "; ".join(output_report["errors"]))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--practice-json", required=True, type=Path)
    parser.add_argument("--courseware-json", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    result = generate(args.practice_json, args.output_dir, args.courseware_json, replace=args.replace)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.as_json else f"generated={args.output_dir.resolve()} status={result['status']}")


if __name__ == "__main__":
    main()
