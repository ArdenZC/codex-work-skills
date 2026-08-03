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


_BASELINE_CACHE: dict[tuple[str, str], ControlledV11Baseline] = {}


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

    raw_xls_inventory = validate_xls_named_range_inventory(
        controlled_xls,
        v11_manifest["anchors"],
        variant,
    )
    xlsx_inventory = validate_named_range_inventory(
        controlled_workbook,
        v11_manifest["anchors"],
        variant,
    )
    inventory_errors = _inventory_errors(
        "controlled XLS",
        raw_xls_inventory,
        expected_inventory,
        variant,
    )
    inventory_errors.extend(
        _inventory_errors(
            "controlled XLSX",
            xlsx_inventory,
            expected_inventory,
            variant,
        )
    )
    inventory_errors.extend(
        compare_xls_and_xlsx_named_ranges(
            raw_xls_inventory,
            xlsx_inventory,
            required_names(variant),
        )
    )
    inventory_errors.extend(
        compare_named_range_inventories(
            raw_xls_inventory,
            xlsx_inventory,
            required_names(variant),
        )
    )
    if inventory_errors:
        raise RuntimeError(
            "Controlled v1.1 baseline named-range inventory is invalid: "
            + "; ".join(sorted(set(inventory_errors)))
        )

    baseline = ControlledV11Baseline(
        controlled_v11_xls=controlled_xls,
        controlled_v11_xlsx=controlled_xlsx,
        controlled_workbook=controlled_workbook,
        raw_xls_inventory=raw_xls_inventory,
        xlsx_inventory=xlsx_inventory,
        expected_locations=expected_locations,
    )
    _BASELINE_CACHE[cache_key] = baseline
    return baseline
