"""Small synthetic acceptance for the Lesson Content 2.2 artifact boundary.

This harness exercises the real Content 2.2 validator and Content QA on three
representative courses.  It intentionally does not generate a full 40/64-hour
DOCX batch; the DOCX/reference visibility path is covered by the focused unit
regression and the later small Agent smoke.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_lesson_content_v2 import assess_content_quality, lesson_generator
from tests.test_lesson_content_v22 import (
    DB_SPECS,
    NURSING_SPECS,
    SOFTWARE_SPECS,
    _pool,
    make_v22_payload,
)


def _nursing_references() -> list[dict[str, Any]]:
    return [
        {
            "reference_id": "REF-NURSING-BOOK",
            "reference_type": "book",
            "title": "基础护理学",
            "authors": ["李小妹"],
            "edition": "第7版",
            "publisher": "人民卫生出版社",
            "source_kind": "provided",
            "source_region": "domestic",
            "evidence": "用户提供：基础护理学教材.pdf",
        },
        {
            "reference_id": "REF-NURSING-STANDARD",
            "reference_type": "guideline",
            "title": "护理技术操作规范相关章节",
            "source_kind": "generic",
            "source_region": "domestic",
        },
    ]


def _run_case(label: str, payload: dict[str, Any]) -> dict[str, Any]:
    lesson_generator.validate_content_v2_input(payload)
    quality = assess_content_quality(payload)
    if quality["status"] != "passed":
        raise AssertionError({"case": label, "errors": quality["errors"], "warnings": quality["warnings"]})

    lessons = payload["lessons"]
    tasks = payload.get("practice_task_contract", {}).get("tasks", [])
    theory_hours = sum(int(lesson["hours"]) for lesson in lessons)
    practice_hours = sum(int(task["practice_hours"]) for task in tasks)
    expected = payload["delivery_plan"]
    if theory_hours != expected["theory_hours"]:
        raise AssertionError({"case": label, "theory_hours": theory_hours, "expected": expected})
    if practice_hours != expected["practice_hours"]:
        raise AssertionError({"case": label, "practice_hours": practice_hours, "expected": expected})
    if theory_hours + practice_hours != payload["total_hours"]:
        raise AssertionError({"case": label, "total_hours": payload["total_hours"]})

    return {
        "course": payload["course_name"],
        "total_hours": payload["total_hours"],
        "theory_hours": theory_hours,
        "practice_hours": practice_hours,
        "lesson_count": len(lessons),
        "practice_task_count": len(tasks),
        "reference_pool_size": len(payload["reference_pool"]),
        "reference_reuse": quality["reference_provenance"]["cross_lesson_reuse"],
        "content_qa": quality["status"],
    }


def main() -> int:
    cases = [
        (
            "database-40h",
            make_v22_payload(
                course="数据结构高级",
                major="软件工程专业",
                theory_hours=20,
                practice_hours=20,
                lesson_count=10,
                task_hours=[2] * 10,
                practice_work_orders=True,
                specs=DB_SPECS,
            ),
        ),
        (
            "software-modeling-64h",
            make_v22_payload(
                course="软件建模与设计",
                major="软件工程专业",
                theory_hours=32,
                practice_hours=32,
                lesson_count=16,
                task_hours=[2] * 16,
                practice_work_orders=True,
                specs=SOFTWARE_SPECS,
            ),
        ),
        (
            "nursing-non-it-split",
            make_v22_payload(
                course="基础护理技术",
                major="护理专业",
                audience="高职护理二年级",
                theory_hours=6,
                practice_hours=6,
                lesson_count=3,
                task_hours=[2, 2, 2],
                practice_work_orders=True,
                references=_nursing_references(),
                specs=NURSING_SPECS,
            ),
        ),
    ]
    results = [_run_case(label, payload) for label, payload in cases]
    print(json.dumps({"status": "passed", "cases": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
