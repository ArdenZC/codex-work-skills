from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LessonPlanPackageTests(unittest.TestCase):
    def test_template_validator(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "validate_template.py"), "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["template_version"], "1.1.2")


if __name__ == "__main__":
    unittest.main()
