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
GRADEBOOK_SCRIPTS = ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "scripts"


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


def _prewarm_controlled_baseline() -> float:
    """Build or validate the shared immutable baseline before forking shards."""
    candidates = (
        shutil.which("soffice"),
        shutil.which("soffice.com"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
    )
    soffice = next((candidate for candidate in candidates if candidate and Path(candidate).exists()), None)
    if soffice is None:
        raise RuntimeError("LibreOffice/soffice is required to prewarm the Gradebook baseline")

    if str(GRADEBOOK_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(GRADEBOOK_SCRIPTS))
    from named_range_template_baseline import build_controlled_v11_baseline

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="gradebook-shard-baseline-") as temp_name:
        build_controlled_v11_baseline(Path(temp_name), str(soffice))
    return time.monotonic() - started


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", action="append", dest="groups", choices=DEFAULT_GROUPS)
    parser.add_argument("--sequential", action="store_true")
    args = parser.parse_args(argv)
    groups = tuple(args.groups or DEFAULT_GROUPS)
    if len(set(groups)) != len(groups):
        parser.error("each semantic group may be specified only once")

    log_root = Path(tempfile.mkdtemp(prefix="gradebook-shards-"))
    processes: dict[str, tuple[subprocess.Popen[bytes], Path, float]] = {}
    handles = []
    try:
        baseline_seconds = _prewarm_controlled_baseline()
        print(f"Gradebook controlled baseline ready ({baseline_seconds:.2f}s)")
        statuses: dict[str, int] = {}
        durations: dict[str, float] = {}

        def start_group(group: str) -> tuple[subprocess.Popen[bytes], Path, float]:
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
            return process, log_path, time.monotonic()

        if args.sequential:
            for group in groups:
                processes[group] = start_group(group)
                process, _, started = processes[group]
                statuses[group] = process.wait()
                durations[group] = time.monotonic() - started
        else:
            for group in groups:
                processes[group] = start_group(group)
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

        summary_lines = [
            "### Gradebook semantic shards",
            f"- controlled baseline prewarm: {baseline_seconds:.2f}s",
        ]
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
