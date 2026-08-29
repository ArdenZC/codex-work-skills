"""Path containment checks shared by the lesson-plan production workflow."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Iterable


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _long_existing_ancestor(path: Path) -> Path:
    """Expand an existing Windows ancestor, including short 8.3 aliases."""

    absolute = _absolute_lexical(path)
    if os.name != "nt":
        return absolute
    missing: list[str] = []
    current = absolute
    while not current.exists() and current != current.parent:
        missing.append(current.name)
        current = current.parent
    if not current.exists():
        return absolute
    try:
        kernel32 = ctypes.windll.kernel32
        get_long_path_name = kernel32.GetLongPathNameW
        get_long_path_name.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        get_long_path_name.restype = ctypes.c_uint32
        buffer_size = 32768
        buffer = ctypes.create_unicode_buffer(buffer_size)
        length = get_long_path_name(str(current), buffer, buffer_size)
        if not length or length >= buffer_size:
            return absolute
        expanded = Path(buffer.value)
        for part in reversed(missing):
            expanded /= part
        return expanded
    except (AttributeError, OSError):  # pragma: no cover - non-Windows API variants
        return absolute


def _variants(path: Path) -> set[str]:
    lexical = _absolute_lexical(path)
    values = {str(lexical), str(lexical.resolve(strict=False)), str(_long_existing_ancestor(lexical))}
    if os.name == "nt":
        values.update(value.casefold() for value in tuple(values))
    return {os.path.normpath(value) for value in values}


def _contains(parent: str, child: str) -> bool:
    try:
        return os.path.commonpath([parent, child]) == parent
    except ValueError:
        return False


def paths_overlap(left: Path | str, right: Path | str) -> bool:
    """Return true for equality or either lexical/resolved containment direction."""

    left_values = _variants(Path(left))
    right_values = _variants(Path(right))
    for left_value in left_values:
        for right_value in right_values:
            if left_value == right_value or _contains(left_value, right_value) or _contains(right_value, left_value):
                return True
    return False


def paths_equal(left: Path | str, right: Path | str) -> bool:
    """Return true when two paths identify the same file across supported aliases."""

    return bool(_variants(Path(left)) & _variants(Path(right)))


def assert_output_path_safe(output_dir: Path | str, protected_paths: Iterable[Path | str]) -> Path:
    output = _absolute_lexical(Path(output_dir))
    for protected in protected_paths:
        if paths_overlap(output, protected):
            raise ValueError(f"Output directory must not overlap protected path: {protected}")
    return output


def assert_external_qa_path_safe(
    qa_report: Path | str,
    output_dir: Path | str,
    protected_paths: Iterable[Path | str],
) -> Path:
    """Validate an external QA path before it participates in a generation commit."""

    report = _absolute_lexical(Path(qa_report))
    output = _absolute_lexical(Path(output_dir))
    if report.exists() and report.is_dir():
        raise ValueError(f"External QA report path must be a file, not a directory: {report}")
    if paths_overlap(report, output):
        raise ValueError(f"External QA report must not overlap output directory: {output}")
    for protected in protected_paths:
        if paths_overlap(report, protected):
            raise ValueError(f"External QA report must not overlap protected path: {protected}")
    return report


def lesson_protected_paths(
    *,
    skill_dir: Path,
    source: Path,
    schema: Path,
    template: Path,
    manifest: Path,
    package_roots: Iterable[Path] = (),
) -> list[Path]:
    paths = [skill_dir, source, schema, template, manifest, manifest.parent, *package_roots]
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = _absolute_lexical(Path(path))
        key = os.path.normcase(os.path.normpath(str(resolved)))
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result
