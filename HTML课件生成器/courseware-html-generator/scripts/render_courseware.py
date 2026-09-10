"""Render Courseware Content Contract 1.1 into two offline single-file HTML documents."""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from content_contract import CoursewareContractError, load_content
from activity_time_reviewer import ACTIVITY_ROLE_LABELS
from pedagogical_review import review_content
from repair_courseware import repair_content
from source_truth_validator import validate_source_truth
from validate_courseware import validate_html_outputs


RUNTIME_CSS = r"""
:root {
  --ink: #26384a;
  --muted: #637487;
  --line: #cad6df;
  --line-strong: #9eb2c0;
  --paper: #f8fbfc;
  --paper-blue: #edf4f7;
  --paper-warm: #fbf7f0;
  --accent: #6b8f9d;
  --accent-soft: #dbe8eb;
  --sage: #7d9d91;
  --peach: #c89579;
  --shadow: 0 14px 34px rgba(47, 69, 84, .12);
}
* { box-sizing: border-box; }
html, body { margin: 0; width: 100%; min-height: 100%; background: var(--paper-blue); color: var(--ink); }
body { font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif; line-height: 1.5; }
button { font: inherit; }
.app { min-height: 100vh; display: flex; flex-direction: column; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 14px 24px; border-bottom: 1px solid var(--line); background: rgba(248, 251, 252, .96); }
.topbar-title { min-width: 0; }
.topbar-title strong { display: block; font-size: clamp(16px, 1.5vw, 22px); letter-spacing: .02em; }
.topbar-title span { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
.topbar-actions { display: flex; align-items: center; gap: 12px; white-space: nowrap; }
.page-counter { color: var(--muted); font-variant-numeric: tabular-nums; font-size: 13px; }
.projection-toggle, .answer-button, .stepper-controls button { border: 1px solid var(--line-strong); border-radius: 999px; background: var(--paper); color: var(--ink); padding: 7px 12px; cursor: pointer; transition: background .18s ease, color .18s ease, border-color .18s ease; }
.projection-toggle:hover, .answer-button:hover, .stepper-controls button:hover { border-color: var(--accent); background: var(--accent-soft); }
.deck { flex: 1; display: grid; place-items: center; padding: 20px 24px 24px; min-height: 0; }
.slide-page { display: none; width: min(94vw, calc((100vh - 142px) * 1.7778)); aspect-ratio: 16 / 9; max-height: calc(100vh - 142px); overflow: hidden; padding: clamp(22px, 3vw, 46px); border: 1px solid var(--line); border-radius: 22px; background: var(--paper); box-shadow: var(--shadow); }
.slide-page.is-active { display: flex; flex-direction: column; }
.slide-kicker { color: var(--accent); font-size: clamp(11px, 1.05vw, 15px); font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.slide-title { margin: 7px 0 0; font-size: clamp(25px, 3.2vw, 52px); line-height: 1.12; letter-spacing: -.025em; }
.slide-rule { width: 100%; height: 1px; margin: 16px 0 18px; background: linear-gradient(90deg, var(--accent), var(--line), transparent); }
.slide-layout { flex: 1; min-height: 0; display: grid; grid-auto-rows: minmax(0, 1fr); gap: clamp(12px, 1.5vw, 22px); align-content: stretch; overflow: hidden; }
.slide-layout > * { min-width: 0; min-height: 0; }
.layout-hero, .layout-focus { grid-template-columns: minmax(0, 1fr); }
.layout-split, .layout-comparison { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.layout-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.layout-timeline { grid-template-columns: minmax(0, .78fr) minmax(0, 1.22fr); }
.layout-default { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.block-paragraph { margin: 0; font-size: clamp(16px, 1.35vw, 23px); color: var(--ink); }
.block-paragraph + .block-paragraph { margin-top: 7px; }
.bullet-block, .summary-block { overflow: auto; padding: 14px 17px; border: 1px solid var(--line); border-radius: 15px; background: var(--paper-blue); }
.bullet-block ul, .summary-block ul { margin: 0; padding-left: 1.35em; font-size: clamp(15px, 1.23vw, 21px); }
.bullet-block li + li, .summary-block li + li { margin-top: 7px; }
.cards-block { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; overflow: auto; }
.info-card { padding: 15px 16px; min-height: 100%; border: 1px solid var(--line); border-radius: 16px; background: var(--paper-warm); }
.info-card.tone-sage { background: #f0f6f2; }
.info-card.tone-peach { background: #fcf1e9; }
.info-card.tone-blue { background: #edf4f7; }
.info-card h3 { margin: 0 0 6px; font-size: clamp(14px, 1.18vw, 20px); }
.info-card p { margin: 0; color: var(--muted); font-size: clamp(13px, 1.08vw, 18px); }
.table-wrap { overflow: auto; border: 1px solid var(--line); border-radius: 14px; background: var(--paper); }
.table-block { width: 100%; border-collapse: collapse; font-size: clamp(13px, 1.02vw, 17px); }
.table-block th, .table-block td { padding: 9px 11px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
.table-block th { background: var(--accent-soft); color: var(--ink); font-weight: 700; }
.table-block tr:last-child td { border-bottom: 0; }
.code-block { margin: 0; overflow: auto; border: 1px solid var(--line-strong); border-radius: 14px; background: #f1f5f6; }
.code-block figcaption { padding: 8px 12px; color: var(--muted); border-bottom: 1px solid var(--line); font-size: 12px; }
.code-block pre { margin: 0; padding: 14px; color: #314d5c; font-family: "Cascadia Code", Consolas, monospace; font-size: clamp(12px, 1vw, 16px); line-height: 1.55; white-space: pre-wrap; }
.formula-block { padding: 15px 18px; border: 1px solid var(--line); border-radius: 15px; background: #f6f4ee; }
.formula { font-family: "Cambria Math", "Times New Roman", serif; font-size: clamp(20px, 2vw, 32px); color: #385b68; }
.formula-block p { margin: 8px 0 0; color: var(--muted); font-size: clamp(13px, 1.06vw, 18px); }
.svg-block { margin: 0; padding: 10px; border: 1px solid var(--line); border-radius: 15px; background: var(--paper); }
.svg-block svg { display: block; width: 100%; height: auto; max-height: min(31vh, calc(100% - 30px)); }
.svg-block figcaption { margin: 5px 4px 0; color: var(--muted); font-size: 12px; }
.image-block { margin: 0; padding: 10px; border: 1px solid var(--line); border-radius: 15px; background: var(--paper); }
.image-block img { display: block; width: 100%; max-height: min(31vh, calc(100% - 30px)); object-fit: contain; }
.image-block figcaption { margin: 5px 4px 0; color: var(--muted); font-size: 12px; }
.quiz-block, .stepper-block { min-height: 0; overflow: auto; padding: 15px 17px; border: 1px solid var(--line-strong); border-radius: 16px; background: #f5f8f7; }
.quiz-question { margin: 0 0 10px; font-weight: 700; font-size: clamp(15px, 1.25vw, 21px); }
.quiz-options { display: grid; gap: 7px; }
.quiz-option { display: block; width: 100%; padding: 9px 11px; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); color: var(--ink); text-align: left; cursor: pointer; }
.quiz-option:hover, .quiz-option.is-selected { border-color: var(--accent); background: var(--accent-soft); }
.answer-button { margin-top: 10px; padding: 5px 10px; font-size: 12px; }
.quiz-answer { margin-top: 9px; padding: 9px 11px; border-radius: 10px; background: #e9f1ed; color: #38594c; font-size: 13px; }
.quiz-answer[hidden] { display: none; }
.stepper-track { display: grid; gap: 8px; }
.stepper-step { display: none; padding: 11px 13px; border: 1px solid var(--line); border-radius: 12px; background: var(--paper); }
.stepper-step.is-current { display: block; }
.stepper-step strong { display: block; margin-bottom: 4px; }
.stepper-step span { color: var(--muted); font-size: 14px; }
.stepper-controls { display: flex; gap: 7px; margin-top: 10px; }
.stepper-controls button { padding: 5px 9px; font-size: 12px; }
.comparison-block { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.comparison-side { padding: 14px; border: 1px solid var(--line); border-radius: 14px; background: var(--paper-blue); }
.comparison-side:nth-child(2) { background: var(--paper-warm); }
.comparison-side h3 { margin: 0 0 7px; font-size: clamp(14px, 1.15vw, 19px); }
.comparison-side p, .comparison-side ul { margin: 0; color: var(--muted); font-size: clamp(13px, 1.05vw, 17px); }
.comparison-side ul { padding-left: 1.2em; }
.deck-footer { display: flex; align-items: center; gap: 12px; padding: 0 24px 12px; color: var(--muted); font-size: 12px; }
.progress-track { height: 4px; flex: 1; overflow: hidden; border-radius: 99px; background: var(--line); }
.progress-value { height: 100%; width: 0; border-radius: inherit; background: var(--accent); transition: width .18s ease; }
body.projection-mode { --ink: #172b3a; --muted: #405b6b; --line: #9db2be; --line-strong: #6f8f9c; }
body.projection-mode .slide-page { box-shadow: 0 16px 36px rgba(31, 54, 69, .17); }
.teacher-app { min-height: 100vh; display: flex; flex-direction: column; }
.teacher-header { padding: 12px 18px; border-bottom: 1px solid var(--line); background: var(--paper); }
.teacher-header strong { font-size: 18px; }
.teacher-header span { color: var(--muted); font-size: 12px; margin-left: 10px; }
.teacher-deck { flex: 1; min-height: 0; padding: 14px 18px 18px; }
.teacher-page { display: none; grid-template-columns: minmax(0, 1.18fr) minmax(300px, .82fr); gap: 16px; height: 100%; min-height: 0; }
.teacher-page.is-active { display: grid; }
.teacher-left { min-width: 0; min-height: 0; display: grid; place-items: center; }
.teacher-left .slide-page { width: 100%; max-width: none; max-height: calc(100vh - 116px); padding: clamp(18px, 2vw, 30px); }
.teacher-left .slide-title { font-size: clamp(22px, 2.45vw, 38px); }
.teacher-left .slide-layout { gap: 10px; }
.teacher-left .cards-block { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
.teacher-left .info-card { padding: 8px 9px; border-radius: 10px; }
.teacher-left .info-card h3 { font-size: clamp(11px, 1vw, 15px); margin-bottom: 3px; }
.teacher-left .info-card p { font-size: clamp(10px, .82vw, 13px); }
.teacher-left .block-paragraph { font-size: clamp(13px, 1.05vw, 17px); }
.teacher-left .svg-block svg { max-height: 20vh; }
.teacher-notes { min-width: 0; min-height: 0; overflow: auto; padding: 18px 20px; border: 1px solid var(--line); border-radius: 18px; background: var(--paper); box-shadow: var(--shadow); }
.notes-heading { padding-bottom: 13px; border-bottom: 1px solid var(--line); font-weight: 700; color: #486c78; }
.speaker-script { margin-top: 14px; color: var(--ink); font-size: clamp(15px, 1.12vw, 19px); line-height: 1.78; }
.speaker-script p { margin: 0 0 12px; }
.teacher-note-grid { display: grid; gap: 9px; margin-top: 13px; }
.teacher-note { padding: 10px 12px; border: 1px solid var(--line); border-radius: 12px; background: var(--paper-blue); }
.teacher-note strong { display: block; color: #557786; font-size: 12px; margin-bottom: 3px; }
.teacher-note span { color: var(--muted); font-size: 13px; }
.activity-plan-note { background: #f4f0e5; }
.activity-plan-note ol { margin: 6px 0 0; padding-left: 1.25em; color: var(--muted); font-size: 13px; }
.teacher-reserve { margin: 10px 18px 0; padding: 10px 14px; border: 1px solid #d9c4a0; border-radius: 12px; background: #fff8e9; color: #725b39; }
.teacher-reserve strong { margin-right: 8px; }
.teacher-reserve span { color: #856d49; font-size: 13px; }
@media (max-width: 900px) {
  .teacher-page { grid-template-columns: 1fr; overflow: auto; }
  .teacher-left .slide-page { min-height: 55vh; }
  .teacher-notes { min-height: 34vh; }
}
"""


