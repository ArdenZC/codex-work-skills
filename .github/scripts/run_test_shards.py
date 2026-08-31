"""Run the repository regression suite as explicit, isolated test shards.

The normal CI jobs already split the expensive package suites.  This runner
provides the same boundary for local work: a fast Content V2 lane, a full
suite manifest, per-shard timing, and isolated temporary/Office profiles.
It never changes the tests selected by a shard; ``--list`` reports the exact
partition so a new test cannot silently disappear from the full lane.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
TEST_MODULE = "tests.test_template_packages"
GRADEBOOK_SHARDS = ROOT / ".github" / "scripts" / "run_gradebook_shards.py"
LESSON_SKILL_TESTS = ROOT / "教案生成器" / "lesson-plan-docx-generator" / "tests"
GRADEBOOK_SKILL_TESTS = ROOT / "平时成绩记分册生成器" / "course-gradebook-generator" / "tests"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows PowerShell commonly exposes a legacy code page.  Shard logs contain
# repository paths and test data from several locales; replacing only on the
# reporting stream keeps the child test result intact while preventing the
# runner itself from turning a passing shard into an encoding failure.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


@dataclass(frozen=True)
class SuiteSpec:
    """One independently runnable semantic test shard."""

    name: str
    parallel_safe: bool
    kind: str
    count: int
    resource_group: str | None = None


def _class_test_ids(class_name: str, *, include: Iterable[str] | None = None, exclude: Iterable[str] | None = None) -> tuple[str, ...]:
    module = importlib.import_module(TEST_MODULE)
    test_class = getattr(module, class_name)
    names = set(unittest.defaultTestLoader.getTestCaseNames(test_class))
    if include is not None:
        names &= set(include)
    if exclude is not None:
        names -= set(exclude)
    prefix = f"{TEST_MODULE}.{class_name}."
    return tuple(prefix + name for name in sorted(names))


def _lesson_content_ids() -> tuple[str, ...]:
    mixin = importlib.import_module("tests.test_lesson_content_v2").LessonContentV2Mixin
    return _class_test_ids(
        "LessonTemplatePackageTests",
        include=(name for name in vars(mixin) if name.startswith("test_")),
    )


def _lesson_package_ids() -> tuple[str, ...]:
    mixin = importlib.import_module("tests.test_lesson_content_v2").LessonContentV2Mixin
    return _class_test_ids(
        "LessonTemplatePackageTests",
        exclude=(name for name in vars(mixin) if name.startswith("test_")),
    )


def _workflow_ids() -> tuple[str, ...]:
    return _class_test_ids("WorkflowContractTests")


def _static_gradebook_ids() -> tuple[str, ...]:
    return (
        f"{TEST_MODULE}.GradebookTotalRuleTests.test_total_rule_matches_exactly_with_zero_and_nonzero_skill_weights",
        f"{TEST_MODULE}.GradebookPowerShellContractTests.test_com_path_uses_same_rounding_preflight_and_exact_output_contract",
        f"{TEST_MODULE}.GradebookPowerShellContractTests.test_local_com_integration_script_is_repeatable_and_has_skip_boundary",
    )


def _module_count(module_name: str) -> int:
    return unittest.defaultTestLoader.loadTestsFromName(module_name).countTestCases()


def _suite_specs() -> dict[str, SuiteSpec]:
    lesson_content = _lesson_content_ids()
    lesson_package = _lesson_package_ids()
    gradebook_class_count = _module_count(f"{TEST_MODULE}.GradebookTemplatePackageTests")
    gradebook_static_count = len(_static_gradebook_ids())
    workflow = _workflow_ids()
    return {
        "lesson-content": SuiteSpec("lesson-content", True, "ids", len(lesson_content)),
        "lesson-package": SuiteSpec("lesson-package", False, "ids", len(lesson_package)),
        "gradebook": SuiteSpec("gradebook", False, "gradebook", gradebook_class_count + gradebook_static_count, "repository-validator"),
        "package-contracts": SuiteSpec("package-contracts", True, "ids", len(workflow)),
        "tooling": SuiteSpec("tooling", True, "module", _module_count("tests.test_template_package_tooling"), "repository-validator"),
        "release": SuiteSpec("release", False, "module", _module_count("tests.test_template_package_release"), "repository-validator"),
        "classifier": SuiteSpec("classifier", True, "module", _module_count("tests.test_ci_change_classifier")),
        "runner": SuiteSpec("runner", True, "module", _module_count("tests.test_run_test_shards")),
        # The two skill directories intentionally contain the same generic
        # ``test_package`` module name.  They are therefore discovered in
        # separate worker processes; keeping their tiny expected counts here
        # avoids importing both into one interpreter during ``--list``.
        "lesson-skill": SuiteSpec("lesson-skill", True, "discover", 1),
        "gradebook-skill": SuiteSpec("gradebook-skill", True, "discover", 2),
    }


ALIASES = {
    "fast": ("lesson-content", "package-contracts", "classifier", "runner"),
    "full": ("lesson-content", "lesson-package", "gradebook", "package-contracts", "tooling", "release", "classifier", "runner"),
    "ci": ("full", "lesson-skill", "gradebook-skill"),
}


def _expand_suites(requested: Sequence[str], specs: dict[str, SuiteSpec]) -> tuple[str, ...]:
    result: list[str] = []

    def append(name: str) -> None:
        names = ALIASES.get(name, (name,))
        for expanded in names:
            if expanded in ALIASES:
                append(expanded)
            elif expanded not in result:
                if expanded not in specs:
                    raise ValueError(f"unknown test suite: {expanded}")
                result.append(expanded)

    for name in requested:
        append(name)
    return tuple(result)


def _suite_test_ids(name: str) -> tuple[str, ...]:
    if name == "lesson-content":
        return _lesson_content_ids()
    if name == "lesson-package":
        return _lesson_package_ids()
    if name == "package-contracts":
        return _workflow_ids()
    if name == "tooling":
        return ("tests.test_template_package_tooling",)
    if name == "release":
        return ("tests.test_template_package_release",)
    if name == "classifier":
        return ("tests.test_ci_change_classifier",)
    if name == "runner":
        return ("tests.test_run_test_shards",)
    return ()


def _suite_count(name: str, specs: dict[str, SuiteSpec]) -> int:
    return specs[name].count


def _discover_count(name: str) -> int:
    if name == "lesson-skill":
        start_dir = LESSON_SKILL_TESTS
    elif name == "gradebook-skill":
        start_dir = GRADEBOOK_SKILL_TESTS
    else:
        raise ValueError(f"unsupported discovery suite: {name}")
    return unittest.defaultTestLoader.discover(str(start_dir), pattern="test_*").countTestCases()


def _isolated_environment(shard_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["CODEX_TEST_SHARD_ROOT"] = str(shard_root)
    environment["TEMP"] = str(shard_root)
    environment["TMP"] = str(shard_root)
    environment["TMPDIR"] = str(shard_root)
    environment["PYTHONPYCACHEPREFIX"] = str(shard_root / "python-cache")
    # Do not rewrite the host Office profile.  The repository's isolated owner
    # validators deliberately use a normal Skill tree and LibreOffice's native
    # profile; changing USERPROFILE/APPDATA on Windows makes those conversions
    # fail before the validator can inspect the copied workbook.  The default
    # scheduler therefore serializes Office/COM shards, while TEMP/TMP and
    # Python cache isolation still keeps artifacts off the system volume.
    return environment


def _run_ids(ids: Sequence[str], *, verbose: bool) -> int:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for test_id in ids:
        suite.addTests(loader.loadTestsFromName(test_id))
    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


def _run_discovery(name: str, *, verbose: bool) -> int:
    if name == "lesson-skill":
        start_dir = LESSON_SKILL_TESTS
    elif name == "gradebook-skill":
        start_dir = GRADEBOOK_SKILL_TESTS
    else:
        raise ValueError(f"unsupported discovery suite: {name}")
    suite = unittest.defaultTestLoader.discover(str(start_dir), pattern="test_*")
    result = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


def _run_worker(name: str, *, verbose: bool) -> int:
    if name == "gradebook":
        command = [sys.executable, str(GRADEBOOK_SHARDS), "--group", "contracts", "--group", "generation"]
        if sys.platform == "darwin":
            command.append("--sequential")
        return subprocess.run(command, cwd=ROOT, env=os.environ.copy(), check=False).returncode
    spec = _suite_specs()[name]
    if spec.kind == "module":
        return _run_ids(_suite_test_ids(name), verbose=verbose)
    if spec.kind == "discover":
        return _run_discovery(name, verbose=verbose)
    return _run_ids(_suite_test_ids(name), verbose=verbose)


def _run_one(name: str, *, python: str, root: Path, verbose: bool) -> tuple[int, float, Path]:
    shard_root = root / name
    shard_root.mkdir(parents=True, exist_ok=True)
    log_path = shard_root / "output.log"
    command = [python, str(Path(__file__).resolve()), "--worker", "--suite", name]
    if verbose:
        command.append("--verbose")
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8", errors="replace") as stream:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=_isolated_environment(shard_root),
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return result.returncode, time.monotonic() - started, log_path


def _run_parent(names: Sequence[str], *, python: str, root: Path, parallel: bool, allow_office_parallel: bool, verbose: bool) -> int:
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results: dict[str, tuple[int, float, Path]] = {}

    if not parallel:
        for name in names:
            results[name] = _run_one(name, python=python, root=root, verbose=verbose)
    else:
        pending = list(names)
        running: dict[str, tuple[subprocess.Popen[bytes], Path, object, float]] = {}
        specs = _suite_specs()

        def can_start(name: str) -> bool:
            """Return whether a pending shard can share the current workers.

            Safe shards may overlap by default.  Office/COM shards remain
            serialized unless explicitly opted into, and repository-wide
            validators use a shared lock even in opt-in mode because they
            inspect and materialize the same canonical package trees.
            """

            spec = specs[name]
            if not allow_office_parallel:
                if not spec.parallel_safe and running:
                    return False
                if any(not specs[running_name].parallel_safe for running_name in running):
                    return False
            if spec.resource_group is not None and any(
                specs[running_name].resource_group == spec.resource_group for running_name in running
            ):
                return False
            return True

        while pending or running:
            capacity = max(1, min(len(pending), os.cpu_count() or 1))
            while pending and len(running) < capacity:
                candidate_index = next((index for index, name in enumerate(pending) if can_start(name)), None)
                if candidate_index is None:
                    break
                candidate = pending.pop(candidate_index)
                spec = specs[candidate]
                shard_root = root / candidate
                shard_root.mkdir(parents=True, exist_ok=True)
                log_path = shard_root / "output.log"
                handle = log_path.open("wb")
                command = [python, str(Path(__file__).resolve()), "--worker", "--suite", candidate]
                if verbose:
                    command.append("--verbose")
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=_isolated_environment(shard_root),
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                )
                running[candidate] = (process, log_path, handle, time.monotonic())
                if not allow_office_parallel and not spec.parallel_safe:
                    break
            for name, (process, log_path, handle, item_started) in tuple(running.items()):
                status = process.poll()
                if status is not None:
                    handle.close()
                    results[name] = (status, time.monotonic() - item_started, log_path)
                    del running[name]
            if running:
                time.sleep(0.1)

    failures = 0
    print(f"test shard run: {time.monotonic() - started:.2f}s, suites={len(names)}")
    for name in names:
        status, duration, log_path = results[name]
        print(f"[{name}] {duration:.2f}s exit={status} log={log_path}")
        output = log_path.read_text(encoding="utf-8", errors="replace")
        print(output, end="")
        failures += status != 0
    return 1 if failures else 0


def _print_manifest(specs: dict[str, SuiteSpec], *, as_json: bool) -> int:
    payload: dict[str, object] = {"suites": {}, "aliases": {}}
    for name, spec in specs.items():
        payload["suites"][name] = {
            "tests": _suite_count(name, specs),
            "parallel_safe": spec.parallel_safe,
            "kind": spec.kind,
            "resource_group": spec.resource_group,
        }
    for alias, names in ALIASES.items():
        expanded = _expand_suites((alias,), specs)
        payload["aliases"][alias] = {
            "suites": expanded,
            "tests": sum(_suite_count(name, specs) for name in expanded),
        }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for name, details in payload["suites"].items():
        print(f"{name}: {details['tests']} tests, parallel_safe={details['parallel_safe']}")
    for alias, details in payload["aliases"].items():
        print(f"{alias}: {details['tests']} tests ({', '.join(details['suites'])})")
    full_count = int(payload["aliases"]["full"]["tests"])
    discovered_count = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py").countTestCases()
    if full_count != discovered_count:
        raise SystemExit(
            f"full shard manifest does not cover root discovery: manifest={full_count}, discovered={discovered_count}"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", action="append", choices=tuple((*ALIASES, *_suite_specs())), help="suite or alias to run")
    parser.add_argument("--list", action="store_true", dest="list_suites")
    parser.add_argument("--json", action="store_true", help="emit --list output as JSON")
    parser.add_argument("--parallel", action="store_true", help="run safe shards concurrently")
    parser.add_argument("--allow-office-parallel", action="store_true", help="also overlap Office/COM shards (opt-in)")
    parser.add_argument("--root", type=Path, help="artifact root on a non-system volume")
    parser.add_argument("--python", default=sys.executable, help="Python executable used for worker processes")
    parser.add_argument("--keep-artifacts", action="store_true", help="keep shard logs and temporary outputs")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    specs = _suite_specs()
    if args.list_suites:
        return _print_manifest(specs, as_json=args.json)
    if not args.suite:
        parser.error("--suite is required (use --list to inspect the manifest)")
    names = _expand_suites(args.suite, specs)
    if args.worker:
        if len(names) != 1:
            parser.error("--worker accepts exactly one concrete suite")
        return _run_worker(names[0], verbose=args.verbose)

    artifact_root = args.root
    temporary_root: Path | None = None
    if artifact_root is None:
        temporary_root = Path(tempfile.mkdtemp(prefix="codex-test-shards-"))
        artifact_root = temporary_root
    try:
        return _run_parent(
            names,
            python=str(Path(args.python).resolve()),
            root=artifact_root,
            parallel=args.parallel,
            allow_office_parallel=args.allow_office_parallel,
            verbose=args.verbose,
        )
    finally:
        if temporary_root is not None and not args.keep_artifacts:
            shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
