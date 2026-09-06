"""Render Practice Class Content Contract 1.0 into an offline teaching package.

The renderer keeps the contract semantic and course-neutral. It emits stable
entry pages plus focused detail pages so that a rich practice package remains
usable on a classroom screen and from ``file://``.
"""

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


STUDENT_INDEXES = ("student-task.html", "learning-center.html", "study-guide.html", "foundation-kit.html")
TEACHER_INDEXES = ("teacher-guide.html", "teacher-reference.html")


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def text_block(value: Any) -> str:
    return esc(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", value).strip("-")
    return cleaned or "item"


def interaction_family(kind: str) -> str:
    """Map semantic interaction types to the actual UI family rendered below."""

    if kind in {"choice", "match", "diagnose", "predict-next", "build-relation", "compare-strategies", "scenario-decision"}:
        return "choice-family"
    if kind in {"stepper", "trace"}:
        return "step-family"
    if kind == "classify":
        return "classify-family"
    if kind == "reorder":
        return "reorder-family"
    if kind == "state-simulator":
        return "state-simulator-family"
    if kind == "multi-question":
        return "multi-question-family"
    return "neutral-family"


def _nav_links(active: str, role: str, prefix: str) -> str:
    if role == "student":
        links = (
            (f"{prefix}student-task.html", "实践路线", "student"),
            (f"{prefix}learning-center.html", "学习中心", "center"),
            (f"{prefix}study-guide.html", "学习指南", "guide"),
            (f"{prefix}foundation-kit.html", "基础补给", "kit"),
        )
    else:
        links = (
            (f"{prefix}teacher-guide.html", "教师指南", "teacher"),
            (f"{prefix}teacher-reference.html", "教师参考目录", "reference"),
            (f"{prefix}../student/student-task.html", "学生路线", "student"),
        )
    return "".join(
        f'<a class="nav-link {"active" if key == active else ""}" href="{href}">{label}</a>'
        for href, label, key in links
    )


def student_tools(content: dict[str, Any]) -> str:
    context = content.get("course_context") or {}
    tools = context.get("tools") or []
    if not tools and context.get("software"):
        tools = [context["software"]]
    if not tools:
        return ""
    return f'<span class="chip">本次工具：{esc("、".join(str(item) for item in tools))}</span>'


def teacher_context(content: dict[str, Any]) -> str:
    context = content.get("course_context") or {}
    labels = {
        "course_name": "课程",
        "audience": "对象",
        "language": "语言/记法",
        "tools": "工具",
        "platform": "平台",
        "software": "软件",
        "database_dialect": "数据库方言",
        "framework": "框架",
        "other_constraints": "课堂约束",
    }
    chips: list[str] = []
    for field, label in labels.items():
        value = context.get(field)
        if isinstance(value, list):
            value = "、".join(str(item) for item in value)
        if value:
            chips.append(f'<span class="chip">{esc(label)}：{esc(value)}</span>')
    return "".join(chips)


def shell(
    content: dict[str, Any],
    active: str,
    title: str,
    body: str,
    *,
    role: str,
    prefix: str = "",
    detail: bool = False,
    eyebrow: str = "实践课资料包",
) -> str:
    source = content["source_courseware"]
    page_class = "page detail-page" if detail else "page index-page"
    footer = "实践课资料包 · 学生路线" if role == "student" else "实践课资料包 · 教师使用"
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
    .page {{ max-width:1180px; margin:0 auto; padding:24px 22px 56px; }}
    .detail-page {{ max-width:920px; }}
    .masthead {{ display:flex; gap:20px; justify-content:space-between; align-items:flex-start; padding:20px 0 10px; }}
    .eyebrow {{ color:var(--accent); font-size:.82rem; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    h1,h2,h3 {{ line-height:1.25; margin:0 0 12px; }} h1 {{ font-size:clamp(1.75rem,4vw,2.8rem); }} h2 {{ font-size:1.45rem; }} h3 {{ font-size:1.08rem; }}
    h4 {{ margin:20px 0 8px; }} p {{ margin:8px 0 14px; }}
    .nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 24px; padding:10px; background:#f0f4f1; border:1px solid var(--line); border-radius:14px; }}
    .nav-link {{ padding:7px 12px; border-radius:10px; text-decoration:none; color:var(--ink); }} .nav-link:hover,.nav-link.active {{ background:var(--sky); color:#214e5a; }}
    .hero {{ background:linear-gradient(135deg,var(--sky),#f3f6ef 64%,var(--peach)); padding:24px; border:1px solid var(--line); border-radius:22px; }}
    .hero p {{ max-width:820px; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:16px; }} .chip {{ display:inline-flex; padding:4px 10px; border-radius:999px; background:#ffffffaa; border:1px solid #c7d9da; color:#3f5b68; font-size:.9rem; }} .detail-help {{ flex-basis:100%; }}
    .section {{ margin-top:28px; }} .section-head {{ display:flex; gap:12px; align-items:baseline; justify-content:space-between; margin-bottom:12px; }}
    .summary-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }}
    .card {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:18px; box-shadow:0 4px 16px #384d5a0d; min-width:0; }}
    .card.soft {{ background:var(--sage); }} .card.warm {{ background:var(--peach); }} .card.blue {{ background:var(--sky); }}
    .label {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:.78rem; font-weight:700; background:#eef2f2; color:#526b75; }} .label.core {{ background:#dcecef; color:#285b68; }} .label.optional {{ background:#e6efe9; color:#3a6553; }} .label.challenge {{ background:#f8eade; color:#87523a; }}
    .task-top {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px; }}
    .task-meta {{ color:var(--muted); font-size:.9rem; }}
    .detail-main {{ max-width:900px; margin:0 auto; }}
    .detail-card {{ margin-top:18px; }}
    .detail-nav {{ display:flex; flex-wrap:wrap; gap:10px; justify-content:space-between; align-items:center; margin:18px 0; }}
    .detail-nav a,.entry-button {{ display:inline-flex; align-items:center; gap:5px; padding:8px 12px; border:1px solid #adc3c6; border-radius:10px; background:#fff; text-decoration:none; color:var(--ink); }}
    .entry-button {{ background:#e8f1f2; border-color:#b8d0d2; font-weight:700; }} .entry-button:hover,.detail-nav a:hover {{ background:var(--sky); }}
    ol,ul {{ margin:7px 0 12px; padding-left:1.35rem; }} li {{ margin:4px 0; }}
    .scaffold {{ padding:12px 14px; margin:12px 0; border-radius:12px; background:#f3f6f4; border:1px dashed #b8cac6; }}
    .acceptance {{ display:grid; gap:6px; }} .check {{ display:flex; gap:8px; align-items:flex-start; }}
    pre {{ overflow:auto; max-width:100%; padding:14px; border-radius:12px; background:#263b48; color:#f4f6f1; font:.88rem/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }} code {{ font-family:inherit; }}
    .source-ref {{ display:inline-block; margin:3px 4px 3px 0; padding:3px 8px; border-radius:8px; background:#eef5f4; color:#426b76; font-size:.84rem; text-decoration:none; }} .source-ref:hover {{ background:#dcecef; }}
    .callout {{ padding:14px 16px; border-radius:14px; background:#fff9ed; border:1px solid #ead9ae; }}
    .interaction {{ margin-top:16px; padding:18px; background:#f7f8f6; border-radius:14px; border:1px solid var(--line); }}
    .interaction button,.interaction select,.interaction input {{ border:1px solid #adc3c6; background:#fff; color:var(--ink); border-radius:9px; padding:8px 11px; margin:5px 5px 5px 0; cursor:pointer; font:inherit; }} .interaction button:hover,.interaction button:focus,.interaction select:focus,.interaction input:focus {{ background:var(--sky); outline:2px solid #9dbdc1; outline-offset:1px; }}
    .feedback {{ min-height:1.7em; color:#3e6759; font-weight:600; }} .feedback.wrong {{ color:#8a5b45; }}
    .step {{ display:none; padding:12px; background:#fff; border-radius:10px; margin:12px 0; }} .step.show {{ display:block; }}
    .classify-item,.reorder-item,.simulator-row,.multi-question {{ padding:9px 0; }} .classify-item label {{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
    .reorder-list {{ list-style:none; padding:0; margin:14px 0; display:grid; gap:8px; }} .reorder-item {{ display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px; padding:10px 12px; background:#fff; border:1px solid var(--line); border-radius:10px; }}
    .reorder-controls {{ white-space:nowrap; }} .reorder-controls button {{ padding:5px 8px; margin:0 0 0 4px; }}
    .sim-array {{ padding:8px 10px; background:#fff; border-radius:9px; font-family:ui-monospace,SFMono-Regular,Consolas,monospace; overflow:auto; }}
    .terminal-note {{ display:none; padding:10px 12px; border-radius:10px; background:#e6efe9; color:#315d4b; font-weight:700; }} .terminal-note.show {{ display:block; }}
    .multi-question {{ display:none; padding:12px; background:#fff; border-radius:10px; }} .multi-question.is-current {{ display:block; }}
    .reference-answer {{ white-space:pre-wrap; }}
    .footer {{ margin-top:42px; padding-top:16px; border-top:1px solid var(--line); color:var(--muted); font-size:.9rem; }}
    @media (max-width:1100px) {{ .summary-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
    @media (max-width:700px) {{ .page {{ padding:16px 14px 42px; }} .masthead {{ display:block; }} .nav {{ gap:4px; }} .nav-link {{ padding:6px 8px; font-size:.9rem; }} .summary-grid {{ grid-template-columns:1fr; }} .detail-nav {{ align-items:stretch; }} }}
  </style>
</head>
<body>
  <main class="{page_class}" data-role="{role}" data-page-kind="{"detail" if detail else "index"}">
    <header class="masthead">
      <div><div class="eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1></div>
      <div class="chip">{esc(source["chapter_title"])}</div>
    </header>
    <nav class="nav" aria-label="实践课页面导航">{_nav_links(active, role, prefix)}</nav>
    {body}
    <footer class="footer">{esc(content["course_title"])} · {footer}</footer>
  </main>
  <script>
  (() => {{
    const neutralRetry = '还有项目需要调整，请根据本题规则重新检查。';
    const neutralSuccess = '已完成当前检查，请把判断依据说给同伴听。';
    document.querySelectorAll('[data-choice]').forEach((button) => button.addEventListener('click', () => {{
      const box = button.closest('[data-question], [data-interaction-root]');
      if (!box) return;
      const feedback = box.querySelector('.feedback');
      const correct = button.dataset.correct === 'true';
      if (feedback) {{ feedback.textContent = button.dataset.feedback || (correct ? neutralSuccess : neutralRetry); feedback.classList.toggle('wrong', !correct); }}
      box.querySelectorAll('[data-choice]').forEach((item) => item.setAttribute('aria-pressed', item === button ? 'true' : 'false'));
      const root = button.closest('[data-multi-root]');
      if (root) {{
        const questions = [...root.querySelectorAll('[data-question]')];
        const answered = questions.filter((item) => item.querySelector('[data-choice][aria-pressed="true"]')).length;
        const correctCount = questions.filter((item) => item.querySelector('[data-choice][aria-pressed="true"]')?.dataset.correct === 'true').length;
        const score = root.querySelector('[data-multi-score]');
        if (score) score.textContent = `已完成 ${{answered}} / ${{questions.length}} 题；当前正确 ${{correctCount}} 题`;
        const next = root.querySelector('[data-multi-next]');
        if (next) next.disabled = false;
      }}
    }}));
    document.querySelectorAll('[data-stepper]').forEach((box) => {{
      const steps = [...box.querySelectorAll('.step')]; let current = 0;
      const show = (index) => {{ current = Math.max(0, Math.min(index, steps.length - 1)); steps.forEach((step, i) => step.classList.toggle('show', i === current)); const status = box.querySelector('.step-status'); if (status) status.textContent = `第 ${{current + 1}} / ${{steps.length}} 步`; }};
      box.querySelector('[data-prev]')?.addEventListener('click', () => show(current - 1)); box.querySelector('[data-next]')?.addEventListener('click', () => show(current + 1)); show(0);
    }});
    document.querySelectorAll('[data-classify]').forEach((box) => {{
      box.querySelector('[data-check]')?.addEventListener('click', () => {{
        let correct = true; box.querySelectorAll('[data-classify-item]').forEach((item) => {{ const select = item.querySelector('select'); const ok = select && select.value === item.dataset.answer; correct = correct && ok; }});
        const feedback = box.querySelector('.feedback'); if (feedback) {{ feedback.textContent = correct ? (box.dataset.successFeedback || neutralSuccess) : (box.dataset.retryFeedback || neutralRetry); feedback.classList.toggle('wrong', !correct); }}
      }});
    }});
    document.querySelectorAll('[data-reorder]').forEach((box) => {{
      const list = box.querySelector('[data-reorder-list]');
      const items = () => [...list.querySelectorAll('[data-reorder-item]')];
      const refresh = () => items().forEach((item, index) => {{ item.querySelector('[data-position]').textContent = String(index + 1); item.querySelector('[data-move-up]').disabled = index === 0; item.querySelector('[data-move-down]').disabled = index === items().length - 1; }});
      box.querySelectorAll('[data-move-up]').forEach((button) => button.addEventListener('click', () => {{ const item = button.closest('[data-reorder-item]'); const previous = item.previousElementSibling; if (previous) list.insertBefore(item, previous); refresh(); }}));
      box.querySelectorAll('[data-move-down]').forEach((button) => button.addEventListener('click', () => {{ const item = button.closest('[data-reorder-item]'); const next = item.nextElementSibling; if (next) list.insertBefore(next, item); refresh(); }}));
      box.querySelector('[data-check]')?.addEventListener('click', () => {{ const expected = JSON.parse(box.dataset.correctOrder); const actual = items().map((item) => item.dataset.itemId); const ok = expected.every((item, index) => item === actual[index]); const feedback = box.querySelector('.feedback'); if (feedback) {{ feedback.textContent = ok ? (box.dataset.successFeedback || neutralSuccess) : (box.dataset.retryFeedback || neutralRetry); feedback.classList.toggle('wrong', !ok); }} }});
      refresh();
    }});
    document.querySelectorAll('[data-simulator]').forEach((box) => {{
      const rounds = JSON.parse(box.dataset.rounds); let current = 0;
      const feedback = box.querySelector('.feedback'); const status = box.querySelector('.sim-status'); const next = box.querySelector('[data-next-round]'); const nextState = box.querySelector('[data-next-state]'); const terminal = box.querySelector('[data-terminal-note]');
      const fill = (round) => {{ box.querySelector('[data-state-a]').value = round.left; box.querySelector('[data-state-b]').value = round.right; box.querySelector('[data-state-mid]').value = round.mid; const continuing = round.status === 'continue'; if (nextState) nextState.hidden = !continuing; if (next) {{ next.hidden = !continuing; next.disabled = true; }} if (terminal) {{ terminal.classList.toggle('show', !continuing); terminal.textContent = round.status === 'found' ? '已到达终止状态：找到目标，过程结束。' : '已到达终止状态：没有可继续的状态，过程结束。'; }} if (status) status.textContent = `第 ${{current + 1}} / ${{rounds.length}} 轮`; }};
      box.querySelector('[data-check]')?.addEventListener('click', () => {{ const round = rounds[current]; const values = [Number(box.querySelector('[data-state-a]').value), Number(box.querySelector('[data-state-b]').value), Number(box.querySelector('[data-state-mid]').value)]; let ok = values[0] === round.left && values[1] === round.right && values[2] === round.mid; if (round.status === 'continue') ok = ok && Number(box.querySelector('[data-state-next-a]').value) === round.next_left && Number(box.querySelector('[data-state-next-b]').value) === round.next_right; if (feedback) {{ feedback.textContent = ok ? (round.feedback || box.dataset.successFeedback || neutralSuccess) : (box.dataset.retryFeedback || neutralRetry); feedback.classList.toggle('wrong', !ok); }} if (ok && round.status === 'continue' && next) next.disabled = false; }});
      next?.addEventListener('click', () => {{ if (rounds[current]?.status !== 'continue' || current >= rounds.length - 1) return; current += 1; fill(rounds[current]); if (feedback) {{ feedback.textContent = '请先完成当前状态的判断，再检查反馈。'; feedback.classList.remove('wrong'); }} }});
      fill(rounds[0]);
    }});
    document.querySelectorAll('[data-multi-root]').forEach((root) => {{
      const questions = [...root.querySelectorAll('[data-question]')]; let current = 0;
      const next = root.querySelector('[data-multi-next]'); const status = root.querySelector('[data-multi-status]');
      const show = (index) => {{ current = Math.max(0, Math.min(index, questions.length - 1)); questions.forEach((question, i) => question.classList.toggle('is-current', i === current)); if (status) status.textContent = `问题 ${{current + 1}} / ${{questions.length}}`; if (next) {{ next.disabled = true; next.textContent = current === questions.length - 1 ? '完成本组' : '下一题'; }} }};
      next?.addEventListener('click', () => {{ if (!questions[current].querySelector('[data-choice][aria-pressed="true"]')) return; if (current < questions.length - 1) show(current + 1); else {{ next.disabled = true; if (status) status.textContent = '本组问题已完成'; }} }}); show(0);
    }});
  }})();
  </script>
</body>
</html>
'''


def _task_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in content["tasks"]}


def _knowledge_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in content["knowledge_links"]}


def _guide_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in content["study_guide"]}


def _kit_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in content["foundation_kit"]}


def _task_title(task_by_id: dict[str, dict[str, Any]], task_id: str) -> str:
    return task_by_id.get(task_id, {}).get("title", "相关任务")


def _knowledge_titles(knowledge_by_id: dict[str, dict[str, Any]], ids: list[str]) -> str:
    return "、".join(knowledge_by_id[item]["title"] for item in ids if item in knowledge_by_id) or "本次实践方法"


def _source_attrs(values: list[str]) -> str:
    return esc(" ".join(values))


def _detail_nav(*, back_href: str, back_label: str, previous: tuple[str, str] | None, next_item: tuple[str, str] | None) -> str:
    previous_html = f'<a href="{previous[0]}">← 上一个：{esc(previous[1])}</a>' if previous else "<span></span>"
    next_html = f'<a href="{next_item[0]}">下一个：{esc(next_item[1])} →</a>' if next_item else "<span></span>"
    return f'<div class="detail-nav"><a href="{back_href}">← {esc(back_label)}</a><span class="detail-nav-pair">{previous_html} {next_html}</span></div>'


def _task_href(task_id: str, detail: bool = False) -> str:
    return f"../tasks/{slug(task_id)}.html" if detail else f"tasks/{slug(task_id)}.html"


def _learning_href(center_id: str, detail: bool = False) -> str:
    return f"../learning/{slug(center_id)}.html" if detail else f"learning/{slug(center_id)}.html"


def _guide_href(guide_id: str, detail: bool = False) -> str:
    return f"../guides/{slug(guide_id)}.html" if detail else f"guides/{slug(guide_id)}.html"


def _kit_href(kit_id: str, detail: bool = False) -> str:
    return f"../kit/{slug(kit_id)}.html" if detail else f"kit/{slug(kit_id)}.html"


def _help_links(content: dict[str, Any], refs: list[str], *, detail: bool) -> str:
    guides = _guide_map(content)
    kits = _kit_map(content)
    links: list[str] = []
    for ref in refs:
        if ref in guides:
            links.append(f'<a class="source-ref" href="{_guide_href(ref, detail)}">{esc(guides[ref]["title"])}</a>')
        elif ref in kits:
            links.append(f'<a class="source-ref" href="{_kit_href(ref, detail)}">{esc(kits[ref]["title"])}</a>')
    if not links:
        links.append(f'<a class="source-ref" href="{("../" if detail else "")}learning-center.html">回到学习中心复做</a>')
    return "".join(links)


def _starter_html(asset: dict[str, Any], *, detail: bool) -> str:
    prefix = "../" if detail else ""
    return f'''<details class="starter-box"><summary>查看起点材料：{esc(asset["path"])}</summary>
      <pre><code>{esc(asset["content"])}</code></pre>
      <p class="task-meta">可直接打开或下载：<a href="{prefix}starter/{esc(asset["path"])}">{esc(asset["path"])}</a></p>
    </details>'''


def _task_summary(content: dict[str, Any], task: dict[str, Any]) -> str:
    guides = _guide_map(content)
    kits = _kit_map(content)
    help_text = "、".join(
        guides[ref]["title"] if ref in guides else kits[ref]["title"]
        for ref in task.get("help_refs", [])
        if ref in guides or ref in kits
    ) or "学习中心"
    return f'''<article class="card" id="task-summary-{slug(task["id"])}" data-task-id="{esc(task["id"])}" data-source-slide-ids="{_source_attrs(task.get("source_slide_ids", []))}">
      <div class="task-top"><span class="label {esc(task["level"])}">{esc(LEVEL_LABELS.get(task["level"], task["level"]))}</span><span class="task-meta">约 {esc(task["estimated_minutes"])} 分钟</span></div>
      <h3>{esc(task["title"])}</h3><p>{text_block(task["overview"])}</p><p class="task-meta">需要帮助时：{esc(help_text)}</p>
      <a class="entry-button" href="{_task_href(task["id"])}">打开任务</a>
    </article>'''


def render_student_index(content: dict[str, Any]) -> str:
    grouped = {level: [task for task in content["tasks"] if task["level"] == level] for level in ("core", "optional", "challenge")}
    headings = {"core": "核心必做", "optional": "有余力", "challenge": "提高挑战"}
    sections: list[str] = []
    for level in ("core", "optional", "challenge"):
        cards = "".join(_task_summary(content, task) for task in grouped[level])
        sections.append(f'<section class="section" id="{level}-tasks"><div class="section-head"><h2>{headings[level]}</h2><span class="task-meta">{len(grouped[level])} 项任务</span></div><div class="summary-grid">{cards}</div></section>')
    knowledge = _knowledge_map(content)
    theory_items = "".join(f'<li>{esc(item["title"])}：{text_block(item["student_can_do"])}</li>' for item in knowledge.values())
    body = f'''
    <section class="hero"><div class="eyebrow">先完成一条可检查的路线</div><h2>今天要完成什么</h2><p>先打开核心必做任务，按“理解 → 操作/实现 → 验证”推进；有余力再扩大练习面，提高挑战用于迁移。每张任务卡只给你进入所需的信息，完整步骤会在任务详情页展开。</p><div class="meta"><span class="chip">课堂时长 {esc(content["duration_minutes"])} 分钟</span><span class="chip">核心必做 {len(grouped["core"])} 项</span>{student_tools(content)}</div></section>
    <section class="section"><div class="section-head"><h2>课堂路线</h2><a href="learning-center.html">先去学习中心热身 →</a></div><div class="card blue"><ol><li>先完成全部核心必做，打开每张任务卡逐项检查。</li><li>遇到卡点就打开任务卡里的帮助入口，不需要等待额外材料。</li><li>完成一个可运行、可操作或可解释的结果后，再选择有余力和提高挑战。</li></ol></div></section>
    <section class="section"><div class="section-head"><h2>本次理论线</h2><span class="task-meta">从已讲内容进入实践</span></div><div class="card"><ul>{theory_items}</ul></div></section>
    {"".join(sections)}'''
    return shell(content, "student", "实践路线", body, role="student", eyebrow="实践路线首页")


def render_task_detail(content: dict[str, Any], task: dict[str, Any], index: int) -> str:
    knowledge_by_id = _knowledge_map(content)
    assets = {item["id"]: item for item in content["starter_assets"]}
    steps = "".join(
        f"<li><strong>{esc(step['title'])}</strong>：{text_block(step['instruction'])}"
        + (f'<br><span class="task-meta">自检：{text_block(step["check"])}</span>' if step.get("check") else "")
        + "</li>"
        for step in task["steps"]
    )
    acceptance = "".join(f'<div class="check"><span aria-hidden="true">□</span><span>{text_block(item)}</span></div>' for item in task["acceptance"])
    starters = "".join(_starter_html(assets[asset_id], detail=True) for asset_id in task.get("starter_asset_ids", []) if asset_id in assets)
    previous = None
    next_item = None
    if index > 0:
        previous_task = content["tasks"][index - 1]
        previous = (_task_href(previous_task["id"], detail=True), previous_task["title"])
    if index < len(content["tasks"]) - 1:
        next_task = content["tasks"][index + 1]
        next_item = (_task_href(next_task["id"], detail=True), next_task["title"])
    source_refs = task.get("source_slide_ids", [])
    body = f'''
    {_detail_nav(back_href="../student-task.html", back_label="实践路线", previous=previous, next_item=next_item)}
    <section class="hero" data-task-id="{esc(task["id"])}" data-source-slide-ids="{_source_attrs(source_refs)}"><div class="task-top"><span class="label {esc(task["level"])}">{esc(LEVEL_LABELS.get(task["level"], task["level"]))}</span><span class="task-meta">约 {esc(task["estimated_minutes"])} 分钟</span></div><h2>{esc(task["title"])}</h2><p>{text_block(task["overview"])}</p><p class="task-meta">对应知识：{esc(_knowledge_titles(knowledge_by_id, task["knowledge_link_ids"]))}</p>{_detail_meta(int(task["estimated_minutes"]), _help_links(content, task.get("help_refs", []), detail=True))}</section>
    <div class="detail-main">
      <section class="card detail-card"><h3>先从这个起点开始</h3><div class="scaffold">{text_block(task["scaffold"])}</div><h3>完成步骤</h3><ol>{steps}</ol></section>
      <section class="card detail-card"><h3>验收清单</h3><div class="acceptance">{acceptance}</div></section>
      {f'<section class="card detail-card"><h3>起点材料</h3>{starters}</section>' if starters else ''}
      <section class="card detail-card"><h3>卡住时去哪里</h3><p>先回到对应的学习资料，完成一小步后再回来继续：</p><div>{_help_links(content, task.get("help_refs", []), detail=True)}</div></section>
    </div>
    {_detail_nav(back_href="../student-task.html", back_label="实践路线", previous=previous, next_item=next_item)}'''
    return shell(content, "student", task["title"], body, role="student", prefix="../", detail=True, eyebrow="任务详情")


def _option_buttons(interaction: dict[str, Any]) -> str:
    return "".join(
        f'<button type="button" data-choice data-correct="{"true" if option.get("correct", index == interaction.get("answer_index")) else "false"}" data-feedback="{esc(option["feedback"])}" aria-pressed="false">{esc(option["label"])}</button>'
        for index, option in enumerate(interaction.get("options", []))
    )


def _feedback_attrs(interaction: dict[str, Any]) -> str:
    return f'data-success-feedback="{esc(interaction.get("success_feedback", ""))}" data-retry-feedback="{esc(interaction.get("retry_feedback", ""))}" data-completion-feedback="{esc(interaction.get("completion_feedback", ""))}"'


def render_interaction(center: dict[str, Any]) -> str:
    interaction = center["interaction"]
    kind = interaction["type"]
    family = interaction_family(kind)
    interaction_id = esc(center["id"])
    base = f'data-interaction-root data-interaction="{interaction_id}" data-interaction-type="{esc(kind)}" data-renderer-family="{family}" {_feedback_attrs(interaction)}'
    if family == "choice-family":
        return f'<div class="interaction" {base}><strong>{esc(interaction["prompt"])}</strong><div class="choice-options">{_option_buttons(interaction)}</div><div class="feedback" aria-live="polite">选择后阅读反馈，并说明你的依据。</div></div>'
    if family == "step-family":
        steps = "".join(f'<div class="step"><strong>{esc(step["title"])}</strong><p>{text_block(step["text"])}</p></div>' for step in interaction["steps"])
        return f'<div class="interaction" data-stepper="{interaction_id}" {base}><strong>{esc(interaction["prompt"])}</strong>{steps}<div><button type="button" data-prev>上一步</button><button type="button" data-next>下一步</button><span class="task-meta step-status" aria-live="polite"></span></div></div>'
    if family == "classify-family":
        categories = "".join(f'<option value="{esc(category)}">{esc(category)}</option>' for category in interaction["categories"])
        items = "".join(f'<div class="classify-item" data-classify-item data-answer="{esc(item["answer"])}"><label>{esc(item["label"])}<select aria-label="为 {esc(item["label"])} 选择分类"><option value="">请选择</option>{categories}</select></label><small class="task-meta">{esc(item["feedback"])}</small></div>' for item in interaction["items"])
        return f'<div class="interaction" data-classify="{interaction_id}" {base}><strong>{esc(interaction["prompt"])}</strong>{items}<button type="button" data-check>检查分类</button><div class="feedback" aria-live="polite">逐项完成后再检查。</div></div>'
    if family == "reorder-family":
        rows = "".join(f'<li class="reorder-item" data-reorder-item data-item-id="{esc(item["id"])}"><span><span data-position>{index + 1}</span>．{esc(item["label"])}</span><span class="reorder-controls"><button type="button" data-move-up aria-label="将{esc(item["label"])}上移">上移</button><button type="button" data-move-down aria-label="将{esc(item["label"])}下移">下移</button></span></li>' for index, item in enumerate(interaction["items"]))
        order = esc(json.dumps(interaction["correct_order"], ensure_ascii=False))
        return f'<div class="interaction" data-reorder="{interaction_id}" data-correct-order="{order}" {base}><strong>{esc(interaction["prompt"])}</strong><ol class="reorder-list" data-reorder-list>{rows}</ol><button type="button" data-check>检查顺序</button><div class="feedback" aria-live="polite">先改变顺序，再检查结果。</div></div>'
    if family == "state-simulator-family":
        state = interaction["state"]
        values = "、".join(esc(value) for value in state["values"])
        rounds = esc(json.dumps(interaction["rounds"], ensure_ascii=False))
        return f'<div class="interaction" data-simulator="{interaction_id}" data-rounds="{rounds}" {base}><strong>{esc(interaction["prompt"])}</strong><p class="sim-array">数据：[{values}]；目标：{esc(state["target"])}</p><div class="simulator-row">当前状态：<label>起点 <input data-state-a type="number"></label><label>终点 <input data-state-b type="number"></label><label>中心位置 <input data-state-mid type="number"></label></div><div class="simulator-row" data-next-state>下一状态：<label>起点 <input data-state-next-a type="number"></label><label>终点 <input data-state-next-b type="number"></label></div><button type="button" data-check>检查当前状态</button><button type="button" data-next-round disabled>进入下一轮</button><span class="task-meta sim-status" aria-live="polite"></span><div class="terminal-note" data-terminal-note></div><div class="feedback" aria-live="polite">先完成当前状态，再检查反馈。</div></div>'
    if family == "multi-question-family":
        question_parts: list[str] = []
        for index, question in enumerate(interaction["questions"]):
            options = "".join(
                f'<button type="button" data-choice data-correct="{"true" if option.get("correct", option_index == question.get("answer_index")) else "false"}" data-feedback="{esc(option["feedback"])}" aria-pressed="false">{esc(option["label"])}</button>'
                for option_index, option in enumerate(question["options"])
            )
            question_parts.append(f'<div class="multi-question" data-question data-question-index="{index}"><p><strong>{index + 1}．{esc(question["prompt"])}</strong></p><div>{options}</div><div class="feedback" aria-live="polite">请选择并阅读反馈。</div></div>')
        questions = "".join(question_parts)
        return f'<div class="interaction" {base} data-multi-root><strong>{esc(interaction["prompt"])}</strong><span class="task-meta" data-multi-status></span>{questions}<div class="feedback" data-multi-score aria-live="polite">已完成 0 / {len(interaction["questions"])} 题；当前正确 0 题</div><button type="button" data-multi-next disabled>下一题</button></div>'
    return f'<div class="interaction" {base}><strong>{esc(interaction["prompt"])}</strong><div class="feedback">{esc(interaction.get("retry_feedback") or "还有项目需要调整，请根据本题规则重新检查。")}</div></div>'


def render_learning_index(content: dict[str, Any]) -> str:
    task_by_id = _task_map(content)
    knowledge_by_id = _knowledge_map(content)
    cards = []
    for center in content["learning_center"]:
        tasks = "、".join(_task_title(task_by_id, task_id) for task_id in center["task_ids"])
        topics = _knowledge_titles(knowledge_by_id, center["knowledge_link_ids"])
        cards.append(f'<article class="card" id="learning-summary-{slug(center["id"])}" data-center-id="{esc(center["id"])}"><div class="task-top"><span class="label">互动实验</span><span class="task-meta">对应 {esc(topics)}</span></div><h3>{esc(center["title"])}</h3><p>{text_block(center["purpose"])}</p><p class="task-meta">用于：{esc(tasks)}</p><a class="entry-button" href="{_learning_href(center["id"])}">进入实验</a></article>')
    body = f'<section class="hero"><div class="eyebrow">围绕任务练习关键判断</div><h2>学习中心目录</h2><p>每个实验都只解决一个具体卡点。先看摘要，再进入单个实验；完成后带着反馈回到任务详情页。</p><div class="meta">{student_tools(content)}<span class="chip">{len(content["learning_center"])} 个实验区</span></div></section><section class="section"><div class="summary-grid">{"".join(cards)}</div></section>'
    return shell(content, "center", "学习中心", body, role="student", eyebrow="学习中心目录")


def render_learning_detail(content: dict[str, Any], center: dict[str, Any], index: int) -> str:
    task_by_id = _task_map(content)
    knowledge_by_id = _knowledge_map(content)
    previous = None
    next_item = None
    if index > 0:
        previous_center = content["learning_center"][index - 1]
        previous = (_learning_href(previous_center["id"], detail=True), previous_center["title"])
    if index < len(content["learning_center"]) - 1:
        next_center = content["learning_center"][index + 1]
        next_item = (_learning_href(next_center["id"], detail=True), next_center["title"])
    tasks = "、".join(_task_title(task_by_id, task_id) for task_id in center["task_ids"])
    task_links = _task_links(content, center["task_ids"])
    topics = _knowledge_titles(knowledge_by_id, center["knowledge_link_ids"])
    body = f'''
    {_detail_nav(back_href="../learning-center.html", back_label="学习中心", previous=previous, next_item=next_item)}
    <section class="hero"><div class="eyebrow">聚焦实验</div><h2>{esc(center["title"])}</h2><p>{text_block(center["purpose"])}</p><p class="task-meta">对应知识：{esc(topics)} · 用于：{esc(tasks)}</p>{_detail_meta(_task_minutes(content, center["task_ids"]), task_links)}</section>
    <div class="detail-main"><section class="card detail-card">{render_interaction(center)}</section></div>
    {_detail_nav(back_href="../learning-center.html", back_label="学习中心", previous=previous, next_item=next_item)}'''
    return shell(content, "center", center["title"], body, role="student", prefix="../", detail=True, eyebrow="学习中心 · 实验详情")


def _guide_summary(content: dict[str, Any], guide: dict[str, Any]) -> str:
    task_by_id = _task_map(content)
    tasks = "、".join(_task_title(task_by_id, item) for item in guide["task_ids"])
    preview = guide["body"][:150]
    return f'<article class="card" id="guide-summary-{slug(guide["id"])}" data-guide-id="{esc(guide["id"])}"><h3>{esc(guide["title"])}</h3><p>{text_block(preview)}{"…" if len(guide["body"]) > 150 else ""}</p><p class="task-meta">帮助任务：{esc(tasks)}</p><a class="entry-button" href="{_guide_href(guide["id"])}">打开资料</a></article>'


def render_guide_index(content: dict[str, Any]) -> str:
    body = f'<section class="hero"><div class="eyebrow">按理论顺序自助复盘</div><h2>学习指南目录</h2><p>先根据任务卡选择一个资料条目；每个条目都提供同一案例的解释、快速查表、常见卡点和检查点。</p></section><section class="section"><div class="summary-grid">{"".join(_guide_summary(content, item) for item in content["study_guide"])}</div></section>'
    return shell(content, "guide", "学习指南", body, role="student", eyebrow="学习指南目录")


def render_guide_detail(content: dict[str, Any], guide: dict[str, Any], index: int) -> str:
    task_by_id = _task_map(content)
    tasks = _task_links(content, guide["task_ids"])
    previous = None
    next_item = None
    if index > 0:
        item = content["study_guide"][index - 1]
        previous = (_guide_href(item["id"], detail=True), item["title"])
    if index < len(content["study_guide"]) - 1:
        item = content["study_guide"][index + 1]
        next_item = (_guide_href(item["id"], detail=True), item["title"])
    body = f'''
    {_detail_nav(back_href="../study-guide.html", back_label="学习指南", previous=previous, next_item=next_item)}
    <section class="hero"><div class="eyebrow">学习资料详情</div><h2>{esc(guide["title"])}</h2><p>{text_block(guide["body"])}</p><p class="task-meta">帮助任务：</p><div>{tasks}</div>{_detail_meta(_task_minutes(content, guide["task_ids"]), tasks, label="关联任务")}</section>
    <div class="detail-main"><section class="card detail-card"><h3>同一案例 / 操作示例</h3><div class="callout">{text_block(guide["worked_example"])}</div><h3>快速查表</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in guide["quick_reference"])}</ul><h3>常见卡点</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in guide["common_errors"])}</ul><h3>检查自己</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in guide["checkpoints"])}</ul></section></div>
    {_detail_nav(back_href="../study-guide.html", back_label="学习指南", previous=previous, next_item=next_item)}'''
    return shell(content, "guide", guide["title"], body, role="student", prefix="../", detail=True, eyebrow="学习指南 · 资料详情")


def _kit_summary(content: dict[str, Any], kit: dict[str, Any]) -> str:
    task_by_id = _task_map(content)
    tasks = "、".join(_task_title(task_by_id, item) for item in kit["task_ids"])
    preview = kit["content"][:150]
    return f'<article class="card soft" id="kit-summary-{slug(kit["id"])}" data-kit-id="{esc(kit["id"])}"><div class="label">基础补给</div><h3>{esc(kit["title"])}</h3><p>{text_block(preview)}{"…" if len(kit["content"]) > 150 else ""}</p><p class="task-meta">服务任务：{esc(tasks)}</p><a class="entry-button" href="{_kit_href(kit["id"])}">打开补给</a></article>'


def render_kit_index(content: dict[str, Any]) -> str:
    body = f'<section class="hero"><div class="eyebrow">只补本节真正会用到的能力</div><h2>基础补给目录</h2><p>遇到术语、工具操作或语法卡点时，打开一个微专题；每个条目都给出使用时机、步骤和自检。</p><div class="meta">{student_tools(content)}<span class="chip">{len(content["foundation_kit"])} 个微专题</span></div></section><section class="section"><div class="summary-grid">{"".join(_kit_summary(content, item) for item in content["foundation_kit"])}</div></section>'
    return shell(content, "kit", "基础补给", body, role="student", eyebrow="基础补给目录")


def render_kit_detail(content: dict[str, Any], kit: dict[str, Any], index: int) -> str:
    task_by_id = _task_map(content)
    tasks = _task_links(content, kit["task_ids"])
    previous = None
    next_item = None
    if index > 0:
        item = content["foundation_kit"][index - 1]
        previous = (_kit_href(item["id"], detail=True), item["title"])
    if index < len(content["foundation_kit"]) - 1:
        item = content["foundation_kit"][index + 1]
        next_item = (_kit_href(item["id"], detail=True), item["title"])
    body = f'''
    {_detail_nav(back_href="../foundation-kit.html", back_label="基础补给", previous=previous, next_item=next_item)}
    <section class="hero"><div class="eyebrow">微专题详情</div><h2>{esc(kit["title"])}</h2><p>{text_block(kit["content"])}</p><p class="task-meta">什么时候打开：{text_block(kit["when_to_use"])}</p><p class="task-meta">服务任务：</p><div>{tasks}</div>{_detail_meta(_task_minutes(content, kit["task_ids"]), tasks, label="关联任务")}</section>
    <div class="detail-main"><section class="card soft detail-card"><h3>操作步骤</h3><ol>{"".join(f"<li>{text_block(item)}</li>" for item in kit["steps"])}</ol><h3>自检</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in kit["self_check"])}</ul></section></div>
    {_detail_nav(back_href="../foundation-kit.html", back_label="基础补给", previous=previous, next_item=next_item)}'''
    return shell(content, "kit", kit["title"], body, role="student", prefix="../", detail=True, eyebrow="基础补给 · 微专题详情")


def task_source_text(task: dict[str, Any], knowledge_by_id: dict[str, dict[str, Any]]) -> str:
    return _knowledge_titles(knowledge_by_id, task.get("knowledge_link_ids", []))


def _task_minutes(content: dict[str, Any], task_ids: list[str]) -> int:
    task_by_id = _task_map(content)
    return sum(int(task_by_id[task_id].get("estimated_minutes", 0)) for task_id in task_ids if task_id in task_by_id)


def _task_links(content: dict[str, Any], task_ids: list[str], *, prefix: str = "../") -> str:
    task_by_id = _task_map(content)
    return " ".join(
        f'<a class="source-ref" href="{prefix}tasks/{slug(task_id)}.html">{esc(_task_title(task_by_id, task_id))}</a>'
        for task_id in task_ids
        if task_id in task_by_id
    )


def _detail_meta(minutes: int, help_links: str, *, label: str = "预计") -> str:
    help_text = help_links or "请回到上一级目录选择相关入口。"
    return f'<div class="meta detail-meta"><span class="chip">{esc(label)}约 {minutes} 分钟</span><span class="chip">帮助入口在本页</span><span class="detail-help">{help_text}</span></div>'


def render_teacher_guide(content: dict[str, Any]) -> str:
    teacher = content["teacher_guide"]
    task_by_id = _task_map(content)
    knowledge_by_id = _knowledge_map(content)
    timing = "".join(f'<li><strong>{esc(item["minutes"])} 分钟</strong>：{text_block(item["focus"])}</li>' for item in teacher["timing"])
    guidance = "".join(
        f'<article class="card"><div class="task-top"><span class="label {esc(task_by_id[item["task_id"]]["level"])}">{esc(LEVEL_LABELS.get(task_by_id[item["task_id"]]["level"], task_by_id[item["task_id"]]["level"]))}</span><span class="task-meta">{esc(task_source_text(task_by_id[item["task_id"]], knowledge_by_id))}</span></div><h3>{esc(task_by_id[item["task_id"]]["title"])}</h3><p><strong>巡回观察：</strong>{text_block(item["look_for"])}</p><p><strong>卡住时追问：</strong>{text_block(item["ask_when_stuck"])}</p></article>'
        for item in teacher["task_guidance"]
    )
    errors = "".join(f'<li><strong>{text_block(item["symptom"])}</strong>：{text_block(item["intervention"])}</li>' for item in teacher["common_errors"])
    pace_adjustments = "".join(f'<div class="card soft"><p>{text_block(item)}</p></div>' for item in teacher["pace_adjustments"])
    closing_checks = "".join(f"<li>{text_block(item)}</li>" for item in teacher["closing_checks"])
    body = f'''
    <section class="hero"><div class="eyebrow">课堂控制台</div><h2>教师指南</h2><p>{text_block(teacher["purpose"])}</p><div class="callout"><strong>理论—实践桥：</strong>{text_block(teacher["theory_bridge"])}</div><div class="meta"><a class="source-ref" href="../student/student-task.html">打开学生路线</a><a class="source-ref" href="teacher-reference.html">打开教师参考目录</a>{teacher_context(content)}</div></section>
    <section class="section"><h2>建议节奏（{esc(content["duration_minutes"])} 分钟）</h2><div class="card"><ol>{timing}</ol></div></section>
    <section class="section"><h2>任务观察点与理论链接</h2><div class="summary-grid">{guidance}</div></section>
    <section class="section"><h2>常见错误与干预</h2><div class="card warm"><ul>{errors}</ul></div></section>
    <section class="section"><h2>弱基础与快进度学生</h2><div class="summary-grid">{pace_adjustments}</div></section>
    <section class="section"><h2>完成标准与出口抽查</h2><div class="card blue"><p>完成标准：学生现场完成核心必做任务的可观察成果，能够指出理论依据、解释关键判断，并用验收条件复核结果；不把统一提交物作为默认门槛。</p><ul>{closing_checks}</ul></div></section>'''
    return shell(content, "teacher", "教师指南", body, role="teacher", eyebrow="教师课堂控制台")


def render_teacher_reference_index(content: dict[str, Any]) -> str:
    task_by_id = _task_map(content)
    cards = "".join(
        f'<article class="card" id="reference-summary-{slug(reference["task_id"])}" data-task-id="{esc(reference["task_id"])}"><div class="task-top"><span class="label {esc(task_by_id[reference["task_id"]]["level"])}">{esc(LEVEL_LABELS.get(task_by_id[reference["task_id"]]["level"], task_by_id[reference["task_id"]]["level"]))}</span><span class="task-meta">逐任务参考</span></div><h3>{esc(reference["title"])}</h3><p>{text_block(reference.get("reference_result") or "查看完整参考成果、关键步骤和验收依据。")}</p><a class="entry-button" href="references/{slug(reference["task_id"])}.html">查看参考</a></article>'
        for reference in content["teacher_reference"]["task_references"]
    )
    body = f'<section class="hero"><div class="eyebrow">教师专用答案层</div><h2>教师参考目录</h2><p>目录只显示任务摘要；完整参考成果、关键步骤和验收依据进入逐任务详情页，便于备课和现场快速查答案。</p><div class="meta"><a class="source-ref" href="../student/student-task.html">学生路线</a><a class="source-ref" href="teacher-guide.html">教师指南</a>{teacher_context(content)}</div></section><section class="section"><div class="summary-grid">{cards}</div></section>'
    return shell(content, "reference", "教师参考目录", body, role="teacher", eyebrow="教师参考目录")


def render_teacher_reference_detail(content: dict[str, Any], reference: dict[str, Any], index: int) -> str:
    task_by_id = _task_map(content)
    task = task_by_id[reference["task_id"]]
    previous = None
    next_item = None
    refs = content["teacher_reference"]["task_references"]
    if index > 0:
        item = refs[index - 1]
        previous = (f"{slug(item['task_id'])}.html", item["title"])
    if index < len(refs) - 1:
        item = refs[index + 1]
        next_item = (f"{slug(item['task_id'])}.html", item["title"])
    source_refs = " ".join(reference.get("source_slide_ids", []))
    result = f'<p><strong>参考结果：</strong>{text_block(reference["reference_result"])}</p>' if reference.get("reference_result") else ""
    body = f'''
    {_detail_nav(back_href="../teacher-reference.html", back_label="教师参考目录", previous=previous, next_item=next_item)}
    <section class="hero" data-task-id="{esc(reference["task_id"])}" data-source-slide-ids="{esc(source_refs)}"><div class="task-top"><span class="label {esc(task["level"])}">{esc(LEVEL_LABELS.get(task["level"], task["level"]))}</span><span class="task-meta">完整参考成果</span></div><h2>{esc(reference["title"])}</h2><p><a class="source-ref" href="../../student/tasks/{slug(reference["task_id"])}.html">查看学生任务</a></p>{_detail_meta(int(task["estimated_minutes"]), f'<a class="source-ref" href="../../student/tasks/{slug(reference["task_id"])}.html">打开学生任务</a>', label="课堂任务")}</section>
    <div class="detail-main"><section class="card detail-card"><h3>参考答案 / 参考成果</h3><pre class="reference-answer"><code>{esc(reference["reference_answer"])}</code></pre>{result}<h3>关键步骤</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["key_steps"])}</ul><h3>可接受变体</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["acceptable_variants"])}</ul><h3>常见错误</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["common_errors"])}</ul><h3>验收依据</h3><ul>{"".join(f"<li>{text_block(item)}</li>" for item in reference["acceptance_basis"])}</ul></section></div>
    {_detail_nav(back_href="../teacher-reference.html", back_label="教师参考目录", previous=previous, next_item=next_item)}'''
    return shell(content, "reference", reference["title"], body, role="teacher", prefix="../", detail=True, eyebrow="教师参考 · 任务详情")


def _safe_asset_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative.strip():
        raise ValueError(f"starter asset path must be relative and stay within student/starter/: {relative}")
    return path


def _write_page(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def generate(practice_path: Path, output_dir: Path, courseware_path: Path | None = None, *, replace: bool = False) -> dict[str, Any]:
    content = load_json(practice_path)
    courseware = load_courseware(courseware_path) if courseware_path else None
    contract_report = require_valid(content, courseware)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not replace:
        raise FileExistsError(f"output directory is not empty; use --replace: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    if replace:
        for stale in ("student", "teacher", "practice-content.json", "qa-report.json"):
            target = output_dir / stale
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()

    student_dir = output_dir / "student"
    teacher_dir = output_dir / "teacher"
    student_dir.mkdir(exist_ok=True)
    teacher_dir.mkdir(exist_ok=True)
    starter_dir = student_dir / "starter"
    if content["starter_assets"]:
        starter_dir.mkdir(exist_ok=True)
    (output_dir / "practice-content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for asset in content["starter_assets"]:
        destination = starter_dir / _safe_asset_path(asset["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(asset["content"], encoding="utf-8", newline="\n")

    _write_page(student_dir / "student-task.html", render_student_index(content))
    _write_page(student_dir / "learning-center.html", render_learning_index(content))
    _write_page(student_dir / "study-guide.html", render_guide_index(content))
    _write_page(student_dir / "foundation-kit.html", render_kit_index(content))
    for index, task in enumerate(content["tasks"]):
        _write_page(student_dir / "tasks" / f"{slug(task['id'])}.html", render_task_detail(content, task, index))
    for index, center in enumerate(content["learning_center"]):
        _write_page(student_dir / "learning" / f"{slug(center['id'])}.html", render_learning_detail(content, center, index))
    for index, guide in enumerate(content["study_guide"]):
        _write_page(student_dir / "guides" / f"{slug(guide['id'])}.html", render_guide_detail(content, guide, index))
    for index, kit in enumerate(content["foundation_kit"]):
        _write_page(student_dir / "kit" / f"{slug(kit['id'])}.html", render_kit_detail(content, kit, index))

    _write_page(teacher_dir / "teacher-guide.html", render_teacher_guide(content))
    _write_page(teacher_dir / "teacher-reference.html", render_teacher_reference_index(content))
    references = content["teacher_reference"]["task_references"]
    for index, reference in enumerate(references):
        _write_page(teacher_dir / "references" / f"{slug(reference['task_id'])}.html", render_teacher_reference_detail(content, reference, index))

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