RUNTIME_JS = r"""
(function () {
  "use strict";
  const pages = Array.from(document.querySelectorAll("[data-page-index]"));
  const counter = document.querySelector("[data-page-counter]");
  const progress = document.querySelector("[data-progress-value]");
  let index = 0;
  let wheelAccumulator = 0;
  let wheelCooldownUntil = 0;
  let pointerStart = null;
  let lastPointerAdvance = null;

  function interactive(target) {
    return !!(target && target.closest && target.closest("button, a, input, textarea, select, [role=button], [data-interactive=true]"));
  }

  function setPage(next) {
    if (!pages.length) return;
    index = Math.max(0, Math.min(pages.length - 1, next));
    pages.forEach(function (page, pageIndex) {
      page.classList.toggle("is-active", pageIndex === index);
      page.setAttribute("aria-hidden", pageIndex === index ? "false" : "true");
    });
    if (counter) counter.textContent = (index + 1) + " / " + pages.length;
    if (progress) progress.style.width = (((index + 1) / pages.length) * 100) + "%";
    document.body.dataset.pageIndex = String(index);
    document.dispatchEvent(new CustomEvent("courseware:pagechange", { detail: { index: index } }));
  }

  function advance() { setPage(index + 1); }
  function retreat() { setPage(index - 1); }

  function pointerAdvance(event) {
    if (interactive(event.target) || !pointerStart) return;
    const dx = event.clientX - pointerStart.x;
    const dy = event.clientY - pointerStart.y;
    pointerStart = null;
    if ((dx * dx + dy * dy) > 64) return;
    advance();
    lastPointerAdvance = { target: event.target, time: Date.now() };
  }

  document.addEventListener("pointerdown", function (event) {
    pointerStart = { x: event.clientX, y: event.clientY };
  }, true);
  document.addEventListener("pointerup", pointerAdvance, true);
  document.addEventListener("click", function (event) {
    if (interactive(event.target)) return;
    if (lastPointerAdvance && lastPointerAdvance.target === event.target && Date.now() - lastPointerAdvance.time < 450) {
      lastPointerAdvance = null;
      return;
    }
    advance();
  }, true);

  document.addEventListener("wheel", function (event) {
    if (interactive(event.target)) return;
    event.preventDefault();
    const now = Date.now();
    if (now < wheelCooldownUntil) return;
    let delta = event.deltaY;
    if (event.deltaMode === 1) delta *= 16;
    if (event.deltaMode === 2) delta *= window.innerHeight;
    if (!delta) return;
    if (wheelAccumulator && Math.sign(delta) !== Math.sign(wheelAccumulator)) wheelAccumulator = 0;
    wheelAccumulator += delta;
    if (Math.abs(wheelAccumulator) >= 80) {
      if (wheelAccumulator > 0) advance(); else retreat();
      wheelAccumulator = 0;
      wheelCooldownUntil = now + 520;
    }
  }, { passive: false, capture: true });

  document.addEventListener("keydown", function (event) {
    const typingTarget = event.target && event.target.closest && event.target.closest("input, textarea, select, [contenteditable=true]");
    if (typingTarget && event.key !== "Escape") return;
    if (interactive(event.target) && [" ", "Enter"].includes(event.key)) return;
    if (["ArrowRight", "PageDown", " "].includes(event.key)) { event.preventDefault(); advance(); }
    else if (["ArrowLeft", "PageUp"].includes(event.key)) { event.preventDefault(); retreat(); }
    else if (event.key === "Home") { event.preventDefault(); setPage(0); }
    else if (event.key === "End") { event.preventDefault(); setPage(pages.length - 1); }
  }, true);

  document.addEventListener("click", function (event) {
    const target = event.target.closest ? event.target.closest("[data-action]") : null;
    if (!target) return;
    const action = target.dataset.action;
    if (action === "projection") {
      document.body.classList.toggle("projection-mode");
      target.setAttribute("aria-pressed", document.body.classList.contains("projection-mode") ? "true" : "false");
    } else if (action === "show-answer") {
      const quiz = target.closest("[data-quiz]");
      const answer = quiz && quiz.querySelector("[data-answer]");
      if (answer) answer.hidden = !answer.hidden;
    } else if (action === "quiz-choice") {
      const quiz = target.closest("[data-quiz]");
      if (quiz) {
        quiz.querySelectorAll("[data-action=quiz-choice]").forEach(function (button) { button.classList.remove("is-selected"); });
        target.classList.add("is-selected");
      }
    } else if (action === "stepper") {
      const stepper = target.closest("[data-stepper]");
      if (!stepper) return;
      let current = Number(stepper.dataset.current || 0);
      const count = stepper.querySelectorAll("[data-step-index]").length;
      if (target.dataset.direction === "next") current = Math.min(count - 1, current + 1);
      if (target.dataset.direction === "prev") current = Math.max(0, current - 1);
      if (target.dataset.direction === "reset") current = 0;
      stepper.dataset.current = String(current);
      stepper.querySelectorAll("[data-step-index]").forEach(function (step) { step.classList.toggle("is-current", Number(step.dataset.stepIndex) === current); });
    }
  });

  window.__coursewareRuntime = {
    getPageIndex: function () { return index; },
    getPageCount: function () { return pages.length; },
    goTo: setPage,
    next: advance,
    previous: retreat
  };
  setPage(0);
}());
"""


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _render_list(value: Any) -> str:
    if isinstance(value, list):
        return "<ul>" + "".join(f"<li>{_escape(item)}</li>" for item in value) + "</ul>"
    return f"<p>{_escape(value)}</p>"


