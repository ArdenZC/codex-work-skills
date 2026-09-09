"""Build five course-neutral generalization holdouts without fixture branches.

The holdout definitions are intentionally independent of the three regression
fixtures.  They exercise the same Courseware 1.1 -> Practice 1.1 path with
different languages, tools, artifacts, and interaction purposes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SOURCE_DIR = HERE / "source-packs"
PRACTICE_DIR = HERE / "practice-contracts"
MANIFEST = HERE / "SOURCE-FREEZE.json"


def _context(name: str, audience: str, language: str, tools: list[str], platform: str, software: str, **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "course_name": name,
        "audience": audience,
        "language": language,
        "tools": tools,
        "platform": platform,
        "software": software,
    }
    value.update(extra)
    return value


def _unit(uid: str, title: str, know: str, able: str, example: str, not_yet: str = "") -> dict[str, Any]:
    return {"id": uid, "title": title, "students_should_know": [know], "students_should_be_able_to": [able], "prerequisites": [], "not_yet_taught": [not_yet] if not_yet else [], "canonical_fact_ids": [] , "_example": example}


def _courseware(spec: dict[str, Any]) -> dict[str, Any]:
    course_id = spec["id"]
    units = [_unit(f"{course_id}-u{i + 1}", item["title"], item["know"], item["able"], item["example"], item.get("not_yet", "")) for i, item in enumerate(spec["units"])]
    facts: list[dict[str, Any]] = []
    slides: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        slide_id = f"{course_id}-s{index + 1}"
        fact_id = f"{course_id}-f{index + 1}"
        unit["canonical_fact_ids"] = [fact_id]
        facts.append({"id": fact_id, "kind": "rule", "statement": spec["units"][index]["fact"], "source_slide_ids": [slide_id], "learning_unit_ids": [unit["id"]]})
        intent = {
            "opening": f"从{unit['title']}在真实工作中的一个小判断开始。",
            "core_explanation": spec["units"][index]["know"],
            "example": spec["units"][index]["example"],
            "misconception": spec["units"][index]["misconception"],
            "question": f"学生能否用{unit['title']}解释这个结果？",
            "transition": f"接下来把{unit['title']}带入实践活动。",
        }
        blocks: list[dict[str, Any]] = [
            {"type": "paragraph", "text": f"{spec['units'][index]['know']} 本页把概念放进{spec['units'][index]['example']}，要求学生先观察证据，再做出一个可复核判断。"},
            {"type": "cards", "items": [{"title": "先看什么", "text": spec["units"][index]["know"]}, {"title": "再做什么", "text": spec["units"][index]["able"]}, {"title": "不要混淆", "text": spec["units"][index]["misconception"]}]},
            {"type": "table", "headers": ["观察对象", "本页证据", "检查动作"], "rows": [[unit["title"], spec["units"][index]["example"], "说出依据并记录结果"], ["边界", spec["units"][index]["boundary"], "指出何时需要回查资料"]]},
        ]
        sample = spec["units"][index].get("sample")
        if sample:
            blocks.append({"type": "code", "language": sample["language"], "caption": sample["caption"], "code": sample["code"]})
        script_parts = [intent[field] for field in ("opening", "core_explanation", "example", "misconception", "question", "transition")]
        speaker_script = (f"本页开场可以先问学生：{script_parts[0]} 教师随后说明：{script_parts[1]} 结合例子{script_parts[2]}，提醒学生不要把它误认为{script_parts[3]}。接着追问：{script_parts[4]}，让学生先说依据，再看表格或示例核对。{script_parts[5]} ") * 4
        slides.append({"id": slide_id, "title": spec["units"][index]["title"], "kicker": "理论锚点", "layout": ["split", "grid", "comparison", "focus", "timeline"][index % 5], "blocks": blocks, "speaker_script": speaker_script, "lecture_minutes": 12, "activity_minutes": 6, "suggested_minutes": 18, "teaching_intent": intent, "learning_unit_ids": [unit["id"]]})
    for unit in units:
        unit.pop("_example", None)
    return {"contract_version": "1.1", "course_title": spec["name"], "chapter_title": spec["chapter"], "audience": spec["audience"], "session_minutes": 90, "prepared_minutes": 90, "core_minutes": 72, "extension_minutes": 18, "theme": "morandi-academy", "course_context": spec["context"], "learning_units": units, "canonical_facts": facts, "slides": slides}


def _refs(task: dict[str, Any], knowledge: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    links = [knowledge[index] for index in task["knowledge"]]
    slide_ids = sorted({ref for item in links for ref in item["source_slide_ids"]})
    unit_ids = sorted({ref for item in links for ref in item["learning_unit_ids"]})
    fact_ids = sorted({ref for item in links for ref in item["canonical_fact_ids"]})
    return slide_ids, unit_ids, fact_ids


def _gap(marker: str, target: str, replacement: str, instruction: str, kind: str = "logic") -> dict[str, str]:
    return {"marker": marker, "target": target, "replacement": replacement, "student_instruction": instruction, "kind": kind}


def _starter(spec: dict[str, Any], task_id: str, asset: dict[str, Any]) -> dict[str, Any]:
    value = dict(asset)
    value["id"] = f"{spec['id']}-{asset['id']}"
    value["task_id"] = task_id
    return value


def _apply_reference(asset: dict[str, Any]) -> str:
    value = asset["content"]
    for gap in asset.get("editable_gaps", []):
        target = gap.get("target") or gap["marker"]
        value = value.replace(target, gap["replacement"], 1)
    return value


def _interaction(kind: str, title: str, course_id: str, estimated: int) -> dict[str, Any]:
    prefix = f"围绕{title}，先做一个判断，再把反馈带回任务。"
    if kind == "choice" or kind == "scenario-decision":
        return {"type": kind, "estimated_minutes": estimated, "prompt": prefix, "options": [{"label": f"证据支持{title}的关键条件", "feedback": "正确。请把这条证据写入任务验收。"}, {"label": "只凭结果表面相似就直接通过", "feedback": "还不够，需要回到条件或过程证据。"}, {"label": "跳过检查直接改变工具设置", "feedback": "先保留可解释的检查步骤，再改变设置。"}], "answer_index": 0, "success_feedback": "判断完成，请回到对应任务执行。", "retry_feedback": "请从理论页的条件和当前证据重新核对。"}
    if kind in {"stepper", "trace"}:
        return {"type": kind, "estimated_minutes": estimated, "prompt": prefix, "steps": [{"title": "定位输入", "text": f"列出{title}的输入、观察对象和当前已知条件。"}, {"title": "执行一步", "text": f"只改变一个与{title}相关的操作，记录状态变化。"}, {"title": "核对结果", "text": "用理论中的判断标准解释结果，并决定是否进入下一步。"}, {"title": "回到任务", "text": "把观察到的规律写成任务中的一个小验收条件。"}]}
    if kind == "state-simulator":
        return {"type": kind, "estimated_minutes": estimated, "prompt": f"根据{title}的过程状态，填写下一步字段；输入框不会预填答案。", "state_fields": [{"id": "phase", "label": "当前阶段", "input_type": "text"}, {"id": "action", "label": "下一动作", "input_type": "text"}], "state": {"context_label": "当前场景", "context": f"{title}的过程被拆成两个可观察状态。"}, "visualization": {"kind": "state-machine", "title": f"{title}状态图", "items": [{"label": "观察", "value": "先收集证据"}, {"label": "检查", "value": "按标准核对"}, {"label": "处理", "value": "做一个最小动作"}]}, "rounds": [{"given": {"phase": "观察", "action": "等待"}, "expected": {"action": "检查"}, "next_expected": {"phase": "检查", "action": "核对"}, "status": "continue", "observation": "已经从描述转向证据检查。", "feedback": "下一动作应当能产生可观察证据。"}, {"given": {"phase": "检查", "action": "核对"}, "expected": {"action": "处理"}, "status": "found", "observation": "已完成一次最小、可解释的处理。", "feedback": "过程到达终止状态，可以回到任务验收。"}]}
    if kind == "diagnose":
        def case(case_id: str, symptom: str) -> dict[str, Any]:
            return {"id": case_id, "title": symptom, "context": f"在{title}操作中出现：{symptom}。", "error_prompt": "先判断最可能的原因", "error_options": [{"label": "输入/前置条件未核对", "feedback": "先查证据。"}, {"label": "直接把结果当作原因", "feedback": "结果只能帮助定位，不能代替原因。"}], "error_answer_index": 0, "fix_prompt": "再选择最小修复", "fix_options": [{"label": "补一项检查并重新观察", "feedback": "修复动作可复核。"}, {"label": "一次改动所有设置", "feedback": "改动太大，无法知道哪一步有效。"}], "fix_answer_index": 0}
        return {"type": kind, "estimated_minutes": estimated, "prompt": f"连续处理{title}中的两个诊断案例，先说现象，再选最小修复。", "diagnostic_cases": [case(f"{course_id}-case-1", "结果为空或没有变化"), case(f"{course_id}-case-2", "结果与理论条件不一致")], "completion_feedback": "两个诊断案例都完成；请把最小修复带回实践任务。"}
    if kind == "multi-question":
        questions = []
        for index, question in enumerate(("第一步应保留什么证据？", "哪个动作最能验证理论？", "什么时候需要打开补给资料？")):
            questions.append({"prompt": f"{title}：{question}", "options": [{"label": "记录条件、动作和可观察结果", "feedback": "正确，三者缺一不可。"}, {"label": "只记录最后一个数字", "feedback": "缺少过程，无法复核。"}, {"label": "先跳过检查", "feedback": "应先让判断可被验证。"}], "answer_index": 0})
        return {"type": kind, "estimated_minutes": estimated, "prompt": f"逐题完成{title}的三个检查点，每题反馈后再进入下一题。", "questions": questions}
    if kind == "classify":
        return {"type": kind, "estimated_minutes": estimated, "prompt": f"把{title}中的动作分到正确的工作角色。", "categories": ["证据", "动作", "验收"], "items": [{"id": "evidence", "label": "读取现象、条件和原始记录", "answer": "证据", "feedback": "先形成可复核证据。"}, {"id": "action", "label": "只修改一个关键设置或字段", "answer": "动作", "feedback": "动作要小且能回退。"}, {"id": "accept", "label": "按标准解释结果并决定下一步", "answer": "验收", "feedback": "验收连接理论与实践。"}]}
    if kind == "reorder":
        return {"type": kind, "estimated_minutes": estimated, "prompt": f"排列{title}的实际工作顺序，先恢复证据链，再做判断。", "items": [{"id": "observe", "label": "执行最小操作并观察结果"}, {"id": "check", "label": "核对输入和前置条件"}, {"id": "explain", "label": "用理论解释结果"}, {"id": "verify", "label": "按验收清单回归"}], "correct_order": ["check", "observe", "explain", "verify"], "success_feedback": "顺序正确，已经形成可复核的实践闭环。", "retry_feedback": "先把证据和前置条件放在最前面。"}
    raise ValueError(kind)


def _practice(spec: dict[str, Any], courseware: dict[str, Any]) -> dict[str, Any]:
    course_id = spec["id"]
    unit_by_id = {item["id"]: item for item in courseware["learning_units"]}
    fact_by_id = {item["id"]: item for item in courseware["canonical_facts"]}
    knowledge: list[dict[str, Any]] = []
    for index, unit in enumerate(courseware["learning_units"]):
        slide = courseware["slides"][index]
        fact_id = unit["canonical_fact_ids"][0]
        knowledge.append({"id": f"{course_id}-k{index + 1}", "title": unit["title"], "summary": unit["students_should_know"][0], "source_slide_ids": [slide["id"]], "student_can_do": unit["students_should_be_able_to"][0], "learning_unit_ids": [unit["id"]], "canonical_fact_ids": [fact_id]})
    guide_ids = [f"{course_id}-g{i + 1}" for i in range(len(knowledge) + 1)]
    kit_ids = [f"{course_id}-kit{i + 1}" for i in range(len(knowledge))]
    tasks: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    for index, raw in enumerate(spec["tasks"]):
        task_id = f"{course_id}-{raw['id']}"
        slide_ids, unit_ids, fact_ids = _refs(raw, knowledge)
        task: dict[str, Any] = {"id": task_id, "level": raw["level"], "title": raw["title"], "knowledge_link_ids": [knowledge[i]["id"] for i in raw["knowledge"]], "source_slide_ids": slide_ids, "learning_unit_ids": unit_ids, "canonical_fact_ids": fact_ids, "task_kind": raw["task_kind"], "artifact_kind": raw["artifact_kind"], "capabilities": raw["capabilities"], "scaffold_level": raw.get("scaffold_level", "high"), "modality": raw.get("modality", "practice"), "overview": raw["overview"], "scaffold": raw["scaffold"], "steps": [{"title": title, "instruction": instruction, "check": check} for title, instruction, check in raw["steps"]], "acceptance": raw["acceptance"], "help_refs": [guide_ids[raw["knowledge"][0]], kit_ids[raw["knowledge"][0]]], "estimated_minutes": raw["minutes"], "verification": raw.get("verification", "按验收条件复核输入、动作和结果。")}
        if raw.get("asset"):
            asset = _starter(spec, task_id, raw["asset"])
            assets.append(asset)
            task["starter_asset_ids"] = [asset["id"]]
        if raw.get("todo_count") is not None:
            task["todo_count"] = raw["todo_count"]
        tasks.append(task)
    task_by_id = {task["id"]: task for task in tasks}
    centers: list[dict[str, Any]] = []
    kinds = ["choice", "state-simulator", "stepper", "diagnose", "multi-question", "classify", "reorder"]
    for index, kind in enumerate(kinds):
        task_indexes = spec["centers"][index]["tasks"]
        linked_tasks = [tasks[item] for item in task_indexes]
        linked_knowledge = sorted({ref for task in linked_tasks for ref in task["knowledge_link_ids"]})
        linked_units = sorted({ref for task in linked_tasks for ref in task["learning_unit_ids"]})
        linked_facts = sorted({ref for task in linked_tasks for ref in task["canonical_fact_ids"]})
        interaction = _interaction(kind, spec["centers"][index]["title"], course_id, spec["centers"][index].get("minutes", 6))
        center_title = spec["centers"][index]["title"]
        centers.append({"id": f"{course_id}-lab{index + 1}", "title": center_title, "knowledge_link_ids": linked_knowledge, "task_ids": [task["id"] for task in linked_tasks], "learning_unit_ids": linked_units, "canonical_fact_ids": linked_facts, "purpose": spec["centers"][index].get("purpose", f"用{center_title}把理论判断落实到证据、动作和验收。"), "interaction": interaction})
    guides: list[dict[str, Any]] = []
    for index, item in enumerate(knowledge):
        linked = [task for task in tasks if item["id"] in task["knowledge_link_ids"]]
        guides.append({"id": guide_ids[index], "title": f"{index + 1}. {item['title']}怎么用", "knowledge_link_ids": [item["id"]], "task_ids": [task["id"] for task in linked], "learning_unit_ids": item["learning_unit_ids"], "canonical_fact_ids": item["canonical_fact_ids"], "body": f"{item['summary']} 先把本页术语换成当前任务里的对象，再按检查点推进，不必重新翻整本教材。", "worked_example": f"以{spec['units'][index]['example']}为例：先读条件，再执行一个最小动作，最后用“{item['student_can_do']}”解释观察到的结果。", "quick_reference": [item["summary"], item["student_can_do"], "每次只改变一个关键条件并保留前后结果。"], "common_errors": [spec["units"][index]["misconception"], "只看最后结果，没有记录过程证据。"], "checkpoints": ["我能指出本任务使用的理论页。", "我能说出当前结果的证据和下一步。"]})
    for guide in guides:
        linked_tasks = [task_by_id[task_id] for task_id in guide.get("task_ids", []) if task_id in task_by_id]
        guide["learning_unit_ids"] = sorted({ref for task in linked_tasks for ref in task["learning_unit_ids"]})
        guide["canonical_fact_ids"] = sorted({ref for task in linked_tasks for ref in task["canonical_fact_ids"]})
    all_tasks = [task["id"] for task in tasks]
    all_units = sorted({ref for task in tasks for ref in task["learning_unit_ids"]})
    all_facts = sorted({ref for task in tasks for ref in task["canonical_fact_ids"]})
    guides.append({"id": guide_ids[-1], "title": "6. 从证据到解释的自助路径", "knowledge_link_ids": [item["id"] for item in knowledge], "task_ids": all_tasks, "learning_unit_ids": all_units, "canonical_fact_ids": all_facts, "body": "当结果不符合预期时，沿着条件—动作—证据—解释四步回查；每一步都能指向一个具体学习资料或基础补给。", "worked_example": "先复述当前输入和预期，再只做一个最小修复，重新观察并把变化解释给同伴。", "quick_reference": ["先找最早出现差异的步骤。", "优先回到对应理论页和基础补给。", "能解释为什么修复有效才算完成。"], "common_errors": ["同时改动多个变量，无法归因。", "把教师参考答案当成第一步，而不先观察。"], "checkpoints": ["我知道每个 core task 卡住时的入口。", "我能把一次操作连接到一个理论事实。"]})
    kits: list[dict[str, Any]] = []
    for index, item in enumerate(knowledge):
        linked = [task["id"] for task in tasks if item["id"] in task["knowledge_link_ids"]]
        kits.append({"id": kit_ids[index], "title": f"{item['title']}基础补给", "kind": spec["units"][index]["kit_kind"], "content": f"这是开始{item['title']}任务前的最小工具卡：{item['summary']}", "task_ids": linked, "learning_unit_ids": item["learning_unit_ids"], "canonical_fact_ids": item["canonical_fact_ids"], "when_to_use": f"看到{item['title']}相关卡点，先打开这张补给卡。", "steps": [f"确认当前任务使用的是{item['title']}。", f"按卡片中的一个动作检查{spec['units'][index]['boundary']}。", "回到任务重新运行或复核，并记录变化。"], "self_check": [f"我能用自己的话解释{item['title']}。", "我能指出一个可观察的检查结果。"]})
    for kit in kits:
        linked_tasks = [task_by_id[task_id] for task_id in kit.get("task_ids", []) if task_id in task_by_id]
        kit["learning_unit_ids"] = sorted({ref for task in linked_tasks for ref in task["learning_unit_ids"]})
        kit["canonical_fact_ids"] = sorted({ref for task in linked_tasks for ref in task["canonical_fact_ids"]})
    references: list[dict[str, Any]] = []
    for task in tasks:
        raw = next(item for item in spec["tasks"] if f"{course_id}-{item['id']}" == task["id"])
        answer = raw.get("reference_answer", f"完成{task['title']}：{raw['acceptance'][0]}；{raw['acceptance'][-1]}。")
        if raw.get("asset"):
            answer = _apply_reference(next(asset for asset in assets if asset["task_id"] == task["id"]))
        references.append({"task_id": task["id"], "title": task["title"], "source_slide_ids": task["source_slide_ids"], "learning_unit_ids": task["learning_unit_ids"], "canonical_fact_ids": task["canonical_fact_ids"], "reference_answer": answer, "reference_result": raw.get("reference_result", "结果与验收条件一致，并能说明关键判断依据。"), "key_steps": [step["instruction"] for step in task["steps"]], "acceptable_variants": raw.get("acceptable_variants", ["只要保留同一理论约束、证据链和可解释验收即可接受。"]), "common_errors": raw.get("common_errors", ["跳过前置条件", "一次改变多个关键因素", "只报结果不解释依据"]), "acceptance_basis": task["acceptance"]})
    guidance = [{"task_id": task["id"], "look_for": f"检查学生是否真的完成“{task['title']}”的关键动作，并能指出对应理论证据。", "ask_when_stuck": f"请学生先复述{task['overview']}中的输入、动作和预期，再问哪一条理论事实能解释当前现象。"} for task in tasks]
    return {"contract_version": "1.1", "course_title": spec["name"], "practice_title": spec["practice_title"], "audience": spec["audience"], "duration_minutes": 90, "course_context": spec["context"], "source_courseware": {"mode": "courseware", "contract_version": "1.1", "chapter_title": courseware["chapter_title"], "taught_slide_ids": [slide["id"] for slide in courseware["slides"]]}, "knowledge_links": knowledge, "tasks": tasks, "learning_center": centers, "study_guide": guides, "foundation_kit": kits, "teacher_guide": {"purpose": f"带领学生用{spec['name']}的理论完成一条可观察实践闭环。", "theory_bridge": "每次巡视先让学生指出 source 理论事实，再看操作证据；不要用教师答案替代学生判断。", "timing": [{"minutes": 8, "focus": "理论回看与第一个可观察判断"}, {"minutes": 30, "focus": "core 前半段：小步操作和即时核对"}, {"minutes": 24, "focus": "core 后半段：完成、运行或诊断"}, {"minutes": 20, "focus": "差异化路径和连续互动"}, {"minutes": 8, "focus": "解释性收束与个别抽查"}], "task_guidance": guidance, "common_errors": [{"symptom": "学生直接改结果而不记录条件", "intervention": "让学生回到理论页，写出输入、动作和预期后再做一次最小变化。"}, {"symptom": "学生把一次偶然成功当成规则", "intervention": "要求换一个边界或反例，说明规则是否仍成立。"}, {"symptom": "学生卡在工具操作而非本课知识", "intervention": "先打开对应 foundation-kit，完成自检后再回到 core task。"}], "pace_adjustments": ["基础较弱时只要求完成所有 core 的第一验收点，并把 optional 改为教师示范。", "进度较快时要求比较两个条件或处理 challenge，但不打断基础学生路径。", "课堂时间不足时保留理论关联、一个可观察结果和一次解释性抽查。"], "closing_checks": ["随机请学生解释一个结果背后的理论事实。", "检查每个 core 是否至少留下一个可复核结果。", "确认学生知道下次卡住时打开哪份资料。"]}, "teacher_reference": {"task_references": references}, "starter_assets": assets}


def _code_asset(asset_id: str, path: str, language: str, content: str, gaps: list[dict[str, str]]) -> dict[str, Any]:
    return {"id": asset_id, "path": path, "language": language, "content": content, "editable_gaps": gaps}


def _text_asset(asset_id: str, path: str, language: str, content: str) -> dict[str, Any]:
    return {"id": asset_id, "path": path, "language": language, "content": content}


def _specs() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    web_context = _context("Python Web 接口基础", "高职软件开发专业学生", "Python", ["Python", "VS Code"], "Windows", "Python 3.12", framework="Flask", other_constraints=["本次只关注请求校验与响应结构"])
    web_asset = _code_asset("request-checker", "request_checker.py", "Python", '''def normalize_request(request):\n    status = "valid"  # TODO 1\n    if not request.get("name"):  # TODO 2\n        status = "invalid"\n    return {"status": status, "name": request.get("name", "guest")}  # TODO 3\n''', [_gap("status = \"valid\"  # TODO 1", "status = \"valid\"  # TODO 1", "status = \"accepted\"  # TODO 1", "把成功状态改成接口约定的 accepted。"), _gap("if not request.get(\"name\"):  # TODO 2", "if not request.get(\"name\"):  # TODO 2", "if not request.get(\"name\") or not request.get(\"name\").strip():  # TODO 2", "补上只有空白字符时也应拒绝的条件。"), _gap("return {\"status\": status, \"name\": request.get(\"name\", \"guest\")}  # TODO 3", "return {\"status\": status, \"name\": request.get(\"name\", \"guest\")}  # TODO 3", "return {\"status\": status, \"name\": request.get(\"name\", \"guest\"), \"normalized\": True}  # TODO 3", "在响应中加入已完成规范化的布尔标记。", "response")])
    web_units = [{"title": "请求与响应", "know": "接口输入、处理结果和响应字段要有明确对应", "able": "能从一条请求记录说出预期响应", "example": "用户提交姓名后返回状态与规范化标记", "fact": "响应字段必须能回到请求条件和处理动作", "misconception": "把浏览器显示出来的文字当成完整响应", "boundary": "缺少字段与空白字段", "kit_kind": "HTTP 观察"}, {"title": "路由与参数", "know": "路径参数和查询参数在接口中承担不同输入角色", "able": "能把一个业务输入放到正确参数位置", "example": "/users/42 与 ?active=true 的差别", "fact": "参数位置应与接口契约中的语义一致", "misconception": "所有输入都塞进同一个字符串", "boundary": "路径缺失与查询可选", "kit_kind": "路由识别"}, {"title": "输入校验", "know": "校验要在业务处理前拦住不满足契约的输入", "able": "能为一个字段写出可观察的校验条件", "example": "姓名为空白时返回可解释状态", "fact": "校验条件必须覆盖空值、空白和有效值的边界", "misconception": "只检查字段是否存在就等于校验", "boundary": "空值、空白、有效值", "kit_kind": "Python 字符串"}, {"title": "可观察调试", "know": "调试要比较预期响应和实际响应，而不是盲目改代码", "able": "能根据现象定位最早发生差异的步骤", "example": "状态正确但响应缺少字段", "fact": "最小修复应同时保留现象、原因和回归检查", "misconception": "把所有条件一起改掉更快", "boundary": "状态与字段分别核对", "kit_kind": "调试记录"}, {"title": "接口场景验收", "know": "接口验收要覆盖正常、边界和错误输入", "able": "能为一个接口设计三条可复核场景", "example": "有效姓名、空白姓名和缺失姓名", "fact": "至少一个边界场景必须能区分正确与错误实现", "misconception": "只测正常输入就能证明接口完成", "boundary": "正常与边界响应", "kit_kind": "场景清单"}]
    web_tasks = [{"id": "observe", "level": "core", "title": "读懂一条请求的证据", "knowledge": [0], "task_kind": "observation", "artifact_kind": "result", "capabilities": ["state_tracking", "explanation"], "overview": "从请求样例中标出输入、处理动作和响应字段。", "scaffold": "已给出一条带姓名字段的请求记录和响应草稿。", "minutes": 8, "steps": [("圈出输入", "标记方法、路径、字段和值。", "能解释每个字段来自哪里。"), ("对齐响应", "把响应字段连回处理动作。", "不遗漏状态字段。"), ("口头解释", "用一句话说明输入变化会影响哪个输出。", "同伴能复述。")], "acceptance": ["写出输入—动作—响应三段关系", "指出一个边界字段" ]}, {"id": "route", "level": "core", "title": "把参数放回路由契约", "knowledge": [1], "task_kind": "analysis", "artifact_kind": "document", "capabilities": ["file_editing", "explanation"], "overview": "依据接口契约卡修改参数位置表。", "scaffold": "提供三条路径和参数槽位，只需填入参数来源与用途。", "minutes": 10, "steps": [("读取契约", "比较路径参数和查询参数的语义。", "每个输入有唯一位置。"), ("填写表格", "将三个输入放入对应槽位。", "表格不出现重复归属。"), ("举反例", "写出一个放错位置会造成的现象。", "能说明为什么错。" )], "acceptance": ["完成参数位置表", "解释一个放错参数的后果"]}, {"id": "validate", "level": "core", "title": "补齐输入校验 starter", "knowledge": [2], "task_kind": "implementation", "artifact_kind": "source-code", "capabilities": ["code_editing", "execution", "explanation"], "overview": "在完整 Python 函数框架中补三个会改变响应语义的 TODO。", "scaffold": "保留函数、输入字典、返回结构和三个关键空位；先按阶段修改，再运行 py_compile 和样例。", "minutes": 16, "steps": [("先改状态", "完成 TODO 1 后解释成功状态的契约。", "状态文本符合接口约定。"), ("补边界", "完成 TODO 2，分别测试有效、空白和缺失姓名。", "三类输入得到可解释差异。"), ("补字段", "完成 TODO 3 并检查返回字段是否完整。", "响应结构与样例一致。"), ("回归", "运行编译检查并口头解释三个 TODO 的作用。", "能说明修改如何影响结果。" )], "acceptance": ["三个 TODO 都有真实改动", "样例和边界输入结果可解释", "能说明校验发生在业务处理前"], "asset": web_asset, "todo_count": 3, "verification": "用 Python 3.12 执行 py_compile，并用三条字典输入检查响应字段。", "reference_result": "有效输入返回 accepted 和 normalized=true；空白输入返回 invalid。"}, {"id": "debug", "level": "core", "title": "诊断响应字段缺失", "knowledge": [3], "task_kind": "debugging", "artifact_kind": "result", "capabilities": ["diagnosis", "explanation"], "overview": "根据现象卡找出响应不完整的最小原因。", "scaffold": "给出预期/实际对照表和三条可能原因。", "minutes": 12, "steps": [("对照字段", "逐项比较预期与实际响应。", "找到第一个差异。"), ("回查动作", "回到校验和返回结构，排除无关修改。", "说出最小原因。"), ("写回归", "增加一条能暴露同类问题的检查。", "检查能重复执行。" )], "acceptance": ["指出最早差异", "给出一个最小修复和回归检查"]}, {"id": "scenario", "level": "core", "title": "设计三条接口验收场景", "knowledge": [4], "task_kind": "experiment", "artifact_kind": "scenario", "capabilities": ["scenario_reasoning", "explanation"], "overview": "为同一接口安排正常、边界和缺失输入三类场景。", "scaffold": "提供场景表头、输入槽和预期响应槽。", "minutes": 12, "steps": [("写正常例", "填入有效姓名并写预期字段。", "结果覆盖状态和姓名。"), ("写边界例", "填入空白姓名并写预期状态。", "边界能区分实现。"), ("交换检查", "与同伴互换场景表并找一个遗漏。", "能解释遗漏影响。" )], "acceptance": ["三类场景均有输入和预期", "至少一条边界能区分错误实现"]}, {"id": "docs", "level": "optional", "title": "比较两种参数设计", "knowledge": [1, 3], "task_kind": "analysis", "artifact_kind": "document", "capabilities": ["comparison", "explanation"], "overview": "比较路径参数与查询参数在接口可读性上的取舍。", "scaffold": "提供两种方案和同一业务场景。", "minutes": 10, "steps": [("看方案", "标出两种方案的输入差别。", "能指出差别。"), ("比影响", "比较缓存、可读性和错误提示。", "至少写两个依据。"), ("做选择", "为当前场景选择方案并解释。", "解释与理论一致。" )], "acceptance": ["完成两方案比较", "能为选择给出依据"]}, {"id": "boundary", "level": "optional", "title": "扩展边界检查表", "knowledge": [2, 4], "task_kind": "analysis", "artifact_kind": "document", "capabilities": ["scenario_reasoning", "comparison"], "overview": "为接口增加长度、空白和类型边界。", "scaffold": "提供已有三条场景和四个边界槽位。", "minutes": 10, "steps": [("列边界", "按字段类型补充边界。", "每个边界可执行。"), ("排序", "按风险排列测试顺序。", "先测最能区分实现的项。"), ("回带代码", "指出哪些边界由 TODO 2 覆盖。", "能对应代码位置。" )], "acceptance": ["新增至少两个边界", "边界能回连到代码或理论"]}, {"id": "transfer", "level": "challenge", "title": "为新资源写接口契约", "knowledge": [0, 4], "task_kind": "scenario", "artifact_kind": "document", "capabilities": ["scenario_reasoning", "explanation"], "overview": "把同样的校验思路迁移到课程资源查询接口。", "scaffold": "提供资源字段清单和契约模板。", "minutes": 12, "steps": [("选字段", "区分路径、查询和响应字段。", "字段有明确语义。"), ("定边界", "写一个空结果和一个无效条件。", "边界可观察。"), ("讲清楚", "向同伴说明契约如何支持回归。", "说明有理论依据。" )], "acceptance": ["完成一个可读契约", "包含正常与边界场景"]}]
    result.append({"id": "web-api", "name": "Python Web 接口基础", "chapter": "请求校验与可观察接口", "practice_title": "实践：把请求契约落成可验证响应", "audience": "高职软件开发专业学生", "context": web_context, "units": web_units, "tasks": web_tasks, "centers": [{"title": "请求证据映射", "tasks": [0]}, {"title": "接口状态推演", "tasks": [0, 2]}, {"title": "参数契约逐步检查", "tasks": [1]}, {"title": "响应缺失诊断", "tasks": [3]}, {"title": "连续验收题组", "tasks": [2, 4]}, {"title": "动作角色分类", "tasks": [1, 3]}, {"title": "场景验收排序", "tasks": [4, 7]}]})

    def general_spec(course_id: str, name: str, chapter: str, practice_title: str, audience: str, context: dict[str, Any], units: list[dict[str, str]], tasks: list[dict[str, Any]], centers: list[dict[str, Any]]) -> dict[str, Any]:
        return {"id": course_id, "name": name, "chapter": chapter, "practice_title": practice_title, "audience": audience, "context": context, "units": units, "tasks": tasks, "centers": centers}

    spreadsheet_context = _context("Excel 数据处理基础", "高职财经与信息管理专业学生", "Excel 公式", ["Microsoft Excel", "Power Query"], "Windows", "Microsoft Excel 365", other_constraints=["不使用宏，保留每一步可追溯"])
    spreadsheet_units = [{"title": "字段与数据类型", "know": "字段含义和数据类型决定后续筛选与计算是否可靠", "able": "能识别日期、文本和数值字段", "example": "订单日期、地区和金额三列", "fact": "先确认字段语义，再做计算或筛选", "misconception": "看到数字就一定可以直接相加", "boundary": "空值与文本数字", "kit_kind": "工作表基础"}, {"title": "清洗与筛选", "know": "清洗要保留原始证据并明确每个修正规则", "able": "能用筛选找出空值和异常格式", "example": "地区名称有前后空格", "fact": "清洗规则必须能说明哪些行被改变", "misconception": "直接覆盖原表就算完成清洗", "boundary": "空格、空值和重复行", "kit_kind": "筛选清洗"}, {"title": "公式与引用", "know": "相对引用和绝对引用决定填充公式是否仍指向正确条件", "able": "能解释一个公式在下拉后的引用变化", "example": "金额乘税率并按地区查找", "fact": "复制公式前必须确认变化的行列和固定的条件", "misconception": "所有引用在复制时都应移动", "boundary": "固定税率与变化金额", "kit_kind": "公式引用"}, {"title": "汇总与透视", "know": "汇总结果的粒度必须和业务问题一致", "able": "能按月份或地区得到可解释汇总", "example": "按地区统计订单金额和笔数", "fact": "先确定一行代表什么，再选择汇总字段", "misconception": "结果数字对了就不必说明粒度", "boundary": "明细行与汇总行", "kit_kind": "透视分析"}, {"title": "结果复核", "know": "结果复核要用总量、边界行和抽样行交叉检查", "able": "能找到一个汇总异常并说明检查路径", "example": "透视总额与明细总额不一致", "fact": "总量核对和抽样核对要同时存在", "misconception": "只看图表外观就算验证", "boundary": "漏行与重复计数", "kit_kind": "结果复核"}]
    spreadsheet_tasks = [{"id": "inspect", "level": "core", "title": "识别表格字段与粒度", "knowledge": [0], "task_kind": "observation", "artifact_kind": "workbook", "capabilities": ["file_editing", "explanation"], "overview": "打开订单样例，给字段贴上类型和含义标签。", "scaffold": "提供带表头和六行数据的 CSV 起点。", "minutes": 8, "steps": [("看表头", "逐列写出业务含义。", "每列都有解释。"), ("标类型", "区分日期、文本、数值和空值。", "类型与样例一致。"), ("说粒度", "说明一行订单还是一项商品。", "能指导后续汇总。" )], "acceptance": ["完成字段标签", "说出一行代表的对象"], "asset": _text_asset("orders", "orders.csv", "CSV", "order_id,order_date,region,amount\nA01,2025-04-01,华东,120\nA02,2025-04-02,华南,80\nA03,2025-04-02,华东,50\n")}, {"id": "clean", "level": "core", "title": "按规则清洗异常字段", "knowledge": [1], "task_kind": "tooling", "artifact_kind": "workbook", "capabilities": ["file_editing", "diagnosis"], "overview": "在副本上清理空格、空值和重复订单。", "scaffold": "给出三条异常记录和清洗规则卡。", "minutes": 10, "steps": [("筛异常", "用筛选找出三类异常。", "每类至少找到一行。"), ("留证据", "记录原值和修正动作。", "原值可回查。"), ("再筛选", "重新筛选确认规则已生效。", "异常行状态可解释。" )], "acceptance": ["三类异常都有处理记录", "清洗后能解释改变范围"]}, {"id": "formula", "level": "core", "title": "填充公式并核对引用", "knowledge": [2], "task_kind": "implementation", "artifact_kind": "workbook", "capabilities": ["file_editing", "explanation"], "overview": "填写金额计算列，检查税率条件在下拉时是否固定。", "scaffold": "提供金额、税率和地区列，公式列留出首行起点。", "minutes": 14, "steps": [("写首行", "在首行建立金额乘税率公式。", "首行结果可手算复核。"), ("拖填", "向下填充并观察引用变化。", "固定条件仍指向税率单元格。"), ("抽查", "挑一行手算并对照。", "差异能定位到引用。" )], "acceptance": ["公式填充完整", "能解释一个相对/绝对引用"]}, {"id": "pivot", "level": "core", "title": "按正确粒度做汇总", "knowledge": [3], "task_kind": "experiment", "artifact_kind": "workbook", "capabilities": ["file_editing", "visualization", "explanation"], "overview": "按地区汇总订单笔数和金额，并说明一行汇总代表什么。", "scaffold": "提供明细表和两个业务问题。", "minutes": 12, "steps": [("定粒度", "先写每一行汇总代表的地区。", "粒度先于拖字段。"), ("建汇总", "放入地区、笔数和金额。", "两种指标都出现。"), ("解释", "比较华东与华南差异。", "解释引用明细证据。" )], "acceptance": ["汇总粒度正确", "笔数和金额均可解释"]}, {"id": "verify", "level": "core", "title": "找出汇总与明细的差异", "knowledge": [4], "task_kind": "debugging", "artifact_kind": "result", "capabilities": ["diagnosis", "comparison", "explanation"], "overview": "根据总量和抽样行定位一次汇总异常。", "scaffold": "给出明细总额、汇总总额和两条抽样记录。", "minutes": 12, "steps": [("比总量", "比较明细与汇总总额。", "确认是否存在差异。"), ("抽样行", "回到一条边界日期记录。", "能提出一个原因。"), ("最小修复", "只修正一个筛选或重复条件并回算。", "总量恢复一致。" )], "acceptance": ["指出差异来源", "给出最小修复并复核总量"]}, {"id": "chart", "level": "optional", "title": "把汇总转成可读图表", "knowledge": [3, 4], "task_kind": "tooling", "artifact_kind": "workbook", "capabilities": ["visualization", "comparison"], "overview": "选择适合比较地区金额的图表，并标注口径。", "scaffold": "提供同一汇总表和两种图表候选。", "minutes": 10, "steps": [("选图", "比较柱形和折线适用条件。", "选择与离散类别匹配的形式。"), ("加口径", "标注金额单位和时间范围。", "图表读者不需猜口径。"), ("复核", "从图表回查一个明细数字。", "图表与表格一致。" )], "acceptance": ["图表选择有依据", "标注口径并完成回查"]}, {"id": "power", "level": "optional", "title": "设计一条可复用清洗路径", "knowledge": [1, 2], "task_kind": "tooling", "artifact_kind": "workbook", "capabilities": ["file_editing", "scenario_reasoning"], "overview": "把一次清洗步骤排成可重复执行的路径。", "scaffold": "提供原始表、规则卡和操作顺序槽。", "minutes": 10, "steps": [("拆步骤", "分离导入、清洗和检查。", "每步有输入输出。"), ("排顺序", "把不可交换的步骤放对位置。", "先保留证据再改值。"), ("写自检", "给每步加一个可观察检查。", "路径可复用。" )], "acceptance": ["完成可重复路径", "每步都有检查点"]}, {"id": "dashboard", "level": "challenge", "title": "为业务问题构造小型看板", "knowledge": [0, 3, 4], "task_kind": "scenario", "artifact_kind": "workbook", "capabilities": ["visualization", "scenario_reasoning", "explanation"], "overview": "从业务问题出发选择字段、粒度和一个可解释图表。", "scaffold": "提供问题卡、字段清单和看板草图。", "minutes": 14, "steps": [("拆问题", "把业务问题拆成指标与筛选条件。", "指标可计算。"), ("定粒度", "说明一行图表数据代表什么。", "粒度不混乱。"), ("讲结果", "向同伴说明看板如何支持判断。", "说明有证据。" )], "acceptance": ["完成问题—指标—图表链", "能用一条明细记录解释看板结果"]}]
    spreadsheet_tasks[2]["asset"] = _text_asset("formula-card", "formula-card.csv", "CSV", "region,amount,tax_rate,total\n华东,120,0.06,TODO\n华南,80,0.06,TODO\n")
    result.append(general_spec("spreadsheet", "Excel 数据处理基础", "字段清洗与可解释汇总", "实践：从明细表到可复核汇总", "高职财经与信息管理专业学生", spreadsheet_context, spreadsheet_units, spreadsheet_tasks, [{"title": "字段类型映射", "tasks": [0]}, {"title": "清洗状态推演", "tasks": [0, 1]}, {"title": "公式引用逐步检查", "tasks": [2]}, {"title": "汇总异常诊断", "tasks": [3, 4]}, {"title": "结果复核题组", "tasks": [3, 4]}, {"title": "动作角色分类", "tasks": [1, 2]}, {"title": "看板制作排序", "tasks": [5, 7]}]))

    network_context = _context("计算机网络基础", "高职网络技术专业学生", "IPv4", ["Wireshark", "Cisco Packet Tracer"], "Windows", "Wireshark 4", other_constraints=["先观察抓包证据，再改网络配置"])
    network_units = [{"title": "地址与子网", "know": "IPv4 地址、掩码和网络边界共同决定主机是否同网段", "able": "能根据地址和掩码判断网络边界", "example": "192.168.10.23/24 的网络号", "fact": "掩码不是装饰，它决定可达判断的边界", "misconception": "只看地址前两段就能判断同网段", "boundary": "/24 与 /26", "kit_kind": "地址换算"}, {"title": "链路与 ARP", "know": "同网段发送前需要通过 ARP 找到下一跳的链路地址", "able": "能从抓包顺序解释 ARP 请求与应答", "example": "先广播询问再单播发送", "fact": "ARP 证据应先于后续数据帧出现", "misconception": "看到 IP 就等于知道链路地址", "boundary": "缓存命中与未命中", "kit_kind": "抓包筛选"}, {"title": "路由与 TTL", "know": "路由器按下一跳转发并让 TTL 逐跳减少", "able": "能沿路径写出每跳的观察结果", "example": "客户端到服务端经过两台路由器", "fact": "TTL 变化可以帮助定位路径是否真的经过某一跳", "misconception": "TTL 由终端在每一跳重新设回初值", "boundary": "到达与超时", "kit_kind": "路径跟踪"}, {"title": "故障定位", "know": "网络诊断要区分地址、链路、路由和服务层症状", "able": "能根据现象选择最小检查", "example": "能 ping 网关但不能访问服务", "fact": "最小检查应从最靠近现象的一层开始", "misconception": "任何失败都先重启所有设备", "boundary": "网关可达与端口不可达", "kit_kind": "分层诊断"}, {"title": "证据闭环", "know": "一次诊断需要把现象、抓包证据和修复后的回归结果连起来", "able": "能写出一条可复核诊断记录", "example": "修复路由后再次观察 SYN/ACK", "fact": "修复后必须回到同一证据点做回归", "misconception": "配置保存成功就等于业务恢复", "boundary": "配置状态与实际流量", "kit_kind": "诊断记录"}]
    network_tasks = [{"id": "address", "level": "core", "title": "判断两个主机是否同网段", "knowledge": [0], "task_kind": "analysis", "artifact_kind": "result", "capabilities": ["state_tracking", "explanation"], "overview": "用地址和掩码卡判断两台主机的网络边界。", "scaffold": "提供四组地址/掩码和网络号槽位。", "minutes": 8, "steps": [("抄地址", "把地址与掩码分列。", "不混用主机号。"), ("算边界", "写出网络号并比较。", "每组结论有依据。"), ("说例外", "找一组最容易看错的边界。", "能说明掩码作用。" )], "acceptance": ["完成四组同网段判断", "解释掩码改变边界的方式"]}, {"id": "arp", "level": "core", "title": "按抓包顺序解释 ARP", "knowledge": [1], "task_kind": "observation", "artifact_kind": "result", "capabilities": ["state_tracking", "explanation"], "overview": "从一个抓包片段中排列 ARP 请求、应答和后续数据。", "scaffold": "给出四条带方向和地址的帧记录。", "minutes": 10, "steps": [("认广播", "找出询问目标链路地址的帧。", "能解释广播范围。"), ("找应答", "配对请求和应答。", "请求方与应答方对应。"), ("接数据", "说明为什么后续才能发送数据。", "链路证据完整。" )], "acceptance": ["正确解释 ARP 顺序", "指出一次缓存命中或未命中"]}, {"id": "ttl", "level": "core", "title": "追踪 TTL 的逐跳变化", "knowledge": [2], "task_kind": "experiment", "artifact_kind": "result", "capabilities": ["state_tracking", "visualization", "explanation"], "overview": "沿三跳路径填写每跳 TTL 与下一跳。", "scaffold": "提供初始 TTL、路径节点和状态表。", "minutes": 14, "steps": [("填首跳", "记录客户端发出的 TTL。", "初值明确。"), ("逐跳减", "按路由器顺序填写变化。", "每一跳只减少一次。"), ("核对终点", "比较服务端收到的值和路径。", "能排除一跳遗漏。" )], "acceptance": ["完成三跳状态表", "解释 TTL 对路径定位的帮助"]}, {"id": "layer-debug", "level": "core", "title": "按分层证据定位故障", "knowledge": [3], "task_kind": "debugging", "artifact_kind": "result", "capabilities": ["diagnosis", "explanation"], "overview": "根据网关、端口和服务现象选择最小检查。", "scaffold": "提供三种现象和四层检查卡。", "minutes": 12, "steps": [("分层", "把现象放到地址、链路、路由或服务层。", "一层一结论。"), ("选检查", "选择能排除最大范围的最小命令/观察。", "检查与现象匹配。"), ("写原因", "将结果连接到一条理论事实。", "原因不是猜测。" )], "acceptance": ["三种现象均有分层判断", "每种判断有一个最小检查"]}, {"id": "evidence", "level": "core", "title": "形成网络诊断证据链", "knowledge": [4], "task_kind": "tooling", "artifact_kind": "document", "capabilities": ["file_editing", "explanation"], "overview": "把抓包、配置和回归结果整理成一条诊断记录。", "scaffold": "提供现象—证据—动作—回归四列表格。", "minutes": 12, "steps": [("记现象", "写出用户可感知的失败。", "现象可复现。"), ("挂证据", "贴一条抓包或路径观察。", "证据能定位层次。"), ("做回归", "修复后重复同一观察。", "前后结果可比较。" )], "acceptance": ["四列记录完整", "回归观察与原证据对应"]}, {"id": "filters", "level": "optional", "title": "设计 Wireshark 过滤器练习", "knowledge": [1, 2], "task_kind": "tooling", "artifact_kind": "document", "capabilities": ["file_editing", "comparison"], "overview": "为 ARP、ICMP 和 TCP 三种观察目的选择过滤条件。", "scaffold": "提供三种问题和候选过滤卡。", "minutes": 10, "steps": [("对问题", "把问题和协议字段配对。", "每个问题有一个筛选方向。"), ("试过滤", "在样例包中观察剩余帧。", "过滤后仍保留目标证据。"), ("写解释", "说明为何其他过滤会漏掉证据。", "解释可复核。" )], "acceptance": ["三个问题都有过滤方案", "能解释一个漏证据的方案"]}, {"id": "latency", "level": "optional", "title": "比较延迟与丢包现象", "knowledge": [2, 3], "task_kind": "analysis", "artifact_kind": "result", "capabilities": ["comparison", "scenario_reasoning"], "overview": "比较同一路径的高延迟和丢包记录，区分症状。", "scaffold": "提供两段时间序列和路径摘要。", "minutes": 10, "steps": [("读序列", "标出延迟尖峰和缺失回应。", "证据标记清楚。"), ("连路径", "比较两段记录经过的节点。", "不把两个层次混为一谈。"), ("提动作", "为每种现象给一个小检查。", "动作与现象相邻。" )], "acceptance": ["正确区分两类现象", "每类都有后续检查"]}, {"id": "incident", "level": "challenge", "title": "模拟一次服务恢复演练", "knowledge": [3, 4], "task_kind": "scenario", "artifact_kind": "scenario", "capabilities": ["scenario_reasoning", "diagnosis", "explanation"], "overview": "从用户报障开始完成分层定位、最小修复和回归。", "scaffold": "提供报障卡、三条观察结果和回归表。", "minutes": 14, "steps": [("定层", "根据第一条证据缩小范围。", "不跳层。"), ("选修复", "只改变一个路由或服务条件。", "修复可回退。"), ("回归讲解", "重复原观察并向同伴解释。", "恢复有证据。" )], "acceptance": ["形成一条完整证据链", "能说明为何没有盲目重启全部设备"]}]
    result.append(general_spec("networking", "计算机网络基础", "IPv4 路径观察与故障诊断", "实践：用抓包证据定位网络问题", "高职网络技术专业学生", network_context, network_units, network_tasks, [{"title": "地址边界判断", "tasks": [0]}, {"title": "链路状态推演", "tasks": [1, 2]}, {"title": "TTL 路径逐步追踪", "tasks": [2]}, {"title": "分层故障诊断", "tasks": [3]}, {"title": "连续证据题组", "tasks": [3, 4]}, {"title": "动作角色分类", "tasks": [1, 4]}, {"title": "恢复演练排序", "tasks": [4, 7]}]))

    ai_context = _context("AI 分类评估基础", "高职人工智能应用专业学生", "Python", ["JupyterLab", "NumPy"], "Windows", "JupyterLab", framework="NumPy", other_constraints=["只使用已给标签和预测结果，不引入新模型训练"])
    ai_asset = _code_asset("metrics", "metrics.py", "Python", '''def classification_metrics(predicted, actual):\n    tp = 0  # TODO 1\n    fp = 0  # TODO 2\n    fn = 0  # TODO 3\n    precision = 0 if tp + fp == 0 else tp / (tp + fp)\n    return {"precision": precision, "tp": tp, "fp": fp, "fn": fn}\n''', [_gap("tp = 0  # TODO 1", "tp = 0  # TODO 1", "tp = sum(1 for p, a in zip(predicted, actual) if p == 1 and a == 1)  # TODO 1", "统计预测为正且实际为正的样本。", "metric"), _gap("fp = 0  # TODO 2", "fp = 0  # TODO 2", "fp = sum(1 for p, a in zip(predicted, actual) if p == 1 and a == 0)  # TODO 2", "统计误报样本。", "metric"), _gap("fn = 0  # TODO 3", "fn = 0  # TODO 3", "fn = sum(1 for p, a in zip(predicted, actual) if p == 0 and a == 1)  # TODO 3", "统计漏报样本。", "metric")])
    ai_units = [{"title": "标签与预测", "know": "评估先要明确实际标签和模型预测分别代表什么", "able": "能把一条样本放入正确的比较位置", "example": "预测为正但实际为负的样本", "fact": "同一个样本的预测和实际标签必须成对比较", "misconception": "预测为正就等于实际为正", "boundary": "正例与负例", "kit_kind": "数组配对"}, {"title": "混淆矩阵", "know": "TP、FP、FN、TN 把分类结果按两个维度拆开", "able": "能从样本表数出四类结果", "example": "四格矩阵中的误报与漏报", "fact": "矩阵四格互斥且覆盖全部样本", "misconception": "只看正确率就能知道错误类型", "boundary": "误报与漏报", "kit_kind": "矩阵填表"}, {"title": "Precision 与 Recall", "know": "Precision 关注预测为正的可信度，Recall 关注实际正例被找回的比例", "able": "能根据业务风险选择关注指标", "example": "告警系统宁可少漏报还是少误报", "fact": "分母不同导致两个指标回答不同问题", "misconception": "两个指标只是不同叫法", "boundary": "分母和业务代价", "kit_kind": "指标公式"}, {"title": "阈值变化", "know": "改变阈值会同时改变预测标签和指标，不应只看单个数字", "able": "能比较两个阈值下的结果差异", "example": "阈值从 0.5 调到 0.7", "fact": "阈值选择应由错误代价和验证证据共同决定", "misconception": "阈值越高模型一定越好", "boundary": "指标权衡", "kit_kind": "阈值实验"}, {"title": "评估结论", "know": "评估结论必须说明数据、指标、阈值和风险边界", "able": "能写出带条件的评估结论", "example": "在验证集上 recall 提升但误报增加", "fact": "一个指标上升不自动等于模型适合部署", "misconception": "最高分数就是唯一选择", "boundary": "验证与部署", "kit_kind": "结论表达"}]
    ai_tasks = [{"id": "pair", "level": "core", "title": "配对预测与实际标签", "knowledge": [0], "task_kind": "observation", "artifact_kind": "result", "capabilities": ["state_tracking", "explanation"], "overview": "逐行对齐预测数组与实际标签数组。", "scaffold": "给出八条成对数据和四格标签卡。", "minutes": 8, "steps": [("对齐", "把每个预测和实际标签放在同一行。", "没有错位。"), ("标记", "标出预测正、实际负的行。", "找到误报候选。"), ("解释", "说明为什么只看预测值不够。", "解释引用标签。" )], "acceptance": ["完成逐行配对", "指出一类错误样本"]}, {"id": "matrix", "level": "core", "title": "填写混淆矩阵四格", "knowledge": [1], "task_kind": "analysis", "artifact_kind": "result", "capabilities": ["state_tracking", "visualization", "explanation"], "overview": "把样本表归入 TP、FP、FN、TN 并核对总数。", "scaffold": "提供标签对照表和四格空表。", "minutes": 12, "steps": [("逐行分类", "按预测/实际组合给每行贴标签。", "每行只进一格。"), ("汇总", "数出四格数量。", "四格合计等于样本数。"), ("解释", "说出误报与漏报差别。", "业务含义清楚。" )], "acceptance": ["四格数值正确", "四格合计与样本数一致"]}, {"id": "metrics", "level": "core", "title": "补齐指标计算 starter", "knowledge": [2], "task_kind": "implementation", "artifact_kind": "source-code", "capabilities": ["code_editing", "execution", "explanation"], "overview": "在完整 Python 函数中补三个真实统计位置，再编译并对照手算。", "scaffold": "保留函数参数、返回字典和指标公式，只留下 TP/FP/FN 三个关键空位。", "minutes": 16, "steps": [("补 TP", "按预测和实际同时为正的条件填写。", "TP 与手算一致。"), ("补 FP/FN", "分别填写误报和漏报条件。", "两个错误类型不混淆。"), ("跑样例", "用八条标签检查返回字典。", "输出包含三类计数和 precision。"), ("解释分母", "说明 precision 为什么使用 TP+FP。", "能联系理论事实。" )], "acceptance": ["三个 TODO 都有真实统计逻辑", "py_compile 通过且结果可手算", "能解释 precision 分母"], "asset": ai_asset, "todo_count": 3, "verification": "用 Python py_compile 并以八条固定标签手算 TP/FP/FN。", "reference_result": "返回字典的 TP、FP、FN 与混淆矩阵一致。"}, {"id": "threshold", "level": "core", "title": "比较两个阈值的指标代价", "knowledge": [3], "task_kind": "experiment", "artifact_kind": "result", "capabilities": ["comparison", "scenario_reasoning", "explanation"], "overview": "根据概率表比较阈值 0.5 和 0.7 的错误变化。", "scaffold": "提供概率、标签和两个阈值的结果槽。", "minutes": 12, "steps": [("定预测", "按每个阈值给概率贴预测标签。", "阈值规则一致。"), ("算变化", "比较两组误报和漏报。", "变化有证据。"), ("选场景", "为高漏报代价场景选择阈值。", "选择引用业务风险。" )], "acceptance": ["完成两阈值比较", "能说明阈值选择与风险关系"]}, {"id": "conclude", "level": "core", "title": "写一条带边界的评估结论", "knowledge": [4], "task_kind": "analysis", "artifact_kind": "document", "capabilities": ["explanation", "scenario_reasoning"], "overview": "把数据、指标、阈值和风险写进一段可审阅结论。", "scaffold": "提供结论四要素句式和一组验证结果。", "minutes": 10, "steps": [("填数据", "写清验证集和样本范围。", "范围可复核。"), ("报指标", "说明 precision/recall 的变化。", "不只报一个分数。"), ("写边界", "指出尚不能推出的结论。", "避免过度承诺。" )], "acceptance": ["结论覆盖四要素", "明确一个风险边界"]}, {"id": "tradeoff", "level": "optional", "title": "做一次指标取舍讨论", "knowledge": [2, 3], "task_kind": "scenario", "artifact_kind": "scenario", "capabilities": ["comparison", "scenario_reasoning"], "overview": "为告警、筛查和推荐三个场景选择更关注的指标。", "scaffold": "提供三张业务风险卡和两组指标。", "minutes": 10, "steps": [("看风险", "找出漏报和误报哪一个更昂贵。", "风险描述具体。"), ("选指标", "将场景与指标连线。", "选择有分母依据。"), ("说反例", "指出指标高但仍不合适的情况。", "能说明数据边界。" )], "acceptance": ["三个场景都有选择", "每个选择有风险依据"]}, {"id": "slice", "level": "optional", "title": "检查一个数据切片", "knowledge": [0, 4], "task_kind": "analysis", "artifact_kind": "result", "capabilities": ["diagnosis", "comparison"], "overview": "比较整体指标与一个子群体指标，寻找可能差异。", "scaffold": "提供整体和子群体两组四格计数。", "minutes": 10, "steps": [("比四格", "比较两组矩阵。", "找到一项差异。"), ("找原因", "提出一个需要继续验证的原因。", "不把猜测当结论。"), ("写后续", "为子群体设计一个回查动作。", "动作可执行。" )], "acceptance": ["指出一个可解释差异", "写出后续验证动作"]}, {"id": "policy", "level": "challenge", "title": "提出一份阈值评估策略", "knowledge": [3, 4], "task_kind": "scenario", "artifact_kind": "document", "capabilities": ["scenario_reasoning", "explanation", "comparison"], "overview": "为一个需要控制漏报的场景提出阈值评估策略。", "scaffold": "提供风险说明、概率表和结论模板。", "minutes": 12, "steps": [("定义目标", "写明优先控制哪类错误。", "目标能转成指标。"), ("设计比较", "安排至少两个阈值和一条回归检查。", "比较可复核。"), ("说明边界", "写出尚需更多数据的地方。", "策略不过度承诺。" )], "acceptance": ["策略包含指标、阈值和回归", "写明数据边界"]}]
    result.append(general_spec("ai-evaluation", "AI 分类评估基础", "混淆矩阵、指标与阈值选择", "实践：从分类结果到有边界的评估结论", "高职人工智能应用专业学生", ai_context, ai_units, ai_tasks, [{"title": "标签配对判断", "tasks": [0]}, {"title": "混淆矩阵状态", "tasks": [0, 1]}, {"title": "指标计算过程", "tasks": [1, 2]}, {"title": "阈值变化诊断", "tasks": [3]}, {"title": "连续评估题组", "tasks": [2, 3, 4]}, {"title": "证据动作分类", "tasks": [1, 4]}, {"title": "策略步骤排序", "tasks": [4, 7]}]))

    testing_context = _context("软件测试设计基础", "高职软件技术专业学生", "测试设计", ["TestRail", "Microsoft Excel"], "Windows", "TestRail", framework="Gherkin", other_constraints=["本次只设计可执行测试，不要求编写应用代码"])
    testing_units = [{"title": "需求与测试目标", "know": "测试目标要从需求行为和可观察结果中来", "able": "能把一句需求拆成可验证行为", "example": "登录失败三次后锁定账户", "fact": "测试用例必须能指出触发条件、动作和预期结果", "misconception": "把功能名称当成测试目标", "boundary": "前置条件与结果", "kit_kind": "需求拆解"}, {"title": "等价类与边界", "know": "等价类减少重复，边界值暴露规则切换处的错误", "able": "能为一个输入划分有效和无效类", "example": "密码长度 8 到 20 位", "fact": "边界值应覆盖刚好满足与刚好不满足的位置", "misconception": "只测一个正常值就代表整个范围", "boundary": "7、8、20、21", "kit_kind": "边界设计"}, {"title": "决策表", "know": "多个条件共同决定结果时需要显式列出组合", "able": "能把条件组合整理成互斥规则", "example": "会员、库存和优惠券共同决定折扣", "fact": "决策表每列都应对应一条可执行规则", "misconception": "把条件写在一段话里就等于覆盖组合", "boundary": "组合遗漏与重复", "kit_kind": "决策表"}, {"title": "缺陷分诊", "know": "缺陷优先级要同时看影响范围、复现稳定性和业务风险", "able": "能为缺陷选择优先级并说明依据", "example": "支付成功但订单状态未更新", "fact": "优先级不是严重程度的同义词，需要可解释依据", "misconception": "所有阻塞都按个人感觉排序", "boundary": "影响与复现", "kit_kind": "缺陷分诊"}, {"title": "回归与覆盖", "know": "回归集合要覆盖修复点和受影响路径，而不是无限增加用例", "able": "能从一个缺陷选择最小回归集合", "example": "修复优惠券后检查结算和退款", "fact": "回归选择要能回到需求规则和影响路径", "misconception": "用例越多覆盖就一定越好", "boundary": "最小集合与遗漏风险", "kit_kind": "回归选择"}]
    testing_tasks = [{"id": "goal", "level": "core", "title": "把需求改写成可观察目标", "knowledge": [0], "task_kind": "analysis", "artifact_kind": "document", "capabilities": ["file_editing", "explanation"], "overview": "从一条登录需求拆出触发条件、动作和结果。", "scaffold": "提供需求句、三列表和一个反例。", "minutes": 8, "steps": [("找触发", "标出前置条件和输入。", "触发条件具体。"), ("写动作", "写学生或系统要做的动作。", "动作可执行。"), ("写结果", "写出可观察结果和失败结果。", "结果不含模糊词。" )], "acceptance": ["完成三列表", "正反结果都可观察"]}, {"id": "boundary", "level": "core", "title": "设计等价类与边界用例", "knowledge": [1], "task_kind": "analysis", "artifact_kind": "document", "capabilities": ["file_editing", "scenario_reasoning"], "overview": "为密码长度规则选择最小而有代表性的输入。", "scaffold": "提供 8—20 位规则、输入槽和预期槽。", "minutes": 12, "steps": [("划分", "写出有效、过短、过长三类。", "每类有代表。"), ("选边界", "填写 7、8、20、21 四个值。", "边界覆盖完整。"), ("说明", "解释为什么不需要遍历所有长度。", "说明引用等价类。" )], "acceptance": ["三类等价类完整", "四个边界值有预期结果"]}, {"id": "decision", "level": "core", "title": "把条件组合变成决策表", "knowledge": [2], "task_kind": "modeling", "artifact_kind": "document", "capabilities": ["file_editing", "visualization", "explanation"], "overview": "为会员、库存和优惠券规则构造互斥测试列。", "scaffold": "提供三个条件、四种结果和空决策表。", "minutes": 14, "steps": [("列条件", "把条件拆成可判断的是/否。", "条件互斥清楚。"), ("补组合", "覆盖正常、缺货和无券组合。", "每列有动作。"), ("查遗漏", "用反例检查是否有组合没有结果。", "遗漏可定位。" )], "acceptance": ["每列是一条可执行规则", "至少覆盖一个缺货反例"]}, {"id": "triage", "level": "core", "title": "按证据给缺陷分诊", "knowledge": [3], "task_kind": "debugging", "artifact_kind": "result", "capabilities": ["diagnosis", "comparison", "explanation"], "overview": "根据影响、复现和业务风险安排缺陷顺序。", "scaffold": "提供三个缺陷卡和统一分诊表。", "minutes": 12, "steps": [("读现象", "分离用户影响和技术描述。", "现象可复述。"), ("看复现", "标记稳定、偶发和不可复现。", "证据明确。"), ("定优先", "写出排序及至少一条依据。", "排序不是凭感觉。" )], "acceptance": ["三条缺陷均有优先级", "排序有风险和复现依据"]}, {"id": "regression", "level": "core", "title": "选择最小回归集合", "knowledge": [4], "task_kind": "scenario", "artifact_kind": "document", "capabilities": ["scenario_reasoning", "explanation"], "overview": "从修复点和影响路径中选出必须回归的用例。", "scaffold": "提供修复描述、五条候选用例和影响图。", "minutes": 10, "steps": [("找修复点", "标出直接改变的规则。", "规则与用例相连。"), ("扩影响", "沿依赖路径选择间接影响。", "不漏关键路径。"), ("定集合", "删除不必要重复用例并解释。", "集合最小但有理由。" )], "acceptance": ["直接和间接影响均覆盖", "能解释一个被删除的重复项"]}, {"id": "gherkin", "level": "optional", "title": "把用例改写成 Given-When-Then", "knowledge": [0, 1], "task_kind": "tooling", "artifact_kind": "document", "capabilities": ["file_editing", "explanation"], "overview": "将一个边界用例改写成清晰的场景步骤。", "scaffold": "提供三列表和 Gherkin 句式槽位。", "minutes": 10, "steps": [("写 Given", "补前置数据和状态。", "前置可复现。"), ("写 When", "写一个动作。", "动作不混合多个行为。"), ("写 Then", "写可观察结果。", "结果可判定。" )], "acceptance": ["完成一个边界场景", "每个步骤可执行"]}, {"id": "coverage", "level": "optional", "title": "比较覆盖与用例成本", "knowledge": [2, 4], "task_kind": "analysis", "artifact_kind": "result", "capabilities": ["comparison", "scenario_reasoning"], "overview": "比较两套回归集合的覆盖和执行成本。", "scaffold": "提供需求规则、用例集合和执行时长。", "minutes": 10, "steps": [("看覆盖", "标出各集合覆盖的规则。", "覆盖证据明确。"), ("看成本", "比较执行时长和重复项。", "成本可计算。"), ("做取舍", "选择一套并说明风险。", "选择有依据。" )], "acceptance": ["完成两套集合比较", "说明取舍风险"]}, {"id": "release", "level": "challenge", "title": "设计一次发布前风险回归", "knowledge": [3, 4], "task_kind": "scenario", "artifact_kind": "scenario", "capabilities": ["scenario_reasoning", "explanation", "comparison"], "overview": "为高风险支付变更设计发布前的最小回归和停线条件。", "scaffold": "提供变更说明、影响路径和时间预算。", "minutes": 14, "steps": [("识别风险", "连接业务影响和缺陷证据。", "风险可排序。"), ("选回归", "安排最小高价值用例。", "用例覆盖关键规则。"), ("定停线", "写出出现什么证据就不能发布。", "停线条件可观察。" )], "acceptance": ["回归集合和停线条件完整", "能说明每个选择的理论依据"]}]
    result.append(general_spec("software-testing", "软件测试设计基础", "等价类、决策表与风险回归", "实践：从需求规则设计可执行测试", "高职软件技术专业学生", testing_context, testing_units, testing_tasks, [{"title": "需求目标映射", "tasks": [0]}, {"title": "边界值过程", "tasks": [1]}, {"title": "决策表排序", "tasks": [2]}, {"title": "缺陷分诊诊断", "tasks": [3]}, {"title": "连续回归题组", "tasks": [3, 4]}, {"title": "证据动作分类", "tasks": [0, 3]}, {"title": "发布风险排序", "tasks": [4, 7]}]))
    return result


def build_all() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    specs = _specs()
    return [(spec, _courseware(spec)) for spec in specs]


def write_all() -> list[dict[str, Any]]:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    PRACTICE_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for spec, courseware in build_all():
        courseware_path = SOURCE_DIR / f"{spec['id']}.courseware.json"
        practice_path = PRACTICE_DIR / f"{spec['id']}.practice.json"
        practice = _practice(spec, courseware)
        courseware_path.write_text(json.dumps(courseware, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        practice_path.write_text(json.dumps(practice, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        manifest.append({"id": spec["id"], "courseware": courseware_path.name, "practice": practice_path.name, "courseware_sha256": hashlib.sha256(courseware_path.read_bytes()).hexdigest(), "practice_sha256": hashlib.sha256(practice_path.read_bytes()).hexdigest()})
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the five frozen source/contract packs")
    parser.add_argument("--freeze-manifest", action="store_true", help="write source hashes after materializing packs")
    args = parser.parse_args()
    if not args.write and not args.freeze_manifest:
        parser.error("use --write or --freeze-manifest")
    manifest = write_all()
    if args.freeze_manifest:
        MANIFEST.write_text(json.dumps({"status": "frozen-before-first-generation", "holdouts": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": "pass", "holdouts": manifest}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
