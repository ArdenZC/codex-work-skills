from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GradebookPackageTests(unittest.TestCase):
    def test_regular_score_average_is_exact(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from generate_gradebook import generate_regular_scores

        scores = generate_regular_scores(86.5, "fixture")
        self.assertEqual(len(scores), 8)
        self.assertAlmostEqual(sum(scores) / len(scores), 86.5, places=7)

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


if __name__ == "__main__":
    unittest.main()
