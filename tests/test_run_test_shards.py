from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


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

    def test_lesson_package_parallel_partition_is_exact_and_balanced(self) -> None:
        package = run_test_shards._lesson_package_ids()
        groups = run_test_shards._partition_ids(package, 4)
        self.assertEqual(set().union(*(set(group) for group in groups)), set(package))
        self.assertEqual(sum(len(group) for group in groups), len(package))
        self.assertLessEqual(max(map(len, groups)) - min(map(len, groups)), 1)
        self.assertEqual(len(set().union(*(set(group) for group in groups))), len(package))

    def test_fast_alias_is_a_subset_of_full_alias(self) -> None:
        specs = run_test_shards._suite_specs()
        fast = set(run_test_shards._expand_suites(("fast",), specs))
        full = set(run_test_shards._expand_suites(("full",), specs))
        self.assertTrue(fast <= full)

    def test_hardening_suite_is_in_full_manifest(self) -> None:
        specs = run_test_shards._suite_specs()
        self.assertIn("hardening", specs)
        self.assertIn("hardening", run_test_shards._expand_suites(("full",), specs))
        self.assertEqual(
            specs["hardening"].count,
            unittest.defaultTestLoader.loadTestsFromName("tests.test_lesson_skill_hardening").countTestCases(),
        )

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
        self.assertTrue(payload["suites"]["lesson-package"]["parallel_safe"])
        self.assertFalse(payload["suites"]["gradebook"]["parallel_safe"])
        self.assertEqual(payload["suites"]["gradebook"]["resource_group"], "repository-validator")
        self.assertEqual(payload["suites"]["tooling"]["resource_group"], "repository-validator")
        self.assertEqual(payload["suites"]["release"]["resource_group"], "repository-validator")

    def test_isolated_environment_redirects_temp_and_preserves_host_office_profile(self) -> None:
        root = ROOT / "_test-shard-root"
        environment = run_test_shards._isolated_environment(root)
        self.assertEqual(environment["TEMP"], str(root))
        self.assertEqual(environment["TMP"], str(root))
        self.assertEqual(environment["PYTHONPYCACHEPREFIX"], str(root / "python-cache"))
        if sys.platform == "win32":
            for key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA"):
                if key in os.environ:
                    self.assertEqual(environment[key], os.environ[key])

    def test_python_command_resolution_handles_bare_explicit_relative_and_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="shard-python-resolution-") as temp_name:
            folder = Path(temp_name)
            explicit = folder / "fake-python.exe"
            explicit.write_bytes(b"placeholder")
            with patch.object(run_test_shards.shutil, "which", return_value=str(explicit)) as which:
                self.assertEqual(run_test_shards._resolve_python_command("python"), str(explicit.resolve()))
                which.assert_called_once_with("python")
            self.assertEqual(
                run_test_shards._resolve_python_command(str(explicit)),
                str(explicit.resolve()),
            )
            relative = explicit.relative_to(Path.cwd()) if explicit.is_relative_to(Path.cwd()) else None
            if relative is not None:
                self.assertEqual(run_test_shards._resolve_python_command(str(relative)), str(explicit.resolve()))
            with self.assertRaisesRegex(FileNotFoundError, "not found"):
                with patch.object(run_test_shards.shutil, "which", return_value=None):
                    run_test_shards._resolve_python_command("definitely-not-a-python")

    def test_windows_style_missing_path_fails_closed(self) -> None:
        with self.assertRaises(FileNotFoundError):
            run_test_shards._resolve_python_command(r"C:\missing\python.exe")


if __name__ == "__main__":
    unittest.main()
