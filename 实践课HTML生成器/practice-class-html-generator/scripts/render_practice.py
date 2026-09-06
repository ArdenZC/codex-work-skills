"""Render Practice Class Content Contract 1.0 into offline classroom pages."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from practice_contract import load_courseware, load_json, require_valid
from validate_practice import validate_output_files


OUTPUT_HTML = (
    "student-task.html",
    "learning-center.html",
    "study-guide.html",
    "foundation-kit.html",
    "teacher-guide.html",
)


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def text_block(value: Any) -> str:
    return esc(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def slug(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", value).strip("-")
    return cleaned or "item"


def nav(active: str) -> str:
    links = (
        ("student-task.html", "学生任务", "student"),
        ("learning-center.html", "学习中心", "center"),
        ("study-guide.html", "学习指南", "guide"),
        ("foundation-kit.html", "基础工具包", "kit"),
        ("teacher-guide.html", "教师指南", "teacher"),
    )
    items = "".join(
        f'<a class="nav-link {"active" if key == active else ""}" href="{href}">{label}</a>'
        for href, label, key in links
    )
    return f'<nav class="nav" aria-label="实践课页面导航">{items}</nav>'


def shell(content: dict[str, Any], active: str, title: str, body: str) -> str:
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
    .hero p {{ max-width:780px; }}
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
    pre {{ overflow:auto; padding:14px; border-radius:12px; background:#263b48; color:#f4f6f1; font: .88rem/1.55 ui-monospace,SFMono-Regular,Consolas,monospace; }} code {{ font-family:inherit; }}
    .source-ref {{ display:inline-block; margin:3px 4px 3px 0; padding:3px 8px; border-radius:8px; background:#eef5f4; color:#426b76; font-size:.84rem; text-decoration:none; }}
    .source-ref:hover {{ background:#dcecef; }} .callout {{ padding:14px 16px; border-radius:14px; background:#fff9ed; border:1px solid #ead9ae; }}
    .interaction {{ margin-top:12px; padding:14px; background:#f7f8f6; border-radius:13px; border:1px solid var(--line); }}
    .interaction button {{ border:1px solid #adc3c6; background:#fff; color:var(--ink); border-radius:9px; padding:8px 11px; margin:5px 5px 5px 0; cursor:pointer; font:inherit; }} .interaction button:hover,.interaction button:focus {{ background:var(--sky); outline:2px solid #9dbdc1; outline-offset:1px; }}
    .feedback {{ min-height:1.7em; color:#3e6759; font-weight:600; }} .feedback.wrong {{ color:#8a5b45; }} .step {{ display:none; padding:12px; background:#fff; border-radius:10px; }} .step.show {{ display:block; }}
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
    {nav(active)}
    {body}
    <footer class="footer">{esc(content["course_title"])} · 面向 {esc(content["audience"])} · 本页为离线单文件课件</footer>
  </main>
  <script>
  (() => {{
    document.querySelectorAll('[data-choice]').forEach((button) => button.addEventListener('click', () => {{
      const box = button.closest('[data-interaction]');
      const feedback = box.querySelector('.feedback');
      feedback.textContent = button.dataset.feedback || '';
      feedback.classList.toggle('wrong', button.dataset.correct !== 'true');
      box.querySelectorAll('[data-choice]').forEach((item) => item.setAttribute('aria-pressed', item === button ? 'true' : 'false'));
    }}));
    document.querySelectorAll('[data-stepper]').forEach((box) => {{
      const steps = [...box.querySelectorAll('.step')]; let current = 0;
      const show = (index) => {{ current = Math.max(0, Math.min(index, steps.length - 1)); steps.forEach((step, i) => step.classList.toggle('show', i === current)); box.querySelector('.step-status').textContent = `第 ${{current + 1}} / ${{steps.length}} 步`; }};
      box.querySelector('[data-prev]').addEventListener('click', () => show(current - 1)); box.querySelector('[data-next]').addEventListener('click', () => show(current + 1)); show(0);
    }});
  }})();
  </script>
</body>
</html>
'''


def source_links(knowledge: list[dict[str, Any]], *, target: str = "#") -> str:
    links: list[str] = []
    for item in knowledge:
        refs = "、".join(esc(ref) for ref in item.get("source_slide_ids", [])) or "独立设计"
        href = f"{target}#knowledge-{slug(item['id'])}" if target != "#" else f"#knowledge-{slug(item['id'])}"
        links.append(f'<a class="source-ref" href="{href}">{esc(item["title"])} · 理论页 {refs}</a>')
    return "".join(links)


def render_task(task: dict[str, Any], assets_by_id: dict[str, dict[str, Any]], knowledge_by_id: dict[str, dict[str, Any]]) -> str:
    level = task["level"]
    refs = "、".join(esc(ref) for ref in task.get("knowledge_link_ids", []))
    source_refs = sorted({ref for knowledge_id in task.get("knowledge_link_ids", []) for ref in knowledge_by_id.get(knowledge_id, {}).get("source_slide_ids", [])})
    source_label = "、".join(esc(ref) for ref in source_refs) or "独立资料"
    steps = "".join(f"<li><strong>{esc(step['title'])}</strong>：{text_block(step['instruction'])}" + (f"<br><span class=\"task-meta\">自检：{text_block(step['check'])}</span>" if step.get("check") else "") + "</li>" for step in task["steps"])
    acceptance = "".join(f'<div class="check"><span aria-hidden="true">□</span><span>{text_block(item)}</span></div>' for item in task["acceptance"])
    help_links = "".join(f'<a class="source-ref" href="{("study-guide.html#guide-" + slug(ref)) if ref.startswith("guide-") else ("foundation-kit.html#kit-" + slug(ref))}">{esc(ref)}</a>' for ref in task.get("help_refs", []))
    starter = ""
    for asset_id in task.get("starter_asset_ids", []):
        asset = assets_by_id.get(asset_id)
        if not asset:
            continue
        starter += f'<details><summary>打开 starter：{esc(asset["path"])}</summary><pre><code>{esc(asset["content"])}</code></pre><p class="task-meta">也可下载：<a href="starter/{esc(asset["path"])}">{esc(asset["path"])}</a></p></details>'
    return f'''
    <article class="card task-card" id="task-{slug(task["id"])}" data-task-id="{esc(task["id"])}">
      <div class="task-top"><span class="label {esc(level)}">{esc(level)}</span><span class="chip">{esc(task["modality"])}</span><span class="task-meta">约 {esc(task["estimated_minutes"])} 分钟</span></div>
      <h3>{esc(task["title"])}</h3>
      <p>{text_block(task["overview"])}</p>
      <p class="task-meta">理论锚点：{refs} · 理论页：<span class="task-source-refs">{source_label}</span></p>
      <div class="scaffold"><strong>脚手架：</strong>{text_block(task["scaffold"])}</div>
      <h4>完成步骤</h4><ol>{steps}</ol>
      <h4>验收清单</h4><div class="acceptance">{acceptance}</div>
      {starter}
      <div class="task-meta">需要帮助时：{help_links or "先回到学习中心复做对应互动"}</div>
    </article>'''


def render_student(content: dict[str, Any]) -> str:
    knowledge = content["knowledge_links"]
    assets = {item["id"]: item for item in content["starter_assets"]}
    knowledge_by_id = {item["id"]: item for item in knowledge}
    grouped = {level: [task for task in content["tasks"] if task["level"] == level] for level in ("core", "optional", "challenge")}
    sections = ""
    labels = {"core": "核心任务：先完成可验证的最小成果", "optional": "可选任务：扩大练习面", "challenge": "挑战任务：解释与迁移"}
    for level in ("core", "optional", "challenge"):
        sections += f'<section class="section" id="{level}-tasks"><div class="section-head"><h2>{labels[level]}</h2><span class="task-meta">{len(grouped[level])} 项</span></div>{"".join(render_task(task, assets, knowledge_by_id) for task in grouped[level])}</section>'
    theory = "".join(f'<article class="card blue" id="knowledge-{slug(item["id"])}"><h3>{esc(item["title"])}</h3><p>{text_block(item["summary"])}</p><p><strong>做完后你能：</strong>{text_block(item["student_can_do"])}</p><div>{source_links([item])}</div></article>' for item in knowledge)
    body = f'''
    <section class="hero"><div class="eyebrow">先做出一个可检查的成果</div><h2>{esc(content["course_title"])} · 实践任务</h2><p>本页把理论页的概念转成一步一步的操作、建模或实现。先完成 core，再按时间选择 optional / challenge；每项任务都保留了理论锚点和可观察的验收条件。</p><div class="meta"><span class="chip">课堂时长 {esc(content["duration_minutes"])} 分钟</span><span class="chip">核心任务 {len(grouped["core"])} 项</span><span class="chip">理论页 {len(content["source_courseware"]["taught_slide_ids"])} 页</span></div></section>
    <section class="section"><div class="section-head"><h2>从理论页进入实践</h2><a href="learning-center.html">去学习中心做互动 →</a></div><div class="card-grid">{theory}</div></section>
    {sections}'''
    return shell(content, "student", "学生任务", body)


def render_interaction(center: dict[str, Any]) -> str:
    interaction = center["interaction"]
    kind = interaction["type"]
    if kind in {"choice", "match"}:
        buttons = "".join(f'<button type="button" data-choice data-correct="{"true" if option.get("correct", index == interaction.get("answer_index")) else "false"}" data-feedback="{esc(option["feedback"])}" aria-pressed="false">{esc(option["label"])}</button>' for index, option in enumerate(interaction["options"]))
        return f'<div class="interaction" data-interaction="{esc(center["id"])}"><strong>{esc(interaction["prompt"])}</strong><div>{buttons}</div><div class="feedback" aria-live="polite">选择后看反馈，并把理由说完整。</div></div>'
    steps = "".join(f'<div class="step"><strong>{esc(step["title"])}</strong><p>{text_block(step["text"])}</p></div>' for step in interaction["steps"])
    return f'<div class="interaction" data-stepper="{esc(center["id"])}"><strong>{esc(interaction["prompt"])}</strong>{steps}<div><button type="button" data-prev>上一步</button><button type="button" data-next>下一步</button><span class="task-meta step-status" aria-live="polite"></span></div></div>'


def render_center(content: dict[str, Any], center: dict[str, Any]) -> str:
    knowledge = {item["id"]: item for item in content["knowledge_links"]}
    refs = [knowledge[item] for item in center["knowledge_link_ids"] if item in knowledge]
    source = "、".join(ref for item in refs for ref in item.get("source_slide_ids", [])) or "独立练习"
    tasks = "、".join(center["task_ids"])
    return f'<article class="card" id="center-{slug(center["id"])}"><div class="task-top"><span class="label">知识点互动</span><span class="task-meta">理论页 {esc(source)}</span></div><h3>{esc(center["title"])}</h3><p>{text_block(center["purpose"])}</p><p class="task-meta">服务任务：{esc(tasks)}</p>{render_interaction(center)}</article>'


def render_learning_center(content: dict[str, Any]) -> str:
    centers = "".join(render_center(content, center) for center in content["learning_center"])
    body = f'''<section class="hero"><div class="eyebrow">互动只为帮助你完成任务</div><h2>学习中心</h2><p>每个互动都对应一个知识点和至少一个实践任务。点击选项或逐步推进后，请把反馈转述成自己的判断，再回到学生任务页面执行。</p></section><section class="section"><div class="card-grid">{centers}</div></section>'''
    return shell(content, "center", "学习中心", body)


def render_study_guide(content: dict[str, Any]) -> str:
    guides = "".join(f'<article class="card" id="guide-{slug(guide["id"])}"><h3>{esc(guide["title"])}</h3><p class="task-meta">知识点：{esc("、".join(guide["knowledge_link_ids"]))}</p><p>{text_block(guide["body"])}</p><h4>检查自己</h4><ul>{"".join(f"<li>{text_block(item)}</li>" for item in guide["checkpoints"])}</ul></article>' for guide in content["study_guide"])
    body = f'''<section class="hero"><div class="eyebrow">卡住时回到可观察的判断</div><h2>学习指南</h2><p>这里不是答案库，而是一组能够帮助你继续完成任务的复盘卡片。先指出自己卡在概念、步骤还是验收，再打开对应条目。</p></section><section class="section"><div class="card-grid">{guides}</div></section>'''
    return shell(content, "guide", "学习指南", body)


def render_foundation_kit(content: dict[str, Any]) -> str:
    kits = "".join(f'<article class="card soft" id="kit-{slug(kit["id"])}"><div class="label">{esc(kit["kind"])}</div><h3>{esc(kit["title"])}</h3><p>{text_block(kit["content"])}</p><ol>{"".join(f"<li>{text_block(item)}</li>" for item in kit["steps"])}</ol></article>' for kit in content["foundation_kit"])
    body = f'''<section class="hero"><div class="eyebrow">按课程动态生成的起步工具</div><h2>基础工具包</h2><p>工具包只包含完成本次实践所需的最小支撑：术语、操作顺序、检查表或 starter 入口。请边用边解释，不要把工具包当成脱离任务的百科。</p></section><section class="section"><div class="card-grid">{kits}</div></section>'''
    return shell(content, "kit", "基础工具包", body)


def render_teacher_guide(content: dict[str, Any]) -> str:
    teacher = content["teacher_guide"]
    timing = "".join(f'<li><strong>{esc(item["minutes"])} 分钟</strong>：{text_block(item["focus"])}</li>' for item in teacher["timing"])
    guidance = "".join(f'<article class="card"><h3>{esc(item["task_id"])}</h3><p><strong>观察：</strong>{text_block(item["look_for"])}</p><p><strong>卡住时追问：</strong>{text_block(item["ask_when_stuck"])}</p></article>' for item in teacher["task_guidance"])
    errors = "".join(f'<li><strong>{text_block(item["symptom"])}</strong>：{text_block(item["intervention"])}</li>' for item in teacher["common_errors"])
    pace_adjustments = "".join(f'<div class="card soft"><p>{text_block(item)}</p></div>' for item in teacher["pace_adjustments"])
    closing_checks = "".join(f"<li>{text_block(item)}</li>" for item in teacher["closing_checks"])
    body = f'''<section class="hero"><div class="eyebrow">课堂控制台</div><h2>教师指南</h2><p>{text_block(teacher["purpose"])}</p><div class="callout"><strong>理论—实践桥：</strong>{text_block(teacher["theory_bridge"])}</div></section><section class="section"><h2>建议节奏</h2><div class="card"><ol>{timing}</ol></div></section><section class="section"><h2>任务观察点</h2><div class="card-grid">{guidance}</div></section><section class="section"><h2>常见错误与干预</h2><div class="card warm"><ul>{errors}</ul></div></section><section class="section"><h2>按课堂状态调整</h2><div class="card-grid">{pace_adjustments}</div></section><section class="section"><h2>结束检查</h2><div class="card blue"><ul>{closing_checks}</ul></div></section>'''
    return shell(content, "teacher", "教师指南", body)


def _safe_asset_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative.strip():
        raise ValueError(f"starter asset path must be relative and stay within starter/: {relative}")
    return path


def generate(practice_path: Path, output_dir: Path, courseware_path: Path | None = None, *, replace: bool = False) -> dict[str, Any]:
    content = load_json(practice_path)
    courseware = load_courseware(courseware_path) if courseware_path else None
    contract_report = require_valid(content, courseware)
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not replace:
        raise FileExistsError(f"output directory is not empty; use --replace: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    starter_dir = output_dir / "starter"
    if starter_dir.exists() and replace:
        shutil.rmtree(starter_dir)
    starter_dir.mkdir(exist_ok=True)
    (output_dir / "practice-content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for asset in content["starter_assets"]:
        destination = starter_dir / _safe_asset_path(asset["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(asset["content"], encoding="utf-8", newline="\n")
    pages = {
        "student-task.html": render_student(content),
        "learning-center.html": render_learning_center(content),
        "study-guide.html": render_study_guide(content),
        "foundation-kit.html": render_foundation_kit(content),
        "teacher-guide.html": render_teacher_guide(content),
    }
    for name, page in pages.items():
        (output_dir / name).write_text(page, encoding="utf-8", newline="\n")
    # Keep the required manifest present while the output-level QA walks the
    # complete delivery directory; it is replaced with the final report below.
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
