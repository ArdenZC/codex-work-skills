"""Path and containment helpers with symlink-aware comparisons."""

from __future__ import annotations

import os
from pathlib import Path

from .models import TemplateToolError


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_path(value: str | os.PathLike[str], base: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    return path.resolve(strict=False)


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise TemplateToolError(f"path is outside root: {path}") from exc


def display_path(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return f"<external>/{resolved.name}"


def is_within(path: Path, root: Path, *, allow_equal: bool = True) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return allow_equal or path.resolve() != root.resolve()


def paths_overlap(left: Path, right: Path) -> bool:
    left_resolved = left.resolve(strict=False)
    right_resolved = right.resolve(strict=False)
    return (
        left_resolved == right_resolved
        or is_within(left_resolved, right_resolved)
        or is_within(right_resolved, left_resolved)
    )


def require_no_overlap(path: Path, protected: list[Path], *, label: str) -> None:
    for other in protected:
        if paths_overlap(path, other):
            raise TemplateToolError(f"{label} overlaps protected path: {path} <> {other}")


def ensure_no_parent_escape(path: Path, root: Path, *, label: str) -> None:
    if not is_within(path, root):
        raise TemplateToolError(f"{label} escapes its package root: {path}")


def safe_relative(value: str, *, label: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise TemplateToolError(f"{label} must be a relative path without '..': {value!r}")
    if not value or candidate == Path("."):
        raise TemplateToolError(f"{label} must not be empty")
    return candidate
