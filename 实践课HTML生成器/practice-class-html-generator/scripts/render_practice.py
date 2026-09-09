"""Render Practice Class Content Contract 1.1 as a compact offline HTML package."""

from __future__ import annotations

import argparse
import copy
import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from apply_reference_gaps import build_reference_report
from classroom_integrity import closure, materialize_bundles, prepare_assets, reference_gate, write_asset, STUDENT_ROLES, package_links
from repair_practice import repair_content
from practice_pedagogical_review import review_content
from practice_contract import LEVEL_LABELS, RENDERER_FAMILIES, load_courseware, load_json, normalize_content, validate_content
from practice_time_reviewer import review_practice_time
from source_truth_validator import validate_source_truth

COURSEWARE_SCRIPTS = Path(__file__).resolve().parents[3] / "HTML课件生成器" / "courseware-html-generator" / "scripts"
if str(COURSEWARE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(COURSEWARE_SCRIPTS))
from activity_time_reviewer import review_courseware_time  # noqa: E402


TEXT_ASSET_EXTENSIONS = {
    ".c", ".cpp", ".h", ".hpp", ".py", ".java", ".js", ".ts", ".html", ".htm", ".css",
    ".sql", ".md", ".txt", ".json", ".yaml", ".yml", ".xml", ".csv",
}
NON_TEXT_ASSET_EXTENSIONS = {".drawio", ".xlsx", ".xls", ".docx", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".zip"}


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
    for raw, human in {
        "source_slide_ids": "已讲理论页",
        "interaction type": "互动类型",
        "renderer family": "呈现方式",
    }.items():
        text = text.replace(raw, human)
    return text


def _unique_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = re.sub(r"\s+", " ", value).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _public_evidence_value(value: Any) -> Any:
    """Keep teacher evidence useful without exposing contract metadata."""

    hidden_keys = {
        "id",
        "task_id",
        "source_slide_ids",
        "slide_id",
        "renderer_family",
        "interaction_type",
    }
    if isinstance(value, dict):
        return {
            key: _public_evidence_value(item)
            for key, item in value.items()
            if key not in hidden_keys
        }
    if isinstance(value, list):
        return [_public_evidence_value(item) for item in value]
    return value


def _teacher_behavior_evidence(content: dict[str, Any], evidence: Any) -> str:
    """Render executable evidence as human-readable classroom observations."""

    checks = evidence.get("checks", []) if isinstance(evidence, dict) else evidence
    if not isinstance(checks, list):
        checks = []
    kind_labels = {
        "syntax": "语法检查",
        "function-call": "函数行为检查",
        "web-request": "网页请求检查",
        "query-result": "查询结果检查",
        "structured-data": "结构化数据检查",
        "browser": "浏览器观察",
        "manual-evidence": "课堂观察",
    }
    status_labels = {
        "MANUAL_EVIDENCE_DEFINED": "待课堂人工核对",
        "AUTOMATED_UNAVAILABLE": "自动化不可用 · 已定义人工验收标准",
        "MANUAL_PASS": "课堂人工核对通过",
        "FAIL": "未通过",
        "PASS": "通过",
    }
    rows: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        raw_status = str(check.get("status", "")).upper()
        automation_status = str(check.get("automation", "")).upper()
        if raw_status in status_labels:
            status = status_labels[raw_status]
        elif automation_status in status_labels:
            status = status_labels[automation_status]
        elif check.get("passed") is True or raw_status in {"PASSED"}:
            status = status_labels["PASS"]
        else:
            status = status_labels["FAIL"]
        kind = kind_labels.get(str(check.get("verification_type", "")), "行为检查")
        details: list[str] = []
        if check.get("status_code") is not None:
            details.append(f"状态码 {check['status_code']}")
        payload = check.get("json") if check.get("json") is not None else check.get("body")
        if payload not in (None, ""):
            safe_payload = _public_evidence_value(payload)
            rendered = json.dumps(safe_payload, ensure_ascii=False) if isinstance(safe_payload, (dict, list)) else str(safe_payload)
            details.append(_humanize(content, rendered))
        rows.append(f"<li><strong>{esc(kind)}</strong>：{esc(status)}" + (f"（{esc('；'.join(details))}）" if details else "") + "</li>")
    return "".join(rows) or "<li>已定义课堂行为检查，详情见教师参考材料。</li>"


def _teacher_formula_evidence(content: dict[str, Any], fact: dict[str, Any]) -> str:
    """Render formula truth facts without exposing machine-only field names."""

    bindings = fact.get("bindings", {}) if isinstance(fact.get("bindings"), dict) else {}
    input_fields = [bindings.get("input_field"), *(_list(bindings.get("input_fields")))]
    input_fields = [str(item) for item in input_fields if item not in (None, "")]
    lines: list[str] = []
    if fact.get("formula"):
        lines.append(f"<li><strong>公式</strong>：<code>{esc(fact['formula'])}</code></li>")
    if input_fields:
        lines.append(f"<li><strong>输入字段</strong>：{esc('、'.join(input_fields))}</li>")
    if bindings.get("output_field"):
        lines.append(f"<li><strong>结果字段</strong>：{esc(bindings['output_field'])}</li>")
    if fact.get("operation_location"):
        lines.append(f"<li><strong>填写位置</strong>：{esc(fact['operation_location'])}</li>")
    if fact.get("expected_result") is not None:
        result = _humanize(content, json.dumps(fact["expected_result"], ensure_ascii=False) if isinstance(fact["expected_result"], (dict, list)) else str(fact["expected_result"]))
        lines.append(f"<li><strong>当前数据期望结果</strong>：{esc(result)}</li>")
    return "".join(lines) or "<li>已定义当前数据公式核验，详情见教师参考材料。</li>"


def _nav_links(role: str, prefix: str) -> str:
    if role == "student":
        links = (("student-task.html", "任务路线"), ("learning-center.html", "学习中心"), ("study-guide.html", "学习指南"), ("foundation-kit.html", "基础补给"))
    else:
        links = (("teacher-guide.html", "课堂指导"), ("teacher-reference.html", "教师参考"), ("../student/student-task.html", "学生任务"))
    return "".join(f'<a class="nav-link" href="{esc(prefix + href)}">{esc(label)}</a>' for href, label in links)


