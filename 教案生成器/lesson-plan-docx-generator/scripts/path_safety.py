"""Path containment checks shared by the lesson-plan production workflow."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable


IS_WINDOWS = os.name == "nt"


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _long_existing_ancestor(path: Path) -> Path:
    """Expand an existing Windows ancestor, including short 8.3 aliases."""

    absolute = _absolute_lexical(path)
    if not IS_WINDOWS:
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


def filesystem_case_sensitive(path: Path | str) -> bool:
    """Detect Darwin case semantics without ever probing inside the target tree."""

    if IS_WINDOWS:
        return False
    if sys.platform != "darwin":
        return True

    absolute = _absolute_lexical(Path(path))
    parent = absolute if absolute.is_dir() else absolute.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not parent.exists():
        return False
    try:
        device = os.stat(parent).st_dev
    except OSError:
        return False
    cached = _DARWIN_CASE_SENSITIVITY.get(device)
    if cached is not None:
        return cached

    # The system temporary directory is the only permitted probe root. It must
    # be on the same device and lexically independent from the target tree.
    # When that cannot be proved, fail closed by treating the volume as
    # case-insensitive; protection may broaden, but it can never weaken.
    temp_root = _absolute_lexical(Path(tempfile.gettempdir()))
    try:
        temp_device = os.stat(temp_root).st_dev
        independent = not _lexical_overlap(temp_root, parent)
    except OSError:
        temp_device = None
        independent = False
    if temp_device != device or not independent or not temp_root.is_dir():
        _DARWIN_CASE_SENSITIVITY[device] = False
        return False

    probe: Path | None = None
    try:
        probe = Path(tempfile.mkdtemp(prefix=".codex-case-probe-", dir=str(temp_root)))
        marker = probe / "CaseProbe"
        marker.mkdir()
        result = not (probe / "caseprobe").exists()
    except OSError:
        result = False
    finally:
        if probe is not None:
            try:
                shutil.rmtree(probe)
            except OSError:
                pass
    _DARWIN_CASE_SENSITIVITY[device] = result
    return result


_DARWIN_CASE_SENSITIVITY: dict[int, bool] = {}


def _lexical_overlap(left: Path, right: Path) -> bool:
    left_text = os.path.normpath(str(_absolute_lexical(left)))
    right_text = os.path.normpath(str(_absolute_lexical(right)))
    return (
        left_text == right_text
        or _contains(left_text, right_text)
        or _contains(right_text, left_text)
    )


def _variants(path: Path) -> set[str]:
    lexical = _absolute_lexical(path)
    path_values = {
        str(lexical),
        str(lexical.resolve(strict=False)),
        str(_long_existing_ancestor(lexical)),
    }
    if sys.platform == "darwin":
        path_values.update(
            normalized
            for value in tuple(path_values)
            for normalized in (
                unicodedata.normalize("NFC", value),
                unicodedata.normalize("NFD", value),
            )
        )
    values = set(path_values)
    case_insensitive = IS_WINDOWS or (
        sys.platform == "darwin" and not filesystem_case_sensitive(lexical)
    )
    if case_insensitive:
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
