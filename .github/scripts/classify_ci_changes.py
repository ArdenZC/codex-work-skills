"""Classify changed repository paths into the CI suites they require."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterable, Sequence


DOC_EXACT = frozenset(
    {
        "README.md",
        "教案生成器/简介.md",
        "平时成绩记分册生成器/简介.md",
        "多Agent兼容规范.md",
    }
)
DOC_PREFIX = "docs/"
LESSON_ROOT = "教案生成器/lesson-plan-docx-generator"
GRADEBOOK_ROOT = "平时成绩记分册生成器/course-gradebook-generator"
ZERO_SHA = "0" * 40
BOOLEAN_KEYS = (
    "docs_only",
    "run_docs",
    "run_lesson",
    "run_gradebook",
    "run_tooling",
    "run_release",
    "run_package_contracts",
    "force_full",
)


def _normalize_path(path: str) -> str:
    normalized = str(path).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def is_documentation_path(path: str) -> bool:
    """Return whether a path is in the intentionally small docs allowlist."""

    normalized = _normalize_path(path)
    return normalized in DOC_EXACT or (
        normalized.startswith(DOC_PREFIX) and normalized.endswith(".md")
    )


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _is_package_risk(path: str) -> bool:
    lowered = path.casefold()
    name = lowered.rsplit("/", 1)[-1]
    return (
        "/assets/templates/" in f"/{lowered}"
        or "/schemas/" in f"/{lowered}"
        or name.startswith("manifest.")
        or name in {
            "package_common.py",
            "validate_template.py",
            "build_named_range_template.py",
            "named_range_contracts.py",
            "named_range_utils.py",
            "xls_named_range_utils.py",
            "named_range_template_baseline.py",
            "install.py",
            "install_adapters.py",
        }
        or "validator" in name
    )


def _base_result(paths: Iterable[str]) -> dict[str, object]:
    return {
        "docs_only": False,
        "run_docs": False,
        "run_lesson": False,
        "run_gradebook": False,
        "run_tooling": False,
        "run_release": False,
        "run_package_contracts": False,
        "force_full": False,
        "classification": "full",
        "reason": "",
        "changed_files": sorted({_normalize_path(path) for path in paths if _normalize_path(path)}),
    }


def _mark(result: dict[str, object], *keys: str) -> None:
    for key in keys:
        result[key] = True


def _full_result(
    paths: Iterable[str],
    reason: str,
    *,
    classification: str = "full",
) -> dict[str, object]:
    result = _base_result(paths)
    _mark(result, "force_full", "run_lesson", "run_gradebook", "run_tooling", "run_release", "run_package_contracts")
    result["classification"] = classification
    result["reason"] = reason
    return result


def _classification(labels: set[str]) -> str:
    if not labels:
        return "full"
    order = ("docs", "lesson", "gradebook", "tooling", "release")
    return "+".join(label for label in order if label in labels)


def classify(
    paths: Sequence[str],
    *,
    event_name: str,
    ambiguous: bool = False,
) -> dict[str, object]:
    """Return the affected CI suites for a changed path set.

    The function deliberately treats empty, ambiguous, unknown, and manual
    inputs as full CI.  This is the fail-closed boundary for the workflow.
    """

    normalized = sorted({_normalize_path(path) for path in paths if _normalize_path(path)})
    if event_name in {"workflow_dispatch", "schedule"}:
        return _full_result(normalized, f"{event_name} requests a full regression")
    if event_name not in {"pull_request", "push"}:
        return _full_result(normalized, f"unsupported event {event_name!r} requires full CI")
    if ambiguous:
        return _full_result(normalized, "deleted or renamed paths require full CI")
    if not normalized:
        return _full_result(normalized, "changed paths are empty or unavailable")

    result = _base_result(normalized)
    labels: set[str] = set()
    reasons: list[str] = []
    unknown: list[str] = []
    documentation_count = 0

    for path in normalized:
        if is_documentation_path(path):
            labels.add("docs")
            documentation_count += 1
            continue

        if path == ".github/workflows/template-package-ci.yml" or path.startswith(".github/scripts/"):
            return _full_result(normalized, f"shared CI helper changed: {path}")
        if path == "tests/test_template_packages.py" or path == "tests/validate_template_packages.py":
            return _full_result(normalized, f"shared package contract test changed: {path}")
        if path.startswith("requirements") or path.endswith("/requirements.txt"):
            return _full_result(normalized, f"dependency contract changed: {path}")

        if _under(path, LESSON_ROOT):
            _mark(result, "run_lesson", "run_package_contracts")
            labels.add("lesson")
            reasons.append("lesson package")
            if _is_package_risk(path):
                _mark(result, "run_tooling", "run_release")
                labels.update({"tooling", "release"})
                reasons.append("lesson package contract")
            continue

        if _under(path, GRADEBOOK_ROOT):
            _mark(result, "run_gradebook", "run_package_contracts")
            labels.add("gradebook")
            reasons.append("gradebook package")
            if _is_package_risk(path):
                _mark(result, "run_tooling", "run_release")
                labels.update({"tooling", "release"})
                reasons.append("gradebook package contract")
            continue

        if path == "tools/template_package.py" or _under(path, "tools/template_tooling"):
            _mark(result, "run_tooling", "run_release", "run_package_contracts")
            labels.update({"tooling", "release"})
            reasons.append("template tooling")
            continue

        if path in {
            "tests/test_template_package_tooling.py",
            "tests/test_template_package_release.py",
            ".github/workflows/template-release.yml",
        }:
            _mark(result, "run_tooling", "run_release", "run_package_contracts")
            labels.update({"tooling", "release"})
            reasons.append("template lifecycle")
            continue

        if path.endswith("/install.py") or path.endswith("/install_adapters.py"):
            _mark(result, "run_tooling", "run_release", "run_package_contracts")
            labels.update({"tooling", "release"})
            reasons.append("installation lifecycle")
            continue

        unknown.append(path)

    if unknown:
        return _full_result(normalized, "unknown or ambiguous paths require full CI: " + ", ".join(unknown))

    if documentation_count == len(normalized):
        result["docs_only"] = True
        result["run_docs"] = True
        result["classification"] = "docs"
        result["reason"] = "all changed files match the documentation allowlist"
        return result

    result["classification"] = _classification(labels)
    result["reason"] = "; ".join(dict.fromkeys(reasons)) or "affected module paths changed"
    return result


def _git_changed_paths(
    base_sha: str,
    head_sha: str,
    *,
    cwd: Path | None = None,
) -> tuple[list[str], bool]:
    raw_fields = subprocess.check_output(
        ["git", "diff", "--name-status", "--find-renames", "-z", base_sha, head_sha],
        cwd=cwd,
    ).split(b"\0")
    paths: list[str] = []
    ambiguous = False
    index = 0
    while index < len(raw_fields) - 1:
        status = raw_fields[index].decode("ascii", errors="replace")
        index += 1
        if status.startswith(("R", "C")):
            if index + 1 >= len(raw_fields):
                ambiguous = True
                break
            paths.extend(
                field.decode("utf-8", errors="surrogateescape")
                for field in raw_fields[index : index + 2]
            )
            index += 2
        else:
            if index >= len(raw_fields):
                ambiguous = True
                break
            paths.append(raw_fields[index].decode("utf-8", errors="surrogateescape"))
            index += 1
            if status.startswith("D"):
                ambiguous = True
    return paths, ambiguous


def _resolve_event_paths(args: argparse.Namespace) -> tuple[list[str], bool, str | None]:
    if args.event in {"workflow_dispatch", "schedule"}:
        return [], False, None
    if args.event == "pull_request":
        base_sha, head_sha = args.base_sha, args.head_sha
    elif args.event == "push":
        base_sha, head_sha = args.before_sha, args.current_sha
        if base_sha == ZERO_SHA:
            if not head_sha or head_sha == ZERO_SHA:
                return [], True, "push revision is unavailable"
            base_sha = subprocess.check_output(
                ["git", "rev-list", "--max-parents=0", head_sha],
                text=True,
                encoding="utf-8",
            ).splitlines()[0]
    else:
        return [], True, f"unsupported event {args.event!r}"
    if not base_sha or not head_sha or base_sha == ZERO_SHA or head_sha == ZERO_SHA:
        return [], True, "comparison revision is unavailable"
    paths, ambiguous = _git_changed_paths(base_sha, head_sha)
    return paths, ambiguous, None


def _write_multiline(handle, key: str, values: Iterable[str]) -> None:
    delimiter = f"CI_{key.upper()}_{uuid.uuid4().hex}"
    handle.write(f"{key}<<{delimiter}\n")
    for value in values:
        handle.write(f"{value}\n")
    handle.write(f"{delimiter}\n")


def _required_jobs(result: dict[str, object]) -> list[str]:
    jobs = []
    if result["run_docs"]:
        jobs.append("documentation-checks")
    if result["run_package_contracts"]:
        jobs.append("package-contracts")
    if result["run_tooling"]:
        jobs.append("template-tooling")
    if result["run_lesson"]:
        jobs.append("template-lesson")
    if result["run_gradebook"]:
        jobs.append("template-gradebook")
    if result["run_release"]:
        jobs.append("template-release")
    return jobs


def _write_outputs(result: dict[str, object], output_path: Path | None, summary_path: Path | None, event_name: str) -> None:
    required = _required_jobs(result)
    skipped = [
        name
        for name in (
            "documentation-checks",
            "package-contracts",
            "template-tooling",
            "template-lesson",
            "template-gradebook",
            "template-release",
        )
        if name not in required
    ]
    if output_path:
        with output_path.open("a", encoding="utf-8") as handle:
            for key in BOOLEAN_KEYS:
                handle.write(f"{key}={'true' if result[key] else 'false'}\n")
            handle.write(f"classification={result['classification']}\n")
            handle.write(f"reason={result['reason']}\n")
            _write_multiline(handle, "changed_files", result["changed_files"])
            _write_multiline(handle, "required_jobs", required)
            _write_multiline(handle, "skipped_jobs", skipped)
    if summary_path:
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write("## Change classifier\n\n")
            handle.write(f"- Event: `{event_name}`\n")
            handle.write(f"- Classification: `{result['classification']}`\n")
            handle.write(f"- force_full: `{str(result['force_full']).lower()}`\n")
            handle.write(f"- Reason: {result['reason']}\n\n")
            handle.write("### Changed files\n\n")
            handle.write("\n".join(f"- `{path}`" for path in result["changed_files"]) or "- none")
            handle.write("\n\n### Jobs required\n\n")
            handle.write("\n".join(f"- `{job}`" for job in required) or "- none")
            handle.write("\n\n### Jobs skipped\n\n")
            handle.write("\n".join(f"- `{job}`" for job in skipped) or "- none")
            handle.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--before-sha", default="")
    parser.add_argument("--current-sha", default="")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--assert-docs-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths, ambiguous, error = _resolve_event_paths(args)
        if error:
            result = _full_result(paths, error)
        else:
            result = classify(paths, event_name=args.event, ambiguous=ambiguous)
    except Exception as exc:  # pragma: no cover - defensive workflow boundary
        result = _full_result([], f"classifier exception requires full CI: {exc}")

    _write_outputs(result, args.output, args.summary, args.event)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.assert_docs_only and not result["docs_only"]:
        print(f"docs-only allowlist violation: {result['reason']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
