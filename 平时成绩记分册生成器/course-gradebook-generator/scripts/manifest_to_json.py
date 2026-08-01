from __future__ import annotations

import argparse
import json
from pathlib import Path

from package_common import DEFAULT_MANIFEST, load_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert the gradebook YAML manifest to JSON for the PowerShell compatibility path.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    manifest.pop("_path", None)
    payload = json.dumps(manifest, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
