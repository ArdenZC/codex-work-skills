from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
COURSEWARE_SCRIPTS = REPO / "HTML课件生成器" / "courseware-html-generator" / "scripts"
sys.path.insert(0, str(COURSEWARE_SCRIPTS))
sys.path.insert(0, str(ROOT / "scripts"))

import content_contract  # noqa: E402
from practice_contract import load_json, validate_content  # noqa: E402


class GeneralizationHoldoutTests(unittest.TestCase):
    def test_five_holdouts_are_real_contract_pairs(self) -> None:
        manifest = load_json(ROOT / "holdouts" / "SOURCE-FREEZE.json")
        self.assertEqual(len(manifest["holdouts"]), 5)
        for entry in manifest["holdouts"]:
            courseware_path = ROOT / "holdouts" / "source-packs" / entry["courseware"]
            practice_path = ROOT / "holdouts" / "practice-contracts" / entry["practice"]
            courseware = load_json(courseware_path)
            practice = load_json(practice_path)
            courseware_report = content_contract.validate_content(courseware, base_dir=courseware_path.parent)
            # These frozen architecture-pair fixtures predate the G1
            # modality-specific fields.  Keep their structural regression
            # check while the current generator path uses the strict default.
            practice_report = validate_content(practice, courseware, enforce_task_semantics=False)
            self.assertEqual(courseware_report["status"], "pass", entry["id"])
            self.assertEqual(practice_report["status"], "pass", entry["id"])
            slide_ids = {slide["id"] for slide in courseware["slides"]}
            self.assertTrue(all(set(task["source_slide_ids"]) <= slide_ids for task in practice["tasks"]))
            self.assertEqual(practice["course_context"], courseware["course_context"])
            self.assertEqual(len(practice["tasks"]), 8)
            self.assertEqual({task["level"] for task in practice["tasks"]}, {"core", "optional", "challenge"})

    def test_non_program_holdouts_have_no_c_template_pollution(self) -> None:
        pollution = re.compile(r"(?i)(?:#\s*include\s*[<\"]|\bdev-c\+\+\b|\bcode::blocks\b|\bbinary_search\b|\bc\s*语言补给|\bmalloc\s*\()")
        for name in ("spreadsheet.practice.json", "networking.practice.json", "software-testing.practice.json"):
            raw = (ROOT / "holdouts" / "practice-contracts" / name).read_text(encoding="utf-8")
            self.assertIsNone(pollution.search(raw), name)

    def test_renderer_has_no_fixture_specific_branch(self) -> None:
        renderer = (ROOT / "scripts" / "render_practice.py").read_text(encoding="utf-8")
        for marker in ("data-structures", "software-testing", "web-api", "ai-evaluation"):
            self.assertNotIn(marker, renderer)


if __name__ == "__main__":
    unittest.main()
