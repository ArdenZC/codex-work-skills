"""Git-index-backed trust checks for executable template tooling."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess

from .models import TemplateToolError


_IGNORED_SCRIPT_PARTS = {"__pycache__"}
_IGNORED_SCRIPT_SUFFIXES = {".pyc"}
_IGNORED_SCRIPT_PREFIXES = ("~$",)


def _normalise_index_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TemplateToolError(f"Git index contains an unsafe path: {value!r}")
    result = path.as_posix()
    return result.casefold() if os.name == "nt" else result


def _is_ignored_script_file(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    return (
        "__pycache__" in parts
        or path.suffix.casefold() in _IGNORED_SCRIPT_SUFFIXES
        or path.name.casefold().startswith(_IGNORED_SCRIPT_PREFIXES)
    )


@dataclass(frozen=True)
class GitTrustIndex:
    """The cached set of paths tracked by the repository's Git index."""

    repo_root: Path
    tracked_paths: frozenset[str]

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "GitTrustIndex":
        requested = repo_root.expanduser().resolve()
        try:
            top_level = subprocess.run(
                ["git", "-C", str(requested), "rev-parse", "--show-toplevel"],
                capture_output=True,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise TemplateToolError(
                "Repository Git index is required to establish validator trust."
            ) from exc
        if top_level.returncode != 0:
            raise TemplateToolError(
                "Repository Git index is required to establish validator trust."
            )
        actual = Path(top_level.stdout.strip()).expanduser().resolve()
        if actual != requested:
            raise TemplateToolError(
                f"Git repository root does not match the requested repo-root: {requested} != {actual}"
            )
        try:
            indexed = subprocess.run(
                ["git", "-C", str(requested), "ls-files", "--cached", "-z"],
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            raise TemplateToolError(
                "Repository Git index is required to establish validator trust."
            ) from exc
        if indexed.returncode != 0:
            raise TemplateToolError(
                "Repository Git index is required to establish validator trust."
            )
        try:
            raw_paths = indexed.stdout.decode("utf-8", errors="surrogateescape")
        except AttributeError as exc:
            raise TemplateToolError(
                "Repository Git index is required to establish validator trust."
            ) from exc
        tracked = frozenset(
            _normalise_index_path(value)
            for value in raw_paths.split("\0")
            if value
        )
        return cls(repo_root=requested, tracked_paths=tracked)

    def _relative_key(self, path: Path) -> str | None:
        resolved = path.expanduser().resolve(strict=False)
        try:
            relative = resolved.relative_to(self.repo_root)
        except ValueError:
            return None
        return _normalise_index_path(relative.as_posix())

    def _lexical_path(self, path: Path) -> Path:
        absolute = Path(os.path.abspath(os.fspath(path.expanduser())))
        try:
            relative = absolute.relative_to(self.repo_root)
        except ValueError as exc:
            raise TemplateToolError(f"path is outside the repository Git root: {path}") from exc
        current = self.repo_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise TemplateToolError(f"path contains a symlinked component: {current}")
        return absolute

    def is_tracked(self, path: Path) -> bool:
        key = self._relative_key(path)
        return key is not None and key in self.tracked_paths

    def require_tracked_regular_file(self, path: Path, *, label: str) -> Path:
        lexical = self._lexical_path(path)
        if lexical.is_symlink():
            raise TemplateToolError(f"{label} is not a trusted regular file: {lexical}")
        try:
            mode = lexical.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise TemplateToolError(f"{label} is not a trusted regular file: {lexical}") from exc
        if not stat.S_ISREG(mode):
            raise TemplateToolError(f"{label} is not a trusted regular file: {lexical}")
        if not self.is_tracked(lexical):
            raise TemplateToolError(f"{label} is not tracked by the repository Git index: {lexical}")
        return lexical.resolve(strict=False)

    def tracked_files_under(self, directory: Path) -> list[Path]:
        directory = directory.expanduser().resolve(strict=False)
        directory_key = self._relative_key(directory)
        if directory_key is None:
            raise TemplateToolError(f"scripts directory is outside the repository Git root: {directory}")
        prefix = directory_key + "/"
        candidates: list[Path] = []
        for key in sorted(self.tracked_paths):
            if not key.startswith(prefix):
                continue
            relative = PurePosixPath(key)
            candidate = self.repo_root.joinpath(*relative.parts)
            candidates.append(candidate)
        return candidates


def trusted_script_files(owner: Path, trust_index: GitTrustIndex) -> list[Path]:
    """Validate and list only Git-tracked regular files available to a validator."""
    scripts = owner / "scripts"
    if scripts.is_symlink() or not scripts.is_dir():
        raise TemplateToolError(f"owner validator scripts directory was not found: {scripts}")

    # Scan the live directory first so an untracked helper or symlink is rejected
    # before any validator process can import it.
    for path in sorted(scripts.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise TemplateToolError(f"Owner scripts directory contains a symlink: {path}")
        if path.is_dir() or _is_ignored_script_file(path):
            continue
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise TemplateToolError(f"cannot inspect owner scripts file: {path}") from exc
        if not stat.S_ISREG(mode):
            raise TemplateToolError(f"Owner scripts directory contains a special file: {path}")
        if not trust_index.is_tracked(path):
            raise TemplateToolError(
                f"Owner scripts directory contains an untrusted executable or support file: {path}"
            )

    trusted: list[Path] = []
    for path in trust_index.tracked_files_under(scripts):
        if _is_ignored_script_file(path):
            continue
        trusted.append(trust_index.require_tracked_regular_file(path, label="Owner scripts file"))
    return sorted(set(trusted), key=lambda item: item.as_posix().casefold())
