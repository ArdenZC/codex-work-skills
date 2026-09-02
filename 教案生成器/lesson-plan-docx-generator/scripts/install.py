from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

from path_safety import paths_overlap


SKILL_NAME = "lesson-plan-docx-generator"
SHARED_SCHEMA = Path("schemas/shared/practice-task-contract.schema.json")
REQUIRED_RELATIVE_FILES = (
    Path("SKILL.md"),
    Path("通用提示词.md"),
    Path("AGENTS.md"),
    Path("requirements.txt"),
    Path("scripts/generate_lesson_plans.py"),
    Path("scripts/content_contract.py"),
    Path("scripts/content_quality.py"),
    Path("scripts/package_common.py"),
    Path("scripts/path_safety.py"),
    Path("scripts/validate_output.py"),
    Path("scripts/validate_template.py"),
    Path("scripts/render_qa.py"),
    Path("scripts/semantic_bookmarks.py"),
    Path("scripts/bookmark_utils.py"),
    Path("scripts/check_dependencies.py"),
    Path("schemas/lesson-plan-input.schema.json"),
    Path("assets/templates/lesson-plan/v1.1.2/manifest.yaml"),
    Path("assets/templates/lesson-plan/v1.1.2/template.docx"),
)


def default_skills_dir() -> Path:
    return Path.home() / ".codex" / "skills"


def ignore_patterns(_dir: str, names: list[str]) -> set[str]:
    ignored = {"__pycache__", ".DS_Store"}
    return {name for name in names if name in ignored or name.endswith(".pyc")}


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _unique_backup_path(target_root: Path) -> Path:
    while True:
        candidate = target_root / f"{SKILL_NAME}_backup_{uuid.uuid4().hex}"
        if not _exists(candidate):
            return candidate


