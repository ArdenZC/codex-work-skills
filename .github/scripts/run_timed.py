"""Run a command and record its duration in GitHub Actions summary."""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    started = time.monotonic()
    result = subprocess.run(command, check=False)
    duration = time.monotonic() - started
    line = f"- {args.label}: {duration:.2f}s"
    print(line)
    summary = args.summary
    if summary is None and os.environ.get("GITHUB_STEP_SUMMARY"):
        summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
    if summary:
        with summary.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
