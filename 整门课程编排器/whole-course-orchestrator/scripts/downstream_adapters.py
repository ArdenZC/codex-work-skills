"""Small adapters from whole-course plans to the stable downstream contracts.

These adapters own the handoff shape. They do not replace or mock either
downstream renderer; the E2E runner invokes the real renderer entrypoints.
"""

from __future__ import annotations

import html
from typing import Any


RENDERER_LAYOUTS = {"hero", "split", "grid", "focus", "comparison", "timeline", "default"}


COURSEWARE_CONTEXT = {
    "course_name": "Synthetic Whole Course",
    "audience": "高职学生",
    "language": "通用",
    "tools": ["浏览器"],
    "platform": "离线浏览器",
    "software": "浏览器",
}


def _renderer_layout(value: str) -> str:
    value = str(value or "default")
    if value in RENDERER_LAYOUTS:
        return value
    return {"semantic-diagram": "focus", "large-visual": "split", "annotated-object": "split", "step-build": "timeline", "diagnose": "comparison", "check": "split", "summary": "focus", "bridge": "split", "demonstration": "split"}.get(value, "default")


def _typed_structure_svg(artifact: str, roles: list[str]) -> str:
    """Return a small, explicit structure fixture for adapter/E2E tests.

    The fixture is intentionally separate from the marker-only fallback.  Its
    data attributes describe actual node/edge endpoints and labels so the
    collector can prove structure without treating visible role text as proof.
    It is not a claim about visual aesthetics or a production diagram layout.
    """

    requested = {str(item).lower() for item in roles}
    if artifact == "class_model":
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 230" role="img" aria-label="class structure" data-structure-evidence="typed">'
            '<g data-node-id="class-a" data-semantic-role="class class_compartment"><rect x="40" y="70" width="180" height="80"/><text x="130" y="112">ClassA</text></g>'
            '<g data-node-id="class-b" data-semantic-role="class class_compartment"><rect x="540" y="70" width="180" height="80"/><text x="630" y="112">ClassB</text></g>'
            '<line data-edge-id="edge-1" data-semantic-role="relationship association" data-source-id="class-a" data-target-id="class-b" data-relation-kind="association" x1="220" y1="110" x2="540" y2="110"/>'
            '<text data-label-for="edge-1" data-label-kind="multiplicity" data-label-endpoint="source" data-label="1" x="250" y="100">1</text>'
            '<text data-label-for="edge-1" data-label-kind="multiplicity" data-label-endpoint="target" data-label="*" x="500" y="100">*</text>'
            '</svg>'
        )
    if artifact == "sequence_model":
        extra = (
            '<g data-node-id="fragment-1" data-semantic-role="fragment"><rect x="320" y="28" width="300" height="150" fill="none" stroke="#999"/></g>'
            if "fragment" in requested else ""
        )
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 230" role="img" aria-label="sequence structure" data-structure-evidence="typed">'
            '<g data-node-id="lifeline-a" data-semantic-role="lifeline"><line x1="180" y1="40" x2="180" y2="190"/><text x="150" y="28">Client</text></g>'
            '<g data-node-id="lifeline-b" data-semantic-role="lifeline"><line x1="650" y1="40" x2="650" y2="190"/><text x="620" y="28">Service</text></g>'
            '<line data-edge-id="message-1" data-semantic-role="message" data-source-id="lifeline-a" data-target-id="lifeline-b" data-message-order="1" x1="180" y1="80" x2="650" y2="80"/>'
            + ('<line data-edge-id="return-1" data-semantic-role="return message" data-source-id="lifeline-b" data-target-id="lifeline-a" data-message-order="2" x1="650" y1="130" x2="180" y2="130"/>' if "return" in requested else "")
            + extra + '</svg>'
        )
    if artifact == "state_model":
        edge_roles = "transition"
        if "guard" in requested:
            edge_roles += " guard event"
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 230" role="img" aria-label="state structure" data-structure-evidence="typed">'
            '<g data-node-id="state-a" data-semantic-role="state"><rect x="80" y="80" width="170" height="60" rx="22"/><text x="165" y="116">Pending</text></g>'
            '<g data-node-id="state-b" data-semantic-role="state"><rect x="610" y="80" width="170" height="60" rx="22"/><text x="695" y="116">Done</text></g>'
            f'<line data-edge-id="transition-1" data-semantic-role="{edge_roles}" data-source-id="state-a" data-target-id="state-b" data-relation-kind="transition" x1="250" y1="110" x2="610" y2="110"/>'
            '</svg>'
        )
    if artifact == "deployment_model":
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 230" role="img" aria-label="deployment structure" data-structure-evidence="typed">'
            '<g data-node-id="node-client" data-semantic-role="node"><rect x="60" y="70" width="170" height="80"/><text x="100" y="112">Client</text></g>'
            '<g data-node-id="artifact-service" data-semantic-role="artifact"><rect x="600" y="70" width="170" height="80"/><text x="640" y="112">Service</text></g>'
            '<line data-edge-id="link-1" data-semantic-role="communication_link deployment" data-source-id="node-client" data-target-id="artifact-service" data-relation-kind="communication_link" x1="230" y1="110" x2="600" y2="110"/>'
            '</svg>'
        )
    if artifact == "use_case_model":
        relation = "include" if "include" in requested else "association"
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 230" role="img" aria-label="use case structure" data-structure-evidence="typed">'
            '<g data-node-id="actor-1" data-semantic-role="actor"><circle cx="120" cy="110" r="32"/><text x="90" y="165">Actor</text></g>'
            '<g data-node-id="usecase-1" data-semantic-role="use_case"><ellipse cx="630" cy="110" rx="110" ry="42"/><text x="570" y="116">UseCase</text></g>'
            f'<line data-edge-id="usecase-edge" data-semantic-role="{relation} association" data-source-id="actor-1" data-target-id="usecase-1" data-relation-kind="{relation}" x1="150" y1="110" x2="520" y2="110"/>'
            '</svg>'
        )
    if artifact == "activity_model":
        first_target = "decision-1" if "decision" in requested else "action-2"
        decision = (
            '<g data-node-id="decision-1" data-semantic-role="decision"><polygon points="420,110 450,80 480,110 450,140"/></g>'
            '<line data-edge-id="flow-2" data-semantic-role="control_flow guard" data-source-id="decision-1" data-target-id="action-2" data-relation-kind="control_flow" x1="450" y1="80" x2="650" y2="55"/>'
            '<line data-edge-id="flow-3" data-semantic-role="control_flow guard" data-source-id="decision-1" data-target-id="action-3" data-relation-kind="control_flow" x1="450" y1="140" x2="650" y2="165"/>'
            if "decision" in requested else ""
        )
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 230" role="img" aria-label="activity structure" data-structure-evidence="typed">'
            '<g data-node-id="action-1" data-semantic-role="action"><rect x="60" y="85" width="150" height="50" rx="18"/><text x="90" y="116">Start</text></g>'
            '<g data-node-id="action-2" data-semantic-role="action"><rect x="650" y="30" width="150" height="50" rx="18"/><text x="680" y="61">Accept</text></g>'
            '<g data-node-id="action-3" data-semantic-role="action"><rect x="650" y="140" width="150" height="50" rx="18"/><text x="680" y="171">Reject</text></g>'
            f'<line data-edge-id="flow-1" data-semantic-role="control_flow" data-source-id="action-1" data-target-id="{first_target}" data-relation-kind="control_flow" x1="210" y1="110" x2="420" y2="110"/>'
            + decision + '</svg>'
        )
    return ""


