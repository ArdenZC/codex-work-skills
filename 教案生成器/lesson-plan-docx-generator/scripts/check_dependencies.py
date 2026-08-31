"""Read-only dependency check for the Lesson Skill runtime."""

from __future__ import annotations

import importlib.util
import sys


REQUIRED_DEPENDENCIES = (
    ("docx", "python-docx"),
    ("yaml", "PyYAML"),
    ("jsonschema", "jsonschema"),
)


def check_dependencies() -> tuple[bool, list[str]]:
    missing: list[str] = []
    for module_name, package_name in REQUIRED_DEPENDENCIES:
        available = importlib.util.find_spec(module_name) is not None
        print(f"{module_name}: {'installed' if available else 'missing'}")
        if not available:
            missing.append(package_name)
    return not missing, missing


def main() -> int:
    print("dependency status:")
    ready, missing = check_dependencies()
    if ready:
        print("ready")
        return 0
    print("missing dependencies: " + ", ".join(missing))
    print("install with: pip install -r requirements.txt")
    return 1


if __name__ == "__main__":
    sys.exit(main())
