"""Deterministic Content V1 quality checks for practice work orders."""

from __future__ import annotations

import re
from collections import Counter
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
_VAGUE_ONLY = {"完成任务", "按要求完成", "进行实践", "提交作业", "完成练习"}
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
)
_IT_MARKERS = ("sql", "数据库索引", "java", "ide", "mysql")
_NURSING_MARKERS = ("患者血压", "无菌护理", "生命体征")
_RESOURCE_ONLY = (
    "投影仪",
    "ppt",
    "mysql workbench",
    "血压计",
    "数据库服务器",
    "护理模型",
    "计算机机房",
)


def _all_text(content: dict[str, Any]) -> str:
    values: list[str] = [
        content["course_name"],
        content["major"],
        content["class_or_audience"],
        content["project_name"],
    ]
    for item in content["task_items"]:
        values.extend([item["title"], item["description"]])
        for key in ("tools_or_materials", "steps", "deliverables", "acceptance_criteria"):
            values.extend(item[key])
    return " ".join(normalise_text(value) for value in values).casefold()


def _reference_looks_like_resource_only(text: str) -> bool:
    """Reject only exact/obvious standalone tool names, not document titles."""

    cleaned = normalise_text(text).casefold().strip("。；;:：")
    if cleaned in {item.casefold() for item in _RESOURCE_ONLY}:
        return True
    return False


def _meaningful(field: str, values: Iterable[str], errors: list[str]) -> None:
    items = [normalise_text(value) for value in values]
    if not items or any(not item for item in items):
        errors.append(f"{field} must contain non-empty text")


def validate_content(content: dict[str, Any]) -> dict[str, Any]:
    """Run semantic checks after JSON Schema validation."""

    errors: list[str] = []
    if content.get("content_contract_version") != "1.0":
        errors.append("content_contract_version must be 1.0")
    total_task_score = 0
    major_text = normalise_text(content.get("major", "")).casefold()
    for index, item in enumerate(content.get("task_items", []), start=1):
        for key in ("title", "description"):
            if not normalise_text(item.get(key)):
                errors.append(f"task_items[{index}].{key} is empty")
        for key in ("tools_or_materials", "steps", "deliverables", "acceptance_criteria"):
            _meaningful(f"task_items[{index}].{key}", item.get(key, []), errors)
        total_task_score += int(item.get("score", 0) or 0)
        combined = " ".join(
            [normalise_text(item.get("title")), normalise_text(item.get("description"))]
            + [normalise_text(value) for key in ("steps", "deliverables", "acceptance_criteria") for value in item.get(key, [])]
        ).casefold()
        if any(marker in combined for marker in _ANSWER_MARKERS):
            errors.append(f"task_items[{index}] contains answer/key leakage")
        if normalise_text(item.get("description")) in _VAGUE_ONLY or not any(
            marker.casefold() in combined for marker in _ACTION_MARKERS
        ):
            errors.append(f"task_items[{index}] is not an executable action description")
        for resource in item.get("tools_or_materials", []):
            if _reference_looks_like_resource_only(resource):
                # Tools/materials are expected here; this helper is deliberately
                # exposed for reference-boundary tests but not applied to them.
                continue
    if total_task_score != 90:
        errors.append(f"task item scores must total 90, got {total_task_score}")
    if major_text and any(marker in major_text for marker in ("护理", "临床", "助产")):
        if any(marker in _all_text(content) for marker in _IT_MARKERS):
            errors.append("nursing content contains unrelated IT terminology")
    if major_text and any(marker in major_text for marker in ("软件", "计算机", "信息", "数据库")):
        if any(marker in _all_text(content) for marker in _NURSING_MARKERS):
            errors.append("software content contains unrelated nursing terminology")
    if any(_reference_looks_like_resource_only(value) for item in content.get("task_items", []) for value in item.get("deliverables", [])):
        errors.append("a deliverable is only a teaching resource; name the student artifact")
    total_score = 10 + total_task_score
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": [],
        "metrics": {
            "task_count": len(content.get("task_items", [])),
            "attendance_score": 10,
            "task_score": total_task_score,
            "total_score": total_score,
        },
    }

def validate_collection(contents: list[dict[str, Any]]) -> dict[str, Any]:
    reports = [validate_content(content) for content in contents]
    errors = [f"content[{index}]: {error}" for index, report in enumerate(reports) for error in report["errors"]]
    skeletons = []
    for content in contents:
        skeletons.append(
            tuple(
                (
                    normalise_text(item["title"]).casefold(),
                    normalise_text(item["description"]).casefold(),
                    tuple(normalise_text(value).casefold() for value in item["steps"]),
                )
                for item in content["task_items"]
            )
        )
    if len(skeletons) > 1 and len(set(skeletons)) == 1:
        errors.append("all generated work orders have the same task skeleton")
    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": [],
        "reports": reports,
        "metrics": {"content_count": len(contents), "total_score": 100},
    }