def _scope_svg(raw: str, scope: str) -> str:
    mapping: dict[str, str] = {}
    for match in re.finditer(r"\bid\s*=\s*(['\"])([^'\"]+)\1", raw):
        mapping[match.group(2)] = f"{scope}-{match.group(2)}"
    scoped = raw
    for old, new in mapping.items():
        scoped = re.sub(rf"(\bid\s*=\s*['\"]){re.escape(old)}(['\"])", rf"\g<1>{new}\g<2>", scoped)
        scoped = scoped.replace(f"url(#{old})", f"url(#{new})")
        scoped = scoped.replace(f"url('#{old}')", f"url('#{new}')")
        scoped = scoped.replace(f"url(\"#{old}\")", f"url(\"#{new}\")")
        scoped = scoped.replace(f'href="#{old}"', f'href="#{new}"')
        scoped = scoped.replace(f"href='#{old}'", f"href='#{new}'")
        scoped = scoped.replace(f'xlink:href="#{old}"', f'xlink:href="#{new}"')
        scoped = scoped.replace(f"xlink:href='#{old}'", f"xlink:href='#{new}'")
    return scoped


def _evidence_attrs(block: dict[str, Any]) -> str:
    """Additive, non-visual evidence hooks for the course-level adapter."""
    attrs: list[str] = []
    artifact_type = block.get("artifact_type") or block.get("semantic_artifact_type")
    if artifact_type:
        attrs.append(f' data-artifact-type="{_escape(artifact_type)}"')
    roles = block.get("semantic_roles") or block.get("semantic_elements") or []
    if isinstance(roles, str):
        roles = [roles]
    if roles:
        attrs.append(f' data-semantic-role="{_escape(" ".join(str(item) for item in roles))}"')
    asset_ids = block.get("source_asset_ids") or block.get("derived_from_asset_ids") or []
    if block.get("asset_id") and not asset_ids:
        asset_ids = [block.get("asset_id")]
    if isinstance(asset_ids, str):
        asset_ids = [asset_ids]
    if asset_ids:
        attrs.append(f' data-source-asset-id="{_escape(" ".join(str(item) for item in asset_ids))}"')
    return "".join(attrs)


