from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from practice_time_reviewer import review_practice_time  # noqa: E402


def _task(*, level: str = "core", breakdown: object = None) -> dict:
    task = {
        "id": "task-1",
        "level": level,
        "estimated_minutes": 20,
        "steps": [{"title": "完成", "instruction": "完成一次可观察操作。"}],
    }
    if breakdown is not None:
        task["time_breakdown"] = breakdown
    return task


class PracticeTimeEvidenceTests(unittest.TestCase):
    def test_t16_core_task_without_breakdown_warns(self) -> None:
        report = review_practice_time({"tasks": [_task()]})
        self.assertEqual(report["status"], "DEGRADED", report)
        self.assertTrue(report["warnings"], report)

    def test_t17_core_task_breakdown_matches_passes(self) -> None:
        report = review_practice_time({"tasks": [_task(breakdown=[
            {"step": "打开起点材料并观察", "minutes": 4},
            {"step": "完成关键修改", "minutes": 10},
            {"step": "验证并记录", "minutes": 6},
        ])]})
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["tasks"][0]["breakdown_minutes"], 20)

    def test_optional_task_without_breakdown_is_not_overstrict(self) -> None:
        report = review_practice_time({"tasks": [_task(level="optional")]})
        self.assertEqual(report["status"], "PASS", report)

    def test_mismatched_breakdown_fails(self) -> None:
        report = review_practice_time({"tasks": [_task(breakdown=[{"step": "做一次检查", "minutes": 3}])]})
        self.assertEqual(report["status"], "FAIL", report)
        self.assertTrue(any("approximately equal" in item for item in report["errors"]), report)


if __name__ == "__main__":
    unittest.main()
