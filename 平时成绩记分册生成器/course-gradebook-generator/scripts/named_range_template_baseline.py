"""Build the current-environment protected baseline for gradebook v1.1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from named_range_contracts import required_names
from named_range_utils import (
    compare_named_range_inventories,
    expected_named_range_locations,
    set_named_range_from_location,
    validate_named_range_inventory,
)
from package_common import V10_MANIFEST, V10_TEMPLATE, V11_MANIFEST, load_manifest
from validate_template import convert_to_xls, convert_to_xlsx
from xls_named_range_utils import (
    compare_xls_and_xlsx_named_ranges,
    normalize_libreoffice_print_title_records,
    normalize_xls_summary_information,
    validate_xls_named_range_inventory,
)


@dataclass(frozen=True)
class ControlledV11Baseline:
    """Artifacts produced by the same controlled v1.1 construction pipeline."""

    controlled_v11_xls: Path
    controlled_v11_xlsx: Path
    controlled_workbook: Any
    raw_xls_inventory: dict[str, Any]
    xlsx_inventory: dict[str, Any]
    expected_locations: dict[str, Any]
    comparison_v11_xls: Path
    comparison_v11_xlsx: Path
    comparison_workbook: Any
    comparison_raw_xls_inventory: dict[str, Any]
    comparison_xlsx_inventory: dict[str, Any]


@dataclass(frozen=True)
class ControlledV11Roundtrip:
    """A committed v1.1 candidate after the same controlled conversion path."""

    controlled_xls: Path
    controlled_xlsx: Path
    controlled_workbook: Any
    raw_xls_inventory: dict[str, Any]
    xlsx_inventory: dict[str, Any]


_BASELINE_CACHE: dict[tuple[str, str], ControlledV11Baseline] = {}
_CANDIDATE_CACHE: dict[tuple[str, str, str], ControlledV11Roundtrip] = {}


def _inventory_errors(
    label: str,
    inventory: dict[str, Any],
    expected_inventory: dict[str, Any],
    variant: str,
) -> list[str]:
    errors = [f"{label}: {error}" for error in inventory.get("errors", [])]
    errors.extend(
        f"{label}: {error}"
        for error in compare_named_range_inventories(
            expected_inventory,
            inventory,
            required_names(variant),
        )
    )
    return errors


def _validated_v11_inventory_pair(
    xls_path: Path,
    workbook,
    manifest: dict[str, Any],
    expected_inventory: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    variant = "with_skill"
    raw_xls_inventory = validate_xls_named_range_inventory(
        xls_path,
        manifest["anchors"],
        variant,
    )
    xlsx_inventory = validate_named_range_inventory(
        workbook,
        manifest["anchors"],
        variant,
    )
    inventory_errors = [
        *raw_xls_inventory.get("errors", []),
        *xlsx_inventory.get("errors", []),
        *compare_xls_and_xlsx_named_ranges(
            raw_xls_inventory,
            xlsx_inventory,
            required_names(variant),
        ),
        *compare_named_range_inventories(
            raw_xls_inventory,
            xlsx_inventory,
            required_names(variant),
        ),
    ]
    if expected_inventory is not None:
        inventory_errors.extend(
            _inventory_errors(
                "controlled XLS",
                raw_xls_inventory,
                expected_inventory,
                variant,
            )
        )
        inventory_errors.extend(
            _inventory_errors(
                "controlled XLSX",
                xlsx_inventory,
                expected_inventory,
                variant,
            )
        )
    if inventory_errors:
        raise RuntimeError(
            "Controlled v1.1 named-range inventory is invalid: "
            + "; ".join(sorted(set(inventory_errors)))
        )
    return raw_xls_inventory, xlsx_inventory


def _roundtrip_xlsx_with_openpyxl(
    source_xlsx: Path,
    temp_dir: Path,
    soffice: str,
) -> tuple[Path, Path, Any]:
    """Reproduce the current-environment post-build XLS round trip."""
    normalized_xlsx = temp_dir / "openpyxl-xlsx" / source_xlsx.name
    normalized_xlsx.parent.mkdir(parents=True, exist_ok=True)
    load_workbook(source_xlsx, data_only=False).save(normalized_xlsx)
    controlled_xls = convert_to_xls(
        normalized_xlsx,
        temp_dir / "controlled-xls",
        soffice,
    )
    normalize_libreoffice_print_title_records(controlled_xls)
    normalize_xls_summary_information(controlled_xls)
    controlled_xlsx = convert_to_xlsx(
        controlled_xls,
        temp_dir / "controlled-xlsx",
        soffice,
    )
    return controlled_xls, controlled_xlsx, load_workbook(controlled_xlsx, data_only=False)


def build_controlled_v11_baseline(
    temp_dir: Path,
    soffice: str,
) -> ControlledV11Baseline:
    """Create a v1.1 workbook from canonical v1.0 in the current environment.

    The cache is scoped to the caller's temporary directory. This keeps all
    artifacts disposable while ensuring repeated comparisons in one process do
    not start another LibreOffice conversion pipeline.
    """
    temp_dir = Path(temp_dir).expanduser().resolve()
    cache_key = (str(temp_dir), str(soffice))
    cached = _BASELINE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    temp_dir.mkdir(parents=True, exist_ok=True)
    base_manifest = load_manifest(V10_MANIFEST)
    v11_manifest = load_manifest(V11_MANIFEST)
    variant = "with_skill"
    expected_locations = expected_named_range_locations(base_manifest["structure"], variant)
    expected_inventory = {
        "locations": {
            name: location.to_dict() for name, location in expected_locations.items()
        }
    }

    source_xlsx = convert_to_xlsx(V10_TEMPLATE, temp_dir / "v10-source-xlsx", soffice)
    named_xlsx = temp_dir / "v11-controlled-source" / "template.xlsx"
    named_xlsx.parent.mkdir(parents=True, exist_ok=True)
    workbook = load_workbook(source_xlsx, data_only=False)
    for name in required_names(variant):
        set_named_range_from_location(workbook, expected_locations[name])
    workbook.save(named_xlsx)

    controlled_xls = convert_to_xls(named_xlsx, temp_dir / "v11-controlled-xls", soffice)
    normalize_libreoffice_print_title_records(controlled_xls)
    normalize_xls_summary_information(controlled_xls)
    controlled_xlsx = convert_to_xlsx(
        controlled_xls,
        temp_dir / "v11-controlled-roundtrip-xlsx",
        soffice,
    )
    controlled_workbook = load_workbook(controlled_xlsx, data_only=False)

    raw_xls_inventory, xlsx_inventory = _validated_v11_inventory_pair(
        controlled_xls,
        controlled_workbook,
        v11_manifest,
        expected_inventory,
    )

    # The committed v1.1 XLS was itself produced by a LibreOffice/openpyxl
    # round trip before the validator opens it. Give the canonical baseline
    # the same post-build history so comparison remains tied to the canonical
    # v1.0 source rather than to platform-specific global ignores.
    comparison_v11_xls, comparison_v11_xlsx, comparison_workbook = _roundtrip_xlsx_with_openpyxl(
        controlled_xlsx,
        temp_dir / "controlled-v11-comparison",
        soffice,
    )
    comparison_raw_xls_inventory, comparison_xlsx_inventory = _validated_v11_inventory_pair(
        comparison_v11_xls,
        comparison_workbook,
        v11_manifest,
        expected_inventory,
    )

    baseline = ControlledV11Baseline(
        controlled_v11_xls=controlled_xls,
        controlled_v11_xlsx=controlled_xlsx,
        controlled_workbook=controlled_workbook,
        raw_xls_inventory=raw_xls_inventory,
        xlsx_inventory=xlsx_inventory,
        expected_locations=expected_locations,
        comparison_v11_xls=comparison_v11_xls,
        comparison_v11_xlsx=comparison_v11_xlsx,
        comparison_workbook=comparison_workbook,
        comparison_raw_xls_inventory=comparison_raw_xls_inventory,
        comparison_xlsx_inventory=comparison_xlsx_inventory,
    )
    _BASELINE_CACHE[cache_key] = baseline
    return baseline


def build_controlled_v11_candidate_roundtrip(
    template_xls: Path,
    temp_dir: Path,
    soffice: str,
) -> ControlledV11Roundtrip:
    """Round-trip a committed v1.1 candidate through the controlled path."""
    template_xls = Path(template_xls).expanduser().resolve()
    temp_dir = Path(temp_dir).expanduser().resolve()
    cache_key = (str(template_xls), str(temp_dir), str(soffice))
    cached = _CANDIDATE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    temp_dir.mkdir(parents=True, exist_ok=True)
    v11_manifest = load_manifest(V11_MANIFEST)
    source_xlsx = convert_to_xlsx(template_xls, temp_dir / "source-xlsx", soffice)
    controlled_xls, controlled_xlsx, controlled_workbook = _roundtrip_xlsx_with_openpyxl(
        source_xlsx,
        temp_dir,
        soffice,
    )
    raw_xls_inventory, xlsx_inventory = _validated_v11_inventory_pair(
        controlled_xls,
        controlled_workbook,
        v11_manifest,
    )
    candidate = ControlledV11Roundtrip(
        controlled_xls=controlled_xls,
        controlled_xlsx=controlled_xlsx,
        controlled_workbook=controlled_workbook,
        raw_xls_inventory=raw_xls_inventory,
        xlsx_inventory=xlsx_inventory,
    )
    _CANDIDATE_CACHE[cache_key] = candidate
    return candidate