def _render_block(block: dict[str, Any], slide_index: int, block_index: int, assets: dict[str, str] | None = None) -> str:
    block_type = block["type"]
    if block_type == "paragraph":
        return f'<p class="block-paragraph">{_escape(block["text"])}</p>'
    if block_type in {"bullets", "summary"}:
        class_name = "summary-block" if block_type == "summary" else "bullet-block"
        return f'<section class="{class_name}">{_render_list(block["items"])}</section>'
    if block_type == "cards":
        cards: list[str] = []
        for item in block["items"]:
            tone = _escape(item.get("tone", ""))
            tone_class = f" tone-{tone}" if tone in {"sage", "peach", "blue"} else ""
            cards.append(f'<article class="info-card{tone_class}"><h3>{_escape(item["title"])}</h3><p>{_escape(item["text"])}</p></article>')
        return f'<section class="cards-block">{"".join(cards)}</section>'
    if block_type == "table":
        headers = "".join(f"<th>{_escape(item)}</th>" for item in block["headers"])
        rows = "".join("<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>" for row in block["rows"])
        return f'<div class="table-wrap"><table class="table-block"><thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table></div>'
    if block_type == "code":
        caption = block.get("caption") or block.get("language", "代码")
        return f'<figure class="code-block"><figcaption>{_escape(caption)}</figcaption><pre><code>{_escape(block["code"])}</code></pre></figure>'
    if block_type == "formula":
        explanation = f'<p>{_escape(block["explanation"])}</p>' if block.get("explanation") else ""
        return f'<section class="formula-block"><div class="formula">{_escape(block["formula"])}</div>{explanation}</section>'
    if block_type == "svg":
        svg = _scope_svg(block["svg"], f"cw-{slide_index}-{block_index}")
        caption = f'<figcaption>{_escape(block["caption"])}</figcaption>' if block.get("caption") else ""
        return f'<figure class="svg-block" data-svg-block{_evidence_attrs(block)}>{svg}{caption}</figure>'
    if block_type == "image":
        asset_data = (assets or {}).get(str(block.get("asset_id")))
        if not asset_data:
            raise CoursewareContractError(f"image asset is not available: {block.get('asset_id')}")
        caption = f'<figcaption>{_escape(block["caption"])}</figcaption>' if block.get("caption") else ""
        alt = _escape(block.get("caption") or "课程图示")
        return f'<figure class="image-block" data-image-block{_evidence_attrs(block)}><img src="{_escape(asset_data)}" alt="{alt}">{caption}</figure>'
    if block_type == "quiz":
        options = "".join(
            f'<button class="quiz-option" data-action="quiz-choice" data-choice="{index}" data-interactive="true">{_escape(option)}</button>'
            for index, option in enumerate(block["options"])
        )
        explanation = _escape(block.get("explanation", ""))
        answer = f'<div class="quiz-answer" data-answer hidden>答案：{_escape(block["options"][block["answer_index"]])}{("。" + explanation) if explanation else ""}</div>'
        return f'<section class="quiz-block" data-quiz><p class="quiz-question">{_escape(block["question"])}</p><div class="quiz-options">{options}</div><button class="answer-button" data-action="show-answer" data-interactive="true">显示答案</button>{answer}</section>'
    if block_type == "stepper":
        steps = "".join(
            f'<article class="stepper-step{" is-current" if index == 0 else ""}" data-step-index="{index}"><strong>{_escape(step["title"])}</strong><span>{_escape(step["text"])}</span></article>'
            for index, step in enumerate(block["steps"])
        )
        controls = ''.join(
            f'<button data-action="stepper" data-direction="{direction}" data-interactive="true">{label}</button>'
            for direction, label in (("prev", "上一步"), ("next", "下一步"), ("reset", "重置"))
        )
        return f'<section class="stepper-block" data-stepper data-current="0"><div class="stepper-track">{steps}</div><div class="stepper-controls">{controls}</div></section>'
    if block_type == "comparison":
        left, right = block["left"], block["right"]
        return f'<section class="comparison-block"><article class="comparison-side"><h3>{_escape(block["left_title"])}</h3>{_render_list(left)}</article><article class="comparison-side"><h3>{_escape(block["right_title"])}</h3>{_render_list(right)}</article></section>'
    raise CoursewareContractError(f"unsupported block type at render: {block_type}")