def _context_tools(content: dict[str, Any]) -> str:
    context = content.get("course_context") if isinstance(content.get("course_context"), dict) else {}
    def normalize(value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.casefold())

    def split_names(value: Any) -> list[str]:
        return [part.strip() for part in re.split(r"\s*[/|、·,，]\s*", str(value or "")) if part.strip()]

    def unique(values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = normalize(value)
            if key and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    tools = unique([str(item) for item in _list(context.get("tools")) if str(item).strip()])
    software = unique(split_names(context.get("software")))
    language = str(context.get("language") or "").strip()
    dialect = str(context.get("database_dialect") or "").strip()
    if dialect:
        label = "本次环境"
        software_keys = {normalize(name) for name in software}
        values = unique(software + [item for item in tools if normalize(item) not in software_keys])
    elif language and re.search(r"\b(C|C\+\+|Java|Python|JavaScript|TypeScript)\b", language, re.IGNORECASE):
        label = "本次环境"
        if software and len(software) == len(tools) and {normalize(item) for item in software} == {normalize(item) for item in tools}:
            values = [language, " / ".join(software)]
        else:
            values = unique([language] + software + tools)
    else:
        label = "本次工具"
        if software and len(software) == len(tools) and {normalize(item) for item in software} == {normalize(item) for item in tools}:
            values = [" / ".join(software)]
        elif len(tools) > 1:
            values = [" / ".join(tools)]
        else:
            values = unique(tools or software)
    return f"{label}：" + (" · ".join(esc(item) for item in values) or "按课程资料选择工具")


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


def _task_time_breakdown(task: dict[str, Any]) -> str:
    steps = [item for item in _list(task.get("time_breakdown")) if isinstance(item, dict)]
    if not steps:
        return ""
    items = "".join(f'<li>{text_block(item.get("step"))} · {esc(item.get("minutes"))} 分钟</li>' for item in steps)
    return f'<div class="section-label">任务时间依据</div><ul class="clean-list">{items}</ul>'


def _shell_css() -> str:
    return r"""+:root{--ink:#17333d;--muted:#5d7279;--line:#d7e3e5;--paper:#f6faf9;--panel:#fff;--accent:#147d78;--accent-soft:#e5f3f0;--warm:#fff4dc;--danger:#a84d35;--success:#176f55;--shadow:0 10px 28px rgba(23,51,61,.08)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}a{color:#126a72}button,select,input{font:inherit}button{cursor:pointer;color:var(--ink);background:#fff;border:1px solid #9bb8ba;border-radius:8px;padding:7px 11px}button:hover,a.nav-link:hover{background:var(--accent-soft)}button:disabled{cursor:not-allowed;opacity:.5}.site-header{background:#153d43;color:#fff;padding:13px 24px;display:flex;align-items:center;justify-content:space-between;gap:18px;min-height:76px}.site-brand{min-width:0}.site-brand .eyebrow,.module-kicker,.eyebrow{font-size:.75rem;letter-spacing:.08em;text-transform:uppercase;color:#a9d6d2}.site-brand h1{font-size:1.08rem;margin:2px 0 0;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.site-brand p{margin:0;color:#d5e9e7;font-size:.88rem}.nav{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px}.nav-link{display:inline-flex;padding:6px 9px;border-radius:7px;color:#e8f5f3;text-decoration:none;font-size:.88rem}.nav-link:hover{color:var(--ink)}.page{max-width:1400px;margin:0 auto;padding:18px 24px 52px}.module-header{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:12px 0 14px;border-bottom:1px solid var(--line)}.module-header h2{margin:2px 0 3px;font-size:1.62rem;line-height:1.25}.module-header p{margin:0;color:var(--muted);max-width:850px}.compact-meta{color:var(--muted);font-size:.88rem;padding:8px 0;text-align:right;max-width:360px}.module-layout{display:grid;grid-template-columns:minmax(205px,250px) minmax(0,1fr);gap:20px;align-items:start;margin-top:16px}.pane-nav{position:sticky;top:12px;background:rgba(255,255,255,.78);border:1px solid var(--line);border-radius:12px;padding:10px;box-shadow:var(--shadow);max-height:calc(100vh - 24px);overflow:auto}.pane-nav strong{display:block;font-size:.88rem;margin:2px 7px 7px}.pane-nav a{display:block;padding:8px 9px;border-radius:8px;color:var(--ink);text-decoration:none;line-height:1.35}.pane-nav a:hover,.pane-nav a.is-active{background:var(--accent-soft);color:#0d605e}.pane-nav .nav-meta{display:block;color:var(--muted);font-size:.78rem;margin-top:2px}.pane-main{min-width:0;max-width:1040px}.pane{display:none}.pane.is-active{display:block}.pane-card,.card,.interaction{background:var(--panel);border:1px solid var(--line);border-radius:13px;box-shadow:var(--shadow)}.pane-card{padding:19px 21px}.pane-title-row{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.pane-title-row h3{margin:0;font-size:1.28rem;line-height:1.35}.pane-lead{color:var(--muted);margin:8px 0 12px}.pane-meta{color:var(--muted);font-size:.86rem;margin:4px 0 14px}.level{display:inline-flex;align-items:center;padding:3px 9px;border-radius:999px;font-size:.79rem;white-space:nowrap}.level.core{background:#dff2ea;color:#17684f}.level.optional{background:#edf1ff;color:#4e5c9a}.level.challenge{background:#fff0cf;color:#8a5a14}.route-overview{background:linear-gradient(120deg,#e9f5f1,#fdf8ec);border:1px solid #cfe3dd;border-radius:13px;padding:14px 17px;margin-top:16px}.route-overview h3{margin:0 0 3px}.route-overview p{margin:0;color:var(--muted)}.route-grid,.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:12px}.route-card,.summary-card{background:#ffffffbf;border:1px solid #d6e6e1;border-radius:10px;padding:10px}.route-card strong,.summary-card strong{display:block}.route-card span,.summary-card span{display:block;color:var(--muted);font-size:.84rem}.section-label{font-size:.8rem;letter-spacing:.04em;color:#397078;text-transform:uppercase;margin:19px 0 6px}.task-steps,.clean-list{margin:8px 0 0;padding-left:22px}.task-steps li,.clean-list li{margin:7px 0}.scaffold,.callout{background:var(--accent-soft);border:1px solid #c6e2dc;border-radius:10px;padding:12px 14px}.acceptance{background:#f7faf2;border:1px solid #dde8ca;border-radius:10px;padding:8px 13px}.related-links{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.related-links a{display:inline-flex;align-items:center;padding:6px 9px;border:1px solid #b8d5d1;border-radius:8px;text-decoration:none;background:#fbfffe}.pane-footer{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin-top:14px}.pane-footer .footer-links{display:flex;flex-wrap:wrap;gap:7px}.small{font-size:.86rem;color:var(--muted)}.chip-row{display:flex;flex-wrap:wrap;gap:7px}.chip{display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;background:#f1f6f5;border:1px solid #d5e4e1;color:#48656b;font-size:.82rem}.starter-box{margin-top:10px;border:1px dashed #abc9c4;border-radius:9px;padding:8px 10px;background:#fbfffe}.starter-box summary{cursor:pointer;color:#116b68}.starter-code,.reference-answer{display:block;overflow:auto;background:#172d35;color:#e8f3ef;border-radius:9px;padding:13px;white-space:pre-wrap;word-break:break-word;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.reference-pane .pane-card{max-width:1080px}.reference-answer{min-height:150px}.interaction{padding:16px 17px;margin-top:14px}.interaction h4{margin:0 0 5px}.interaction .prompt{margin:0 0 12px;font-weight:650}.choice-options{display:grid;gap:8px}.choice-option{text-align:start;width:100%;background:#fbfdfd}.choice-option.is-selected{outline:2px solid #64aaa2;background:var(--accent-soft)}.feedback{min-height:28px;margin-top:10px;padding:7px 9px;border-radius:8px;background:#f3f8f7;color:var(--success)}.feedback.wrong{background:#fff0ea;color:var(--danger)}.feedback:empty{display:none}.step-card{padding:12px 13px;background:#f7fbfa;border:1px solid var(--line);border-radius:9px;min-height:86px}.step-card[hidden],.classify-feedback[hidden],.hint-text[hidden],.terminal-note[hidden]{display:none}.step-card h5{margin:0 0 3px;font-size:1rem}.interaction-controls{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.step-status,.multi-status,.sim-status{font-size:.84rem;color:var(--muted);margin-inline-start:auto;align-self:center}.classify-list{display:grid;gap:9px}.classify-item{padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:#fbfdfd}.classify-item label{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.classify-item select{min-width:170px;border:1px solid #a9c4c2;border-radius:7px;padding:5px;background:#fff}.classify-feedback{display:block;color:var(--muted);margin-top:5px;font-size:.86rem}.hint-text{display:block;color:#79552a;background:var(--warm);border-radius:7px;padding:6px 8px;margin-top:6px}.reorder-list{list-style:none;padding:0;margin:12px 0;display:grid;gap:7px}.reorder-item{display:flex;align-items:center;justify-content:space-between;gap:9px;padding:9px 10px;background:#fbfdfd;border:1px solid var(--line);border-radius:9px}.reorder-controls{white-space:nowrap}.reorder-controls button{padding:4px 7px;margin-inline-start:4px}.state-context,.state-group{padding:9px 11px;border-radius:9px;background:#f6faf9;border:1px solid var(--line);margin-top:9px}.state-group h5{margin:0 0 5px;font-size:.9rem}.state-values{display:flex;flex-wrap:wrap;gap:7px}.state-value{display:inline-flex;gap:4px;padding:4px 7px;background:#fff;border:1px solid #dbe8e6;border-radius:7px}.state-inputs{display:flex;flex-wrap:wrap;gap:9px}.state-inputs label{display:flex;align-items:center;gap:5px}.state-inputs input{width:115px;padding:6px;border:1px solid #a9c4c2;border-radius:7px}.terminal-note{margin-top:9px;padding:8px 10px;border-radius:8px;background:#e8f5ec;color:#23624d}.multi-question{padding:10px 0}.multi-question[hidden]{display:none}.multi-question p{margin:0 0 9px;font-weight:600}.footer{max-width:1400px;margin:0 auto;padding:0 24px 28px;color:var(--muted);font-size:.82rem}.teacher-note{background:#fff8e7;border:1px solid #ecd9a6;border-radius:10px;padding:11px 13px}.timing-list{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0}.timing-item{padding:7px 9px;border:1px solid var(--line);border-radius:8px;background:#fff}.timing-item strong{display:block;color:var(--accent)}
@media(max-width:820px){.site-header{display:block;padding:12px 16px}.nav{justify-content:flex-start;margin-top:7px}.page{padding:14px 15px 42px}.module-header{display:block}.compact-meta{text-align:start;padding-top:6px}.module-layout{grid-template-columns:1fr;gap:12px}.pane-nav{position:static;max-height:none;display:flex;flex-wrap:wrap;gap:4px;align-items:center}.pane-nav strong{width:100%;margin-bottom:1px}.pane-nav a{flex:1 1 180px}.pane-card{padding:15px}.pane-title-row{display:block}.level{margin-top:7px}.footer{padding:0 15px 24px}}
""".lstrip("+") + r''' .site-header{padding:8px 24px;min-height:64px}.site-brand .eyebrow{line-height:1.2}.site-brand h1{line-height:1.15}.site-brand p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.2}[data-page-module="learning-center"] .module-header{padding:4px 0 5px}[data-page-module="learning-center"] .module-header h2{font-size:1.38rem;line-height:1.15}[data-page-module="learning-center"] .module-header p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.35}[data-page-module="learning-center"] .compact-meta{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding:4px 0;line-height:1.35}[data-page-module="learning-center"] .pane-card{padding:14px 16px}[data-page-module="learning-center"] .pane-title-row h3{font-size:1.12rem}[data-page-module="learning-center"] .pane-lead{margin:4px 0 7px}[data-page-module="learning-center"] .interaction{margin-top:9px;padding:12px 13px}.reference-visual{margin-top:14px;padding:14px 16px;background:#f4f0e9;border:1px solid #d8cfc2;border-radius:12px;overflow-x:auto}.reference-visual h4{margin:0 0 9px;color:#37545a}.uml-svg{display:block;width:100%;min-width:760px;height:auto;min-height:190px;background:#fbfaf7;border:1px solid #d7d2c9;border-radius:9px}.uml-svg text{font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;fill:#274c55;font-size:15px}.uml-node{fill:#e6f0ee;stroke:#557e80;stroke-width:2}.uml-line{stroke:#557e80;stroke-width:2.4;fill:none}.uml-label{fill:#765f4a!important;font-size:13px!important;font-weight:650}.uml-field{fill:#47656a!important;font-size:13px!important}.uml-title{fill:#244952!important;font-size:16px!important;font-weight:700}.message-chain{margin:11px 0 0;padding-left:23px;color:#47656a}.message-chain li{margin:5px 0}.state-visual{padding:11px 12px;border:1px solid #cddfdb;border-radius:10px;background:#f4faf8;margin-top:10px}.state-visual-head{display:flex;justify-content:space-between;gap:12px;color:#46666b;font-size:.86rem}.state-array{display:grid;grid-template-columns:repeat(auto-fit,minmax(58px,1fr));gap:6px;margin-top:9px}.state-cell{min-width:0;padding:6px 5px;text-align:center;border:1px solid #c9dcda;border-radius:8px;background:#fff;color:#234b54;transition:opacity .15s,background .15s,border-color .15s}.state-cell .state-index{display:block;color:#71888b;font-size:.75rem}.state-cell .state-value-text{display:block;font-weight:700}.state-cell.is-candidate{background:#e2f1ec;border-color:#83b6aa}.state-cell.is-focus{background:#f6dfad;border-color:#bd8b47;box-shadow:0 0 0 2px #ead2a5}.state-cell.is-outside{opacity:.32}.state-visual-note{margin:9px 0 0;color:#5c6f71;min-height:1.6em}.comparison{padding:11px 12px;border:1px solid #d4dfdf;border-radius:10px;background:#f8fbfa;margin:10px 0}.comparison-parameters{display:flex;flex-wrap:wrap;gap:7px;margin:8px 0}.comparison-parameter.is-selected{background:#dcefe9;border-color:#5c9d91}.comparison-chart{display:grid;gap:8px;margin-top:9px}.comparison-row{display:grid;grid-template-columns:minmax(100px,1fr) minmax(150px,3fr) 70px;gap:8px;align-items:center}.comparison-label{font-size:.88rem;color:#47656a}.comparison-track{height:17px;background:#e5eceb;border-radius:999px;overflow:hidden}.comparison-bar{height:100%;width:0;background:#6b9f96;border-radius:999px;transition:width .18s ease}.comparison-row:nth-child(2) .comparison-bar{background:#c79258}.comparison-count{font-variant-numeric:tabular-nums;color:#36545a;font-size:.86rem}.comparison-explanation{margin:9px 0 0;color:#5c6f71}.diagnostic-case{padding:10px 0;border-top:1px solid #dbe5e3}.diagnostic-case:first-child{border-top:0}.diagnostic-case[hidden]{display:none}.diagnostic-case-title{margin:0 0 4px;color:#315b61}.diagnostic-case-context{margin:0 0 8px;color:#5d7279}.diagnostic-group{margin:9px 0}.diagnostic-group strong{display:block;margin-bottom:5px;color:#47656a}.diagnostic-completion{margin-top:9px;padding:8px 10px;border-radius:8px;background:#e8f5ec;color:#23624d}.diagnostic-completion[hidden]{display:none}@media(max-width:820px){.site-header{padding:10px 16px}.comparison-row{grid-template-columns:1fr}.comparison-count{margin-top:-5px}}'''


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

document.querySelectorAll("[data-compare-root]").forEach((box) => {
  const config = JSON.parse(box.dataset.comparison || "{}"); const parameters = config.parameters || []; const series = config.series || []; const buttons = [...box.querySelectorAll("[data-compare-parameter]")]; const rows = [...box.querySelectorAll("[data-comparison-row]")]; let index = 0;
  const render = () => { const parameter = parameters[index] || {}; buttons.forEach((button, buttonIndex) => button.classList.toggle("is-selected", buttonIndex === index)); const counts = series.map((item) => Number(item.counts?.[index] || 0)); const max = Math.max(1, ...counts); rows.forEach((row, rowIndex) => { const value = counts[rowIndex] || 0; const bar = row.querySelector("[data-comparison-bar]"); const count = row.querySelector("[data-comparison-count]"); if (bar) bar.style.width = `${Math.max(4, value / max * 100)}%`; if (count) count.textContent = `${value} ${series[rowIndex]?.unit || "次"}`; }); const explanation = box.querySelector("[data-comparison-explanation]"); if (explanation) explanation.textContent = parameter.explanation || "观察参数变化后，再回到上方场景判断。"; };
  buttons.forEach((button, buttonIndex) => button.addEventListener("click", () => { index = buttonIndex; render(); })); render();
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
  const rounds = JSON.parse(box.dataset.rounds || "[]"); const fields = JSON.parse(box.dataset.stateFields || "[]"); const visualConfig = box.dataset.stateVisual ? JSON.parse(box.dataset.stateVisual) : null; let current = 0; const fieldMap = new Map(fields.map((field) => [field.id, field])); const labelFor = (id) => fieldMap.get(id)?.label || "过程字段"; const valueText = (value) => typeof value === "object" ? JSON.stringify(value) : String(value);
  const makeGiven = (container, values) => { container.innerHTML = ""; Object.entries(values || {}).forEach(([id, value]) => { const span = document.createElement("span"); span.className = "state-value"; span.innerHTML = `<b>${labelFor(id)}</b> ${valueText(value)}`; container.appendChild(span); }); };
  const makeInputs = (container, values, prefix) => { container.innerHTML = ""; Object.entries(values || {}).forEach(([id, value]) => { const label = document.createElement("label"); label.textContent = `${labelFor(id)} `; const input = document.createElement("input"); input.type = fieldMap.get(id)?.input_type || (typeof value === "number" ? "number" : "text"); input.value = ""; input.dataset.stateInput = prefix; input.dataset.field = id; input.dataset.expectedValue = JSON.stringify(value); label.appendChild(input); container.appendChild(label); }); };
  const renderVisual = (round, checked = false) => { if (!visualConfig) return; const cells = box.querySelector("[data-visual-items]"); if (!cells) return; const visualKind = visualConfig.kind || "table"; if (visualKind === "sequence-range") { const start = Number(round.given?.[visualConfig.start_field]); const end = Number(round.given?.[visualConfig.end_field]); const focus = checked ? Number(round.expected?.[visualConfig.focus_field]) : null; if (!Number.isFinite(start) || !Number.isFinite(end)) return; cells.innerHTML = ""; (visualConfig.items || []).forEach((item, index) => { const cell = document.createElement("div"); const candidate = index >= start && index <= end; cell.className = `state-cell ${candidate ? "is-candidate" : "is-outside"}${focus === index ? " is-focus" : ""}`; cell.dataset.stateIndex = String(index); const indexNode = document.createElement("span"); indexNode.className = "state-index"; indexNode.textContent = `${visualConfig.index_label || "位置"} ${item.label}`; const valueNode = document.createElement("span"); valueNode.className = "state-value-text"; valueNode.textContent = valueText(item.value); cell.append(indexNode, valueNode); cells.appendChild(cell); }); const status = box.querySelector("[data-state-visual-status]"); if (status) status.textContent = checked ? (visualConfig.focus_label || "已核对当前焦点") : `${visualConfig.candidate_label || "当前范围"}：${start}—${end}`; const note = box.querySelector("[data-state-visual-note]"); if (note) note.textContent = checked ? (round.status === "found" ? `${round.observation || ""}；${visualConfig.terminal_label || `已到达终止状态：${focus}`}` : (round.observation || "已显示本轮比较结果。")) : (visualConfig.instruction || "先填写本轮未知字段，再检查下一状态。"); return; } const visualState = round.visual_state || round.visual_values || {}; cells.innerHTML = ""; (visualConfig.items || []).forEach((item, index) => { const cell = document.createElement("div"); const key = item.id || item.label; const value = Object.prototype.hasOwnProperty.call(visualState, key) ? visualState[key] : item.value; const focused = checked && (round.focus_item_id === item.id || round.focus_label === item.label); cell.className = `state-cell${focused ? " is-focus" : ""}`; cell.dataset.stateIndex = String(index); const indexNode = document.createElement("span"); indexNode.className = "state-index"; indexNode.textContent = item.label; const valueNode = document.createElement("span"); valueNode.className = "state-value-text"; valueNode.textContent = valueText(value); cell.append(indexNode, valueNode); cells.appendChild(cell); }); const status = box.querySelector("[data-state-visual-status]"); if (status) status.textContent = checked ? (visualConfig.checked_label || "已核对当前状态") : (visualConfig.status_label || "当前状态"); const note = box.querySelector("[data-state-visual-note]"); if (note) note.textContent = checked ? (round.observation || "已显示本轮状态结果。") : (visualConfig.instruction || "先观察给定状态，再填写需要推导的字段。"); };
  const render = () => { const round = rounds[current]; makeGiven(box.querySelector("[data-state-given]"), round.given); makeInputs(box.querySelector("[data-state-expected]"), round.expected, "current"); const next = box.querySelector("[data-state-next]"); const continuing = round.status === "continue"; if (next) { next.hidden = !continuing; if (continuing) makeInputs(next.querySelector("[data-state-next-inputs]"), round.next_expected, "next"); } const terminal = box.querySelector("[data-terminal-note]"); if (terminal) terminal.hidden = true; const feedback = box.querySelector(".feedback"); if (feedback) { feedback.textContent = ""; feedback.classList.remove("wrong"); } const observation = box.querySelector("[data-state-observation]"); if (observation) { observation.hidden = true; observation.textContent = round.observation || ""; } const nextButton = box.querySelector("[data-next-round]"); if (nextButton) { nextButton.hidden = !continuing; nextButton.disabled = true; } const status = box.querySelector("[data-sim-status]"); if (status) status.textContent = `第 ${current + 1} / ${rounds.length} 轮`; renderVisual(round, false); };
  const same = (input) => { if (!input || input.value.trim() === "") return false; const expected = JSON.parse(input.dataset.expectedValue); if (typeof expected === "number") return Number(input.value) === expected; return input.value.trim() === String(expected); };
  box.querySelector("[data-check]")?.addEventListener("click", () => { const round = rounds[current]; const inputs = [...box.querySelectorAll("[data-state-input]")]; const correct = inputs.length > 0 && inputs.every(same); const feedback = box.querySelector(".feedback"); if (feedback) { feedback.textContent = correct ? (round.feedback || neutralSuccess) : (box.dataset.retryFeedback || neutralRetry); feedback.classList.toggle("wrong", !correct); } const observation = box.querySelector("[data-state-observation]"); if (observation && correct) observation.hidden = false; const nextButton = box.querySelector("[data-next-round]"); if (nextButton && correct) nextButton.disabled = false; const terminal = box.querySelector("[data-terminal-note]"); if (terminal && correct && round.status !== "continue") { terminal.hidden = false; terminal.textContent = round.terminal_label || "已到达终止状态，当前过程结束。"; } if (correct) renderVisual(round, true); });
  box.querySelector("[data-next-round]")?.addEventListener("click", () => { if (current < rounds.length - 1) { current += 1; render(); } }); box.querySelector("[data-reset]")?.addEventListener("click", () => { current = 0; render(); }); render();
});

document.querySelectorAll("[data-diagnostic-root]").forEach((box) => {
  const cases = [...box.querySelectorAll("[data-diagnostic-case]")]; let index = 0; const selections = new Map();
  const show = () => { cases.forEach((item, itemIndex) => { item.hidden = itemIndex !== index; item.querySelectorAll("[data-diagnostic-choice]").forEach((button) => button.classList.remove("is-selected")); const feedback = item.querySelector("[data-diagnostic-feedback]"); if (feedback) { feedback.textContent = ""; feedback.classList.remove("wrong"); } }); const status = box.querySelector("[data-diagnostic-status]"); if (status) status.textContent = `案例 ${index + 1} / ${cases.length}`; const next = box.querySelector("[data-diagnostic-next]"); if (next) next.disabled = true; const completion = box.querySelector("[data-diagnostic-completion]"); if (completion) completion.hidden = true; };
  box.querySelectorAll("[data-diagnostic-choice]").forEach((button) => button.addEventListener("click", () => { const item = button.closest("[data-diagnostic-case]"); const group = button.closest("[data-diagnostic-group]"); if (!item || !group) return; const key = `${item.dataset.caseId}:${group.dataset.diagnosticGroup}`; selections.set(key, Number(button.dataset.optionIndex)); group.querySelectorAll("[data-diagnostic-choice]").forEach((option) => option.classList.toggle("is-selected", option === button)); }));
  box.querySelector("[data-diagnostic-check]")?.addEventListener("click", () => { const item = cases[index]; const error = selections.get(`${item.dataset.caseId}:error`); const fix = selections.get(`${item.dataset.caseId}:fix`); const correct = error === Number(item.dataset.errorAnswer) && fix === Number(item.dataset.fixAnswer); const feedback = item.querySelector("[data-diagnostic-feedback]"); if (feedback) { feedback.textContent = correct ? (item.dataset.successFeedback || neutralSuccess) : (item.dataset.retryFeedback || "请分别核对错误现象与修复动作。"); feedback.classList.toggle("wrong", !correct); } const next = box.querySelector("[data-diagnostic-next]"); if (next) next.disabled = !correct; if (correct && index === cases.length - 1) { const status = box.querySelector("[data-diagnostic-status]"); if (status) status.textContent = `${cases.length} / ${cases.length} Debug 诊断完成`; if (next) next.disabled = true; const completion = box.querySelector("[data-diagnostic-completion]"); if (completion) { completion.hidden = false; completion.textContent = box.dataset.completionFeedback || `${cases.length} / ${cases.length} Debug 诊断完成`; } } });
  box.querySelector("[data-diagnostic-next]")?.addEventListener("click", () => { if (index < cases.length - 1) { index += 1; show(); } }); box.querySelector("[data-diagnostic-reset]")?.addEventListener("click", () => { index = 0; selections.clear(); show(); }); show();
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
<main class="page" data-role="{esc(role)}" data-page-module="{esc(module)}" data-pane-module><section class="module-header" id="module-top"><div><div class="module-kicker">{esc(role_label)} · {esc(title)}</div><h2>{esc(title)}</h2><p>{text_block(subtitle)}</p></div><div class="compact-meta">{_context_tools(content)}</div></section>{body}</main>
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


def _asset_is_text(asset: dict[str, Any]) -> bool:
    path = str(asset.get("path", ""))
    suffix = Path(path).suffix.casefold()
    return suffix in TEXT_ASSET_EXTENSIONS and suffix not in NON_TEXT_ASSET_EXTENSIONS


def _asset_description(asset: dict[str, Any]) -> str:
    path = str(asset.get("path", ""))
    suffix = Path(path).suffix.casefold()
    language = str(asset.get("language", "")).strip()
    if suffix == ".drawio":
        return "可在 draw.io 中继续编辑的建模起点；网页只提供文件入口和任务说明。"
    if suffix in {".xlsx", ".xls", ".docx", ".pptx", ".pdf"}:
        return f"{language or '课堂文件'}起点，下载后在对应工具中打开。"
    return f"{language or '文本'}起点，可打开后按任务步骤编辑。"


def _starter_html(assets: dict[str, dict[str, Any]], ids: list[str]) -> str:
    blocks = []
    for asset_id in ids:
        asset = assets.get(asset_id)
        if not asset:
            continue
        relative = str(asset.get("path", "")).replace("\\", "/")
        # Asset paths are allowed to be written either relative to the
        # starter root (``foo.py``) or with that root made explicit
        # (``starter/foo.py``).  Keep the contract-facing data attribute as
        # authored, but make the browser target match the materialized path.
        href = "starter/" + quote(_safe_asset_path(relative).as_posix(), safe="/@:+,;=-._~")
        link = f'<a class="starter-link" data-starter-path="{esc(relative)}" href="{esc(href)}" download>打开起点文件</a>'
        preview = ""
        if _asset_is_text(asset):
            preview = f'<details class="starter-preview"><summary>查看内容预览</summary><pre class="starter-code" data-starter-preview-path="{esc(relative)}">{esc(asset.get("content"))}</pre></details>'
        blocks.append(f'<article class="starter-box" data-starter-asset="{esc(asset.get("id"))}"><div class="starter-head"><strong>{esc(relative)}</strong><span class="chip">{esc(asset.get("language"))}</span></div><p class="starter-description">{esc(_asset_description(asset))}</p><div class="starter-actions">{link}</div>{preview}</article>')
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
        check = f'<span class="small"><br>检查：{text_block(_humanize(content, step.get("check")))}</span>' if step.get("check") else ""
        step_html.append(f'<li><strong>{esc(_humanize(content, step.get("title")))}</strong>：{text_block(_humanize(content, step.get("instruction")))}{check}</li>')
    steps = "".join(step_html)
    acceptance = "".join(f"<li>{text_block(_humanize(content, item))}</li>" for item in _list(task.get("acceptance")))
    starter = _starter_html(assets, _list(task.get("starter_asset_ids")))
    minutes = f'<span class="chip">约 {esc(task.get("estimated_minutes"))} 分钟</span>' if task.get("estimated_minutes") else ""
    return f'''<article class="pane{' is-active' if index == 0 else ''}" id="task-{esc(slug(task.get("id")))}" data-pane data-task-id="{esc(task.get("id"))}" data-source-slide-ids="{esc(source_refs)}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(task.get("title"))}</h3><p class="pane-lead">{text_block(_humanize(content, task.get("overview")))}</p></div><span class="level {esc(task.get("level"))}">{esc(LEVEL_LABELS.get(task.get("level"), task.get("level")))}</span></div><div class="chip-row"><span class="chip">理论：{esc(_knowledge_titles(knowledge, _list(task.get("knowledge_link_ids"))))}</span>{minutes}<span class="chip">{esc(_modality_label(task.get("modality")))}</span></div><div class="section-label">本次要留下的结果</div><div class="scaffold">{text_block(_humanize(content, task.get("scaffold")))}</div><div class="section-label">完成步骤</div><ol class="task-steps">{steps}</ol>{f'<div class="section-label">起点文件</div>{starter}' if starter else ''}<div class="section-label">卡住时帮助</div><p class="small">先打开一个相关实验或资料，完成一小步，再回到本任务。</p><div class="related-links">{_task_links(content, task)}</div><div class="section-label">课堂验收</div><div class="acceptance"><ul class="clean-list">{acceptance}</ul></div>{_pane_footer(tasks, index, "task-")}</section></article>'''


def render_student_task(content: dict[str, Any]) -> str:
    tasks = [item for item in _list(content.get("tasks")) if isinstance(item, dict)]
    knowledge = _knowledge_map(content)
    assets = {item.get("id"): item for item in _list(content.get("starter_assets")) if isinstance(item, dict) and item.get("id")}
    cards = []
    for level in ("core", "optional", "challenge"):
        selected = [task for task in tasks if task.get("level") == level]
        if selected: cards.append(f'<div class="route-card"><strong>{esc(LEVEL_LABELS[level])}</strong><span>{len(selected)} 个任务 · {esc("、".join(task.get("title", "") for task in selected[:2]))}</span></div>')
    body = f'<section class="route-overview" id="task-route"><h3>今天的实践路线</h3><p>先完成核心必做，再按需要打开有余力或提高挑战。每个任务都能回到对应的理论、实验和自助资料。</p><div class="route-grid">{"".join(cards)}</div></section><div class="module-layout"><aside class="pane-nav" aria-label="任务导航"><strong>当前任务</strong>{_module_nav(tasks, "task-", meta="按路线完成")}</aside><section class="pane-main">{"".join(_task_pane(content, task, assets, knowledge, index, tasks) for index, task in enumerate(tasks))}</section></div>'
    return shell(content, "student", "student-task", "任务路线", "按层级选择任务，当前只聚焦一个任务区，随时可回到理论、实验和自助资料。", body)


def _render_choice(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    options = _list(interaction.get("options")); answer = interaction.get("answer_index")
    if not isinstance(answer, int): answer = next((index for index, option in enumerate(options) if isinstance(option, dict) and option.get("correct") is True), 0)
    buttons = "".join(f'<button type="button" class="choice-option" data-choice data-feedback="{esc(option.get("feedback"))}">{esc(option.get("label"))}</button>' for option in options if isinstance(option, dict))
    comparison = interaction.get("comparison") if isinstance(interaction.get("comparison"), dict) else None
    comparison_html = ""
    comparison_attrs = ""
    if comparison:
        parameters = "".join(f'<button type="button" class="comparison-parameter" data-compare-parameter>{esc(item.get("label"))}</button>' for item in _list(comparison.get("parameters")) if isinstance(item, dict))
        rows = []
        for item in _list(comparison.get("series")):
            if not isinstance(item, dict):
                continue
            rows.append(f'<div class="comparison-row" data-comparison-row><span class="comparison-label">{esc(item.get("label"))}</span><span class="comparison-track"><span class="comparison-bar" data-comparison-bar></span></span><span class="comparison-count" data-comparison-count></span></div>')
        comparison_html = f'<div class="comparison" data-comparison><strong>{esc(comparison.get("parameter_label", "选择一个参数"))}</strong><div class="comparison-parameters">{parameters}</div><div class="comparison-chart" aria-label="{esc(comparison.get("chart_label", "比较结果"))}">{"".join(rows)}</div><p class="comparison-explanation" data-comparison-explanation></p></div>'
        comparison_attrs = f' data-compare-root data-comparison="{_json_attr(comparison)}"'
    family = "choice-family"
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="{family}" data-interaction-id="{esc(interaction_id)}" data-choice-root data-answer-index="{answer}"{comparison_attrs} {base}><h4>先作出判断</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p>{comparison_html}<div class="choice-options">{buttons}</div><div class="interaction-controls"><button type="button" data-check>检查判断</button></div><div class="feedback" aria-live="polite"></div></div>'


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


def _diagnostic_options(options: list[Any], group: str) -> str:
    return "".join(f'<button type="button" class="choice-option" data-diagnostic-choice data-option-index="{index}">{esc(option.get("label"))}</button>' for index, option in enumerate(options) if isinstance(option, dict))


def _render_diagnose(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    cases = [item for item in _list(interaction.get("diagnostic_cases")) if isinstance(item, dict)]
    panels = []
    for item in cases:
        panels.append(f'<section class="diagnostic-case" data-diagnostic-case data-case-id="{esc(item.get("id"))}" data-error-answer="{esc(item.get("error_answer_index"))}" data-fix-answer="{esc(item.get("fix_answer_index"))}" data-success-feedback="{esc(item.get("success_feedback", "本案例诊断和修复判断正确，可以打开对应文件回归验证。"))}" data-retry-feedback="{esc(item.get("retry_feedback", "先分别核对错误现象与修复动作。"))}" hidden><h5 class="diagnostic-case-title">{esc(item.get("title"))}</h5><p class="diagnostic-case-context">{text_block(item.get("context"))}</p><div class="diagnostic-group" data-diagnostic-group="error"><strong>{text_block(item.get("error_prompt", "先判断错误原因"))}</strong><div class="choice-options">{_diagnostic_options(_list(item.get("error_options")), "error")}</div></div><div class="diagnostic-group" data-diagnostic-group="fix"><strong>{text_block(item.get("fix_prompt", "再选择最小修复"))}</strong><div class="choice-options">{_diagnostic_options(_list(item.get("fix_options")), "fix")}</div></div><div class="feedback" data-diagnostic-feedback aria-live="polite"></div></section>')
    return f'<div class="interaction" data-interaction-root data-interaction-type="diagnose" data-renderer-family="multi-question-family" data-interaction-id="{esc(interaction_id)}" data-diagnostic-root data-completion-feedback="{esc(interaction.get("completion_feedback", "Debug 诊断完成，可以回到三个文件做最小回归。"))}" {base}><h4>连续 Debug 诊断</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p>{"".join(panels)}<div class="interaction-controls"><button type="button" data-diagnostic-check>检查本案例</button><button type="button" data-diagnostic-next disabled>进入下一案例</button><button type="button" data-diagnostic-reset>从第一案例开始</button><span class="step-status" data-diagnostic-status></span></div><div class="diagnostic-completion" data-diagnostic-completion hidden></div></div>'


def _render_state(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    state = interaction.get("state") if isinstance(interaction.get("state"), dict) else {}
    target = f'；{esc(state.get("target_label"))}：{esc(state.get("target"))}' if state.get("target") is not None else ""
    context = f'<div class="state-context"><b>{esc(state.get("context_label", "背景状态"))}</b>：{text_block(state.get("context", "请阅读题面给出的状态。"))}{target}</div>'
    visual = interaction.get("visualization") if isinstance(interaction.get("visualization"), dict) else None
    if visual is None and isinstance(interaction.get("state_visual"), dict):
        visual = interaction.get("state_visual")
    visual_html = ""
    visual_attr = ""
    if visual:
        visual_attr = f' data-state-visual="{_json_attr(visual)}"'
        visual_html = f'<div class="state-visual" data-state-visual><div class="state-visual-head"><strong>{esc(visual.get("index_label", "位置"))} / {esc(visual.get("value_label", "值"))}</strong><span data-state-visual-status></span></div><div class="state-array" data-visual-items role="list"></div><p class="state-visual-note" data-state-visual-note></p></div>'
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="state-simulator-family" data-interaction-id="{esc(interaction_id)}" data-state-root data-rounds="{_json_attr(_list(interaction.get("rounds")))}" data-state-fields="{_json_attr(_list(interaction.get("state_fields")))}"{visual_attr} data-retry-feedback="{esc(interaction.get("retry_feedback", "请核对给定状态、未知字段和下一状态。"))}" {base}><h4>状态推演</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p>{context}{visual_html}<div class="state-group"><h5>题面给定</h5><div class="state-values" data-state-given></div></div><div class="state-group"><h5>本轮请你填写</h5><div class="state-inputs" data-state-expected></div></div><div class="state-group" data-state-next><h5>下一状态请你推导</h5><div class="state-inputs" data-state-next-inputs></div></div><div class="interaction-controls"><button type="button" data-check>检查当前状态</button><button type="button" data-next-round hidden disabled>进入下一轮</button><button type="button" data-reset>从第一轮开始</button><span class="sim-status" data-sim-status></span></div><div class="state-context" data-state-observation hidden></div><div class="terminal-note" data-terminal-note hidden></div><div class="feedback" aria-live="polite"></div></div>'


def _render_multi(interaction: dict[str, Any], base: str, interaction_id: str) -> str:
    questions = [item for item in _list(interaction.get("questions")) if isinstance(item, dict)]; panes = []
    for question in questions:
        options = "".join(f'<button type="button" class="choice-option" data-choice data-feedback="{esc(option.get("feedback"))}">{esc(option.get("label"))}</button>' for option in _list(question.get("options")) if isinstance(option, dict))
        panes.append(f'<div class="multi-question" data-question hidden><p>{text_block(question.get("prompt"))}</p><div class="choice-options">{options}</div><div class="feedback" aria-live="polite"></div></div>')
    return f'<div class="interaction" data-interaction-root data-interaction-type="{esc(interaction.get("type"))}" data-renderer-family="multi-question-family" data-interaction-id="{esc(interaction_id)}" data-multi-root data-questions="{_json_attr(questions)}" {base}><h4>逐题核对</h4><p class="prompt">{text_block(interaction.get("prompt"))}</p>{"".join(panes)}<div class="interaction-controls"><button type="button" data-multi-check>检查本题</button><button type="button" data-multi-next disabled>下一题</button><span class="multi-status" data-multi-status></span></div></div>'


def render_interaction(center: dict[str, Any]) -> str:
    interaction = center.get("interaction", {}) if isinstance(center.get("interaction"), dict) else {}; kind = str(interaction.get("type", "choice")); family = interaction_family(kind); interaction_id = str(center.get("id", "interaction")); minutes = interaction.get("estimated_minutes"); time_attr = f' data-estimated-minutes="{esc(minutes)}"' if isinstance(minutes, int) and not isinstance(minutes, bool) else ""; base = f'data-center-id="{esc(interaction_id)}"{time_attr}'
    if kind == "diagnose" and interaction.get("diagnostic_cases"): return _render_diagnose(interaction, base, interaction_id)
    if family == "choice-family": return _render_choice(interaction, base, interaction_id)
    if family == "step-family": return _render_step(interaction, base, interaction_id)
    if family == "classify-family": return _render_classify(interaction, base, interaction_id)
    if family == "reorder-family": return _render_reorder(interaction, base, interaction_id)
    if family == "state-simulator-family": return _render_state(interaction, base, interaction_id)
    return _render_multi(interaction, base, interaction_id)


def _center_pane(center: dict[str, Any], index: int, centers: list[dict[str, Any]], knowledge: dict[str, dict[str, Any]], tasks: dict[str, dict[str, Any]]) -> str:
    interaction = center.get("interaction", {}) if isinstance(center.get("interaction"), dict) else {}; minutes = f'<span class="chip">互动约 {esc(interaction.get("estimated_minutes"))} 分钟</span>' if isinstance(interaction.get("estimated_minutes"), int) else ""; task_titles = "、".join(_task_title(tasks, item) for item in _list(center.get("task_ids"))); active = " is-active" if index == 0 else ""
    return f'<article class="pane{active}" id="lab-{esc(slug(center.get("id")))}" data-pane data-center-id="{esc(center.get("id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(center.get("title"))}</h3><p class="pane-lead">{text_block(center.get("purpose"))}</p></div>{minutes}</div><div class="chip-row"><span class="chip">理论：{esc(_knowledge_titles(knowledge, _list(center.get("knowledge_link_ids"))))}</span><span class="chip">服务任务：{esc(task_titles)}</span></div>{render_interaction(center)}{_pane_footer(centers, index, "lab-", route_label="返回实验目录")}</section></article>'


def render_learning_center(content: dict[str, Any]) -> str:
    centers = [item for item in _list(content.get("learning_center")) if isinstance(item, dict)]; body = f'<div class="module-layout"><aside class="pane-nav" aria-label="实验导航"><strong>选择一个实验</strong>{_module_nav(centers, "lab-")}</aside><section class="pane-main">{"".join(_center_pane(center, index, centers, _knowledge_map(content), _task_map(content)) for index, center in enumerate(centers))}</section></div>'
    return shell(content, "student", "learning-center", "学习中心", "每个实验只保留一个操作焦点；先做判断或填写，再把反馈带回任务。", body)


def _guide_pane(guide: dict[str, Any], index: int, guides: list[dict[str, Any]], knowledge: dict[str, dict[str, Any]], tasks: dict[str, dict[str, Any]]) -> str:
    task_titles = "、".join(_task_title(tasks, item) for item in _list(guide.get("task_ids"))); quick = "".join(f"<li>{text_block(item)}</li>" for item in _list(guide.get("quick_reference"))); errors = "".join(f"<li>{text_block(item)}</li>" for item in _list(guide.get("common_errors"))); checks = "".join(f"<li>{text_block(item)}</li>" for item in _list(guide.get("checkpoints"))); active = " is-active" if index == 0 else ""
    return f'<article class="pane{active}" id="guide-{esc(slug(guide.get("id")))}" data-pane data-guide-id="{esc(guide.get("id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(guide.get("title"))}</h3><p class="pane-lead">{text_block(guide.get("body"))}</p></div></div><div class="chip-row"><span class="chip">理论：{esc(_knowledge_titles(knowledge, _list(guide.get("knowledge_link_ids"))))}</span><span class="chip">服务任务：{esc(task_titles)}</span></div><div class="section-label">同一案例</div><div class="callout">{text_block(guide.get("worked_example"))}</div><div class="section-label">快速查表</div><ul class="clean-list">{quick}</ul><div class="section-label">常见卡点</div><ul class="clean-list">{errors}</ul><div class="section-label">检查自己</div><ul class="clean-list">{checks}</ul>{_pane_footer(guides, index, "guide-", route_label="返回资料目录")}</section></article>'


def render_study_guide(content: dict[str, Any]) -> str:
    guides = [item for item in _list(content.get("study_guide")) if isinstance(item, dict)]; body = f'<div class="module-layout"><aside class="pane-nav" aria-label="资料导航"><strong>选择一份资料</strong>{_module_nav(guides, "guide-")}</aside><section class="pane-main">{"".join(_guide_pane(guide, index, guides, _knowledge_map(content), _task_map(content)) for index, guide in enumerate(guides))}</section></div>'
    return shell(content, "student", "study-guide", "学习指南", "遇到卡点时先打开一个小主题，读案例、查错误，再回到当前任务。", body)


def _kit_pane(kit: dict[str, Any], index: int, kits: list[dict[str, Any]], tasks: dict[str, dict[str, Any]]) -> str:
    task_titles = "、".join(_task_title(tasks, item) for item in _list(kit.get("task_ids"))); steps = "".join(f"<li>{text_block(item)}</li>" for item in _list(kit.get("steps"))); checks = "".join(f"<li>{text_block(item)}</li>" for item in _list(kit.get("self_check"))); active = " is-active" if index == 0 else ""
    return f'<article class="pane{active}" id="kit-{esc(slug(kit.get("id")))}" data-pane data-kit-id="{esc(kit.get("id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(kit.get("title"))}</h3><p class="pane-lead">{text_block(kit.get("content"))}</p></div><span class="chip">{esc(kit.get("kind"))}</span></div><div class="chip-row"><span class="chip">什么时候打开：{text_block(kit.get("when_to_use"))}</span><span class="chip">服务任务：{esc(task_titles)}</span></div><div class="section-label">操作步骤</div><ol class="task-steps">{steps}</ol><div class="section-label">自检</div><ul class="clean-list">{checks}</ul>{_pane_footer(kits, index, "kit-", route_label="返回补给目录")}</section></article>'


def render_foundation_kit(content: dict[str, Any]) -> str:
    kits = [item for item in _list(content.get("foundation_kit")) if isinstance(item, dict)]
    if not kits: body = '<section class="pane-card"><h3>本课程暂未声明基础补给</h3><p class="pane-lead">请直接沿任务脚手架开始，遇到卡点时回到学习指南。</p></section>'
    else: body = f'<div class="module-layout"><aside class="pane-nav" aria-label="补给导航"><strong>选择一个补给</strong>{_module_nav(kits, "kit-")}</aside><section class="pane-main">{"".join(_kit_pane(kit, index, kits, _task_map(content)) for index, kit in enumerate(kits))}</section></div>'
    return shell(content, "student", "foundation-kit", "基础补给", "只在需要时打开一小块操作补给，保持课堂节奏，不把整套资料压在学生面前。", body)


def render_teacher_guide(content: dict[str, Any]) -> str:
    teacher = content.get("teacher_guide", {}) if isinstance(content.get("teacher_guide"), dict) else {}; tasks, knowledge = _task_map(content), _knowledge_map(content); guidance = [item for item in _list(teacher.get("task_guidance")) if isinstance(item, dict)]
    timing_blocks: list[str] = []
    timing_seen: set[str] = set()
    for item in _list(teacher.get("timing")):
        if not isinstance(item, dict):
            continue
        focus = _humanize(content, item.get("focus"))
        if focus in timing_seen:
            continue
        timing_seen.add(focus)
        timing_blocks.append(f'<div class="timing-item"><strong>{esc(item.get("minutes"))} 分钟</strong>{text_block(focus)}</div>')
    timing = "".join(timing_blocks)
    nav_items = [{"id": item.get("task_id"), "title": _task_title(tasks, item.get("task_id", "")), "purpose": "抽查与追问"} for item in guidance]
    panes = []
    for item in guidance:
        task = tasks.get(item.get("task_id"), {})
        active = " is-active" if len(panes) == 0 else ""
        panes.append(f'<article class="pane{active}" id="teacher-task-{esc(slug(item.get("task_id")))}" data-pane data-task-id="{esc(item.get("task_id"))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(task.get("title", item.get("task_id")))}</h3><p class="pane-lead">理论桥接：{esc(_knowledge_titles(knowledge, _list(task.get("knowledge_link_ids"))))}</p></div><span class="level {esc(task.get("level"))}">{esc(LEVEL_LABELS.get(task.get("level"), task.get("level", "实践")))}</span></div><div class="section-label">教师观察点</div><div class="scaffold">{text_block(_humanize(content, item.get("look_for")))}</div><div class="section-label">学生卡住时</div><div class="teacher-note">{text_block(_humanize(content, item.get("ask_when_stuck")))}</div>{_task_time_breakdown(task)}</section></article>')
    common_items = _unique_text([f'{_humanize(content, item.get("symptom"))}：{_humanize(content, item.get("intervention"))}' for item in _list(teacher.get("common_errors")) if isinstance(item, dict)])
    common = "".join(f"<li>{text_block(item)}</li>" for item in common_items)
    pace = "".join(f"<li>{text_block(item)}</li>" for item in _unique_text([_humanize(content, item) for item in _list(teacher.get("pace_adjustments"))]))
    closing = "".join(f"<li>{text_block(item)}</li>" for item in _unique_text([_humanize(content, item) for item in _list(teacher.get("closing_checks"))]))
    overview = f'<section class="teacher-note"><strong>课堂目的：</strong>{text_block(_humanize(content, teacher.get("purpose")))}<br><strong>理论桥接：</strong>{text_block(_humanize(content, teacher.get("theory_bridge")))}<div class="timing-list">{timing}</div></section><div class="summary-grid"><div class="summary-card"><strong>常见错误</strong><ul class="clean-list">{common}</ul></div><div class="summary-card"><strong>节奏调节</strong><ul class="clean-list">{pace}</ul></div><div class="summary-card"><strong>收束检查</strong><ul class="clean-list">{closing}</ul></div></div>'
    body = f'{overview}<div class="module-layout"><aside class="pane-nav" aria-label="教师任务指导"><strong>按任务抽查</strong>{_module_nav(nav_items, "teacher-task-")}</aside><section class="pane-main">{"".join(panes)}</section></div>'
    return shell(content, "teacher", "teacher-guide", "课堂指导", "按任务打开抽查与追问建议；答案集中在教师参考模块，课堂指导保持可观察、可调节。", body)


def _reference_visual_html(reference: dict[str, Any]) -> str:
    visual = reference.get("reference_visual")
    if not isinstance(visual, dict):
        visual = reference.get("model_visual")
    if not isinstance(visual, dict):
        return ""
    title = str(visual.get("title") or "参考模型")
    nodes = [item for item in _list(visual.get("nodes")) if isinstance(item, dict)]
    box_width = 230
    gap = 45
    left = 25
    top = 48
    heights = [max(72, 42 + 21 * len(_list(item.get("fields")))) for item in nodes]
    view_width = max(760, left * 2 + len(nodes) * box_width + max(0, len(nodes) - 1) * gap)
    view_height = max(185, top + (max(heights) if heights else 72) + 62)
    svg_parts = [f'<svg class="uml-svg" viewBox="0 0 {view_width} {view_height}" role="img" aria-label="{esc(title)}"><defs><marker id="uml-arrow-{slug(reference.get("task_id"))}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#397078"></path></marker></defs>']
    positions: dict[str, tuple[float, float, float, float]] = {}
    for index, node in enumerate(nodes):
        x = left + index * (box_width + gap)
        y = top
        height = heights[index]
        node_id = str(node.get("id"))
        positions[node_id] = (x, y, box_width, height)
    for relation in _list(visual.get("relations")):
        if not isinstance(relation, dict):
            continue
        start = positions.get(str(relation.get("from")))
        end = positions.get(str(relation.get("to")))
        if not start or not end:
            continue
        x1, y1, w1, h1 = start
        x2, y2, w2, h2 = end
        forward = x1 <= x2
        sx = x1 + w1 if forward else x1
        ex = x2 if forward else x2 + w2
        sy = y1 + h1 / 2
        ey = y2 + h2 / 2
        label_x = (sx + ex) / 2
        # Long relationship semantics should not sit on top of a class box.
        # Put the label in the open band above the nodes so endpoint meanings
        # remain readable even when the relation text is longer than the gap.
        label_y = top - 14
        svg_parts.append(f'<line class="uml-line" x1="{sx:g}" y1="{sy:g}" x2="{ex:g}" y2="{ey:g}" marker-end="url(#uml-arrow-{slug(reference.get("task_id"))})"></line><text class="uml-label" x="{label_x:g}" y="{label_y:g}" text-anchor="middle">{esc(relation.get("label"))}</text>')
    for node in nodes:
        node_id = str(node.get("id"))
        x, y, width, height = positions[node_id]
        svg_parts.append(f'<rect class="uml-node" x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" rx="8"></rect><text class="uml-title" x="{x + 12:g}" y="{y + 23:g}">{esc(node.get("title"))}</text>')
        for line_index, field in enumerate(_list(node.get("fields"))):
            svg_parts.append(f'<text class="uml-field" x="{x + 12:g}" y="{y + 45 + line_index * 18:g}">{esc(field)}</text>')
    svg_parts.append("</svg>")
    messages = "".join(f"<li><strong>{esc(item.get('from'))} → {esc(item.get('to'))}</strong>：{text_block(item.get('label'))}</li>" for item in _list(visual.get("messages")) if isinstance(item, dict))
    if not nodes and not messages:
        rows = visual.get("rows") if isinstance(visual.get("rows"), list) else visual.get("items")
        if isinstance(rows, list) and rows:
            rendered_rows = []
            for row in rows:
                if isinstance(row, dict):
                    rendered_rows.append("<tr>" + "".join(f"<td>{text_block(value)}</td>" for value in row.values()) + "</tr>")
                elif isinstance(row, list):
                    rendered_rows.append("<tr>" + "".join(f"<td>{text_block(value)}</td>" for value in row) + "</tr>")
                else:
                    rendered_rows.append(f"<tr><td>{text_block(row)}</td></tr>")
            table_html = f'<table class="reference-fallback-table"><tbody>{"".join(rendered_rows)}</tbody></table>'
        else:
            table_html = '<div class="reference-fallback-table">教师参考视觉暂用表格化说明。</div>'
        return f'<section class="reference-visual" data-reference-visual="{esc(visual.get("kind", "table"))}"><h4>{esc(title)}</h4>{table_html}</section>'
    message_html = f'<ol class="message-chain">{messages}</ol>' if messages else ""
    return f'<section class="reference-visual" data-reference-visual="{esc(visual.get("kind", "model"))}"><h4>{esc(title)}</h4>{"".join(svg_parts) if nodes else ""}{message_html}</section>'


def render_teacher_reference(content: dict[str, Any]) -> str:
    references = [item for item in _list(content.get("teacher_reference", {}).get("task_references", [])) if isinstance(item, dict)]; tasks, knowledge = _task_map(content), _knowledge_map(content); nav_items = [{"id": item.get("task_id"), "title": item.get("title"), "purpose": "参考成果"} for item in references]; panes = []
    for index, reference in enumerate(references):
        task = tasks.get(reference.get("task_id"), {}); key_steps = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("key_steps"))); variants = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("acceptable_variants"))); errors = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("common_errors"))); basis = "".join(f"<li>{text_block(item)}</li>" for item in _list(reference.get("acceptance_basis"))); result = f'<div class="section-label">参考结果</div><div class="callout">{text_block(reference.get("reference_result"))}</div>' if reference.get("reference_result") else ""
        active = " is-active" if index == 0 else ""
        visual = _reference_visual_html(reference)
        for artifact in reference.get('verified_reference', []):
            visual += '<div class="section-label">已验证参考实现：' + esc(artifact['path']) + '</div><pre class="starter-code reference-artifact">' + esc(artifact['content']) + '</pre>'
        if reference.get('behavior_evidence'):
            visual += '<div class="section-label">行为验证证据</div><ul class="clean-list">' + _teacher_behavior_evidence(content, reference['behavior_evidence']) + '</ul>'
        for fact in content.get('formula_facts', []):
            if fact.get('task_id') == reference.get('task_id'):
                from formula_truth import verify_formula
                visual += '<div class="section-label">当前数据公式</div><ul class="clean-list">' + _teacher_formula_evidence(content, fact) + '</ul>'
        panes.append(f'<article class="pane reference-pane{active}" id="reference-{esc(slug(reference.get("task_id")))}" data-pane data-task-id="{esc(reference.get("task_id"))}" data-source-slide-ids="{esc(" ".join(reference.get("source_slide_ids", [])))}"><section class="pane-card"><div class="pane-title-row"><div><h3>{esc(reference.get("title"))}</h3><p class="pane-lead">理论：{esc(_knowledge_titles(knowledge, _list(task.get("knowledge_link_ids"))))}</p></div><a href="../student/student-task.html#task-{esc(slug(reference.get("task_id")))}">打开学生任务</a></div><div class="section-label">参考答案 / 参考成果</div><pre class="reference-answer">{text_block(_humanize(content, reference.get("reference_answer")))}</pre>{visual}{result}<div class="section-label">关键步骤</div><ul class="clean-list">{key_steps}</ul><div class="section-label">可接受变体</div><ul class="clean-list">{variants}</ul><div class="section-label">常见错误</div><ul class="clean-list">{errors}</ul><div class="section-label">验收依据</div><ul class="clean-list">{basis}</ul>{_pane_footer(references, index, "reference-", route_label="返回参考目录")}</section></article>')
    body = f'<div class="module-layout"><aside class="pane-nav" aria-label="教师参考导航"><strong>选择参考成果</strong>{_module_nav(nav_items, "reference-")}</aside><section class="pane-main">{"".join(panes)}</section></div>'
    return shell(content, "teacher", "teacher-reference", "教师参考", "按任务切换参考答案和可接受变体，答案区保持宽版，便于课堂核对。", body, prefix="")


