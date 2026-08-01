from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from package_common import DEFAULT_SCHEMA, validate_input


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate normalized gradebook input against the package schema.")
    parser.add_argument("--input-json", required=True)
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.input_json).read_text(encoding="utf-8-sig"))
        validate_input(data, args.schema)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"validated input={Path(args.input_json).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
