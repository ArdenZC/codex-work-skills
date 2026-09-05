"""Deterministic Content V1 quality checks for practice work orders."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

from content_contract import normalise_text


class WorkOrderQualityError(ValueError):
    pass


_ANSWER_MARKERS = (
    "标准答案",
    "参考答案",
    "教师答案",
    "完整sql",
    "最终sql",
    "最终e-r图",
    "最终er图",
    "操作结论",
)
_VAGUE_ONLY = {
    "完成任务",
    "按照要求完成任务",
    "按要求完成",
    "认真操作",
    "认真完成任务",
    "完成相关工作",
    "完成相关内容",
    "进行实践",
    "提交作业",
    "提交任务成果",
    "完成练习",
    "检查任务结果",
}
_VAGUE_FRAGMENTS = (
    "认真",
    "按要求",
    "按照要求",
    "相关工作",
    "相关内容",
    "完成任务",
    "进行实践",
    "提交作业",
    "提交任务成果",
    "检查任务结果",
)
_ACTION_MARKERS = (
    "创建",
    "设计",
    "分析",
    "绘制",
    "配置",
    "记录",
    "测量",
    "核对",
    "整理",
    "编写",
    "实施",
    "观察",
    "清洁",
    "评估",
    "验证",
    "操作",
    "建立",
    "提取",
    "划分",
    "设置",
    "复核",
    "收集",
    "分类",
    "标记",
    "执行",
    "检查",
    "提交",
    "阅读",
    "圈定",
    "选择",
    "补充",
    "签名",
    "完成",
)
_IT_MARKERS = ("sql", "数据库索引", "java", "ide", "mysql", "api")
_NURSING_MARKERS = ("患者", "血压", "无菌", "生命体征", "护理操作")
_RESOURCE_ONLY = (
    "投影仪",
    "ppt",
    "mysql workbench",
    "血压计",
    "数据库服务器",
    "护理模型",
    "计算机机房",
)


def _compact(text: Any) -> str:
    value = unicodedata.normalize("NFKC", normalise_text(text)).casefold()
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def _all_text(content: dict[str, Any]) -> str:
    values: list[Any] = [
        content.get("course_name", ""),
        content.get("major", ""),
        content.get("class_or_audience", ""),
        content.get("project_name", ""),
        content.get("task_title", ""),
        content.get("project_id", ""),
        *content.get("safety_or_compliance", []),
    ]
    for item in content.get("task_items", []):
        values.extend([item.get("title", ""), item.get("description", "")])
        for key in ("tools_or_materials", "steps", "deliverables", "acceptance_criteria"):
            values.extend(item.get(key, []))
    return " ".join(normalise_text(value) for value in values).casefold()


def _reference_looks_like_resource_only(text: str) -> bool:
    """Compatibility helper; WorkOrder has no reference field of its own."""

    cleaned = normalise_text(text).casefold().strip("。；;:：")
    return cleaned in {item.casefold() for item in _RESOURCE_ONLY}


def _is_vague_only(text: Any) -> bool:
    compact = _compact(text)
    if not compact:
        return True
    if compact in {_compact(value) for value in _VAGUE_ONLY}:
        return True
    remainder = compact
    for fragment in _VAGUE_FRAGMENTS:
        remainder = remainder.replace(_compact(fragment), "")
    return len(remainder) < 4


def _is_vague_deliverable(text: Any) -> bool:
    return _compact(text) in {
        "完成任务",
        "实验结果",
        "学习成果",
        "任务成果",
        "相关材料",
        "提交成果",
        "结果",
    }


def _is_vague_criterion(text: Any) -> bool:
    return _compact(text) in {
        "认真完成任务",
        "按照要求完成",
        "按要求完成",
        "符合要求",
        "质量合格",
        "完成任务",
        "结果正确",
    }


def _narrative_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _compact(item.get("title", "")),
        _compact(item.get("description", "")),
        tuple(_compact(value) for value in item.get("deliverables", [])),
        tuple(_compact(value) for value in item.get("acceptance_criteria", [])),
    )


def _coverage_anchor(value: Any) -> set[str]:
    compact = _compact(value)
    if not compact:
        return set()
    anchors = {compact}
    if len(compact) >= 2:
        anchors.update(compact[index : index + 2] for index in range(len(compact) - 1))
    anchors.update(token.casefold() for token in re.findall(r"[a-z0-9]+", str(value)))
    return anchors


def _has_coverage(source: Any, targets: Iterable[Any]) -> bool:
    source_text = _compact(source)
    if not source_text:
        return False
    source_anchors = _coverage_anchor(source)
    for target in targets:
        target_text = _compact(target)
        if source_text == target_text or (len(source_text) >= 3 and source_text in target_text):
            return True
        if any(len(anchor) >= 2 for anchor in source_anchors & _coverage_anchor(target)):
            return True
    return False


def _step_has_action_and_object(text: Any) -> bool:
    """Apply the minimum deterministic action + object step gate."""

    value = normalise_text(text)
    if _is_vague_only(value):
        return False
    compact = _compact(value)
    actions = [
        (compact.find(_compact(marker)), _compact(marker))
        for marker in _ACTION_MARKERS
        if _compact(marker) in compact
    ]
    if not actions:
        return False
    position, action = min(actions, key=lambda item: item[0])
    remainder = compact[:position] + compact[position + len(action) :]
    # A concrete target may be short (for example, “结果” in “检查结果”),
    # but an action by itself must not pass.
    return len(remainder) >= 2


def validate_content(content: dict[str, Any]) -> dict[str, Any]:
    """Run semantic checks after JSON Schema validation."""

    errors: list[str] = []
    executability_errors: list[str] = []
    deliverable_errors: list[str] = []
    acceptance_errors: list[str] = []
    cross_domain_errors: list[str] = []
    total_task_score = 0
    major_text = normalise_text(content.get("major", "")).casefold()
    try:
        practice_hours = int(content.get("practice_hours"))
    except (TypeError, ValueError):
        practice_hours = 0
    if practice_hours != 2:
        errors.append(
            "practice_hours must equal 2 because one WorkOrder represents exactly one 2-hour Practice Task"
        )

    for index, item in enumerate(content.get("task_items", []), start=1):
        for key in ("title", "description"):
            if not normalise_text(item.get(key)):
                errors.append(f"task_items[{index}].{key} is empty")
        for key in ("tools_or_materials", "steps", "deliverables", "acceptance_criteria"):
            values = item.get(key, [])
            if not values or any(not normalise_text(value) for value in values):
                errors.append(f"task_items[{index}].{key} must contain non-empty text")
        total_task_score += int(item.get("score", 0) or 0)
        combined = " ".join(
            [normalise_text(item.get("title")), normalise_text(item.get("description"))]
            + [
                normalise_text(value)
                for key in ("steps", "deliverables", "acceptance_criteria")
                for value in item.get(key, [])
            ]
        ).casefold()
        if any(marker.casefold() in combined for marker in _ANSWER_MARKERS):
            errors.append(f"task_items[{index}] contains answer/key leakage")
        if _is_vague_only(item.get("description")) or _is_vague_only(item.get("title")):
            executability_errors.append(f"task_items[{index}] is only a generic task phrase")
        if not any(marker.casefold() in combined for marker in _ACTION_MARKERS):
            executability_errors.append(f"task_items[{index}] has no substantive action")
        if len(_compact(combined)) < 8:
            executability_errors.append(f"task_items[{index}] does not name a professional object")
        for step_index, step in enumerate(item.get("steps", []), start=1):
            if not _step_has_action_and_object(step):
                executability_errors.append(
                    f"{content.get('practice_task_id', '<unknown>')} task_item[{index}] "
                    f"step[{step_index}] is vague or lacks action/object: {normalise_text(step)!r}"
                )

        for deliverable in item.get("deliverables", []):
            if _is_vague_deliverable(deliverable):
                deliverable_errors.append(
                    f"task_items[{index}] has an unobservable deliverable: {deliverable}"
                )
        criteria = item.get("acceptance_criteria", [])
        observable_criteria = [value for value in criteria if not _is_vague_criterion(value)]
        if not criteria or not observable_criteria:
            acceptance_errors.append(
                f"{content.get('practice_task_id', '<unknown>')} task_item[{index}]: "
                "missing observable acceptance criterion (category=acceptance)"
            )
        else:
            for deliverable in item.get("deliverables", []):
                if _is_vague_deliverable(deliverable):
                    continue
                if not _has_coverage(deliverable, observable_criteria):
                    acceptance_errors.append(
                        f"{content.get('practice_task_id', '<unknown>')} task_item[{index}]: "
                        f"deliverable {normalise_text(deliverable)!r} has no observable "
                        f"acceptance coverage; missing_deliverable={normalise_text(deliverable)!r} "
                        "(category=acceptance)"
                    )

    errors.extend(executability_errors)
    errors.extend(deliverable_errors)
    errors.extend(acceptance_errors)
    if total_task_score != 90:
        errors.append(f"task item scores must total 90, got {total_task_score}")

    all_text = _all_text(content)
    if any(marker in major_text for marker in ("护理", "临床", "助产")):
        if any(marker in all_text for marker in _IT_MARKERS):
            cross_domain_errors.append("nursing content contains unrelated IT terminology")
    if any(marker in major_text for marker in ("软件", "计算机", "信息", "数据库")):
        if any(marker in all_text for marker in _NURSING_MARKERS):
            cross_domain_errors.append("software content contains unrelated nursing terminology")
    errors.extend(cross_domain_errors)

    safety_values = content.get("safety_or_compliance", [])
    if safety_values and any(not normalise_text(value) for value in safety_values):
        errors.append("safety_or_compliance contains empty text")

    narrative_keys = [_narrative_key(item) for item in content.get("task_items", [])]
    repetition_failed = len(narrative_keys) != len(set(narrative_keys))
    if repetition_failed:
        errors.append("task item narrative duplicates are not allowed within one work order")

    total_score = 10 + total_task_score
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": [],
        "categories": {
            "practice_hours_unit": "pass" if practice_hours == 2 else "fail",
            "executability": "fail" if executability_errors else "pass",
            "deliverable": "fail" if deliverable_errors else "pass",
            "acceptance": "fail" if acceptance_errors else "pass",
            "cross_domain": "fail" if cross_domain_errors else "pass",
            "repetition": "fail" if repetition_failed else "pass",
            "score": "pass" if total_task_score == 90 else "fail",
        },
        "metrics": {
            "practice_hours": practice_hours,
            "task_count": len(content.get("task_items", [])),
            "attendance_score": 10,
            "task_score": total_task_score,
            "total_score": total_score,
        },
    }


def validate_collection(contents: list[dict[str, Any]]) -> dict[str, Any]:
    """Check each work order and only its student-facing narrative for reuse."""

    reports = [validate_content(content) for content in contents]
    errors = [
        f"content[{index}]: {error}"
        for index, report in enumerate(reports)
        for error in report["errors"]
    ]
    skeletons = [
        tuple(_narrative_key(item) for item in content["task_items"])
        for content in contents
    ]
    if len(skeletons) > 1 and len(set(skeletons)) == 1:
        errors.append("all generated work orders have the same task narrative skeleton")
    all_narratives = [
        _narrative_key(item)
        for content in contents
        for item in content["task_items"]
    ]
    if len(all_narratives) != len(set(all_narratives)):
        errors.append("duplicate task narrative is not allowed across work orders")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": [],
        "reports": reports,
        "metrics": {
            "content_count": len(contents),
            "total_score": 100,
            "repetition_scope": [
                "task_items.title",
                "task_items.description",
                "task_items.deliverables",
                "task_items.acceptance_criteria",
            ],
        },
    }
