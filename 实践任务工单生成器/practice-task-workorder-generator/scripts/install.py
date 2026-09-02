"""Install the Practice Work Order Skill with staging and rollback."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path


SKILL_NAME = "practice-task-workorder-generator"
SHARED_SCHEMA = Path("schemas/shared/practice-task-contract.schema.json")
REQUIRED = (
    "简介.md",
    "AGENTS.md",
    "通用提示词.md",
    "SKILL.md",
    "requirements.txt",
    "manifest.yaml",
    "agents/openai.yaml",
    "schemas/work-order-content.schema.json",
    "scripts/content_contract.py",
    "scripts/content_quality.py",
    "scripts/cross_artifact_quality.py",
    "scripts/check_dependencies.py",
    "scripts/generate_work_orders.py",
    "scripts/install.py",
    "scripts/install_adapters.py",
    "scripts/render_qa.py",
    "scripts/validate_output.py",
    "scripts/validate_template.py",
    "assets/templates/practice-work-order/v1.0.0/manifest.yaml",
    "assets/templates/practice-work-order/v1.0.0/template.docx",
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
        path = root / f"{SKILL_NAME}_backup_{uuid.uuid4().hex}"
        if not _exists(path):
            return path


def _shared_schema_source(source: Path) -> Path:
    candidates = (
        source / SHARED_SCHEMA,
        source.parents[1] / SHARED_SCHEMA,
        source.parents[2] / SHARED_SCHEMA,
    )
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise FileNotFoundError(
        "canonical shared Practice Task schema is missing; expected schemas/shared/practice-task-contract.schema.json"
    )


def _required_source_files(source: Path) -> list[Path]:
    missing = [source / relative for relative in REQUIRED if not (source / relative).is_file()]
    if missing:
        raise FileNotFoundError("missing required files: " + ", ".join(str(path) for path in missing))
    return [source / relative for relative in REQUIRED]


def _verify_stage(source: Path, stage: Path, shared_source: Path) -> None:
    for relative in REQUIRED:
        source_file, staged_file = source / relative, stage / relative
        if not staged_file.is_file():
            raise RuntimeError(f"staged installation is missing required file: {relative}")
        if _sha256(source_file) != _sha256(staged_file):
            raise RuntimeError(f"staged installation integrity check failed: {relative}")
    staged_shared = stage / SHARED_SCHEMA
    if not staged_shared.is_file() or _sha256(shared_source) != _sha256(staged_shared):
        raise RuntimeError("staged installation integrity check failed: canonical shared Practice Task schema")


def _remove(path: Path | None) -> None:
    if path is None or not _exists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


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
    shared_source = _shared_schema_source(source)
    if _exists(target) and not replace:
        raise FileExistsError(f"target exists: {target}; use --replace")
    if skills_dir.exists() and skills_dir.is_symlink():
        raise ValueError(f"refusing to install through symlinked directory: {skills_dir}")
    print(f"source={source}")
    print(f"target={target}")
    print(f"shared_schema={shared_source}")
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
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        shared_target = stage / SHARED_SCHEMA
        shared_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(shared_source, shared_target)
        _verify_stage(source, stage, shared_source)
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
    parser.add_argument(
        "--keep-backup",
        action="store_true",
        help="retain the previous installation after a successful replacement",
    )
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