def _required_source_files(source: Path) -> list[Path]:
    missing = [source / relative for relative in REQUIRED_RELATIVE_FILES if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError(
            "Lesson Skill source is incomplete; missing required files: "
            + ", ".join(str(path) for path in missing)
        )
    shared_candidates = (source / SHARED_SCHEMA, source.parents[1] / SHARED_SCHEMA, source.parents[2] / SHARED_SCHEMA)
    shared = next((candidate for candidate in shared_candidates if candidate.is_file() and not candidate.is_symlink()), None)
    if shared is None:
        raise FileNotFoundError(
            "Lesson Skill source is missing canonical shared Practice Task schema: "
            "schemas/shared/practice-task-contract.schema.json"
        )
    return [*(source / relative for relative in REQUIRED_RELATIVE_FILES), shared]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_stage(source: Path, stage: Path) -> None:
    for relative in REQUIRED_RELATIVE_FILES:
        source_file, staged_file = source / relative, stage / relative
        if not staged_file.is_file():
            raise RuntimeError(f"staged installation is missing required file: {relative}")
        if _sha256(source_file) != _sha256(staged_file):
            raise RuntimeError(f"staged installation integrity check failed: {relative}")
    shared_candidates = (source / SHARED_SCHEMA, source.parents[1] / SHARED_SCHEMA, source.parents[2] / SHARED_SCHEMA)
    shared_source = next((candidate for candidate in shared_candidates if candidate.is_file() and not candidate.is_symlink()), None)
    staged_shared = stage / SHARED_SCHEMA
    if shared_source is None or not staged_shared.is_file() or _sha256(shared_source) != _sha256(staged_shared):
        raise RuntimeError("staged installation integrity check failed: canonical shared Practice Task schema")


def _preflight(source: Path, target_root: Path, target: Path, replace: bool) -> None:
    """Perform every rejecting check before the first filesystem mutation."""

    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError(f"Lesson Skill source directory not found: {source}")
    _required_source_files(source)
    if paths_overlap(source, target_root) or paths_overlap(source, target):
        raise ValueError(f"Source and installation target must not overlap: {source} / {target_root}")
    if _exists(target):
        if target.is_dir() and target.is_symlink():
            raise ValueError(f"Refusing to install through a symlink target: {target}")
        if not replace:
            raise FileExistsError(
                f"Target already exists: {target}. Re-run with --replace to back it up and replace it."
            )
    if target_root.is_symlink():
        raise ValueError(f"Refusing to install through a symlink installation root: {target_root}")
    if target_root.exists() and not target_root.is_dir():
        raise NotADirectoryError(f"Installation root is not a directory: {target_root}")


def _remove_stage(stage: Path | None) -> str | None:
    if stage is None:
        return None
    try:
        if stage.is_symlink():
            stage.unlink()
        elif stage.is_dir():
            shutil.rmtree(stage)
        elif stage.exists():
            stage.unlink()
    except Exception as exc:  # pragma: no cover - filesystem failures vary by platform
        return f"cleanup failed for staging directory: {exc}; residual path: {stage}"
    return None


def install(source: Path, target_root: Path, *, replace: bool = False, dry_run: bool = False) -> Path:
    source = _absolute(source)
    target_root = _absolute(target_root)
    target = target_root / SKILL_NAME
    _preflight(source, target_root, target, replace)
    backup = _unique_backup_path(target_root) if _exists(target) else None
    print(f"source={source}")
    print(f"target={target}")
    if backup is not None:
        print(f"backup={backup}")
    if dry_run:
        print("dry-run=yes (no filesystem mutation)")
        return target

    target_root.mkdir(parents=True, exist_ok=True)
    stage: Path | None = None
    moved_backup = False
    operation_error: BaseException | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=str(target_root)))
        stage.rmdir()
        shutil.copytree(source, stage, ignore=ignore_patterns, symlinks=False)
        shared_candidates = (source / SHARED_SCHEMA, source.parents[1] / SHARED_SCHEMA, source.parents[2] / SHARED_SCHEMA)
        shared_source = next((candidate for candidate in shared_candidates if candidate.is_file() and not candidate.is_symlink()), None)
        if shared_source is None:
            raise FileNotFoundError("canonical shared Practice Task schema is unavailable")
        shared_target = stage / SHARED_SCHEMA
        shared_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared_source, shared_target)
        _verify_stage(source, stage)
        if backup is not None:
            os.replace(str(target), str(backup))
            moved_backup = True
        try:
            os.replace(str(stage), str(target))
            stage = None
        except Exception as commit_error:
            rollback_error: Exception | None = None
            if moved_backup:
                try:
                    if _exists(target):
                        if target.is_dir() and not target.is_symlink():
                            shutil.rmtree(target)
                        else:
                            target.unlink()
                    os.replace(str(backup), str(target))
                    moved_backup = False
                except Exception as exc:  # pragma: no cover - filesystem-specific
                    rollback_error = exc
            detail = f"installation commit failed: {commit_error}"
            detail += (
                f"; rollback failed: {rollback_error}; backup retained at {backup}"
                if rollback_error is not None
                else "; previous installation restored"
            )
            raise RuntimeError(detail) from commit_error
        print(f"installed={target}")
        return target
    except BaseException as exc:
        operation_error = exc
        raise
    finally:
        try:
            cleanup_error = _remove_stage(stage)
        except Exception as exc:  # pragma: no cover - defensive for injected cleanup failures
            cleanup_error = f"cleanup failed for staging directory: {exc}; residual path: {stage}"
        if cleanup_error:
            print(f"WARNING: {cleanup_error}", file=sys.stderr)
            if operation_error is not None:
                operation_error.add_note(cleanup_error)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install lesson-plan-docx-generator into the local Codex skills directory.")
    parser.add_argument("--skills-dir", default=str(default_skills_dir()), help="Target Codex skills directory. Defaults to ~/.codex/skills.")
    parser.add_argument("--replace", action="store_true", help="Back up and replace an existing installed copy.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned paths without copying files.")
    args = parser.parse_args()

    source = Path(__file__).resolve().parents[1]
    install(source, Path(args.skills_dir), replace=args.replace, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
