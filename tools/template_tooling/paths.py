"""Path and containment helpers with symlink-aware comparisons."""

from __future__ import annotations

import os
import hashlib
import shutil
import stat
import unicodedata
import uuid
from pathlib import Path

from .models import TemplateToolError


WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


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


def validate_windows_component(value: str, *, label: str) -> str:
    """Validate one portable filename component, including Windows rules."""
    if not isinstance(value, str) or not value:
        raise TemplateToolError(f"{label} must not be empty")
    if value in {".", ".."} or any(char in value for char in '<>:"/\\|?*'):
        raise TemplateToolError(f"{label} contains an unsafe filename component: {value!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise TemplateToolError(f"{label} contains a control character: {value!r}")
    if value.endswith((".", " ")):
        raise TemplateToolError(f"{label} may not end with a dot or space: {value!r}")
    stem = value.split(".", 1)[0].casefold()
    if stem in WINDOWS_RESERVED_NAMES:
        raise TemplateToolError(f"{label} uses a Windows reserved name: {value!r}")
    return value


def _assert_copyable(path: Path) -> None:
    if path.is_symlink():
        raise TemplateToolError(f"symlink is not allowed: {path}")
    mode = path.stat(follow_symlinks=False).st_mode
    if not stat.S_ISREG(mode):
        raise TemplateToolError(f"only regular files are allowed: {path}")


def copy_tree_no_symlinks(source: Path, destination: Path) -> list[Path]:
    """Copy a directory without following symlinks or accepting special files."""
    if source.is_symlink() or not source.is_dir():
        raise TemplateToolError(f"package root must be a real directory: {source}")
    destination.mkdir(parents=True, exist_ok=False)
    created: list[Path] = [destination]
    entries = sorted(
        source.rglob("*"),
        key=lambda item: (
            unicodedata.normalize("NFC", item.relative_to(source).as_posix()).casefold(),
            unicodedata.normalize("NFC", item.relative_to(source).as_posix()),
        ),
    )
    for source_path in entries:
        relative = source_path.relative_to(source)
        target = destination / relative
        if source_path.is_symlink():
            raise TemplateToolError(f"symlink is not allowed: {source_path}")
        if source_path.is_dir():
            target.mkdir()
            created.append(target)
            continue
        _assert_copyable(source_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        created.append(target)
    return created


def tree_fingerprints(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise TemplateToolError(f"symlink is not allowed in package comparison: {path}")
        if path.is_dir():
            continue
        _assert_copyable(path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[path.relative_to(root).as_posix()] = digest.hexdigest().upper()
    return result


def remove_path_or_raise(path: Path) -> None:
    """Remove a path and prove that the removal completed."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)
    if path.exists() or path.is_symlink():
        raise TemplateToolError(f"failed to remove path: {path}")


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write a new text file through a sibling temporary file and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("w", encoding=encoding, newline="") as stream:
            stream.write(text)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            remove_path_or_raise(temporary)