def _write_page(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _safe_asset_path(relative: str) -> Path:
    # Contracts describe paths relative to the student starter root, while
    # classroom bundle examples may spell that root explicitly as
    # ``starter/foo``. Normalize the latter so it is not materialized as
    # ``starter/starter/foo``.
    normalized = str(relative).replace("\\", "/").lstrip("/")
    if normalized == "starter":
        normalized = ""
    elif normalized.startswith("starter/"):
        normalized = normalized[len("starter/"):]
    candidate = Path(normalized)
    if candidate.is_absolute() or ".." in candidate.parts: raise ValueError(f"starter path must stay inside starter/: {relative}")
    return candidate


def _sanitize_student_content(content: dict[str, Any]) -> dict[str, Any]:
    """Remove teacher answers and replacement metadata from the distributable copy."""

    safe = copy.deepcopy(content)
    for field in ('starter_bundles', 'classroom_assets', 'formula_facts', 'runtime_dependencies', 'integrity_version'):
        safe.pop(field, None)
    safe['starter_assets'] = [a for a in safe.get('starter_assets', []) if a.get('role', 'student-edit') in STUDENT_ROLES]
    for task in safe.get('tasks', []):
        task.pop('reference_verification', None)
    safe.pop("teacher_guide", None)
    safe.pop("teacher_reference", None)
    safe.pop("canonical_facts", None)
    for collection in ("knowledge_links", "tasks", "learning_center", "study_guide", "foundation_kit"):
        for item in _list(safe.get(collection)):
            if not isinstance(item, dict):
                continue
            item.pop("canonical_fact_ids", None)
            item.pop("time_breakdown", None)
    for asset in _list(safe.get("starter_assets")):
        if not isinstance(asset, dict):
            continue
        asset.pop("editable_gaps", None)
        for key in ('source_path','source_sha256','reference_verification'):
            asset.pop(key, None)
        for field in ("replacement", "target", "reference_answer", "reference_result", "acceptable_variants", "common_errors", "acceptance_basis"):
            asset.pop(field, None)
    return safe


def _copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def _generate_candidate(
    practice_path: Path,
    output_dir: Path,
    courseware_path: Path | None = None,
    *,
    replace: bool = False,
    auto_repair: bool = False,
    repair_rounds: int = 2,
    source_root: Path | None = None,
    evidence_mode: str = "migration-trust",
) -> dict[str, Any]:
    raw_content = load_json(practice_path); courseware = load_courseware(courseware_path) if courseware_path else None
    repair_report: dict[str, Any] = {"status": "not-run", "round_limit": min(max(0, repair_rounds), 2)}
    if auto_repair:
        repaired = repair_content(raw_content, courseware, max_rounds=repair_rounds)
        repair_report = {key: value for key, value in repaired.items() if key not in {"content", "validation"}}
        repair_report["validation"] = repaired.get("validation", {})
        if repaired.get("status") != "pass":
            raise ValueError("automatic contract repair failed: " + "; ".join(repaired.get("errors", [])))
        content = repaired["content"]
        migration = repaired.get("migration", {})
    else:
        content, migration = normalize_content(raw_content, courseware)
    g3 = evidence_mode == "strict" or content.get("integrity_version") == "1.0"
    lineage = []
    if g3:
        if courseware:
            environment = courseware.get('course_context', {}).get('delivery_environment')
            if environment:
                content.setdefault('course_context', {})['delivery_environment'] = environment
        content, lineage = prepare_assets(content, source_root)
    source_truth: dict[str, Any] = {"status": "not-run", "mode": evidence_mode, "errors": [], "warnings": []}
    time_evidence: dict[str, Any] = {"status": "not-run", "mode": evidence_mode, "errors": [], "warnings": []}
    courseware_time: dict[str, Any] = {"status": "not-run", "mode": evidence_mode, "errors": [], "warnings": []}
    if evidence_mode not in {"strict", "migration-trust"}:
        raise ValueError(f"unsupported evidence mode: {evidence_mode}")
    if evidence_mode == "strict":
        if source_root is None:
            raise ValueError("strict Practice generation requires --source-root")
        if courseware is None:
            raise ValueError("strict Practice generation requires --courseware-json")
        courseware_time = review_courseware_time(courseware, mode="strict")
        if courseware_time["status"] == "FAIL":
            raise ValueError("Courseware TIME_EVIDENCE_FAIL; Practice NOT_RUN: " + "; ".join(courseware_time.get("errors", [])))
        source_truth = validate_source_truth(courseware, source_root, content, mode="strict")
        if source_truth["status"] != "pass":
            raise ValueError("source truth verification failed: " + "; ".join(source_truth.get("errors", [])))
        time_evidence = review_practice_time(content, mode="strict")
        if time_evidence["status"] == "FAIL":
            raise ValueError("Practice time evidence failed: " + "; ".join(time_evidence.get("errors", [])))
    else:
        time_evidence = review_practice_time(content, mode=evidence_mode)
    formula_truth: dict[str, Any] = {"status": "not-run", "formulas": [], "errors": []}
    if g3:
        from formula_truth import verify_formulas
        formula_truth = verify_formulas(content, source_root)
        if formula_truth["status"] != "PASS":
            raise ValueError("FORMULA_SEMANTIC_FAIL: " + "; ".join(formula_truth.get("errors", [])))
        for fact, report in zip(content.get('formula_facts', []), formula_truth['formulas']):
            if report['status'] == 'PASS':
                fact['expected_result'] = report['expected_result']
    contract = validate_content(content, courseware)
    contract["migration"] = migration
    if contract["status"] != "pass": raise ValueError("invalid Practice Class Content Contract: " + "; ".join(contract["errors"]))
    pedagogical = review_content(content, contract, time_mode=evidence_mode)
    if pedagogical["status"] == "FAIL": raise ValueError("Practice Pedagogical Integrity Review failed: " + "; ".join(pedagogical["errors"]))
    integrity = reference_gate(content, source_root) if g3 else {"status": "NOT_RUN"}
    if integrity['status'] == 'FAIL':
        raise ValueError('REFERENCE_BEHAVIOR_FAIL / CLASSROOM_PACKAGE_INTEGRITY: ' + '; '.join(integrity['errors']))
    if output_dir.exists():
        if not replace: raise FileExistsError(f"output exists; use --replace: {output_dir}")
        if not output_dir.is_dir(): raise ValueError(f"output target must be a directory: {output_dir}")
        shutil.rmtree(output_dir)
    from generation_provenance import provenance
    origin = provenance(__file__, source_root, repair_report.get('status', 'not-run'))
    if g3 and evidence_mode == 'strict' and not origin['valid']:
        raise ValueError('PROVENANCE_INVALID: strict generation requires a committed clean worktree')
    student_dir, teacher_dir = output_dir / "student", output_dir / "teacher"; student_dir.mkdir(parents=True, exist_ok=True); teacher_dir.mkdir(parents=True, exist_ok=True)
    if content.get('spreadsheet_workflow'):
        for task in content.get('tasks', []):
            if task.get('artifact_kind') == 'workbook':
                task['overview'] = str(task.get('overview', '')) + '\n' + content['spreadsheet_workflow']
    _write_page(student_dir / "student-task.html", render_student_task(content)); _write_page(student_dir / "learning-center.html", render_learning_center(content)); _write_page(student_dir / "study-guide.html", render_study_guide(content)); _write_page(student_dir / "foundation-kit.html", render_foundation_kit(content)); _write_page(teacher_dir / "teacher-guide.html", render_teacher_guide(content)); _write_page(teacher_dir / "teacher-reference.html", render_teacher_reference(content))
    for asset in _list(content.get("starter_assets")):
        if not isinstance(asset, dict): continue
        if asset.get('role', 'student-edit') not in STUDENT_ROLES: continue
        target = student_dir / "starter" / _safe_asset_path(str(asset.get("path", "")))
        write_asset(asset, target, source_root)
    if g3:
        bundle_materialization = materialize_bundles(content, student_dir / "starter", source_root, include_private=False)
        if bundle_materialization["status"] != "PASS":
            raise ValueError("CLASSROOM_PACKAGE_INTEGRITY: " + "; ".join(bundle_materialization["errors"]))
        final_closure = closure(content, student_dir / "starter")
        if final_closure["status"] != "PASS":
            raise ValueError("CLASSROOM_PACKAGE_INTEGRITY: " + "; ".join(final_closure["errors"]))
    if g3: (output_dir / 'generation-provenance.json').write_text(json.dumps(origin, ensure_ascii=False, indent=2), encoding='utf-8')
    if g3:
        integrity = reference_gate(content, source_root, output_dir / 'teacher-package')
        reference_report = {'status': 'pass' if integrity['status'] == 'PASS' else 'fail', **{k:v for k,v in integrity.items() if k != 'status'}}
        (output_dir / 'asset-lineage.json').write_text(json.dumps(lineage, ensure_ascii=False, indent=2), encoding='utf-8')
        (output_dir / 'behavior-verification.json').write_text(json.dumps(integrity, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        reference_report = build_reference_report(content, output_dir=output_dir / "teacher-package")
    (output_dir / "practice-content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    student_package = output_dir / "student-package"
    _copy_tree(student_dir, student_package / "student")
    safe_content = _sanitize_student_content(content)
    (student_package / "practice-content.json").write_text(json.dumps(safe_content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (student_package / "student-manifest.json").write_text(json.dumps({
        "package_kind": "student",
        "contract_version": content.get("contract_version"),
        "pages": ["student/student-task.html", "student/learning-center.html", "student/study-guide.html", "student/foundation-kit.html"],
        "starter_directory": "student/starter",
        "teacher_answers_included": False,
        "replacement_metadata_included": False,
        "canonical_answers_included": False,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    _copy_tree(teacher_dir, output_dir / "teacher-package" / "teacher")
    (output_dir / "teacher-package" / "full-practice-content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (output_dir / "qa-report.json").write_text("{}\n", encoding="utf-8", newline="\n")
    try:
        from validate_practice import validate_output_files
        outputs = validate_output_files(content, output_dir)
    except Exception as exc:  # pragma: no cover
        outputs = {"status": "fail", "errors": [f"output QA unavailable: {exc}"], "warnings": [], "files": []}
    if g3:
        link_report = package_links(student_package)
        outputs['errors'].extend(link_report['errors'])
        if link_report['status'] == 'FAIL': outputs['status'] = 'fail'
        package_closure = closure(content, student_package / "student" / "starter")
        outputs['classroom_package_integrity'] = package_closure
        outputs['formula_truth'] = formula_truth
        outputs['errors'].extend(package_closure['errors'])
        if package_closure['status'] == 'FAIL': outputs['status'] = 'fail'
    qa = {"status": "pass" if contract["status"] == "pass" and pedagogical["status"] != "FAIL" and outputs["status"] == "pass" and reference_report["status"] == "pass" else "fail", "contract": contract, "pedagogical": pedagogical, "outputs": outputs, "reference_generation": reference_report, "classroom_integrity": integrity, "asset_lineage": lineage, "formula_truth": formula_truth, "contract_repair": repair_report, "source_truth": source_truth, "courseware_time_evidence": courseware_time, "time_evidence": time_evidence}
    (output_dir / "qa-report.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (output_dir / "teacher-package" / "qa-report.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return qa


def generate(practice_path, output_dir, courseware_path=None, *, replace=False, **kwargs):
    """Only publish a fully verified candidate; retain existing outputs on failure."""
    import tempfile
    import uuid
    output_dir = Path(output_dir).resolve()
    if output_dir.exists() and not replace:
        raise FileExistsError(f"output exists; use --replace: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.practice-candidate-', dir=output_dir.parent) as temp:
        candidate = Path(temp) / 'output'
        report = _generate_candidate(practice_path, candidate, courseware_path, **kwargs)
        if report['status'] != 'pass':
            raise ValueError('Practice candidate QA failed: ' + json.dumps(report, ensure_ascii=False))
        backup = output_dir.with_name(output_dir.name + '.backup-' + uuid.uuid4().hex)
        moved = False
        try:
            if output_dir.exists():
                output_dir.rename(backup); moved = True
            candidate.rename(output_dir)
        except Exception:
            if moved and not output_dir.exists(): backup.rename(output_dir)
            raise
        if moved: shutil.rmtree(backup)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--practice-json", required=True, type=Path); parser.add_argument("--courseware-json", type=Path); parser.add_argument("--source-root", type=Path); parser.add_argument("--evidence-mode", choices=("strict", "migration-trust"), default="migration-trust"); parser.add_argument("--output-dir", required=True, type=Path); parser.add_argument("--replace", action="store_true"); parser.add_argument("--auto-repair", action="store_true", help="repair derivable contract omissions for at most two rounds before rendering"); parser.add_argument("--repair-rounds", type=int, default=2); parser.add_argument("--json", action="store_true", dest="as_json"); args = parser.parse_args(); report = generate(args.practice_json, args.output_dir, args.courseware_json, replace=args.replace, auto_repair=args.auto_repair, repair_rounds=args.repair_rounds, source_root=args.source_root, evidence_mode=args.evidence_mode); print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json else f"status={report['status']} errors={len(report['outputs']['errors'])}"); raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
