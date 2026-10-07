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
        release_scale_count = run_test_shards._suite_count("lesson-release-scale", specs)
        discovered_count = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py").countTestCases()
        self.assertEqual(manifest_count + release_scale_count, discovered_count)

    def test_lesson_content_and_package_are_an_exact_partition(self) -> None:
        content = set(run_test_shards._lesson_content_ids())
        package = set(run_test_shards._lesson_package_ids())
        lesson = set(run_test_shards._class_test_ids("LessonTemplatePackageTests")) | set(
            run_test_shards._module_test_ids(run_test_shards.LESSON_V21_TEST_MODULE)
        ) | set(run_test_shards._module_test_ids(run_test_shards.LESSON_V22_TEST_MODULE)) | set(
            run_test_shards._module_test_ids(run_test_shards.LESSON_V23_TEST_MODULE)
        ) | set(run_test_shards._module_test_ids(run_test_shards.LESSON_CONTRACT_HARDENING_TEST_MODULE)
        )
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
            sum(unittest.defaultTestLoader.loadTestsFromName(m).countTestCases() for m in ("tests.test_lesson_skill_hardening", "tests.test_lesson_release_compatibility")),
        )

    def test_release_compatibility_module_is_covered_exactly_by_hardening(self):
        self.assertEqual(run_test_shards._suite_test_ids("hardening"),
            ("tests.test_lesson_skill_hardening", "tests.test_lesson_release_compatibility"))
        specs = run_test_shards._suite_specs()
        for alias in ("full", "ci"):
            expanded = run_test_shards._expand_suites((alias,), specs)
            self.assertEqual(expanded.count("hardening"), 1)

    def test_lesson_benchmark_suite_is_in_full_manifest(self) -> None:
        specs = run_test_shards._suite_specs()
        self.assertIn("lesson-benchmark", specs)
        self.assertIn("lesson-benchmark", run_test_shards._expand_suites(("full",), specs))
        self.assertEqual(
            specs["lesson-benchmark"].count,
            unittest.defaultTestLoader.loadTestsFromName("tests.test_lesson_exemplar_benchmark").countTestCases(),
        )

    def test_lesson_lifecycle_suite_is_in_fast_and_full_manifests(self) -> None:
        specs = run_test_shards._suite_specs()
        self.assertIn("lesson-lifecycle", specs)
        self.assertIn("lesson-lifecycle", run_test_shards._expand_suites(("fast",), specs))
        self.assertIn("lesson-lifecycle", run_test_shards._expand_suites(("full",), specs))
        self.assertEqual(
            specs["lesson-lifecycle"].count,
            sum(unittest.defaultTestLoader.loadTestsFromName(module).countTestCases()
                for module in ("tests.test_lesson_lifecycle_contracts", "tests.test_semantic_scope_foundation")),
        )

    def test_lesson_course_scope_suite_has_exact_worker_and_fast_full_coverage(self) -> None:
        specs = run_test_shards._suite_specs()
        module = "tests.test_lesson_course_scope"
        self.assertIn("lesson-course-scope", specs)
        self.assertEqual(specs["lesson-course-scope"].count,
                         unittest.defaultTestLoader.loadTestsFromName(module).countTestCases())
        self.assertEqual((module,), run_test_shards._suite_test_ids("lesson-course-scope"))
        for alias in ("fast", "full", "ci"):
            self.assertIn("lesson-course-scope", run_test_shards._expand_suites((alias,), specs))

    def test_lesson_release_scale_suite_is_separate_and_serialized(self) -> None:
        specs = run_test_shards._suite_specs()
        full = run_test_shards._expand_suites(("full",), specs)
        regular_lesson = ("lesson-content", "lesson-package", "lesson-lifecycle", "lesson-course-scope", "lesson-quality", "lesson-pipeline", "lesson-benchmark", "hardening")
        self.assertIn("lesson-release-scale", specs)
        self.assertNotIn("lesson-release-scale", full)
        self.assertTrue(
            all("lesson-release-scale" not in run_test_shards._expand_suites((name,), specs) for name in regular_lesson)
        )
        self.assertFalse(specs["lesson-release-scale"].parallel_safe)
        self.assertEqual(specs["lesson-release-scale"].resource_group, "lesson-render")
        self.assertEqual(
            specs["lesson-release-scale"].count,
            unittest.defaultTestLoader.loadTestsFromName("tests.test_lesson_release_scale_e2e").countTestCases(),
        )

    def test_quality_suite_has_exact_worker_and_fast_full_coverage(self) -> None:
        specs = run_test_shards._suite_specs()
        self.assertEqual(
            specs["lesson-quality"].count,
            unittest.defaultTestLoader.loadTestsFromName("tests.test_benchmark_quality_eligibility").countTestCases(),
        )
        self.assertEqual(("tests.test_benchmark_quality_eligibility",), run_test_shards._suite_test_ids("lesson-quality"))
        for alias in ("fast", "full", "ci"):
            self.assertIn("lesson-quality", run_test_shards._expand_suites((alias,), specs))

    def test_pipeline_suite_has_exact_worker_and_fast_full_coverage(self) -> None:
        specs = run_test_shards._suite_specs()
        modules = ("tests.test_benchmark_preparation", "tests.test_lesson_pipeline")
        self.assertEqual(sum(unittest.defaultTestLoader.loadTestsFromName(m).countTestCases() for m in modules),
                         specs["lesson-pipeline"].count)
        self.assertEqual(modules, run_test_shards._suite_test_ids("lesson-pipeline"))
        for alias in ("fast", "full", "ci"):
            self.assertIn("lesson-pipeline", run_test_shards._expand_suites((alias,), specs))

    def test_teacher_review_suite_has_exact_worker_and_fast_full_coverage(self) -> None:
        specs = run_test_shards._suite_specs()
        module = "tests.test_teacher_review_selection"
        self.assertEqual(unittest.defaultTestLoader.loadTestsFromName(module).countTestCases(),
                         specs["lesson-teacher-review"].count)
        self.assertEqual((module,), run_test_shards._suite_test_ids("lesson-teacher-review"))
        self.assertTrue(specs["lesson-teacher-review"].parallel_safe)
        for alias in ("fast", "full", "ci"):
            self.assertIn("lesson-teacher-review", run_test_shards._expand_suites((alias,), specs))

    def test_final_acceptance_suite_is_independent_render_lane(self):
        module = "tests.test_lesson_final_acceptance"
        specs = run_test_shards._suite_specs()
        spec = specs["lesson-final-acceptance"]
        self.assertEqual(unittest.defaultTestLoader.loadTestsFromName(module).countTestCases(), spec.count)
        self.assertEqual((module,), run_test_shards._suite_test_ids("lesson-final-acceptance"))
        self.assertFalse(spec.parallel_safe)
        self.assertEqual(spec.resource_group, "lesson-render")
        for alias in ("fast", "full", "ci"):
            self.assertIn("lesson-final-acceptance", run_test_shards._expand_suites((alias,), specs))

    def test_gradebook_discovery_worker_does_not_reuse_lesson_package_common(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "run_test_shards.py"), "--worker", "--suite", "gradebook-skill"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("Ran 2 tests", result.stderr)

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
        release_scale_count = payload["suites"]["lesson-release-scale"]["tests"]
        self.assertEqual(payload["aliases"]["full"]["tests"] + release_scale_count, discovered_count)
        self.assertTrue(payload["suites"]["lesson-content"]["parallel_safe"])
        self.assertTrue(payload["suites"]["lesson-package"]["parallel_safe"])
        self.assertFalse(payload["suites"]["gradebook"]["parallel_safe"])
        self.assertEqual(payload["suites"]["gradebook"]["resource_group"], "repository-validator")
        self.assertEqual(payload["suites"]["tooling"]["resource_group"], "repository-validator")
        self.assertEqual(payload["suites"]["release"]["resource_group"], "repository-validator")
        self.assertTrue(payload["suites"]["lesson-benchmark"]["parallel_safe"])

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

    def test_parallel_capacity_stays_full_as_pending_queue_shrinks(self):
        # Three independent suites on two CPUs: when the first exits, the third
        # must start immediately beside the still-running second suite.
        active = set()
        starts = []
        polls = {}
        class Process:
            def __init__(self, command, **kwargs):
                self.name = command[command.index("--suite") + 1]
                starts.append((self.name, frozenset(active)))
                active.add(self.name)
                polls[self.name] = 0
            def poll(self):
                polls[self.name] += 1
                if self.name == "b" and polls[self.name] < 3:
                    return None
                active.discard(self.name)
                return 0
        specs = {name: run_test_shards.SuiteSpec(name, True, "module", 1) for name in ("a", "b", "c")}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(run_test_shards, "_suite_specs", return_value=specs), \
                patch.object(run_test_shards.os, "cpu_count", return_value=2), \
                patch.object(run_test_shards.subprocess, "Popen", Process), \
                patch.object(run_test_shards.time, "sleep"):
            status = run_test_shards._run_parent(tuple(specs), python=sys.executable,
                root=Path(folder), parallel=True, allow_office_parallel=False, verbose=False)
        self.assertEqual(status, 0)
        self.assertEqual(starts, [("a", frozenset()), ("b", frozenset({"a"})), ("c", frozenset({"b"}))])

    def test_windows_style_missing_path_fails_closed(self) -> None:
        with self.assertRaises(FileNotFoundError):
            run_test_shards._resolve_python_command(r"C:\missing\python.exe")


if __name__ == "__main__":
    unittest.main()
