"""Run gradebook semantic test groups concurrently on one runner."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[2]
TEST_RUNNER = ROOT / ".github" / "scripts" / "run_gradebook_tests.py"
DEFAULT_GROUPS = ("contracts", "generation")


def _isolated_office_environment(profile_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    if os.name == "nt":
        environment["USERPROFILE"] = str(profile_root)
        environment["APPDATA"] = str(profile_root / "AppData" / "Roaming")
        environment["LOCALAPPDATA"] = str(profile_root / "AppData" / "Local")
    else:
        environment["HOME"] = str(profile_root)
        environment["XDG_CONFIG_HOME"] = str(profile_root / ".config")
    return environment


def _append_summary(lines: list[str]) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    with Path(summary).open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", action="append", dest="groups", choices=DEFAULT_GROUPS)
    args = parser.parse_args(argv)
    groups = tuple(args.groups or DEFAULT_GROUPS)
    if len(set(groups)) != len(groups):
        parser.error("each semantic group may be specified only once")

    log_root = Path(tempfile.mkdtemp(prefix="gradebook-shards-"))
    processes: dict[str, tuple[subprocess.Popen[bytes], Path, float]] = {}
    handles = []
    try:
        for group in groups:
            group_root = log_root / group
            group_root.mkdir()
            log_path = group_root / "output.log"
            handle = log_path.open("wb")
            handles.append(handle)
            process = subprocess.Popen(
                [sys.executable, str(TEST_RUNNER), "--group", group, "--verbose"],
                cwd=ROOT,
                env=_isolated_office_environment(group_root / "office-profile"),
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            processes[group] = (process, log_path, time.monotonic())

        statuses: dict[str, int] = {}
        durations: dict[str, float] = {}
        pending = set(processes)
        while pending:
            for group in tuple(pending):
                process, _, started = processes[group]
                status = process.poll()
                if status is not None:
                    statuses[group] = status
                    durations[group] = time.monotonic() - started
                    pending.remove(group)
            if pending:
                time.sleep(0.1)

        summary_lines = ["### Gradebook semantic shards"]
        for group in groups:
            summary_lines.append(
                f"- {group}: {durations[group]:.2f}s, exit={statuses[group]}"
            )
        _append_summary(summary_lines)

        for group in groups:
            _, log_path, _ = processes[group]
            print(f"===== gradebook shard: {group} =====")
            print(log_path.read_text(encoding="utf-8", errors="replace"), end="")
            print(f"===== gradebook shard: {group} ({durations[group]:.2f}s, exit={statuses[group]}) =====")
        return 0 if all(status == 0 for status in statuses.values()) else 1
    finally:
        for handle in handles:
            handle.close()
        shutil.rmtree(log_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
