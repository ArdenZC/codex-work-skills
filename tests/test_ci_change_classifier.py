from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))

from classify_ci_changes import classify  # noqa: E402


class ChangeClassifierTests(unittest.TestCase):
    def assert_flags(self, result: dict[str, object], **expected: bool) -> None:
        for key, value in expected.items():
            self.assertEqual(result[key], value, key)

    def test_documentation_allowlist_is_docs_only(self) -> None:
        result = classify(
            ["README.md", "docs/ci.md", "教案生成器/简介.md", "平时成绩记分册生成器/简介.md", "多Agent兼容规范.md"],
            event_name="pull_request",
        )
        self.assert_flags(result, docs_only=True, run_docs=True, force_full=False)
        self.assertEqual(result["classification"], "docs")

    def test_behavior_markdown_is_not_docs_only(self) -> None:
        for path in ("SKILL.md", "sub/AGENTS.md", "CLAUDE.md", "GEMINI.md", "CONVENTIONS.md", ".github/copilot-instructions.md"):
            result = classify([path], event_name="pull_request")
            self.assert_flags(result, docs_only=False, force_full=True)

    def test_lesson_business_change_runs_only_lesson_and_contracts(self) -> None:
        result = classify(
            ["教案生成器/lesson-plan-docx-generator/scripts/generate_lesson_plans.py"],
            event_name="pull_request",
        )
        self.assert_flags(result, run_lesson=True, run_package_contracts=True, run_gradebook=False, run_tooling=False, run_release=False, force_full=False)

    def test_lesson_template_change_adds_tooling_and_release(self) -> None:
        result = classify(
            ["教案生成器/lesson-plan-docx-generator/assets/templates/lesson-plan/v1.1.1/manifest.yaml"],
            event_name="pull_request",
        )
        self.assert_flags(result, run_lesson=True, run_package_contracts=True, run_tooling=True, run_release=True, run_gradebook=False, force_full=False)

    def test_gradebook_business_and_template_changes_are_scoped(self) -> None:
        business = classify(
            ["平时成绩记分册生成器/course-gradebook-generator/scripts/generate_gradebook.py"],
            event_name="pull_request",
        )
        self.assert_flags(business, run_gradebook=True, run_package_contracts=True, run_lesson=False, run_tooling=False, run_release=False, force_full=False)
        template = classify(
            ["平时成绩记分册生成器/course-gradebook-generator/scripts/named_range_contracts.py"],
            event_name="pull_request",
        )
        self.assert_flags(template, run_gradebook=True, run_package_contracts=True, run_tooling=True, run_release=True, run_lesson=False, force_full=False)

    def test_tooling_and_release_paths_do_not_run_both_core_skills(self) -> None:
        tooling = classify(["tools/template_tooling/archive.py"], event_name="pull_request")
        self.assert_flags(tooling, run_tooling=True, run_release=True, run_package_contracts=True, run_lesson=False, run_gradebook=False, force_full=False)
        release = classify(["tests/test_template_package_release.py"], event_name="pull_request")
        self.assert_flags(release, run_tooling=True, run_release=True, run_package_contracts=True, run_lesson=False, run_gradebook=False, force_full=False)

    def test_mixed_changes_run_each_affected_core(self) -> None:
        result = classify(
            [
                "教案生成器/lesson-plan-docx-generator/scripts/generate_lesson_plans.py",
                "平时成绩记分册生成器/course-gradebook-generator/scripts/generate_gradebook.py",
            ],
            event_name="pull_request",
        )
        self.assert_flags(result, run_lesson=True, run_gradebook=True, run_package_contracts=True, force_full=False)

    def test_docs_plus_code_is_not_docs_only(self) -> None:
        result = classify(
            ["README.md", "教案生成器/lesson-plan-docx-generator/scripts/generate_lesson_plans.py"],
            event_name="pull_request",
        )
        self.assert_flags(result, docs_only=False, run_docs=False, run_lesson=True, force_full=False)

    def test_shared_and_unknown_paths_fail_closed(self) -> None:
        for path in (
            ".github/workflows/template-package-ci.yml",
            ".github/scripts/new_helper.py",
            "requirements-dev.txt",
            "tests/test_template_packages.py",
            "unknown/new-module.py",
        ):
            result = classify([path], event_name="pull_request")
            self.assert_flags(result, force_full=True, run_lesson=True, run_gradebook=True, run_tooling=True, run_release=True, run_package_contracts=True)

    def test_empty_deleted_or_renamed_inputs_fail_closed(self) -> None:
        self.assert_flags(classify([], event_name="push"), force_full=True, run_lesson=True, run_gradebook=True)
        self.assert_flags(
            classify(["README.md", "new-name.md"], event_name="push", ambiguous=True),
            force_full=True,
            run_lesson=True,
            run_gradebook=True,
        )

    def test_manual_and_schedule_are_full(self) -> None:
        for event in ("workflow_dispatch", "schedule"):
            result = classify(["README.md"], event_name=event)
            self.assert_flags(result, docs_only=False, run_docs=False, force_full=True, run_lesson=True, run_gradebook=True, run_tooling=True, run_release=True, run_package_contracts=True)


if __name__ == "__main__":
    unittest.main()
