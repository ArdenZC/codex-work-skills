"""Render Practice Class Content Contract 1.0 as a compact offline HTML package."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from practice_contract import LEVEL_LABELS, RENDERER_FAMILIES, load_courseware, load_json, validate_content


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def text_block(value: Any) -> str:
    return esc(value).replace("\n", "<br>")


def slug(value: Any) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "-", str(value or "")).strip("-")
    return cleaned or "item"


def interaction_family(kind: str) -> str:
    return RENDERER_FAMILIES.get(kind, "choice-family")


def _json_attr(value: Any) -> str:
    return esc(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _task_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _list(content.get("tasks")) if isinstance(item, dict) and item.get("id")}


def _knowledge_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _list(content.get("knowledge_links")) if isinstance(item, dict) and item.get("id")}


def _guide_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _list(content.get("study_guide")) if isinstance(item, dict) and item.get("id")}


def _kit_map(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _list(content.get("foundation_kit")) if isinstance(item, dict) and item.get("id")}


def _task_title(tasks: dict[str, dict[str, Any]], task_id: str) -> str:
    return str(tasks.get(task_id, {}).get("title", "相关实践任务"))


def _knowledge_titles(knowledge: dict[str, dict[str, Any]], ids: list[str]) -> str:
    titles = [str(knowledge[item].get("title")) for item in ids if item in knowledge]
    return "、".join(titles) if titles else "本节课已讲理论"


def _item_key(item: dict[str, Any]) -> Any:
    return item.get("id", item.get("task_id"))


def _humanize(content: dict[str, Any], value: Any) -> str:
    """Replace machine references in teacher-authored prose with human names."""

    text = str(value if value is not None else "")
    replacements: dict[str, str] = {}
    for field in ("tasks", "learning_center", "study_guide", "foundation_kit"):
        for item in _list(content.get(field)):
            if isinstance(item, dict) and item.get("id"):
                replacements[str(item["id"])] = str(item.get("title", item["id"]))
    for item in _list(content.get("knowledge_links")):
        if isinstance(item, dict) and item.get("id"):
            replacements[str(item["id"])] = str(item.get("title", item["id"]))
            for ref in _list(item.get("source_slide_ids")):
                replacements[str(ref)] = str(item.get("title", ref))
    for item in _list(content.get("starter_assets")):
        if isinstance(item, dict) and item.get("id"):
            replacements[str(item["id"])] = f"起点材料 {item.get('path', '')}".strip()
    for raw, human in sorted(replacements.items(), key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(raw, human)
    return text


def _nav_links(role: str, prefix: str) -> str:
    if role == "student":
        links = (("student-task.html", "任务路线"), ("learning-center.html", "学习中心"), ("study-guide.html", "学习指南"), ("foundation-kit.html", "基础补给"))
    else:
        links = (("teacher-guide.html", "课堂指导"), ("teacher-reference.html", "教师参考"), ("../student/student-task.html", "学生任务"))
    return "".join(f'<a class="nav-link" href="{esc(prefix + href)}">{esc(label)}</a>' for href, label in links)


def _context_tools(content: dict[str, Any]) -> str:
    context = content.get("course_context") if isinstance(content.get("course_context"), dict) else {}
    values: list[str] = []
    for key in ("language", "database_dialect", "platform", "software", "framework"):
        if context.get(key):
            values.append(str(context[key]))
    for item in _list(context.get("tools")):
        if str(item) not in values:
            values.append(str(item))
    return " · ".join(esc(item) for item in values) or "按课程资料选择工具"


def _modality_label(value: Any) -> str:
    labels = {
        "coding": "编程脚手架",
        "programming": "编程脚手架",
        "sql": "SQL 操作",
        "modeling": "建模工具",
        "tooling": "工具操作",
        "mixed": "混合实践",
    }
    return labels.get(str(value), "实践操作")


def _shell_css() -> str:
    return r"""+:root{--ink:#17333d;--muted:#5d7279;--line:#d7e3e5;--paper:#f6faf9;--panel:#fff;--accent:#147d78;--accent-soft:#e5f3f0;--warm:#fff4dc;--danger:#a84d35;--success:#176f55;--shadow:0 10px 28px rgba(23,51,61,.08)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}a{color:#126a72}button,select,input{font:inherit}button{cursor:pointer;color:var(--ink);background:#fff;border:1px solid #9bb8ba;border-radius:8px;padding:7px 11px}button:hover,a.nav-link:hover{background:var(--accent-soft)}button:disabled{cursor:not-allowed;opacity:.5}.site-header{background:#153d43;color:#fff;padding:13px 24px;display:flex;align-items:center;justify-content:space-between;gap:18px;min-height:76px}.site-brand{min-width:0}.site-brand .eyebrow,.module-kicker,.eyebrow{font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;color:#a9d6d2}.site-brand h1{font-size:1.08rem;margin:2px 0 0;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.site-brand p{margin:0;color:#d5e9e7;font-size:.88rem}.nav{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px}.nav-link{display:inline-flex;padding:6px 9px;border-radius:7px;color:#e8f5f3;text-decoration:none;font-size:.88rem}.nav-link:hover{color:var(--ink)}.page{max-width:1400px;margin:0 auto;padding:18px 24px 52px}.module-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:12px 0 14px;border-bottom:1px solid var(--line)}.module-header h2{margin:2px 0 3px;font-size:1.62rem;line-height:1.25}.module-header p{margin:0;color:var(--muted);max-width:850px}.compact-meta{color:var(--muted);font-size:.88rem;padding:8px 0;text-align:right;max-width:360px}.module-layout{display:grid;grid-template-columns:minmax(205px,250px) minmax(0,1fr);gap:20px;align-items:start;margin-top:16px}.pane-nav{position:sticky;top:12px;background:rgba(255,255,255,.78);border:1px solid var(--line);border-radius:12px;padding:10px;box-shadow:var(--shadow);max-height:calc(100vh - 24px);overflow:auto}.pane-nav strong{display:block;font-size:.88rem;margin:2px 7px 7px}.pane-nav a{display:block;padding:8px 9px;border-radius:8px;color:var(--ink);text-decoration:none;line-height:1.35}.pane-nav a:hover,.pane-nav a.is-active{background:var(--accent-soft);color:#0d605e}.pane-nav .nav-meta{display:block;color:var(--muted);font-size:.78rem;margin-top:2px}.pane-main{min-width:0;max-width:1040px}.pane{display:none}.pane.is-active{display:block}.pane-card,.card,.interaction{background:var(--panel);border:1px solid var(--line);border-radius:13px;box-shadow:var(--shadow)}.pane-card{padding:19px 21px}.pane-title-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.pane-title-row h3{margin:0;font-size:1.28rem;line-height:1.35}.pane-lead{color:var(--muted);margin:8px 0 12px}.pane-meta{color:var(--muted);font-size:.86rem;margin:4px 0 14px}.level{display:inline-flex;align-items:center;padding:3px 9px;border-radius:999px;font-size:.79rem;white-space:nowrap}.level.core{background:#dff2ea;color:#17684f}.level.optional{background:#edf1ff;color:#4e5c9a}.level.challenge{background:#fff0cf;color:#8a5a14}.route-overview{background:linear-gradient(120deg,#e9f5f1,#fdf8ec);border:1px solid #cfe3dd;border-radius:13px;padding:14px 17px;margin-top:16px}.route-overview h3{margin:0 0 3px}.route-overview p{margin:0;color:var(--muted)}.route-grid,.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:12px}.route-card,.summary-card{background:#ffffffbf;border:1px solid #d6e6e1;border-radius:10px;padding:10px}.route-card strong,.summary-card strong{display:block}.route-card span,.summary-card span{display:block;color:var(--muted);font-size:.84rem}.section-label{font-size:.8rem;letter-spacing:.04em;color:#397078;text-transform:uppercase;margin:19px 0 6px}.task-steps,.clean-list{margin:8px 0 0;padding-left:22px}.task-steps li,.clean-list li{margin:7px 0}.scaffold,.callout{background:var(--accent-soft);border:1px solid #c6e2dc;border-radius:10px;padding:12px 14px}.acceptance{background:#f7faf2;border:1px solid #dde8ca;border-radius:10px;padding:8px 13px}.related-links{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.related-links a{display:inline-flex;align-items:center;padding:6px 9px;border:1px solid #b8d5d1;border-radius:8px;text-decoration:none;background:#fbfffe}.pane-footer{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin-top:14px}.pane-footer .footer-links{display:flex;flex-wrap:wrap;gap:7px}.small{font-size:.86rem;color:var(--muted)}.chip-row{display:flex;flex-wrap:wrap;gap:7px}.chip{display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;background:#f1f6f5;border:1px solid #d5e4e1;color:#48656b;font-size:.82rem}.starter-box{margin-top:10px;border:1px dashed #abc9c4;border-radius:9px;padding:8px 10px;background:#fbfffe}.starter-box summary{cursor:pointer;color:#116b68}.starter-code,.reference-answer{display:block;overflow:auto;background:#172d35;color:#e8f3ef;border-radius:9px;padding:13px;white-space:pre-wrap;word-break:break-word;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.reference-pane .pane-card{max-width:1080px}.reference-answer{min-height:150px}.interaction{padding:16px 17px;margin-top:14px}.interaction h4{margin:0 0 5px}.interaction .prompt{margin:0 0 12px;font-weight:650}.choice-options{display:grid;gap:8px}.choice-option{text-align:start;width:100%;background:#fbfdfd}.choice-option.is-selected{outline:2px solid #64aaa2;background:var(--accent-soft)}.feedback{min-height:28px;margin-top:10px;padding:7px 9px;border-radius:8px;background:#f3f8f7;color:var(--success)}.feedback.wrong{background:#fff0ea;color:var(--danger)}.feedback:empty{display:none}.step-card{padding:12px 13px;background:#f7fbfa;border:1px solid var(--line);border-radius:9px;min-height:86px}.step-card[hidden],.classify-feedback[hidden],.hint-text[hidden],.terminal-note[hidden]{display:none}.step-card h5{margin:0 0 3px;font-size:1rem}.interaction-controls{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.step-status,.multi-status,.sim-status{font-size:.84rem;color:var(--muted);margin-inline-start:auto;align-self:center}.classify-list{display:grid;gap:9px}.classify-item{padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:#fbfdfd}.classify-item label{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.classify-item select{min-width:170px;border:1px solid #a9c4c2;border-radius:7px;padding:5px;background:#fff}.classify-feedback{display:block;color:var(--muted);margin-top:5px;font-size:.86rem}.hint-text{display:block;color:#79552a;background:var(--warm);border-radius:7px;padding:6px 8px;margin-top:6px}.reorder-list{list-style:none;padding:0;margin:12px 0;display:grid;gap:7px}.reorder-item{display:flex;align-items:center;justify-content:space-between;gap:9px;padding:9px 10px;background:#fbfdfd;border:1px solid var(--line);border-radius:9px}.reorder-controls{white-space:nowrap}.reorder-controls button{padding:4px 7px;margin-inline-start:4px}.state-context,.state-group{padding:9px 11px;border-radius:9px;background:#f6faf9;border:1px solid var(--line);margin-top:9px}.state-group h5{margin:0 0 5px;font-size:.9rem}.state-values{display:flex;flex-wrap:wrap;gap:7px}.state-value{display:inline-flex;gap:4px;padding:4px 7px;background:#fff;border:1px solid #dbe8e6;border-radius:7px}.state-inputs{display:flex;flex-wrap:wrap;gap:9px}.state-inputs label{display:flex;align-items:center;gap:5px}.state-inputs input{width:115px;padding:6px;border:1px solid #a9c4c2;border-radius:7px}.terminal-note{margin-top:9px;padding:8px 10px;border-radius:8px;background:#e8f5ec;color:#23624d}.multi-question{padding:10px 0}.multi-question[hidden]{display:none}.multi-question p{margin:0 0 9px;font-weight:600}.footer{max-width:1400px;margin:0 auto;padding:0 24px 28px;color:var(--muted);font-size:.82rem}.teacher-note{background:#fff8e7;border:1px solid #ecd9a6;border-radius:10px;padding:11px 13px}.timing-list{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0}.timing-item{padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:#fff}.timing-item strong{display:block;color:var(--accent)}
@media(max-width:820px){.site-header{display:block;padding:12px 16px}.nav{justify-content:flex-start;margin-top:7px}.page{padding:14px 15px 42px}.module-header{display:block}.compact-meta{text-align:start;padding-top:6px}.module-layout{grid-template-columns:1fr;gap:12px}.pane-nav{position:static;max-height:none;display:flex;flex-wrap:wrap;gap:4px;align-items:center}.pane-nav strong{width:100%;margin-bottom:1px}.pane-nav a{flex:1 1 180px}.pane-card{padding:15px}.pane-title-row{display:block}.level{margin-top:7px}.footer{padding:0 15px 24px}}
""".lstrip("+") + r''' .site-header{padding:8px 24px;min-height:64px}.site-brand .eyebrow{line-height:1.2}.site-brand h1{line-height:1.15}.site-brand p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.2}[data-page-module="learning-center"] .module-header{padding:4px 0 5px}[data-page-module="learning-center"] .module-header h2{font-size:1.38rem;line-height:1.15}[data-page-module="learning-center"] .module-header p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.35}[data-page-module="learning-center"] .compact-meta{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:4px 0;line-height:1.35}[data-page-module="learning-center"] .pane-card{padding:14px 16px}[data-page-module="learning-center"] .pane-title-row h3{font-size:1.12rem}[data-page-module="learning-center"] .pane-lead{margin:4px 0 7px}[data-page-module="learning-center"] .interaction{margin-top:9px;padding:12px 13px}@media(max-width:820px){.site-header{padding:10px 16px}}'''


def _shell_script() -> str:
    return r'''
const neutralSuccess = "已完成一次验证，可以把这一步带回任务。";
const neutralRetry = "还需要再核对一次输入与题面。";

function activatePane(module, requested, writeHash = false) {
  const panes = [...module.querySelectorAll("[data-pane]")];
  if (!panes.length) return;
  const wanted = requested && panes.some((pane) => pane.id === requested) ? requested : panes[0].id;
  panes.forEach((pane) => { const active = pane.id === wanted; pane.classList.toggle("is-active", active); pane.hidden = !active; pane.setAttribute("aria-hidden", String(!active)); });
  module.querySelectorAll("[data-pane-target]").forEach((link) => link.classList.toggle("is-active", link.getAttribute("data-pane-target") === `#${wanted}`));
  if (writeHash && window.location.hash !== `#${wanted}`) history.replaceState(null, "", `#${wanted}`);
}

document.querySelectorAll("[data-pane-module]").forEach((module) => {
  activatePane(module, decodeURIComponent(window.location.hash.slice(1)), false);
  window.addEventListener("hashchange", () => activatePane(module, decodeURIComponent(window.location.hash.slice(1)), false));
  module.addEventListener("click", (event) => { const link = event.target.closest("[data-pane-target]"); if (!link || !link.getAttribute("data-pane-target")?.startsWith("#")) return; event.preventDefault(); activatePane(module, link.getAttribute("data-pane-target").slice(1), true); });
});

document.querySelectorAll("[data-choice-root]").forEach((box) => {
  const options = [...box.querySelectorAll("[data-choice]")]; let selected = null;
  options.forEach((option, index) => option.addEventListener("click", () => { selected = index; options.forEach((item) => item.classList.toggle("is-selected", item === option)); }));
  box.querySelector("[data-check]")?.addEventListener("click", () => { const feedback = box.querySelector(".feedback"); if (selected === null) { feedback.textContent = "先选择一个答案，再检查理由。"; feedback.classList.add("wrong"); return; } const option = options[selected]; const correct = selected === Number(box.dataset.answerIndex); feedback.textContent = option.dataset.feedback || (correct ? neutralSuccess : neutralRetry); feedback.classList.toggle("wrong", !correct); });
});

document.querySelectorAll("[data-step-root]").forEach((box) => {
  const cards = [...box.querySelectorAll("[data-step]")]; let index = 0; const status = box.querySelector("[data-step-status]");
  const show = () => { cards.forEach((card, cardIndex) => { card.hidden = cardIndex !== index; }); if (status) status.textContent = `第 ${index + 1} / ${cards.length} 步`; const before = box.querySelector("[data-step-prev]"); const after = box.querySelector("[data-step-next]"); if (before) before.disabled = index === 0; if (after) after.disabled = index === cards.length - 1; };
  box.querySelector("[data-step-prev]")?.addEventListener("click", () => { index = Math.max(0, index - 1); show(); }); box.querySelector("[data-step-next]")?.addEventListener("click", () => { index = Math.min(cards.length - 1, index + 1); show(); }); box.querySelector("[data-step-reset]")?.addEventListener("click", () => { index = 0; show(); }); show();
});

document.querySelectorAll("[data-classify-root]").forEach((box) => {
  const items = [...box.querySelectorAll("[data-classify-item]")];
  box.querySelector("[data-check]")?.addEventListener("click", () => { let complete = true; let allCorrect = true; items.forEach((item) => { const select = item.querySelector("select"); const message = item.querySelector("[data-classify-feedback]"); const answered = Boolean(select?.value); const correct = answered && select.value === item.dataset.answer; complete = complete && answered; allCorrect = allCorrect && correct; if (message) { message.textContent = item.dataset.feedback || (correct ? neutralSuccess : neutralRetry); message.hidden = false; } item.classList.toggle("is-wrong", answered && !correct); }); const feedback = box.querySelector(".feedback"); if (feedback) { feedback.textContent = complete && allCorrect ? (box.dataset.successFeedback || neutralSuccess) : (box.dataset.retryFeedback || "请补全分类，并根据反馈修正错项。"); feedback.classList.toggle("wrong", !(complete && allCorrect)); } });
  box.querySelectorAll("[data-hint-button]").forEach((button) => button.addEventListener("click", () => { const hint = button.parentElement?.querySelector("[data-hint-text]"); if (hint) hint.hidden = !hint.hidden; }));
});

document.querySelectorAll("[data-reorder-root]").forEach((box) => {
  const list = box.querySelector("[data-reorder-list]"); const initial = JSON.parse(box.dataset.initialOrder || "[]"); const expected = JSON.parse(box.dataset.correctOrder || "[]"); const items = () => [...list.querySelectorAll("[data-reorder-item]")]; const refresh = () => items().forEach((item, index) => { const position = item.querySelector("[data-position]"); if (position) position.textContent = String(index + 1); });
  box.querySelectorAll("[data-move-up]").forEach((button) => button.addEventListener("click", () => { const item = button.closest("[data-reorder-item]"); const before = item?.previousElementSibling; if (before) list.insertBefore(item, before); refresh(); })); box.querySelectorAll("[data-move-down]").forEach((button) => button.addEventListener("click", () => { const item = button.closest("[data-reorder-item]"); const after = item?.nextElementSibling; if (after) list.insertBefore(after, item); refresh(); }));
  box.querySelector("[data-reset]")?.addEventListener("click", () => { const map = new Map(items().map((item) => [item.dataset.itemId, item])); initial.forEach((id) => map.get(id) && list.appendChild(map.get(id))); refresh(); const feedback = box.querySelector(".feedback"); if (feedback) feedback.textContent = "已恢复起始顺序，请先观察再排列。"; });
  box.querySelector("[data-check]")?.addEventListener("click", () => { const actual = items().map((item) => item.dataset.itemId); const sameLength = actual.length === expected.length; const noDuplicates = new Set(actual).size === actual.length; const known = actual.every((id) => expected.includes(id)); const correct = sameLength && noDuplicates && known && actual.every((id, index) => id === expected[index]); const feedback = box.querySelector(".feedback"); if (feedback) { feedback.textContent = correct ? (box.dataset.successFeedback || neutralSuccess) : (box.dataset.retryFeedback || "顺序还不对，请核对每一步的前置条件。"); feedback.classList.toggle("wrong", !correct); } }); refresh();
});

document.querySelectorAll("[data-state-root]").forEach((box) => {
  const rounds = JSON.parse(box.dataset.rounds || "[]"); const fields = JSON.parse(box.dataset.stateFields || "[]"); let current = 0; const fieldMap = new Map(fields.map((field) => [field.id, field])); const labelFor = (id) => fieldMap.get(id)?.label || "过程字段"; const valueText = (value) => typeof value === "object" ? JSON.stringify(value) : String(value);
  const makeGiven = (container, values) => { container.innerHTML = ""; Object.entries(values || {}).forEach(([id, value]) => { const span = document.createElement("span"); span.className = "state-value"; span.innerHTML = `<b>${labelFor(id)}</b> ${valueText(value)}`; container.appendChild(span); }); };
  const makeInputs = (container, values, prefix) => { container.innerHTML = ""; Object.entries(values || {}).forEach(([id, value]) => { const label = document.createElement("label"); label.textContent = `${labelFor(id)} `; const input = document.createElement("input"); input.type = fieldMap.get(id)?.input_type || (typeof value === "number" ? "number" : "text"); input.value = ""; input.dataset.stateInput = prefix; input.dataset.field = id; input.dataset.expectedValue = JSON.stringify(value); label.appendChild(input); container.appendChild(label); }); };
  const render = () => { const round = rounds[current]; makeGiven(box.querySelector("[data-state-given]"), round.given); makeInputs(box.querySelector("[data-state-expected]"), round.expected, "current"); const next = box.querySelector("[data-state-next]"); const continuing = round.status === "continue"; if (next) { next.hidden = !continuing; if (continuing) makeInputs(next.querySelector("[data-state-next-inputs]"), round.next_expected, "next"); } const terminal = box.querySelector("[data-terminal-note]"); if (terminal) terminal.hidden = true; const feedback = box.querySelector(".feedback"); if (feedback) { feedback.textContent = ""; feedback.classList.remove("wrong"); } const observation = box.querySelector("[data-state-observation]"); if (observation) { observation.hidden = true; observation.textContent = round.observation || ""; } const nextButton = box.querySelector("[data-next-round]"); if (nextButton) { nextButton.hidden = !continuing; nextButton.disabled = true; } const status = box.querySelector("[data-sim-status]"); if (status) status.textContent = `第 ${current + 1} / ${rounds.length} 轮`; };
  const same = (input) => { if (!input || input.value.trim() === "") return false; const expected = JSON.parse(input.dataset.expectedValue); if (typeof expected === "number") return Number(input.value) === expected; return input.value.trim() === String(expected); };
  box.querySelector("[data-check]")?.addEventListener("click", () => { const round = rounds[current]; const inputs = [...box.querySelectorAll("[data-state-input]")]; const correct = inputs.length > 0 && inputs.every(same); const feedback = box.querySelector(".feedback"); if (feedback) { feedback.textContent = correct ? (round.feedback || neutralSuccess) : (box.dataset.retryFeedback || neutralRetry); feedback.classList.toggle("wrong", !correct); } const observation = box.querySelector("[data-state-observation]"); if (observation && correct) observation.hidden = false; const nextButton = box.querySelector("[data-next-round]"); if (nextButton && correct) nextButton.disabled = false; const terminal = box.querySelector("[data-terminal-note]"); if (terminal && correct && round.status !== "continue") { terminal.hidden = false; terminal.textContent = round.terminal_label || "已到达终止状态，当前过程结束。"; } });
  box.querySelector("[data-next-round]")?.addEventListener("click", () => { if (current < rounds.length - 1) { current += 1; render(); } }); box.querySelector("[data-reset]")?.addEventListener("click", () => { current = 0; render(); }); render();
});

document.querySelectorAll("[data-multi-root]").forEach((box) => {
  const questions = JSON.parse(box.dataset.questions || "[]"); let index = 0; let selected = null; const panes = [...box.querySelectorAll("[data-question]")]; const show = () => { selected = null; panes.forEach((pane, paneIndex) => { pane.hidden = paneIndex !== index; pane.querySelectorAll("[data-choice]").forEach((button) => button.classList.remove("is-selected")); const feedback = pane.querySelector(".feedback"); if (feedback) feedback.textContent = ""; }); const status = box.querySelector("[data-multi-status]"); if (status) status.textContent = `问题 ${index + 1} / ${questions.length}`; const next = box.querySelector("[data-multi-next]"); if (next) next.disabled = true; };
  panes.forEach((pane) => pane.querySelectorAll("[data-choice]").forEach((button, optionIndex) => button.addEventListener("click", () => { selected = optionIndex; pane.querySelectorAll("[data-choice]").forEach((item) => item.classList.toggle("is-selected", item === button)); }))); box.querySelector("[data-multi-check]")?.addEventListener("click", () => { const pane = panes[index]; const feedback = pane.querySelector(".feedback"); if (selected === null) { feedback.textContent = "先选择一个答案。"; feedback.classList.add("wrong"); return; } const option = questions[index].options[selected]; const correct = selected === Number(questions[index].answer_index); feedback.textContent = option.feedback || (correct ? neutralSuccess : neutralRetry); feedback.classList.toggle("wrong", !correct); box.querySelector("[data-multi-next]").disabled = false; }); box.querySelector("[data-multi-next]")?.addEventListener("click", () => { if (index < panes.length - 1) { index += 1; show(); } else { const status = box.querySelector("[data-multi-status]"); if (status) status.textContent = "本组问题已完成"; box.querySelector("[data-multi-next]").disabled = true; } }); show();
});
'''


def shell(content: dict[str, Any], role: str, module: str, title: str, subtitle: str, body: str, *, prefix: str = "") -> str:
    role_label = "学生实践空间" if role == "student" else "教师课堂空间"
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(content.get("course_title"))} · {esc(title)}</title><style>{_shell_css()}</style></head><body>
<header class="site-header"><div class="site-brand"><div class="eyebrow">{esc(role_label)}</div><h1>{esc(content.get("course_title"))}</h1><p>{esc(content.get("practice_title"))}</p></div><nav class="nav" aria-label="模块导航">{_nav_links(role, prefix)}</nav></header>
<main class="page" data-role="{esc(role)}" data-page-module="{esc(module)}" data-pane-module><section class="module-header" id="module-top"><div><div class="module-kicker">{esc(role_label)} · {esc(title)}</div><h2>{esc(title)}</h2><p>{text_block(subtitle)}</p></div><div class="compact-meta">可用工具：{_context_tools(content)}</div></section>{body}</main>
<footer class="footer">内容来自已讲理论与实践合同；本页的互动服务具体学习目标，完成后请回到任务路线继续。</footer><script>{_shell_script()}</script></body></html>'''


def _module_nav(items: list[dict[str, Any]], id_prefix: str, *, meta: str = "") -> str:
    links = []
    for item in items:
        pane_id = f"{id_prefix}{slug(_item_key(item))}"
        links.append(f'<a href="#{esc(pane_id)}" data-pane-target="#{esc(pane_id)}">{esc(item.get("title"))}<span class="nav-meta">{esc(meta or item.get("purpose", ""))}</span></a>')
    return "".join(links)


def _pane_footer(items: list[dict[str, Any]], index: int, pane_prefix: str, *, route_label: str = "返回目录") -> str:
    previous = items[index - 1] if index > 0 else None
    following = items[index + 1] if index + 1 < len(items) else None
    previous_html = f'<a href="#{esc(pane_prefix + slug(_item_key(previous)))}" data-pane-target="#{esc(pane_prefix + slug(_item_key(previous)))}">← 上一项</a>' if previous else ""
    following_html = f'<a href="#{esc(pane_prefix + slug(_item_key(following)))}" data-pane-target="#{esc(pane_prefix + slug(_item_key(following)))}">下一项 →</a>' if following else ""
    return f'<div class="pane-footer"><div class="footer-links"><a href="#module-top">{esc(route_label)}</a>{previous_html}{following_html}</div></div>'


def _starter_html(assets: dict[str, dict[str, Any]], ids: list[str]) -> str:
    blocks = []
    for asset_id in ids:
        asset = assets.get(asset_id)
        if asset:
            blocks.append(f'<details class="starter-box"><summary>打开起点材料：{esc(asset.get("path"))}</summary><pre class="starter-code">{esc(asset.get("content"))}</pre></details>')
    return "".join(blocks)


def _task_links(content: dict[str, Any], task: dict[str, Any]) -> str:
    guides, kits = _guide_map(content), _kit_map(content)
    task_id = task.get("id")
    centers = [center for center in _list(content.get("learning_center")) if isinstance(center, dict) and task_id in _list(center.get("task_ids"))]
    links: list[str] = [f'<a href="learning-center.html#lab-{esc(slug(center.get("id")))}">学习实验：{esc(center.get("title"))}</a>' for center in centers]
    for ref in task.get("help_refs", []):
        if ref in guides: links.append(f'<a href="study-guide.html#guide-{esc(slug(ref))}">学习资料：{esc(guides[ref].get("title"))}</a>')
        if ref in kits: links.append(f'<a href="foundation-kit.html#kit-{esc(slug(ref))}">基础补给：{esc(kits[ref].get("title"))}</a>')
    if not any("study-guide.html#" in link for link in links) and guides:
        guide = next((item for item in guides.values() if task_id in _list(item.get("task_ids"))), next(iter(guides.values())))
        links.append(f'<a href="study-guide.html#guide-{esc(slug(guide.get("id")))}">学习资料：{esc(guide.get("title"))}</a>')
    if not any("foundation-kit.html#" in link for link in links) and kits:
        kit = next((item for item in kits.values() if task_id in _list(item.get("task_ids"))), next(iter(kits.values())))
        links.append(f'<a href="foundation-kit.html#kit-{esc(slug(kit.get("id")))}">基础补给：{esc(kit.get("title"))}</a>')
    return "".join(dict.fromkeys(links))


def _task_pane(content: dict[str, Any], task: dict[str, Any], assets: dict[str, dict[str, Any]], knowledge: dict[str, dict[str, Any]], index: int, tasks: list[dict[str, Any]]) -> str:
    source_refs = " ".join(str(item) for item in task.get("source_slide_ids", []))
    step_html = []
    for step in _list(task.get("steps")):
        check = f'<span class="small"><br>检查：{text_block(step.get("check"))}</span>' if step.get("check") else ""
        step_html.append(f'<li><strong>{esc(step.get("title"))}</strong>：{text_block(step.get("instruction"))}{check}</li>')
    steps = "".join(step_html)
    acceptance = "".join(f"<li>{text_block(item)}</li>" for item in _list(task.get("acceptance")))
    starter = _starter_html(assets, _list(task.get("starter_asset_ids")))
    minutes = f'<span class="chip">约 {esc(task.get("estimated_minutes"))} 分钟</span>' if task.get("estimated_minutes") else ""
    return f'''<article class="pane{' is-active' if index == 0 else ''}" id="task-{esc(slug(task.get("id")))}" data-pane data-task-id="{esc(task.get("id"))}" data-source-slide-ids="{esc(source_refs)}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(task.get("title"))}</h3><p class="pane-lead">{text_block(task.get("overview"))}</p></div><span class="level {esc(task.get("level"))}">{esc(LEVEL_LABELS.get(task.get("level"), task.get("level")))}</span></div><div class="chip-row"><span class="chip">理论：{esc(_knowledge_titles(knowledge, _list(task.get("knowledge_link_ids"))))}</span>{minutes}<span class="chip">{esc(_modality_label(task.get("modality")))}</span></div><div class="section-label">本次要留下的结果</div><div class="scaffold">{text_block(task.get("scaffold"))}</div><div class="section-label">完成步骤</div><ol class="task-steps">{steps}</ol><div class="section-label">验收清单</div><div class="acceptance"><ul class="clean-list">{acceptance}</ul></div>{f'<div class="section-label">起点材料</div>{starter}' if starter else ''}<div class="section-label">卡住时的自助路径</div><p class="small">先打开一个相关实验或资料，完成一小步，再回到本任务。</p><div class="related-links">{_task_links(content, task)}</div>{_pane_footer(tasks, index, "task-")}</section></article>'''


def render_student_task(content: dict[str, Any]) -> str:
    tasks = [item for item in _list(content.get("tasks")) if isinstance(item, dict)]
    knowledge = _knowledge_map(content)
    assets = {item.get("id"): item for item in _list(content.get("starter_assets")) if isinstance(item, dict) and item.get("id")}
    cards = []
    for level in ("core", "optional", "challenge"):
        selected = [task for task in tasks if task.get("level") == level]
        if selected: cards.append(f'<div class="route-card"><strong>{esc(LEVEL_LABELS[level])}</strong><span>{len(selected)} 个任务 · {esc("、".join(task.get("title", "") for task in selected[:2]))}</span></div>')
    body = f'<section class="route-overview" id="task-route"><h3>今天的实践路线</h3><p>先完成核心必做，再按需要打开有余力或提高挑战。每个任务都能回到对应的理论、实验和自助资料。</p><div class="route-grid">{"".join(cards)}</div></section><div class="module-layout"><aside class="pane-nav" aria-label="任务导航"><strong>当前任务</strong>{_module_nav(tasks, "task-", meta="按路线完成")}</aside><section class="pane-main">{"".join(_task_pane(content, task, assets, knowledge, index, tasks) for index, task in enumerate(tasks))}</section></div>'
    return shell(content, "student", "student-task", "任务路线", "按层级选择任务，当前只保留一个任务工作区，pane 内可回到理论、实验和自助资料。", body)


def _render_choice(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    options = _list(interaction.get("options")); answer = interaction.get("answer_index")
    if not isinstance(answer, int): answer = next((index for index, option in enumerate(options) if isinstance(option, dict) and option.get("correct") is True), 0)
    buttons = "".join(f'<button type="button" class="choice-option" data-choice data-feedback="{esc(option.get("feedback"))}">{esc(option.get("label"))}</button>' for option in options if isinstance(option, dict))
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="choice-family" data-interaction-id="{esc(interaction_id)}" data-choice-root data-answer-index="{answer}" {base}><h4>先作出判断</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p><div class="choice-options">{buttons}</div><div class="interaction-controls"><button type="button" data-check>检查判断</button></div><div class="feedback" aria-live="polite"></div></div>'


def _render_step(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    cards = "".join(f'<div class="step-card" data-step hidden><h5>{esc(step.get("title"))}</h5><div>{text_block(step.get("text"))}</div></div>' for step in _list(interaction.get("steps")) if isinstance(step, dict))
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="step-family" data-interaction-id="{esc(interaction_id)}" data-step-root {base}><h4>按步骤推进</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p>{cards}<div class="interaction-controls"><button type="button" data-step-prev>上一步</button><button type="button" data-step-next>下一步</button><button type="button" data-step-reset>重置</button><span class="step-status" data-step-status></span></div></div>'


def _render_classify(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    categories = _list(interaction.get("categories")); options = '<option value="">请选择</option>' + "".join(f'<option value="{esc(item)}">{esc(item)}</option>' for item in categories); items = []
    for item in _list(interaction.get("items")):
        hint = f'<button type="button" data-hint-button>查看提示</button><span class="hint-text" data-hint-text hidden>{text_block(item.get("hint"))}</span>' if item.get("hint") else ""
        items.append(f'<div class="classify-item" data-classify-item data-answer="{esc(item.get("answer"))}" data-feedback="{esc(item.get("feedback"))}"><label>{esc(item.get("label"))}<select aria-label="为 {esc(item.get("label"))} 选择分类">{options}</select></label><small class="classify-feedback" data-classify-feedback hidden></small>{hint}</div>')
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="classify-family" data-interaction-id="{esc(interaction_id)}" data-classify-root data-success-feedback="{esc(interaction.get("success_feedback", "分类完成，可以回到任务解释理由。"))}" data-retry-feedback="{esc(interaction.get("retry_feedback", "请根据逐项反馈修正分类。"))}" {base}><h4>逐项分类</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p><div class="classify-list">{"".join(items)}</div><div class="interaction-controls"><button type="button" data-check>检查分类</button></div><div class="feedback" aria-live="polite"></div></div>'


def _render_reorder(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    items = [item for item in _list(interaction.get("items")) if isinstance(item, dict)]; initial = [item.get("id") for item in items]; order = _list(interaction.get("correct_order"))
    rows = "".join(f'<li class="reorder-item" data-reorder-item data-item-id="{esc(item.get("id"))}"><span><span data-position>{index + 1}</span>．{esc(item.get("label"))}</span><span class="reorder-controls"><button type="button" data-move-up aria-label="上移此项">↑</button><button type="button" data-move-down aria-label="下移此项">↓</button></span></li>' for index, item in enumerate(items))
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="reorder-family" data-interaction-id="{esc(interaction_id)}" data-reorder-root data-initial-order="{_json_attr(initial)}" data-correct-order="{_json_attr(order)}" data-success-feedback="{esc(interaction.get("success_feedback", "顺序正确，可以把理由带回实践任务。"))}" data-retry-feedback="{esc(interaction.get("retry_feedback", "顺序还不对，请逐项核对前置条件。"))}" {base}><h4>排列操作顺序</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p><ol class="reorder-list" data-reorder-list>{rows}</ol><div class="interaction-controls"><button type="button" data-check>检查顺序</button><button type="button" data-reset>恢复起始顺序</button></div><div class="feedback" aria-live="polite"></div></div>'


def _render_state(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    state = interaction.get("state") if isinstance(interaction.get("state"), dict) else {}
    target = f'；{esc(state.get("target_label"))}：{esc(state.get("target"))}' if state.get("target") is not None else ""
    context = f'<div class="state-context"><b>{esc(state.get("context_label", "背景状态"))}</b>：{text_block(state.get("context", "请阅读题面给出的状态。"))}{target}</div>'
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="state-simulator-family" data-interaction-id="{esc(interaction_id)}" data-state-root data-rounds="{_json_attr(_list(interaction.get("rounds")))}" data-state-fields="{_json_attr(_list(interaction.get("state_fields")))}" data-retry-feedback="{esc(interaction.get("retry_feedback", "请核对给定状态、未知字段和下一状态。"))}" {base}><h4>状态推演</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p>{context}<div class="state-group"><h5>题面给定</h5><div class="state-values" data-state-given></div></div><div class="state-group"><h5>本轮请你填写</h5><div class="state-inputs" data-state-expected></div></div><div class="state-group" data-state-next><h5>下一状态请你推导</h5><div class="state-inputs" data-state-next-inputs></div></div><div class="interaction-controls"><button type="button" data-check>检查当前状态</button><button type="button" data-next-round hidden disabled>进入下一轮</button><button type="button" data-reset>从第一轮开始</button><span class="sim-status" data-sim-status></span></div><div class="state-context" data-state-observation hidden></div><div class="terminal-note" data-terminal-note hidden></div><div class="feedback" aria-live="polite"></div></div>'


def _render_multi(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    questions = [item for item in _list(interaction.get("questions")) if isinstance(item, dict)]; panes = []
    for question in questions:
        options = "".join(f'<button type="button" class="choice-option" data-choice data-feedback="{esc(option.get("feedback"))}">{esc(option.get("label"))}</button>' for option in _list(question.get("options")) if isinstance(option, dict))
        panes.append(f'<div class="multi-question" data-question hidden><p>{text_block(question.get("prompt"))}</p><div class="choice-options">{options}</div><div class="feedback" aria-live="polite"></div></div>')
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="multi-question-family" data-interaction-id="{esc(interaction_id)}" data-multi-root data-questions="{_json_attr(questions)}" {base}><h4>逐题核对</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p>{"".join(panes)}<div class="interaction-controls"><button type="button" data-multi-check>检查本题</button><button type="button" data-multi-next disabled>下一题</button><span class="multi-status" data-multi-status></span></div></div>'


def render_interaction(center: dict[str, Any]) -> str:
    interaction = center.get("interaction", {}) if isinstance(center.get("interaction"), dict) else {}; kind = str(interaction.get("type", "choice")); family = interaction_family(kind); interaction_id = str(center.get("id", "interaction")); minutes = interaction.get("estimated_minutes"); time_attr = f' data-estimated-minutes="{esc(minutes)}"' if isinstance(minutes, int) and not isinstance(minutes, bool) else ""; base = f'data-center-id="{esc(interaction_id)}"{time_attr}'
    if family == "choice-family": return _render_choice(interaction, base, interaction_id)
    if family == "step-family": return _render_step(interaction, base, interaction_id)
    if family == "classify-family": return _render_classify(interaction, base, interaction_id)
    if family == "reorder-family": return _render_reorder(interaction, base, interaction_id)
    if family == "state-simulator-family": return _render_state(interaction, base, interaction_id)
    return _render_multi(interaction, base, interaction_id)


def _center_pane(center: dict[str, Any], index: int, centers: list[dict[str, Any]], knowledge: dict[str, dict[str, Any]], tasks: dict[str, dict[str, Any]]) -> str:
    interaction = center.get("interaction", {}) if isinstance(center.get("interaction"), dict) else {}; minutes = f'<span class="chip">互动约 {esc(interaction.get("estimated_minutes"))} 分钟</span>' if isinstance(interaction.get("estimated_minutes"), int) else ""; task_titles = "、".join(_task_title(tasks, item) for item in _list(center.get("task_ids")))
    return f'<article class="pane{' is-active' if index == 0 else ''}" id="lab-{esc(slug(center.get("id")))}" data-pane data-center-id="{esc(center.get("id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(center.get("title"))}</h3><p class="pane-lead">{text_block(center.get("purpose"))}</p></div>{minutes}</div><div class="chip-row"><span class="chip">理论：{esc(_knowledge_titles(knowledge, _list(center.get("knowledge_link_ids"))))}</span><span class="chip">服务任务：{esc(task_titles)}</span></div>{render_interaction(center)}{_pane_footer(centers, index, "lab-", route_label="返回实验目录")}</section></article>'


def render_learning_center(content: dict[str, Any]) -> str:
    centers = [item for item in _list(content.get("learning_center")) if isinstance(item, dict)]; body = f'<div class="module-layout"><aside class="pane-nav" aria-label="实验导航"><strong>选择一个实验</strong>{_module_nav(centers, "lab-")}</aside><section class="pane-main">{"".join(_center_pane(center, index, centers, _knowledge_map(content), _task_map(content)) for index, center in enumerate(centers))}</section></div>'
    return shell(content, "student", "learning-center", "学习中心", "每个实验只保留一个操作焦点；先做判断或填写，再把反馈带回任务。", body)


def _guide_pane(guide: dict[str, Any], index: int, guides: list[dict[str, Any]], knowledge: dict[str, dict[str, Any]], tasks: dict[str, dict[str, Any]]) -> str:
    task_titles = "、".join(_task_title(tasks, item) for item in _list(guide.get("task_ids"))); quick = "".join(f"<li>{text_block(item)}</li>" for item in _list(guide.get("quick_reference"))); errors = "".join(f"<li>{text_block(item)}</li>" for item in _list(guide.get("common_errors"))); checks = "".join(f"<li>{text_block(item)}</li>" for item in _list(guide.get("checkpoints")))
    return f'<article class="pane{' is-active' if index == 0 else ''}" id="guide-{esc(slug(guide.get("id")))}" data-pane data-guide-id="{esc(guide.get("id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(guide.get("title"))}</h3><p class="pane-lead">{text_block(guide.get("body"))}</p></div></div><div class="chip-row"><span class="chip">理论：{esc(_knowledge_titles(knowledge, _list(guide.get("knowledge_link_ids"))))}</span><span class="chip">服务任务：{esc(task_titles)}</span></div><div class="section-label">同一案例</div><div class="callout">{text_block(guide.get("worked_example"))}</div><div class="section-label">快速查表</div><ul class="clean-list">{quick}</ul><div class="section-label">常见卡点</div><ul class="clean-list">{errors}</ul><div class="section-label">检查自己</div><ul class="clean-list">{checks}</ul>{_pane_footer(guides, index, "guide-", route_label="返回资料目录")}</section></article>'


def render_study_guide(content: dict[str, Any]) -> str:
    guides = [item for item in _list(content.get("study_guide")) if isinstance(item, dict)]; body = f'<div class="module-layout"><aside class="pane-nav" aria-label="资料导航"><strong>选择一份资料</strong>{_module_nav(guides, "guide-")}</aside><section class="pane-main">{"".join(_guide_pane(guide, index, guides, _knowledge_map(content), _task_map(content)) for index, guide in enumerate(guides))}</section></div>'
    return shell(content, "student", "study-guide", "学习指南", "遇到卡点时先打开一个小主题，读案例、查错误，再回到当前任务。", body)


def _kit_pane(kit: dict[str, Any], index: int, kits: list[dict[str, Any]], tasks: dict[str, dict[str, Any]]) -> str:
    task_titles = "、".join(_task_title(tasks, item) for item in _list(kit.get("task_ids"))); steps = "".join(f"<li>{text_block(item)}</li>" for item in _list(kit.get("steps"))); checks = "".join(f"<li>{text_block(item)}</li>" for item in _list(kit.get("self_check")))
    return f'<article class="pane{' is-active' if index == 0 else ''}" id="kit-{esc(slug(kit.get("id")))}" data-pane data-kit-id="{esc(kit.get("id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(kit.get("title"))}</h3><p class="pane-lead">{text_block(kit.get("content"))}</p></div><span class="chip">{esc(kit.get("kind"))}</span></div><div class="chip-row"><span class="chip">什么时候打开：{text_block(kit.get("when_to_use"))}</span><span class="chip">服务任务：{esc(task_titles)}</span></div><div class="section-label">操作步骤</div><ol class="task-steps">{steps}</ol><div class="section-label">自检</div><ul class="clean-list">{checks}</ul>{_pane_footer(kits, index, "kit-", route_label="返回补给目录")}</section></article>'


def render_foundation_kit(content: dict[str, Any]) -> str:
    kits = [item for item in _list(content.get("foundation_kit")) if isinstance(item, dict)]
    if not kits: body = '<section class="pane-card"><h3>本课程暂未声明基础补给</h3><p class="pane-lead">请直接沿任务脚手架开始，遇到卡点时回到学习指南。</p></section>'
    else: body = f'<div class="module-layout"><aside class="pane-nav" aria-label="补给导航"><strong>选择一个补给</strong>{_module_nav(kits, "kit-")}</aside><section class="pane-main">{"".join(_kit_pane(kit, index, kits, _task_map(content)) for index, kit in enumerate(kits))}</section></div>'
    return shell(content, "student", "foundation-kit", "基础补给", "只在需要时打开一小块操作补给，保持课堂节奏，不把整套资料压在学生面前。", body)


def render_teacher_guide(content: dict[str, Any]) -> str:
    teacher = content.get("teacher_guide", {}) if isinstance(content.get("teacher_guide"), dict) else {}; tasks, knowledge = _task_map(content), _knowledge_map(content); guidance = [item for item in _list(teacher.get("task_guidance")) if isinstance(item, dict)]
    timing = "".join(f'<div class="timing-item"><strong>{esc(item.get("minutes"))} 分钟</strong>{text_block(_humanize(content, item.get("focus")))}</div>' for item in _list(teacher.get("timing")) if isinstance(item, dict)); nav_items = [{"id": item.get("task_id"), "title": _task_title(tasks, item.get("task_id", "")), "purpose": "抽查与追问"} for item in guidance]
    panes = []
    for item in guidance:
        task = tasks.get(item.get("task_id"), {})
        panes.append(f'<article class="pane{' is-active' if len(panes) == 0 else ''}" id="teacher-task-{esc(slug(item.get("task_id")))}" data-pane data-task-id="{esc(item.get("task_id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(task.get("title", item.get("task_id")))}</h3><p class="pane-lead">理论桥接：{esc(_knowledge_titles(knowledge, _list(task.get("knowledge_link_ids"))))}</p></div><span class="level {esc(task.get("level"))}">{esc(LEVEL_LABELS.get(task.get("level"), task.get("level", "实践")))}</span></div><div class="section-label">教师观察点</div><div class="scaffold">{text_block(_humanize(content, item.get("look_for")))}</div><div class="section-label">学生卡住时</div><div class="teacher-note">{text_block(_humanize(content, item.get("ask_when_stuck")))}</div></section></article>')
    common = "".join(f'<li><strong>{text_block(_humanize(content, item.get("symptom")))}</strong>：{text_block(_humanize(content, item.get("intervention")))}</li>' for item in _list(teacher.get("common_errors")) if isinstance(item, dict)); pace = "".join(f"<li>{text_block(_humanize(content, item))}</li>" for item in _list(teacher.get("pace_adjustments"))); closing = "".join(f"<li>{text_block(_humanize(content, item))}</li>" for item in _list(teacher.get("closing_checks")))
    overview = f'<section class="teacher-note"><strong>课堂目的：</strong>{text_block(_humanize(content, teacher.get("purpose")))}<br><strong>理论桥接：</strong>{text_block(_humanize(content, teacher.get("theory_bridge")))}<div class="timing-list">{timing}</div></section><div class="summary-grid"><div class="summary-card"><strong>常见错误</strong><ul class="clean-list">{common}</ul></div><div class="summary-card"><strong>节奏调节</strong><ul class="clean-list">{pace}</ul></div><div class="summary-card"><strong>收束检查</strong><ul class="clean-list">{closing}</ul></div></div>'
    body = f'{overview}<div class="module-layout"><aside class="pane-nav" aria-label="教师任务指导"><strong>按任务抽查</strong>{_module_nav(nav_items, "teacher-task-")}</aside><section class="pane-main">{"".join(panes)}</section></div>'
    return shell(content, "teacher", "teacher-guide", "课堂指导", "按任务打开抽查与追问建议；答案集中在教师参考模块，课堂指导保持可观察、可调节。", body)


def render_teacher_reference(content: dict[str, Any]) -> str:
    references = [item for item in _list(content.get("teacher_reference", {}).get("task_references", [])) if isinstance(item, dict)]; tasks, knowledge = _task_map(content), _knowledge_map(content); nav_items = [{"id": item.get("task_id"), "title": item.get("title"), "purpose": "参考成果"} for item in references]; panes = []
    for index, reference in enumerate(references):
        task = tasks.get(reference.get("task_id"), {}); key_steps = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("key_steps"))); variants = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("acceptable_variants"))); errors = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("common_errors"))); basis = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("acceptance_basis"))); result = f'<div class="section-label">参考结果</div><div class="callout">{text_block(reference.get("reference_result"))}</div>' if reference.get("reference_result") else ""
        panes.append(f'<article class="pane reference-pane{' is-active' if index == 0 else ''}" id="reference-{esc(slug(reference.get("task_id")))}" data-pane data-task-id="{esc(reference.get("task_id"))}" data-source-slide-ids="{esc(" ".join(reference.get("source_slide_ids", [])))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(reference.get("title"))}</h3><p class="pane-lead">理论：{esc(_knowledge_titles(knowledge, _list(task.get("knowledge_link_ids"))))}</p></div><a href="../student/student-task.html#task-{esc(slug(reference.get("task_id")))}">打开学生任务</a></div><div class="section-label">参考答案 / 参考成果</div><pre class="reference-answer">{text_block(_humanize(content, reference.get("reference_answer")))}</pre>{f'<div class="section-label">参考结果</div><div class="callout">{text_block(_humanize(content, reference.get("reference_result")))}</div>' if reference.get("reference_result") else ""}<div class="section-label">关键步骤</div><ul class="clean-list">{"".join(f"<li>{text_block(_humanize(content, item))}</li>" for item in _list(reference.get("key_steps")))}</ul><div class="section-label">可接受变体</div><ul class="clean-list">{"".join(f"<li>{text_block(_humanize(content, item))}</li>" for item in _list(reference.get("acceptable_variants")))}</ul><div class="section-label">常见错误</div><ul class="clean-list">{"".join(f"<li>{text_block(_humanize(content, item))}</li>" for item in _list(reference.get("common_errors")))}</ul><div class="section-label">验收依据</div><ul class="clean-list">{"".join(f"<li>{text_block(_humanize(content, item))}</li>" for item in _list(reference.get("acceptance_basis")))}</ul>{_pane_footer(references, index, "reference-", route_label="返回参考目录")}</section></article>')
    body = f'<div class="module-layout"><aside class="pane-nav" aria-label="教师参考导航"><strong>选择参考成果</strong>{_module_nav(nav_items, "reference-")}</aside><section class="pane-main">{"".join(panes)}</section></div>'
    return shell(content, "teacher", "teacher-reference", "教师参考", "按任务切换参考答案和可接受变体，答案区保持宽版，便于课堂核对。", body, prefix="")


def _write_page(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _safe_asset_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts: raise ValueError(f"starter path must stay inside starter/: {relative}")
    return candidate


def generate(practice_path: Path, output_dir: Path, courseware_path: Path | None = None, *, replace: bool = False) -> dict[str, Any]:
    content = load_json(practice_path); courseware = load_courseware(courseware_path) if courseware_path else None; contract = validate_content(content, courseware)
    if contract["status"] != "pass": raise ValueError("invalid Practice Class Content Contract: " + "; ".join(contract["errors"]))
    if output_dir.exists():
        if not replace: raise FileExistsError(f"output exists; use --replace: {output_dir}")
        if not output_dir.is_dir(): raise ValueError(f"output target must be a directory: {output_dir}")
        shutil.rmtree(output_dir)
    student_dir, teacher_dir = output_dir / "student", output_dir / "teacher"; student_dir.mkdir(parents=True, exist_ok=True); teacher_dir.mkdir(parents=True, exist_ok=True)
    _write_page(student_dir / "student-task.html", render_student_task(content)); _write_page(student_dir / "learning-center.html", render_learning_center(content)); _write_page(student_dir / "study-guide.html", render_study_guide(content)); _write_page(student_dir / "foundation-kit.html", render_foundation_kit(content)); _write_page(teacher_dir / "teacher-guide.html", render_teacher_guide(content)); _write_page(teacher_dir / "teacher-reference.html", render_teacher_reference(content))
    for asset in _list(content.get("starter_assets")):
        if not isinstance(asset, dict): continue
        target = student_dir / "starter" / _safe_asset_path(str(asset.get("path", ""))); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(str(asset.get("content", "")), encoding="utf-8", newline="\n")
    (output_dir / "practice-content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (output_dir / "qa-report.json").write_text("{}\n", encoding="utf-8", newline="\n")
    try:
        from validate_practice import validate_output_files
        outputs = validate_output_files(content, output_dir)
    except Exception as exc:  # pragma: no cover
        outputs = {"status": "fail", "errors": [f"output QA unavailable: {exc}"], "warnings": [], "files": []}
    qa = {"status": "pass" if contract["status"] == "pass" and outputs["status"] == "pass" else "fail", "contract": contract, "outputs": outputs}
    (output_dir / "qa-report.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return qa


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--practice-json", required=True, type=Path); parser.add_argument("--courseware-json", type=Path); parser.add_argument("--output-dir", required=True, type=Path); parser.add_argument("--replace", action="store_true"); parser.add_argument("--json", action="store_true", dest="as_json"); args = parser.parse_args(); report = generate(args.practice_json, args.output_dir, args.courseware_json, replace=args.replace); print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else f"status={report['status']} errors={len(report['outputs']['errors'])}"); raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
