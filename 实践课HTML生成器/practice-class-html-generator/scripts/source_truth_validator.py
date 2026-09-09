"""Expose the Courseware Source Truth layer to Practice without duplicating it."""

from __future__ import annotations

import importlib.util
from pathlib import Path


COURSEWARE_VALIDATOR = Path(__file__).resolve().parents[3] / "HTML课件生成器" / "courseware-html-generator" / "scripts" / "source_truth_validator.py"
_spec = importlib.util.spec_from_file_location("_courseware_source_truth_validator_g2", COURSEWARE_VALIDATOR)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load Courseware Source Truth validator: {COURSEWARE_VALIDATOR}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

TRUTH_MODES = _module.TRUTH_MODES
build_csv_source_model = _module.build_csv_source_model
build_fact_usage_registry = _module.build_fact_usage_registry
excel_column_letter = _module.excel_column_letter
source_freeze_sha256 = _module.source_freeze_sha256
validate_cross_material_consistency = _module.validate_cross_material_consistency
validate_fact = _module.validate_fact
validate_source_truth = _module.validate_source_truth

__all__ = [
    "TRUTH_MODES",
    "build_csv_source_model",
    "build_fact_usage_registry",
    "excel_column_letter",
    "source_freeze_sha256",
    "validate_cross_material_consistency",
    "validate_fact",
    "validate_source_truth",
]