def _render_slide_body(slide: dict[str, Any], slide_index: int, *, include_page_attrs: bool = True, assets: dict[str, str] | None = None) -> str:
    attrs = f' data-page-index="{slide_index}" data-page-id="{_escape(slide["id"])}"' if include_page_attrs else ""
    kicker = f'<div class="slide-kicker">{_escape(slide.get("kicker", ""))}</div>' if slide.get("kicker") else ""
    blocks = "".join(_render_block(block, slide_index, block_index, assets) for block_index, block in enumerate(slide["blocks"]))
    active = " is-active" if slide_index == 0 else ""
    return f'<section class="slide-page{active}"{attrs} aria-hidden="{"false" if slide_index == 0 else "true"}">{kicker}<h1 class="slide-title">{_escape(slide["title"])}</h1><div class="slide-rule"></div><div class="slide-layout layout-{_escape(slide["layout"])}">{blocks}</div></section>'


def _document_header(title: str, body_class: str) -> str:
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_escape(title)}</title><style data-courseware-style>{RUNTIME_CSS}</style></head><body class="{body_class}" data-courseware-runtime="1">'


def render_student(content: dict[str, Any], assets: dict[str, str] | None = None) -> str:
    title = f'{content["course_title"]} · {content["chapter_title"]}'
    pages = "".join(_render_slide_body(slide, index, assets=assets) for index, slide in enumerate(content["slides"]))
    return (
        _document_header(title, "student-mode")
        + '<div class="app"><header class="topbar"><div class="topbar-title"><strong>'
        + _escape(content["course_title"])
        + '</strong><span>'
        + _escape(content["chapter_title"])
        + '</span></div><div class="topbar-actions"><span class="page-counter" data-page-counter></span><button class="projection-toggle" data-action="projection" data-interactive="true" aria-pressed="false">投影增强</button></div></header><main class="deck" id="deck">'
        + pages
        + '</main><footer class="deck-footer"><span>课堂页面</span><span class="progress-track"><span class="progress-value" data-progress-value></span></span></footer></div><script data-courseware-runtime-script>'
        + RUNTIME_JS
        + "</script></body></html>"
    )


