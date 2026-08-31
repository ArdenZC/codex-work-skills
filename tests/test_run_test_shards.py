from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_test_shards  # noqa: E402


class TestShardManifest(unittest.TestCase):
    def test_full_manifest_matches_root_discovery(self) -> None:
        specs = run_test_shards._suite_specs()
        full = run_test_shards._expand_suites(("full",), specs)
        manifest_count = sum(run_test_shards._suite_count(name, specs) for name in full)
        discovered_count = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py").countTestCases()
        self.assertEqual(manifest_count, discovered_count)

    def test_lesson_content_and_package_are_an_exact_partition(self) -> None:
        content = set(run_test_shards._lesson_content_ids())
        package = set(run_test_shards._lesson_package_ids())
        lesson = set(run_test_shards._class_test_ids("LessonTemplatePackageTests"))
        self.assertEqual(content & package, set())
        self.assertEqual(content | package, lesson)

    def test_fast_alias_is_a_subset_of_full_alias(self) -> None:
        specs = run_test_shards._suite_specs()
        fast = set(run_test_shards._expand_suites(("fast",), specs))
        full = set(run_test_shards._expand_suites(("full",), specs))
        self.assertTrue(fast <= full)

    def test_list_json_reports_parallel_safety_and_counts(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run_test_shards.py"), "--list", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        discovered_count = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py").countTestCases()
        self.assertEqual(payload["aliases"]["full"]["tests"], discovered_count)
        self.assertTrue(payload["suites"]["lesson-content"]["parallel_safe"])
        self.assertFalse(payload["suites"]["gradebook"]["parallel_safe"])

    def test_isolated_environment_redirects_temp_and_windows_profile(self) -> None:
        root = ROOT / "_test-shard-root"
        environment = run_test_shards._isolated_environment(root)
        self.assertEqual(environment["TEMP"], str(root))
        self.assertEqual(environment["TMP"], str(root))
        self.assertEqual(environment["PYTHONPYCACHEPREFIX"], str(root / "python-cache"))
        if sys.platform == "win32":
            self.assertEqual(environment["USERPROFILE"], str(root / "office-profile"))
            self.assertEqual(environment["LOCALAPPDATA"], str(root / "office-profile" / "AppData" / "Local"))


if __name__ == "__main__":
    unittest.main()
