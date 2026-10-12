from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "SKILL.md"
PROMPT = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "通用提示词.md"


class RoutineExemplarWorkflowGuidanceTests(unittest.TestCase):
    def test_daily_path_searches_before_drafting_and_compares_before_docx(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        prompt = PROMPT.read_text(encoding="utf-8")
        for text in (skill, prompt):
            self.assertIn("ONLINE_EXEMPLAR_SEARCH_NOT_EXECUTED", text)
            self.assertIn("日常非盲对照", text)
            self.assertIn("schemas/benchmark-lesson-review.schema.json", text)
            self.assertIn("至多一轮实质性修订", text)
            self.assertIn("BENCHMARK_REVIEW_COMPLETE", text)
        workflow = skill.split("## 日常教案的优秀案例检索与对照（默认 Agent 工作流）", 1)[1]
        workflow = workflow.split("\n## Teaching Exemplar Benchmark 2.3", 1)[0]
        self.assertLess(workflow.index("开始写 Lesson Content 前"), workflow.index("完成第一版 Content"))
        self.assertLess(workflow.index("完成第一版 Content"), workflow.index("调用 Word 生成器前"))

    def test_formal_benchmark_remains_optional_and_existing_assets_are_reused(self) -> None:
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("exemplar_contract.py", skill)
        self.assertIn("benchmark_quality_eligibility.py", skill)
        self.assertIn("exemplar_split.py", skill)
        self.assertIn("benchmark_preparation.py", skill)
        self.assertIn("validate_benchmark_review.py", skill)
        self.assertIn("高级可选模式", skill)
        self.assertIn("--benchmark-mode none", skill)


if __name__ == "__main__":
    unittest.main()
