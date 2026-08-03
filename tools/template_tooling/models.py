"""Shared data structures and errors for template package tooling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOOL_VERSION = "0.1.0"
METADATA_SCHEMA_VERSION = "1.0"


class TemplateToolError(Exception):
    """An expected, user-facing tooling error."""


@dataclass(frozen=True, order=True)
class SemVer:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)


@dataclass
class TemplatePackage:
    template_id: str
    version: str
    format: str
    package_dir: Path
    template_path: Path
    manifest_path: Path
    fingerprint: str
    validator: Path | None
    is_default: bool
    is_canonical: bool
    manifest: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def semver(self) -> SemVer:
        return parse_semver(self.version)

    def to_dict(self, root: Path | None = None) -> dict[str, Any]:
        def display_path(path: Path | None) -> str | None:
            if path is None:
                return None
            resolved = path.resolve(strict=False)
            if root is None:
                return resolved.name
            try:
                return resolved.relative_to(root.resolve()).as_posix()
            except ValueError:
                return f"<external>/{resolved.name}"

        return {
            "id": self.template_id,
            "version": self.version,
            "format": self.format,
            "package": display_path(self.package_dir) if root is not None else self.package_dir.name,
            "template": display_path(self.template_path) if root is not None else self.template_path.name,
            "manifest": display_path(self.manifest_path) if root is not None else self.manifest_path.name,
            "fingerprint": self.fingerprint,
            "validator": display_path(self.validator) if root is not None else (self.validator.name if self.validator else None),
            "owner_skill": (
                display_path(self.validator.parent.parent)
                if self.validator is not None and root is not None
                else (self.validator.parent.parent.name if self.validator else None)
            ),
            "is_default": self.is_default,
            "is_canonical": self.is_canonical,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def parse_semver(value: Any) -> SemVer:
    if not isinstance(value, str):
        raise TemplateToolError("version must be a strict ASCII MAJOR.MINOR.PATCH string")
    if not value or any(char not in "0123456789." for char in value):
        raise TemplateToolError(f"invalid semantic version: {value!r}")
    parts = value.split(".")
    if len(parts) != 3 or any(not part or (len(part) > 1 and part.startswith("0")) for part in parts):
        raise TemplateToolError(f"invalid semantic version: {value!r}")
    try:
        numbers = tuple(int(part, 10) for part in parts)
    except ValueError as exc:
        raise TemplateToolError(f"invalid semantic version: {value!r}") from exc
    if any(number < 0 for number in numbers):
        raise TemplateToolError(f"invalid semantic version: {value!r}")
    return SemVer(*numbers)


def package_dir_matches_version(name: str, version: str) -> bool:
    """Accept the repository's existing ``v1.0.0`` directory convention."""
    return name == version or name == f"v{version}"
