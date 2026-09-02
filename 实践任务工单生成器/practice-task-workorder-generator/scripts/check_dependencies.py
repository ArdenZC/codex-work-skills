"""Read-only dependency doctor for the Practice Work Order Skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = {
    "docx": "python-docx",
    "yaml": "PyYAML",
    "jsonschema": "jsonschema",
}


def check_dependencies() -> dict[str, Any]:
    missing = [package for module, package in REQUIRED_MODULES.items() if importlib.util.find_spec(module) is None]
    return {
        "status": "pass" if not missing else "fail",
        "required": list(REQUIRED_MODULES.values()),
        "missing": missing,
        "install_hint": "pip install -r requirements.txt" if missing else None,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = check_dependencies()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["status"])
        if report["missing"]:
            print("missing: " + ", ".join(report["missing"]))
            print(report["install_hint"])
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