def _script_paragraphs(script: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", script) if part.strip()]
    return "".join(f"<p>{_escape(paragraph)}</p>" for paragraph in paragraphs)


def _activity_plan_note(slide: dict[str, Any]) -> str:
    minutes = slide.get("activity_minutes")
    plan = slide.get("activity_plan")
    if not isinstance(minutes, int) or minutes <= 0 or not isinstance(plan, dict):
        return ""
    segments = "".join(
        f'<li>{_escape(item.get("label"))} {_escape(item.get("minutes"))}分钟</li>'
        for item in plan.get("segments", [])
        if isinstance(item, dict)
    )
    summary = _escape(plan.get("student_action"))
    check = _escape(plan.get("check_method"))
    role_label = ACTIVITY_ROLE_LABELS.get(plan.get("activity_role"))
    title = f'课堂活动 · {role_label} · {_escape(minutes)}分钟' if role_label else f'课堂活动 · {_escape(minutes)}分钟'
    return f'<div class="teacher-note activity-plan-note"><strong>{title}</strong><span>{summary}；检查：{check}</span><ol>{segments}</ol></div>'


def _teacher_reserve(content: dict[str, Any]) -> str:
    extensions = [item for item in content.get("extensions", []) if isinstance(item, dict)]
    if not extensions:
        return ""
    total = sum(int(item.get("minutes", 0) or 0) for item in extensions if isinstance(item.get("minutes"), int))
    items = "".join(
        f'<li><strong>{_escape(item.get("title"))}</strong> · {_escape(item.get("minutes"))}分钟：{_escape(item.get("content"))}（使用条件：{_escape(item.get("use_when"))}；活动：{_escape(item.get("activity"))}）</li>'
        for item in extensions
    )
    return f'<section class="teacher-reserve"><strong>备用内容 / 讲得快时使用 · 累计 {total} 分钟</strong><span>这些内容不默认进入学生主线。</span><ul>{items}</ul></section>'


def render_teacher(content: dict[str, Any], assets: dict[str, str] | None = None) -> str:
    title = f'{content["course_title"]} · {content["chapter_title"]} · 教师备课'
    pages: list[str] = []
    for index, slide in enumerate(content["slides"]):
        notes: list[str] = []
        activity_note = _activity_plan_note(slide)
        if activity_note:
            notes.append(activity_note)
        for label, field in (("演示建议", "demo_hint"), ("课堂接话方式", "classroom_followup"), ("授课节奏 / 易错提醒", "pacing_note")):
            if slide.get(field):
                notes.append(f'<div class="teacher-note"><strong>{label}</strong><span>{_escape(slide[field])}</span></div>')
        active = " is-active" if index == 0 else ""
        pages.append(
            f'<section class="teacher-page{active}" data-page-index="{index}" data-page-id="{_escape(slide["id"])}" aria-hidden="{"false" if index == 0 else "true"}">'
            f'<div class="teacher-left">{_render_slide_body(slide, index, include_page_attrs=False, assets=assets)}</div>'
            f'<aside class="teacher-notes"><div class="notes-heading">第{index + 1}页 | {_escape(slide["title"])} | 建议 {slide["suggested_minutes"]} 分钟</div><div class="speaker-script">{_script_paragraphs(slide["speaker_script"])}</div><div class="teacher-note-grid">{"".join(notes)}</div></aside></section>'
        )
    return (
        _document_header(title, "teacher-mode")
        + '<div class="teacher-app"><header class="teacher-header"><strong>'
        + _escape(content["course_title"])
        + '</strong><span>'
        + _escape(content["chapter_title"])
        + ' · 逐页备课</span><span class="page-counter" data-page-counter></span></header>'
        + _teacher_reserve(content)
        + '<main class="teacher-deck" id="deck">'
        + "".join(pages)
        + '</main><footer class="deck-footer"><span>键盘 / 滚轮翻页</span><span class="progress-track"><span class="progress-value" data-progress-value></span></span></footer></div><script data-courseware-runtime-script>'
        + RUNTIME_JS
        + "</script></body></html>"
    )


def _remove(path: Path | None) -> None:
    if path is None or not (path.exists() or path.is_symlink()):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _asset_data_uris(content: dict[str, Any], base_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for asset in content.get("assets", []):
        if not isinstance(asset, dict):
            continue
        asset_id = asset.get("id")
        path_value = asset.get("path")
        if not isinstance(asset_id, str) or not isinstance(path_value, str):
            continue
        path = (base_dir / path_value).resolve()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        result[asset_id] = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    return result


def generate(
    content_path: Path,
    output_dir: Path,
    *,
    replace: bool = False,
    auto_repair: bool = False,
    repair_rounds: int = 2,
    source_root: Path | None = None,
    evidence_mode: str = "migration-trust",
    separate_practice_available: bool = False,
) -> dict[str, Any]:
    content_path = content_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    repair_report: dict[str, Any] = {"status": "not-run", "round_limit": min(max(0, repair_rounds), 2)}
    if auto_repair:
        raw = json.loads(content_path.read_text(encoding="utf-8"))
        repaired = repair_content(raw, base_dir=content_path.parent, max_rounds=repair_rounds)
        repair_report = {key: value for key, value in repaired.items() if key not in {"content", "validation"}}
        repair_report["validation"] = repaired.get("validation", {})
        if repaired.get("status") != "pass":
            raise CoursewareContractError("automatic contract repair failed: " + "; ".join(repaired.get("errors", [])))
        content = repaired["content"]
    else:
        content = load_content(content_path)
    source_truth: dict[str, Any] = {"status": "not-run", "mode": evidence_mode, "errors": [], "warnings": []}
    from generation_provenance import provenance
    origin = provenance(__file__, source_root)
    if evidence_mode == "strict" and not origin['valid']:
        raise CoursewareContractError('PROVENANCE_INVALID: strict generation requires a committed clean worktree')
    if evidence_mode == "strict":
        if source_root is None:
            raise CoursewareContractError("strict evidence mode requires --source-root")
        source_truth = validate_source_truth(content, source_root, mode=evidence_mode)
        if source_truth["status"] != "pass":
            raise CoursewareContractError("source truth verification failed: " + "; ".join(source_truth.get("errors", [])))
    elif evidence_mode != "migration-trust":
        raise CoursewareContractError(f"unsupported evidence mode: {evidence_mode}")
    if output_dir.exists() and not replace:
        raise FileExistsError(f"output exists: {output_dir}; use --replace")
    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.courseware-stage-", dir=str(parent)))
    backup: Path | None = None
    try:
        assets = _asset_data_uris(content, content_path.parent)
        student = render_student(content, assets)
        teacher = render_teacher(content, assets)
        qa = validate_html_outputs(content, student, teacher)
        if qa["status"] != "pass":
            raise CoursewareContractError("generated HTML QA failed: " + "; ".join(qa["errors"]))
        pedagogical = review_content(
            content,
            time_mode=evidence_mode,
            separate_practice_available=separate_practice_available,
        )
        pedagogical.setdefault("metrics", {})["source_truth"] = {
            "status": source_truth.get("status"),
            "fact_count": len(source_truth.get("facts", [])),
            "cross_material_status": source_truth.get("cross_material", {}).get("status") if isinstance(source_truth.get("cross_material"), dict) else "not-run",
        }
        if pedagogical["status"] == "FAIL":
            raise CoursewareContractError("pedagogical review failed: " + "; ".join(pedagogical["errors"]))
        (stage / "student.html").write_text(student, encoding="utf-8", newline="\n")
        (stage / "teacher.html").write_text(teacher, encoding="utf-8", newline="\n")
        report = {
            "status": "pass",
            "contract": "Courseware Content Contract 1.1",
            "source": str(content_path),
            "outputs": ["student.html", "teacher.html"],
            "qa": qa,
            "pedagogical": pedagogical,
            "source_truth": source_truth,
            "contract_repair": repair_report,
        }
        if evidence_mode == 'strict':
            origin['repair_status'] = repair_report.get('status', 'not-run')
            (stage / 'generation-provenance.json').write_text(json.dumps(origin, ensure_ascii=False, indent=2), encoding='utf-8')
        (stage / "qa-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        if output_dir.exists():
            backup = parent / f".{output_dir.name}.courseware-backup-{uuid.uuid4().hex}"
            os.replace(str(output_dir), str(backup))
        try:
            os.replace(str(stage), str(output_dir))
            stage = None  # type: ignore[assignment]
        except Exception as commit_error:
            if backup is not None and not output_dir.exists():
                os.replace(str(backup), str(output_dir))
                backup = None
            raise RuntimeError(f"courseware commit failed; previous output restored: {commit_error}") from commit_error
        _remove(backup)
        report["output_dir"] = str(output_dir)
        return report
    finally:
        _remove(stage)
        _remove(backup)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-json", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--auto-repair", action="store_true", help="repair derivable contract omissions for at most two rounds before rendering")
    parser.add_argument("--repair-rounds", type=int, default=2)
    parser.add_argument("--source-root", type=Path, help="raw source root for strict fact verification")
    parser.add_argument("--evidence-mode", choices=("strict", "migration-trust"), default="migration-trust")
    parser.add_argument("--separate-practice-available", action="store_true", help="apply the theory/practice boundary heuristic for a companion Practice asset")
    parser.add_argument("--render", action="store_true", help="accepted for workflow symmetry; HTML is always rendered")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = generate(
            args.content_json,
            args.output_dir,
            replace=args.replace,
            auto_repair=args.auto_repair,
            repair_rounds=args.repair_rounds,
            source_root=args.source_root,
            evidence_mode=args.evidence_mode,
            separate_practice_available=args.separate_practice_available,
        )
    except Exception as exc:  # noqa: BLE001 - CLI must expose a useful failure
        report = {"status": "fail", "errors": [str(exc)]}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"courseware generation: {report['status']}")
        if report.get("output_dir"):
            print(f"output_dir={report['output_dir']}")
        for error in report.get("errors", []):
            print(f"ERROR: {error}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
