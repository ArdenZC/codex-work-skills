"""Run one complete semantic slice of the gradebook regression suite."""

from __future__ import annotations

import argparse
import importlib
import sys
import unittest
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
TEST_MODULE = "tests.test_template_packages"
TEMPLATE_TEST_CLASS = "GradebookTemplatePackageTests"
STATIC_TESTS = (
    f"{TEST_MODULE}.GradebookTotalRuleTests.test_total_rule_matches_exactly_with_zero_and_nonzero_skill_weights",
    f"{TEST_MODULE}.GradebookPowerShellContractTests.test_com_path_uses_same_rounding_preflight_and_exact_output_contract",
    f"{TEST_MODULE}.GradebookPowerShellContractTests.test_local_com_integration_script_is_repeatable_and_has_skip_boundary",
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# These groups are semantic rather than positional. Every package test is
# listed exactly once so a new test cannot silently disappear from CI.
CONTRACT_TEMPLATE_TESTS = (
    "test_canonical_template_and_compatibility_entry",
    "test_invalid_input_is_rejected",
    "test_custom_template_allows_writable_values_but_preserves_formatting",
    "test_custom_template_rejects_protected_target_sheet_settings",
    "test_custom_template_rejects_protected_font_family_changes",
    "test_custom_template_rejects_dejavu_fallback_for_simsun",
    "test_custom_template_rejects_liberation_fallback_for_simsun",
    "test_custom_template_xls_roundtrip_rejects_protected_and_metadata_font_fallback",
    "test_canonical_libreoffice_roundtrip_passes_font_guard",
    "test_custom_template_rejects_print_header_footer_changes",
    "test_custom_template_rejects_non_target_sheet_changes",
    "test_custom_template_rejects_regular_item_header_change",
    "test_legacy_output_dir_with_multiple_candidates_fails_explicitly",
    "test_named_range_builder_preserves_raw_xls_and_roundtrip_inventory",
    "test_named_range_builder_preserves_complete_v11_source_and_rejects_partial_or_wrong_sources",
    "test_named_range_builder_rejects_overlapping_packages_before_soffice",
    "test_controlled_v11_baseline_handles_roundtrip_normalization_and_protected_tamper",
    "test_named_range_manifest_contract_is_closed_and_minor_matrix_is_strict",
    "test_named_range_template_faults_are_rejected_by_real_validator",
    "test_named_range_output_fault_reports_use_consistent_top_level_fields",
    "test_fingerprint_is_enforced_before_both_skip_paths",
    "test_matching_custom_v11_package_can_skip_with_explicit_report",
    "test_python_output_path_collisions_are_rejected_before_generation",
    "test_python_custom_package_paths_are_all_protected",
    "test_builder_uses_fixed_canonical_v10_baseline_for_layout_faults",
    "test_structure_breaking_xls_is_rejected",
    "test_incompatible_manifest_major_is_rejected",
    "test_manifest_loading_failures_are_clear",
    "test_named_range_capacity_faults_are_rejected_and_exact_100_passes",
    "test_python_failure_preserves_existing_output_and_unrelated_xls",
    "test_regular_score_boundaries_are_exact",
)

GENERATION_TEMPLATE_TESTS = (
    "test_python_generator_zero_skill_and_qa",
    "test_python_generator_preserves_fractional_weight_headers",
    "test_output_validation_rejects_theory_score_mismatch",
    "test_output_validation_rejects_non_target_sheet_changes",
    "test_python_generator_skill_and_leading_zero_id",
    "test_python_generator_ignores_unrelated_xls_files",
    "test_rejects_source_total_mismatch_positive_one",
    "test_rejects_source_total_mismatch_negative_one",
    "test_rejects_fractional_source_total_before_generation",
    "test_rejects_fractional_regular_score_before_generation",
    "test_output_validation_rejects_protected_font_fallback",
    "test_output_validation_rejects_xls_roundtrip_font_fallback",
    "test_python_generator_skill_xls_roundtrip_passes_font_guard",
    "test_output_validation_rejects_target_sheet_formatting_changes",
    "test_output_validation_rejects_extra_blank_student_rows",
    "test_python_compatibility_template_and_skipped_validation_leave_qa_metadata",
    "test_python_generator_expands_beyond_template_rows",
    "test_named_range_variants_and_dynamic_capacity_are_real_outputs",
    "test_named_range_runtime_preflight_rejects_matching_fingerprint_faults",
    "test_com_named_range_runtime_preflight_cannot_be_skipped_by_either_flag",
    "test_named_range_success_report_has_empty_diagnostics_at_both_levels",
    "test_com_output_collisions_and_failure_cleanup_are_real",
    "test_python_double_skip_runs_raw_preflight_before_candidate_creation",
    "test_skip_validation_requires_real_output_and_raw_named_ranges",
    "test_formula_error_is_rejected",
    "test_student_count_mismatch_is_rejected",
)


GROUP_TEMPLATE_TESTS = {
    "contracts": CONTRACT_TEMPLATE_TESTS,
    "generation": GENERATION_TEMPLATE_TESTS,
}


def _template_test_names() -> set[str]:
    module = importlib.import_module(TEST_MODULE)
    test_class = getattr(module, TEMPLATE_TEST_CLASS)
    return {name for name in dir(test_class) if name.startswith("test_")}


def _all_expected_names() -> set[str]:
    return set(CONTRACT_TEMPLATE_TESTS) | set(GENERATION_TEMPLATE_TESTS)


def validate_groups() -> None:
    groups = [name for tests in GROUP_TEMPLATE_TESTS.values() for name in tests]
    duplicates = sorted(name for name in set(groups) if groups.count(name) > 1)
    expected = _template_test_names()
    actual = set(groups)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if duplicates or missing or unexpected:
        details = {
            "duplicates": duplicates,
            "missing": missing,
            "unexpected": unexpected,
        }
        raise SystemExit(f"Gradebook shard manifest is not an exact partition: {details}")
    if actual != _all_expected_names():
        raise SystemExit("Gradebook shard manifest has inconsistent internal expectations")


def _iter_test_names(group: str) -> Iterable[str]:
    if group == "contracts":
        yield from STATIC_TESTS
    prefix = f"{TEST_MODULE}.{TEMPLATE_TEST_CLASS}."
    yield from (prefix + name for name in GROUP_TEMPLATE_TESTS[group])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=tuple(GROUP_TEMPLATE_TESTS))
    parser.add_argument("--list", action="store_true", dest="list_groups")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    validate_groups()
    if args.list_groups:
        for group, tests in GROUP_TEMPLATE_TESTS.items():
            static_count = len(STATIC_TESTS) if group == "contracts" else 0
            print(f"{group}: {static_count + len(tests)} tests")
        print(f"total: {len(STATIC_TESTS) + len(_all_expected_names())} tests")
        return 0
    if args.group is None:
        parser.error("--group or --list is required")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for test_name in _iter_test_names(args.group):
        suite.addTests(loader.loadTestsFromName(test_name))
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