def _svg_for_page(page: dict[str, Any]) -> str:
    artifact = str(page.get("artifact_type") or "")
    roles = page.get("planned_semantic_elements") or page.get("semantic_elements") or []
    if page.get("semantic_structure_fixture") and artifact:
        typed = _typed_structure_svg(artifact, [str(item) for item in roles])
        if typed:
            return typed
    role_markup = "".join(f'<g data-semantic-role="{html.escape(str(role))}"><rect x="{30 + index * 170}" y="80" width="140" height="72" rx="10" fill="#dbe8eb" stroke="#6b8f9d"/><text x="{100 + index * 170}" y="122" text-anchor="middle" font-size="14">{html.escape(str(role))}</text></g>' for index, role in enumerate(roles[:5]))
    if not role_markup:
        role_markup = '<circle cx="120" cy="116" r="40" fill="#dbe8eb" stroke="#6b8f9d" data-semantic-role="visual"/><text x="120" y="121" text-anchor="middle" font-size="14">visual</text>'
    artifact_marker = f' data-artifact-type="{html.escape(artifact)}"' if artifact else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 230" role="img" aria-label="semantic visual"{artifact_marker}>{role_markup}</svg>'


def adapt_session_to_courseware(session: dict[str, Any], *, course_title: str = "Synthetic Whole Course", audience: str = "高职学生", visual_plans: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    pages = session.get("pages", [])
    if not pages:
        pages = [*pages, {"id": f"{session.get('id', 'session')}-summary", "title": "Evidence summary", "primary_job": "summarize", "layout": "summary", "lecture_minutes": 2, "activity_minutes": 0, "suggested_minutes": 2, "learning_node_ids": [], "content_evidence": {"check": "summarize"}}]
    learning_units = []
    facts = []
    slides = []
    visual_by_page = {str(item.get("page_id")): item for item in (visual_plans or []) if isinstance(item, dict) and item.get("page_id")}
    for index, page in enumerate(pages, start=1):
        page = dict(page)
        page_id = str(page.get("id") or f"page-{index}")
        visual_plan = visual_by_page.get(page_id, {})
        if visual_plan:
            if visual_plan.get("artifact_type"):
                page["artifact_type"] = visual_plan["artifact_type"]
            if visual_plan.get("visual_intent"):
                page["visual_intent"] = visual_plan["visual_intent"]
            page["planned_semantic_elements"] = visual_plan.get("planned_semantic_elements", [])
            page["source_asset_ids"] = visual_plan.get("selected_source_asset_ids", visual_plan.get("source_asset_ids", []))
            page["semantic_structure_fixture"] = bool(visual_plan.get("semantic_structure_fixture"))
            page["structure_requirements"] = visual_plan.get("structure_requirements", {})
        unit_id = f"unit-{page_id}"
        fact_id = f"fact-{page_id}"
        title = str(page.get("title") or page.get("teaching_question") or page_id)
        lecture = max(0, int(round(float(page.get("lecture_minutes", 1) or 1))))
        activity = max(0, int(round(float(page.get("activity_minutes", 0) or 0))))
        suggested = max(1, lecture + activity)
        learning_units.append({"id": unit_id, "title": title, "students_should_know": [str(page.get("teaching_question") or title)], "students_should_be_able_to": [str(page.get("learning_outcome") or "能解释本页证据")], "prerequisites": [], "not_yet_taught": [], "canonical_fact_ids": [fact_id]})
        facts.append({
            "id": fact_id,
            "kind": "source-supported",
            "statement": str(page.get("learning_outcome") or f"Evidence for {title}"),
            "source_slide_ids": [page_id],
            "learning_unit_ids": [unit_id],
            "verification": {"status": "source-supported", "method": "direct-text"},
            "evidence": [{"evidence_type": "direct-text", "source_id": "source_truth.txt", "quote": "source-backed teaching evidence"}],
        })
        blocks: list[dict[str, Any]] = [{"type": "paragraph", "text": str(page.get("teaching_question") or title)}]
        if page.get("artifact_type") or page.get("visual_intent"):
            blocks.append({"type": "svg", "caption": title, "svg": _svg_for_page(page), "artifact_type": page.get("artifact_type"), "semantic_roles": page.get("planned_semantic_elements") or page.get("semantic_elements") or [], "source_asset_ids": page.get("source_asset_ids", [])})
        elif page.get("content_evidence", {}).get("steps") or page.get("content_evidence", {}).get("procedure"):
            steps = page.get("content_evidence", {}).get("steps") or page.get("content_evidence", {}).get("procedure") or ["observe", "act", "check"]
            blocks.append({"type": "bullets", "items": [str(item.get("instruction") if isinstance(item, dict) else item) for item in steps]})
        elif page.get("primary_job") == "check":
            blocks.append({"type": "quiz", "question": title, "options": ["依据当前证据作答", "忽略证据直接猜测"], "answer_index": 0, "explanation": "答案必须与页面证据对应。"})
        else:
            blocks.append({"type": "cards", "items": [{"title": "evidence", "text": str(page.get("learning_outcome") or title), "tone": "blue"}]})
        script = str(page.get("final_speaker_script") or page.get("planned_speaker_script") or "")
        if not script:
            outcome = str(page.get("learning_outcome") or "本页学习结果")
            job = str(page.get("primary_job") or "理解")
            question = str(page.get("teaching_question") or title)
            question_text = question.replace("？", "；").replace("?", ";")
            evidence_kind = str(page.get("visual_intent") or page.get("artifact_type") or "页面证据")
            session_key = str(session.get("id") or "session")
            page_ref = f"{session_key[-1:]}-{index}"
            job_guidance = {
                "define": "先划出概念边界，再用必要条件检验表述",
                "check": "把判断拆成可核对的条件，并逐项记录依据",
                "visualize": "把关系放回图形结构，说明每个元素为何出现在当前位置",
                "step_through": "按动作顺序演示过程，指出每一步的输入和输出",
                "diagnose": "从现象回溯可能原因，再选择最小验证动作",
                "compare": "先确定比较维度，再分别寻找两侧的证据",
                "summarize": "把本页证据压缩成可迁移的结论和限制条件",
            }.get(job, "围绕本页问题组织观察、解释和复核")
            script = (
                f"在{session_key}/{page_ref}中，教师把“{title}”作为本页焦点，先追问“{question_text}”。"
                f"学生在{page_ref}上采用{job}方法：{job_guidance}；请把观察记录落到“{evidence_kind}”的具体位置。"
                f"随后用“{outcome}”作为验收标准，比较当前判断与页面条件，不把未出现的信息补进答案。"
                f"围绕{session_key}的第{index}页，收束时要提出一条迁移规则，并说明后续检查会补哪种证据。"
            )
            target_chars = max(180, lecture * 120)
            supplements = [
                f"请为{page_ref}写出一个反例，说明它改变了哪项条件，以及为什么不能沿用当前结论。",
                f"再把“{question_text}”改写成一个学生能够现场验证的小问题；在{page_ref}中标出预期看到的信号。",
                f"在{page_ref}的复核中，若同伴给出另一种解释，先引用{evidence_kind}的位置，再判断两种解释各自遗漏了什么。",
                f"将“{outcome}”压缩为一句可复核的课堂记录，记录中保留对象、条件和结果三类信息。",
                f"离开{session_key}前，学生预测{page_ref}对应的下一步错误，并选择一次最小检查动作。",
                f"教师还要追问{page_ref}中的一个反事实：如果关键条件被移除，原来的判断会在哪一步失效。",
                f"请学生把{evidence_kind}与口头解释逐项对照，圈出仍然没有证据支持的词语。",
                f"在{session_key}的汇报中，只提交与{page_ref}直接相关的观察记录，并标记哪些内容属于推测而不是页面事实。",
                f"本页结束前把{outcome}转成下一次实践可以执行的检查动作，保留动作的输入、操作和预期输出。",
            ]
            for supplement in supplements:
                if len(script) >= target_chars:
                    break
                script += " " + supplement
            extra_sentences = [
                f"补充核对一：从{evidence_kind}的起点记录输入条件，再写出预计出现的变化。",
                f"补充核对二：把{outcome}转成一张观察表，分别登记事实、推测和待验证项。",
                f"补充核对三：如果{title}中的关键条件被替换，学生说明结论会在哪个位置改变。",
                f"补充核对四：围绕{question_text}安排一次快速复述，复述中必须保留判断依据和限制。",
                f"补充核对五：教师将{session_key}的课堂记录与下一步实践连接，指出需要继续观察的信号。",
            ]
            extra = 0
            while len(script) < target_chars:
                if extra < len(extra_sentences):
                    sentence = extra_sentences[extra]
                else:
                    sentence = f"补充核对{extra + 1}：为{title}选择一个新的观察角度，并记录它对{outcome}的支持理由。"
                script += " " + sentence
                extra += 1
        slide = {
            "id": page_id,
            "title": title,
            "layout": _renderer_layout(str(page.get("layout") or "default")),
            "blocks": blocks,
            "speaker_script": script,
            "lecture_minutes": lecture,
            "activity_minutes": activity,
            "suggested_minutes": suggested,
            "teaching_intent": {"opening": title, "core_explanation": str(page.get("learning_outcome") or title), "example": "观察页面证据", "misconception": "不要把计划当作成品证据", "question": str(page.get("teaching_question") or title), "transition": "继续检查下一项证据"},
            "learning_unit_ids": [unit_id],
            "canonical_fact_ids": [fact_id],
        }
        if activity:
            slide["activity_plan"] = {"type": "question-discussion", "teacher_prompt": title, "student_action": "根据页面证据做出判断", "expected_artifact_or_response": "一句有依据的回答", "check_method": "核对页面证据", "segments": [{"label": "判断", "minutes": max(1, activity)}]}
        slides.append(slide)
    # The downstream contract validates the prepared/page totals. Use the
    # rendered page plan as the handoff authority after integer normalization;
    # do not add an unplanned summary page or leave a root duration that no
    # longer matches the actual slides.
    session_minutes = max(1, int(sum(slide["suggested_minutes"] for slide in slides)))
    return {
        "contract_version": "1.1",
        "course_title": course_title,
        "chapter_title": str(session.get("title") or session.get("id") or "Synthetic session"),
        "audience": audience,
        "session_minutes": session_minutes,
        "prepared_minutes": session_minutes,
        "core_minutes": session_minutes,
        "extension_minutes": 0,
        "theme": "morandi-academy",
        "course_context": {"course_name": course_title, "audience": audience, "language": "通用", "tools": ["浏览器"], "platform": "离线浏览器", "software": "浏览器"},
        "learning_units": learning_units,
        "canonical_facts": facts,
        "slides": slides,
    }


def _drawio_starter(task: dict[str, Any]) -> str:
    artifact = str(task.get("artifact_type") or "")
    if artifact == "sequence_model":
        return '<mxfile><diagram name="starter"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="lifeline" value="lifeline lifelines" style="umlLifeline" vertex="1" parent="1"/><mxCell id="gap" value="editable_gap:missing_message editable_gap:wrong_message_order missing_messages wrong_order" style="shape=note" vertex="1" parent="1"/><mxCell id="message" value="missing_message" style="message;edgeStyle=orthogonalEdgeStyle" edge="1" parent="1" source="lifeline" target="gap"/></root></mxGraphModel></diagram></mxfile>'
    return '<mxfile><diagram name="starter"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="class" value="class_compartment attribute partial_classes" style="umlClass" vertex="1" parent="1"/><mxCell id="gap" value="editable_gap:missing_relation editable_gap:wrong_multiplicity missing_relationship missing_multiplicity" style="shape=note" vertex="1" parent="1"/><mxCell id="relation" value="association relationship multiplicity 1..*" style="edgeStyle=orthogonalEdgeStyle" edge="1" parent="1" source="class" target="class"/></root></mxGraphModel></diagram></mxfile>'


def adapt_session_to_practice(session: dict[str, Any], *, course_title: str = "Synthetic Whole Course", audience: str = "高职学生", source_pages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tasks = session.get("tasks", []) or [{"id": f"{session.get('id', 'session')}-task", "title": "Evidence task", "capability": "construct", "estimated_minutes": 30, "artifact_type": "class_model", "knowledge_node_ids": []}]
    knowledge_links = []
    practice_tasks = []
    starter_assets = []
    references = []
    pages = source_pages or session.get("pages", []) or [{"id": f"{session.get('id', 'session')}-page"}]
    slide_ids = [str(page.get("id")) for page in pages if page.get("id")]
    unit_ids = [f"unit-{slide_id}" for slide_id in slide_ids]
    fact_ids = [f"fact-{slide_id}" for slide_id in slide_ids]
    for index, task in enumerate(tasks, start=1):
        task_id = str(task.get("id") or f"task-{index}")
        link_ids = [f"knowledge-{task_id}"]
        source_slide_id = str(task.get("source_slide_id") or slide_ids[0])
        source_index = slide_ids.index(source_slide_id) if source_slide_id in slide_ids else 0
        source_slide_id = slide_ids[source_index]
        source_unit_id = unit_ids[source_index]
        source_fact_id = fact_ids[source_index]
        knowledge_links.append({"id": link_ids[0], "title": str(task.get("title") or task_id), "summary": "课程级计划中的可观察能力。", "source_slide_ids": [source_slide_id], "learning_unit_ids": [source_unit_id], "canonical_fact_ids": [source_fact_id], "student_can_do": "能依据证据完成任务。"})
        artifact = str(task.get("artifact_type") or "")
        # The student page must not expose machine task IDs as visible file
        # names. Each task is rendered in its own output directory, so a
        # stable human-facing starter name is sufficient here.
        path = "starter.drawio" if artifact else "starter.txt"
        content = _drawio_starter(task) if artifact else "# student starter\n# editable gap\n"
        if artifact == "sequence_model":
            gap = {"marker": "editable_gap:missing_message", "replacement": "ReservationService -> Reservation: create_or_confirm()", "student_instruction": "补齐消息接收者和成功分支动作。", "kind": "semantic-gap"}
        elif artifact:
            gap = {"marker": "editable_gap:missing_relation", "replacement": "Reservation - TimeSlot: relation", "student_instruction": "补齐关系并保留多重性语义。", "kind": "semantic-gap"}
        else:
            gap = {"marker": "editable gap", "replacement": "student_observation", "student_instruction": "填写一个基于证据的观察。", "kind": "text-gap"}
        starter_assets.append({"id": f"starter-{task_id}", "path": path, "language": "draw.io" if artifact else "text", "task_id": task_id, "content": content, "editable_gaps": [gap]})
        task_kind = "modeling" if artifact else "analysis"
        artifact_kind = "diagram" if artifact == "sequence_model" else "model" if artifact else "document"
        capabilities = ["model_editing", "visualization", "explanation"] if artifact else ["explanation", "comparison"]
        task_record = {"id": task_id, "level": str(task.get("level") or "core"), "title": str(task.get("title") or task_id), "knowledge_link_ids": link_ids, "learning_unit_ids": [source_unit_id], "canonical_fact_ids": [source_fact_id], "source_slide_ids": [source_slide_id], "modality": str(task.get("capability") or "construct"), "overview": "根据课程级问题完成一个可观察结果。", "scaffold": "打开 starter，先定位证据，再修改缺口。", "steps": [{"title": "观察", "instruction": "定位 starter 中的结构。", "check": "能指出结构位置。"}, {"title": "修改", "instruction": "完成一个语义缺口。", "check": "文件仍可继续编辑。"}], "acceptance": ["结果与教学问题一致。"], "help_refs": [], "estimated_minutes": int(round(float(task.get("estimated_minutes", 30) or 30))), "starter_asset_ids": [f"starter-{task_id}"], "task_kind": task_kind, "artifact_kind": artifact_kind, "capabilities": capabilities}
        if artifact:
            task_record.update({"editable_model": "可编辑的课程模型 starter", "required_edit": "补齐语义缺口并保留结构", "modeling_constraints": ["不删除已有结构", "每个关系或消息都要能回到页面证据"]})
        practice_tasks.append(task_record)
        references.append({"task_id": task_id, "title": str(task.get("title") or task_id), "source_slide_ids": [source_slide_id], "learning_unit_ids": [source_unit_id], "canonical_fact_ids": [source_fact_id], "reference_answer": "教师参考答案保留在教师包。", "reference_visual": {"kind": "uml-sequence" if artifact == "sequence_model" else "uml-class", "title": "教师参考结构"}, "key_steps": ["观察", "修改"], "acceptable_variants": ["语义等价结果"], "common_errors": ["只改文字不保留结构"], "acceptance_basis": ["文件存在且可继续编辑"]})
    study = [{"id": "guide-1", "title": "证据检查", "knowledge_link_ids": [item["id"] for item in knowledge_links], "task_ids": [item["id"] for item in practice_tasks], "learning_unit_ids": sorted({unit for item in practice_tasks for unit in item["learning_unit_ids"]}), "canonical_fact_ids": sorted({fact for item in practice_tasks for fact in item["canonical_fact_ids"]}), "body": "先读理论问题，再检查 starter。", "worked_example": "从一个缺口开始。", "quick_reference": ["看结构", "改缺口"], "common_errors": ["把计划当成文件"], "checkpoints": ["保存文件"]}]
    return {
        "contract_version": "1.1",
        "course_title": course_title,
        "practice_title": str(session.get("title") or "Synthetic practice"),
        "audience": audience,
        "duration_minutes": max(30, int(round(float(session.get("planned_minutes") or 60)))),
        "course_context": {**COURSEWARE_CONTEXT, "course_name": course_title, "audience": audience},
        "source_courseware": {"mode": "courseware", "contract_version": "1.1", "chapter_title": str(session.get("title") or "Synthetic"), "taught_slide_ids": slide_ids},
        "knowledge_links": knowledge_links,
        "tasks": practice_tasks,
        "learning_center": [],
        "study_guide": study,
        "foundation_kit": [],
        "teacher_guide": {"purpose": "检查课程级实践证据。", "theory_bridge": "回到理论页面证据。", "timing": [{"minutes": max(1, int(round(float(session.get("planned_minutes") or 30)))), "focus": "完成任务"}], "task_guidance": [{"task_id": task["id"], "look_for": "语义结构", "ask_when_stuck": "请学生指出证据"} for task in practice_tasks], "common_errors": [{"symptom": "只改表面文字", "intervention": "回到结构检查"}], "pace_adjustments": ["按需减少可选步骤"], "closing_checks": ["文件存在", "学生能说明依据"]},
        "teacher_reference": {"task_references": references},
        "starter_assets": starter_assets,
    }
