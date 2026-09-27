"""Aggregate per-Lesson Benchmark Reviews into one deterministic course summary."""

from __future__ import annotations

import sys

from validate_benchmark_review import main


if __name__ == "__main__":
    raise SystemExit(main(["--aggregate", *sys.argv[1:]]))
