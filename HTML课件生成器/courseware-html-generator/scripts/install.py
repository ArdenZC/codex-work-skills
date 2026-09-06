"""Install the HTML Courseware Skill with staging, integrity checks, and rollback."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


SKILL_NAME = "courseware-html-generator"
REQUIRED = (
    "简介.md",
    "AGENTS.md",
    "通用提示词.md",
    "SKILL.md",
    "CLAUDE.md",
    "GEMINI.md",
    "CONVENTIONS.md",
    "requirements.txt",
    "README.md",
    "manifest.yaml",
    "agents/openai.yaml",
    "docs/content-contract-v1.md",
    "schemas/courseware-content.schema.json",
    "examples/data-structures.example.json",
    "examples/uml.example.json",
    "scripts/content_contract.py",
    "scripts/render_courseware.py",
    "scripts/validate_courseware.py",
    "scripts/install.py",
    "scripts/install_adapters.py",
    "tests/test_courseware.py",
    "tests/browser_smoke.mjs",
)


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_path(root: Path) -> Path:
    while True:
        candidate = root / f"{SKILL_NAME}_backup_{uuid.uuid4().hex}"
        if not _exists(candidate):
            return candidate


def _remove(path: Path | None) -> None:
    if path is None or not _exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _required_source_files(source: Path) -> list[Path]:
    missing = [source / relative for relative in REQUIRED if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError("missing required files: " + ", ".join(str(path) for path in missing))
    return [source / relative for relative in REQUIRED]


def _verify_stage(source: Path, stage: Path) -> None:
    for relative in REQUIRED:
        source_file = source / relative
        staged_file = stage / relative
        if not staged_file.is_file():
            raise RuntimeError(f"staged installation is missing required file: {relative}")
        if _sha256(source_file) != _sha256(staged_file):
            raise RuntimeError(f"staged installation integrity check failed: {relative}")


def install(
    source: Path,
    skills_dir: Path,
    *,
    replace: bool = False,
    dry_run: bool = False,
    keep_backup: bool = False,
) -> Path:
    source = source.expanduser().resolve()
    skills_dir = skills_dir.expanduser().resolve()
    target = skills_dir / SKILL_NAME
    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError(source)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("source and target must not overlap")
    _required_source_files(source)
    if _exists(target) and not replace:
        raise FileExistsError(f"target exists: {target}; use --replace")
    if _exists(skills_dir) and skills_dir.is_symlink():
        raise ValueError(f"refusing to install through symlinked directory: {skills_dir}")
    print(f"source={source}")
    print(f"target={target}")
    if dry_run:
        print("dry-run=yes (no filesystem mutation)")
        return target

    skills_dir.mkdir(parents=True, exist_ok=True)
    stage: Path | None = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=str(skills_dir)))
    stage.rmdir()
    backup = _backup_path(skills_dir) if _exists(target) else None
    moved_backup = False
    operation_error: BaseException | None = None
    try:
        shutil.copytree(
            source,
            stage,
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
        )
        _verify_stage(source, stage)
        if backup is not None:
            os.replace(str(target), str(backup))
            moved_backup = True
        try:
            os.replace(str(stage), str(target))
            stage = None
        except Exception as commit_error:
            if moved_backup and not _exists(target):
                os.replace(str(backup), str(target))
                moved_backup = False
            raise RuntimeError(f"installation commit failed; previous installation restored: {commit_error}") from commit_error
        print(f"installed={target}")
        if backup is not None and not keep_backup:
            _remove(backup)
        return target
    except BaseException as exc:
        operation_error = exc
        raise
    finally:
        try:
            _remove(stage)
        except Exception as cleanup_error:  # pragma: no cover - filesystem-specific
            message = f"staging cleanup failed; residual path: {stage}: {cleanup_error}"
            print("WARNING: " + message, file=sys.stderr)
            if operation_error is not None:
                operation_error.add_note(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--keep-backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    install(
        Path(__file__).resolve().parents[1],
        args.skills_dir,
        replace=args.replace,
        dry_run=args.dry_run,
        keep_backup=args.keep_backup,
    )


if __name__ == "__main__":
    main()
