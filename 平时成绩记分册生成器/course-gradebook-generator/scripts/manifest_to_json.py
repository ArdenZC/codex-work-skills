from __future__ import annotations

import argparse
import json
from pathlib import Path

from package_common import (
    DEFAULT_MANIFEST,
    load_manifest,
    protected_template_package_directories,
    protected_template_package_paths,
    resolve_template_package,
    validate_template_package_identity,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert the gradebook YAML manifest to JSON for the PowerShell compatibility path.")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--template", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    package = resolve_template_package(args.template or None, args.manifest or None)
    manifest = load_manifest(package.manifest_path)
    protected_paths = protected_template_package_paths(
        package.manifest,
        selected_template=package.template_path,
    )
    protected_directories = protected_template_package_directories(
        package.manifest,
        selected_template=package.template_path,
    )
    manifest.pop("_path", None)
    manifest["template_path"] = str(package.template_path)
    manifest["manifest_path"] = str(package.manifest_path)
    manifest["anchor_mode"] = package.anchor_mode
    manifest["protected_package_paths"] = sorted(str(path) for path in protected_paths)
    manifest["protected_package_directories"] = sorted(str(path) for path in protected_directories)
    validate_template_package_identity(package.template_path, package.manifest)
    payload = json.dumps(manifest, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
